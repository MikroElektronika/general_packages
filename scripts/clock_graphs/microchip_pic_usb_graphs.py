"""Write the clock graphs of the USB PIC16/PIC18 parts (clock_graphs/microchip_pic_usb/*.json).

convert_pic.py cannot convert these: their system clock also goes through a USB PLL (PLLDIV prescaler
to 4 MHz and a 96 MHz PLL, or a 3x/4x PLL) and a CPU divider (CPUDIV). The trees are written by hand
from the data sheets' oscillator chapters (PIC18F2455/2550/4455/4550, PIC18FxxJ50/J53/J13, PIC18F8xJ5x,
PIC18FxxJ94/J99, PIC18F13K50/14K50, PIC18F2xK50/45K50, PIC16F145x) and read the oscillator labels the
way convert_pic.py does (crystal ranges, internal oscillator). The fuse values come from the parts' EDC
files (<MCU>.PIC, edc/ folder of the Microchip device family packs, Apache-2.0), the same absolute values
the mikroC definitions use, so one graph drives XC8 (symbolic config_words, through graph.symbols) and
mikroC (numeric config_registers).

Runtime choices stay runtime choices: the internal oscillator frequency your code selects (OSCCON) is
entered, and PLLs enabled only by code (OSCTUNE.PLLEN, SPLLEN) are shown as configured by the fuses.

  python scripts/clock_graphs/microchip_pic_usb_graphs.py --xc8 <PIC/XC8/def folder> --edc <folder with DFP edc/*.PIC files>
"""

import argparse
import json
import re
from collections import OrderedDict
from pathlib import Path

from convert_pic import classify, edc_fields, option_id, range_rule
from graphlib import GRAPHS_ROOT, REPO_ROOT, check_graph, write_graph
from microchip_dspic_graphs import fixed, khz, posc_derive, posc_nodes, prune, runtime_divider
from stm32_graphs import MHZ, graph

OSC_KEYS = ('FOSC', 'OSC')
BOUND = OSC_KEYS + ('PLLDIV', 'CPUDIV', 'PLLSEL', 'PLLEN', 'CFGPLLEN', 'PLLMULT', 'POSCMD')
SETTINGS = ('USBDIV', 'LS48MHZ', 'USBLSCLK', 'PCLKEN', 'FCMEN', 'IESO', 'CLKOEC', 'CLKOEN', 'CLKOUTEN', 'SOSCSEL')
SOURCE = ('PIC16F145x/PIC18 USB data sheets (Oscillator sections); fuse values from the Microchip DFP EDC files')


def field_of(fields, *keys):
    return next((field for field in fields if field.split('.')[1] in keys), None)


def cpudiv_factors(label):
    """(primary divider, 96 MHz PLL divider) from a CPUDIV label; one divider for both when the label names one."""
    match = re.search(r'Primary Oscillator Src:\s*/(\d+).*?PLL Src:\s*/(\d+)', label)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r'(?:divided|divide) by\s*(\d+)', label, re.I)
    number = int(match.group(1)) if match else 1
    return number, number


