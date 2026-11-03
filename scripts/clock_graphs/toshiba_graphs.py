"""Write the Toshiba TXZ+ clock graphs (clock_graphs/toshiba/*.json).

Hand-written from the TMPM3H, TMPM4K and TMPM4L reference manuals (Clock Control and Operation
Mode chapter) for the CGOSCCR/CGPLL0SEL/CGSYSCR fields the NECTO definitions expose and the core
SystemInit applies. fPLL = fpllref x PLL0SETIM / PLL0SELD (PLL0SELFM is kept 0); PLL0SELFOSC and
PLL0SELCORR follow the PLL reference frequency. FOSC_KHZ_VALUE is fc (before the clock gear).
Speed grades come from the NECTO database max_speed of each part.
Register values are absolute bit values (see clock_graphs/README.md).

Run:  python scripts/clock_graphs/toshiba_graphs.py
"""

from graphlib import REPO_ROOT, check_graph, hexv, write_graph
from stm32_graphs import MHZ, en, external, factors, fixed, graph, mux, rule

# PLL0SELFOSC: upper bound of each reference range (MHz) -> code.
FOSC_RANGES = [(7, 0), (8, 1), (10, 2), (12, 3), (15, 4), (19, 5), (24, 6)]


def toshiba(graph_id, title, source, devices, fc_max, corrections, xtal_max, pllref=False, mcksel=False, variants=()):
    """corrections: PLL reference MHz -> PLL0SELCORR code (only these references are supported)."""
    ref = 'pllref' if pllref else 'fosc'
    nodes = [
        fixed('ihosc1', 'IHOSC1 10 MHz', 0, 0, 10 * MHZ, en('SYSTEM_CGOSCCR.IHOSC1EN', 1, auto='on')),
        external('ehosc', 'EHOSC', 0, 1, None, tooltip=f'External crystal (EHOSC) or clock (EHCLKIN), 6-{xtal_max // MHZ} MHz.'),
        {'id': 'fosc', 'label': 'fosc (OSCSEL)', 'kind': 'mux', 'x': 1, 'y': 0,
         'options': [{'id': 'ihosc1', 'label': 'IHOSC1', 'from': 'ihosc1', 'set': {'SYSTEM_CGOSCCR.OSCSEL': hexv(0)}},
                     {'id': 'ehosc', 'label': 'EHOSC crystal', 'from': 'ehosc',
                      'set': {'SYSTEM_CGOSCCR.OSCSEL': hexv(1 << 8), 'SYSTEM_CGOSCCR.EOSCEN': hexv(1 << 1)}},
                     {'id': 'ehclkin', 'label': 'EHCLKIN clock input', 'from': 'ehosc',
                      'set': {'SYSTEM_CGOSCCR.OSCSEL': hexv(1 << 8), 'SYSTEM_CGOSCCR.EOSCEN': hexv(2 << 1)}}]},
    ]
    del nodes[1]['enable']
    if pllref:
        nodes.append(factors('pllref', 'PLL reference (PLLREFSEL)', 2, 1, 'fosc', 'SYSTEM_CGSYSCR.PLLREFSEL', 3,
                             [(1, 0), (2, 1), (3, 2), (4, 3)]))
    nodes += [
        {'id': 'pllmul', 'label': 'PLL xN (PLL0SETIM)', 'kind': 'multiplier', 'x': 3, 'y': 1,
         'enable': en('SYSTEM_CGPLL0SEL.PLL0ON', 1),
         'options': [{'id': str(n), 'label': f'x{n}', 'from': ref, 'mul': n,
                      'set': {'SYSTEM_CGPLL0SEL.PLL0SETIM': hexv(n << 8), 'SYSTEM_CGPLL0SEL.PLL0SELFM': hexv(0)}}
                     for n in range(1, 256)]},
        factors('pll', 'PLL /D (PLL0SELD)', 4, 1, 'pllmul', 'SYSTEM_CGPLL0SEL.PLL0SELD', 20, [(2, 1), (4, 2), (8, 3)]),
        mux('fc', 'fc (PLL0SEL)', 5, 0, 'SYSTEM_CGPLL0SEL.PLL0SEL', [('fosc', 'fosc (no PLL)', 'fosc', 0), ('pll', 'PLL', 'pll', 1 << 1)],
            max=fc_max, consumer=True),
        factors('fsys', 'fsys (GEAR)', 6, 0, 'fc', 'SYSTEM_CGSYSCR.GEAR', 0, [(1, 0), (2, 1), (4, 2), (8, 3), (16, 4)], consumer=True),
        factors('ft0', 'Peripheral prescaler (PRCK)', 6, 2, 'fc', 'SYSTEM_CGSYSCR.PRCK', 8, [(1 << n, n) for n in range(10)]),
    ]
    if mcksel:
        nodes.append(factors('fsysm', 'fsysm (MCKSEL)', 7, 0, 'fsys', 'SYSTEM_CGSYSCR.MCKSEL', 6, [(1, 0), (2, 1), (4, 2)], consumer=True))
    references = ' || '.join(f'f.{ref} == {mhz * MHZ}' for mhz in corrections)
    derive = [
        {'field': 'SYSTEM_CGPLL0SEL.PLL0SELFOSC',
         'cases': [{'when': f'f.{ref} <= {limit * MHZ}', 'value': hexv(code << 22)} for limit, code in FOSC_RANGES],
         'default': hexv(FOSC_RANGES[-1][1] << 22)},
        {'field': 'SYSTEM_CGPLL0SEL.PLL0SELCORR',
         'cases': [{'when': f'f.{ref} == {mhz * MHZ}', 'value': hexv(code << 25)} for mhz, code in corrections.items()],
         'default': hexv(next(iter(corrections.values())) << 25)},
    ]
    constraints = [rule(f"sel.fc != 'pll' || {references}",
                        f'The PLL reference must be {", ".join(str(m) for m in corrections)} MHz (PLL0SELCORR values).')]
    result = graph(graph_id, title, source, devices, 'fc',
                   {'ehosc': {'label': 'EHOSC frequency', 'default': 10 * MHZ, 'min': 6 * MHZ, 'max': xtal_max}}, nodes,
                   settings=['SYSTEM_CGOSCCR.IHOSC2EN'], derive=derive, constraints=constraints, variants=list(variants))
    result['vendor'] = 'Toshiba'
    return result


