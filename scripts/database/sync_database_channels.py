#!/usr/bin/env python3
"""
Safely propagate NECTO DB changes:

    Live -> Development -> Experimental

Uses SQLite-native joins to find only changed rows, then performs a field-level
three-way merge:
- unrelated pending downstream fields are preserved;
- already-propagated values are accepted;
- conflicting edits to the same field fail loudly.

Schema changes are intentionally NOT auto-propagated. Apply the same schema
change explicitly to downstream channel DBs in the PR and review it separately.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from db_common import DB_PATHS, current_database_paths, materialize_git_databases, qi, sha256_file


class MergeConflict(RuntimeError):
    pass


def attach(con: sqlite3.Connection, path: Path, alias: str) -> None:
    con.execute(f"ATTACH DATABASE ? AS {qi(alias)}", (str(path.resolve()),))


def tables(con: sqlite3.Connection, schema: str) -> List[str]:
    return [
        r[0]
        for r in con.execute(
            f"SELECT name FROM {qi(schema)}.sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def schema_sql(con: sqlite3.Connection, schema: str, table: str) -> str:
    row = con.execute(
        f"SELECT sql FROM {qi(schema)}.sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return (row[0] or "") if row else ""


def table_info(con: sqlite3.Connection, schema: str, table: str):
    # SQLite PRAGMA does not accept bound parameters for the table name.
    safe = table.replace("'", "''")
    return con.execute(f"PRAGMA {qi(schema)}.table_info('{safe}')").fetchall()


def cols_and_pk(con: sqlite3.Connection, schema: str, table: str) -> Tuple[List[str], List[str]]:
    info = table_info(con, schema, table)
    cols = [r[1] for r in info]
    pk = [name for _, name in sorted((r[5], r[1]) for r in info if r[5])]
    if not pk:
        raise MergeConflict(f"Table {table} has no PRIMARY KEY; safe propagation requires one")
    return cols, pk


def pk_pred(left: str, right: str, pk: Sequence[str]) -> str:
    return " AND ".join(f"{left}.{qi(c)} IS {right}.{qi(c)}" for c in pk)


def where_pk(pk: Sequence[str]) -> str:
    return " AND ".join(f"{qi(c)} IS ?" for c in pk)


def key_dict(pk: Sequence[str], key: Sequence[Any]) -> Dict[str, Any]:
    return {c: v for c, v in zip(pk, key)}


def propagate(base_source: Path, new_source: Path, target: Path, label: str) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"label": label, "tables": [], "conflicts": []}
    con = sqlite3.connect(str(target))
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys=OFF")
        attach(con, base_source, "base_db")
        attach(con, new_source, "new_db")

        base_tables = tables(con, "base_db")
        new_tables = tables(con, "new_db")
        dst_tables = tables(con, "main")
        if base_tables != new_tables:
            raise MergeConflict(f"{label}: source table set changed; explicit schema migration required")
        if new_tables != dst_tables:
            raise MergeConflict(f"{label}: downstream table set differs; explicit schema migration required")

        for table in new_tables:
            base_schema = schema_sql(con, "base_db", table)
            new_schema = schema_sql(con, "new_db", table)
            dst_schema = schema_sql(con, "main", table)
            if base_schema != new_schema:
                raise MergeConflict(
                    f"{label}: upstream schema changed for {table}. "
                    "Schema changes are not auto-propagated; apply them explicitly to all downstream DBs."
                )
            if new_schema != dst_schema:
                raise MergeConflict(
                    f"{label}: downstream schema for {table} differs from upstream schema."
                )

            cols, pk = cols_and_pk(con, "new_db", table)
            dst_cols, dst_pk = cols_and_pk(con, "main", table)
            if cols != dst_cols or pk != dst_pk:
                raise MergeConflict(f"{label}: columns/PK mismatch for {table}")

            join = pk_pred("b", "n", pk)
            non_pk = [c for c in cols if c not in pk]
            changed_expr = " OR ".join(f"b.{qi(c)} IS NOT n.{qi(c)}" for c in non_pk) or "0"

            added_sql = (
                f"SELECT {','.join('n.' + qi(c) for c in cols)} "
                f"FROM {qi('new_db')}.{qi(table)} n "
                f"WHERE NOT EXISTS (SELECT 1 FROM {qi('base_db')}.{qi(table)} b WHERE {join})"
            )
            removed_sql = (
                f"SELECT {','.join('b.' + qi(c) for c in cols)} "
                f"FROM {qi('base_db')}.{qi(table)} b "
                f"WHERE NOT EXISTS (SELECT 1 FROM {qi('new_db')}.{qi(table)} n WHERE {join})"
            )
            updated_select = []
            for c in cols:
                updated_select += [f"b.{qi(c)}", f"n.{qi(c)}"]
            updated_sql = (
                f"SELECT {','.join(updated_select)} "
                f"FROM {qi('base_db')}.{qi(table)} b "
                f"JOIN {qi('new_db')}.{qi(table)} n ON {join} "
                f"WHERE {changed_expr}"
            )

            inserted = deleted = updated = 0

            for row in con.execute(added_sql):
                incoming = dict(zip(cols, tuple(row)))
                key = tuple(incoming[c] for c in pk)
                existing = con.execute(
                    f"SELECT * FROM {qi(table)} WHERE {where_pk(pk)}", key
                ).fetchone()
                if existing is None:
                    con.execute(
                        f"INSERT INTO {qi(table)} ({','.join(qi(c) for c in cols)}) "
                        f"VALUES ({','.join('?' for _ in cols)})",
                        [incoming[c] for c in cols],
                    )
                    inserted += 1
                elif any(existing[c] != incoming[c] for c in cols):
                    summary["conflicts"].append({
                        "table": table,
                        "key": key_dict(pk, key),
                        "type": "insert_conflict",
                    })

            for row in con.execute(removed_sql):
                old = dict(zip(cols, tuple(row)))
                key = tuple(old[c] for c in pk)
                existing = con.execute(
                    f"SELECT * FROM {qi(table)} WHERE {where_pk(pk)}", key
                ).fetchone()
                if existing is None:
                    continue
                if all(existing[c] == old[c] for c in cols):
                    con.execute(f"DELETE FROM {qi(table)} WHERE {where_pk(pk)}", key)
                    deleted += 1
                else:
                    summary["conflicts"].append({
                        "table": table,
                        "key": key_dict(pk, key),
                        "type": "delete_conflict",
                    })

            for row in con.execute(updated_sql):
                values = tuple(row)
                old = {c: values[i * 2] for i, c in enumerate(cols)}
                incoming = {c: values[i * 2 + 1] for i, c in enumerate(cols)}
                key = tuple(incoming[c] for c in pk)
                existing = con.execute(
                    f"SELECT * FROM {qi(table)} WHERE {where_pk(pk)}", key
                ).fetchone()
                if existing is None:
                    summary["conflicts"].append({
                        "table": table,
                        "key": key_dict(pk, key),
                        "type": "update_missing_target_row",
                    })
                    continue

                set_cols: List[str] = []
                set_vals: List[Any] = []
                for col in non_pk:
                    if old[col] == incoming[col]:
                        continue
                    target_value = existing[col]
                    if target_value == old[col]:
                        set_cols.append(col)
                        set_vals.append(incoming[col])
                    elif target_value == incoming[col]:
                        pass
                    else:
                        summary["conflicts"].append({
                            "table": table,
                            "key": key_dict(pk, key),
                            "type": "field_conflict",
                            "column": col,
                            "upstream_old": old[col],
                            "upstream_new": incoming[col],
                            "target": target_value,
                        })
                if set_cols:
                    con.execute(
                        f"UPDATE {qi(table)} SET " + ",".join(f"{qi(c)}=?" for c in set_cols)
                        + f" WHERE {where_pk(pk)}",
                        set_vals + list(key),
                    )
                    updated += 1

            if inserted or deleted or updated:
                summary["tables"].append({
                    "table": table,
                    "inserted": inserted,
                    "deleted": deleted,
                    "updated": updated,
                })

        if summary["conflicts"]:
            con.rollback()
            raise MergeConflict(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
        con.commit()
    finally:
        con.close()
    return summary


def copy_current_to_preview(repo_root: Path, preview_root: Path) -> Dict[str, Path]:
    current = current_database_paths(repo_root)
    out: Dict[str, Path] = {}
    for channel, source in current.items():
        target = preview_root / DB_PATHS[channel]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        out[channel] = target
    return out


def render_sync_report(summaries: List[Dict[str, Any]], sync_required: List[str], write_mode: bool = False) -> str:
    lines = ["## Database channel synchronization", ""]
    if sync_required:
        lines += [
            "**Synchronization required.** Commit the inherited changes to:", ""
        ]
        lines += [f"- `{p}`" for p in sync_required]
        lines += [
            "", "Run locally:", "", "```bash",
            "git fetch origin main",
            "python3 scripts/database/sync_database_channels.py --base-ref origin/main --write",
            "```", "",
        ]
    elif write_mode:
        lines += ["Propagation was applied to the tracked downstream DB files.", ""]
    else:
        lines += ["All downstream DBs already contain the required inherited changes.", ""]

    for s in summaries:
        lines += [f"### {s['label']}", ""]
        if not s["tables"]:
            lines.append("No rows needed propagation.")
        else:
            lines += ["| Table | Inserted | Deleted | Updated |", "|---|---:|---:|---:|"]
            for t in s["tables"]:
                lines.append(f"| `{t['table']}` | {t['inserted']} | {t['deleted']} | {t['updated']} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref")
    parser.add_argument("--base-root", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--preview-dir", type=Path)
    parser.add_argument("--report", type=Path, default=Path("database-sync-report.md"))
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    current = current_database_paths(repo_root)

    with tempfile.TemporaryDirectory(prefix="necto-db-base-") as base_td:
        if args.base_ref:
            base = materialize_git_databases(args.base_ref, Path(base_td))
        elif args.base_root:
            base = {
                "live": args.base_root / "live" / "necto_db.db",
                "development": args.base_root / "development" / "necto_db.db",
                "experimental": args.base_root / "experimental" / "necto_db.db",
            }
        else:
            parser.error("one of --base-ref or --base-root is required")

        if args.write:
            working = current
        else:
            preview_root = (args.preview_dir or Path(tempfile.mkdtemp(prefix="necto-db-preview-"))).resolve()
            working = copy_current_to_preview(repo_root, preview_root)

        summaries = [
            propagate(base["live"], working["live"], working["development"], "LIVE → DEVELOPMENT"),
            propagate(base["development"], working["development"], working["experimental"], "DEVELOPMENT → EXPERIMENTAL"),
        ]

        sync_required: List[str] = []
        if not args.write:
            for channel in ("development", "experimental"):
                # Preview starts as an exact byte copy and we only write when propagation
                # actually changes data, so hash comparison is both fast and exact here.
                if sha256_file(current[channel]) != sha256_file(working[channel]):
                    sync_required.append(DB_PATHS[channel])

        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(render_sync_report(summaries, sync_required, args.write), encoding="utf-8")
        print(args.report.read_text(encoding="utf-8"))
        return 3 if sync_required else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MergeConflict as exc:
        print("DATABASE PROPAGATION CONFLICT:\n" + str(exc))
        raise SystemExit(2)
