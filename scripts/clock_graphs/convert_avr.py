"""Convert the AVR clock fuses of the NECTO mikroC AVR definitions into clock graphs
(clock_graphs/avr/*.json).

AVR parts select their clock with the LOW.SUT_CKSEL fuse (source and start-up time in one field)
and divide it by 8 with CKDIV8; mikroC programs the fuses from the definition's config_registers.
Each distinct SUT_CKSEL layout becomes one graph. A clock source is written as a masked value
(the bits all of its start-up variants share), so choosing a source keeps the start-up time.
XMEGA (runtime clock system) and parts without SUT_CKSEL are skipped.

  python scripts/clock_graphs/convert_avr.py --defs <AVR/mikroC/def folder> [--db <necto_db.db for max speeds>]
"""

import argparse
import json
import re
import sqlite3
from collections import OrderedDict
from pathlib import Path

from graphlib import GRAPHS_ROOT, REPO_ROOT, check_graph, hexv, write_graph

MHZ = 1000000


def classify(label):
    """(kind, frequency or (min, max)) for one SUT_CKSEL source label, or None."""
    text = label.strip()
    numbers = [float(n) for n in re.findall(r'(\d+(?:\.\d+)?)', text)]
    if re.search(r'Low-Freq\. Crystal|32\s*kHz', text, re.I):
        return 'fixed', 32768
    if re.search(r'128\s*kHz|WD128', text, re.I):
        return 'fixed', 128000
    if re.search(r'^PLL', text, re.I):
        return 'fixed', 16 * MHZ
    if re.search(r'ATtiny15 Comp', text):
        return 'fixed', 1600000
    if re.search(r'^Int\. RC Osc\.', text):
        return 'fixed', (numbers[0] * MHZ if numbers else 8 * MHZ)
    if re.search(r'Crystal/Resonator Low', text):
        return 'external', (400000, 900000)
    if re.search(r'Crystal/Resonator Medium', text):
        return 'external', (900000, 3 * MHZ)
    if re.search(r'Crystal/Resonator High', text):
        return 'external', (3 * MHZ, None)
    match = re.search(r'XOSC\s*(\d*\.?\d+)\s*-\s*(\d+)\s*MHz', text)
    if match:
        return 'external', (float(match.group(1)) * MHZ, float(match.group(2)) * MHZ)
    if re.search(r'^Ext\.|Full Swing', text, re.I):
        if len(numbers) >= 2:
            return 'external', (numbers[0] * MHZ, numbers[1] * MHZ)
        if len(numbers) == 1:
            low_open = re.search(r'-\s*\d', text) and not re.search(r'\d\s*-', text)
            return 'external', ((None, numbers[0] * MHZ) if low_open else (numbers[0] * MHZ, None))
        return 'external', (None, None)
    return None


def option_id(label):
    return re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_')[:40] or 'source'


def masked_groups(settings, field_mask):
    """Group SUT_CKSEL values by source label: [(label, value, mask)] or None when groups collide."""
    groups = OrderedDict()
    for setting in settings:
        label = re.split(r'[:;,]', setting['label'])[0].strip()
        groups.setdefault(label, []).append(int(str(setting['value']), 16))
    result = []
    for label, values in groups.items():
        mask = field_mask
        for value in values[1:]:
            mask &= ~(value ^ values[0])
        result.append((label, values[0] & mask, mask))
    for label, bits, mask in result:
        for other, values in groups.items():
            if other != label and any(value & mask == bits for value in values):
                return None
    return result


