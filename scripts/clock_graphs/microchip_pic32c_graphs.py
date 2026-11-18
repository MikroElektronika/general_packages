"""Write the Microchip PIC32C (ARM) clock graphs (clock_graphs/microchip_pic32c/*.json).

Hand-written from the PIC32C datasheets' clock chapters (MPLAB Harmony csp clock plibs were used
only to cross-check defaults and limits). Only families whose NECTO definitions carry the clock
registers and whose core system library (system/src/pic32/<lib>/init_clock.c) applies them are
described: PIC32CX SG41/SG60/SG61 and PIC32CZ CA70/MC70 (the SAM D5x/E5x and SAM E70 clock
systems), PIC32CX MTC/MTG/MTSH (core 0), PIC32CX SG12, PIC32CX BZ2/BZ3/BZ6 and PIC32CZ
CA80/CA90/CA91. Register values are absolute bit values (see clock_graphs/README.md).

Run:  python scripts/clock_graphs/microchip_pic32c_graphs.py
"""

import copy

from graphlib import REPO_ROOT, check_graph, hexv, write_graph
from stm32_graphs import MHZ, en, external, factors, fixed, mux, rule, span
from microchip_sam_graphs import PRES, SAM_D5X, SAM_X7, gclk_div, pow2, sam


def derived(base, graph_id, title, source, devices):
    """A PIC32C family that carries the clock system (and NECTO register set) of a SAM family."""
    result = copy.deepcopy(base)
    result.update({'id': graph_id, 'title': title, 'source': source, 'devices': list(devices)})
    return result


# ---------------------------------------------------------------------------------------------
# PIC32CX SG41/SG60/SG61 (init_clock.c as SAM D5x/E5x): DFLL48M / XOSC0/1 / XOSC32K -> GCLK1 ->
# DPLL0/DPLL1 -> GCLK0 -> CPUDIV, 120 MHz. Default: DFLL48M / 48 = 1 MHz -> DPLL0 x120 = 120 MHz.
PIC32CX_SG = derived(
    SAM_D5X, 'pic32cx_sg41_sg6x', 'PIC32CX SG41/SG60/SG61 clock tree',
    'PIC32CX SG41/SG60/SG61 datasheet DS60001715, OSCCTRL/GCLK/MCLK', ['^PIC32CX1025SG(41|60|61)'])

# ---------------------------------------------------------------------------------------------
# PIC32CZ CA70/MC70 (init_clock.c as SAM E70): main RC / crystal -> PLLA (or UPLL) -> PRES (HCLK,
# 300 MHz) -> MDIV (MCK, 150 MHz). Default: main RC 12 MHz -> PLLA x25 = 300 MHz, MCK 150 MHz.
PIC32CZ_CA70 = derived(
    SAM_X7, 'pic32cz_ca70_mc70', 'PIC32CZ CA70/MC70 clock tree',
    'PIC32CZ CA70/MC70 datasheet DS60001786, PMC', ['^PIC32CZ2051(CA|MC)70'])


# ---------------------------------------------------------------------------------------------
# PIC32CX MT (MTC/MTG/MTSH) core 0 clock graph fragment.
#
# Hand-written from the PIC32CXMTSH/MTC/MTG datasheet (DS60001765) PMC, SUPC and SEFC chapters; the
# PLL VCO ranges and the flash access time are cross-checked against the MPLAB Harmony
# clk_pic32cx_mt / sefc plibs. Serves the core 0 parts (system/src/pic32/pic32cx_mt*/init_clock.c);
# the S1 parts are core 1 images whose clock is set by the core 0 application, they carry no
# clock registers.
#
# TD_SLCK (32 kHz RC or 32.768 kHz crystal) or MAINCK (12 MHz main RC or 12-48 MHz crystal) -> PLLA
# = reference x (MUL + 1) (VCO 380-600 MHz) -> PLLACK0 / PLLACK1 = VCO / (DIVPMC + 1);
# PLLACK0 or MAINCK -> PLLB = reference x (MUL + 1) (VCO 300-600 MHz) -> PLLBCK = VCO / (DIVPMC0 + 1);
# MD_SLCK | MAINCK | PLLACK1 | PLLBCK -> PRES -> CPU_CLK0 = MCK0 (at most 200 MHz) -> MCK0DIV / MCK0DIV2.
# The fractional PLL parts (PMC_PLL_CTRL2.FRACR) are not used: init_clock.c writes them 0.
# Register values are absolute bit values (see clock_graphs/README.md).
# Flash access time 32 ns: FWS >= f x 32 ns (Harmony sefc convention), i.e. FWS = k up to k x 31.25 MHz.
FWS_CASES = [{'when': f'f.cpu <= {k * 31250000}', 'value': hexv(k << 8)} for k in range(1, 7)]

