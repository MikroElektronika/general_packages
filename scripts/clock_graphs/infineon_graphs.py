"""Write the Infineon clock graphs (clock_graphs/infineon/*.json).

Hand-written from the reference manuals and data sheets of the XMC1000/XMC4000, PSOC 4 and
FM0+/FM3/FM4 families, for the register sets the core_packages system library applies
(ARM/gcc_clang/system/src/infineon/<group>/init_clock.c):

  XMC1100-1300  SCU_CLKCR: DCO1 64 MHz / 2 / IDIV -> MCLK, PCLK = MCLK or 2 x MCLK
  XMC1400       + SCU_CLKCR1.DCLKSEL (DCO1 or OSC_HP, x 2), SCU_ANAOSCHPCTRL (OSC_HP)
  XMC4000       OSC_HP / fOFI -> main PLL (P, N, K2) -> fSYS -> fCPU / fPERIPH / fCCU
  PSOC 4        IMO (24-48 MHz) / EXTCLK / EXCO (ECO crystal, PLL) -> HFCLK -> SYSCLK
  FM0+/FM3/FM4  high-speed CR / main oscillator -> main PLL (K, N, M) -> HCLK -> PCLK0..2

Register values are absolute bit values (see clock_graphs/README.md). The fractional MCLK
divider of the XMC1 (FDIV) is kept at 0 by the graph: only integer dividers are offered.
The default clocks of the system library run the FM parts from the high-speed CR through the
PLL about 3-5 % below the data sheet maximum (the trimmed CR can be that fast); the graphs check
the same headroom when the CR feeds the PLL.

Run:  python scripts/clock_graphs/infineon_graphs.py
"""

from graphlib import REPO_ROOT, check_graph, hexv, write_graph
from stm32_graphs import MHZ, en, external, factors, fixed, graph, mux, rule, span

VENDOR = 'Infineon'
BINARY = [(1, 0), (2, 1), (4, 2), (8, 3)]            # /1 /2 /4 /8 encodings (PSOC 4, FM APBC)
FM_BSR = [(1, 0), (2, 1), (3, 2), (4, 3), (6, 4), (8, 5), (16, 6)]


def finish(item):
    item['vendor'] = VENDOR
    return item


def zero(field):
    """A field the graph keeps at 0 (no cases)."""
    return {'field': field, 'cases': [], 'default': hexv(0)}


# ---------------------------------------------------------------------------------------------
# XMC1000

def xmc1100():
    nodes = [
        fixed('dco1', 'DCO1 64 MHz', 0, 1, 64 * MHZ, tooltip='Internal oscillator DCO1 (64 MHz), the only MCLK source.'),
        {'id': 'dclk2', 'label': '/2', 'kind': 'divider', 'x': 1, 'y': 1,
         'options': [{'id': '2', 'label': '/2', 'from': 'dco1', 'div': 2}]},
        span('mclk', 'MCLK (IDIV)', 2, 1, 'dclk2', 'SCU_CLKCR.IDIV', 8, 1, 255, 'div', max=32 * MHZ, consumer=True,
             tooltip='CPU and bus clock: 32 MHz / IDIV (the fractional FDIV is kept at 0).'),
        {'id': 'pclk', 'label': 'PCLK', 'kind': 'multiplier', 'x': 3, 'y': 1, 'max': 64 * MHZ, 'consumer': True,
         'tooltip': 'Peripheral clock of CCU4/CCU8/POSIF/MATH/BCCU: MCLK or 2 x MCLK.',
         'options': [{'id': '1', 'label': 'x1', 'from': 'mclk', 'set': {'SCU_CLKCR.PCLKSEL': hexv(0)}},
                     {'id': '2', 'label': 'x2', 'from': 'mclk', 'mul': 2, 'set': {'SCU_CLKCR.PCLKSEL': hexv(1 << 16)}}]},
    ]
    return finish(graph('xmc1100', 'XMC1100/1200/1300 clock tree', 'XMC1100/XMC1200/XMC1300 reference manuals, SCU "Clock Control"',
                        ['^XMC1[1-3]'], 'mclk', {}, nodes, derive=[zero('SCU_CLKCR.FDIV')]))


