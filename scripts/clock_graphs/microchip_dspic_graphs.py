"""Write the Microchip dsPIC30F/dsPIC33F/dsPIC33E/PIC24 clock graphs (clock_graphs/microchip_dspic/*.json).

The clock trees are written by hand from the dsPIC30F, dsPIC33/PIC24 family reference manuals
(Oscillator chapters) and the data sheets' operating limits. The fuse values they write come from
the parts' EDC files (<MCU>.PIC, edc/ folder of the Microchip device family packs, Apache-2.0):
each symbol of an XC16 config_word (FNOSC = PRIPLL) gets the absolute value the EDC file gives it,
which is also the value the mikroC definitions use, so one graph drives XC16 (symbolic config_words,
through graph.symbols) and mikroC (numeric config_registers). Every part whose oscillator fuses have
the same symbols and values shares one graph.

What the fuses cannot say is written down as runtime choices or entered frequencies:
* dsPIC33F/E and PIC24H/E program their PLL (CLKDIV.PLLPRE/PLLPOST, PLLFBD) in code, so the PLL
  output is the frequency your code sets (the tool proposes the definition's clock).
* FRC postscalers (CLKDIV.FRCDIV/RCDIV) are runtime dividers shown with their reset values.
* PIC24F 96 MHz USB PLL feeds the CPU through CLKDIV.CPDIV (reset 1:1, 32 MHz).

  python scripts/clock_graphs/microchip_dspic_graphs.py --xc16 <dsPIC/XC16/def folder> --edc <folder with DFP edc/*.PIC files>
"""

import argparse
import json
import re
from collections import OrderedDict
from pathlib import Path

from convert_pic import edc_fields
from graphlib import GRAPHS_ROOT, REPO_ROOT, check_graph, hexv, write_graph
from stm32_graphs import MHZ, graph

# Hardware codes of FNOSC (dsPIC33/PIC24) per symbol; a symbol whose EDC value differs stops the run.
FNOSC_CODES = {'FRC': 0, 'FRCPLL': 1, 'PRI': 2, 'PRIPLL': 3, 'SOSC': 4, 'LPRC': 5, 'FRCDIV16': 6, 'LPFRC': 6, 'DCO': 6,
               'FRCDIVN': 7, 'LPRCDIVN': 7, 'FRCDIV': 7, 'OSCFDIV': 7}
POSC_CODES = {'EC': 0, 'XT': 1, 'MS': 1, 'HS': 2, 'NONE': 3}
RCDIV = [1, 2, 4, 8, 16, 32, 64, 256]

FAMILIES = {
    # template, title, FRC Hz, LPRC Hz, Fosc max, crystal range, PLL output range (runtime PLL), Fcy divider
    'dspic33f': ('dspic33', 'dsPIC33F/PIC24H clock tree (configuration fuses)', 7370000, 32768, 80 * MHZ, (3 * MHZ, 40 * MHZ), (12500000, 100 * MHZ), 2),
    'dspic33f_lp': ('dspic33', 'dsPIC33FJ/PIC24FJ 16 MIPS clock tree (configuration fuses)', 7370000, 32768, 32 * MHZ, (3500000, 32 * MHZ), (12500000, 100 * MHZ), 2),
    'dspic33e': ('dspic33', 'dsPIC33E/PIC24E clock tree (configuration fuses)', 7370000, 32768, 140 * MHZ, (3500000, 25 * MHZ), (15 * MHZ, 170 * MHZ), 2),
    'pic24f': ('pic24f', 'PIC24F clock tree (configuration fuses)', 8 * MHZ, 31000, 32 * MHZ, (3500000, 32 * MHZ), None, 2),
    'dspic30f': ('dspic30f', 'dsPIC30F clock tree (configuration fuses)', 7370000, 512000, 120 * MHZ, None, None, 4),
    'dspic30f_smps': ('dspic30f_smps', 'dsPIC30F SMPS clock tree (configuration fuses)', None, None, 60 * MHZ, None, None, 2),
}
SOURCE = ('dsPIC30F/dsPIC33/PIC24 family reference manuals (Oscillator sections) and data sheets; fuse values from the '
          'Microchip DFP EDC files')