def usb_pll(fields, labels, tables, settings):
    """PIC18F2455/4550, PIC18FxxJ50/J53/J13, PIC18F8xJ5x: PLLDIV prescaler -> 96 MHz PLL, CPUDIV."""
    osc = field_of(fields, *OSC_KEYS)
    plldiv, cpudiv, pllsel = field_of(fields, 'PLLDIV'), field_of(fields, 'CPUDIV'), field_of(fields, 'PLLSEL')
    two_dividers = cpudiv and any('PLL Src' in label for label in labels[cpudiv].values())
    nodes = [{'id': 'ext', 'label': 'External oscillator / clock', 'kind': 'source', 'x': 0, 'y': 1, 'input': 'ext'},
             {'id': 'intosc', 'label': 'Internal oscillator (set by your code)', 'kind': 'source', 'x': 0, 'y': 3, 'input': 'intosc',
              'tooltip': 'The internal oscillator frequency is chosen at runtime (OSCCON.IRCF): enter the frequency your code sets.'},
             fixed('int8', 'INTOSC 8 MHz (PLL)', 0, 4, 8 * MHZ)]
    constraints, used, options, pll_ids, int_ids = [], set(), [], [], []
    for symbol, value in tables[osc].items():
        label = labels[osc][symbol]
        kind = classify(label)
        if not kind:
            raise SystemExit(f'{osc}: {symbol} ({label}) not understood')
        oid = option_id(symbol, used)
        option = {'id': oid, 'label': label[:60], 'set': {osc: value}}
        if 'PLL' in symbol:
            option.update({'from': 'pll', 'keeps': ['int8' if symbol.startswith('INTOSC') else 'ext']})
            pll_ids.append(oid)
            if kind[0] == 'external':
                rule = range_rule(oid, label, kind[1][0], kind[1][1], 'primary')
                constraints.extend([rule] if rule else [])
        elif kind[0] == 'internal':
            option['from'] = 'intosc'
            int_ids.append(oid)
        elif kind[0] == 'fixed':
            option['mul'] = int(kind[1])
        else:
            option['from'] = 'ext'
            rule = range_rule(oid, label, kind[1][0], kind[1][1], 'primary')
            constraints.extend([rule] if rule else [])
        options.append(option)
    in_pll = ' || '.join(f"sel.primary == '{oid}'" for oid in pll_ids) or '0'
    int_pll = [oid for oid in pll_ids if oid.startswith('intosc')]
    pllsrc = [{'id': 'ext', 'label': 'External oscillator', 'from': 'ext'}]
    if int_pll:
        pllsrc[0]['when'] = ' && '.join(f"sel.primary != '{oid}'" for oid in int_pll)
        pllsrc.append({'id': 'int8', 'label': 'INTOSC 8 MHz', 'from': 'int8', 'when': ' || '.join(f"sel.primary == '{oid}'" for oid in int_pll)})
    nodes.append({'id': 'pllsrc', 'label': 'PLL input', 'kind': 'mux', 'x': 1, 'y': 0, 'options': pllsrc})
    nodes.append({'id': 'prediv', 'label': 'PLL prescaler (PLLDIV)', 'kind': 'divider', 'x': 2, 'y': 0,
                  'tooltip': 'Divides the oscillator to the 4 MHz the 96 MHz PLL needs.',
                  'options': [{'id': symbol, 'label': f'/{symbol}', 'from': 'pllsrc', 'div': int(symbol), 'set': {plldiv: value}}
                              for symbol, value in tables[plldiv].items()]})
    note = 'The PLL runs once CFGPLLEN is ON or your code sets OSCTUNE.PLLEN.' if field_of(fields, 'CFGPLLEN') or not two_dividers else ''
    if pllsel:
        nodes.append({'id': 'pll', 'label': 'PLL (PLLSEL)', 'kind': 'multiplier', 'x': 3, 'y': 0, 'tooltip': note,
                      'options': [{'id': 'pll96', 'label': '96 MHz PLL /2', 'from': 'prediv', 'mul': 12, 'set': {pllsel: tables[pllsel]['PLL96']}},
                                  {'id': 'pll4x', 'label': '4x PLL', 'from': 'prediv', 'mul': 4, 'set': {pllsel: tables[pllsel]['PLL4X']}}]})
        need4 = "sel.pll == 'pll96'"
    elif two_dividers:
        nodes.append({'id': 'pll', 'label': '96 MHz PLL', 'kind': 'multiplier', 'x': 3, 'y': 0,
                      'options': [{'id': '24', 'label': 'x24', 'from': 'prediv', 'mul': 24}]})
        need4 = '1'
    else:
        nodes.append({'id': 'pll', 'label': '96 MHz PLL /2', 'kind': 'multiplier', 'x': 3, 'y': 0, 'tooltip': note,
                      'options': [{'id': '12', 'label': 'x24 /2', 'from': 'prediv', 'mul': 12}]})
        need4 = '1'
    constraints.append({'expr': f"!({in_pll}) || !({need4}) || (f.prediv >= 3990000 && f.prediv <= 4010000)",
                        'message': 'The 96 MHz PLL needs 4 MHz: choose PLLDIV so that the oscillator / PLLDIV is 4 MHz.'})
    nodes.append({'id': 'primary', 'label': f'Oscillator ({osc.split(".")[1]})', 'kind': 'mux', 'x': 4, 'y': 1, 'options': options})
    if cpudiv:
        divs = []
        for symbol, value in tables[cpudiv].items():
            osc_div, pll_div = cpudiv_factors(labels[cpudiv][symbol])
            if two_dividers:
                divs.append({'id': f'p{pll_div}', 'label': f'/{pll_div} (PLL)', 'from': 'primary', 'div': pll_div, 'set': {cpudiv: value}, 'when': in_pll})
                divs.append({'id': f'o{osc_div}', 'label': f'/{osc_div}', 'from': 'primary', 'div': osc_div, 'set': {cpudiv: value}, 'when': f'!({in_pll})'})
            else:
                divs.append({'id': str(osc_div), 'label': f'/{osc_div}', 'from': 'primary', 'div': osc_div, 'set': {cpudiv: value}})
        bypass = ' || '.join(f"sel.primary == '{oid}'" for oid in int_ids)
        node = {'id': 'sysclk', 'label': 'CPU clock (CPUDIV)', 'kind': 'divider', 'x': 5, 'y': 1, 'options': divs}
        if bypass:
            node['bypass'] = bypass
            node['tooltip'] = 'CPUDIV divides the primary oscillator and the PLL, not the internal oscillator.'
        nodes.append(node)
    else:
        nodes.append({'id': 'sysclk', 'label': 'CPU clock', 'kind': 'output', 'x': 5, 'y': 1,
                      'options': [{'id': '1', 'label': '/1', 'from': 'primary'}]})
    inputs = {'ext': {'label': 'External frequency', 'default': 8 * MHZ, 'min': 1, 'max': 48 * MHZ},
              'intosc': {'label': 'Internal oscillator frequency', 'default': 8 * MHZ, 'min': 31000, 'max': 8 * MHZ}}
    return nodes, inputs, [], constraints, 48 * MHZ