PIC32CX_MT = sam(
    'pic32cx_mt', 'PIC32CX MTC/MTG/MTSH clock tree', 'PIC32CXMTSH/MTC/MTG datasheet DS60001765, PMC / SUPC / SEFC',
    ['^PIC32CX(1025|2051|5112)MT(C|G|SH)(64|128)$'], 'cpu',
    {'main_xtal': {'label': 'Main crystal frequency', 'default': 12 * MHZ, 'min': 12 * MHZ, 'max': 48 * MHZ}},
    [
        fixed('main_rc', 'Main RC 12 MHz', 0, 0, 12 * MHZ, en('CKGR_MOR.MOSCRCEN', 1 << 3, auto='on')),
        external('main_xtal', 'Main crystal', 0, 2, en('CKGR_MOR.MOSCXTEN', 1),
                 tooltip='12-48 MHz crystal (CKGR_MOR.MOSCXTEN) or external clock on XIN (MOSCXTBY).'),
        mux('mainck', 'MAINCK', 1, 1, 'CKGR_MOR.MOSCSEL', [('rc', 'Main RC', 'main_rc', 0), ('xtal', 'Main crystal', 'main_xtal', 1 << 24)]),
        {'id': 'td_slck', 'label': 'Timing domain slow clock (TD_SLCK)', 'kind': 'source', 'x': 0, 'y': 4,
         'tooltip': 'SUPC_CR.TDXTALSEL switches TD_SLCK to the 32.768 kHz crystal (only a VDDBU power-on switches it back).',
         'options': [{'id': 'rc', 'label': 'RC 32 kHz', 'mul': 32000, 'set': {'SUPC_CR.TDXTALSEL': hexv(0)}},
                     {'id': 'xtal', 'label': 'Crystal 32.768 kHz', 'mul': 32768, 'set': {'SUPC_CR.TDXTALSEL': hexv(1 << 3)}}]},
        fixed('md_slck', 'MD_SLCK (RC 32 kHz)', 0, 6, 32000, tooltip='Monitoring domain slow clock: always the 32 kHz RC.'),
        mux('pllasrc', 'PLLA reference', 1, 4, 'PMC_PLLA_CTRL0.PLLMS',
            [('td_slck', 'TD_SLCK', 'td_slck', 0), ('mainck', 'MAINCK', 'mainck', 1 << 27)]),
        span('plla', 'PLLA xMUL', 2, 4, 'pllasrc', 'PMC_PLLA_CTRL1.MUL', 0, 1, 32768, 'mul', offset=-1,
             min=380 * MHZ, max=600 * MHZ, enable=en('PMC_PLLA_CTRL0.ENPLL', 1 << 28),
             tooltip='PLLA VCO = reference x (MUL + 1): 380-600 MHz.'),
        span('pllack1', 'PLLACK1 /DIVPMC1', 3, 4, 'plla', 'PMC_PLLA_CTRL0.DIVPMC1', 12, 1, 256, 'div', offset=-1,
             enable=en('PMC_PLLA_CTRL0.ENPLLO1', 1 << 30), tooltip='PLLA output 1: processor clock source.'),
        span('pllack0', 'PLLACK0 /DIVPMC0', 3, 5, 'plla', 'PMC_PLLA_CTRL0.DIVPMC0', 0, 1, 256, 'div', offset=-1,
             enable=en('PMC_PLLA_CTRL0.ENPLLO0', 1 << 29), tooltip='PLLA output 0: PLLB/PLLC reference.'),
        mux('pllbsrc', 'PLLB reference', 2, 2, 'PMC_PLLB_CTRL0.PLLMS',
            [('pllack0', 'PLLACK0', 'pllack0', 0), ('mainck', 'MAINCK', 'mainck', 1 << 27)]),
        span('pllb', 'PLLB xMUL', 3, 2, 'pllbsrc', 'PMC_PLLB_CTRL1.MUL', 0, 1, 256, 'mul', offset=-1,
             min=300 * MHZ, max=600 * MHZ, enable=en('PMC_PLLB_CTRL0.ENPLL', 1 << 28),
             tooltip='PLLB VCO = reference x (MUL + 1): 300-600 MHz.'),
        span('pllbck', 'PLLBCK /DIVPMC0', 4, 2, 'pllb', 'PMC_PLLB_CTRL0.DIVPMC0', 0, 1, 256, 'div', offset=-1,
             enable=en('PMC_PLLB_CTRL0.ENPLLO0', 1 << 29), tooltip='PLLB output.'),
        mux('css', 'CPU_CLK0 / MCK0 source', 5, 1, 'PMC_CPU_CKR.CSS',
            [('md_slck', 'MD_SLCK', 'md_slck', 0), ('mainck', 'MAINCK', 'mainck', 1),
             ('pllack1', 'PLLACK1', 'pllack1', 2), ('pllbck', 'PLLBCK', 'pllbck', 3)]),
        factors('cpu', 'CPU_CLK0 / MCK0 (PRES)', 6, 1, 'css', 'PMC_CPU_CKR.PRES', 4, PRES, max=200 * MHZ, consumer=True,
                tooltip='Core 0 processor clock and master clock MCK0: at most 200 MHz.'),
        factors('mck0div', 'MCK0DIV', 7, 1, 'cpu', 'PMC_CPU_CKR.RATIO_MCK0DIV', 24, [(1, 0), (2, 1)], consumer=True,
                tooltip='Peripheral bus clock (FLEXCOM, TC, ...); Microchip configures MCK0 / 2 at 200 MHz.'),
        factors('mck0div2', 'MCK0DIV2', 7, 2, 'cpu', 'PMC_CPU_CKR.RATIO_MCK0DIV2', 26, [(1, 0), (2, 1)], consumer=True),
    ],
    settings=['CKGR_MOR.MOSCXTBY', 'CKGR_MOR.CFDEN', 'SUPC_MR.OSCBYPASS', 'SEFC_EEFC_FMR.CLOE'],
    derive=[
        {'field': 'SEFC_EEFC_FMR.FWS', 'cases': FWS_CASES, 'default': hexv(7 << 8)},
        # Flash high-speed patch on from 160 MHz (SFR_FLASH = 0), bypassed below.
        {'field': 'SFR_FLASH.PATCH_BYPASS', 'cases': [{'when': 'f.cpu >= 160000000', 'value': hexv(0)}], 'default': hexv(1)},
    ])


