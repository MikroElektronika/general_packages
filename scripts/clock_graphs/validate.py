"""Validate clock_graphs/: structure, expressions, index.json freshness and, with --defs,
every bound register field and value against NECTO MCU definitions.

  python scripts/clock_graphs/validate.py
  python scripts/clock_graphs/validate.py --defs <folder with def/<MCU>.json files, searched recursively>
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from build_index import build_index
from graphlib import GRAPHS_ROOT, check_graph, load_graphs


def load_definitions(root):
    """MCU name -> {field id: set of allowed absolute values} for visible fields only."""
    definitions = {}
    for path in Path(root).rglob('*.json'):
        if 'def' not in path.parts:
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, UnicodeDecodeError):
            continue
        fields = {}
        for register in data.get('config_registers') or []:
            for field in register.get('fields') or []:
                if field.get('hidden'):
                    continue
                mask = int(str(field.get('mask', '0')), 16)
                values = {int(str(setting['value']), 16) for setting in field.get('settings') or [] if str(setting.get('value', '')).strip()}
                span = field.get('settings_array')
                if span and mask:
                    shift = (mask & -mask).bit_length() - 1
                    values |= {(number << shift) & mask for number in range(int(span['min_value']), int(span['max_value']) + 1)}
                fields[f'{register["key"]}.{field["key"]}'] = values
        if fields:
            definitions[str(data.get('mcu') or path.stem).upper()] = fields
    return definitions


def resolve(field, fields):
    return next((name for name in field.split('|') if name in fields), None)


def check_against_definitions(graph, definitions):
    """Problems found by checking a graph against every definition it serves."""
    patterns = [re.compile(pattern) for pattern in graph['devices']]
    served = {name: fields for name, fields in definitions.items() if any(pattern.search(name) for pattern in patterns)}
    if not served:
        return [], 0
    unavailable = defaultdict(set)   # (node, option) -> MCUs without the value
    missing = defaultdict(set)       # field -> MCUs without it
    for name, fields in served.items():
        for node in graph['nodes']:
            writes = []
            for option in node.get('options', []):
                for field, value in (option.get('set') or {}).items():
                    writes.append((node['id'], option['id'], field, int(value, 16)))
            spec = node.get('range')
            if spec:
                for factor in range(spec['min'], spec['max'] + 1):
                    raw = factor * spec.get('scale', 1) + spec.get('offset', 0)
                    writes.append((node['id'], str(factor), spec['field'], raw << spec.get('lsb', 0)))
            for node_id, option_id, field, value in writes:
                actual = resolve(field, fields)
                if actual is None:
                    missing[field].add(name)
                elif value not in fields[actual]:
                    unavailable[(node_id, option_id, field)].add(name)
            if node.get('enable'):
                actual = resolve(node['enable']['field'], fields)
                if actual is None:
                    missing[node['enable']['field']].add(name)
                else:
                    for key in ('on', 'off'):
                        if int(node['enable'][key], 16) not in fields[actual]:
                            unavailable[(node['id'], f'enable.{key}', actual)].add(name)
        for setting in graph.get('settings', []):
            if resolve(setting, fields) is None:
                missing[setting].add(name)
    problems = []
    total = len(served)
    for field, names in sorted(missing.items()):
        problems.append(f'field {field} missing or hidden on {len(names)}/{total} MCUs (e.g. {sorted(names)[0]})')
    for (node_id, option_id, field), names in sorted(unavailable.items()):
        if len(names) == total:
            problems.append(f'node {node_id} option {option_id}: {field} value offered by none of the {total} MCUs (graph error or definition gap)')
    return problems, total


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--defs', help='folder with NECTO MCU definitions (def/<MCU>.json) to check field values against')
    parser.add_argument('--strict', action='store_true', help='with --defs, fail on fields missing from some MCUs too')
    args = parser.parse_args()

    failed = False
    graphs = load_graphs()
    for relative, graph in graphs.items():
        problems = check_graph(graph)
        if graph.get('id') and Path(relative).stem != graph['id']:
            problems.append(f'file name must be {graph["id"]}.json')
        for problem in problems:
            print(f'ERROR {relative}: {problem}')
        failed = failed or bool(problems)

    index_path = GRAPHS_ROOT / 'index.json'
    expected = build_index(graphs)
    if not index_path.exists() or json.loads(index_path.read_text(encoding='utf-8')) != expected:
        print('ERROR clock_graphs/index.json is stale: run python scripts/clock_graphs/build_index.py')
        failed = True

    if args.defs:
        definitions = load_definitions(args.defs)
        print(f'Loaded {len(definitions)} MCU definitions from {args.defs}')
        for relative, graph in graphs.items():
            problems, total = check_against_definitions(graph, definitions)
            print(f'{relative}: {total} MCUs')
            for problem in problems:
                hard = args.strict
                print(f'  {"ERROR" if hard else "note "} {problem}')
                failed = failed or hard

    print('Clock graphs are valid.' if not failed else 'Clock graph validation failed.')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
