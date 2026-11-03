"""Write the Nuvoton clock graphs (clock_graphs/nuvoton/*.json).

Hand-written from the M2354 technical reference manual (Clock Controller) for the fields the NECTO
definitions expose and the core SystemInit applies: the core always runs the PLL from HIRC, and
HXT/LXT are left out (their enable bits are not in the definitions).
FOUT = FIN x 2 (FBDIV + 2) / ((INDIV + 1) NO), NO = 1, 2, 2, 4 for OUTDIV 0..3.
Register values are absolute bit values (see clock_graphs/README.md).

Run:  python scripts/clock_graphs/nuvoton_graphs.py
"""

from graphlib import REPO_ROOT, check_graph, hexv, write_graph
from stm32_graphs import MHZ, en, factors, fixed, graph, mux, span

M2354 = graph(
    'm2354', 'M2354 clock tree', 'M2354 technical reference manual, Clock Controller', ['^M2354'], 'hclk', {},
    [
        fixed('hirc', 'HIRC 12 MHz', 0, 0, 12 * MHZ, en('CLK_PWRCTL.HIRCEN', 1 << 2, auto='on')),
        fixed('hirc48', 'HIRC48 48 MHz', 0, 2, 48 * MHZ, en('CLK_PWRCTL.HIRC48EN', 1 << 18)),
        fixed('mirc', 'MIRC 4 MHz', 0, 3, 4 * MHZ, en('CLK_PWRCTL.MIRC', 1 << 21)),
        fixed('lirc', 'LIRC 32 kHz', 0, 4, 32000, en('CLK_PWRCTL.LIRCEN', 1 << 3)),
        span('indiv', 'PLL /NR (INDIV)', 1, 0, 'hirc', 'CLK_PLLCTL.INDIV', 9, 1, 32, 'div', offset=-1),
        {'id': 'fbdiv', 'label': 'PLL x2NF (FBDIV)', 'kind': 'multiplier', 'x': 2, 'y': 0,
         'options': [{'id': str(n), 'label': f'x2x{n}', 'from': 'indiv', 'mul': 2 * n, 'set': {'CLK_PLLCTL.FBDIV': hexv(n - 2)}}
                     for n in range(2, 514)]},
        factors('pll', 'PLL /NO (OUTDIV)', 3, 0, 'fbdiv', 'CLK_PLLCTL.OUTDIV', 14, [(1, 0), (2, 1), (4, 3)]),
        mux('hclksrc', 'HCLK source', 4, 1, 'CLK_CLKSEL0.HCLKSEL', [('pll', 'PLL', 'pll', 2), ('hirc', 'HIRC', 'hirc', 7),
                                                                 ('hirc48', 'HIRC48', 'hirc48', 5), ('mirc', 'MIRC', 'mirc', 6),
                                                                 ('lirc', 'LIRC', 'lirc', 3)]),
        span('hclk', 'HCLK (HCLKDIV)', 5, 1, 'hclksrc', 'CLK_CLKDIV0.HCLKDIV', 0, 1, 16, 'div', offset=-1, max=96 * MHZ, consumer=True),
    ])
M2354['vendor'] = 'Nuvoton'

GRAPHS = [M2354]


def main():
    failed = False
    for item in GRAPHS:
        problems = check_graph(item)
        for problem in problems:
            print(f'{item["id"]}: {problem}')
        failed = failed or bool(problems)
        print(f'wrote {write_graph(item, f"nuvoton/{item["id"]}.json").relative_to(REPO_ROOT)}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
