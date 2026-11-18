"""Convert the oscillator fuses of the NECTO mikroC PIC (PIC10/12/16/18) definitions into clock graphs
(clock_graphs/microchip_pic/*.json).

PIC parts pick their clock with configuration fuses that mikroC programs from config_registers:
FOSC/OSC (classic) or FEXTOSC + RSTOSC (newer parts), and a 4x PLL fuse (PLLEN/CFGPLLEN/PLLCFG).
The fuse labels name each source; external sources take the frequency you enter (with the label's
range as a constraint), fixed internal sources take the label's frequency, and an internal oscillator
whose frequency is chosen at runtime (OSCCON/OSCFRQ) takes the frequency your code sets. Each
distinct layout becomes one graph. USB parts with CPUDIV/PLLDIV are not converted yet.

  python scripts/clock_graphs/convert_pic.py --defs <PIC/mikroC/def folder> [--xc8 <PIC/XC8/def folder>] [--db <necto_db.db>]

With --xc8 each graph also gets a symbols table, matching the XC8 config_words (symbolic FOSC = HSMP)
to the mikroC values by their labels, so the same graph drives XC8 setups.
"""

import argparse
import json
import re
import sqlite3
from collections import OrderedDict
from pathlib import Path

from graphlib import GRAPHS_ROOT, REPO_ROOT, check_graph, hexv, write_graph

MHZ = 1000000
PLL_FIELDS = ('PLLEN', 'CFGPLLEN', 'PLLCFG')


def mhz_numbers(label):
    """Frequencies named in a label, in Hz (MHz unless followed by kHz)."""
    values = []
    for number, unit in re.findall(r'(\d+(?:\.\d+)?)\s*(MHz|kHz)?', label, re.I):
        if unit:
            values.append(float(number) * (1000 if unit.lower() == 'khz' else MHZ))
    return values


FREQ = r'(\d+(?:\.\d+)?)\s*(khz|mhz)'


def hz(number, unit):
    return float(number) * (1000 if unit == 'khz' else MHZ)


def external_range(label):
    """(low, high) Hz from wording such as '4-16 MHz', '500 kHz-16 MHz', '<500 kHz', 'above 8MHz'."""
    text = label.lower()
    match = re.search(r'(\d+(?:\.\d+)?)\s*(khz|mhz)?\s*(?:-|to)\s*' + FREQ, text)
    if match:
        return hz(match.group(1), match.group(2) or match.group(4)), hz(match.group(3), match.group(4))
    match = re.search(r'(?:<|below|up to)\s*' + FREQ, text)
    if match:
        return None, hz(*match.groups())
    match = re.search(r'(?:>|above|over)\s*' + FREQ, text)
    if match:
        return hz(*match.groups()), None
    if text.startswith('xt'):
        return 100000, 4 * MHZ
    if text.startswith('hs'):
        return 4 * MHZ, None
    if text.startswith('ecl'):
        return None, 500000
    if text.startswith('ecm'):
        return 500000, 8 * MHZ
    if text.startswith('ech'):
        return 8 * MHZ, None
    return None, None


def classify(label):
    """(kind, data) for an oscillator fuse option: fixed Hz, ext range, ext x4, int (runtime), fextosc, skip."""
    text = label.lower().strip()
    if 'not enabled' in text or 'oscillator disabled' in text:
        return None
    multiplier = 4 if re.search(r'4\s*x|x\s*4|4x', text) and 'pll' in text else (2 if re.search(r'2\s*x|2x', text) and 'pll' in text else 1)
    match = re.search(r'(?:hffrq|oscfrq)\s*=\s*(\d+(?:\.\d+)?)\s*mhz(?:.*cdiv\s*=\s*1\s*:\s*(\d+))?', text)
    if match:
        return 'fixed', float(match.group(1)) * MHZ * multiplier / int(match.group(2) or 1)
    match = re.search(r'hfintosc\s*\(\s*(\d+(?:\.\d+)?)\s*mhz\s*\)', text)
    if match:
        return 'fixed', float(match.group(1)) * MHZ * multiplier
    if 'lfintosc' in text or re.search(r'31(\.\d+)?\s*khz', text):
        return 'fixed', 31000
    if text.startswith('sosc') or 'secondary oscillator' in text:
        return 'fixed', 32768
    if 'extosc operating per fextosc' in text or 'extosc with' in text:
        return 'fextosc', multiplier
    if re.search(r'intosc|internal|intrc|hfintosc|intio', text):
        return 'internal', multiplier
    if text.startswith('lp'):
        return 'fixed', 32768
    if re.search(r'^(xt|hs|ec|ech|ecm|ecl|rc|extrc|external rc|external clock)\b', text) or text.startswith(('xt ', 'hs ', 'ec ')):
        low, high = external_range(label)
        return 'external', (low, high, multiplier)
    return None


def option_id(label, used):
    base = re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_')[:32] or 'source'
    oid = base
    while oid in used:
        oid += '_'
    used.add(oid)
    return oid


