#!/usr/bin/env python3
"""Send NECTO database-change reports to a Mattermost incoming webhook.

For JSON database reports, each changed table is rendered as a Mattermost
message attachment. Mattermost collapses long attachment text behind its
native "Show More" control, which keeps large SDK mapping updates readable.

The actual HTTP POST uses curl rather than urllib. The general_packages repo's
existing Mattermost workflow already uses curl successfully, and this also
makes proxy/WAF errors easier to diagnose with --fail-with-body.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def row_id(row: Mapping[str, Any], pk: Sequence[str]) -> str:
    keys = list(pk) if pk else list(row)[:3]
    return ", ".join(f"{c}={compact_json(row.get(c))}" for c in keys)


def split_text(text: str, limit: int) -> List[str]:
    """Legacy Markdown mode splitter."""
    if len(text) <= limit:
        return [text]
    chunks: List[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            if current:
                chunks.append(current.rstrip())
                current = ""
            for i in range(0, len(line), limit):
                chunks.append(line[i:i + limit].rstrip())
            continue
        if len(current) + len(line) > limit and current:
            chunks.append(current.rstrip())
            current = ""
        current += line
    if current.strip():
        chunks.append(current.rstrip())
    return chunks


def curl_post(webhook: str, payload: Dict[str, Any]) -> None:
    """POST JSON with curl and include any HTTP error body in failures."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="mattermost-", suffix=".json", delete=False) as f:
            f.write(data)
            tmp_path = f.name

        proc = subprocess.run(
            [
                "curl",
                "--fail-with-body",
                "--silent",
                "--show-error",
                "-X", "POST",
                "-H", "Content-Type: application/json",
                "--data-binary", f"@{tmp_path}",
                webhook,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            details = "\n".join(
                part for part in (
                    f"curl exit code: {proc.returncode}",
                    f"Mattermost response: {proc.stdout.strip()}" if proc.stdout.strip() else "",
                    f"curl error: {proc.stderr.strip()}" if proc.stderr.strip() else "",
                ) if part
            )
            raise RuntimeError(f"Mattermost webhook POST failed.\n{details}")
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def common_header(title: str) -> str:
    repo = os.getenv("GITHUB_REPOSITORY", "")
    sha = os.getenv("GITHUB_SHA", "")
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    actor = os.getenv("GITHUB_ACTOR", "unknown")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    commit_message = os.getenv("DB_COMMIT_MESSAGE", "").strip()
    commit_url = f"{server}/{repo}/commit/{sha}" if repo and sha else ""
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else ""
    short_sha = sha[:8] if sha else "unknown"

    lines = [f"## 🗄️ {title}", f"**Actor:** `{actor}`"]
    if commit_url:
        lines.append(f"**Commit:** [{short_sha}]({commit_url})")
    if commit_message:
        lines.append(f"**Message:** {commit_message.splitlines()[0]}")
    if run_url:
        lines.append(f"**Full report:** [GitHub Actions run]({run_url})")
    return "\n".join(lines)


def limited(items: List[Any], detail_limit: int) -> tuple[List[Any], int]:
    if detail_limit <= 0:
        return items, 0
    return items[:detail_limit], max(0, len(items) - detail_limit)


def table_attachment(table: Mapping[str, Any], channel: str, detail_limit: int, run_url: str) -> Dict[str, Any]:
    added = len(table.get("added", []))
    removed = len(table.get("removed", []))
    updated = len(table.get("updated", []))
    name = str(table["table"])
    summary = f"{channel.upper()} · {name}: +{added} / -{removed} / ~{updated}"

    lines = [
        f"**Rows:** {table.get('old_count', '?')} → {table.get('new_count', '?')}",
    ]
    schema_status = table.get("schema_status", "unchanged")
    if schema_status != "unchanged":
        lines.append(f"**Schema:** {schema_status}")
    if table.get("row_diff_skipped"):
        lines.append(f"**Row diff skipped:** `{table['row_diff_skipped']}`")

    for label, symbol, key in (("Added", "+", "added"), ("Removed", "-", "removed")):
        rows = list(table.get(key, []))
        if not rows:
            continue
        shown, more = limited(rows, detail_limit)
        lines += ["", f"**{label} ({len(rows)})**"]
        for row in shown:
            lines.append(f"- `{symbol}` {row_id(row, table.get('pk', []))}")
        if more:
            lines.append(f"- … **{more} more** row(s) in the full report")

    updates = list(table.get("updated", []))
    if updates:
        shown, more = limited(updates, detail_limit)
        lines += ["", f"**Updated ({len(updates)})**"]
        for update in shown:
            key_text = ", ".join(
                f"{k}={compact_json(v)}" for k, v in update.get("key", {}).items()
            )
            changes = "; ".join(
                f"{column}: {compact_json(values.get('old'))} → {compact_json(values.get('new'))}"
                for column, values in update.get("changes", {}).items()
            )
            lines.append(f"- `~` {key_text} — {changes}")
        if more:
            lines.append(f"- … **{more} more** updated row(s) in the full report")

    if run_url:
        lines += ["", f"[Open complete workflow report]({run_url})"]

    return {
        "fallback": summary,
        "title": f"{name}  ·  +{added}  -{removed}  ~{updated}",
        "text": "\n".join(lines),
    }


def payload_size(payload: Dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def build_json_payloads(
    report: Mapping[str, Any],
    title: str,
    detail_limit: int,
    payload_limit: int,
    prefix_text: str,
) -> List[Dict[str, Any]]:
    header = common_header(title)
    if prefix_text.strip():
        header += "\n\n" + prefix_text.strip()

    repo = os.getenv("GITHUB_REPOSITORY", "")
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else ""

    all_payloads: List[Dict[str, Any]] = []
    for db in report.get("databases", []):
        if not db.get("changed"):
            continue
        channel = str(db.get("channel", "database")).upper()
        attachments = [
            table_attachment(table, channel, detail_limit, run_url)
            for table in db.get("tables", [])
        ]
        if not attachments:
            continue

        base_text = f"{header}\n\n### {channel}\n`{db.get('path', '')}`"
        current: List[Dict[str, Any]] = []
        for attachment in attachments:
            candidate = {"text": base_text, "attachments": current + [attachment]}
            if current and payload_size(candidate) > payload_limit:
                all_payloads.append({"text": base_text, "attachments": current})
                current = [attachment]
            else:
                current.append(attachment)
        if current:
            all_payloads.append({"text": base_text, "attachments": current})

    return all_payloads


def write_dry_run(payloads: Iterable[Dict[str, Any]], directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    count = 0
    for count, payload in enumerate(payloads, start=1):
        (directory / f"mattermost-payload-{count:02d}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--json-report", type=Path, help="database-diff.json from db_diff.py")
    mode.add_argument("--report", type=Path, help="legacy Markdown report")
    parser.add_argument("--prefix-report", type=Path, help="optional short warning/prefix Markdown")
    parser.add_argument("--webhook-env", default="MATTERMOST_WEBHOOK_URL")
    parser.add_argument("--detail-limit", type=int, default=20,
                        help="maximum row details per Added/Removed/Updated section for each table")
    parser.add_argument("--payload-limit", type=int, default=13000,
                        help="soft JSON payload size limit; attachments are split across posts")
    parser.add_argument("--chunk-size", type=int, default=12000, help="legacy Markdown mode only")
    parser.add_argument("--title", default="NECTO database update")
    parser.add_argument("--dry-run-dir", type=Path,
                        help="write payload JSON files here instead of calling Mattermost")
    args = parser.parse_args()

    prefix_text = ""
    if args.prefix_report and args.prefix_report.exists():
        prefix_text = args.prefix_report.read_text(encoding="utf-8")

    if args.json_report:
        report = json.loads(args.json_report.read_text(encoding="utf-8"))
        payloads = build_json_payloads(
            report,
            title=args.title,
            detail_limit=args.detail_limit,
            payload_limit=max(3000, args.payload_limit),
            prefix_text=prefix_text,
        )
    else:
        header = common_header(args.title) + "\n\n"
        if prefix_text.strip():
            header += prefix_text.strip() + "\n\n"
        report_text = args.report.read_text(encoding="utf-8")
        chunks = split_text(report_text, max(1000, args.chunk_size - len(header) - 80))
        payloads = []
        for index, chunk in enumerate(chunks, start=1):
            text = header + chunk if index == 1 else f"## 🗄️ {args.title} — continued ({index}/{len(chunks)})\n\n{chunk}"
            payloads.append({"text": text})

    if not payloads:
        print("No changed database tables to send to Mattermost.")
        return 0

    if args.dry_run_dir:
        count = write_dry_run(payloads, args.dry_run_dir)
        print(f"Wrote {count} Mattermost payload(s) to {args.dry_run_dir}")
        return 0

    webhook = os.getenv(args.webhook_env, "").strip()
    if not webhook:
        raise RuntimeError(f"Environment variable {args.webhook_env} is empty")

    for payload in payloads:
        curl_post(webhook, payload)
    print(f"Sent {len(payloads)} Mattermost message(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