# ---------------------------------------------------------------------------------------------
# PIC32CX0525SG12084/12144 secure embedded controllers (pic32cx_sg1 init_clock.c): the 32 kHz clock
# domain (always-on silicon oscillator, 32.768 kHz crystal or the 32KHZ_IN pin, VBAT_CLK32_EN) is
# the reference of the 48 MHz PLL; the processor clock is PLL / PROC_DIV (1, 3, 4, 16 or 48, reset
# /4 = 12 MHz) and SLOW_CLK is PLL / n (0 = off, reset 480 = 100 kHz). Code runs from SRAM, so there
# are no flash wait states. Default: silicon oscillator -> PLL 48 MHz -> /1 = 48 MHz.

PIC32CX_SG1 = sam(
    'pic32cx_sg1', 'PIC32CX SG12 clock tree', 'PIC32CX0525SG12 datasheet, PCR and VBAT-powered control chapters',
    ['^PIC32CX0525SG12'], 'cpu', {},
    [
        fixed('silosc', 'Silicon oscillator 32 kHz', 0, 0, 32768, tooltip='Always-on internal 32 kHz silicon oscillator.'),
        fixed('xtal32', 'Crystal 32.768 kHz', 0, 1, 32768,
              tooltip='32.768 kHz crystal on XTAL1/XTAL2, or a single-ended clock on XTAL2 (VBAT_CLK32_EN.XOSEL).'),
        fixed('pin32k', '32KHZ_IN pin', 0, 2, 32768, tooltip='External 32.768 kHz clock on the 32KHZ_IN pin.'),
        mux('int32k', 'Always-on 32 kHz source', 1, 0, 'VBAT_CLK32_EN.C32KHZ_SRC',
            [('silosc', 'Silicon oscillator', 'silosc', 0), ('xtal', 'Crystal oscillator', 'xtal32', 1 << 2)],
            tooltip='The crystal is used only once a clock is detected on the crystal pins.'),
        mux('clk32k', '32 kHz clock domain', 2, 1, 'VBAT_CLK32_EN.EXT_32K',
            [('internal', 'Always-on source', 'int32k', 0), ('pin', '32KHZ_IN pin', 'pin32k', 1 << 1)],
            tooltip='Without a clock on 32KHZ_IN the always-on source is selected automatically.'),
        {'id': 'pll', 'label': 'PLL 48 MHz', 'kind': 'multiplier', 'x': 3, 'y': 1,
         'tooltip': '48 MHz main clock, locked to the 32 kHz clock domain.',
         'options': [{'id': 'on', 'label': 'PLL 48 MHz', 'from': 'clk32k', 'mul': 46875, 'div': 32}]},
        factors('cpu', 'Processor clock (PROC_DIV)', 4, 1, 'pll', 'PROC_CLK_CTRL.DIV', 0,
                [(1, 1), (3, 3), (4, 4), (16, 16), (48, 48)], max=48 * MHZ, consumer=True,
                tooltip='Processor clock: 48 MHz PLL / 1, 3, 4, 16 or 48.'),
        {'id': 'slow_clk', 'label': 'SLOW_CLK /n', 'kind': 'divider', 'x': 4, 'y': 2, 'consumer': True,
         'tooltip': 'Slow clock for PWM, tachometer and other low-speed blocks: 48 MHz / n (0 = off, 480 = 100 kHz).',
         'options': [{'id': 'off', 'label': 'Off', 'mul': 0, 'set': {'SLOW_CLK_CTRL.DIV': hexv(0)}}] +
                    [{'id': str(n), 'label': f'/{n}', 'from': 'pll', 'div': n, 'set': {'SLOW_CLK_CTRL.DIV': hexv(n)}}
                     for n in range(1, 1024)]},
    ],
    settings=['VBAT_CLK32_EN.XOSEL'])