def multiplier_pll(fields, labels, tables, settings):
    """PIC18F13K50/14K50, PIC18F2xK50/45K50, PIC16F145x: oscillator -> 3x/4x PLL -> CPUDIV."""
    osc, cpudiv = field_of(fields, *OSC_KEYS), field_of(fields, 'CPUDIV')
    enable = field_of(fields, 'PLLEN', 'CFGPLLEN')
    multiplier = field_of(fields, 'PLLSEL', 'PLLMULT')
    nodes = [{'id': 'ext', 'label': 'External oscillator / clock', 'kind': 'source', 'x': 0, 'y': 1, 'input': 'ext'},
             {'id': 'intosc', 'label': 'Internal oscillator (set by your code)', 'kind': 'source', 'x': 0, 'y': 3, 'input': 'intosc',
              'tooltip': 'The internal oscillator frequency is chosen at runtime (OSCCON.IRCF): 16 MHz (HFINTOSC) feeds the 3x PLL.'}]
    constraints, used, options = [], set(), []
    for symbol, value in tables[osc].items():
        label = labels[osc][symbol]
        kind = classify(label)
        if not kind:
            raise SystemExit(f'{osc}: {symbol} ({label}) not understood')
        oid = option_id(symbol, used)
        option = {'id': oid, 'label': label[:60], 'set': {osc: value}}
        if kind[0] == 'internal':
            option['from'] = 'intosc'
        elif kind[0] == 'fixed':
            option['mul'] = int(kind[1])
        else:
            option['from'] = 'ext'
            rule = range_rule(oid, label, kind[1][0], kind[1][1], 'primary')
            constraints.extend([rule] if rule else [])
        options.append(option)
    nodes.append({'id': 'primary', 'label': f'Oscillator ({osc.split(".")[1]})', 'kind': 'mux', 'x': 1, 'y': 1, 'options': options})
    on = next(symbol for symbol, label in labels[enable].items() if not re.search(r'disab|off|software|firmware', label, re.I))
    off = next(symbol for symbol in tables[enable] if symbol != on)
    pll_options = [{'id': 'off', 'label': 'PLL off (or enabled by your code)', 'from': 'primary', 'set': {enable: tables[enable][off]}}]
    if multiplier:
        for symbol, value in tables[multiplier].items():
            factor = int(re.search(r'(\d)', symbol).group(1))
            pll_options.append({'id': f'x{factor}', 'label': f'x{factor}', 'from': 'primary', 'mul': factor,
                                'set': {enable: tables[enable][on], multiplier: value}})
    else:
        pll_options.append({'id': 'x4', 'label': 'x4', 'from': 'primary', 'mul': 4, 'set': {enable: tables[enable][on]}})
    nodes.append({'id': 'pll', 'label': f'PLL ({enable.split(".")[1]})', 'kind': 'multiplier', 'x': 2, 'y': 1, 'max': 48 * MHZ, 'options': pll_options,
                  'tooltip': 'USB needs 48 MHz from the PLL: 12 MHz x4 or 16 MHz x3.'})
    nodes.append({'id': 'sysclk', 'label': 'CPU clock (CPUDIV)', 'kind': 'divider', 'x': 3, 'y': 1,
                  'options': [{'id': str(cpudiv_factors(labels[cpudiv][symbol])[0]), 'label': f'/{cpudiv_factors(labels[cpudiv][symbol])[0]}',
                               'from': 'pll', 'div': cpudiv_factors(labels[cpudiv][symbol])[0], 'set': {cpudiv: value}}
                              for symbol, value in tables[cpudiv].items()]})
    inputs = {'ext': {'label': 'External frequency', 'default': 12 * MHZ, 'min': 1, 'max': 48 * MHZ},
              'intosc': {'label': 'Internal oscillator frequency', 'default': 16 * MHZ, 'min': 31000, 'max': 16 * MHZ}}
    return nodes, inputs, [], constraints, 48 * MHZ


