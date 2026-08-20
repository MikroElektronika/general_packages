#!/usr/bin/env python3
"""Send a compact NECTO database-change summary to Mattermost.

The Mattermost message intentionally contains only:
- actor / commit metadata,
- a link to the GitHub Actions run,
- the names of changed tables grouped by database channel.

Row-level details remain in the GitHub PR comment / Actions artifacts.
HTTP POST uses curl to match the existing general_packages Mattermost workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping


def split_text(text: str, limit: int) -> List[str]:
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
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
        lines.append(f"**Details:** [Open GitHub Actions report]({run_url})")
    return "\n".join(lines)


def changed_table_names(db: Mapping[str, Any]) -> List[str]:
    names: List[str] = []
    for table in db.get("tables", []):
        # db_diff.py only emits changed tables today, but keep this defensive
        # check in case the JSON format later includes unchanged tables too.
        changed = (
            bool(table.get("added"))
            or bool(table.get("removed"))
            or bool(table.get("updated"))
            or table.get("schema_status", "unchanged") != "unchanged"
            or bool(table.get("row_diff_skipped"))
            or table.get("old_count") != table.get("new_count")
        )
        if changed:
            names.append(str(table.get("table", "unknown")))
    return names


def build_summary(report: Mapping[str, Any], title: str, prefix_text: str) -> str:
    lines = [common_header(title)]

    if prefix_text.strip():
        lines += ["", prefix_text.strip()]

    found_any = False
    for db in report.get("databases", []):
        if not db.get("changed"):
            continue

        tables = changed_table_names(db)
        if not tables:
            continue

        found_any = True
        channel = str(db.get("channel", "database")).upper()
        lines += ["", f"### {channel}"]
        lines.extend(f"- `{table}`" for table in tables)

    if not found_any:
        return ""

    return "\n".join(lines)


def write_dry_run(payloads: List[Dict[str, Any]], directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    for index, payload in enumerate(payloads, start=1):
        (directory / f"mattermost-payload-{index:02d}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return len(payloads)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-report", type=Path, required=True,
                        help="database-diff.json generated by db_diff.py")
    parser.add_argument("--prefix-report", type=Path,
                        help="optional short warning/prefix Markdown")
    parser.add_argument("--webhook-env", default="MATTERMOST_WEBHOOK_URL")
    parser.add_argument("--title", default="NECTO database update")
    parser.add_argument("--chunk-size", type=int, default=12000,
                        help="maximum text size per Mattermost post")
    parser.add_argument("--dry-run-dir", type=Path,
                        help="write payload JSON files here instead of posting")
    args = parser.parse_args()

    prefix_text = ""
    if args.prefix_report and args.prefix_report.exists():
        prefix_text = args.prefix_report.read_text(encoding="utf-8")

    report = json.loads(args.json_report.read_text(encoding="utf-8"))
    text = build_summary(report, args.title, prefix_text)
    if not text:
        print("No changed database tables to send to Mattermost.")
        return 0

    chunks = split_text(text, max(1000, args.chunk_size))
    payloads = [{"text": chunk} for chunk in chunks]

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