# ---------------------------------------------------------------------------------------------
# PIC32CX-BZ2 (PIC32CX1012BZ24/25), PIC32CX-BZ3 (PIC32CX5109BZ31) and PIC32CX-BZ6 (PIC32CX2051BZ62)
# wireless MCUs (pic32cx_bz init_clock.c). CRU: SYSCLK = OSCCON.NOSC of FRC 8 MHz / FRCDIV, SPLL1 or
# POSC (16 MHz crystal of the RF subsystem). SPLL1 = RF PLL (SPLL3) / SPLLPOSTDIV1, the RF PLL
# multiplies the 16 MHz crystal (BZ2 x6 = 96 MHz, BZ3 x4 = 64 MHz, BZ6 x8 = 128 MHz) and can not run
# from the FRC; on BZ2 SPLLPOSTDIV1 = 1 divides by 1.5. PBCLKx = SYSCLK / (PBDIV + 1). SPLL2 (ADC
# charge pump, 8-24 MHz) = SPLL_BYP source / SPLLPOSTDIV2. Flash wait states (PCHE CHECON.PFMWS/ADRWS)
# follow SYSCLK. Default: FRC / 1 = 8 MHz (the highest internal-oscillator frequency).

FRCDIV = [(1, 0), (2, 1), (4, 2), (8, 3), (16, 4), (32, 5), (64, 6), (256, 7)]