def j94(fields, labels, tables, settings):
    """PIC18FxxJ94/J99: PIC24-style oscillator (FRC 8 MHz, FOSC/POSCMD) with a 4x/6x/8x or 96 MHz PLL (PLLDIV)."""
    osc, plldiv, poscmd = field_of(fields, 'FOSC'), field_of(fields, 'PLLDIV'), field_of(fields, 'POSCMD')
    nodes = [fixed('frc', 'FRC 8 MHz', 0, 0, 8 * MHZ), *posc_nodes(), fixed('sosc', 'SOSC 32.768 kHz', 0, 3, 32768),
             fixed('lprc', 'LPRC 31 kHz', 0, 4, 31000),
             {'id': 'frc16', 'label': 'FRC/16', 'kind': 'divider', 'x': 1, 'y': 5, 'options': [{'id': '16', 'label': '/16', 'from': 'frc', 'div': 16}]},
             runtime_divider('frcdiv', 'FRC postscaler (your code)', 1, 6, 'frc', 2, 'OSCCON.IRCF postscaler, reset 1:2 (4 MHz).'),
             {'id': 'pllin', 'label': 'PLL input', 'kind': 'mux', 'x': 1, 'y': 0, 'tooltip': 'FRC with FRCPLL, POSC with PRIPLL.',
              'options': [{'id': 'frc', 'label': 'FRC', 'from': 'frc', 'when': "sel.sysclk != 'pripll'"},
                          {'id': 'posc', 'label': 'POSC', 'from': 'posc', 'when': "sel.sysclk == 'pripll'"}]}]
    pll_options, constraints = [], []
    for symbol, value in tables[plldiv].items():
        match = re.match(r'^(NODIV|DIV(\d+))$', symbol)
        if match:
            div = int(match.group(2) or 1)
            pll_options.append({'id': f'usb{div}', 'label': f'/{div} -> 96 MHz PLL /2', 'from': 'pllin', 'mul': 12, 'div': div, 'set': {plldiv: value}})
            constraints.append({'expr': f"sel.pll != 'usb{div}' || !(sel.sysclk == 'frcpll' || sel.sysclk == 'pripll') || "
                                        f"(f.pllin >= {3990000 * div} && f.pllin <= {4010000 * div})",
                                'message': f'The 96 MHz PLL needs 4 MHz after the prescaler: PLL input / {div} must be 4 MHz.'})
        elif re.match(r'^PLL\dX$', symbol):
            factor = int(symbol[3])
            pll_options.append({'id': f'x{factor}', 'label': f'x{factor}', 'from': 'pllin', 'mul': factor, 'set': {plldiv: value}})
        elif symbol == 'NOPLL':
            pll_options.append({'id': 'off', 'label': 'No PLL', 'mul': 0, 'set': {plldiv: value}})
        else:
            raise SystemExit(f'{plldiv}: {symbol} not understood')
    nodes.append({'id': 'pll', 'label': 'PLL (PLLDIV)', 'kind': 'multiplier', 'x': 2, 'y': 0, 'options': pll_options})
    choices = {'FRC': ('frc', 'FRC', 'frc'), 'FRCPLL': ('frcpll', 'FRC + PLL', 'pll'), 'PRI': ('pri', 'POSC', 'posc'),
               'PRIPLL': ('pripll', 'POSC + PLL', 'pll'), 'SOSC': ('sosc', 'SOSC', 'sosc'), 'LPRC': ('lprc', 'LPRC', 'lprc'),
               'FRC500KHZ': ('frc16', 'FRC/16 (500 kHz)', 'frc16'), 'FRCDIV': ('frcdiv', 'FRC/postscaler', 'frcdiv')}
    sys_options = []
    for symbol, value in tables[osc].items():
        oid, text, source = choices[symbol]
        sys_options.append({'id': oid, 'label': f'{text} ({symbol})', 'from': source, 'set': {osc: value}})
    nodes.append({'id': 'sysclk', 'label': 'System clock (FOSC)', 'kind': 'mux', 'x': 3, 'y': 1, 'options': sys_options})
    used = "sel.sysclk == 'pri' || sel.sysclk == 'pripll'"
    constraints.insert(0, {'expr': f"!({used}) || sel.poscmode == 'ec' || (in.posc >= 3500000 && in.posc <= 40000000)",
                           'message': 'A primary crystal must be 3.5 MHz - 40 MHz (MS up to 10 MHz, HS above).'})
    inputs = {'posc': {'label': 'POSC frequency', 'default': 8 * MHZ, 'min': 1, 'max': 64 * MHZ}}
    return nodes, inputs, [posc_derive(poscmd, tables[poscmd], used)], constraints, 64 * MHZ


