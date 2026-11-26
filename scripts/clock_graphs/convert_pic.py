"""Convert the oscillator fuses of the NECTO mikroC PIC (PIC10/12/16/18) definitions into clock graphs
(clock_graphs/microchip_pic/*.json).

PIC parts pick their clock with configuration fuses that mikroC programs from config_registers:
FOSC/OSC (classic) or FEXTOSC + RSTOSC (newer parts), and a 4x PLL fuse (PLLEN/CFGPLLEN/PLLCFG).
The fuse labels name each source; external sources take the frequency you enter (with the label's
range as a constraint), fixed internal sources take the label's frequency, and an internal oscillator
whose frequency is chosen at runtime (OSCCON/OSCFRQ) takes the frequency your code sets. Each
distinct layout becomes one graph. USB parts with CPUDIV/PLLDIV are written by hand instead
(microchip_pic_usb_graphs.py).

  python scripts/clock_graphs/convert_pic.py --defs <PIC/mikroC/def folder> [--xc8 <PIC/XC8/def folder>]
                                             [--edc <DFP edc folder>] [--db <necto_db.db>]

With --xc8 each graph also gets a symbols table, matching the XC8 config_words (symbolic FOSC = HSMP)
to the mikroC values by their labels (the text before '; PFM ...' remarks when the wording differs), so
the same graph drives XC8 setups. Parts that only have an XC8 definition are converted too: their numeric
fuse values come from a mikroC part with the same XC8 oscillator settings, or, with --edc, from the
part's EDC file (<MCU>.PIC) of the Microchip device family pack (edc/ folder of the .atpack, Apache-2.0).
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


def head(label):
    """A label without the trailing remarks the mikroC and XC8 definitions word differently ('; PFM set to ...')."""
    return re.split(r';|:\s|\(fosc', normalize(label))[0].strip(' ,')


def match_label(numeric, label):
    """The mikroC setting naming the same option as an XC8 label: same text, same head, or a unique prefix."""
    found = [item for item in numeric if normalize(item['label']) == normalize(label)]
    if found:
        return found[0]  # several: the same option encoded more than once ('11XX', '0011'), any of them will do
    found = [item for item in numeric if head(item['label']) == head(label)]
    if len(found) == 1:
        return found[0]
    wanted = head(label)
    found = [item for item in numeric if head(item['label']) and (wanted.startswith(head(item['label'])) or head(item['label']).startswith(wanted))]
    return found[0] if len(found) == 1 else None


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
                    match = match_label(numeric, setting['label'])
                if not match:
                    continue
                value = hexv(int(match['value'], 16))
                previous = table.setdefault(field_id, {}).setdefault(str(setting['value']), value)
                if previous != value:
                    conflicts.add((field_id, str(setting['value'])))
    for field_id, symbol in conflicts:
        table[field_id].pop(symbol, None)
    return {field: symbols for field, symbols in table.items() if symbols}


EDC_PARTS = set()  # XC8-only parts whose fuse values came from a DFP EDC file
OSC_KEYS = ('FOSC', 'OSC', 'FOSC0', 'FEXTOSC', 'RSTOSC', 'CPUDIV', 'PLLDIV') + PLL_FIELDS


def xc8_oscillator_words(path):
    words = json.loads(path.read_text(encoding='utf-8', errors='ignore')).get('config_words') or []
    return {f'{word.get("label_group")}.{word["key"]}': word for word in words
            if word.get('key') in OSC_KEYS and word.get('settings') and not word.get('hidden')}


def donor_values(words, donor_words, donor_fields):
    """field id -> {XC8 symbol: numeric value} of a mikroC part, through its own XC8 labels."""
    table = {}
    for field_id, word in donor_words.items():
        numeric = donor_fields.get(field_id)
        if not numeric:
            continue
        is_pll = word['key'] in PLL_FIELDS
        for setting in word['settings']:
            if is_pll:
                match = next((item for item in numeric['settings'] if pll_state(item['label']) == pll_state(setting['label'])), None)
            else:
                match = match_label(numeric['settings'], setting['label'])
            if match:
                table.setdefault(field_id, {})[str(setting['value'])] = match['value']
    return table


def edc_fields(path, words):
    """Numeric fuse fields from a DFP EDC file: each DCRFieldSemantic's value shifted to the field's position."""
    text = path.read_text(encoding='utf-8', errors='ignore')
    fields = {}
    for field_id, word in words.items():
        group, key = field_id.split('.', 1)
        register = re.search(r'<edc:DCRDef\b[^>]*edc:cname="%s".*?</edc:DCRDef>' % re.escape(group), text, re.S)
        if not register:
            return None
        position, found = 0, None
        for item in re.finditer(r'<edc:AdjustPoint\b[^>]*edc:offset="([^"]+)"|<edc:DCRFieldDef\b([^>]*)>(.*?)</edc:DCRFieldDef>',
                                register.group(0), re.S):
            if item.group(1):
                position += int(item.group(1), 0)
                continue
            attributes = dict(re.findall(r'edc:(\w+)="([^"]*)"', item.group(2)))
            if attributes.get('cname') == key:
                found = {semantic['cname']: int(re.search(r'==\s*(0x[0-9A-Fa-f]+|\d+)', semantic['when']).group(1), 0) << position
                         for semantic in (dict(re.findall(r'edc:(\w+)="([^"]*)"', tag))
                                          for tag in re.findall(r'<edc:DCRFieldSemantic\b[^>]*>', item.group(3)))
                         if semantic.get('cname') and re.search(r'==\s*(0x[0-9A-Fa-f]+|\d+)', semantic.get('when', ''))}
                break
            position += int(attributes.get('nzwidth', '0'), 0)
        if not found:
            return None
        settings = [{'value': hexv(found[str(setting['value'])]), 'label': setting['label']}
                    for setting in word['settings'] if str(setting['value']) in found]
        fields[field_id] = {'key': key, 'settings': settings}
    return fields


def xc8_only_fields(xc8_root, mikroc_fields, edc_root=None):
    """Numeric fuse fields for parts that only have an XC8 definition (symbolic config_words).

    The numbers come from a mikroC part (the donor) whose XC8 definition names the same oscillator fields:
    a donor with the very same XC8 settings lends its mikroC fields unchanged (so the part joins the donor's
    graph); otherwise each XC8 symbol takes the number the donor's mikroC definition gives the same symbol.
    Parts without a donor covering every symbol get no fields (and are reported as skipped)."""
    donors = {}
    for mcu in mikroc_fields:
        path = Path(xc8_root) / f'{mcu}.json'
        if path.exists():
            donors[mcu] = xc8_oscillator_words(path)
    result = {}
    for path in sorted(Path(xc8_root).glob('*.json')):
        mcu = path.stem.upper()
        if mcu in mikroc_fields:
            continue
        words = xc8_oscillator_words(path)
        signature = json.dumps(words, sort_keys=True)
        exact = next((donor for donor, donor_words in donors.items()
                      if json.dumps(donor_words, sort_keys=True) == signature and set(mikroc_fields[donor]) >= set(words)), None)
        if exact:
            result[mcu] = {field_id: mikroc_fields[exact][field_id] for field_id in words}
            continue
        result[mcu] = {}
        for donor, donor_words in donors.items():
            if set(donor_words) != set(words):
                continue
            table = donor_values(words, donor_words, mikroc_fields[donor])
            wanted = {(field_id, str(setting['value'])) for field_id, word in words.items() for setting in word['settings']
                      if classify(setting['label']) or word['key'] in PLL_FIELDS}
            if all(symbol in table.get(field_id, {}) for field_id, symbol in wanted):
                result[mcu] = {field_id: {'key': word['key'], 'settings': [
                    {'value': table[field_id][str(setting['value'])], 'label': setting['label']}
                    for setting in word['settings'] if str(setting['value']) in table.get(field_id, {})]} for field_id, word in words.items()}
                break
        if not result[mcu] and edc_root and (Path(edc_root) / f'{path.stem}.PIC').exists():
            result[mcu] = edc_fields(Path(edc_root) / f'{path.stem}.PIC', words) or {}
            if result[mcu]:
                EDC_PARTS.add(mcu)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--defs', required=True, help='PIC/mikroC/def folder of core_packages')
    parser.add_argument('--xc8', help='PIC/XC8/def folder: add XC8 symbols to the graphs')
    parser.add_argument('--edc', help='edc/ folder of Microchip DFPs: fuse values of XC8-only parts without a mikroC donor')
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

    if args.xc8:
        for mcu, fields in xc8_only_fields(args.xc8, mikroc_fields, args.edc).items():
            mikroc_fields[mcu] = fields
            body = convert(mcu, fields, 1) if fields else None
            if not body:
                skipped.append(mcu)
                continue
            layouts.setdefault(json.dumps(list(body)), []).append(mcu)

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
            'source': 'NECTO mikroC PIC definitions (oscillator configuration fuses), PIC datasheets'
                      + ('; fuse values of XC8-only parts from the Microchip DFP EDC files' if EDC_PARTS & set(mcus) else ''),
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
          f'skipped {len(skipped)} (USB CPUDIV/PLLDIV parts, written by microchip_pic_usb_graphs.py, or fuses not understood): {", ".join(skipped[:10])}{" ..." if len(skipped) > 10 else ""}')


if __name__ == '__main__':
    main()
