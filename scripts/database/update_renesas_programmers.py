"""Restore Renesas programmers, debuggers, and device mappings after a DB refresh.

Run this *after* all imported programmer/debugger data (CODEGRIP, mikroProg,
J-Link, Microchip) because the importer deletes and rebuilds device mappings.
This step is repeatable and keeps unrelated programmer/debugger data intact.
"""

import sqlite3
from pathlib import Path


# (UID, display name, icon, programmer description, debugger description)
RENESAS_TOOLS = (
    (
        'renesas_e2',
        'Renesas E2',
        'images/programmers/renesas_e2.png',
        'Renesas E2 emulator for RA, RX and RL78 devices, through the Renesas e2 GDB server.',
        'Renesas E2 emulator for RA, RX and RL78 devices.',
    ),
    (
        'renesas_e2lite',
        'Renesas E2 Lite',
        'images/programmers/renesas_e2lite.png',
        'Renesas E2 Lite emulator (also on-board) for RA, RX and RL78 devices, through the Renesas e2 GDB server.',
        'Renesas E2 Lite emulator (also on-board) for RA, RX and RL78 devices.',
    ),
    (
        'renesas_com',
        'Renesas COM Port',
        'images/programmers/renesas_com.png',
        'RL78 programming and debugging through the TOOL0 pin and a USB-serial adapter (COM port), without an emulator.',
        'RL78 debugging through the TOOL0 pin and a USB-serial adapter (COM port).',
    ),
)

E2_COMPILERS = ('gcc_arm_none_eabi', 'clang-llvm', 'llvm-rl78-elf', 'rx-elf-gcc')


def _add_compiler_mapping(con: sqlite3.Connection, programmer_uid: str, compiler_uid: str) -> None:
    """Add a mapping once, even on schemas without a uniqueness constraint."""
    con.execute(
        '''
        INSERT INTO CompilerToProgrammer (programmer_uid, compiler_uid)
        SELECT ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM CompilerToProgrammer
            WHERE programmer_uid = ? AND compiler_uid = ?
        )
        ''',
        (programmer_uid, compiler_uid, programmer_uid, compiler_uid),
    )