def xmc1400():
    nodes = [
        no_enable(external('xtal', 'XTAL1 input', 0, 0, None, tooltip='Crystal (4-20 MHz) or external clock (4-48 MHz) on XTAL1.')),
        {'id': 'oschp', 'label': 'OSC_HP', 'kind': 'mux', 'x': 1, 'y': 0,
         'options': [{'id': 'crystal', 'label': 'Crystal', 'from': 'xtal', 'set': {'SCU_ANAOSCHPCTRL.MODE': hexv(0)}},
                     {'id': 'external', 'label': 'External clock', 'from': 'xtal', 'set': {'SCU_ANAOSCHPCTRL.MODE': hexv(1 << 4)}},
                     {'id': 'off', 'label': 'Disabled', 'mul': 0, 'set': {'SCU_ANAOSCHPCTRL.MODE': hexv(3 << 4)}}]},
        fixed('dco1', 'DCO1 48 MHz', 0, 2, 48 * MHZ),
        {'id': 'dclk', 'label': 'DCLK (x2)', 'kind': 'mux', 'x': 2, 'y': 1, 'max': 96 * MHZ,
         'options': [{'id': 'dco1', 'label': 'DCO1 x 2', 'from': 'dco1', 'mul': 2, 'set': {'SCU_CLKCR1.DCLKSEL': hexv(0)}},
                     {'id': 'osc', 'label': 'OSC_HP x 2', 'from': 'oschp', 'mul': 2, 'set': {'SCU_CLKCR1.DCLKSEL': hexv(1 << 9)}}]},
        {'id': 'dclk2', 'label': '/2', 'kind': 'divider', 'x': 3, 'y': 1,
         'options': [{'id': '2', 'label': '/2', 'from': 'dclk', 'div': 2}]},
        span('mclk', 'MCLK (IDIV)', 4, 1, 'dclk2', 'SCU_CLKCR.IDIV', 8, 1, 255, 'div', max=48 * MHZ, consumer=True,
             tooltip='CPU and bus clock: DCLK / 2 / IDIV (the fractional FDIV is kept at 0).'),
        {'id': 'pclk', 'label': 'PCLK', 'kind': 'multiplier', 'x': 5, 'y': 1, 'max': 96 * MHZ, 'consumer': True,
         'tooltip': 'Peripheral clock of CCU4/CCU8/POSIF/MATH/BCCU: MCLK or 2 x MCLK.',
         'options': [{'id': '1', 'label': 'x1', 'from': 'mclk', 'set': {'SCU_CLKCR.PCLKSEL': hexv(0)}},
                     {'id': '2', 'label': 'x2', 'from': 'mclk', 'mul': 2, 'set': {'SCU_CLKCR.PCLKSEL': hexv(1 << 16)}}]},
    ]
    derive = [
        zero('SCU_CLKCR.FDIV'), zero('SCU_CLKCR1.FDIV_HI'),
        {'field': 'SCU_ANAOSCHPCTRL.GAINSEL', 'cases': [{'when': 'in.xtal <= 10000000', 'value': hexv(0)}], 'default': hexv(2 << 2)},
        {'field': 'SCU_ANAOSCHPCTRL.HYSCTRL', 'cases': [{'when': 'in.xtal > 20000000', 'value': hexv(0)}], 'default': hexv(1 << 6)},
    ]
    constraints = [
        rule("sel.dclk != 'osc' || sel.oschp != 'off'", 'DCLK from OSC_HP needs OSC_HP enabled (crystal or external clock).'),
        rule("sel.dclk != 'osc' || sel.oschp != 'crystal' || in.xtal <= 20000000", 'An OSC_HP crystal must be 4-20 MHz (an external clock up to 48 MHz).'),
    ]
    return finish(graph('xmc1400', 'XMC1400 clock tree', 'XMC1400 reference manual, SCU "Clock Control"', ['^XMC14'], 'mclk',
                        {'xtal': {'label': 'OSC_HP frequency', 'default': 16 * MHZ, 'min': 4 * MHZ, 'max': 48 * MHZ}}, nodes,
                        settings=['SCU_CLKCR.RTCCLKSEL', 'SCU_CLKCR1.ADCCLKSEL'], derive=derive, constraints=constraints))