def bz_nodes(rfpll_mul, sys_max, pbs, bz2):
    if bz2:
        # SPLLPOSTDIV1: 1 = /1.5, n >= 2 = /n.
        spll1 = {'id': 'spll1', 'label': 'SPLL1 /SPLLPOSTDIV1', 'kind': 'divider', 'x': 2, 'y': 2,
                 'tooltip': 'SPLL1 = RF PLL / SPLLPOSTDIV1 (1 = /1.5).',
                 'options': [{'id': '1_5', 'label': '/1.5', 'from': 'rfpll', 'mul': 2, 'div': 3,
                              'set': {'SPLLCON.SPLLPOSTDIV1': hexv(1 << 8)}}] +
                            [{'id': str(n), 'label': f'/{n}', 'from': 'rfpll', 'div': n,
                              'set': {'SPLLCON.SPLLPOSTDIV1': hexv(n << 8)}} for n in range(2, 256)]}
    else:
        spll1 = span('spll1', 'SPLL1 /SPLLPOSTDIV1', 2, 2, 'rfpll', 'SPLLCON.SPLLPOSTDIV1', 8, 1, 255, 'div',
                     tooltip='SPLL1 = RF PLL / SPLLPOSTDIV1.')
    nodes = [
        fixed('frc', 'FRC 8 MHz', 0, 0, 8 * MHZ, tooltip='Internal fast RC oscillator.'),
        factors('frcdiv', 'FRCDIV', 1, 0, 'frc', 'OSCCON.FRCDIV', 24, FRCDIV),
        fixed('posc', 'POSC 16 MHz crystal', 0, 1, 16 * MHZ,
              tooltip='16 MHz crystal of the RF subsystem (required by the RF PLL and the radio).'),
        {'id': 'rfpll', 'label': f'RF PLL (SPLL3) x{rfpll_mul}', 'kind': 'multiplier', 'x': 1, 'y': 2,
         'tooltip': f'RF PLL: 16 MHz crystal x {rfpll_mul} = {16 * rfpll_mul} MHz. It can not run from the FRC.',
         'options': [{'id': 'on', 'label': f'x{rfpll_mul}', 'from': 'posc', 'mul': rfpll_mul}]},
        spll1,
        mux('sysclk', 'SYSCLK (NOSC)', 3, 1, 'OSCCON.NOSC',
            [('frc', 'FRC / FRCDIV', 'frcdiv', 0), ('spll', 'SPLL1', 'spll1', 1 << 8), ('posc', 'POSC', 'posc', 2 << 8)],
            max=sys_max, consumer=True, tooltip=f'System (CPU) clock: at most {sys_max // MHZ} MHz.'),
    ]
    for n in range(1, pbs + 1):
        extra = {'max': 6400000, 'tooltip': 'PBCLK3 (analog peripherals): at most 6.4 MHz.'} if n == 3 else {'max': sys_max}
        nodes.append(span(f'pb{n}', f'PBCLK{n} /PBDIV', 4, n - 1, 'sysclk', f'PB{n}DIV.PBDIV', 0, 1, 128, 'div',
                          offset=-1, consumer=True, **extra))
    nodes += [
        mux('spll2src', 'SPLL2 source (SPLL_BYP)', 2, 4, 'SPLLCON.SPLL_BYP',
            [('spll3', 'RF PLL (SPLL3)', 'rfpll', 0), ('posc', 'POSC', 'posc', 2 << 30), ('frc', 'FRC', 'frc', 3 << 30)]),
        {'id': 'spll2', 'label': 'SPLL2 /SPLLPOSTDIV2', 'kind': 'divider', 'x': 3, 'y': 4, 'consumer': True,
         'tooltip': 'ADC charge pump clock: 8-24 MHz, 0 = off.',
         'options': [{'id': 'off', 'label': 'Off', 'mul': 0, 'set': {'SPLLCON.SPLLPOSTDIV2': hexv(0)}}] +
                    [{'id': str(n), 'label': f'/{n}', 'from': 'spll2src', 'div': n,
                      'set': {'SPLLCON.SPLLPOSTDIV2': hexv(n << 16)}} for n in range(1, 16)]},
    ]
    return nodes


def bz_settings(pbs):
    return ['OSCCON.WAKE2SPD', 'CHECON.PREFEN'] + [f'PB{n}DIV.PBDIVON' for n in range(2, pbs + 1)]


SPLL2_RULE = rule('f.spll2 == 0 || (f.spll2 >= 8000000 && f.spll2 <= 24000000)',
                  'SPLL2 (ADC charge pump clock) must be 8-24 MHz or off.')

PIC32CX_BZ2 = sam(
    'pic32cx_bz2', 'PIC32CX-BZ2 clock tree', 'PIC32CX-BZ2 / WBZ451 family datasheet, CRU and PCHE chapters; MPLAB Harmony csp clk_pic32cx_bz',
    ['^PIC32CX1012BZ2[45]'], 'sysclk', {},
    bz_nodes(6, 64 * MHZ, 3, True),
    settings=bz_settings(3) + ['CHECON.ADRWS'],
    derive=[{'field': 'CHECON.PFMWS', 'cases': [{'when': 'f.sysclk <= 33000000', 'value': hexv(0)}], 'default': hexv(1)}],
    constraints=[SPLL2_RULE])