SETTINGS = ('FCKSM', 'FCKSMEN', 'IESO', 'OSCIOFNC', 'PLLKEN', 'SOSCSEL', 'SOSCSRC', 'LPRCSEL', 'PLL96MHZ', 'PLLSS', 'SOSCHP')
BOUND = ('FNOSC', 'POSCMD', 'POSCMOD', 'POSCFREQ', 'PLLDIV', 'PLLMODE', 'FOSFPR', 'FOS', 'FPR', 'FRANGE')
# 60 MIPS dsPIC33E/PIC24E parts (MU8xx/GU8xx/GP806/MC806): Fosc up to 120 MHz.
SLOW_E = re.compile(r'^(DSPIC33EP|PIC24EP)\d+(MU8|GU8|GP8|MC8)')


def family(mcu, words):
    keys = {field.split('.')[1] for field in words}
    if mcu.startswith('DSPIC30F'):
        return 'dspic30f_smps' if 'FRANGE' in keys else 'dspic30f'
    if mcu.startswith(('DSPIC33E', 'PIC24E')):
        return 'dspic33e'
    if re.match(r'^(DSPIC33FJ\d+(GP|MC)10|PIC24FJ\d+MC10)', mcu):
        return 'dspic33f_lp'
    if mcu.startswith(('DSPIC33F', 'PIC24H')):
        return 'dspic33f'
    return 'pic24f'


def field_of(words, key):
    return next((field for field in words if field.split('.')[1] == key), None)


def fixed(node_id, label, x, y, hz, tooltip=None):
    node = {'id': node_id, 'label': label, 'kind': 'source', 'x': x, 'y': y, 'options': [{'id': 'on', 'label': label, 'mul': hz}]}
    if tooltip:
        node['tooltip'] = tooltip
    return node


def runtime_divider(node_id, label, x, y, source, default, tooltip):
    """A postscaler your code programs (CLKDIV.FRCDIV/RCDIV): not a fuse, shown with its reset value."""
    return {'id': node_id, 'label': label, 'kind': 'divider', 'x': x, 'y': y, 'default': str(default), 'tooltip': tooltip,
            'options': [{'id': str(div), 'label': f'/{div}', 'from': source, 'div': div} for div in RCDIV]}


def khz(hz):
    return f'{hz / MHZ:g} MHz' if hz >= MHZ else f'{hz / 1000:g} kHz'


def posc_nodes(x=0, y=1):
    return [
        {'id': 'posc', 'label': 'Primary oscillator (POSC)', 'kind': 'source', 'x': x, 'y': y, 'input': 'posc',
         'tooltip': 'Crystal (XT up to 10 MHz, HS above) or external clock (EC); POSCMD follows.'},
        {'id': 'poscmode', 'label': 'POSC type', 'kind': 'mux', 'x': x, 'y': y + 1, 'default': 'crystal',
         'options': [{'id': 'crystal', 'label': 'Crystal (XT/HS)', 'mul': 1}, {'id': 'ec', 'label': 'External clock (EC)', 'mul': 1}]},
    ]


def posc_derive(field, table, used):
    """POSCMD/POSCMOD follows the primary oscillator use: off, EC, XT/MS (<= 10 MHz) or HS."""
    off = table.get('NONE') or table.get('PRIOSC_OFF')
    cases = [{'when': f'!({used})', 'value': off}, {'when': "sel.poscmode == 'ec'", 'value': table['EC']}]
    slow = table.get('XT') or table.get('MS')
    if slow:
        cases.append({'when': 'in.posc <= 10000000', 'value': slow})
    return {'field': field, 'cases': cases, 'default': table['HS']}


def fnosc_options(field, table, available):
    """FNOSC options: (symbol, option id, label, source node, keeps)."""
    options = []
    for symbol, option_id, label, source, keeps in available:
        if symbol in table:
            option = {'id': option_id, 'label': f'{label} ({symbol})', 'from': source, 'set': {field: table[symbol]}}
            if keeps:
                option['keeps'] = keeps
            options.append(option)
    return options


