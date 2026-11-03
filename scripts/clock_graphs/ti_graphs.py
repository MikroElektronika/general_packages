"""Write the Texas Instruments clock graphs (clock_graphs/ti/*.json).

Hand-written from the TM4C123x (SPMS376) and TM4C129x (SPMS433) datasheets, System Control
chapter, for the register fields the NECTO definitions expose and the core systemInit applies.
Register values are absolute bit values (see clock_graphs/README.md).

Run:  python scripts/clock_graphs/ti_graphs.py
"""

from graphlib import REPO_ROOT, check_graph, hexv, write_graph
from stm32_graphs import MHZ, en, external, factors, fixed, graph, mux, rule, span


def ti(graph_id, title, source, devices, fosc, inputs, nodes, **extra):
    result = graph(graph_id, title, source, devices, fosc, inputs, nodes, **extra)
    result['vendor'] = 'Texas Instruments'
    return result


# TM4C123 RCC.XTAL codes: crystal frequency in Hz -> code (the PLL needs at least 5 MHz).
TM4C123_XTAL = [(4000000, 6), (4096000, 7), (4915200, 8), (5000000, 9), (5120000, 10), (6000000, 11), (6144000, 12),
                (7372800, 13), (8000000, 14), (8192000, 15), (10000000, 16), (12000000, 17), (12288000, 18),
                (13560000, 19), (14318180, 20), (16000000, 21), (16384000, 22), (18000000, 23), (20000000, 24),
                (24000000, 25), (25000000, 26)]

# The core runs RCC2 (USERCC2 = 1): OSCSRC2 picks the oscillator, the 400 MHz PLL output is divided
# by 2 x SYSDIV2 + SYSDIV2LSB + 1 (DIV400 = 1), the bypassed oscillator by SYSDIV2 + 1.
RCC2 = {'RCC2.USERCC2': hexv(1 << 31), 'RCC.USESYSDIV': hexv(1 << 22)}


def tm4c123_pll_divider(divisor):
    code = divisor - 1
    return {'RCC2.DIV400': hexv(1 << 30), 'RCC2.SYSDIV2': hexv((code >> 1) << 23), 'RCC2.SYSDIV2LSB': hexv((code & 1) << 22)}


TM4C123 = ti(
    'tm4c123', 'TM4C123 system clock tree', 'TM4C123x datasheet SPMS376, System Control (RCC/RCC2)', ['^TM4C123'], 'sysclk',
    {'mosc': {'label': 'Main oscillator (crystal)', 'default': 16 * MHZ, 'min': 4 * MHZ, 'max': 25 * MHZ}},
    [
        external('mosc', 'MOSC', 0, 0, en('RCC.MOSCDIS', 0, off=1), tooltip='Main oscillator: a 4-25 MHz crystal; RCC.XTAL follows it.'),
        fixed('piosc', 'PIOSC 16 MHz', 0, 1, 16 * MHZ, en('RCC.IOSCDIS', 0, off=1 << 1, auto='on')),
        {'id': 'piosc4', 'label': 'PIOSC/4', 'kind': 'divider', 'x': 1, 'y': 2,
         'options': [{'id': '4', 'label': '/4', 'from': 'piosc', 'div': 4}]},
        fixed('lfiosc', 'LFIOSC 30 kHz', 0, 3, 30000),
        {'id': 'oscsrc', 'label': 'Oscillator source', 'kind': 'mux', 'x': 2, 'y': 1,
         'options': [{'id': oid, 'label': text, 'from': source,
                      'set': {'RCC2.OSCSCR2': hexv(code << 4), 'RCC.OSCSCR': hexv(code << 4)}}
                     for oid, text, source, code in [('mosc', 'MOSC', 'mosc', 0), ('piosc', 'PIOSC', 'piosc', 1),
                                                     ('piosc4', 'PIOSC/4', 'piosc4', 2), ('lfiosc', 'LFIOSC', 'lfiosc', 3)]]},
        {'id': 'pll', 'label': 'PLL 400 MHz', 'kind': 'source', 'x': 3, 'y': 0, 'enable': en('RCC2.PWRDN2', 0, off=1 << 13),
         'tooltip': 'The PLL runs at 400 MHz from MOSC (5 MHz or more) or PIOSC.',
         'options': [{'id': 'on', 'label': 'PLL 400 MHz', 'mul': 400 * MHZ, 'keeps': ['oscsrc']}]},
        {'id': 'plldiv', 'label': 'PLL divider (SYSDIV2)', 'kind': 'divider', 'x': 4, 'y': 0,
         'options': [{'id': str(n), 'label': f'/{n}', 'from': 'pll', 'div': n, 'set': tm4c123_pll_divider(n)} for n in range(5, 129)]},
        span('oscdiv', 'Oscillator divider (SYSDIV2)', 4, 2, 'oscsrc', 'RCC2.SYSDIV2', 23, 1, 64, 'div', offset=-1),
        {'id': 'sysclk', 'label': 'System clock', 'kind': 'mux', 'x': 5, 'y': 1, 'max': 80 * MHZ, 'consumer': True,
         'options': [{'id': 'pll', 'label': 'PLL', 'from': 'plldiv', 'set': {**RCC2, 'RCC2.BYPASS2': hexv(0)}},
                     {'id': 'osc', 'label': 'Oscillator (PLL bypassed)', 'from': 'oscdiv',
                      'set': {**RCC2, 'RCC2.BYPASS2': hexv(1 << 11), 'RCC2.DIV400': hexv(0)}}]},
    ],
    settings=['RCC2.USBPWRDN'],
    derive=[{'field': 'RCC.XTAL', 'cases': [{'when': "sel.oscsrc != 'mosc'", 'value': hexv(21 << 6)}] +
             [{'when': f'in.mosc == {hz}', 'value': hexv(code << 6)} for hz, code in TM4C123_XTAL], 'default': hexv(21 << 6)}],
    constraints=[
        rule("sel.oscsrc != 'mosc' || " + ' || '.join(f'in.mosc == {hz}' for hz, _ in TM4C123_XTAL),
             'RCC.XTAL lists the supported crystals: 4, 4.096, 4.9152, 5, 5.12, 6, 6.144, 7.3728, 8, 8.192, 10, 12, 12.288, 13.56, '
             '14.31818, 16, 16.384, 18, 20, 24 or 25 MHz.'),
        rule("sel.sysclk != 'pll' || sel.oscsrc == 'piosc' || (sel.oscsrc == 'mosc' && in.mosc >= 5000000)",
             'The PLL needs PIOSC or a main oscillator of at least 5 MHz.'),
    ])

