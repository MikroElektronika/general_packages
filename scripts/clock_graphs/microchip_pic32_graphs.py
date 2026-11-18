"""Write the Microchip PIC32 clock graphs (clock_graphs/microchip_pic32/*.json).

Hand-written from the PIC32MX and PIC32MZ family reference manuals (Oscillator chapter). PIC32 select
their whole system clock with configuration fuses (DEVCFG1/DEVCFG2): mikroC programs them from the
numeric config_registers, XC32 from the symbolic config_words, which graph.symbols maps to the same
numbers. Peripheral bus dividers set at runtime (PIC32MZ PBxDIV) are not fuses and are left out.
Maximum SYSCLK per part: data/pic32_max_mhz.json (NECTO database max_speed).
Register values are absolute bit values (see clock_graphs/README.md).

Run:  python scripts/clock_graphs/microchip_pic32_graphs.py
"""

import json
from collections import defaultdict
from pathlib import Path

from graphlib import REPO_ROOT, check_graph, hexv, write_graph
from stm32_graphs import MHZ, en, factors, fixed, graph, mux, rule

SPEEDS = json.loads((Path(__file__).parent / 'data' / 'pic32_max_mhz.json').read_text(encoding='utf-8'))['parts']


def speed_variants(prefix, family_max):
    """Variants limiting SYSCLK for the parts slower than the family maximum."""
    groups = defaultdict(list)
    for part, mhz in SPEEDS.items():
        if part.startswith(prefix) and mhz and mhz * MHZ < family_max:
            groups[mhz].append(part)
    return [{'devices': [f'^{part}$' for part in sorted(parts)], 'limits': {'sysclk': {'max': mhz * MHZ}}}
            for mhz, parts in sorted(groups.items())]


def symbols(field, pairs):
    return {field: {symbol: hexv(value) for symbol, value in pairs}}


def posc_mode(field_values, sysclk_uses_posc):
    """POSCMOD follows the primary oscillator use: off, external clock, XT (<= 10 MHz) or HS."""
    cases = [{'when': f'!({sysclk_uses_posc})', 'value': hexv(field_values['OFF'])},
             {'when': "sel.poscmode == 'ec'", 'value': hexv(field_values['EC'])}]
    if 'XT' in field_values:
        cases.append({'when': 'in.posc <= 10000000', 'value': hexv(field_values['XT'])})
    return {'field': 'DEVCFG1.POSCMOD', 'cases': cases, 'default': hexv(field_values['HS'])}


def posc_nodes():
    return [
        {'id': 'posc', 'label': 'Primary oscillator (POSC)', 'kind': 'source', 'x': 0, 'y': 1, 'input': 'posc',
         'tooltip': 'Crystal (XT up to 10 MHz, HS above) or external clock (EC); POSCMOD follows.'},
        {'id': 'poscmode', 'label': 'POSC type', 'kind': 'mux', 'x': 0, 'y': 2, 'default': 'crystal',
         'options': [{'id': 'crystal', 'label': 'Crystal (XT/HS)', 'mul': 1}, {'id': 'ec', 'label': 'External clock (EC)', 'mul': 1}]},
    ]