def range_rule(oid, label, low, high, node='source'):
    parts = ([f'in.ext >= {int(low)}'] if low else []) + ([f'in.ext <= {int(high)}'] if high else [])
    if not parts:
        return None
    return {'expr': f"sel.{node} != '{oid}' || ({' && '.join(parts)})",
            'message': f'{label.split(",")[0]}: the external frequency must be {(low or 0) / MHZ:g}-{(high or 0) / MHZ:g} MHz.'.replace('-0 MHz', ' MHz or more')}


def convert(mcu, fields, max_hz):
    """One MCU's graph body (nodes, constraints, inputs) or None when its fuses are not understood."""
    primary = next((key for key in fields if key.endswith('.RSTOSC')), None)
    oscillator = primary or next((key for key in fields if re.match(r'.*\.(FOSC|OSC|FOSC0)$', key)), None)
    if not oscillator or any(key.endswith(('.CPUDIV', '.PLLDIV')) for key in fields):
        return None
    nodes = [{'id': 'ext', 'label': 'External oscillator / clock', 'kind': 'source', 'x': 0, 'y': 1, 'input': 'ext'},
             {'id': 'intosc', 'label': 'Internal oscillator (set by your code)', 'kind': 'source', 'x': 0, 'y': 3, 'input': 'intosc',
              'tooltip': 'The internal oscillator frequency is chosen at runtime (OSCCON/OSCFRQ): enter the frequency your code sets.'}]
    constraints, used, options = [], set(), []
    fext = next((key for key in fields if key.endswith('.FEXTOSC')), None)
    if fext:
        fext_options, fused = [], set()
        for setting in fields[fext]['settings']:
            kind = classify(setting['label'])
            if not kind or kind[0] not in ('external', 'fixed'):
                continue
            oid = option_id(setting['label'], fused)
            option = {'id': oid, 'label': setting['label'].split(',')[0].strip(), 'set': {fext: hexv(int(setting['value'], 16))}}
            if kind[0] == 'fixed':
                option['mul'] = int(kind[1])
            else:
                option['from'] = 'ext'
                rule = range_rule(oid, option['label'], kind[1][0], kind[1][1], 'fextosc')
                if rule:
                    constraints.append(rule)
            fext_options.append(option)
        if fext_options:
            nodes.append({'id': 'fextosc', 'label': 'External oscillator (FEXTOSC)', 'kind': 'mux', 'x': 1, 'y': 1, 'options': fext_options})
    for setting in fields[oscillator]['settings']:
        label = setting['label'].strip()
        kind = classify(label)
        if not kind:
            continue
        oid = option_id(label, used)
        option = {'id': oid, 'label': label[:60], 'set': {oscillator: hexv(int(setting['value'], 16))}}
        if kind[0] == 'fixed':
            option['mul'] = int(kind[1])
        elif kind[0] == 'internal':
            option.update({'from': 'intosc', 'mul': kind[1]})
        elif kind[0] == 'fextosc':
            if not fext:
                continue
            option.update({'from': 'fextosc', 'mul': kind[1]})
        else:
            low, high, multiplier = kind[1]
            option.update({'from': 'ext', 'mul': multiplier})
            rule = range_rule(oid, label, low, high)
            if rule:
                constraints.append(rule)
        options.append(option)
    if not options:
        return None
    nodes.append({'id': 'source', 'label': f'Oscillator ({oscillator.split(".")[-1]})', 'kind': 'mux', 'x': 2, 'y': 1, 'options': options})
    fosc = 'source'
    pll = next((key for key in fields if key.split('.')[-1] in PLL_FIELDS), None)
    if pll:
        values = {}
        for setting in fields[pll]['settings']:
            text = setting['label'].lower()
            values['off' if re.search(r'disab|off|direct|not', text) else 'on'] = int(setting['value'], 16)
        if 'on' in values and 'off' in values:
            nodes.append({'id': 'pll', 'label': f'4x PLL ({pll.split(".")[-1]})', 'kind': 'multiplier', 'x': 3, 'y': 1,
                          'options': [{'id': '1', 'label': 'x1 (PLL off)', 'from': 'source', 'set': {pll: hexv(values['off'])}},
                                      {'id': '4', 'label': 'x4 (PLL on)', 'from': 'source', 'mul': 4, 'set': {pll: hexv(values['on'])}}]})
            fosc = 'pll'
    next(node for node in nodes if node['id'] == fosc).update(max=max_hz, consumer=True)
    return nodes, constraints


def normalize(label):
    return re.sub(r'\s+', ' ', re.sub(r'^[01X]{3,4}\s+', '', label.strip())).lower()


def pll_state(label):
    return 'off' if re.search(r'disab|off|direct|not', label.lower()) else 'on'


