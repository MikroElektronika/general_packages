"""Write the Analog Devices clock graphs (clock_graphs/adi/*.json).

Hand-written from the MAX32690 user guide (GCR clock control) for the GCR_CLKCTRL fields the NECTO
definition exposes and the core SystemInit applies.
Register values are absolute bit values (see clock_graphs/README.md).

Run:  python scripts/clock_graphs/adi_graphs.py
"""

from graphlib import REPO_ROOT, check_graph, hexv, write_graph
from stm32_graphs import MHZ, en, factors, fixed, graph

MAX32690 = graph(
    'max32690', 'MAX32690 clock tree', 'MAX32690 user guide UG7618, GCR clock control', ['^MAX32690'], 'sysclk', {},
    [
        fixed('ipo', 'IPO 120 MHz', 0, 0, 120 * MHZ, en('GCR_CLKCTRL.IPO_EN', 1 << 19)),
        fixed('iso', 'ISO 60 MHz', 0, 1, 60 * MHZ, en('GCR_CLKCTRL.ISO_EN', 1 << 18, auto='on'),
              tooltip='Internal secondary oscillator: the clock after reset.'),
        fixed('erfo', 'ERFO 32 MHz', 0, 2, 32 * MHZ, en('GCR_CLKCTRL.ERFO_EN', 1 << 16), tooltip='External 32 MHz crystal.'),
        fixed('ibro', 'IBRO 7.3728 MHz', 0, 3, 7372800),
        fixed('ertco', 'ERTCO 32.768 kHz', 0, 4, 32768, en('GCR_CLKCTRL.ERTCO_EN', 1 << 17), tooltip='External 32.768 kHz crystal.'),
        fixed('inro', 'INRO 8 kHz', 0, 5, 8000),
        {'id': 'sysosc', 'label': 'SYS_OSC (SYSCLK_SEL)', 'kind': 'mux', 'x': 1, 'y': 2,
         'options': [{'id': oid, 'label': text, 'from': source, 'set': {'GCR_CLKCTRL.SYSCLK_SEL': hexv(code << 9)}}
                     for oid, text, source, code in [('ipo', 'IPO', 'ipo', 4), ('iso', 'ISO', 'iso', 0), ('erfo', 'ERFO', 'erfo', 2),
                                                     ('ibro', 'IBRO', 'ibro', 5), ('ertco', 'ERTCO', 'ertco', 6), ('inro', 'INRO', 'inro', 3)]]},
        factors('sysclk', 'SYSCLK (SYSCLK_DIV)', 2, 2, 'sysosc', 'GCR_CLKCTRL.SYSCLK_DIV', 6, [(1 << n, n) for n in range(8)],
                max=120 * MHZ, consumer=True),
    ])
MAX32690['vendor'] = 'Analog Devices'

GRAPHS = [MAX32690]


def main():
    failed = False
    for item in GRAPHS:
        problems = check_graph(item)
        for problem in problems:
            print(f'{item["id"]}: {problem}')
        failed = failed or bool(problems)
        print(f'wrote {write_graph(item, f"adi/{item["id"]}.json").relative_to(REPO_ROOT)}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