PIC32CX_BZ3 = sam(
    'pic32cx_bz3', 'PIC32CX-BZ3 clock tree', 'PIC32CX-BZ3 / WBZ351 family datasheet, CRU and PCHE chapters; MPLAB Harmony csp clk_pic32cx_bz',
    ['^PIC32CX5109BZ31'], 'sysclk', {},
    bz_nodes(4, 64 * MHZ, 3, False),
    settings=bz_settings(3) + ['CHECON.ADRWS'],
    derive=[{'field': 'CHECON.PFMWS', 'cases': [{'when': 'f.sysclk <= 32000000', 'value': hexv(1)}], 'default': hexv(2)}],
    constraints=[SPLL2_RULE])

PIC32CX_BZ6 = sam(
    'pic32cx_bz6', 'PIC32CX-BZ6 clock tree', 'PIC32CX-BZ6 family datasheet, CRU and PCHE chapters; MPLAB Harmony csp clk_pic32cx_bz',
    ['^PIC32CX2051BZ6'], 'sysclk', {},
    bz_nodes(8, 128 * MHZ, 5, False),
    settings=bz_settings(5),
    derive=[{'field': 'CHECON.PFMWS', 'cases': [{'when': 'f.sysclk < 51200000', 'value': hexv(0)},
                                                {'when': 'f.sysclk < 76800000', 'value': hexv(1)},
                                                {'when': 'f.sysclk < 102400000', 'value': hexv(3)}],
             'default': hexv(4)},
            {'field': 'CHECON.ADRWS', 'cases': [{'when': 'f.sysclk < 64000000', 'value': hexv(0)}], 'default': hexv(1 << 8)}],
    constraints=[SPLL2_RULE])


# ---------------------------------------------------------------------------------------------
# PIC32CZ CA80/CA90/CA91 clock graph fragment (pic32cz_ca8, pic32cz2051ca9, pic32cz4010ca9,
# pic32cz8110ca9 init_clock.c).
#
# DFLL48M (open loop 48 MHz, or closed loop on generator 2), XOSC (crystal or external clock,
# up to 48 MHz), XOSC32K and OSCULP32K -> PLL0/PLL1 (reference: generator 1, XOSC or DFLL48M;
# Fpfd = reference / REFDIV 4-60 MHz, Fvco = Fpfd x FBDIV 800-1600 MHz, output k = Fvco / POSTDIVk,
# above 12.7 MHz) -> generator 0 -> MCLK CLKDIV0 (CPU, 300 MHz) and CLKDIV1 (bus, 150 MHz).
# Default (MPLAB Harmony csp clk_pic32cz_ca defaults): DFLL48M /12 = 4 MHz x225 = 900 MHz /3 =
# 300 MHz CPU, bus /2 = 150 MHz. PLL0 outputs 1..3 (/4, /6, /12) are kept enabled: init_clock.c
# steps the CPU up through them. The PLLs need the PLL voltage regulator (SUPC VREGCTRL.AVREGEN).
# Flash wait states: FCR_CTRLA.AUTOWS (on by default); FWS follows the CPU clock (Harmony table,
# 23 MHz per wait state, 7 above 150 MHz) for AUTOWS off. FRACDIV (PLL1 outputs 0/1) is not used.
def czca_pll(n, y, outputs):
    nodes = [
        mux(f'pll{n}_gclk', f'PLL{n} generator', 3, y + 1, f'PCHCTRL_PLL{n}.GEN', [('gclk1', 'GCLK1', 'gclk1', 1)]),
        mux(f'pll{n}_ref', f'PLL{n} reference', 4, y, f'PLL{n}CTRL.REFSEL',
            [('gclk', 'GCLK', f'pll{n}_gclk', 0), ('xosc', 'XOSC', 'xosc', 1 << 8), ('dfll48m', 'DFLL48M', 'dfll48m', 2 << 8)]),
        span(f'pll{n}_pfd', f'PLL{n} /REFDIV', 5, y, f'pll{n}_ref', f'PLL{n}REFDIV.REFDIV', 0, 1, 63, 'div',
             min=4 * MHZ, max=60 * MHZ, tooltip='Fpfd = reference / REFDIV: 4-60 MHz.'),
        span(f'pll{n}_vco', f'PLL{n} xFBDIV', 6, y, f'pll{n}_pfd', f'PLL{n}FBDIV.FBDIV', 0, 21, 1023, 'mul',
             min=800 * MHZ, max=1600 * MHZ, enable=en(f'PLL{n}CTRL.ENABLE', 1 << 1),
             tooltip='Fvco = Fpfd x FBDIV: 800-1600 MHz (BWSEL is set with the PLL settings).'),
    ]
    for k in outputs:
        auto = 'on' if (n == 0 and k > 0) else 'both'
        nodes.append(span(f'pll{n}_out{k}', f'PLL{n} out{k} /POSTDIV{k}', 7, y + k - outputs[0], f'pll{n}_vco',
                          f'PLL{n}POSTDIVA.POSTDIV{k}', 8 * k, 1, 63, 'div', min=12700001,
                          enable=en(f'PLL{n}POSTDIVA.OUTEN{k}', 1 << (7 + 8 * k), auto=auto),
                          tooltip=f'PLL{n} output {k} = Fvco / POSTDIV{k}, above 12.7 MHz.' +
                          (' Kept enabled: the CPU clock is stepped up through it.' if auto == 'on' else '')))
    return nodes