def no_enable(node):
    del node['enable']
    return node


# ---------------------------------------------------------------------------------------------
# XMC4000

def xmc4():
    fmax = 144 * MHZ
    nodes = [
        external('osc', 'OSC_HP', 0, 0, en('SCU_OSCHPCTRL.MODE', 0, 3 << 4), tooltip='Crystal or external clock on XTAL1 (4-25 MHz crystal).'),
        fixed('ofi', 'fOFI 24 MHz', 0, 2, 24 * MHZ, tooltip='Internal backup clock (calibrated, see fOFI calibration).'),
        mux('pllin', 'PLL input', 1, 1, 'SCU_PLLCON2.PINSEL', [('osc', 'OSC_HP', 'osc', 0), ('ofi', 'fOFI', 'ofi', 0x101)]),
        span('pdiv', '/P', 2, 1, 'pllin', 'SCU_PLLCON1.PDIV', 24, 1, 16, 'div', offset=-1, min=4 * MHZ, max=16 * MHZ,
             tooltip='VCO input: 4-16 MHz.'),
        span('vco', 'VCO xN', 3, 1, 'pdiv', 'SCU_PLLCON1.NDIV', 8, 1, 128, 'mul', offset=-1, min=260 * MHZ, max=520 * MHZ,
             tooltip='VCO: 260-520 MHz.'),
        span('pll', 'fPLL /K2', 4, 1, 'vco', 'SCU_PLLCON1.K2DIV', 16, 1, 128, 'div', offset=-1),
        mux('syssel', 'fSYS source', 5, 2, 'SCU_SYSCLKCR.SYSSEL', [('pll', 'Main PLL', 'pll', 1 << 16), ('ofi', 'fOFI', 'ofi', 0)]),
        span('sys', 'fSYS (SYSDIV)', 6, 2, 'syssel', 'SCU_SYSCLKCR.SYSDIV', 0, 1, 256, 'div', offset=-1, max=fmax, consumer=True),
        factors('cpu', 'fCPU', 7, 1, 'sys', 'SCU_CPUCLKCR.CPUDIV', 0, [(1, 0), (2, 1)], max=fmax, consumer=True),
        factors('periph', 'fPERIPH', 8, 1, 'cpu', 'SCU_PBCLKCR.PBDIV', 0, [(1, 0), (2, 1)], consumer=True),
        factors('ccu', 'fCCU', 7, 3, 'sys', 'SCU_CCUCLKCR.CCUDIV', 0, [(1, 0), (2, 1)], max=fmax, consumer=True),
    ]
    # OSC watchdog divider while OSC_HP feeds the PLL: fOSC / 2.5 MHz (OSCVAL = divider - 1), as
    # system_XMC4xxx.c. Unused, the definition default (/5) stays.
    derive = [{'field': 'SCU_OSCHPCTRL.OSCVAL',
               'cases': [{'when': f"sel.pllin == 'osc' && in.osc < {(d + 1) * 2500000}", 'value': hexv((d - 1) << 16)}
                         for d in range(2, 16)] + [{'when': "sel.pllin == 'osc'", 'value': hexv(15 << 16)}],
               'default': hexv(4 << 16)},
              # Flash wait states: fCPU x 22 ns, rounded up (FCON.WSPFLASH).
              {'field': 'FLASH0_FCON.WSPFLASH',
               'cases': [{'when': f'f.cpu <= {round(n * 1e9 / 22)}', 'value': hexv(n)} for n in range(1, 6)],
               'default': hexv(6)}]
    variants = [{'devices': ['^XMC4[12]'], 'limits': {'sys': {'max': 80 * MHZ}, 'cpu': {'max': 80 * MHZ}, 'ccu': {'max': 80 * MHZ}}},
                {'devices': ['^XMC4[45]'], 'limits': {'sys': {'max': 120 * MHZ}, 'cpu': {'max': 120 * MHZ}, 'ccu': {'max': 120 * MHZ}}}]
    return finish(graph('xmc4', 'XMC4000 clock tree', 'XMC4000 reference manuals, SCU "Clock Generation Unit"; XMC4000 data sheets',
                        ['^XMC4'], 'cpu', {'osc': {'label': 'OSC_HP frequency', 'default': 12 * MHZ, 'min': 4 * MHZ, 'max': 40 * MHZ}},
                        nodes, settings=['SCU_PLLCON0.OFICAL', '?SCU_OSCHPCTRL.GAINSEL'], derive=derive, variants=variants))