def dspic33(spec, words, tables, rcdiv_pll):
    _, title, frc_hz, lprc_hz, fosc_max, crystal, pll_range, fcy_div = spec
    fnosc = field_of(words, 'FNOSC')
    poscmd = field_of(words, 'POSCMD') or field_of(words, 'POSCMOD')
    table = tables[fnosc]
    nodes = [fixed('frc', f'FRC {khz(frc_hz)}', 0, 0, frc_hz), *posc_nodes(), fixed('sosc', 'SOSC 32.768 kHz', 0, 3, 32768),
             fixed('lprc', f'LPRC {khz(lprc_hz)}', 0, 4, lprc_hz),
             {'id': 'pll', 'label': 'PLL output (your code)', 'kind': 'source', 'x': 2, 'y': 0, 'input': 'pll',
              'min': pll_range[0], 'max': min(pll_range[1], fosc_max),
              'tooltip': 'Fosc = Fin x M / (N1 x N2), programmed at runtime (CLKDIV.PLLPRE = N1, PLLFBD = M, CLKDIV.PLLPOST = N2). '
                         'Keep Fin / N1 at 0.8-8 MHz and the VCO (Fin x M / N1) in its data sheet range.'},
             {'id': 'frcdiv16', 'label': 'FRC/16', 'kind': 'divider', 'x': 1, 'y': 5, 'options': [{'id': '16', 'label': '/16', 'from': 'frc', 'div': 16}]},
             runtime_divider('frcdivn', 'FRCDIV (your code)', 1, 6, 'frc', 1, 'CLKDIV.FRCDIV postscaler, reset 1:1.')]
    choices = [('FRC', 'frc', 'FRC', 'frc', None), ('FRCPLL', 'frcpll', 'FRC + PLL', 'pll', ['frc']), ('PRI', 'pri', 'POSC', 'posc', None),
               ('PRIPLL', 'pripll', 'POSC + PLL', 'pll', ['posc']), ('SOSC', 'sosc', 'SOSC', 'sosc', None), ('LPRC', 'lprc', 'LPRC', 'lprc', None),
               ('FRCDIV16', 'frcdiv16', 'FRC/16', 'frcdiv16', None), ('FRCDIVN', 'frcdivn', 'FRC/FRCDIV', 'frcdivn', None),
               ('LPRCDIVN', 'frcdivn', 'FRC/FRCDIV', 'frcdivn', None)]
    nodes.append({'id': 'sysclk', 'label': 'Fosc (FNOSC)', 'kind': 'mux', 'x': 3, 'y': 1, 'max': fosc_max, 'consumer': True,
                  'options': fnosc_options(fnosc, table, choices)})
    nodes.append({'id': 'fcy', 'label': f'Fcy (Fosc/{fcy_div})', 'kind': 'output', 'x': 4, 'y': 1,
                  'options': [{'id': str(fcy_div), 'label': f'/{fcy_div}', 'from': 'sysclk', 'div': fcy_div}]})
    used = "sel.sysclk == 'pri' || sel.sysclk == 'pripll'"
    constraints = [{'expr': f"!({used}) || sel.poscmode == 'ec' || (in.posc >= {crystal[0]} && in.posc <= {crystal[1]})",
                    'message': f'A primary crystal must be {khz(crystal[0])} - {khz(crystal[1])}.'},
                   {'expr': "sel.sysclk != 'pripll' || in.posc >= 1600000", 'message': 'The PLL needs at least 1.6 MHz at its input (0.8 MHz after N1 = 2).'}]
    inputs = {'posc': {'label': 'POSC frequency', 'default': 8 * MHZ, 'min': 1, 'max': fosc_max},
              'pll': {'label': 'PLL output (Fosc) set by your code', 'default': min(fosc_max, pll_range[1]), 'min': pll_range[0], 'max': min(pll_range[1], fosc_max)}}
    return nodes, inputs, [posc_derive(poscmd, tables[poscmd], used)], constraints


