#!/usr/bin/env python3
"""Send a Markdown database-change report to a Mattermost incoming webhook."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path
from typing import List


def split_text(text: str, limit: int) -> List[str]:
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


def post(webhook: str, text: str) -> None:
    payload = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"Mattermost webhook returned HTTP {response.status}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--webhook-env", default="MATTERMOST_WEBHOOK_URL")
    parser.add_argument("--chunk-size", type=int, default=12000)
    parser.add_argument("--title", default="NECTO database update")
    args = parser.parse_args()

    webhook = os.getenv(args.webhook_env, "").strip()
    if not webhook:
        raise RuntimeError(f"Environment variable {args.webhook_env} is empty")

    repo = os.getenv("GITHUB_REPOSITORY", "")
    sha = os.getenv("GITHUB_SHA", "")
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    actor = os.getenv("GITHUB_ACTOR", "unknown")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    commit_message = os.getenv("DB_COMMIT_MESSAGE", "").strip()
    commit_url = f"{server}/{repo}/commit/{sha}" if repo and sha else ""
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else ""
    short_sha = sha[:8] if sha else "unknown"

    header = [f"## 🗄️ {args.title}", f"**Actor:** `{actor}`"]
    if commit_url:
        header.append(f"**Commit:** [{short_sha}]({commit_url})")
    if commit_message:
        first_line = commit_message.splitlines()[0]
        header.append(f"**Message:** {first_line}")
    if run_url:
        header.append(f"**Full uncapped report:** [GitHub Actions run]({run_url})")
    header_text = "\n".join(header) + "\n\n"

    report = args.report.read_text(encoding="utf-8")
    chunks = split_text(report, max(1000, args.chunk_size - len(header_text) - 80))
    for index, chunk in enumerate(chunks, start=1):
        prefix = header_text if index == 1 else f"## 🗄️ {args.title} — continued ({index}/{len(chunks)})\n\n"
        post(webhook, prefix + chunk)
    print(f"Sent {len(chunks)} Mattermost message(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