# ---------------------------------------------------------------------------------------------
# PSOC 4

# 24 MHz grades (CY_HF_CLK_MAX_FREQ = 24 MHz): PSOC 4000S/4100S..., 4700S, part of the 4100S Max HV.
PSOC4_24MHZ = ['^CY8C402', '^CY8C412', '^CY8C472', '^CY8C4149AZI-S5[78]', '^CY8C4149AZI-S568']


def psoc4():
    imo = [(24 + 4 * code, code) for code in range(7)]
    nodes = [
        {'id': 'imo', 'label': 'IMO', 'kind': 'source', 'x': 0, 'y': 0,
         'tooltip': 'Internal main oscillator, factory trimmed (24-48 MHz in 4 MHz steps; 24 MHz only on the 24 MHz grades).',
         'options': [{'id': str(mhz), 'label': f'{mhz} MHz', 'mul': mhz * MHZ, 'set': {'CLK_IMO_SELECT.FREQ': hexv(code)}}
                     for mhz, code in imo]},
        external('extclk', 'EXTCLK', 0, 1, None, tooltip='External clock on the EXTCLK pin (P0.6).'),
    ]
    del nodes[1]['enable']
    hfsel = [('imo', 'IMO', 'imo', 0), ('ext', 'EXTCLK', 'extclk', 1), ('exco', 'EXCO (ECO / PLL)', 'exco', 2)]
    # EXCO (ECO crystal + PLL): only on the parts whose definition has the EXCO registers; on the
    # others these nodes are absent (their fields are missing) and HFCLK_SEL offers no EXCO.
    nodes += [
        {'id': 'eco', 'label': 'ECO crystal', 'kind': 'source', 'x': 0, 'y': 3,
         'tooltip': 'External crystal oscillator (4-33 MHz). Load capacitance, ESR and drive level are set below.',
         'options': [{'id': str(mhz), 'label': f'{mhz} MHz', 'mul': mhz * MHZ, 'set': {'EXCO_ECO_CONFIG.FREQ': hexv(mhz)}}
                     for mhz in range(4, 34)]},
        # REF_SEL: IMO = 1 on EXCO v1 (bit 1), 2 on EXCO v2 (bits 2:1); each part offers one of them.
        {'id': 'pllref', 'label': 'PLL reference', 'kind': 'mux', 'x': 1, 'y': 3,
         'options': [{'id': 'eco', 'label': 'ECO', 'from': 'eco', 'set': {'EXCO_CLK_SELECT.REF_SEL': hexv(0)}},
                     {'id': 'imo', 'label': 'IMO', 'from': 'imo', 'set': {'EXCO_CLK_SELECT.REF_SEL': hexv(2)}},
                     {'id': 'imo2', 'label': 'IMO', 'from': 'imo', 'set': {'EXCO_CLK_SELECT.REF_SEL': hexv(4)}}]},
        span('pllq', 'PLL /Q', 2, 3, 'pllref', 'EXCO_PLL_CONFIG.REFERENCE_DIV', 8, 1, 64, 'div', offset=-1,
             min=1 * MHZ, max=3 * MHZ, tooltip='PLL phase detector input: 1-3 MHz.'),
        span('pllvco', 'PLL xP', 3, 3, 'pllq', 'EXCO_PLL_CONFIG.FEEDBACK_DIV', 0, 8, 255, 'mul',
             min=22500000, max=104 * MHZ, tooltip='PLL VCO: 22.5-104 MHz.'),
        factors('pllout', 'PLL output', 4, 3, 'pllvco', 'EXCO_PLL_CONFIG.OUTPUT_DIV', 14, BINARY),
        {'id': 'exco', 'label': 'EXCO', 'kind': 'mux', 'x': 5, 'y': 2,
         'options': [{'id': 'pll', 'label': 'PLL', 'from': 'pllout', 'set': {'EXCO_PLL_CONFIG.ENABLE': hexv(1 << 31)}},
                     {'id': 'eco', 'label': 'ECO', 'from': 'eco', 'set': {'EXCO_PLL_CONFIG.ENABLE': hexv(0)}}]},
    ]
    settings = ['?EXCO_ECO_CONFIG.CLOAD', '?EXCO_ECO_CONFIG.ESR', '?EXCO_ECO_CONFIG.DRIVE']
    nodes += [
        mux('hfsel', 'HFCLK source', 6, 1, 'CLK_SELECT.HFCLK_SEL', hfsel),
        factors('hfclk', 'HFCLK', 7, 1, 'hfsel', 'CLK_SELECT.HFCLK_DIV', 2, BINARY, max=48 * MHZ, consumer=True),
        factors('sysclk', 'SYSCLK (CPU)', 8, 1, 'hfclk', 'CLK_SELECT.SYSCLK_DIV', 6, BINARY, max=48 * MHZ, consumer=True),
    ]
    variants = [{'devices': PSOC4_24MHZ, 'limits': {'hfclk': {'max': 24 * MHZ}, 'sysclk': {'max': 24 * MHZ}}}]
    return finish(graph('psoc4', 'PSOC 4 clock tree', 'PSOC 4 architecture/registers technical reference manuals (SRSS, EXCO); mtb-pdl-cat2 cy_sysclk',
                        ['^CY8C4'], 'sysclk', {'extclk': {'label': 'EXTCLK frequency', 'default': 24 * MHZ, 'min': 1 * MHZ, 'max': 48 * MHZ}},
                        nodes, settings=settings, variants=variants))