# TM4C129: VCO = PLL input / ((Q + 1)(N + 1)) x MINT, only 320 or 480 MHz; SYSCLK = VCO / (PSYSDIV + 1),
# at most 120 MHz. systemInit sets the flash/EEPROM timing from FOSC_KHZ_VALUE.
TM4C129 = ti(
    'tm4c129', 'TM4C129 system clock tree', 'TM4C129x datasheet SPMS433, System Control (RSCLKCFG, PLLFREQ0/1)', ['^TM4C129'], 'sysclk',
    {'mosc': {'label': 'Main oscillator (crystal)', 'default': 25 * MHZ, 'min': 4 * MHZ, 'max': 25 * MHZ}},
    [
        external('mosc', 'MOSC', 0, 0, en('MOSCCTL.PWRDN', 0, off=1 << 3), tooltip='Main oscillator: 4-25 MHz.'),
        fixed('piosc', 'PIOSC 16 MHz', 0, 1, 16 * MHZ),
        fixed('lfiosc', 'LFIOSC 33 kHz', 0, 2, 33000),
        fixed('rtcosc', 'RTC oscillator 32.768 kHz', 0, 3, 32768),
        mux('pllsrc', 'PLL source', 1, 0, 'RSCLKCFG.PLLSRC', [('piosc', 'PIOSC', 'piosc', 0), ('mosc', 'MOSC', 'mosc', 3 << 24)]),
        span('plln', 'PLL /(N+1)', 2, 0, 'pllsrc', 'PLLFREQ1.N', 0, 1, 32, 'div', offset=-1),
        span('pllq', 'PLL /(Q+1)', 3, 0, 'plln', 'PLLFREQ1.Q', 8, 1, 32, 'div', offset=-1),
        {'id': 'mint', 'label': 'PLL xMINT (VCO)', 'kind': 'multiplier', 'x': 4, 'y': 0, 'min': 320 * MHZ, 'max': 480 * MHZ,
         'enable': en('PLLFREQ0.PLLPWR', 1 << 23), 'tooltip': 'VCO: 320 or 480 MHz (MFRAC is kept 0).',
         'options': [{'id': str(n), 'label': f'x{n}', 'from': 'pllq', 'mul': n,
                      'set': {'PLLFREQ0.MINT': hexv(n), 'PLLFREQ0.MFRAC': hexv(0)}} for n in range(4, 1024)]},
        span('psysdiv', 'PSYSDIV', 5, 0, 'mint', 'RSCLKCFG.PSYSDIV', 0, 1, 1024, 'div', offset=-1),
        mux('oscsrc', 'Oscillator source', 1, 2, 'RSCLKCFG.OSCSRC', [('piosc', 'PIOSC', 'piosc', 0), ('lfiosc', 'LFIOSC', 'lfiosc', 2 << 20),
                                                                    ('mosc', 'MOSC', 'mosc', 3 << 20), ('rtcosc', 'RTCOSC', 'rtcosc', 4 << 20)]),
        span('osysdiv', 'OSYSDIV', 5, 2, 'oscsrc', 'RSCLKCFG.OSYSDIV', 10, 1, 1024, 'div', offset=-1),
        mux('sysclk', 'System clock', 6, 1, 'RSCLKCFG.USEPLL', [('pll', 'PLL', 'psysdiv', 1 << 28), ('osc', 'Oscillator', 'osysdiv', 0)],
            max=120 * MHZ, consumer=True),
    ],
    settings=['MOSCCTL.NOXTAL', 'MOSCCTL.SESRC'],
    derive=[{'field': 'MOSCCTL.OSCRNG', 'cases': [{'when': 'in.mosc >= 10000000', 'value': hexv(1 << 4)}], 'default': hexv(0)}],
    constraints=[
        rule("sel.sysclk != 'pll' || f.mint == 320000000 || f.mint == 480000000", 'The PLL VCO must be exactly 320 or 480 MHz.'),
    ])

