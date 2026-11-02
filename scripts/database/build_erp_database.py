#!/usr/bin/env python3
"""Build erp_db.db from the tracked Live necto_db.db without a full refresh.

Applies the same ERP-only steps that reupload_databases.py runs on its ERP copy
(steps 4, 7, 8, 14, 18 and 18.1), so the daily ERP update only needs the Live
database committed on main and Elasticsearch access.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import reupload_databases as reupload
from filter_erp_devices import filter_erp_database

REPO_ROOT = Path(__file__).resolve().parents[2]


def build_erp_database(necto_db: Path, erp_db: Path, index_name: str | None = None) -> None:
    shutil.copy2(necto_db, erp_db)
    erp = str(erp_db)

    reupload.log_step('\033[96mERP step 4: Adding extra columns for ERP database.\033[0m')
    reupload.addCollumnsToTable(erp, ['pid'], 'Boards', ['VARCHAR(50)'], ['NoDefault'])
    reupload.addCollumnsToTable(erp, ['package_uid'], 'BoardToDevice', ['TEXT'], ['NoDefault'])
    reupload.addCollumnsToTable(
        erp, ['pid', 'graphic_tool'], 'Compilers', ['VARCHAR(50)', 'BOOLEAN'], ['NoDefault', 0]
    )

    reupload.log_step('\033[96mERP steps 7-8: Updating BoardToDevice package information.\033[0m')
    allDevices = reupload.read_data_from_db(erp, 'SELECT DISTINCT uid, def_file FROM Devices')
    reupload.checkDevicePackages(erp, allDevices)
    reupload.clearDevicePackages(erp)

    # JLink mappings are added to the NECTO database only (full refresh step 11)
    reupload.log_step('\033[96mERP step 11: Removing NECTO-only Segger J-Link mappings.\033[0m')
    reupload.deleteFromTable(erp, 'DELETE FROM ProgrammerToDevice WHERE programer_uid="segger_jlink"')
    reupload.deleteFromTable(erp, 'DELETE FROM DebuggerToDevice WHERE debugger_uid="segger_jlink"')

    # Devices still hold the NECTO family_uid here, so the ERP copy can serve as the source
    reupload.log_step('\033[96mERP step 14: Adding ERP-applicable info.\033[0m')
    reupload.update_erp_info(erp, erp)

    reupload.log_step('\033[96mERP step 18: Updating ERP database for DBP sync.\033[0m')
    for table in ('DeviceVendors', 'DeviceFamilies', 'DeviceArchitectures'):
        reupload.createErpDbpSyncInfo(db=erp, table=table)

    reupload.log_step('\033[96mERP step 18.1: Removing MCUs not present in visible ES MCU packages.\033[0m')
    filter_erp_database(erp, index_name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--necto_db', type=Path, default=REPO_ROOT / reupload.CHANNEL_DB_PATHS['live'],
        help='Source Live necto_db.db. Defaults to the tracked Live database.'
    )
    parser.add_argument('--output', type=Path, default=Path('erp_db.db'), help='Output erp_db.db path')
    parser.add_argument('--index', default='', help='Elasticsearch index name. Defaults to ES_INDEX_LIVE.')
    args = parser.parse_args()

    if not args.necto_db.is_file():
        raise SystemExit(f'Missing database: {args.necto_db}')
    build_erp_database(args.necto_db, args.output, args.index or None)