# ---------------------------------------------------------------------------------------------
# FM0+ / FM3 / FM4

def fm(graph_id, title, source, devices, cr_mhz, fm3=False, apbc2=True, variants=()):
    """FM clock generation unit. FM3 definitions name the registers in upper case and carry the
    oscillator enable bits (MOSCE/SOSCE/PLLE) and the sub clocks; FM0+/FM4 in lower case."""
    r = (lambda name: name.upper()) if fm3 else (lambda name: name.lower())
    nodes = [
        fixed('hcr', f'High-speed CR {cr_mhz} MHz', 0, 2, cr_mhz * MHZ,
              tooltip='Internal high-speed CR oscillator, factory trimmed by the startup code.'),
        external('mosc', 'Main oscillator', 0, 0, en(r('SCM_CTL') + '.MOSCE', 1 << 1) if fm3 else None,
                 tooltip='Main crystal oscillator (4-48 MHz). Its frequency is not stored in the definition.'),
    ]
    if not fm3:
        del nodes[1]['enable']
    nodes += [
        mux('pllin', 'PLL input', 1, 1, r('PSW_TMR') + '.' + r('PINC'), [('mosc', 'Main oscillator', 'mosc', 0), ('hcr', 'High-speed CR', 'hcr', 1 << 4)]),
        span('pllk', 'PLL /K', 2, 1, 'pllin', r('PLL_CTL1') + '.' + r('PLLK'), 4, 1, 16, 'div', offset=-1,
             min=4 * MHZ, max=16 * MHZ, tooltip='PLL input after K: 4-16 MHz.'),
        span('pll', 'CLKPLL xN', 3, 1, 'pllk', r('PLL_CTL2') + '.' + r('PLLN'), 0, 1, 64, 'mul', offset=-1,
             **({'enable': en(r('SCM_CTL') + '.PLLE', 1 << 4)} if fm3 else {})),
        # PLL macro (VCO) = CLKPLL x M; only checked by the variant constraints.
        span('vco', 'PLL macro xM', 4, 0, 'pll', r('PLL_CTL1') + '.' + r('PLLM'), 0, 1, 16, 'mul', offset=-1, optional=True,
             tooltip='PLL macro oscillation clock = CLKPLL x M (feedback divider M).'),
    ]
    master = [('hcr', 'High-speed CR', 'hcr', 0), ('mosc', 'Main oscillator', 'mosc', 1 << 5), ('pll', 'Main PLL', 'pll', 2 << 5)]
    settings = [r('CSW_TMR') + '.' + r('MOWT'), r('PSW_TMR') + '.' + r('POWT')]
    if fm3:
        nodes += [fixed('lcr', 'Low-speed CR 100 kHz', 0, 3, 100000),
                  fixed('sosc', 'Sub oscillator 32.768 kHz', 0, 4, 32768, enable=en('SCM_CTL.SOSCE', 1 << 3))]
        master += [('lcr', 'Low-speed CR', 'lcr', 4 << 5), ('sosc', 'Sub oscillator', 'sosc', 5 << 5)]
        settings += ['CSW_TMR.SOWT', 'SWC_PSR.SWDS', 'TTC_PSR.TTC', 'APBC1_PSR.APBC1EN', 'APBC2_PSR.APBC2EN']
    nodes += [
        mux('master', 'Master clock (RCS)', 5, 2, r('SCM_CTL') + '.' + r('RCS'), master),
        factors('hclk', 'HCLK (BSR)', 6, 2, 'master', r('BSC_PSR') + '.' + r('BSR'), 0, FM_BSR, consumer=True),
        factors('pclk0', 'PCLK0 (APB0)', 7, 1, 'hclk', r('APBC0_PSR') + '.' + r('APBC0'), 0, BINARY, consumer=True),
        factors('pclk1', 'PCLK1 (APB1)', 7, 2, 'hclk', r('APBC1_PSR') + '.' + r('APBC1'), 0, BINARY, consumer=True),
    ]
    if apbc2:
        nodes.append(factors('pclk2', 'PCLK2 (APB2)', 7, 3, 'hclk', r('APBC2_PSR') + '.' + r('APBC2'), 0, BINARY, consumer=True))
    constraints = [rule("sel.master != 'pll' || sel.pllin != 'mosc' || in.mosc >= 4000000", 'The PLL needs a main oscillator of 4 MHz or more.')]
    return finish(graph(graph_id, title, source, devices, 'hclk',
                        {'mosc': {'label': 'Main oscillator frequency', 'default': 4 * MHZ, 'min': 4 * MHZ, 'max': 48 * MHZ}},
                        nodes, settings=settings, constraints=constraints, variants=variants))


