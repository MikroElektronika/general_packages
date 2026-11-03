"""Write the GigaDevice clock graphs (clock_graphs/gigadevice/*.json).

Hand-written from the GD32VF103 user manual (RCU chapter) for the RCU fields the NECTO definitions
expose and the RISC-V core (system_gd32vf103x.c) applies. The RCU follows the STM32F105/107
connectivity-line design: PREDV1 -> PLL1 -> PREDV0SEL -> PREDV0 -> PLLSEL -> PLLMF -> SCS.
Register values are absolute bit values (see clock_graphs/README.md).

Run:  python scripts/clock_graphs/gigadevice_graphs.py
"""

from graphlib import REPO_ROOT, check_graph, hexv, write_graph
from stm32_graphs import AHB, APB, MHZ, en, external, factors, fixed, fixed_div, graph, mux, span


def pllmf_value(factor):
    """PLLMF is split: bits 21:18 plus bit 29 for x17..x32."""
    if factor == 6.5:
        return 13 << 18
    if factor == 16:
        return 14 << 18
    if factor >= 17:
        return (1 << 29) | ((factor - 17) << 18)
    return (factor - 2) << 18


PLLMF = [2, 3, 4, 5, 6, 6.5, 7, 8, 9, 10, 11, 12, 13, 14, 16] + list(range(17, 33))

GD32VF103 = graph(
    'gd32vf103', 'GD32VF103 clock tree', 'GD32VF103 user manual, Reset and clock unit (RCU)', ['^GD32VF103'], 'sysclk',
    {'hxtal': {'label': 'HXTAL frequency', 'default': 8 * MHZ, 'min': 4 * MHZ, 'max': 32 * MHZ}},
    [
        fixed('irc8m', 'IRC8M 8 MHz', 0, 0, 8 * MHZ, en('RCU_CTL.IRC8MEN', 1, auto='on')),
        fixed_div('irc8m_div2', 'IRC8M/2', 3, 0, 'irc8m', 2),
        external('hxtal', 'HXTAL', 0, 2, en('RCU_CTL.HXTALEN', 1 << 16)),
        span('predv1', 'PREDV1', 1, 4, 'hxtal', 'RCU_CFG1.PREDV1', 4, 1, 16, 'div', offset=-1),
        factors('pll1', 'PLL1MF', 2, 4, 'predv1', 'RCU_CFG1.PLL1MF', 8,
                [(8, 6), (9, 7), (10, 8), (11, 9), (12, 10), (13, 11), (14, 12), (15, 13), (16, 14), (20, 15)], op='mul',
                enable=en('RCU_CTL.PLL1EN', 1 << 26)),
        mux('predv0sel', 'PREDV0 source', 2, 2, 'RCU_CFG1.PREDV0SEL', [('hxtal', 'HXTAL', 'hxtal', 0), ('pll1', 'PLL1', 'pll1', 1 << 16)]),
        span('predv0', 'PREDV0', 3, 2, 'predv0sel', 'RCU_CFG1.PREDV0', 0, 1, 16, 'div', offset=-1),
        mux('pllsel', 'PLL source', 4, 1, 'RCU_CFG0.PLLSEL', [('irc8m', 'IRC8M/2', 'irc8m_div2', 0), ('predv0', 'PREDV0', 'predv0', 1 << 16)]),
        {'id': 'pll', 'label': 'PLLMF', 'kind': 'multiplier', 'x': 5, 'y': 1, 'max': 108 * MHZ, 'enable': en('RCU_CTL.PLLEN', 1 << 24),
         'options': [{'id': str(factor).replace('.', '_'), 'label': f'x{factor}', 'from': 'pllsel',
                      **({'mul': 13, 'div': 2} if factor == 6.5 else {'mul': factor}),
                      'set': {'RCU_CFG0.PLLMF': hexv(pllmf_value(factor))}} for factor in PLLMF]},
        factors('usbfs', 'USBFS prescaler', 6, 3, 'pll', 'RCU_CFG0.USBFSPSC', 22, [(1.5, 0), (1, 1), (2, 3)], max=48 * MHZ,
                tooltip='USBFS needs 48 MHz.'),
        mux('sysclk', 'System clock (SCS)', 6, 0, 'RCU_CFG0.SCS', [('irc8m', 'IRC8M', 'irc8m', 0), ('hxtal', 'HXTAL', 'hxtal', 1),
                                                                 ('pll', 'PLL', 'pll', 2)], max=108 * MHZ),
        factors('ahb', 'AHB (AHBPSC)', 7, 0, 'sysclk', 'RCU_CFG0.AHBPSC', 4, AHB, max=108 * MHZ, consumer=True),
        factors('apb1', 'APB1 (APB1PSC)', 8, 0, 'ahb', 'RCU_CFG0.APB1PSC', 8, APB, max=54 * MHZ, consumer=True),
        factors('apb2', 'APB2 (APB2PSC)', 8, 1, 'ahb', 'RCU_CFG0.APB2PSC', 11, APB, max=108 * MHZ, consumer=True),
    ],
    settings=['RCU_CTL.HXTALBPS', 'RCU_CTL.CKMEN'])
GD32VF103['vendor'] = 'GigaDevice'

GRAPHS = [GD32VF103]


def main():
    failed = False
    for item in GRAPHS:
        problems = check_graph(item)
        for problem in problems:
            print(f'{item["id"]}: {problem}')
        failed = failed or bool(problems)
        print(f'wrote {write_graph(item, f"gigadevice/{item["id"]}.json").relative_to(REPO_ROOT)}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