# MSPM0: SYSOSC (32/4 MHz, user 16/24 MHz), HFXT and SYSPLL (MSPM0G only), MCLK from SYSOSC / MDIV,
# HSCLK (SYSPLL or HFCLK) or LFCLK, ULPCLK = MCLK / UDIV. SYSPLL: VCO = ref / PDIV x (QDIV + 1),
# CLK0/CLK1 = VCO / (2 (RDIV + 1)), CLK2X = 2 VCO / (RDIV + 1). Flash wait states follow MCLK.
MSPM0 = ti(
    'mspm0', 'MSPM0 clock tree', 'MSPM0 G/L/C technical reference manuals SLAU846/SLAU847/SLAU893, SYSCTL', ['^MSPM0'], 'mclk',
    {'hfxt': {'label': 'HFXT frequency', 'default': 40 * MHZ, 'min': 4 * MHZ, 'max': 48 * MHZ}},
    [
        {'id': 'sysosc', 'label': 'SYSOSC', 'kind': 'source', 'x': 0, 'y': 0,
         'options': [{'id': '32m', 'label': 'SYSOSC 32 MHz', 'mul': 32 * MHZ, 'set': {'SYSOSCCFG.FREQ': hexv(0)}},
                     {'id': '4m', 'label': 'SYSOSC 4 MHz', 'mul': 4 * MHZ, 'set': {'SYSOSCCFG.FREQ': hexv(1)}},
                     {'id': '24m', 'label': 'SYSOSC 24 MHz (user trim)', 'mul': 24 * MHZ,
                      'set': {'SYSOSCCFG.FREQ': hexv(2), 'SYSOSCTRIMUSER.FREQ': hexv(2)}},
                     {'id': '16m', 'label': 'SYSOSC 16 MHz (user trim)', 'mul': 16 * MHZ,
                      'set': {'SYSOSCCFG.FREQ': hexv(2), 'SYSOSCTRIMUSER.FREQ': hexv(1)}}]},
        external('hfxt', 'HFXT', 0, 2, en('HSCLKEN.HFXTEN', 1), tooltip='High-frequency crystal, 4-48 MHz (MSPM0G).'),
        fixed('lfclk', 'LFCLK 32.768 kHz', 0, 4, 32768),
        mux('pllref', 'SYSPLL reference', 1, 1, 'SYSPLLCFG0.SYSPLLREF', [('sysosc', 'SYSOSC', 'sysosc', 0), ('hfclk', 'HFCLK', 'hfxt', 1)]),
        factors('pdiv', 'SYSPLL /PDIV', 2, 1, 'pllref', 'SYSPLLCFG1.PDIV', 0, [(1, 0), (2, 1), (4, 2), (8, 3)]),
        span('vco', 'SYSPLL xQDIV (VCO)', 3, 1, 'pdiv', 'SYSPLLCFG1.QDIV', 8, 2, 128, 'mul', offset=-1, min=80 * MHZ, max=400 * MHZ,
             enable=en('HSCLKEN.SYSPLLEN', 1 << 8), tooltip='VCO: 80-400 MHz.'),
        {'id': 'clk2x', 'label': 'SYSPLLCLK2X', 'kind': 'divider', 'x': 4, 'y': 1, 'enable': en('SYSPLLCFG0.ENABLECLK2X', 1 << 6),
         'options': [{'id': str(n), 'label': f'x2 /{n}', 'from': 'vco', 'mul': 2, 'div': n,
                      'set': {'SYSPLLCFG0.RDIVCLK2X': hexv((n - 1) << 16)}} for n in range(1, 17)]},
        {'id': 'clk0', 'label': 'SYSPLLCLK0', 'kind': 'divider', 'x': 4, 'y': 2, 'enable': en('SYSPLLCFG0.ENABLECLK0', 1 << 4),
         'options': [{'id': str(2 * n), 'label': f'/{2 * n}', 'from': 'vco', 'div': 2 * n,
                      'set': {'SYSPLLCFG0.RDIVCLK0': hexv((n - 1) << 8)}} for n in range(1, 17)]},
        {'id': 'clk1', 'label': 'SYSPLLCLK1', 'kind': 'divider', 'x': 4, 'y': 3, 'enable': en('SYSPLLCFG0.ENABLECLK1', 1 << 5),
         'tooltip': 'SYSPLLCLK1 clocks CAN-FD and can be routed to CLK_OUT.',
         'options': [{'id': str(2 * n), 'label': f'/{2 * n}', 'from': 'vco', 'div': 2 * n,
                      'set': {'SYSPLLCFG0.RDIVCLK1': hexv((n - 1) << 12)}} for n in range(1, 17)]},
        mux('pllout', 'SYSPLL to HSCLK', 5, 1, 'SYSPLLCFG0.MCLK2XVCO', [('clk2x', 'SYSPLLCLK2X', 'clk2x', 1 << 1), ('clk0', 'SYSPLLCLK0', 'clk0', 0)]),
        mux('hsclk', 'HSCLK', 6, 1, 'HSCLKCFG.HSCLKSEL', [('syspll', 'SYSPLL', 'pllout', 0), ('hfclk', 'HFCLK', 'hfxt', 1)]),
        factors('mdiv', 'SYSOSC /MDIV', 2, 0, 'sysosc', 'MCLKCFG.MDIV', 0, [(n, n - 1) for n in range(1, 17)],
                tooltip='MDIV divides SYSOSC only when MCLK runs from SYSOSC.'),
        {'id': 'mclk', 'label': 'MCLK', 'kind': 'mux', 'x': 7, 'y': 0, 'max': 80 * MHZ, 'consumer': True,
         # MSPM0L/C have no HSCLK: USEHSCLK is written where it exists.
         'options': [{'id': 'sysosc', 'label': 'SYSOSC', 'from': 'mdiv', 'set': {'?MCLKCFG.USEHSCLK': hexv(0), 'MCLKCFG.USELFCLK': hexv(0)}},
                     {'id': 'hsclk', 'label': 'HSCLK', 'from': 'hsclk', 'set': {'MCLKCFG.USEHSCLK': hexv(1 << 16), 'MCLKCFG.USELFCLK': hexv(0)}},
                     {'id': 'lfclk', 'label': 'LFCLK', 'from': 'lfclk', 'set': {'?MCLKCFG.USEHSCLK': hexv(0), 'MCLKCFG.USELFCLK': hexv(1 << 20)}}]},
        factors('ulpclk', 'ULPCLK (UDIV)', 8, 0, 'mclk', 'MCLKCFG.UDIV', 4, [(1, 0), (2, 1), (3, 2)], max=40 * MHZ, consumer=True),
    ],
    settings=['HSCLKEN.USEEXTHFCLK'],
    derive=[
        {'field': 'MCLKCFG.FLASHWAIT', 'cases': [{'when': 'f.mclk <= 24000000', 'value': hexv(0)},
                                                 {'when': 'f.mclk <= 48000000', 'value': hexv(1 << 8)}], 'default': hexv(2 << 8)},
        {'field': 'HFCLKCLKCFG.HFXTRSEL', 'cases': [{'when': f'in.hfxt <= {limit * MHZ}', 'value': hexv(code << 12)}
                                                    for code, limit in enumerate([8, 16, 32])], 'default': hexv(3 << 12)},
    ],
    variants=[
        {'devices': ['^MSPM0L'], 'limits': {'mclk': {'max': 32 * MHZ}, 'ulpclk': {'max': 32 * MHZ}}},
        {'devices': ['^MSPM0C'], 'limits': {'mclk': {'max': 24 * MHZ}, 'ulpclk': {'max': 24 * MHZ}}},
    ])

GRAPHS = [TM4C123, TM4C129, MSPM0]


def main():
    failed = False
    for item in GRAPHS:
        problems = check_graph(item)
        for problem in problems:
            print(f'{item["id"]}: {problem}')
        failed = failed or bool(problems)
        print(f'wrote {write_graph(item, f"ti/{item["id"]}.json").relative_to(REPO_ROOT)}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
