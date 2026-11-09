"""Write the HPMicro clock graphs (clock_graphs/hpmicro/*.json).

Hand-written from the HPMicro SDK register definitions and clock drivers for HPM5300
(soc/HPM5300/ip/hpm_pllctlv2_regs.h, hpm_sysctl_regs.h, hpm_pcfg_regs.h, HPM5301/hpm_clock_drv.c;
BSD-3-Clause) for the fields the NECTO definition exposes and the RISC-V core
(system/src/hpmicro/hpm5301/init_clock.c) applies:

  IRC24M / XTAL24M -> REFSEL -> PLLx (24 MHz x MFI, MFN = 0) -> PLLx_CLKy (/(1 + DIV/5))
  OSC0_CLK0 / PLLx_CLKy -> SYSCTL node MUX -> node DIV (/1../256)

Register values are absolute bit values (see clock_graphs/README.md).

Run:  python scripts/clock_graphs/hpmicro_graphs.py
"""

from graphlib import REPO_ROOT, check_graph, hexv, write_graph
from stm32_graphs import MHZ, fixed, graph, mux, rule, span

# SYSCTL clock node sources (MUX value << 8).
SOURCES = [('osc0', 'OSC0_CLK0', 'osc0'), ('pll0_clk0', 'PLL0_CLK0', 'pll0_clk0'), ('pll0_clk1', 'PLL0_CLK1', 'pll0_clk1'),
           ('pll0_clk2', 'PLL0_CLK2', 'pll0_clk2'), ('pll1_clk0', 'PLL1_CLK0', 'pll1_clk0'), ('pll1_clk1', 'PLL1_CLK1', 'pll1_clk1'),
           ('pll1_clk2', 'PLL1_CLK2', 'pll1_clk2'), ('pll1_clk3', 'PLL1_CLK3', 'pll1_clk3')]


def source_mux(node_id, label, x, y, field, **extra):
    return mux(node_id, label, x, y, field, [(oid, text, src, index << 8) for index, (oid, text, src) in enumerate(SOURCES)],
               **extra)


def post_divider(node_id, label, x, y, source, field):
    """PLL post divider: factor 1 + DIV/5 = (5 + DIV) / 5, DIV 0..63 (/1.0 .. /13.6)."""
    options = []
    for raw in range(64):
        tenths = 10 + raw * 2
        options.append({'id': f'd{raw}', 'label': f'/{tenths // 10}.{tenths % 10}', 'from': source, 'mul': 5, 'div': 5 + raw,
                        'set': {field: hexv(raw)}})
    return {'id': node_id, 'label': label, 'kind': 'divider', 'x': x, 'y': y, 'options': options}


def node_divider(node_id, label, x, y, source, field, lsb=0, high=256, **extra):
    return span(node_id, label, x, y, source, field, lsb, 1, high, 'div', offset=-1, **extra)


def pll(index, y, outputs):
    nodes = [
        mux(f'pll{index}_ref', f'PLL{index} reference', 1, y, f'PLLCTLV2_PLL{index}_CONFIG.REFSEL',
            [('xtal', 'XTAL24M', 'xtal', 0), ('irc', 'IRC24M', 'irc24m', 1)]),
        span(f'pll{index}', f'PLL{index} (x MFI)', 2, y, f'pll{index}_ref', f'PLLCTLV2_PLL{index}_MFI.MFI', 0, 16, 42, 'mul',
             min=384 * MHZ, max=1008 * MHZ, tooltip='PLL output = 24 MHz x MFI (MFN = 0), 384-1008 MHz.'),
    ]
    for clk in range(outputs):
        nodes.append(post_divider(f'pll{index}_clk{clk}', f'PLL{index}_CLK{clk}', 3, y + clk, f'pll{index}',
                                  f'PLLCTLV2_PLL{index}_DIV{clk}.DIV'))
    return nodes