GRAPHS = [
    toshiba('tmpm3h', 'TMPM3H clock tree', 'TMPM3H group reference manuals, Clock Control (CG)', ['^TMPM3H'], 120 * MHZ,
            {6: 14, 8: 18, 10: 23, 12: 27}, 24 * MHZ, variants=[
                {'devices': ['^TMPM3H[0-6]'], 'limits': {'fc': {'max': 40 * MHZ}}},
                {'devices': ['^TMPM3H[L-Q]F(?!10B|[DYZ][AB])'], 'limits': {'fc': {'max': 80 * MHZ}}},
            ]),
    toshiba('tmpm4k', 'TMPM4K clock tree', 'TMPM4K group reference manuals, Clock Control (CG)', ['^TMPM4K'], 160 * MHZ,
            {6: 14, 8: 18, 10: 30, 12: 38}, 12 * MHZ, mcksel=True, variants=[
                {'devices': ['^TMPM4K[0-4]F..A'], 'limits': {'fc': {'max': 80 * MHZ}}},
                {'devices': ['^TMPM4K[0-4]F..B', '^TMPM4KH'], 'limits': {'fc': {'max': 120 * MHZ}}},
            ]),
    toshiba('tmpm4l', 'TMPM4L clock tree', 'TMPM4L group reference manual, Clock Control (CG)', ['^TMPM4L'], 80 * MHZ,
            {6: 14, 8: 18, 10: 30, 12: 38}, 12 * MHZ, pllref=True),
]


def main():
    failed = False
    for item in GRAPHS:
        problems = check_graph(item)
        for problem in problems:
            print(f'{item["id"]}: {problem}')
        failed = failed or bool(problems)
        print(f'wrote {write_graph(item, f"toshiba/{item["id"]}.json").relative_to(REPO_ROOT)}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