def pic24f(spec, words, tables, rcdiv_pll):
    _, title, frc_hz, lprc_hz, fosc_max, crystal, _, fcy_div = spec
    fnosc = field_of(words, 'FNOSC')
    poscmd = field_of(words, 'POSCMD') or field_of(words, 'POSCMOD')
    pll_field = field_of(words, 'PLLMODE') or field_of(words, 'PLLDIV')
    table = tables[fnosc]
    nodes = [fixed('frc', 'FRC 8 MHz', 0, 0, frc_hz), *posc_nodes(), fixed('sosc', 'SOSC 32.768 kHz', 0, 3, 32768),
             fixed('lprc', 'LPRC 31 kHz', 0, 4, lprc_hz), fixed('lpfrc', 'LPFRC 500 kHz', 0, 5, 500000),
             runtime_divider('frcdiv', 'RCDIV (your code)', 1, 6, 'frc', 2, 'CLKDIV.RCDIV postscaler, reset 1:2 (4 MHz).'),
             runtime_divider('lpfrcdiv', 'RCDIV (your code)', 1, 5, 'lpfrc', 2, 'CLKDIV.RCDIV postscaler, reset 1:2.'),
             {'id': 'oscfdiv', 'label': 'Divided oscillator (your code)', 'kind': 'source', 'x': 1, 'y': 7, 'input': 'oscfdiv',
              'tooltip': 'OSCDIV output, programmed at runtime.'},
             {'id': 'dco', 'label': 'DCO (your code)', 'kind': 'source', 'x': 0, 'y': 7, 'input': 'dco', 'tooltip': 'DCO frequency (DCOFSEL), programmed at runtime.'},
             {'id': 'pllin', 'label': 'PLL input', 'kind': 'mux', 'x': 1, 'y': 0,
              'tooltip': 'FRCPLL: FRC (through the RCDIV postscaler on parts whose 4x/6x/8x PLL follows it); PRIPLL: POSC.',
              'options': [{'id': 'frc', 'label': 'FRC', 'from': 'frc', 'when': "sel.sysclk != 'pripll'"},
                          {'id': 'posc', 'label': 'POSC', 'from': 'posc', 'when': "sel.sysclk == 'pripll'"}]}]
    constraints = []
    inputs = {'posc': {'label': 'POSC frequency', 'default': 8 * MHZ, 'min': 1, 'max': fosc_max}}
    if 'OSCFDIV' in table:
        inputs['oscfdiv'] = {'label': 'Divided oscillator frequency (OSCDIV)', 'default': 4 * MHZ, 'min': 1, 'max': fosc_max}
    if 'DCO' in table:
        inputs['dco'] = {'label': 'DCO frequency', 'default': 8 * MHZ, 'min': 1 * MHZ, 'max': fosc_max}
    if not pll_field:
        # Fixed 4x PLL: 4-8 MHz in, 16-32 MHz out.
        nodes[-1].update(min=4 * MHZ, max=8 * MHZ)
        nodes.append({'id': 'pll', 'label': '4x PLL', 'kind': 'multiplier', 'x': 2, 'y': 0, 'options': [{'id': '4', 'label': 'x4', 'from': 'pllin', 'mul': 4}]})
    else:
        options = []
        for symbol, value in tables[pll_field].items():
            match96 = re.match(r'^(?:PLL96)?(NODIV|DIV(?:IDE)?(\d+))$', symbol)
            match_x = re.match(r'^PLL(\d)X$', symbol)
            if match96:
                div = int(match96.group(2) or 1)
                # Prescaler to 4 MHz, 96 MHz PLL, /3 = 32 MHz (CPDIV reset 1:1).
                options.append({'id': f'usb{div}', 'label': f'/{div} -> 96 MHz PLL /3', 'from': 'pllin', 'mul': 8, 'div': div, 'set': {pll_field: value}})
                constraints.append({'expr': f"sel.pll != 'usb{div}' || !(sel.sysclk == 'frcpll' || sel.sysclk == 'pripll') || "
                                            f"(f.pllin >= {3990000 * div} && f.pllin <= {4010000 * div})",
                                    'message': f'The 96 MHz PLL needs 4 MHz after the prescaler: PLL input / {div} must be 4 MHz.'})
            elif match_x:
                options.append({'id': f'x{match_x.group(1)}', 'label': f'x{match_x.group(1)}', 'from': 'pllin', 'mul': int(match_x.group(1)), 'set': {pll_field: value}})
            elif symbol in ('DISABLED', 'DIS'):
                options.append({'id': 'off', 'label': 'PLL disabled', 'mul': 0, 'set': {pll_field: value}})
            else:
                raise SystemExit(f'{pll_field}: symbol {symbol} not understood')
        nodes.append({'id': 'pll', 'label': f'PLL ({pll_field.split(".")[1]})', 'kind': 'multiplier', 'x': 2, 'y': 0, 'options': options,
                      'tooltip': '96 MHz PLL: prescaler to 4 MHz, Fosc = 96 MHz / 3 / CPDIV (reset 1:1). 4x/6x/8x PLL: input times the factor.'})
    multiplied = ' || '.join(f"sel.pll == '{option['id']}'" for option in nodes[-1]['options'] if option['id'].startswith('x')) if pll_field else '1'
    if rcdiv_pll and multiplied:
        # 'FRC with Postscaler and PLL': the RCDIV output feeds the 4x/6x/8x PLL (PIC24FJ256GA705: FRCPLL, 4x = 16 MHz
        # at reset); the 96 MHz USB PLL takes the undivided FRC (FRCPLL with PLLDIV = DIV2 gives its 4 MHz).
        pllin = next(node for node in nodes if node['id'] == 'pllin')
        frc_option = pllin['options'][0]
        frc_option['when'] = f"sel.sysclk != 'pripll' && !({multiplied})"
        pllin['options'].insert(1, {'id': 'frcdiv', 'label': 'FRC/RCDIV', 'from': 'frcdiv', 'when': f"sel.sysclk != 'pripll' && ({multiplied})"})
    choices = [('FRC', 'frc', 'FRC', 'frc', None), ('FRCPLL', 'frcpll', 'FRC + PLL', 'pll', None), ('PRI', 'pri', 'POSC', 'posc', None),
               ('PRIPLL', 'pripll', 'POSC + PLL', 'pll', None), ('SOSC', 'sosc', 'SOSC', 'sosc', None), ('LPRC', 'lprc', 'LPRC', 'lprc', None),
               ('LPFRC', 'lpfrc', 'LPFRC/RCDIV', 'lpfrcdiv', None), ('DCO', 'dco', 'DCO', 'dco', None),
               ('FRCDIV', 'frcdiv', 'FRC/RCDIV', 'frcdiv', None), ('OSCFDIV', 'oscfdiv', 'Divided oscillator', 'oscfdiv', None)]
    nodes.append({'id': 'sysclk', 'label': 'Fosc (FNOSC)', 'kind': 'mux', 'x': 3, 'y': 1, 'max': fosc_max, 'consumer': True,
                  'options': fnosc_options(fnosc, table, choices)})
    nodes.append({'id': 'fcy', 'label': f'Fcy (Fosc/{fcy_div})', 'kind': 'output', 'x': 4, 'y': 1,
                  'options': [{'id': str(fcy_div), 'label': f'/{fcy_div}', 'from': 'sysclk', 'div': fcy_div}]})
    used = "sel.sysclk == 'pri' || sel.sysclk == 'pripll'"
    constraints.insert(0, {'expr': f"!({used}) || sel.poscmode == 'ec' || (in.posc >= {crystal[0]} && in.posc <= {crystal[1]})",
                           'message': f'A primary crystal must be {khz(crystal[0])} - {khz(crystal[1])}.'})
    derive = [posc_derive(poscmd, tables[poscmd], used)]
    freq_field = field_of(words, 'POSCFREQ')
    if freq_field:
        derive.append({'field': freq_field, 'cases': [{'when': 'in.posc <= 100000', 'value': tables[freq_field]['LS']},
                                                      {'when': 'in.posc <= 8000000', 'value': tables[freq_field]['MS']}],
                       'default': tables[freq_field]['HS']})
    return nodes, inputs, derive, constraints