def build(name, mcus, layout, max_hz):
    sources, ckdiv8 = layout
    nodes = [{'id': 'ext', 'label': 'External clock / crystal', 'kind': 'source', 'x': 0, 'y': 1, 'input': 'ext',
              'tooltip': 'Frequency of the external clock, crystal, resonator or RC network.'}]
    options, constraints = [], []
    used = set()
    for label, bits, mask, (kind, data) in sources:
        oid = option_id(label)
        while oid in used:
            oid += '_'
        used.add(oid)
        option = {'id': oid, 'label': label, 'set': {'LOW.SUT_CKSEL': f'{hexv(bits)}/{hexv(mask)}'}}
        if kind == 'fixed':
            option['mul'] = int(data)
        else:
            option['from'] = 'ext'
            low, high = data
            parts = ([f'in.ext >= {int(low)}'] if low else []) + ([f'in.ext <= {int(high)}'] if high else [])
            if parts:
                constraints.append({'expr': f"sel.source != '{oid}' || ({' && '.join(parts)})",
                                    'message': f'{label}: the external frequency must be '
                                               f'{(low or 0) / MHZ:g}-{(high or max_hz) / MHZ:g} MHz.'})
        options.append(option)
    nodes.append({'id': 'source', 'label': 'Clock source (SUT_CKSEL)', 'kind': 'mux', 'x': 1, 'y': 0, 'options': options})
    fosc = 'source'
    if ckdiv8:
        field, divide, through = ckdiv8
        nodes.append({'id': 'cpu', 'label': 'CPU clock (CKDIV8)', 'kind': 'divider', 'x': 2, 'y': 0, 'max': max_hz, 'consumer': True,
                      'options': [{'id': '1', 'label': '/1', 'from': 'source', 'set': {field: hexv(through)}},
                                  {'id': '8', 'label': '/8', 'from': 'source', 'div': 8, 'set': {field: hexv(divide)}}]})
        fosc = 'cpu'
    else:
        nodes[-1].update(max=max_hz, consumer=True)
    shown = ', '.join(mcus[:4]) + (f' and {len(mcus) - 4} more' if len(mcus) > 4 else '')
    graph = {
        'schema': 1, 'id': name, 'title': f'AVR clock fuses ({shown})', 'vendor': 'Microchip',
        'source': 'NECTO mikroC AVR definitions (LOW.SUT_CKSEL, CKDIV8), AVR datasheets',
        'devices': [f'^{re.escape(mcu)}$' for mcu in mcus], 'fosc': fosc,
        'inputs': {'ext': {'label': 'External frequency', 'default': 8 * MHZ, 'min': 1, 'max': max_hz}},
        'settings': ['HIGH.CKOPT'], 'nodes': nodes, 'constraints': constraints,
    }
    return graph


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--defs', required=True, help='AVR/mikroC/def folder of core_packages')
    parser.add_argument('--db', help='necto_db.db, for each part\'s maximum frequency (max_speed)')
    args = parser.parse_args()

    speeds = {}
    if args.db:
        with sqlite3.connect(args.db) as db:
            speeds = {uid.upper(): float(speed or 0) * MHZ for uid, speed in db.execute("SELECT uid, max_speed FROM Devices WHERE uid LIKE 'AT%'")}
    layouts, skipped = OrderedDict(), []
    for path in sorted(Path(args.defs).glob('*.json')):
        mcu = path.stem.upper()
        if mcu.startswith('ATXMEGA'):
            continue
        data = json.loads(path.read_text(encoding='utf-8', errors='ignore'))
        fields = {f'{register["key"]}.{field["key"]}': field for register in data.get('config_registers') or [] for field in register['fields']}
        cksel = fields.get('LOW.SUT_CKSEL')
        if not cksel or not cksel.get('settings'):
            skipped.append(mcu)
            continue
        groups = masked_groups(cksel['settings'], int(str(cksel['mask']), 16))
        if not groups:
            skipped.append(f'{mcu} (ambiguous SUT_CKSEL groups)')
            continue
        sources = []
        for label, bits, mask in groups:
            kind = classify(label)
            if kind:
                sources.append((label, bits, mask, kind))
        ckdiv8 = None
        for field_id in ('LOW.CKDIV8', 'HIGH.CKDIV8'):
            field = fields.get(field_id)
            if field and field.get('settings'):
                values = {setting['label'].strip().lower(): int(str(setting['value']), 16) for setting in field['settings']}
                if 'set' in values and 'clear' in values:
                    ckdiv8 = (field_id, values['set'], values['clear'])
        ckopt = 'HIGH.CKOPT' in fields
        key = json.dumps([sources, ckdiv8, ckopt])
        layouts.setdefault(key, []).append(mcu)

    out_dir = GRAPHS_ROOT / 'avr'
    for old in out_dir.glob('*.json') if out_dir.exists() else []:
        old.unlink()
    written = 0
    for key, mcus in layouts.items():
        sources, ckdiv8, ckopt = json.loads(key)
        sources = [(label, bits, mask, tuple(kind)) for label, bits, mask, kind in sources]
        max_hz = max([speeds.get(mcu, 0) for mcu in mcus] + [0]) or 20 * MHZ
        name = 'avr_' + re.sub(r'[^a-z0-9]+', '_', mcus[0].lower())
        graph = build(name, mcus, (sources, ckdiv8), int(max_hz))
        graph['settings'] = ['HIGH.CKOPT'] if ckopt else []
        problems = check_graph(graph)
        if problems:
            print(f'{name}: NOT written, {"; ".join(problems)}')
            continue
        write_graph(graph, f'avr/{name}.json')
        written += 1
    print(f'Wrote {written} AVR clock graphs for {sum(len(m) for m in layouts.values())} MCUs to '
          f'{out_dir.relative_to(REPO_ROOT)}; skipped {len(skipped)}: {", ".join(skipped[:12])}{" ..." if len(skipped) > 12 else ""}')


if __name__ == '__main__':
    main()