# PIC32MX: FNOSC chooses the source; FRCPLL/PRIPLL run the PLL (FPLLIDIV -> FPLLMUL -> FPLLODIV)
# from FRC or POSC. The two PLL codes (1, 3) share the bits x01, so "PLL" is a masked FNOSC value.
MX_POSCMOD = {'EC': 0, 'XT': 1 << 8, 'HS': 2 << 8, 'OFF': 3 << 8}
MX_IDIV = [(1, 0), (2, 1), (3, 2), (4, 3), (5, 4), (6, 5), (10, 6), (12, 7)]
MX_MUL = [(15, 0), (16, 1), (17, 2), (18, 3), (19, 4), (20, 5), (21, 6), (24, 7)]
MX_ODIV = [(1, 0), (2, 1), (4, 2), (8, 3), (16, 4), (32, 5), (64, 6), (256, 7)]
PIC32MX = graph(
    'pic32mx', 'PIC32MX clock tree (configuration fuses)', 'PIC32 family reference manual, section 6 Oscillator (DS61112)', ['^PIC32MX'],
    'sysclk', {'posc': {'label': 'POSC frequency', 'default': 8 * MHZ, 'min': 3 * MHZ, 'max': 25 * MHZ}},
    [
        fixed('frc', 'FRC 8 MHz', 0, 0, 8 * MHZ),
        *posc_nodes(),
        fixed('sosc', 'SOSC 32.768 kHz', 0, 3, 32768, en('DEVCFG1.FSOSCEN', 1 << 5)),
        fixed('lprc', 'LPRC 31.25 kHz', 0, 4, 31250),
        {'id': 'frcdiv16', 'label': 'FRC/16', 'kind': 'divider', 'x': 1, 'y': 5, 'options': [{'id': '16', 'label': '/16', 'from': 'frc', 'div': 16}]},
        mux('pllin', 'PLL input (FNOSC)', 1, 0, 'DEVCFG1.FNOSC', [('frc', 'FRC (FRCPLL)', 'frc', 1), ('posc', 'POSC (PRIPLL)', 'posc', 3)]),
        factors('pllidiv', 'PLL /FPLLIDIV', 2, 0, 'pllin', 'DEVCFG2.FPLLIDIV', 0, MX_IDIV, min=4 * MHZ, max=5 * MHZ,
                tooltip='PLL input: 4-5 MHz.'),
        factors('pllmul', 'PLL xFPLLMUL', 3, 0, 'pllidiv', 'DEVCFG2.FPLLMUL', 4, MX_MUL, op='mul', min=60 * MHZ, max=120 * MHZ),
        factors('pll', 'PLL /FPLLODIV', 4, 0, 'pllmul', 'DEVCFG2.FPLLODIV', 16, MX_ODIV),
        {'id': 'sysclk', 'label': 'SYSCLK (FNOSC)', 'kind': 'mux', 'x': 5, 'y': 1, 'max': 120 * MHZ, 'consumer': True,
         'options': [{'id': 'pll', 'label': 'PLL (FRCPLL/PRIPLL)', 'from': 'pll', 'set': {'DEVCFG1.FNOSC': f'{hexv(1)}/{hexv(5)}'}},
                     {'id': 'frc', 'label': 'FRC', 'from': 'frc', 'set': {'DEVCFG1.FNOSC': hexv(0)}},
                     {'id': 'pri', 'label': 'POSC', 'from': 'posc', 'set': {'DEVCFG1.FNOSC': hexv(2)}},
                     {'id': 'sosc', 'label': 'SOSC', 'from': 'sosc', 'set': {'DEVCFG1.FNOSC': hexv(4)}},
                     {'id': 'lprc', 'label': 'LPRC', 'from': 'lprc', 'set': {'DEVCFG1.FNOSC': hexv(5)}},
                     {'id': 'frcdiv16', 'label': 'FRC/16', 'from': 'frcdiv16', 'set': {'DEVCFG1.FNOSC': hexv(6)}},
                     {'id': 'frcdiv', 'label': 'FRC/FRCDIV (reset 1:1)', 'from': 'frc', 'set': {'DEVCFG1.FNOSC': hexv(7)}}]},
        factors('pbclk', 'PBCLK (FPBDIV)', 6, 1, 'sysclk', 'DEVCFG1.FPBDIV', 12, [(1, 0), (2, 1), (4, 2), (8, 3)], consumer=True),
    ],
    settings=['DEVCFG2.UPLLEN', 'DEVCFG2.UPLLIDIV'],
    derive=[posc_mode(MX_POSCMOD, "sel.sysclk == 'pri' || (sel.sysclk == 'pll' && sel.pllin == 'posc')")],
    variants=speed_variants('PIC32MX', 120 * MHZ))
PIC32MX['vendor'] = 'Microchip'
PIC32MX['symbols'] = {
    **symbols('DEVCFG1.FNOSC', [('FRC', 0), ('FRCPLL', 1), ('PRI', 2), ('PRIPLL', 3), ('SOSC', 4), ('LPRC', 5), ('FRCDIV16', 6), ('FRCDIV', 7)]),
    **symbols('DEVCFG1.POSCMOD', list(MX_POSCMOD.items())),
    **symbols('DEVCFG1.FSOSCEN', [('OFF', 0), ('ON', 1 << 5)]),
    **symbols('DEVCFG1.FPBDIV', [(f'DIV_{d}', c << 12) for d, c in [(1, 0), (2, 1), (4, 2), (8, 3)]]),
    **symbols('DEVCFG2.FPLLIDIV', [(f'DIV_{d}', c) for d, c in MX_IDIV]),
    **symbols('DEVCFG2.FPLLMUL', [(f'MUL_{m}', c << 4) for m, c in MX_MUL]),
    **symbols('DEVCFG2.FPLLODIV', [(f'DIV_{d}', c << 16) for d, c in MX_ODIV]),
}