# dsPIC30F primary modes: symbol -> (source, multiplier, divider, external range)
XT_RANGE, HS_RANGE, XTL_RANGE, EC_RANGE, PLL_RANGE = (4 * MHZ, 10 * MHZ), (10 * MHZ, 25 * MHZ), (200000, 4 * MHZ), (1, 40 * MHZ), (4 * MHZ, 10 * MHZ)


def dspic30f_mode(symbol):
    if symbol in ('LP', 'LPOSC', 'LOPOSC'):
        return 'sosc', 1, 1, None, 'LP secondary oscillator'
    if symbol in ('FRC', 'LPRC'):
        return symbol.lower(), 1, 1, None, symbol
    if symbol == 'PRI':
        return 'primary', 1, 1, None, 'Primary (FPR)'
    match = re.match(r'^(FRC|XT|ECIO|HS2|HS3)_PLL(\d+)$', symbol)
    if match:
        base, mul = match.group(1), int(match.group(2))
        if base == 'FRC':
            return 'frc', mul, 1, None, f'FRC x{mul}'
        if base in ('HS2', 'HS3'):
            return 'ext', mul, int(base[2]), HS_RANGE, f'HS/{base[2]} x{mul}'
        top = 7500000 if mul == 16 else PLL_RANGE[1]
        return 'ext', mul, 1, (PLL_RANGE[0], top), f'{base} x{mul}'
    ranges = {'XTL': XTL_RANGE, 'XT': XT_RANGE, 'HS': HS_RANGE, 'EC': EC_RANGE, 'ECIO': EC_RANGE, 'ERC': None, 'ERCIO': None}
    if symbol in ranges:
        return 'ext', 1, 1, ranges[symbol], symbol
    raise SystemExit(f'dsPIC30F oscillator mode {symbol} not understood')