# (register key, node id, label, tooltip)
PERIPHERALS = [
    ('MCT0', 'mct0', 'MCHTMR0', 'Machine timer (mtime) clock.'),
    ('TMR0', 'tmr0', 'GPTMR0', None),
    ('TMR1', 'tmr1', 'GPTMR1', None),
    ('I2C0', 'i2c0', 'I2C0', None),
    ('I2C1', 'i2c1', 'I2C1', None),
    ('I2C2', 'i2c2', 'I2C2', None),
    ('I2C3', 'i2c3', 'I2C3', None),
    ('SPI0', 'spi0', 'SPI0', None),
    ('SPI1', 'spi1', 'SPI1', None),
    ('SPI2', 'spi2', 'SPI2', None),
    ('SPI3', 'spi3', 'SPI3', None),
    ('URT0', 'urt0', 'UART0', None),
    ('URT1', 'urt1', 'UART1', None),
    ('URT2', 'urt2', 'UART2', None),
    ('URT3', 'urt3', 'UART3', None),
    ('ANA0', 'ana0', 'ANA0 (ADC0 analog)', None),
    ('REF0', 'ref0', 'REF0 output', 'Reference clock output pin.'),
    ('REF1', 'ref1', 'REF1 output', 'Reference clock output pin.'),
]


def hpm5301():
    nodes = [
        fixed('irc24m', 'IRC24M 24 MHz', 0, 0, 24 * MHZ, tooltip='Internal 24 MHz RC oscillator.'),
        fixed('xtal', 'XTAL24M 24 MHz', 0, 1, 24 * MHZ,
              tooltip='24 MHz crystal. Started by the core when a PLL references it; without a crystal the PLLs fall back to IRC24M.'),
        fixed('osc0', 'OSC0_CLK0 24 MHz', 0, 3, 24 * MHZ, tooltip='24 MHz oscillator clock (osc0_clk0).'),
    ]
    nodes += pll(0, 0, 3)
    nodes += pll(1, 4, 4)
    nodes += [
        source_mux('cpu_src', 'CPU0 source', 4, 0, 'SYSCTL_CLOCK_CPU0.MUX'),
        node_divider('cpu', 'CPU0 (DIV)', 5, 0, 'cpu_src', 'SYSCTL_CLOCK_CPU0.DIV', max=480 * MHZ, consumer=True),
        node_divider('ahb', 'AHB (SUB0_DIV)', 6, 0, 'cpu', 'SYSCTL_CLOCK_CPU0.SUB0_DIV', lsb=16, high=16, max=200 * MHZ,
                     consumer=True),
    ]
    for row, (key, node_id, label, tooltip) in enumerate(PERIPHERALS, start=1):
        extra = {'tooltip': tooltip} if tooltip else {}
        nodes.append(source_mux(f'{node_id}_src', f'{label} source', 4, row, f'SYSCTL_CLOCK_{key}.MUX'))
        nodes.append(node_divider(node_id, label, 5, row, f'{node_id}_src', f'SYSCTL_CLOCK_{key}.DIV', consumer=True, **extra))
    nodes.append(mux('adc0', 'ADC0 clock', 6, 16, 'SYSCTL_ADCCLK0.MUX', [('ahb', 'AHB', 'ahb', 0), ('ana0', 'ANA0', 'ana0', 1 << 8)],
                     consumer=True))
    result = graph(
        'hpm5301', 'HPM5301 clock tree',
        'HPMicro HPM SDK v1.13 register definitions and clock drivers (PLLCTLV2, SYSCTL, PCFG)', ['^HPM5301'], 'cpu', {}, nodes,
        settings=['PCFG_DCDC_MODE.VOLT'],
        constraints=[
            rule('f.cpu <= 360e6 || reg("PCFG_DCDC_MODE.VOLT") == 0 || reg("PCFG_DCDC_MODE.VOLT") >= 1275',
                 'CPU0 above 360 MHz needs a DCDC voltage of at least 1275 mV (HPM SDK hpm5300evk setting for 480 MHz)'),
        ])
    result['vendor'] = 'HPMicro'
    return result


GRAPHS = [hpm5301()]


def main():
    failed = False
    for item in GRAPHS:
        problems = check_graph(item)
        for problem in problems:
            print(f'{item["id"]}: {problem}')
        failed = failed or bool(problems)
        print(f'wrote {write_graph(item, f"hpmicro/{item["id"]}.json").relative_to(REPO_ROOT)}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