def update_renesas_programmers(database: str | Path) -> dict[str, int]:
    """Apply the Renesas DB updates atomically and return mapping counts.

    Intended for the final programmer refresh phase of reupload_databases.py.
    A failed statement rolls back the entire Renesas step for this database.
    """
    database = str(database)
    with sqlite3.connect(database) as con:
        # An explicit transaction protects the delete-then-repopulate mappings.
        con.execute('BEGIN')

        # UPSERT rather than INSERT OR REPLACE: REPLACE deletes existing rows
        # first, potentially cascading to unrelated references when FKs are ON.
        for uid, name, icon, programmer_desc, debugger_desc in RENESAS_TOOLS:
            con.execute(
                '''
                INSERT INTO Programmers
                    (uid, hidden, name, icon, installed, description, installer_package)
                VALUES (?, 0, ?, ?, 1, ?, '')
                ON CONFLICT(uid) DO UPDATE SET
                    hidden = excluded.hidden,
                    name = excluded.name,
                    icon = excluded.icon,
                    installed = excluded.installed,
                    description = excluded.description,
                    installer_package = excluded.installer_package
                ''',
                (uid, name, icon, programmer_desc),
            )
            con.execute(
                '''
                INSERT INTO Debuggers (uid, hidden, name, icon, description)
                VALUES (?, 0, ?, ?, ?)
                ON CONFLICT(uid) DO UPDATE SET
                    hidden = excluded.hidden,
                    name = excluded.name,
                    icon = excluded.icon,
                    description = excluded.description
                ''',
                (uid, name, icon, debugger_desc),
            )

        for compiler_uid in E2_COMPILERS:
            _add_compiler_mapping(con, 'renesas_e2', compiler_uid)

        # Mirror the E2 compiler associations to E2 Lite.
        for (compiler_uid,) in con.execute(
            'SELECT compiler_uid FROM CompilerToProgrammer WHERE programmer_uid = ?',
            ('renesas_e2',),
        ).fetchall():
            _add_compiler_mapping(con, 'renesas_e2lite', compiler_uid)
        _add_compiler_mapping(con, 'renesas_com', 'llvm-rl78-elf')

        # Rebuild ONLY the three Renesas tools' device associations.
        uids = tuple(tool[0] for tool in RENESAS_TOOLS)
        placeholders = ', '.join('?' for _ in uids)
        con.execute(
            f'DELETE FROM ProgrammerToDevice WHERE programer_uid IN ({placeholders})',
            uids,
        )
        con.execute(
            f'DELETE FROM DebuggerToDevice WHERE debugger_uid IN ({placeholders})',
            uids,
        )

        # E2/E2 Lite: all Renesas MCUs. Select support pack by UID/family.
        con.execute(
            '''
            INSERT INTO ProgrammerToDevice
                (programer_uid, device_uid, device_support_package)
            SELECT p.uid, d.uid,
                   CASE
                       WHEN d.uid GLOB 'R5*' THEN '["renesas_e2_rx"]'
                       WHEN d.uid GLOB 'R7F1*' THEN '["renesas_e2_rl78"]'
                       ELSE '["renesas_e2_ra_' || LOWER(d.family_uid) || '"]'
                   END
            FROM Devices AS d
            CROSS JOIN (
                SELECT 'renesas_e2' AS uid
                UNION ALL
                SELECT 'renesas_e2lite'
            ) AS p
            WHERE d.vendor = 'Renesas'
            '''
        )
        con.execute(
            '''
            INSERT INTO DebuggerToDevice (debugger_uid, device_uid)
            SELECT p.uid, d.uid
            FROM Devices AS d
            CROSS JOIN (
                SELECT 'renesas_e2' AS uid
                UNION ALL
                SELECT 'renesas_e2lite'
            ) AS p
            WHERE d.vendor = 'Renesas'
            '''
        )

        # COM port: only RL78 devices whose UID begins with R7F1.
        con.execute(
            '''
            INSERT INTO ProgrammerToDevice
                (programer_uid, device_uid, device_support_package)
            SELECT 'renesas_com', d.uid, '["renesas_e2_rl78"]'
            FROM Devices AS d
            WHERE d.vendor = 'Renesas' AND d.uid GLOB 'R7F1*'
            '''
        )
        con.execute(
            '''
            INSERT INTO DebuggerToDevice (debugger_uid, device_uid)
            SELECT 'renesas_com', d.uid
            FROM Devices AS d
            WHERE d.vendor = 'Renesas' AND d.uid GLOB 'R7F1*'
            '''
        )

        # Keep any previously populated necto_config JSON unchanged, as in
        # the original SQL. Only set the flag when the field is blank.
        con.execute(
            '''
            UPDATE Devices
            SET necto_config = '{"LLDB_SUPPORTED":"FALSE"}'
            WHERE (family_uid GLOB 'RA[246]*'
                   OR family_uid GLOB 'RX*'
                   OR family_uid IN (
                       SELECT name FROM DeviceFamilies
                       WHERE architecture_uid = 'RENESAS_RL78'
                   ))
              AND (necto_config IS NULL OR necto_config = '')
            '''
        )
        con.execute(
            '''
            UPDATE Compilers
            SET default_options = '{"debugger":""}'
            WHERE uid = 'llvm-rl78-elf'
            '''
        )

        result = {
            'programmer_mappings': con.execute(
                f'SELECT COUNT(*) FROM ProgrammerToDevice WHERE programer_uid IN ({placeholders})',
                uids,
            ).fetchone()[0],
            'debugger_mappings': con.execute(
                f'SELECT COUNT(*) FROM DebuggerToDevice WHERE debugger_uid IN ({placeholders})',
                uids,
            ).fetchone()[0],
        }
    return result
