#!/usr/bin/env python3
"""Apply a targeted Devices-table update to one canonical channel database."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sqlite3
import urllib.request
from datetime import datetime
from pathlib import Path

from db_common import integrity_check


def resolve_spreadsheet_regex(sheet_id: str) -> str:
    if not sheet_id:
        raise ValueError("A release spreadsheet id is required for Spreadsheet Regex")
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    with urllib.request.urlopen(url) as response:
        text = response.read().decode("utf-8-sig")

    today = datetime.now().strftime("%d.%m.%Y")
    current_regex = ""
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 9 or not row or row[0] in ("", "Product name"):
            continue
        if "mikroSDK" in row[0] and row[8].strip():
            current_regex = row[8].strip()
        if row[3].strip() == today and current_regex:
            return current_regex
    raise ValueError(f"No mikroSDK database regex was found for {today}")


def add_ai_sdk_marker(value: str | None) -> str:
    try:
        data = json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid Devices.sdk_config JSON: {value!r}") from exc
    data["AI_GENERATED_SDK"] = "True"
    return json.dumps(data, separators=(",", ":"))


def update_devices(
    database: Path,
    *,
    action: str,
    regex: str,
    delete_device: bool,
    xc8_specific: bool,
    ai_sdk: bool,
) -> int:
    pattern = re.compile(regex)
    con = sqlite3.connect(database)
    con.row_factory = sqlite3.Row
    con.create_function(
        "REGEXP",
        2,
        lambda expression, value: value is not None and pattern.search(str(value)) is not None,
    )
    try:
        rows = con.execute(
            "SELECT uid, sdk_config FROM Devices WHERE uid REGEXP ? ORDER BY uid",
            (regex,),
        ).fetchall()
        print(f"Matched {len(rows)} device(s) with regex {regex!r}")

        if action == "set-sdk-support":
            con.execute("UPDATE Devices SET sdk_support=1 WHERE uid REGEXP ?", (regex,))
            if xc8_specific:
                con.execute(
                    "UPDATE Devices SET necto_config=? WHERE uid REGEXP ?",
                    ('{"XC8_SUPPORTED":"TRUE"}', regex),
                )
            if ai_sdk:
                for row in rows:
                    con.execute(
                        "UPDATE Devices SET sdk_config=? WHERE uid=?",
                        (add_ai_sdk_marker(row["sdk_config"]), row["uid"]),
                    )
        elif delete_device:
            con.execute("DELETE FROM Devices WHERE uid REGEXP ?", (regex,))
        else:
            con.execute("UPDATE Devices SET sdk_support=0 WHERE uid REGEXP ?", (regex,))

        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument(
        "--action", choices=("set-sdk-support", "remove-devices"), required=True
    )
    parser.add_argument("--regex")
    parser.add_argument("--spreadsheet-link", default="")
    parser.add_argument("--delete-device", action="store_true")
    parser.add_argument("--xc8-specific", action="store_true")
    parser.add_argument("--ai-sdk", action="store_true")
    args = parser.parse_args()

    database = args.database.resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    regex = args.regex or resolve_spreadsheet_regex(args.spreadsheet_link)
    update_devices(
        database,
        action=args.action,
        regex=regex,
        delete_device=args.delete_device,
        xc8_specific=args.xc8_specific,
        ai_sdk=args.ai_sdk,
    )
    result = integrity_check(database)
    if result != "ok":
        raise RuntimeError(f"Updated database failed PRAGMA integrity_check: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
