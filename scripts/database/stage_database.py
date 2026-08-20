#!/usr/bin/env python3
"""Copy a generated SQLite DB into the correct tracked NECTO channel path."""

import argparse
import shutil
from pathlib import Path

from db_common import DB_PATHS, integrity_check


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--channel', choices=sorted(DB_PATHS), required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--repo-root', type=Path, default=Path('.'))
    args = p.parse_args()

    source = args.source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    result = integrity_check(source)
    if result != 'ok':
        raise RuntimeError(f'Source database failed PRAGMA integrity_check: {result}')

    target = args.repo_root.resolve() / DB_PATHS[args.channel]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    print(f'Staged {args.channel}: {source} -> {target}')
    print('Next: python3 scripts/database/sync_database_channels.py --base-ref origin/main --write')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