# PIC32MZ: FPLLICLK chooses the PLL input, FPLLIDIV -> FPLLMULT (VCO 350-700 MHz) -> FPLLODIV = SPLL;
# FPLLRNG must name the PLL input range and follows the divided input.
MZ_POSCMOD = {'EC': 0, 'HS': 2 << 8, 'OFF': 3 << 8}
MZ_ODIV = [(2, 1), (4, 2), (8, 3), (16, 4), (32, 7)]
MZ_RANGES = [(10, 1), (16, 2), (26, 3), (42, 4), (68, 5)]
PIC32MZ = graph(
    'pic32mz', 'PIC32MZ clock tree (configuration fuses)', 'PIC32MZ family reference manual, section 42 Oscillators with Enhanced PLL (DS60001250)',
    ['^PIC32MZ'], 'sysclk', {'posc': {'label': 'POSC frequency', 'default': 24 * MHZ, 'min': 4 * MHZ, 'max': 64 * MHZ}},
    [
        fixed('frc', 'FRC 8 MHz', 0, 0, 8 * MHZ),
        *posc_nodes(),
        fixed('sosc', 'SOSC 32.768 kHz', 0, 3, 32768, en('DEVCFG1.FSOSCEN', 1 << 6)),
        fixed('lprc', 'LPRC 32 kHz', 0, 4, 32000),
        mux('pllin', 'PLL input (FPLLICLK)', 1, 0, 'DEVCFG2.FPLLICLK', [('posc', 'POSC', 'posc', 0), ('frc', 'FRC', 'frc', 1 << 7)]),
        factors('pllidiv', 'PLL /FPLLIDIV', 2, 0, 'pllin', 'DEVCFG2.FPLLIDIV', 0, [(n, n - 1) for n in range(1, 9)], min=5 * MHZ, max=64 * MHZ,
                tooltip='PLL input: 5-64 MHz; FPLLRNG follows it.'),
        {'id': 'vco', 'label': 'PLL xFPLLMULT (VCO)', 'kind': 'multiplier', 'x': 3, 'y': 0, 'min': 350 * MHZ, 'max': 700 * MHZ,
         'range': {'from': 'pllidiv', 'op': 'mul', 'min': 1, 'max': 128, 'field': 'DEVCFG2.FPLLMULT', 'lsb': 8, 'scale': 1, 'offset': -1}},
        factors('spll', 'SPLL /FPLLODIV', 4, 0, 'vco', 'DEVCFG2.FPLLODIV', 16, MZ_ODIV),
        mux('sysclk', 'SYSCLK (FNOSC)', 5, 1, 'DEVCFG1.FNOSC', [('spll', 'SPLL', 'spll', 1), ('posc', 'POSC', 'posc', 2), ('sosc', 'SOSC', 'sosc', 4),
                                                             ('lprc', 'LPRC', 'lprc', 5), ('frcdiv', 'FRC/FRCDIV (reset 1:1)', 'frc', 7)],
            max=200 * MHZ, consumer=True),
    ],
    derive=[
        posc_mode(MZ_POSCMOD, "sel.sysclk == 'posc' || (sel.sysclk == 'spll' && sel.pllin == 'posc')"),
        {'field': 'DEVCFG2.FPLLRNG', 'cases': [{'when': f'f.pllidiv <= {limit * MHZ}', 'value': hexv(code << 4)} for limit, code in MZ_RANGES],
         'default': hexv(5 << 4)},
    ],
    variants=[{'devices': [f'^{part}$' for part, mhz in sorted(SPEEDS.items()) if part.startswith('PIC32MZ') and mhz > 200],
               'limits': {'sysclk': {'max': 252 * MHZ}}}])
PIC32MZ['vendor'] = 'Microchip'
PIC32MZ['symbols'] = {
    **symbols('DEVCFG1.FNOSC', [('SPLL', 1), ('POSC', 2), ('SOSC', 4), ('LPRC', 5), ('FRCDIV', 7)]),
    **symbols('DEVCFG1.POSCMOD', list(MZ_POSCMOD.items())),
    **symbols('DEVCFG1.FSOSCEN', [('OFF', 0), ('ON', 1 << 6)]),
    **symbols('DEVCFG2.FPLLICLK', [('PLL_POSC', 0), ('PLL_FRC', 1 << 7)]),
    **symbols('DEVCFG2.FPLLIDIV', [(f'DIV_{n}', n - 1) for n in range(1, 9)]),
    **symbols('DEVCFG2.FPLLMULT', [(f'MUL_{n}', (n - 1) << 8) for n in range(1, 129)]),
    **symbols('DEVCFG2.FPLLODIV', [(f'DIV_{d}', c << 16) for d, c in MZ_ODIV]),
    **symbols('DEVCFG2.FPLLRNG', [('RANGE_BYPASS', 0), ('RANGE_5_10_MHZ', 1 << 4), ('RANGE_8_16_MHZ', 2 << 4), ('RANGE_13_26_MHZ', 3 << 4),
                                  ('RANGE_21_42_MHZ', 4 << 4), ('RANGE_34_68_MHZ', 5 << 4)]),
}

GRAPHS = [PIC32MX, PIC32MZ]


def main():
    failed = False
    for item in GRAPHS:
        problems = check_graph(item)
        for problem in problems:
            print(f'{item["id"]}: {problem}')
        failed = failed or bool(problems)
        print(f'wrote {write_graph(item, f"microchip_pic32/{item["id"]}.json").relative_to(REPO_ROOT)}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