def xc8_symbols(mcus, mikroc_fields, xc8_root):
    """graph.symbols for the fuse fields of these MCUs, from their XC8 definitions (labels matched)."""
    table, conflicts = {}, set()
    for mcu in mcus:
        path = Path(xc8_root) / f'{mcu}.json'
        if not path.exists():
            continue
        words = json.loads(path.read_text(encoding='utf-8', errors='ignore')).get('config_words') or []
        fields = mikroc_fields[mcu]
        for word in words:
            field_id = f'{word.get("label_group")}.{word.get("key")}'
            if field_id not in fields:
                continue
            numeric = fields[field_id]['settings']
            is_pll = word['key'] in PLL_FIELDS
            for setting in word.get('settings') or []:
                if is_pll:
                    match = next((item for item in numeric if pll_state(item['label']) == pll_state(setting['label'])), None)
                else:
                    match = next((item for item in numeric if normalize(item['label']) == normalize(setting['label'])), None)
                if not match:
                    continue
                value = hexv(int(match['value'], 16))
                previous = table.setdefault(field_id, {}).setdefault(str(setting['value']), value)
                if previous != value:
                    conflicts.add((field_id, str(setting['value'])))
    for field_id, symbol in conflicts:
        table[field_id].pop(symbol, None)
    return {field: symbols for field, symbols in table.items() if symbols}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--defs', required=True, help='PIC/mikroC/def folder of core_packages')
    parser.add_argument('--xc8', help='PIC/XC8/def folder: add XC8 symbols to the graphs')
    parser.add_argument('--db', help='necto_db.db, for each part\'s maximum frequency (max_speed)')
    args = parser.parse_args()

    speeds = {}
    if args.db:
        with sqlite3.connect(args.db) as db:
            speeds = {uid.upper(): float(speed or 0) * MHZ for uid, speed in db.execute("SELECT uid, max_speed FROM Devices WHERE uid LIKE 'PIC1%'")}
    mikroc_fields = {}
    layouts, skipped = OrderedDict(), []
    for path in sorted(Path(args.defs).glob('*.json')):
        mcu = path.stem.upper()
        data = json.loads(path.read_text(encoding='utf-8', errors='ignore'))
        fields = {}
        for register in data.get('config_registers') or []:
            for field in register['fields']:
                key = field['key']
                if field.get('settings') and not field.get('hidden') and \
                        (key in ('FOSC', 'OSC', 'FOSC0', 'FEXTOSC', 'RSTOSC', 'CPUDIV', 'PLLDIV') or key in PLL_FIELDS):
                    fields[f'{register["key"]}.{key}'] = field
        mikroc_fields[mcu] = fields
        body = convert(mcu, fields, 1)
        if not body:
            skipped.append(mcu)
            continue
        nodes, constraints = body
        key = json.dumps([nodes, constraints])
        layouts.setdefault(key, []).append(mcu)

    out_dir = GRAPHS_ROOT / 'microchip_pic'
    for old in out_dir.glob('*.json') if out_dir.exists() else []:
        old.unlink()
    written = 0
    for key, mcus in layouts.items():
        nodes, constraints = json.loads(key)
        max_hz = int(max([speeds.get(mcu, 0) for mcu in mcus] + [0]) or 64 * MHZ)
        for node in nodes:
            if node.get('consumer'):
                node['max'] = max_hz
        name = 'pic_' + re.sub(r'[^a-z0-9]+', '_', mcus[0].lower())
        shown = ', '.join(mcus[:4]) + (f' and {len(mcus) - 4} more' if len(mcus) > 4 else '')
        fosc = next(node['id'] for node in nodes if node.get('consumer'))
        graph = {
            'schema': 1, 'id': name, 'title': f'PIC oscillator fuses ({shown})', 'vendor': 'Microchip',
            'source': 'NECTO mikroC PIC definitions (oscillator configuration fuses), PIC datasheets',
            'devices': [f'^{re.escape(mcu)}$' for mcu in mcus], 'fosc': fosc,
            'inputs': {'ext': {'label': 'External frequency', 'default': 8 * MHZ, 'min': 1, 'max': max_hz},
                       'intosc': {'label': 'Internal oscillator frequency', 'default': 8 * MHZ, 'min': 31000, 'max': max_hz}},
            'settings': [], 'nodes': nodes, 'constraints': constraints,
        }
        if args.xc8:
            symbols = xc8_symbols(mcus, mikroc_fields, args.xc8)
            if symbols:
                graph['symbols'] = symbols
        problems = check_graph(graph)
        if problems:
            print(f'{name}: NOT written, {"; ".join(problems)}')
            continue
        write_graph(graph, f'microchip_pic/{name}.json')
        written += 1
    print(f'Wrote {written} PIC clock graphs for {sum(len(m) for m in layouts.values())} MCUs to {out_dir.relative_to(REPO_ROOT)}; '
          f'skipped {len(skipped)} (USB CPUDIV/PLLDIV parts or fuses not understood): {", ".join(skipped[:10])}{" ..." if len(skipped) > 10 else ""}')


if __name__ == '__main__':
    main()
