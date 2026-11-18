"""Write the Renesas RL78 clock graphs (clock_graphs/renesas_rl78/*.json).

Hand-written from the RL78/G21, G23, G24 and L23 user's manuals (Clock Generator) for the fields the
NECTO definitions expose and the core init_clock.c applies. The HOCO base frequency comes from the
option bytes the core links (vectors.c): 32 MHz on G21/G23/L23, the 48 MHz path on G24
(HSCLKSEL.FIHSEL); the G24 PLL is left to the register view. FOSC_KHZ_VALUE is fCLK.
Register values are absolute bit values (see clock_graphs/README.md).

Run:  python scripts/clock_graphs/renesas_rl78_graphs.py
"""

from graphlib import REPO_ROOT, check_graph, hexv, write_graph
from stm32_graphs import MHZ, en, factors, fixed, graph, mux

HOCODIV = [(1 << n, n) for n in range(6)]


def rl78(graph_id, title, source, devices, fclk_max, moco=True, xt1=True, hoco_48=False):
    nodes = []
    if hoco_48:
        nodes.append({'id': 'hoco', 'label': 'HOCO 48 MHz', 'kind': 'source', 'x': 0, 'y': 0,
                      'enable': en('SYSTEM_CSC.HIOSTOP', 0, off=1, auto='on'),
                      'options': [{'id': '48', 'label': 'HOCO 48 MHz (FIHSEL)', 'mul': 48 * MHZ, 'set': {'SYSTEM_HSCLKSEL.FIHSEL': hexv(1)}}]})
    else:
        nodes.append(fixed('hoco', 'HOCO 32 MHz', 0, 0, 32 * MHZ, en('SYSTEM_CSC.HIOSTOP', 0, off=1, auto='on'),
                           tooltip='32 MHz HOCO base, selected by the option bytes the core links.'))
    nodes.append(factors('fih', 'fIH (HOCODIV)', 1, 0, 'hoco', 'SYSTEM_HOCODIV.HOCODIV', 0, HOCODIV))
    main_on_chip = 'fih'
    if moco:
        nodes += [
            fixed('moco', 'MOCO 4 MHz', 0, 1, 4 * MHZ, en('SYSTEM_CSC.MIOEN', 1 << 1)),
            factors('fim', 'fIM (MOCODIV)', 1, 1, 'moco', 'SYSTEM_MOCODIV.MOCODIV', 0, [(1, 0), (2, 1), (4, 2)]),
            mux('foco', 'fOCO (MCM1)', 2, 0, 'SYSTEM_CKC.MCM1', [('hoco', 'HOCO', 'fih', 0), ('moco', 'MOCO', 'fim', 1)]),
        ]
        main_on_chip = 'foco'
    nodes += [
        {'id': 'x1', 'label': 'X1 / EXCLK', 'kind': 'source', 'x': 0, 'y': 2, 'input': 'x1',
         'enable': en('SYSTEM_CSC.MSTOP', 0, off=1 << 7), 'tooltip': 'X1 resonator or external clock, 1-20 MHz.'},
        {'id': 'x1kind', 'label': 'X1 pin use', 'kind': 'mux', 'x': 0, 'y': 3, 'default': 'resonator',
         'options': [{'id': 'resonator', 'label': 'Resonator', 'mul': 1}, {'id': 'external', 'label': 'External clock', 'mul': 1}]},
        factors('fmx', 'fMX (MOSCDIV)', 1, 2, 'x1', 'SYSTEM_MOSCDIV.MOSCDIV', 0, [(1, 0), (2, 1), (4, 2), (8, 3), (16, 4)]),
        mux('fmain', 'fMAIN (MCM0)', 3, 0, 'SYSTEM_CKC.MCM0', [('oco', 'On-chip oscillator', main_on_chip, 0), ('fmx', 'fMX', 'fmx', 1 << 4)]),
    ]
    subclocks = [('loco', 'LOCO', 'loco', 1)]
    nodes.append(fixed('loco', 'LOCO 32.768 kHz', 0, 4, 32768))
    if xt1:
        nodes.append(fixed('xt1', 'XT1 32.768 kHz', 0, 5, 32768, en('SYSTEM_CSC.XTSTOP', 0, off=1 << 6)))
        subclocks.insert(0, ('xt1', 'XT1', 'xt1', 0))
    nodes += [
        mux('fsub', 'fSUB (SELLOSC)', 1, 4, 'SYSTEM_CKSEL.SELLOSC', subclocks),
        mux('fclk', 'fCLK (CSS)', 4, 0, 'SYSTEM_CKC.CSS', [('fmain', 'fMAIN', 'fmain', 0), ('fsub', 'fSUB', 'fsub', 1 << 6)],
            max=fclk_max, consumer=True),
    ]
    # The >10 MHz bit (AMPH) applies to the resonator only: an external clock is EXCLK at any frequency.
    x1_modes = [("sel.x1kind == 'external'", 0xC0), ('in.x1 > 10000000', 0x41)]
    derive = [{'field': 'SYSTEM_CMC.X1_MODE', 'cases': [{'when': "sel.fmain != 'fmx'", 'value': hexv(0)}] +
               [{'when': when, 'value': hexv(value)} for when, value in x1_modes], 'default': hexv(0x40)}]
    result = graph(graph_id, title, source, devices, 'fclk',
                   {'x1': {'label': 'X1 frequency', 'default': 8 * MHZ, 'min': 1 * MHZ, 'max': 20 * MHZ}}, nodes,
                   settings=['SYSTEM_CMC.XT1_MODE'] if xt1 else [], derive=derive)
    result['vendor'] = 'Renesas'
    return result


G23 = graph('rl78_g23', 'RL78/G23 clock tree', "RL78/G23 user's manual, Clock Generator", ['^R7F100G'], 'fclk', {},
            [fixed('hoco', 'HOCO 32 MHz', 0, 0, 32 * MHZ, tooltip='32 MHz HOCO base, selected by the option bytes the core links.'),
             factors('fclk', 'fCLK (HOCODIV)', 1, 0, 'hoco', 'SYSTEM_HOCODIV.HOCODIV', 0, HOCODIV, consumer=True,
                     tooltip='The G23 core runs from HOCO and requires FOSC_KHZ_VALUE = 32 MHz / HOCODIV.')])
G23['vendor'] = 'Renesas'

GRAPHS = [
    rl78('rl78_g21', 'RL78/G21 clock tree', "RL78/G21 user's manual, Clock Generator", ['^R7F103G'], 32 * MHZ, moco=False, xt1=False),
    G23,
    rl78('rl78_g24', 'RL78/G24 clock tree', "RL78/G24 user's manual, Clock Generator", ['^R7F101G'], 48 * MHZ, hoco_48=True),
    rl78('rl78_l23', 'RL78/L23 clock tree', "RL78/L23 user's manual, Clock Generator", ['^R7F100L'], 32 * MHZ),
]


def main():
    failed = False
    for item in GRAPHS:
        problems = check_graph(item)
        for problem in problems:
            print(f'{item["id"]}: {problem}')
        failed = failed or bool(problems)
        print(f'wrote {write_graph(item, f"renesas_rl78/{item["id"]}.json").relative_to(REPO_ROOT)}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
