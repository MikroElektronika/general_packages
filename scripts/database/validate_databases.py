#!/usr/bin/env python3
"""Fast validation for all three NECTO SQLite databases."""

from pathlib import Path
import sys

from db_common import current_database_paths, connect, integrity_check, user_tables, primary_key_columns


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    failed = False
    paths = current_database_paths(root)
    for channel, path in paths.items():
        integrity = integrity_check(path)
        print(f"[{channel}] {path}: integrity_check={integrity}")
        if integrity != "ok":
            failed = True
        with connect(path) as con:
            tables = user_tables(con)
            print(f"[{channel}] tables={len(tables)}")
            for table in tables:
                if not primary_key_columns(con, table):
                    print(f"ERROR: [{channel}] table {table} has no PRIMARY KEY")
                    failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