def dspic30f(spec, words, tables, rcdiv_pll):
    _, title, frc_hz, lprc_hz, fosc_max, _, _, fcy_div = spec
    nodes = [fixed('frc', 'FRC 7.37 MHz', 0, 0, frc_hz),
             {'id': 'ext', 'label': 'External crystal / clock / RC', 'kind': 'source', 'x': 0, 'y': 1, 'input': 'ext'},
             fixed('sosc', 'LP oscillator 32.768 kHz', 0, 3, 32768), fixed('lprc', 'LPRC 512 kHz', 0, 4, lprc_hz)]
    constraints = []

    def mode_node(node_id, label, x, y, field, **extra):
        options = []
        for symbol, value in tables[field].items():
            source, mul, div, span, text = dspic30f_mode(symbol)
            option_id = symbol.lower()
            options.append({'id': option_id, 'label': f'{text} ({symbol})', 'from': source, 'mul': mul, 'div': div, 'set': {field: value}})
            if span:
                constraints.append({'expr': f"sel.{node_id} != '{option_id}' || (in.ext >= {span[0]} && in.ext <= {span[1]})",
                                    'message': f'{symbol}: the external frequency must be {khz(span[0])} - {khz(span[1])}.'})
        return {'id': node_id, 'label': label, 'kind': 'mux', 'x': x, 'y': y, 'options': options, **extra}

    combined = field_of(words, 'FOSFPR')
    if combined:
        nodes.append(mode_node('sysclk', 'Fosc (FOSFPR)', 2, 1, combined, max=fosc_max, consumer=True))
    else:
        nodes.append(mode_node('primary', 'Primary mode (FPR)', 1, 1, field_of(words, 'FPR')))
        nodes.append(mode_node('sysclk', 'Fosc (FOS)', 2, 1, field_of(words, 'FOS'), max=fosc_max, consumer=True))
        for constraint in constraints:
            if 'sel.primary' in constraint['expr']:
                constraint['expr'] = f"sel.sysclk != 'pri' || {constraint['expr']}"
    nodes.append({'id': 'fcy', 'label': f'Fcy (Fosc/{fcy_div})', 'kind': 'output', 'x': 3, 'y': 1,
                  'options': [{'id': str(fcy_div), 'label': f'/{fcy_div}', 'from': 'sysclk', 'div': fcy_div}]})
    inputs = {'ext': {'label': 'External frequency', 'default': 10 * MHZ, 'min': 1, 'max': 40 * MHZ}}
    return nodes, inputs, [], constraints