def fm_limits(devices, hclk, vco, cr_margin, pclk=None, pclk1=None, pclk2=None):
    """Variant: HCLK/CLKPLL/PCLK maxima, PLL macro range and the trimmed-CR headroom."""
    low, high = vco
    limits = {'hclk': {'max': hclk}, 'pll': {'max': hclk}}
    for node, value in (('pclk0', pclk), ('pclk1', pclk1), ('pclk2', pclk2)):
        if value:
            limits[node] = {'max': value}
    return {'devices': devices, 'limits': limits, 'constraints': [
        rule(f"sel.master != 'pll' || (f.vco >= {low} && f.vco <= {high})",
             f'PLL macro clock (CLKPLL x M) must be {low / MHZ:g}-{high / MHZ:g} MHz.'),
        rule(f"sel.master != 'pll' || sel.pllin != 'hcr' || f.pll * {cr_margin} <= {hclk}",
             f'From the high-speed CR, CLKPLL must stay {round((cr_margin - 1) * 100)} % below {hclk / MHZ:g} MHz: '
             'the trimmed CR can be that much faster than nominal.')]}


FM3_DEVICES = ['^CY9AF', '^CY9BF[1-5][12]', '^CY9BF6', '^CY9BFD']
FM3_VARIANTS = [
    # MB9A1x0/3x0/4x0/Ax0/Bx0 low power series (40 MHz)
    fm_limits(['^CY9AF1[245]', '^CY9AF34', '^CY9AF4', '^CY9AF[AB]'], 40 * MHZ, (75 * MHZ, 150 * MHZ), 1.05),
    # MB9A110A/310A (40 MHz) and MB9A110K/310K (42 MHz)
    fm_limits(['^CY9AF[13]1[12][LMN]', '^CY9AF[13]1[3-6]'], 40 * MHZ, (200 * MHZ, 300 * MHZ), 1.05),
    fm_limits(['^CY9AF[13]1[12]K'], 42 * MHZ, (200 * MHZ, 300 * MHZ), 1.05),
    # MB9B110/210/310/410/510/610/D10 high performance series (144 MHz)
    fm_limits(['^CY9BF[1-5]1', '^CY9BF2', '^CY9BF6', '^CY9BFD'], 144 * MHZ, (200 * MHZ, 300 * MHZ), 1.05),
    # MB9B120M/320M/520M (72 MHz), MB9B120T/320T/420T/520T (60 MHz)
    fm_limits(['^CY9BF[1-5]2[1-4]'], 72 * MHZ, (75 * MHZ, 150 * MHZ), 1.05),
    fm_limits(['^CY9BF[1-5]2[89]'], 60 * MHZ, (75 * MHZ, 150 * MHZ), 1.05),
]