def template(fields, tables):
    osc = field_of(fields, *OSC_KEYS)
    if 'PRIPLL' in tables[osc]:
        return 'j94'
    if field_of(fields, 'PLLDIV'):
        return 'usb_pll'
    return 'multiplier_pll'


TEMPLATES = {'usb_pll': usb_pll, 'multiplier_pll': multiplier_pll, 'j94': j94}
TITLES = {'usb_pll': 'PIC18 USB clock tree (96 MHz PLL)', 'multiplier_pll': 'PIC USB clock tree (3x/4x PLL)',
          'j94': 'PIC18 J94 clock tree'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--xc8', required=True, help='PIC/XC8/def folder of core_packages')
    parser.add_argument('--edc', required=True, help='folder with the EDC files (<MCU>.PIC) of the PIC16/PIC18 DFPs')
    args = parser.parse_args()

    edc = {path.stem.upper(): path for path in Path(args.edc).glob('*.PIC')}
    groups, skipped = OrderedDict(), []
    for path in sorted(Path(args.xc8).glob('*.json'), key=lambda item: item.stem.upper()):
        mcu = path.stem.upper()
        words = {f'{word.get("label_group")}.{word["key"]}': word for word in json.loads(path.read_text(encoding='utf-8')).get('config_words') or []
                 if word.get('key') in BOUND + SETTINGS and word.get('settings') and not word.get('hidden')}
        keys = {field.split('.')[1] for field in words}
        if not (keys & {'CPUDIV', 'PLLDIV'}):
            continue  # not a USB clock tree: convert_pic.py writes it
        bound = {field: word for field, word in words.items() if word['key'] in BOUND}
        fields = edc_fields(edc[mcu], bound) if mcu in edc else None
        if not fields or any(len(fields[field]['settings']) != len(word['settings']) for field, word in bound.items()):
            skipped.append(mcu)
            continue
        tables = {field: {str(symbol['value']): setting['value'] for symbol, setting in zip(word['settings'], fields[field]['settings'])}
                  for field, word in bound.items()}
        labels = {field: {str(setting['value']): setting['label'] for setting in word['settings']} for field, word in bound.items()}
        settings = tuple(field for field, word in words.items() if word['key'] in SETTINGS or (word['key'] == 'CFGPLLEN' and 'PLLDIV' in keys))
        key = json.dumps([template(bound, tables), tables, labels, settings], sort_keys=True)
        groups.setdefault(key, []).append(mcu)

    out_dir = GRAPHS_ROOT / 'microchip_pic_usb'
    for old in out_dir.glob('*.json') if out_dir.exists() else []:
        old.unlink()
    failed, total = False, 0
    for key, mcus in groups.items():
        name, tables, labels, settings = json.loads(key)
        nodes, inputs, derive, constraints, fosc_max = TEMPLATES[name]({field: None for field in tables}, labels, tables, settings)
        next(node for node in nodes if node['id'] == 'sysclk').update(max=fosc_max, consumer=True)
        nodes.append({'id': 'fcy', 'label': 'Instruction clock (Fosc/4)', 'kind': 'output', 'x': 6, 'y': 1,
                      'options': [{'id': '4', 'label': '/4', 'from': 'sysclk', 'div': 4}]})
        prune(nodes, inputs)
        shown = ', '.join(mcus[:3]) + (f' and {len(mcus) - 3} more' if len(mcus) > 3 else '')
        graph_id = f'pic_usb_{mcus[0].lower()}'
        item = graph(graph_id, f'{TITLES[name]} ({shown})', SOURCE, [f'^{re.escape(mcu)}$' for mcu in mcus], 'sysclk', inputs, nodes,
                     settings=settings, constraints=constraints, derive=derive)
        item['vendor'] = 'Microchip'
        written = {field for node in nodes for option in node.get('options', []) for field in (option.get('set') or {})}
        item['symbols'] = {field: table for field, table in tables.items() if field in written or any(rule['field'] == field for rule in derive)}
        problems = check_graph(item)
        for problem in problems:
            print(f'{graph_id}: {problem}')
        failed = failed or bool(problems)
        write_graph(item, f'microchip_pic_usb/{graph_id}.json')
        total += len(mcus)
    print(f'Wrote {len(groups)} USB PIC clock graphs for {total} MCUs to {out_dir.relative_to(REPO_ROOT)}; '
          f'skipped {len(skipped)}: {", ".join(skipped[:10])}{" ..." if len(skipped) > 10 else ""}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
