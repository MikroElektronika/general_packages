"""Write the Renesas RX clock graphs (clock_graphs/renesas_rx/*.json).

Hand-written from the RX26T, RX66T, RX72M and RX74M/RX74N hardware manuals (Clock Generation
Circuit) for the fields the NECTO definitions expose and the core init_clock.c applies.
RX26T/RX66T/RX72M: HOCO/main oscillator -> PLL (PLLSRCSEL, PLIDIV, STC) -> SCKCR3.CKSEL -> SCKCR
dividers; init_clock.c starts and stops the oscillators the selection needs. RX74M/RX74N: the core
runs from HOCO only and requires FOSC_KHZ_VALUE = HOCO / CPUCK.
Register values are absolute bit values (see clock_graphs/README.md).

Run:  python scripts/clock_graphs/renesas_rx_graphs.py
"""

from graphlib import REPO_ROOT, check_graph, hexv, write_graph
from stm32_graphs import MHZ, en, external, factors, fixed, graph, mux, rule

LOG2 = [(1 << n, n) for n in range(7)]
STC = [x / 2 for x in range(20, 61)]  # x10.0 .. x30.0 in 0.5 steps, code 2 x mul - 1


def stc_id(factor):
    return str(factor).replace('.', '_')


def rx(graph_id, title, source, devices, limits, uclk=False, cfdclk=False, sosc=False, bck_max=None, constraints=()):
    """limits: maxima of iclk, pclka, pclkb, pclkc, pclkd, fclk."""
    iclk_max, pclka_max, pclkb_max, pclkc_max, pclkd_max, fclk_max = limits
    nodes = [
        {'id': 'hoco', 'label': 'HOCO', 'kind': 'source', 'x': 0, 'y': 0, 'enable': en('SYSTEM_HOCOCR.HCSTP', 0, off=1),
         'options': [{'id': str(mhz), 'label': f'HOCO {mhz} MHz', 'mul': mhz * MHZ, 'set': {'SYSTEM_HOCOCR2.HCFRQ': hexv(code)}}
                     for code, mhz in enumerate([16, 18, 20])]},
        external('mosc', 'Main oscillator', 0, 2, en('SYSTEM_MOSCCR.MOSTP', 0, off=1), tooltip='Resonator 8-24 MHz or external clock.'),
        fixed('loco', 'LOCO 240 kHz', 0, 4, 240000, en('SYSTEM_LOCOCR.LCSTP', 0, off=1)),
        mux('pllsrc', 'PLL source', 1, 1, 'SYSTEM_PLLCR.PLLSRCSEL', [('mosc', 'Main oscillator', 'mosc', 0), ('hoco', 'HOCO', 'hoco', 1 << 4)]),
        factors('plidiv', 'PLL /PLIDIV', 2, 1, 'pllsrc', 'SYSTEM_PLLCR.PLIDIV', 0, [(1, 0), (2, 1), (3, 2)], min=8 * MHZ, max=24 * MHZ,
                tooltip='PLL input: 8-24 MHz.'),
        {'id': 'pll', 'label': 'PLL xSTC', 'kind': 'multiplier', 'x': 3, 'y': 1, 'min': 120 * MHZ, 'max': 240 * MHZ,
         'enable': en('SYSTEM_PLLCR2.PLLEN', 0, off=1), 'tooltip': 'PLL output: 120-240 MHz.',
         'options': [{'id': stc_id(factor), 'label': f'x{factor:.1f}', 'from': 'plidiv', 'mul': int(factor * 2), 'div': 2,
                      'set': {'SYSTEM_PLLCR.STC': hexv((int(factor * 2) - 1) << 8)}} for factor in STC]},
    ]
    sources = [('loco', 'LOCO', 'loco', 0), ('hoco', 'HOCO', 'hoco', 1 << 8), ('mosc', 'Main oscillator', 'mosc', 2 << 8)]
    if sosc:
        nodes.append(fixed('sosc', 'Sub-clock 32.768 kHz', 0, 5, 32768, en('SYSTEM_SOSCCR.SOSTP', 0, off=1)))
        sources.append(('sosc', 'Sub-clock', 'sosc', 3 << 8))
    sources.append(('pll', 'PLL', 'pll', 4 << 8))
    nodes += [
        mux('cksel', 'Clock source (CKSEL)', 4, 0, 'SYSTEM_SCKCR3.CKSEL', sources),
        factors('iclk', 'ICLK (ICK)', 5, 0, 'cksel', 'SYSTEM_SCKCR.ICK', 24, LOG2, max=iclk_max, consumer=True),
        factors('pclka', 'PCLKA (PCKA)', 5, 1, 'cksel', 'SYSTEM_SCKCR.PCKA', 12, LOG2, max=pclka_max, consumer=True),
        factors('pclkb', 'PCLKB (PCKB)', 5, 2, 'cksel', 'SYSTEM_SCKCR.PCKB', 8, LOG2, max=pclkb_max, consumer=True),
        factors('pclkc', 'PCLKC (PCKC)', 5, 3, 'cksel', 'SYSTEM_SCKCR.PCKC', 4, LOG2, max=pclkc_max, consumer=True),
        factors('pclkd', 'PCLKD (PCKD)', 5, 4, 'cksel', 'SYSTEM_SCKCR.PCKD', 0, LOG2, max=pclkd_max, consumer=True),
        factors('fclk', 'FCLK (FCK)', 5, 5, 'cksel', 'SYSTEM_SCKCR.FCK', 28, LOG2, max=fclk_max, consumer=True),
    ]
    if bck_max:
        nodes.append(factors('bclk', 'BCLK (BCK)', 5, 6, 'cksel', 'SYSTEM_SCKCR.BCK', 16, LOG2, max=bck_max,
                             tooltip='External bus clock (used only with the external bus).'))
    if uclk:
        nodes.append(factors('uclk', 'UCLK (UCK)', 5, 7, 'pll', 'SYSTEM_SCKCR2.UCK', 4, [(2, 1), (3, 2), (4, 3), (5, 4)], max=48 * MHZ,
                             tooltip='USB needs 48 MHz from a main-oscillator PLL.'))
    if cfdclk:
        nodes.append(factors('cfdclk', 'CANFD clock (CFDCK)', 5, 7, 'cksel', 'SYSTEM_SCKCR2.CFDCK', 12, LOG2, max=60 * MHZ))
    result = graph(graph_id, title, source, devices, 'iclk',
                   {'mosc': {'label': 'Main oscillator frequency', 'default': 16 * MHZ, 'min': 8 * MHZ, 'max': 24 * MHZ}}, nodes,
                   settings=['SYSTEM_MOFCR.MOSEL'],
                   constraints=[rule('f.pclkb <= f.pclka', 'PCLKB must not be faster than PCLKA.'), *constraints])
    result['vendor'] = 'Renesas'
    return result