FM4_VARIANTS = [
    fm_limits(['^S6E2C'], 200 * MHZ, (190 * MHZ, 400 * MHZ), 1.03, 100 * MHZ, 200 * MHZ, 100 * MHZ),
    fm_limits(['^S6E2G'], 180 * MHZ, (190 * MHZ, 400 * MHZ), 1.03, 90 * MHZ, 180 * MHZ, 90 * MHZ),
    fm_limits(['^S6E2D'], 160 * MHZ, (190 * MHZ, 400 * MHZ), 1.03, 80 * MHZ, 160 * MHZ, 80 * MHZ),
    fm_limits(['^S6E2H', '^CY9BF'], 160 * MHZ, (190 * MHZ, 320 * MHZ), 1.03, 80 * MHZ, 160 * MHZ, 80 * MHZ),
]

GRAPHS = [
    xmc1100(),
    xmc1400(),
    xmc4(),
    psoc4(),
    fm('fm0p_s6e1a', 'FM0+ S6E1A clock tree', 'FM0+ peripheral manual (clock); S6E1A1 data sheet DS710-00001', ['^S6E1A'], 4,
       apbc2=False, variants=[fm_limits(['^S6E1A'], 41200000, (72 * MHZ, 150 * MHZ), 1.03, 41200000, 41200000)]),
    fm('fm0p_s6e1c', 'FM0+ S6E1C clock tree', 'FM0+ peripheral manual (clock); S6E1C1/C3 data sheet 002-02769', ['^S6E1C'], 8,
       apbc2=False, variants=[fm_limits(['^S6E1C'], 40800000, (75 * MHZ, 150 * MHZ), 1.02, 40800000, 40800000)]),
    fm('fm3', 'FM3 clock tree', 'FM3 peripheral manual (clock); MB9A/MB9B data sheets', FM3_DEVICES, 4, fm3=True, variants=FM3_VARIANTS),
    fm('fm4', 'FM4 clock tree', 'FM4 peripheral manual (clock); S6E2C/G/D/H and MB9B160-560 data sheets', ['^S6E2', '^CY9BF[1-5]6'], 4,
       variants=FM4_VARIANTS),
]


def main():
    failed = False
    for item in GRAPHS:
        problems = check_graph(item)
        for problem in problems:
            print(f'{item["id"]}: {problem}')
        failed = failed or bool(problems)
        print(f'wrote {write_graph(item, f"infineon/{item["id"]}.json").relative_to(REPO_ROOT)}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
