#!/usr/bin/env python3
"""Generate row-level diffs for Live, Development and Experimental NECTO DBs."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from db_common import DB_PATHS, compact_json, current_database_paths, integrity_check, materialize_git_databases, normalize_value, qi, sha256_file


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
        f"SELECT sql FROM {qi(schema)}.sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return (row[0] or "") if row else ""


def table_info(con: sqlite3.Connection, schema: str, table: str):
    safe = table.replace("'", "''")
    return con.execute(f"PRAGMA {qi(schema)}.table_info('{safe}')").fetchall()


def cols_pk(con: sqlite3.Connection, schema: str, table: str) -> Tuple[List[str], List[str]]:
    info = table_info(con, schema, table)
    cols = [r[1] for r in info]
    pk = [name for _, name in sorted((r[5], r[1]) for r in info if r[5])]
    return cols, pk


def count(con: sqlite3.Connection, schema: str, table: str) -> int:
    return con.execute(f"SELECT COUNT(*) FROM {qi(schema)}.{qi(table)}").fetchone()[0]


def row_json(cols: Sequence[str], values: Sequence[Any]) -> Dict[str, Any]:
    return {c: normalize_value(v) for c, v in zip(cols, values)}


def key_json(pk: Sequence[str], values: Sequence[Any]) -> Dict[str, Any]:
    return {c: normalize_value(v) for c, v in zip(pk, values)}


def pk_pred(left: str, right: str, pk: Sequence[str]) -> str:
    return " AND ".join(f"{left}.{qi(c)} IS {right}.{qi(c)}" for c in pk)


def changed_table_diff(con: sqlite3.Connection, table: str) -> Dict[str, Any]:
    old_cols, old_pk = cols_pk(con, "old_db", table)
    new_cols, new_pk = cols_pk(con, "new_db", table)
    old_schema = schema_sql(con, "old_db", table)
    new_schema = schema_sql(con, "new_db", table)
    schema_changed = old_schema != new_schema

    result: Dict[str, Any] = {
        "table": table,
        "schema_status": "changed" if schema_changed else "unchanged",
        "old_schema": old_schema if schema_changed else None,
        "new_schema": new_schema if schema_changed else None,
        "pk": new_pk if new_pk else old_pk,
        "old_count": count(con, "old_db", table),
        "new_count": count(con, "new_db", table),
        "added": [], "removed": [], "updated": [],
    }

    # Safe row-level matching requires stable PK + columns. Current supplied NECTO
    # database satisfies this for all 29 tables. Future structural changes are
    # still reported, but their row diff is intentionally not guessed.
    if not old_pk or old_pk != new_pk or old_cols != new_cols:
        result["row_diff_skipped"] = "columns_or_primary_key_changed"
        return result

    cols, pk = new_cols, new_pk
    join = pk_pred("o", "n", pk)
    order = ",".join(f"n.{qi(c)}" for c in pk)

    add_sql = (
        f"SELECT {','.join('n.' + qi(c) for c in cols)} "
        f"FROM {qi('new_db')}.{qi(table)} n "
        f"WHERE NOT EXISTS (SELECT 1 FROM {qi('old_db')}.{qi(table)} o WHERE {join})"
        + (f" ORDER BY {order}" if order else "")
    )
    rem_order = ",".join(f"o.{qi(c)}" for c in pk)
    rem_sql = (
        f"SELECT {','.join('o.' + qi(c) for c in cols)} "
        f"FROM {qi('old_db')}.{qi(table)} o "
        f"WHERE NOT EXISTS (SELECT 1 FROM {qi('new_db')}.{qi(table)} n WHERE {join})"
        + (f" ORDER BY {rem_order}" if rem_order else "")
    )

    for row in con.execute(add_sql):
        result["added"].append(row_json(cols, tuple(row)))
    for row in con.execute(rem_sql):
        result["removed"].append(row_json(cols, tuple(row)))

    non_pk = [c for c in cols if c not in pk]
    changed_expr = " OR ".join(f"o.{qi(c)} IS NOT n.{qi(c)}" for c in non_pk) or "0"
    select_parts = [f"n.{qi(c)}" for c in pk]
    for c in non_pk:
        select_parts += [f"o.{qi(c)}", f"n.{qi(c)}"]
    upd_sql = (
        f"SELECT {','.join(select_parts)} "
        f"FROM {qi('old_db')}.{qi(table)} o JOIN {qi('new_db')}.{qi(table)} n ON {join} "
        f"WHERE {changed_expr}"
        + (f" ORDER BY {order}" if order else "")
    )
    for row in con.execute(upd_sql):
        vals = tuple(row)
        key_vals = vals[:len(pk)]
        offset = len(pk)
        changes: Dict[str, Any] = {}
        for i, col in enumerate(non_pk):
            old_v = vals[offset + i * 2]
            new_v = vals[offset + i * 2 + 1]
            if old_v != new_v:
                changes[col] = {"old": normalize_value(old_v), "new": normalize_value(new_v)}
        if changes:
            result["updated"].append({"key": key_json(pk, key_vals), "changes": changes})
    return result


def added_or_removed_table(con: sqlite3.Connection, table: str, added: bool) -> Dict[str, Any]:
    schema = "new_db" if added else "old_db"
    cols, pk = cols_pk(con, schema, table)
    rows = [row_json(cols, tuple(r)) for r in con.execute(f"SELECT * FROM {qi(schema)}.{qi(table)}")]
    return {
        "table": table,
        "schema_status": "added_table" if added else "removed_table",
        "old_schema": None if added else schema_sql(con, schema, table),
        "new_schema": schema_sql(con, schema, table) if added else None,
        "pk": pk,
        "old_count": 0 if added else len(rows),
        "new_count": len(rows) if added else 0,
        "added": rows if added else [],
        "removed": [] if added else rows,
        "updated": [],
    }


def diff_database(old_path: Path, new_path: Path, channel: str) -> Dict[str, Any]:
    con = sqlite3.connect(":memory:")
    try:
        attach(con, old_path, "old_db")
        attach(con, new_path, "new_db")
        old_tables = set(tables(con, "old_db"))
        new_tables = set(tables(con, "new_db"))
        changed_tables: List[Dict[str, Any]] = []
        for table in sorted(old_tables | new_tables):
            if table not in old_tables:
                td = added_or_removed_table(con, table, True)
            elif table not in new_tables:
                td = added_or_removed_table(con, table, False)
            else:
                td = changed_table_diff(con, table)
            if td["schema_status"] != "unchanged" or td["added"] or td["removed"] or td["updated"]:
                changed_tables.append(td)
    finally:
        con.close()

    return {
        "channel": channel,
        "path": DB_PATHS[channel],
        "old_sha256": sha256_file(old_path),
        "new_sha256": sha256_file(new_path),
        "integrity": integrity_check(new_path),
        "changed": bool(changed_tables),
        "tables": changed_tables,
    }


def row_id(row: Mapping[str, Any], pk: Sequence[str]) -> str:
    keys = list(pk) if pk else list(row)[:3]
    return ", ".join(f"{c}={compact_json(row.get(c))}" for c in keys)


def render_markdown(report: Dict[str, Any], detail_limit: int, title: str, collapsible_tables: bool = False) -> str:
    lines = [f"## {title}", ""]
    if not any(d["changed"] for d in report["databases"]):
        return "\n".join(lines + ["No logical database changes detected.", ""])

    for db in report["databases"]:
        if not db["changed"]:
            continue
        lines += [f"### {db['channel'].upper()} — `{db['path']}`", ""]
        lines += ["| Table | Added | Removed | Updated | Rows before → after | Schema |", "|---|---:|---:|---:|---:|---|"]
        for t in db["tables"]:
            lines.append(
                f"| `{t['table']}` | {len(t['added'])} | {len(t['removed'])} | {len(t['updated'])} | "
                f"{t['old_count']} → {t['new_count']} | {t['schema_status']} |"
            )
        lines.append("")

        for t in db["tables"]:
            added_count = len(t["added"])
            removed_count = len(t["removed"])
            updated_count = len(t["updated"])
            if collapsible_tables:
                lines += [
                    "<details>",
                    f"<summary><strong>{t['table']}</strong> — +{added_count} / -{removed_count} / ~{updated_count}</summary>",
                    "",
                ]
            else:
                lines += [f"#### `{t['table']}`", ""]

            if t.get("row_diff_skipped"):
                lines.append(f"- Row-level diff skipped: `{t['row_diff_skipped']}`")
            if t["schema_status"] != "unchanged":
                lines.append(f"- Schema: **{t['schema_status']}**")

            def limit(items: List[Any]):
                if detail_limit <= 0:
                    return items, 0
                return items[:detail_limit], max(0, len(items) - detail_limit)

            for label, symbol, key in (("Added", "+", "added"), ("Removed", "-", "removed")):
                if not t[key]:
                    continue
                shown, more = limit(t[key])
                lines.append(f"- **{label} ({len(t[key])})**")
                for r in shown:
                    lines.append(f"  - `{symbol}` {row_id(r, t['pk'])}")
                if more:
                    lines.append(f"  - … {more} more row(s) in full artifact")

            if t["updated"]:
                shown, more = limit(t["updated"])
                lines.append(f"- **Updated ({len(t['updated'])})**")
                for u in shown:
                    key = ", ".join(f"{k}={compact_json(v)}" for k, v in u["key"].items())
                    changes = "; ".join(
                        f"{c}: {compact_json(v['old'])} → {compact_json(v['new'])}"
                        for c, v in u["changes"].items()
                    )
                    lines.append(f"  - `~` {key} — {changes}")
                if more:
                    lines.append(f"  - … {more} more updated row(s) in full artifact")
            lines.append("")
            if collapsible_tables:
                lines += ["</details>", ""]
    return "\n".join(lines).rstrip() + "\n"


def write_github_output(report: Dict[str, Any]) -> None:
    out = os.getenv("GITHUB_OUTPUT")
    if not out:
        return
    changed = [d["channel"] for d in report["databases"] if d["changed"]]
    with open(out, "a", encoding="utf-8") as f:
        f.write(f"has_changes={'true' if changed else 'false'}\n")
        f.write(f"changed_databases={','.join(changed)}\n")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-ref")
    p.add_argument("--base-root", type=Path)
    p.add_argument("--new-root", type=Path, default=Path("."))
    p.add_argument("--json", type=Path, required=True)
    p.add_argument("--markdown", type=Path, required=True)
    p.add_argument("--full-markdown", type=Path)
    p.add_argument("--detail-limit", type=int, default=50)
    p.add_argument("--title", default="NECTO database changes")
    p.add_argument("--collapsible-tables", action="store_true",
                   help="wrap each changed table in GitHub <details>/<summary> markup")
    args = p.parse_args()

    new_paths = current_database_paths(args.new_root.resolve())
    with tempfile.TemporaryDirectory(prefix="necto-db-base-") as td:
        if args.base_ref:
            old_paths = materialize_git_databases(args.base_ref, Path(td))
        elif args.base_root:
            old_paths = {
                "live": args.base_root / "live" / "necto_db.db",
                "development": args.base_root / "development" / "necto_db.db",
                "experimental": args.base_root / "experimental" / "necto_db.db",
            }
        else:
            p.error("one of --base-ref or --base-root is required")
        report = {
            "base_ref": args.base_ref,
            "databases": [diff_database(old_paths[c], new_paths[c], c) for c in ("live", "development", "experimental")],
        }

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    args.markdown.write_text(render_markdown(report, args.detail_limit, args.title, args.collapsible_tables), encoding="utf-8")
    if args.full_markdown:
        args.full_markdown.parent.mkdir(parents=True, exist_ok=True)
        args.full_markdown.write_text(render_markdown(report, 0, args.title, args.collapsible_tables), encoding="utf-8")
    write_github_output(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
