#!/usr/bin/env python3
"""Materialize the three NECTO databases from a Git ref once for CI reuse."""

import argparse
from pathlib import Path
from db_common import materialize_git_databases


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--ref', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    paths = materialize_git_databases(args.ref, args.output)
    for channel, path in paths.items():
        print(f'{channel}: {path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