PIC32CZ_CA = sam(
    'pic32cz_ca80_ca9x', 'PIC32CZ CA80/CA90/CA91 clock tree',
    'PIC32CZ CA80/CA90 family datasheet DS60001749, OSCCTRL/OSC32KCTRL/GCLK/MCLK/FCR/SUPC',
    ['^PIC32CZ(2051|4010|8110)CA(80|90|91)'], 'cpu',
    {'xosc': {'label': 'XOSC frequency', 'default': 12 * MHZ, 'min': 8 * MHZ, 'max': 48 * MHZ}},
    [
        external('xosc', 'XOSC', 0, 0, en('XOSCCTRLA.ENABLE', 1 << 1), tooltip='Crystal or external clock, up to 48 MHz.'),
        fixed('xosc32k', 'XOSC32K 32.768 kHz', 0, 1, 32768, en('XOSC32K.ENABLE', 1 << 1)),
        fixed('osculp32k', 'OSCULP32K 32.768 kHz', 0, 2, 32768),
        mux('gclk2src', 'GCLK2 source', 1, 3, 'GENCTRL2.SRC', [('xosc', 'XOSC', 'xosc', 0), ('osculp32k', 'OSCULP32K', 'osculp32k', 3),
                                                              ('xosc32k', 'XOSC32K', 'xosc32k', 4)],
            enable=en('GENCTRL2.GENEN', 1 << 8), tooltip='Generator 2 is the closed-loop DFLL48M reference.'),
        gclk_div('gclk2', 'GCLK2 /DIV', 2, 3, 'gclk2src', 'GENCTRL2.DIV', 16, 'GENCTRL2.DIVSEL', 12, 255, 7),
        mux('dfll_ref', 'DFLL48M reference', 3, 3, 'PCHCTRL_DFLL48.GEN', [('gclk2', 'GCLK2', 'gclk2', 2)]),
        span('dfll_mul', 'DFLL48M xMUL', 4, 3, 'dfll_ref', 'DFLLMUL.MUL', 0, 1, 65535, 'mul'),
        {'id': 'dfll48m', 'label': 'DFLL48M', 'kind': 'mux', 'x': 1, 'y': 5, 'enable': en('DFLLCTRLA.ENABLE', 1 << 1, auto='on'),
         'max': 48048000, 'tooltip': 'Startup oscillator (open loop, factory calibration); closed loop locks to reference x MUL.',
         'options': [{'id': 'open', 'label': 'Open loop 48 MHz', 'mul': 48 * MHZ, 'set': {'DFLLCTRLB.LOOPEN': hexv(0)}},
                     {'id': 'closed', 'label': 'Closed loop', 'from': 'dfll_mul', 'set': {'DFLLCTRLB.LOOPEN': hexv(1)}}]},
        mux('gclk1src', 'GCLK1 source', 1, 7, 'GENCTRL1.SRC', [('xosc', 'XOSC', 'xosc', 0), ('osculp32k', 'OSCULP32K', 'osculp32k', 3),
                                                              ('xosc32k', 'XOSC32K', 'xosc32k', 4), ('dfll48m', 'DFLL48M', 'dfll48m', 5)],
            enable=en('GENCTRL1.GENEN', 1 << 8), tooltip='Generator 1 is the PLL GCLK reference.'),
        gclk_div('gclk1', 'GCLK1 /DIV', 2, 7, 'gclk1src', 'GENCTRL1.DIV', 16, 'GENCTRL1.DIVSEL', 12, 255, 15),
        *czca_pll(0, 5, [0, 1, 2, 3]),
        *czca_pll(1, 10, [2, 3]),
        mux('gclk0src', 'GCLK0 source', 8, 1, 'GENCTRL0.SRC',
            [('xosc', 'XOSC', 'xosc', 0), ('gclk1', 'GCLK1', 'gclk1', 2), ('osculp32k', 'OSCULP32K', 'osculp32k', 3),
             ('xosc32k', 'XOSC32K', 'xosc32k', 4), ('dfll48m', 'DFLL48M', 'dfll48m', 5),
             ('pll0_out0', 'PLL0 output 0', 'pll0_out0', 6), ('pll0_out1', 'PLL0 output 1', 'pll0_out1', 7),
             ('pll0_out2', 'PLL0 output 2', 'pll0_out2', 8), ('pll0_out3', 'PLL0 output 3', 'pll0_out3', 9),
             ('pll1_out2', 'PLL1 output 2', 'pll1_out2', 12), ('pll1_out3', 'PLL1 output 3', 'pll1_out3', 13)]),
        gclk_div('gclk0', 'GCLK0 /DIV', 9, 1, 'gclk0src', 'GENCTRL0.DIV', 16, 'GENCTRL0.DIVSEL', 12, 255, 7, max=300 * MHZ),
        factors('cpu', 'CPU (CLKDIV0)', 10, 0, 'gclk0', *pow2('CLKDIV0.DIV'), max=300 * MHZ, consumer=True,
                tooltip='CPU clock (MCLK clock domain 0): at most 300 MHz.'),
        factors('bus', 'Bus (CLKDIV1)', 10, 2, 'gclk0', *pow2('CLKDIV1.DIV'), max=150 * MHZ, consumer=True,
                tooltip='Bus clock (MCLK clock domain 1): at most 150 MHz.'),
    ],
    settings=['FCR_CTRLA.AUTOWS', 'FCR_CTRLA.ADRWS', 'VREGCTRL.AVREGEN', 'PLL0CTRL.BWSEL', 'PLL1CTRL.BWSEL',
              'XOSCCTRLA.XTALEN', 'XOSC32K.XTALEN'],
    derive=[{'field': 'FCR_CTRLA.FWS',
             'cases': [{'when': f'f.cpu <= {mhz}e6', 'value': hexv(ws << 8)}
                       for mhz, ws in ((23, 0), (46, 1), (69, 2), (92, 3), (115, 4), (138, 5), (150, 6))],
             'default': hexv(7 << 8)}],
    constraints=[
        rule('f.bus <= f.cpu', 'The bus clock (CLKDIV1) must not be faster than the CPU clock (CLKDIV0).'),
        rule("reg(\"VREGCTRL.AVREGEN\") != 0 || (reg(\"PLL0CTRL.ENABLE\") == 0 && reg(\"PLL1CTRL.ENABLE\") == 0)",
             'PLL0/PLL1 need the PLL voltage regulator (VREGCTRL.AVREGEN).'),
    ])

GRAPHS = [PIC32CX_SG, PIC32CZ_CA70, PIC32CX_MT, PIC32CX_SG1, PIC32CX_BZ2, PIC32CX_BZ3, PIC32CX_BZ6, PIC32CZ_CA]


def main():
    failed = False
    for item in GRAPHS:
        problems = check_graph(item)
        for problem in problems:
            print(f'{item["id"]}: {problem}')
        failed = failed or bool(problems)
        print(f'wrote {write_graph(item, f"microchip_pic32c/{item["id"]}.json").relative_to(REPO_ROOT)}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
