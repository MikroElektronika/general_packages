#!/usr/bin/env python3
"""Shared helpers for NECTO SQLite database CI tooling."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

DB_PATHS = {
    "live": "utils/databases/database_live/necto_db.db",
    "development": "utils/databases/database_dev/necto_db.db",
    "experimental": "utils/databases/database_experimental/necto_db.db",
}

# Historical fallback used only when reading an older Git revision. This lets
# the folder-rename PR compare against commits where Live was still stored in
# utils/databases/database/necto_db.db. Current working-tree operations always
# require the new database_live path.
LEGACY_DB_PATHS = {
    "live": ("utils/databases/database/necto_db.db",),
    "development": (),
    "experimental": (),
}

MISSING = object()


def qi(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def connect(path: os.PathLike[str] | str) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con


def sha256_file(path: os.PathLike[str] | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def user_tables(con: sqlite3.Connection) -> List[str]:
    return [
        row[0]
        for row in con.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
    ]


def table_sql(con: sqlite3.Connection, table: str) -> str:
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return (row[0] or "") if row else ""


def columns(con: sqlite3.Connection, table: str) -> List[str]:
    return [row[1] for row in con.execute(f"PRAGMA table_info({qi(table)})")]


def primary_key_columns(con: sqlite3.Connection, table: str) -> List[str]:
    rows = con.execute(f"PRAGMA table_info({qi(table)})").fetchall()
    ordered = sorted((row[5], row[1]) for row in rows if row[5])
    return [name for _, name in ordered]


def row_count(con: sqlite3.Connection, table: str) -> int:
    return con.execute(f"SELECT COUNT(*) FROM {qi(table)}").fetchone()[0]


def normalize_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__blob_base64__": base64.b64encode(value).decode("ascii")}
    return value


def jsonable_row(row: Mapping[str, Any], cols: Sequence[str] | None = None) -> Dict[str, Any]:
    if cols is None:
        cols = list(row.keys())
    return {c: normalize_value(row[c]) for c in cols}


def key_to_json(pk_cols: Sequence[str], key: Tuple[Any, ...]) -> Dict[str, Any]:
    return {c: normalize_value(v) for c, v in zip(pk_cols, key)}


def load_rows_by_pk(
    con: sqlite3.Connection,
    table: str,
    *,
    required_pk: bool = True,
) -> Tuple[List[str], List[str], Dict[Tuple[Any, ...], Dict[str, Any]]]:
    cols = columns(con, table)
    pk_cols = primary_key_columns(con, table)
    if required_pk and not pk_cols:
        raise ValueError(
            f"Table {table!r} has no PRIMARY KEY; safe row-level propagation is not possible."
        )

    rows: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for db_row in con.execute(f"SELECT * FROM {qi(table)}"):
        d = dict(db_row)
        key = tuple(d[c] for c in pk_cols) if pk_cols else tuple(d[c] for c in cols)
        rows[key] = d
    return cols, pk_cols, rows


def integrity_check(path: os.PathLike[str] | str) -> str:
    with connect(path) as con:
        row = con.execute("PRAGMA integrity_check").fetchone()
        return row[0] if row else "unknown"


def materialize_git_file(ref: str, repo_path: str, destination: Path) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "show", f"{ref}:{repo_path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        return False
    data = proc.stdout
    # If the database is tracked by Git LFS, `git show` returns the pointer.
    # Smudge it into the real object so SQLite can open the historical DB.
    if data.startswith(b"version https://git-lfs.github.com/spec/v1"):
        smudge = subprocess.run(
            ["git", "lfs", "smudge"],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if smudge.returncode != 0:
            raise RuntimeError(
                f"git lfs smudge failed for {repo_path} at {ref}: "
                + smudge.stderr.decode("utf-8", errors="replace")
            )
        data = smudge.stdout
    destination.write_bytes(data)
    return True


def materialize_git_databases(ref: str, destination_root: Path) -> Dict[str, Path]:
    result: Dict[str, Path] = {}
    for channel, repo_path in DB_PATHS.items():
        dest = destination_root / channel / "necto_db.db"
        candidates = (repo_path, *LEGACY_DB_PATHS.get(channel, ()))
        used_path = None
        for candidate in candidates:
            if materialize_git_file(ref, candidate, dest):
                used_path = candidate
                break
        if used_path is None:
            raise FileNotFoundError(
                f"Could not read any database path for {channel} from git ref {ref}: "
                + ", ".join(candidates)
                + ". Make sure checkout uses fetch-depth: 0 and all three DB files exist."
            )
        if used_path != repo_path:
            print(
                f"[{channel}] using historical database path {used_path} at {ref}; "
                f"current path is {repo_path}"
            )
        result[channel] = dest
    return result


def current_database_paths(repo_root: Path) -> Dict[str, Path]:
    paths = {name: repo_root / rel for name, rel in DB_PATHS.items()}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing database file(s): " + ", ".join(missing))
    return paths


def logical_database_equal(a: Path, b: Path) -> bool:
    """Compare schema + rows, ignoring SQLite page/layout differences."""
    with connect(a) as ca, connect(b) as cb:
        ta, tb = user_tables(ca), user_tables(cb)
        if ta != tb:
            return False
        for table in ta:
            if table_sql(ca, table) != table_sql(cb, table):
                return False
            cols_a, pk_a, rows_a = load_rows_by_pk(ca, table)
            cols_b, pk_b, rows_b = load_rows_by_pk(cb, table)
            if cols_a != cols_b or pk_a != pk_b or rows_a != rows_b:
                return False
    return True


def compact_json(value: Any, max_len: int = 160) -> str:
    text = json.dumps(normalize_value(value), ensure_ascii=False, sort_keys=True)
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def changed_columns(old: Mapping[str, Any], new: Mapping[str, Any], cols: Iterable[str]) -> List[str]:
    return [c for c in cols if old.get(c, MISSING) != new.get(c, MISSING)]