def dspic30f_smps(spec, words, tables, rcdiv_pll):
    _, title, _, _, fosc_max, _, _, fcy_div = spec
    fnosc, poscmd, frange = field_of(words, 'FNOSC'), field_of(words, 'POSCMD'), field_of(words, 'FRANGE')
    nodes = [{'id': 'frc', 'label': 'FRC (FRANGE)', 'kind': 'mux', 'x': 0, 'y': 0,
              'options': [{'id': 'hi', 'label': 'FRC 14.55 MHz', 'mul': 14550000, 'set': {frange: tables[frange]['FRC_HI_RANGE']}},
                          {'id': 'lo', 'label': 'FRC 9.7 MHz', 'mul': 9700000, 'set': {frange: tables[frange]['FRC_LO_RANGE']}}]},
             *posc_nodes(),
             {'id': 'pllin', 'label': 'PLL input', 'kind': 'mux', 'x': 1, 'y': 0,
              'options': [{'id': 'frc', 'label': 'FRC', 'from': 'frc', 'when': "sel.sysclk != 'pripll'"},
                          {'id': 'posc', 'label': 'POSC', 'from': 'posc', 'when': "sel.sysclk == 'pripll'"}]},
             {'id': 'pll', 'label': 'x32 PLL /8', 'kind': 'multiplier', 'x': 2, 'y': 0, 'tooltip': 'The x32 PLL also clocks the PWM and ADC; Fosc = PLL / 8.',
              'options': [{'id': '4', 'label': 'x32 /8', 'from': 'pllin', 'mul': 4}]}]
    choices = [('FRC', 'frc', 'FRC', 'frc', None), ('FRC_PLL', 'frcpll', 'FRC + PLL', 'pll', None),
               ('PRIOSC', 'pri', 'POSC', 'posc', None), ('PRIOSC_PLL', 'pripll', 'POSC + PLL', 'pll', None)]
    nodes.append({'id': 'sysclk', 'label': 'Fosc (FNOSC)', 'kind': 'mux', 'x': 3, 'y': 1, 'max': fosc_max, 'consumer': True,
                  'options': fnosc_options(fnosc, tables[fnosc], choices)})
    nodes.append({'id': 'fcy', 'label': f'Fcy (Fosc/{fcy_div})', 'kind': 'output', 'x': 4, 'y': 1,
                  'options': [{'id': str(fcy_div), 'label': f'/{fcy_div}', 'from': 'sysclk', 'div': fcy_div}]})
    used = "sel.sysclk == 'pri' || sel.sysclk == 'pripll'"
    inputs = {'posc': {'label': 'POSC frequency', 'default': 10 * MHZ, 'min': 1, 'max': fosc_max}}
    return nodes, inputs, [posc_derive(poscmd, tables[poscmd], used)], []


def prune(nodes, inputs):
    """Drop the nodes no Fosc choice reaches (an FRC/16 on a part without FRCDIV16) and their inputs."""
    by_id = {node['id']: node for node in nodes}
    reached, stack = set(), ['fcy']
    while stack:
        node_id = stack.pop()
        if node_id in reached:
            continue
        reached.add(node_id)
        for option in by_id[node_id].get('options', []):
            stack.extend(item for item in [option.get('from'), *option.get('keeps', [])] if item)
    if 'posc' in reached:
        reached.add('poscmode')
    nodes[:] = [node for node in nodes if node['id'] in reached]
    for key in [key for key in inputs if not any(node.get('input') == key for node in nodes)]:
        del inputs[key]


TEMPLATES = {'dspic33': dspic33, 'pic24f': pic24f, 'dspic30f': dspic30f, 'dspic30f_smps': dspic30f_smps}


