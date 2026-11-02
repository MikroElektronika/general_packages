#!/usr/bin/env python3
"""Keep only MCUs from visible Elasticsearch MCU packages in erp_db.db.

An MCU stays in the ERP Devices table only if it is listed in the `mcus`
field of at least one indexed package with type "mcu" and hidden == false.
MCU card rows (uids containing "_") are not MCUs and are left untouched.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import time
from pathlib import Path

from elasticsearch import Elasticsearch

# Tables whose device_uid column references Devices.uid
DEVICE_LINK_TABLES = (
    'BoardToDevice', 'CompilerToDevice', 'DebuggerToDevice',
    'DeviceToPackage', 'DeviceToSocket', 'ProgrammerToDevice', 'SDKToDevice',
)


def fetch_visible_mcus(es: Elasticsearch, index_name: str) -> set[str]:
    query_search = {
        "size": 10000,
        "_source": ["name", "type", "hidden", "mcus"],
        "query": {
            "bool": {
                "filter": [
                    {"match": {"type": "mcu"}},
                    {"term": {"hidden": False}},
                ]
            }
        }
    }

    response = None
    for retry in range(1, 11):
        try:
            response = es.search(index=index_name, body=query_search)
            if not response['timed_out']:
                break
        except Exception as exc:
            print(f"Executing search query - retry number {retry}: {exc}")
        time.sleep(retry)
    if response is None or response['timed_out']:
        raise RuntimeError(f"Could not fetch MCU packages from index {index_name!r}")

    visible_mcus = set()
    packages = 0
    for hit in response['hits']['hits']:
        source = hit['_source']
        if source.get('type') != 'mcu' or source.get('hidden') is not False:
            continue
        packages += 1
        visible_mcus.update(mcu.strip().upper() for mcu in source.get('mcus') or [] if mcu.strip())

    print(f"Found {len(visible_mcus)} MCUs in {packages} visible MCU packages.")
    return visible_mcus


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def filter_erp_devices(database: str | os.PathLike[str], visible_mcus: set[str]) -> list[str]:
    if not visible_mcus:
        # Never wipe the ERP device list because of an empty/failed ES response
        raise RuntimeError("No visible MCUs found in Elasticsearch, refusing to filter ERP database")

    con = sqlite3.connect(database)
    try:
        mcu_uids = [
            row[0] for row in con.execute(
                "SELECT uid FROM Devices WHERE uid NOT LIKE '%\\_%' ESCAPE '\\'"
            )
        ]
        removed = sorted(uid for uid in mcu_uids if uid.upper() not in visible_mcus)
        missing = sorted(visible_mcus - {uid.upper() for uid in mcu_uids})

        # Foreign keys stay off: DeviceVendors declares an invalid reference to
        # Devices(vendor), so cascading deletes are done explicitly instead.
        con.execute("CREATE TEMP TABLE removed_devices (uid TEXT PRIMARY KEY)")
        con.executemany("INSERT INTO removed_devices VALUES (?)", ((uid,) for uid in removed))
        for table in DEVICE_LINK_TABLES:
            if table_exists(con, table):
                con.execute(f"DELETE FROM {table} WHERE device_uid IN (SELECT uid FROM removed_devices)")
        if table_exists(con, 'DeviceDetails'):
            con.execute("DELETE FROM DeviceDetails WHERE uid IN (SELECT uid FROM removed_devices)")
        con.execute("DELETE FROM Devices WHERE uid IN (SELECT uid FROM removed_devices)")
        con.commit()
    finally:
        con.close()

    print(f"Kept {len(mcu_uids) - len(removed)} MCUs, removed {len(removed)} MCUs from {database}.")
    if missing:
        print(f"\033[93mVisible MCUs missing from Devices table ({len(missing)}): {missing}\033[0m")
    return removed


def connect_es() -> Elasticsearch:
    return Elasticsearch(
        [os.environ['ES_HOST']],
        http_auth=(os.environ['ES_USER'], os.environ['ES_PASSWORD'])
    )


def filter_erp_database(database: str | os.PathLike[str], index_name: str | None = None) -> list[str]:
    index_name = index_name or os.environ['ES_INDEX_LIVE']
    visible_mcus = fetch_visible_mcus(connect_es(), index_name)
    return filter_erp_devices(database, visible_mcus)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path, help='Path to erp_db.db')
    parser.add_argument('--index', default='', help='Elasticsearch index name. Defaults to ES_INDEX_LIVE.')
    args = parser.parse_args()

    if not args.database.is_file():
        raise SystemExit(f'Missing database: {args.database}')
    filter_erp_database(args.database, args.index or None)