RX74 = graph(
    'rx74m_rx74n', 'RX74M/RX74N clock tree', 'RX74M/RX74N hardware manual, Clock Generation Circuit', ['^R5K574'], 'cpuclk', {},
    [
        {'id': 'hoco', 'label': 'HOCO', 'kind': 'source', 'x': 0, 'y': 0,
         'options': [{'id': str(mhz), 'label': f'HOCO {mhz} MHz', 'mul': mhz * MHZ, 'set': {'SYSTEM_HOCOCR2.HCFRQ': hexv(code)}}
                     for code, mhz in [(0, 16), (1, 18), (2, 20), (4, 32), (7, 48)]]},
        factors('cpuclk', 'CPUCLK (CPUCK)', 1, 0, 'hoco', 'SYSTEM_SCKDIVCR2.CPUCK', 0, LOG2, consumer=True),
        factors('iclk', 'ICLK (ICK)', 1, 1, 'hoco', 'SYSTEM_SCKDIVCR.ICK', 24, LOG2, consumer=True),
        factors('mriclk', 'MRICLK (MRICK)', 1, 2, 'hoco', 'SYSTEM_SCKDIVCR2.MRICK', 12, LOG2, consumer=True),
        factors('mrpclk', 'MRPCLK (MRPCK)', 1, 3, 'hoco', 'SYSTEM_SCKDIVCR.MRPCK', 28, LOG2, consumer=True),
        factors('pclka', 'PCLKA (PCKA)', 2, 0, 'hoco', 'SYSTEM_SCKDIVCR.PCKA', 12, LOG2, consumer=True),
        factors('pclkb', 'PCLKB (PCKB)', 2, 1, 'hoco', 'SYSTEM_SCKDIVCR.PCKB', 8, LOG2, consumer=True),
        factors('pclkc', 'PCLKC (PCKC)', 2, 2, 'hoco', 'SYSTEM_SCKDIVCR.PCKC', 4, LOG2, consumer=True),
        factors('pclkd', 'PCLKD (PCKD)', 2, 3, 'hoco', 'SYSTEM_SCKDIVCR.PCKD', 0, LOG2, consumer=True),
        factors('pclke', 'PCLKE (PCKE)', 2, 4, 'hoco', 'SYSTEM_SCKDIVCR.PCKE', 20, LOG2, consumer=True),
        factors('bclk', 'BCLK (BCK)', 2, 5, 'hoco', 'SYSTEM_SCKDIVCR.BCK', 16, LOG2),
    ],
    constraints=[rule('f.iclk <= f.cpuclk', 'ICLK must not be faster than CPUCLK.')])
RX74['vendor'] = 'Renesas'

GRAPHS = [
    rx('rx26t', 'RX26T clock tree', 'RX26T hardware manual, Clock Generation Circuit', ['^R5F526T'],
       (120 * MHZ, 120 * MHZ, 60 * MHZ, 120 * MHZ, 60 * MHZ, 60 * MHZ), cfdclk=True,
       constraints=[rule('f.pclkc == f.pclka || f.pclkc == 2 * f.pclka', 'PCLKC:PCLKA must be 1:1 or 2:1.')]),
    rx('rx66t', 'RX66T clock tree', 'RX66T hardware manual, Clock Generation Circuit', ['^R5F566T'],
       (160 * MHZ, 120 * MHZ, 60 * MHZ, 160 * MHZ, 60 * MHZ, 60 * MHZ), uclk=True, bck_max=60 * MHZ,
       constraints=[rule('f.pclkc == f.pclka || f.pclkc == 2 * f.pclka', 'PCLKC:PCLKA must be 1:1 or 2:1.')]),
    rx('rx72m', 'RX72M clock tree', 'RX72M hardware manual, Clock Generation Circuit', ['^R5F572M'],
       (240 * MHZ, 120 * MHZ, 60 * MHZ, 60 * MHZ, 60 * MHZ, 60 * MHZ), uclk=True, sosc=True, bck_max=120 * MHZ),
    RX74,
]


def main():
    failed = False
    for item in GRAPHS:
        problems = check_graph(item)
        for problem in problems:
            print(f'{item["id"]}: {problem}')
        failed = failed or bool(problems)
        print(f'wrote {write_graph(item, f"renesas_rx/{item["id"]}.json").relative_to(REPO_ROOT)}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