def oscillator_words(path):
    words = json.loads(path.read_text(encoding='utf-8')).get('config_words') or []
    return {f'{word.get("label_group")}.{word["key"]}': word for word in words
            if word.get('key') in BOUND + SETTINGS and word.get('settings') and not word.get('hidden')}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--xc16', required=True, help='dsPIC/XC16/def folder of core_packages')
    parser.add_argument('--edc', required=True, help='folder with the EDC files (<MCU>.PIC) of the dsPIC30F/dsPIC33/PIC24 DFPs')
    args = parser.parse_args()

    edc = {path.stem.upper(): path for path in Path(args.edc).glob('*.PIC')}
    groups, skipped = OrderedDict(), []
    for path in sorted(Path(args.xc16).glob('*.json'), key=lambda item: item.stem.upper()):
        mcu = path.stem.upper()
        words = oscillator_words(path)
        bound = {field: word for field, word in words.items() if word['key'] in BOUND}
        fields = edc_fields(edc[mcu], bound) if mcu in edc else None
        if not fields or any(len(fields[field]['settings']) != len(word['settings']) for field, word in bound.items()):
            skipped.append(mcu)
            continue
        # edc_fields keeps the word's setting order (all present), so the symbols zip back onto the values.
        tables = {field: {str(symbol['value']): setting['value'] for symbol, setting in zip(word['settings'], fields[field]['settings'])}
                  for field, word in bound.items()}
        fnosc = field_of(bound, 'FNOSC')
        if fnosc and not mcu.startswith('DSPIC30F'):
            # Codes 1/3/5/7 sit at the field's lowest bit: the smallest trailing-zero count is the field position.
            numbers = [int(value, 16) for value in tables[fnosc].values()]
            lsb = min((number & -number).bit_length() - 1 for number in numbers if number)
            for symbol, value in tables[fnosc].items():
                if FNOSC_CODES.get(symbol, -1) << lsb != int(value, 16):
                    raise SystemExit(f'{mcu}: FNOSC {symbol} = {value} in the EDC file, the graph expects code {FNOSC_CODES.get(symbol)}')
        # XC16 files a few fuses under 'Other' (PLLKEN); mikroC names their real register (FWDT).
        # Newer PIC24F feed the PLL from the FRC postscaler ('FRC with Postscaler and PLL', 'FRCDIV+PLL').
        frcpll = next((setting['label'] for setting in bound[fnosc]['settings'] if setting['value'] == 'FRCPLL'), '') if fnosc else ''
        rcdiv_pll = bool(re.search(r'postscaler|FRCDIV\+PLL|divide-by-N', frcpll, re.I))
        settings = tuple(f'{field}|FWDT.{word["key"]}' if field.startswith('Other.') else field
                         for field, word in words.items() if word['key'] in SETTINGS)
        name = family(mcu, bound)
        key = json.dumps([name, tables, settings, rcdiv_pll and name == 'pic24f'], sort_keys=True)
        groups.setdefault(key, []).append(mcu)

    out_dir = GRAPHS_ROOT / 'microchip_dspic'
    for old in out_dir.glob('*.json') if out_dir.exists() else []:
        old.unlink()
    failed, total = False, 0
    for key, mcus in groups.items():
        name, tables, settings, rcdiv_pll = json.loads(key)
        spec = FAMILIES[name]
        words = {field: None for field in tables}
        nodes, inputs, derive, constraints = TEMPLATES[spec[0]](spec, words, tables, rcdiv_pll)
        prune(nodes, inputs)
        shown = ', '.join(mcus[:3]) + (f' and {len(mcus) - 3} more' if len(mcus) > 3 else '')
        graph_id = f'{name}_{mcus[0].lower()}'
        variants = []
        if name == 'dspic33e':
            slow = [mcu for mcu in mcus if SLOW_E.match(mcu)]
            if slow:
                variants.append({'devices': [f'^{re.escape(mcu)}$' for mcu in slow], 'limits': {'sysclk': {'max': 120 * MHZ}, 'pll': {'max': 120 * MHZ}}})
        item = graph(graph_id, f'{spec[1].replace(" (configuration fuses)", "")} ({shown})', SOURCE, [f'^{re.escape(mcu)}$' for mcu in mcus],
                     'sysclk', inputs, nodes, settings=settings, constraints=constraints, variants=variants, derive=derive)
        item['vendor'] = 'Microchip'
        item['symbols'] = {field: table for field, table in tables.items()
                           if any(field in (option.get('set') or {}) for node in nodes for option in node.get('options', []))
                           or any(rule['field'] == field for rule in derive)}
        problems = check_graph(item)
        for problem in problems:
            print(f'{graph_id}: {problem}')
        failed = failed or bool(problems)
        write_graph(item, f'microchip_dspic/{graph_id}.json')
        total += len(mcus)
    print(f'Wrote {len(groups)} dsPIC/PIC24 clock graphs for {total} MCUs to {out_dir.relative_to(REPO_ROOT)}; '
          f'skipped {len(skipped)}: {", ".join(skipped[:10])}{" ..." if len(skipped) > 10 else ""}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
