"""Write the Microchip SAM clock graphs (clock_graphs/microchip_sam/*.json).

Hand-written from the SAM datasheets' clock chapters (PMC, SYSCTRL/GCLK/PM, OSCCTRL/GCLK/MCLK,
SCIF/PM/BPM). Only families whose NECTO definitions carry the clock registers and whose core
system library (system/src/sam/<lib>/init_clock.c) applies them are described:
SAM E70/S70/V70/V71(RT), SAM G51/G53/G54/G55, SAM4E/4N/4S/4SA/4SD, SAM4L, SAM D09/D10/D11/D20/D21/
DA1/R21/HA0/HA1, SAM C20/C21, SAM L21/L22/R30/R34/R35, SAM D51/E51/E53/E54 and SAM RH71/RH707.
Register values are absolute bit values (see clock_graphs/README.md).

Run:  python scripts/clock_graphs/microchip_sam_graphs.py
"""

from graphlib import REPO_ROOT, check_graph, hexv, write_graph
from stm32_graphs import MHZ, en, external, factors, fixed, fixed_div, graph, mux, rule, span


# PMC_MCKR.PRES: /1 .. /64 are codes 0..6, /3 is code 7.
PRES = [(1, 0), (2, 1), (4, 2), (8, 3), (16, 4), (32, 5), (64, 6), (3, 7)]


def sam(graph_id, title, source, devices, fosc, inputs, nodes, **extra):
    result = graph(graph_id, title, source, devices, fosc, inputs, nodes, **extra)
    result['vendor'] = 'Microchip'
    return result


def slow_clock(y):
    return {'id': 'slck', 'label': 'Slow clock (SLCK)', 'kind': 'source', 'x': 0, 'y': y,
            'tooltip': 'SUPC_CR.XTALSEL switches SLCK to the 32.768 kHz crystal.',
            'options': [{'id': 'rc', 'label': 'RC 32 kHz', 'mul': 32000, 'set': {'SUPC_CR.XTALSEL': hexv(0)}},
                        {'id': 'xtal', 'label': 'Crystal 32.768 kHz', 'mul': 32768, 'set': {'SUPC_CR.XTALSEL': hexv(1 << 3)}}]}


def main_clock(rc_frequencies, xtal_y=2):
    """Main RC (MOSCRCF), main crystal and the MOSCSEL mux."""
    return [
        {'id': 'main_rc', 'label': 'Main RC', 'kind': 'source', 'x': 0, 'y': 0,
         'enable': en('CKGR_MOR.MOSCRCEN', 1 << 3, auto='on'),
         'options': [{'id': str(hz // MHZ), 'label': f'RC {hz // MHZ} MHz', 'mul': hz, 'set': {'CKGR_MOR.MOSCRCF': hexv(code << 4)}}
                     for code, hz in enumerate(rc_frequencies)]},
        external('main_xtal', 'Main crystal', 0, xtal_y, en('CKGR_MOR.MOSCXTEN', 1), tooltip='3-20 MHz crystal (CKGR_MOR.MOSCXTEN).'),
        mux('mainck', 'MAINCK', 1, 1, 'CKGR_MOR.MOSCSEL', [('rc', 'Main RC', 'main_rc', 0), ('xtal', 'Main crystal', 'main_xtal', 1 << 24)]),
    ]


def xtal_input(default):
    return {'main_xtal': {'label': 'Main crystal frequency', 'default': default, 'min': 3 * MHZ, 'max': 20 * MHZ}}


# SAM E70/S70/V70/V71: PLLA = MAINCK / DIVA * (MULA + 1), UPLL 480 MHz from a 12/16 MHz crystal,
# HCLK = selected / PRES (300 MHz), MCK = HCLK / MDIV (150 MHz).
SAM_X7 = sam(
    'sam_e70_s70_v70_v71', 'SAM E70/S70/V70/V71 clock tree', 'SAM E70/S70/V70/V71 datasheet DS60001527, PMC',
    ['^ATSAM[ESV]7[01]'], 'hclk', xtal_input(12 * MHZ),
    [
        *main_clock([4 * MHZ, 8 * MHZ, 12 * MHZ]),
        slow_clock(4),
        span('diva', 'PLLA /DIVA', 2, 1, 'mainck', 'CKGR_PLLAR.DIVA', 0, 1, 255, 'div', min=8 * MHZ, max=32 * MHZ,
             tooltip='PLLA input: 8-32 MHz.'),
        span('mula', 'PLLA xMULA', 3, 1, 'diva', 'CKGR_PLLAR.MULA', 16, 2, 62, 'mul', offset=-1, min=160 * MHZ, max=500 * MHZ,
             tooltip='PLLACK: 160-500 MHz.'),
        {'id': 'upll', 'label': 'UPLL 480 MHz', 'kind': 'source', 'x': 2, 'y': 3, 'enable': en('CKGR_UCKR.UPLLEN', 1 << 16),
         'tooltip': 'UTMI PLL: 480 MHz from a 12 or 16 MHz main crystal.',
         'options': [{'id': 'on', 'label': 'UPLL 480 MHz', 'mul': 480 * MHZ, 'keeps': ['main_xtal']}]},
        factors('upllckdiv', 'UPLLDIV2', 3, 3, 'upll', 'PMC_MCKR.UPLLDIV2', 13, [(1, 0), (2, 1)]),
        mux('css', 'Master clock source', 4, 1, 'PMC_MCKR.CSS', [('slck', 'SLCK', 'slck', 0), ('mainck', 'MAINCK', 'mainck', 1),
                                                                 ('plla', 'PLLA', 'mula', 2), ('upll', 'UPLLCKDIV', 'upllckdiv', 3)]),
        factors('hclk', 'HCLK (PRES)', 5, 1, 'css', 'PMC_MCKR.PRES', 4, PRES, max=300 * MHZ, consumer=True,
                tooltip='Processor clock (HCLK/FCLK): at most 300 MHz.'),
        factors('mck', 'MCK (MDIV)', 6, 1, 'hclk', 'PMC_MCKR.MDIV', 8, [(1, 0), (2, 1), (4, 2), (3, 3)], max=150 * MHZ, consumer=True,
                tooltip='Master clock for the buses and peripherals: at most 150 MHz.'),
        mux('usbsrc', 'USB source', 4, 3, 'PMC_USB.USBS', [('plla', 'PLLA', 'mula', 0), ('upll', 'UPLL', 'upll', 1)]),
        span('usbclk', 'USB_48M /USBDIV', 5, 3, 'usbsrc', 'PMC_USB.USBDIV', 8, 1, 16, 'div', offset=-1, max=48 * MHZ,
             tooltip='USB full speed needs 48 MHz.'),
    ],
    settings=['CKGR_MOR.MOSCXTBY', 'CKGR_MOR.CFDEN'],
    # Wait states follow HCLK (the datasheet bounds are 23 MHz per wait state, at most 6); taking HCLK
    # rather than MCK can only give more wait states, never too few.
    derive=[{'field': 'EEFC_FMR.FWS', 'cases': [{'when': f'f.hclk <= {limit * MHZ}', 'value': hexv(code << 8)}
                                                 for code, limit in enumerate([23, 46, 69, 92, 115, 138])],
             'default': hexv(6 << 8)}],
    constraints=[
        rule("(sel.css != 'upll' && sel.usbsrc != 'upll') || in.main_xtal == 12000000 || in.main_xtal == 16000000",
             'UPLL needs a 12 or 16 MHz main crystal.'),
    ])

# SAM G51/G53/G54/G55: PLLA (and PLLB on G55) multiply the 32 kHz slow clock: (MUL + 1) x SLCK.
SAM_G5 = sam(
    'sam_g5x', 'SAM G51/G53/G54/G55 clock tree', 'SAM G51/G53/G54/G55 datasheets, PMC', ['^ATSAMG5[1345]'], 'hclk', xtal_input(12 * MHZ),
    [
        *main_clock([8 * MHZ, 16 * MHZ, 24 * MHZ]),
        slow_clock(4),
        span('plla', 'PLLA xMULA', 2, 4, 'slck', 'CKGR_PLLAR.MULA', 16, 9, 7501, 'mul', offset=-1, max=120 * MHZ,
             enable=en('CKGR_PLLAR.PLLAEN', 1), tooltip='PLLA multiplies the slow clock: (MULA + 1) x SLCK.'),
        factors('pllaclk', 'PLLADIV2', 3, 4, 'plla', 'PMC_MCKR.PLLADIV2', 12, [(1, 0), (2, 1)]),
        span('pllb', 'PLLB xMULB', 2, 6, 'slck', 'CKGR_PLLBR.MULB', 16, 9, 2401, 'mul', offset=-1, max=120 * MHZ,
             enable=en('CKGR_PLLBR.PLLBEN', 1), tooltip='PLLB (SAM G55) multiplies the slow clock: (MULB + 1) x SLCK.'),
        factors('pllbclk', 'PLLBDIV2', 3, 6, 'pllb', 'PMC_MCKR.PLLBDIV2', 13, [(1, 0), (2, 1)]),
        mux('css', 'Master clock source', 4, 1, 'PMC_MCKR.CSS', [('slck', 'SLCK', 'slck', 0), ('mainck', 'MAINCK', 'mainck', 1),
                                                                 ('plla', 'PLLA', 'pllaclk', 2), ('pllb', 'PLLB', 'pllbclk', 3)]),
        factors('hclk', 'MCK (PRES)', 5, 1, 'css', 'PMC_MCKR.PRES', 4, PRES, max=120 * MHZ, consumer=True,
                tooltip='Master/processor clock. Set EEFC_FMR.FWS for this frequency (see the datasheet flash wait states).'),
        mux('usbsrc', 'USB source', 4, 6, 'PMC_USB.USBS', [('plla', 'PLLA', 'pllaclk', 0), ('pllb', 'PLLB', 'pllbclk', 1)]),
        span('usbclk', 'USB /USBDIV', 5, 6, 'usbsrc', 'PMC_USB.USBDIV', 8, 1, 16, 'div', offset=-1, max=48 * MHZ,
             tooltip='USB (SAM G55) needs 48 MHz.'),
    ],
    settings=['EEFC_FMR.FWS', 'CKGR_MOR.MOSCXTBY', 'CKGR_MOR.CFDEN'],
    variants=[
        # G51: MULA is 0..1463 (PLLA from the slow clock up to 48 MHz).
        {'devices': ['^ATSAMG51'], 'limits': {'plla': {'max': 48 * MHZ}, 'hclk': {'max': 48 * MHZ}}},
        {'devices': ['^ATSAMG53'], 'limits': {'plla': {'max': 48 * MHZ}, 'hclk': {'max': 48 * MHZ}}},
        {'devices': ['^ATSAMG54'], 'limits': {'plla': {'max': 96 * MHZ}, 'hclk': {'max': 96 * MHZ}}},
    ])

# SAM C20/C21: OSC48M / OSC48MDIV (or the 32 kHz oscillators) -> generator 0 / DIV -> CPUDIV.
# XOSC/XOSC32K are left out (their ENABLE bits are hidden in the definitions), and with them the
# FDPLL96M references. Flash wait states follow the CPU clock (19/38/48 MHz bounds).
SAM_C2X = sam(
    'sam_c20_c21', 'SAM C20/C21 clock tree', 'SAM C20/C21 datasheet DS60001479, OSCCTRL/GCLK/MCLK', ['^ATSAMC2[01]'], 'cpu', {},
    [
        fixed('osc48m', 'OSC48M 48 MHz', 0, 0, 48 * MHZ, en('OSC48MCTRL.ENABLE', 1 << 1, auto='on')),
        factors('osc48mdiv', 'OSC48MDIV', 1, 0, 'osc48m', 'OSC48MDIV.DIV', 0, [(n, n - 1) for n in range(1, 17)]),
        fixed('osc32k', 'OSC32K 32.768 kHz', 0, 1, 32768, en('OSC32K.ENABLE', 1 << 1)),
        fixed('osculp32k', 'OSCULP32K 32.768 kHz', 0, 2, 32768),
        mux('gclk0src', 'GCLK0 source', 2, 1, 'GENCTRL0.SRC', [('osc48m', 'OSC48M', 'osc48mdiv', 6), ('osc32k', 'OSC32K', 'osc32k', 4),
                                                             ('osculp32k', 'OSCULP32K', 'osculp32k', 3)]),
        # DIV 0 and 1 both divide by 1.
        {'id': 'gclk0', 'label': 'GCLK0 /DIV', 'kind': 'divider', 'x': 3, 'y': 1,
         'options': [{'id': '1', 'label': '/1', 'from': 'gclk0src', 'div': 1, 'set': {'GENCTRL0.DIV': hexv(0)}},
                     {'id': '1_div1', 'label': '/1 (DIV = 1)', 'from': 'gclk0src', 'div': 1, 'set': {'GENCTRL0.DIV': hexv(1 << 16)}}] +
                    [{'id': str(n), 'label': f'/{n}', 'from': 'gclk0src', 'div': n, 'set': {'GENCTRL0.DIV': hexv(n << 16)}} for n in range(2, 256)]},
        factors('cpu', 'CPU (CPUDIV)', 4, 1, 'gclk0', 'CPUDIV.CPUDIV', 0, [(1 << n, 1 << n) for n in range(8)], max=48 * MHZ, consumer=True),
    ],
    derive=[{'field': 'NVMCTRL_CTRLB.RWS', 'cases': [{'when': 'f.cpu <= 19000000', 'value': hexv(0)},
                                                     {'when': 'f.cpu <= 38000000', 'value': hexv(1 << 1)}],
             'default': hexv(2 << 1)}])

# ---------------------------------------------------------------------------------------------
# Generic clock generator dividers (SYSCTRL GCLK and OSCCTRL GCLK alike): DIVSEL = 0 divides by DIV
# (0 and 1 both mean /1), DIVSEL = 1 divides by 2^(DIV + 1).

def gclk_div(node_id, label, x, y, source, div_field, div_lsb, divsel_field, divsel_bit, linear_max, power_max, **extra):
    def opt(oid, text, div, divsel, raw):
        return {'id': oid, 'label': text, 'from': source, 'div': div,
                'set': {divsel_field: hexv(divsel << divsel_bit), div_field: hexv(raw << div_lsb)}}
    options = [opt('1', '/1', 1, 0, 0), opt('1_div1', '/1 (DIV = 1)', 1, 0, 1)]
    options += [opt(str(n), f'/{n}', n, 0, n) for n in range(2, linear_max + 1)]
    options += [opt(f'p{n}', f'/2^{n + 1} (DIVSEL)', 1 << (n + 1), 1, n) for n in range(power_max + 1)]
    return {'id': node_id, 'label': label, 'kind': 'divider', 'x': x, 'y': y, 'options': options, **extra}


def pow2(field, lsb=0, count=8):
    """Power-of-two dividers whose field holds the factor itself (MCLK CPUDIV/LPDIV/BUPDIV)."""
    return field, lsb, [(1 << n, 1 << n) for n in range(count)]


# ---------------------------------------------------------------------------------------------
# SAM4E / SAM4N / SAM4S / SAM4SA / SAM4SD (atsam4e, atsam4n, atsam4s*, atsam4sa, atsam4sd init_clock.c):
# main RC 4/8/12 MHz or crystal -> PLLA = MAINCK / DIVA x (MULA + 1) (PLLB likewise on 4S) ->
# PLLADIV2 -> CSS -> PRES. The PLL input is 3-32 MHz and its output 80-240 MHz. Flash wait states
# follow the master clock (20 MHz per wait state, VDDCORE 1.08 V table, the conservative one).
SAM4_PMC = sam(
    'sam4_pmc', 'SAM4E/4N/4S clock tree', 'SAM4E DS60001520, SAM4N DS60001523, SAM4S DS60001519, PMC', ['^ATSAM4(E|N|S)'],
    'hclk', xtal_input(12 * MHZ),
    [
        *main_clock([4 * MHZ, 8 * MHZ, 12 * MHZ]),
        slow_clock(6),
        span('diva', 'PLLA /DIVA', 2, 1, 'mainck', 'CKGR_PLLAR.DIVA', 0, 1, 255, 'div', min=3 * MHZ, max=32 * MHZ,
             tooltip='PLLA input: 3-32 MHz.'),
        span('mula', 'PLLA xMULA', 3, 1, 'diva', 'CKGR_PLLAR.MULA', 16, 2, 63, 'mul', offset=-1, min=80 * MHZ, max=240 * MHZ,
             tooltip='PLLA output: 80-240 MHz.'),
        factors('pllack', 'PLLADIV2', 4, 1, 'mula', 'PMC_MCKR.PLLADIV2', 12, [(1, 0), (2, 1)]),
        span('divb', 'PLLB /DIVB', 2, 3, 'mainck', 'CKGR_PLLBR.DIVB', 0, 1, 255, 'div', min=3 * MHZ, max=32 * MHZ,
             tooltip='PLLB (SAM4S/4SA/4SD) input: 3-32 MHz.'),
        span('mulb', 'PLLB xMULB', 3, 3, 'divb', 'CKGR_PLLBR.MULB', 16, 2, 63, 'mul', offset=-1, min=80 * MHZ, max=240 * MHZ,
             tooltip='PLLB output: 80-240 MHz. 96 MHz gives the 48 MHz USB clock with USBDIV /2.'),
        factors('pllbck', 'PLLBDIV2', 4, 3, 'mulb', 'PMC_MCKR.PLLBDIV2', 13, [(1, 0), (2, 1)]),
        mux('css', 'Master clock source', 5, 1, 'PMC_MCKR.CSS', [('slck', 'SLCK', 'slck', 0), ('mainck', 'MAINCK', 'mainck', 1),
                                                                 ('plla', 'PLLA', 'pllack', 2), ('pllb', 'PLLB', 'pllbck', 3)]),
        factors('hclk', 'MCK (PRES)', 6, 1, 'css', 'PMC_MCKR.PRES', 4, PRES, max=120 * MHZ, consumer=True,
                tooltip='Master/processor clock: at most 120 MHz (100 MHz on SAM4N).'),
        {'id': 'usbsrc', 'label': 'USB source', 'kind': 'mux', 'x': 5, 'y': 4,
         'options': [{'id': 'plla', 'label': 'PLLA', 'from': 'pllack', 'set': {'?PMC_USB.USBS': hexv(0)}},
                     {'id': 'pllb', 'label': 'PLLB', 'from': 'pllbck', 'set': {'PMC_USB.USBS': hexv(1)}}],
         'tooltip': 'SAM4E has no USBS: its USB clock always comes from PLLA.'},
        span('usbclk', 'UDP /USBDIV', 6, 4, 'usbsrc', 'PMC_USB.USBDIV', 8, 1, 16, 'div', offset=-1, max=48 * MHZ,
             tooltip='USB device (UDP, SAM4E/4S) needs exactly 48 MHz.'),
    ],
    settings=['CKGR_MOR.MOSCXTBY', 'CKGR_MOR.CFDEN', 'SUPC_MR.OSCBYPASS'],
    derive=[{'field': 'EEFC_FMR.FWS', 'cases': [{'when': f'f.hclk <= {limit * MHZ}', 'value': hexv(code << 8)}
                                                 for code, limit in enumerate([20, 40, 60, 80, 100])],
             'default': hexv(5 << 8)}],
    variants=[{'devices': ['^ATSAM4N'], 'limits': {'hclk': {'max': 100 * MHZ}}}])

# ---------------------------------------------------------------------------------------------
# SAM4L (atsam4l init_clock.c): RCSYS / OSC0 / PLL0 / RC80M / RCFAST -> PM MCSEL -> CPU and PBA-PBD
# dividers (/2^(SEL + 1) when DIV is set). PLL0 runs from OSC0 or generic clock 9 (RCFAST, RC80M or
# OSC0): VCO = (PLLMUL + 1) / PLLDIV x reference, 80-180 MHz, PLLOPT[1] halves the output. Flash:
# one wait state above 18 MHz and high-speed mode (HSEN) above 36 MHz, in power scaling mode PS0.
def pm_div(node_id, label, x, y, source, register, sel_key, div_key, **extra):
    options = [{'id': '1', 'label': '/1', 'from': source, 'set': {f'{register}.{div_key}': hexv(0), f'{register}.{sel_key}': hexv(0)}}]
    options += [{'id': str(1 << (n + 1)), 'label': f'/{1 << (n + 1)}', 'from': source, 'div': 1 << (n + 1),
                 'set': {f'{register}.{div_key}': hexv(1 << 7), f'{register}.{sel_key}': hexv(n)}} for n in range(8)]
    return {'id': node_id, 'label': label, 'kind': 'divider', 'x': x, 'y': y, 'options': options, **extra}


SAM4L = sam(
    'sam4l', 'SAM4L clock tree', 'SAM4L datasheet DS60001543, SCIF/PM/BPM/FLASHCALW', ['^ATSAM4L'], 'cpu',
    {'osc0': {'label': 'OSC0 frequency', 'default': 12 * MHZ, 'min': 600000, 'max': 30 * MHZ}},
    [
        fixed('rcsys', 'RCSYS 115 kHz', 0, 0, 115000),
        external('osc0', 'OSC0', 0, 1, en('SCIF_OSCCTRL0.OSCEN', 1 << 16), tooltip='Crystal 0.6-30 MHz or external clock (SCIF_OSCCTRL0.MODE).'),
        {'id': 'rcfast', 'label': 'RCFAST', 'kind': 'source', 'x': 0, 'y': 2, 'enable': en('SCIF_RCFASTCFG.EN', 1),
         'options': [{'id': str(hz), 'label': f'RCFAST {hz} MHz', 'mul': hz * MHZ, 'set': {'SCIF_RCFASTCFG.FRANGE': hexv(code << 8)}}
                     for code, hz in enumerate([4, 8, 12])]},
        fixed('rc80m', 'RC80M 80 MHz', 0, 3, 80 * MHZ, en('SCIF_RC80MCR.EN', 1)),
        mux('gclk9src', 'GCLK9 source', 1, 2, 'SCIF_GCCTRL9.OSCSEL', [('osc0', 'OSC0', 'osc0', 3 << 8), ('rc80m', 'RC80M', 'rc80m', 4 << 8),
                                                                     ('rcfast', 'RCFAST', 'rcfast', 5 << 8)],
            enable=en('SCIF_GCCTRL9.CEN', 1), tooltip='Generic clock 9 is the PLL0 reference when PLLOSC = GCLK9.'),
        {'id': 'gclk9', 'label': 'GCLK9 /DIV', 'kind': 'divider', 'x': 2, 'y': 2,
         'options': [{'id': '1', 'label': '/1', 'from': 'gclk9src', 'set': {'SCIF_GCCTRL9.DIVEN': hexv(0), 'SCIF_GCCTRL9.DIV': hexv(0)}}] +
                    [{'id': str(2 * (n + 1)), 'label': f'/{2 * (n + 1)}', 'from': 'gclk9src', 'div': 2 * (n + 1),
                      'set': {'SCIF_GCCTRL9.DIVEN': hexv(1 << 1), 'SCIF_GCCTRL9.DIV': hexv(n << 16)}} for n in range(128)]},
        mux('pllsrc', 'PLL0 reference', 3, 1, 'SCIF_PLL0.PLLOSC', [('osc0', 'OSC0', 'osc0', 0), ('gclk9', 'GCLK9', 'gclk9', 1 << 1)]),
        span('plldiv', 'PLL0 /PLLDIV', 4, 1, 'pllsrc', 'SCIF_PLL0.PLLDIV', 8, 1, 15, 'div', min=4 * MHZ, max=16 * MHZ,
             tooltip='PLL0 reference after PLLDIV: 4-16 MHz.'),
        span('pllvco', 'PLL0 x(PLLMUL + 1)', 5, 1, 'plldiv', 'SCIF_PLL0.PLLMUL', 16, 3, 16, 'mul', offset=-1, min=80 * MHZ, max=180 * MHZ,
             enable=en('SCIF_PLL0.PLLEN', 1), tooltip='VCO 80-180 MHz with PLLOPT[0] = 0 (the 160-240 MHz range is set in the register view).'),
        {'id': 'pll0', 'label': 'PLL0 output', 'kind': 'divider', 'x': 6, 'y': 1,
         'options': [{'id': '1', 'label': '/1', 'from': 'pllvco', 'set': {'SCIF_PLL0.PLLOPT': '00000000/00000010'}},
                     {'id': '2', 'label': '/2 (PLLOPT[1])', 'from': 'pllvco', 'div': 2, 'set': {'SCIF_PLL0.PLLOPT': '00000010/00000010'}}]},
        mux('main', 'Main clock (MCSEL)', 7, 2, 'PM_MCCTRL.MCSEL', [('rcsys', 'RCSYS', 'rcsys', 0), ('osc0', 'OSC0', 'osc0', 1),
                                                                    ('pll0', 'PLL0', 'pll0', 2), ('rc80m', 'RC80M', 'rc80m', 4),
                                                                    ('rcfast', 'RCFAST', 'rcfast', 5)]),
        pm_div('cpu', 'CPU (CPUSEL)', 8, 1, 'main', 'PM_CPUSEL', 'CPUSEL', 'CPUDIV', max=48 * MHZ, consumer=True,
               tooltip='CPU and HSB clock: at most 48 MHz (12 MHz in power scaling mode PS1).'),
        *[pm_div(f'pb{bus.lower()}', f'PB{bus} (PB{bus}SEL)', 9, row, 'main', f'PM_PB{bus}SEL', 'PBSEL', 'PBDIV', max=48 * MHZ, consumer=True)
          for row, bus in enumerate('ABCD')],
    ],
    settings=['BPM_PMCON.PS', 'SCIF_OSCCTRL0.MODE', 'SCIF_OSCCTRL0.GAIN'],
    derive=[{'field': 'HFLASHC_FCR.FWS', 'cases': [{'when': 'f.cpu <= 18000000', 'value': hexv(0)}], 'default': hexv(1 << 6)},
            {'field': 'HFLASHC_FCMD.CMD', 'cases': [{'when': 'f.cpu <= 36000000', 'value': hexv(0x11)}], 'default': hexv(0x10)}],
    constraints=[rule("reg('BPM_PMCON.PS') != 1 || f.cpu <= 12000000", 'Power scaling mode PS1 allows at most 12 MHz.'),
                 rule("sel.main != 'rc80m' || f.cpu <= 48000000", 'RC80M must be divided down to 48 MHz for the CPU.')])

# ---------------------------------------------------------------------------------------------
# SAM D09/D10/D11/D20/D21/R21/HA0/HA1 (Harmony headers, init_clock.c): OSC8M, XOSC, the 32 kHz
# oscillators, DFLL48M (open loop, or closed loop: reference generator x DFLLMUL) and FDPLL96M
# (not on D20) -> generic clock generator 0 -> CPUDIV / APBx. Generator 1 is the reference generator
# of the DFLL48M / FDPLL96M (default: OSC8M / 256 = 31.25 kHz -> DFLL x1536 = 48 MHz).
LOG2 = [(1 << n, n) for n in range(8)]


def sysctrl_graph(graph_id, title, source, devices, dpll):
    sources = [('osc8m', 'OSC8M', 'osc8m_presc', 6 << 8), ('xosc', 'XOSC', 'xosc', 0), ('xosc32k', 'XOSC32K', 'xosc32k', 5 << 8),
               ('osc32k', 'OSC32K', 'osc32k', 4 << 8), ('osculp32k', 'OSCULP32K', 'osculp32k', 3 << 8)]
    nodes = [
        fixed('osc8m', 'OSC8M 8 MHz', 0, 0, 8 * MHZ, en('OSC8M.ENABLE', 1 << 1, auto='on')),
        factors('osc8m_presc', 'OSC8M prescaler', 1, 0, 'osc8m', 'OSC8M.PRESC', 8, [(1, 0), (2, 1), (4, 2), (8, 3)]),
        external('xosc', 'XOSC', 0, 1, en('XOSC.ENABLE', 1 << 1), tooltip='External crystal or clock, 0.4-32 MHz.'),
        fixed('xosc32k', 'XOSC32K 32.768 kHz', 0, 2, 32768, en('XOSC32K.ENABLE', 1 << 1)),
        fixed('osc32k', 'OSC32K 32.768 kHz', 0, 3, 32768, en('OSC32K.ENABLE', 1 << 1)),
        fixed('osculp32k', 'OSCULP32K 32.768 kHz', 0, 4, 32768),
        mux('gclk1src', 'GCLK1 source', 1, 5, 'GENCTRL1.SRC', sources, enable=en('GENCTRL1.GENEN', 1 << 16)),
        gclk_div('gclk1', 'GCLK1 /DIV', 2, 5, 'gclk1src', 'GENDIV1.DIV', 8, 'GENCTRL1.DIVSEL', 20, 255, 15),
        mux('dfll_ref', 'DFLL48M reference', 3, 5, 'CLKCTRL.GEN', [('gclk1', 'GCLK1', 'gclk1', 1 << 8)],
            enable=en('CLKCTRL.CLKEN', 1 << 14), max=33000, tooltip='Closed-loop reference: at most 33 kHz.'),
        span('dfll_mul', 'DFLL48M xMUL', 4, 5, 'dfll_ref', 'DFLLMUL.MUL', 0, 1, 65535, 'mul'),
        {'id': 'dfll48m', 'label': 'DFLL48M', 'kind': 'mux', 'x': 5, 'y': 4, 'enable': en('DFLLCTRL.ENABLE', 1 << 1),
         'max': 48048000, 'tooltip': 'Open loop runs on the factory calibration; closed loop locks to reference x DFLLMUL.MUL.',
         'options': [{'id': 'open', 'label': 'Open loop 48 MHz', 'mul': 48 * MHZ, 'set': {'DFLLCTRL.MODE': hexv(0)}},
                     {'id': 'closed', 'label': 'Closed loop', 'from': 'dfll_mul', 'set': {'DFLLCTRL.MODE': hexv(1 << 2)}}]},
    ]
    gclk0 = sources + [('gclk1', 'GCLK1', 'gclk1', 2 << 8), ('dfll48m', 'DFLL48M', 'dfll48m', 7 << 8)]
    if dpll:
        nodes += [
            fixed_div('xosc_half', 'XOSC /2', 1, 6, 'xosc', 2),
            span('xosc_dpll', 'XOSC /(DIV + 1)', 2, 6, 'xosc_half', 'DPLLCTRLB.DIV', 16, 1, 2048, 'div', offset=-1),
            mux('dpll_gclk', 'FDPLL96M generator', 3, 7, 'CLKCTRL_FDPLL.GEN', [('gclk1', 'GCLK1', 'gclk1', 1 << 8)],
                enable=en('CLKCTRL_FDPLL.CLKEN', 1 << 14)),
            mux('dpll_ref', 'FDPLL96M reference', 4, 7, 'DPLLCTRLB.REFCLK', [('xosc32k', 'XOSC32K', 'xosc32k', 0), ('xosc', 'XOSC', 'xosc_dpll', 1 << 4),
                                                                              ('gclk', 'GCLK', 'dpll_gclk', 2 << 4)],
                min=32000, max=2 * MHZ, tooltip='FDPLL96M reference: 32 kHz-2 MHz.'),
            span('fdpll96m', 'FDPLL96M x(LDR + 1)', 5, 7, 'dpll_ref', 'DPLLRATIO.LDR', 0, 1, 4096, 'mul', offset=-1, min=48 * MHZ, max=96 * MHZ,
                 enable=en('DPLLCTRLA.ENABLE', 1 << 1), tooltip='Output 48-96 MHz (the fractional part LDRFRAC is set in the register view).'),
        ]
        gclk0.append(('fdpll96m', 'FDPLL96M', 'fdpll96m', 8 << 8))
    nodes += [
        mux('gclk0src', 'GCLK0 source', 6, 2, 'GENCTRL0.SRC', gclk0),
        gclk_div('gclk0', 'GCLK0 /DIV', 7, 2, 'gclk0src', 'GENDIV0.DIV', 8, 'GENCTRL0.DIVSEL', 20, 255, 7),
        factors('cpu', 'CPU (CPUDIV)', 8, 1, 'gclk0', 'CPUSEL.CPUDIV', 0, LOG2, max=48 * MHZ, consumer=True),
        factors('apba', 'APBA (APBADIV)', 9, 1, 'cpu', 'APBASEL.APBADIV', 0, LOG2, max=48 * MHZ, consumer=True),
        factors('apbb', 'APBB (APBBDIV)', 9, 2, 'cpu', 'APBBSEL.APBBDIV', 0, LOG2, max=48 * MHZ, consumer=True),
        factors('apbc', 'APBC (APBCDIV)', 9, 3, 'cpu', 'APBCSEL.APBCDIV', 0, LOG2, max=48 * MHZ, consumer=True),
    ]
    return sam(graph_id, title, source, devices, 'cpu',
               {'xosc': {'label': 'XOSC frequency', 'default': 16 * MHZ, 'min': 400000, 'max': 32 * MHZ}}, nodes,
               settings=['XOSC.XTALEN', 'XOSC32K.XTALEN'],
               # 1 wait state above 24 MHz (VDD 2.7-3.6 V; below 2.7 V 48 MHz needs 3, set in the register view).
               derive=[
                   {'field': 'NVMCTRL_CTRLB.RWS', 'cases': [{'when': 'f.cpu <= 24000000', 'value': hexv(0)}], 'default': hexv(1 << 1)},
                   {'field': 'XOSC.GAIN', 'cases': [{'when': f'in.xosc <= {limit}', 'value': hexv(code << 8)}
                                                    for code, limit in enumerate([2 * MHZ, 4 * MHZ, 8 * MHZ, 16 * MHZ])],
                    'default': hexv(4 << 8)},
               ])


SAM_D1X = sysctrl_graph(
    'sam_d1x_d21_r21_ha', 'SAM D09/D10/D11/D21/DA1/R21/HA0/HA1 clock tree',
    'SAM D09/D10/D11/D21 DS40001882/DA1/R21/HA1 datasheets, SYSCTRL/GCLK/PM',
    ['^ATSAM(D09|D10|D11|D21|DA1|R21|HA0|HA1)'], dpll=True)
SAM_D20 = sysctrl_graph('sam_d20', 'SAM D20 clock tree', 'SAM D20 datasheet DS60001504, SYSCTRL/GCLK/PM', ['^ATSAMD20'], dpll=False)

# ---------------------------------------------------------------------------------------------
# SAM L21/R30/R34/R35 and SAM L22 (init_clock.c): OSC16M (4/8/12/16 MHz), XOSC and the 32 kHz
# oscillators -> generator 1 -> FDPLL96M (x(LDR + 1), 48-96 MHz) -> DPLLPRESC -> generator 0 ->
# MCLK CPUDIV (and LPDIV/BUPDIV). Performance level PL2 is needed above 12 MHz (8 MHz on L22);
# flash wait states are a register setting (NVMCTRL_CTRLB.RWS, see the datasheet NVM table).
def l2x_graph(graph_id, title, source, devices, codes, cpu_max, pl0_max, lpdiv):
    """codes: GENCTRLn.SRC values of xosc, osculp32k, osc32k (or None), xosc32k, osc16m, dpll."""
    sources = [('xosc', 'XOSC', 'xosc', codes['xosc']), ('osculp32k', 'OSCULP32K', 'osculp32k', codes['osculp32k']),
               ('xosc32k', 'XOSC32K', 'xosc32k', codes['xosc32k']), ('osc16m', 'OSC16M', 'osc16m', codes['osc16m'])]
    nodes = [
        {'id': 'osc16m', 'label': 'OSC16M', 'kind': 'source', 'x': 0, 'y': 0,
         'options': [{'id': str(hz), 'label': f'OSC16M {hz} MHz', 'mul': hz * MHZ, 'set': {'OSC16MCTRL.FSEL': hexv(code << 2)}}
                     for code, hz in enumerate([4, 8, 12, 16])]},
        external('xosc', 'XOSC', 0, 1, en('XOSCCTRL.ENABLE', 1 << 1), tooltip='External crystal or clock, 0.4-32 MHz.'),
        fixed('xosc32k', 'XOSC32K 32.768 kHz', 0, 2, 32768, en('XOSC32K.ENABLE', 1 << 1)),
        fixed('osculp32k', 'OSCULP32K 32.768 kHz', 0, 4, 32768),
    ]
    if codes.get('osc32k') is not None:
        nodes.append(fixed('osc32k', 'OSC32K 32.768 kHz', 0, 3, 32768, en('OSC32K.ENABLE', 1 << 1)))
        sources.append(('osc32k', 'OSC32K', 'osc32k', codes['osc32k']))
    nodes += [
        mux('gclk1src', 'GCLK1 source', 1, 5, 'GENCTRL1.SRC', sources, enable=en('GENCTRL1.GENEN', 1 << 8)),
        gclk_div('gclk1', 'GCLK1 /DIV', 2, 5, 'gclk1src', 'GENCTRL1.DIV', 16, 'GENCTRL1.DIVSEL', 12, 255, 15),
        mux('dpll_gclk', 'FDPLL96M generator', 3, 5, 'PCHCTRL_FDPLL.GEN', [('gclk1', 'GCLK1', 'gclk1', 1)],
            enable=en('PCHCTRL_FDPLL.CHEN', 1 << 6)),
        fixed_div('xosc_half', 'XOSC /2', 1, 6, 'xosc', 2),
        span('xosc_dpll', 'XOSC /(DIV + 1)', 2, 6, 'xosc_half', 'DPLLCTRLB.DIV', 16, 1, 2048, 'div', offset=-1),
        mux('dpll_ref', 'FDPLL96M reference', 4, 5, 'DPLLCTRLB.REFCLK', [('xosc32k', 'XOSC32K', 'xosc32k', 0), ('xosc', 'XOSC', 'xosc_dpll', 1 << 4),
                                                                          ('gclk', 'GCLK', 'dpll_gclk', 2 << 4)],
            min=32000, max=2 * MHZ, tooltip='FDPLL96M reference: 32 kHz-2 MHz.'),
        span('fdpll96m', 'FDPLL96M x(LDR + 1)', 5, 5, 'dpll_ref', 'DPLLRATIO.LDR', 0, 1, 4096, 'mul', offset=-1, min=48 * MHZ, max=96 * MHZ,
             enable=en('DPLLCTRLA.ENABLE', 1 << 1), tooltip='Output 48-96 MHz (the fractional part LDRFRAC is set in the register view).'),
        factors('dpll_presc', 'DPLLPRESC', 6, 5, 'fdpll96m', 'DPLLPRESC.PRESC', 0, [(1, 0), (2, 1), (4, 2)]),
        mux('gclk0src', 'GCLK0 source', 7, 2, 'GENCTRL0.SRC', sources + [('gclk1', 'GCLK1', 'gclk1', 2), ('dpll', 'FDPLL96M', 'dpll_presc', codes['dpll'])]),
        gclk_div('gclk0', 'GCLK0 /DIV', 8, 2, 'gclk0src', 'GENCTRL0.DIV', 16, 'GENCTRL0.DIVSEL', 12, 255, 7),
        factors('cpu', 'CPU (CPUDIV)', 9, 1, 'gclk0', *pow2('CPUDIV.CPUDIV'), max=cpu_max, consumer=True,
                tooltip=f'CPU / AHB / APB clock: at most {cpu_max // MHZ} MHz in PL2.'),
        factors('bup', 'Backup (BUPDIV)', 9, 3, 'gclk0', *pow2('BUPDIV.BUPDIV'), max=cpu_max, consumer=True),
    ]
    constraints = [rule(f"reg('PLCFG.PLSEL') == 2 || f.cpu <= {pl0_max}", f'Performance level PL0 allows at most {pl0_max // MHZ} MHz: select PL2.')]
    if lpdiv:
        nodes.append(factors('lp', 'Low power (LPDIV)', 9, 2, 'gclk0', *pow2('LPDIV.LPDIV'), max=cpu_max, consumer=True))
        constraints += [rule('f.lp <= f.cpu', 'LPDIV must divide at least as much as CPUDIV.'),
                        rule('f.bup <= f.lp', 'BUPDIV must divide at least as much as LPDIV.')]
    else:
        constraints.append(rule('f.bup <= f.cpu', 'BUPDIV must divide at least as much as CPUDIV.'))
    return sam(graph_id, title, source, devices, 'cpu',
               {'xosc': {'label': 'XOSC frequency', 'default': 16 * MHZ, 'min': 400000, 'max': 32 * MHZ}}, nodes,
               settings=['NVMCTRL_CTRLB.RWS', 'PLCFG.PLSEL', 'XOSCCTRL.XTALEN', 'XOSC32K.XTALEN'], constraints=constraints)


SAM_L21 = l2x_graph('sam_l21_r3x', 'SAM L21/R30/R34/R35 clock tree', 'SAM L21 DS60001477, SAM R30/R34/R35 datasheets, OSCCTRL/GCLK/MCLK',
                    ['^ATSAM(L21|R30|R34|R35)'], {'xosc': 0, 'osculp32k': 3, 'osc32k': 4, 'xosc32k': 5, 'osc16m': 6, 'dpll': 8},
                    48 * MHZ, 12 * MHZ, lpdiv=True)
SAM_L22 = l2x_graph('sam_l22', 'SAM L22 clock tree', 'SAM L22 datasheet DS60001465, OSCCTRL/GCLK/MCLK', ['^ATSAML22'],
                    {'xosc': 0, 'osculp32k': 3, 'osc32k': None, 'xosc32k': 4, 'osc16m': 5, 'dpll': 7}, 32 * MHZ, 8 * MHZ, lpdiv=False)

# ---------------------------------------------------------------------------------------------
# SAM D51/E51/E53/E54 (init_clock.c): DFLL48M (open loop, or closed loop on generator 2), XOSC0/1,
# XOSC32K -> generator 1 -> DPLL0/DPLL1 (x(LDR + 1), 96-200 MHz) -> generator 0 -> CPUDIV.
# Default: DFLL48M / 48 (GCLK1) = 1 MHz -> DPLL0 x120 = 120 MHz. Flash wait states: NVMCTRL_CTRLA
# (AUTOWS on by default), set in the register view.
def d5x_dpll(n, y):
    return [
        mux(f'dpll{n}_gclk', f'DPLL{n} generator', 3, y, f'PCHCTRL_FDPLL{n}.GEN', [('gclk1', 'GCLK1', 'gclk1', 1), ('gclk2', 'GCLK2', 'gclk2', 2)]),
        fixed_div(f'xosc0_half{n}', 'XOSC0 /2', 2, y + 1, 'xosc0', 2),
        span(f'xosc0_dpll{n}', 'XOSC0 /(DIV + 1)', 3, y + 1, f'xosc0_half{n}', f'DPLL{n}CTRLB.DIV', 16, 1, 2048, 'div', offset=-1),
        fixed_div(f'xosc1_half{n}', 'XOSC1 /2', 2, y + 2, 'xosc1', 2),
        span(f'xosc1_dpll{n}', 'XOSC1 /(DIV + 1)', 3, y + 2, f'xosc1_half{n}', f'DPLL{n}CTRLB.DIV', 16, 1, 2048, 'div', offset=-1),
        mux(f'dpll{n}_ref', f'DPLL{n} reference', 4, y, f'DPLL{n}CTRLB.REFCLK',
            [('gclk', 'GCLK', f'dpll{n}_gclk', 0), ('xosc32k', 'XOSC32K', 'xosc32k', 1 << 5),
             ('xosc0', 'XOSC0', f'xosc0_dpll{n}', 2 << 5), ('xosc1', 'XOSC1', f'xosc1_dpll{n}', 3 << 5)],
            min=32000, max=3200000, tooltip=f'DPLL{n} reference: 32 kHz-3.2 MHz.'),
        span(f'dpll{n}', f'DPLL{n} x(LDR + 1)', 5, y, f'dpll{n}_ref', f'DPLL{n}RATIO.LDR', 0, 1, 8192, 'mul', offset=-1,
             min=96 * MHZ, max=200 * MHZ, enable=en(f'DPLL{n}CTRLA.ENABLE', 1 << 1),
             tooltip='Output 96-200 MHz (the fractional part LDRFRAC is set in the register view).'),
    ]


SAM_D5X = sam(
    'sam_d5x_e5x', 'SAM D51/E51/E53/E54 clock tree', 'SAM D5x/E5x datasheet DS60001507, OSCCTRL/GCLK/MCLK',
    ['^ATSAM(D51|E51|E53|E54)'], 'cpu',
    {'xosc0': {'label': 'XOSC0 frequency', 'default': 12 * MHZ, 'min': 8 * MHZ, 'max': 48 * MHZ},
     'xosc1': {'label': 'XOSC1 frequency', 'default': 12 * MHZ, 'min': 8 * MHZ, 'max': 48 * MHZ}},
    [
        external('xosc0', 'XOSC0', 0, 0, en('XOSCCTRL0.ENABLE', 1 << 1), tooltip='Crystal or external clock, 8-48 MHz.'),
        external('xosc1', 'XOSC1', 0, 1, en('XOSCCTRL1.ENABLE', 1 << 1), tooltip='Crystal or external clock, 8-48 MHz.'),
        fixed('xosc32k', 'XOSC32K 32.768 kHz', 0, 2, 32768, en('XOSC32K.ENABLE', 1 << 1)),
        fixed('osculp32k', 'OSCULP32K 32.768 kHz', 0, 3, 32768),
        mux('gclk2src', 'GCLK2 source', 1, 4, 'GENCTRL2.SRC', [('xosc0', 'XOSC0', 'xosc0', 0), ('xosc1', 'XOSC1', 'xosc1', 1),
                                                              ('osculp32k', 'OSCULP32K', 'osculp32k', 4), ('xosc32k', 'XOSC32K', 'xosc32k', 5)],
            enable=en('GENCTRL2.GENEN', 1 << 8), tooltip='Generator 2 is the closed-loop DFLL48M reference.'),
        gclk_div('gclk2', 'GCLK2 /DIV', 2, 4, 'gclk2src', 'GENCTRL2.DIV', 16, 'GENCTRL2.DIVSEL', 12, 255, 7),
        mux('dfll_ref', 'DFLL48M reference', 3, 4, 'PCHCTRL_DFLL48.GEN', [('gclk2', 'GCLK2', 'gclk2', 2)], max=33000,
            tooltip='Closed-loop reference: at most 33 kHz.'),
        span('dfll_mul', 'DFLL48M xMUL', 4, 4, 'dfll_ref', 'DFLLMUL.MUL', 0, 1, 65535, 'mul'),
        {'id': 'dfll48m', 'label': 'DFLL48M', 'kind': 'mux', 'x': 1, 'y': 6, 'enable': en('DFLLCTRLA.ENABLE', 1 << 1, auto='on'),
         'max': 48048000, 'tooltip': 'Runs at reset (open loop, factory calibration); closed loop locks to reference x DFLLMUL.MUL.',
         'options': [{'id': 'open', 'label': 'Open loop 48 MHz', 'mul': 48 * MHZ, 'set': {'DFLLCTRLB.MODE': hexv(0)}},
                     {'id': 'closed', 'label': 'Closed loop', 'from': 'dfll_mul', 'set': {'DFLLCTRLB.MODE': hexv(1)}}]},
        mux('gclk1src', 'GCLK1 source', 2, 6, 'GENCTRL1.SRC', [('xosc0', 'XOSC0', 'xosc0', 0), ('xosc1', 'XOSC1', 'xosc1', 1),
                                                              ('osculp32k', 'OSCULP32K', 'osculp32k', 4), ('xosc32k', 'XOSC32K', 'xosc32k', 5),
                                                              ('dfll48m', 'DFLL48M', 'dfll48m', 6)],
            enable=en('GENCTRL1.GENEN', 1 << 8), tooltip='Generator 1 is the DPLL reference.'),
        gclk_div('gclk1', 'GCLK1 /DIV', 3, 6, 'gclk1src', 'GENCTRL1.DIV', 16, 'GENCTRL1.DIVSEL', 12, 255, 15),
        *d5x_dpll(0, 7),
        *d5x_dpll(1, 10),
        mux('gclk0src', 'GCLK0 source', 6, 2, 'GENCTRL0.SRC', [('xosc0', 'XOSC0', 'xosc0', 0), ('xosc1', 'XOSC1', 'xosc1', 1),
                                                              ('gclk1', 'GCLK1', 'gclk1', 3), ('osculp32k', 'OSCULP32K', 'osculp32k', 4),
                                                              ('xosc32k', 'XOSC32K', 'xosc32k', 5), ('dfll48m', 'DFLL48M', 'dfll48m', 6),
                                                              ('dpll0', 'DPLL0', 'dpll0', 7), ('dpll1', 'DPLL1', 'dpll1', 8)]),
        gclk_div('gclk0', 'GCLK0 /DIV', 7, 2, 'gclk0src', 'GENCTRL0.DIV', 16, 'GENCTRL0.DIVSEL', 12, 255, 7),
        factors('cpu', 'CPU (CPUDIV)', 8, 2, 'gclk0', *pow2('CPUDIV.DIV'), max=120 * MHZ, consumer=True,
                tooltip='CPU clock: at most 120 MHz.'),
    ],
    settings=['NVMCTRL_CTRLA.RWS', 'NVMCTRL_CTRLA.AUTOWS', 'XOSCCTRL0.XTALEN', 'XOSCCTRL1.XTALEN', 'XOSC32K.XTALEN'],
    constraints=[rule("sel.dfll48m == 'open' || sel.gclk1src != 'dfll48m' || sel.dfll_ref == 'gclk2'",
                      'The closed-loop DFLL48M reference must not come from a generator the DFLL48M feeds.')])

# ---------------------------------------------------------------------------------------------
# SAM RH71 / RH707 (init_clock.c): main RC 4/8/10/12 MHz or crystal -> PLLA = MAINCK / DIVA x (MULA + 1)
# (VCO band FREQ_VCO follows the output) -> CSS -> PRES (processor clock, 100 MHz RH71 / 50 MHz RH707)
# -> MDIV (MCK, 50 MHz RH71). The flash controller has no wait-state setting.
SAM_RH = sam(
    'sam_rh71_rh707', 'SAM RH71/RH707 clock tree', 'SAMRH71 DS60001593, SAMRH707 datasheet, PMC', ['^ATSAMRH7(1|07)'], 'hclk',
    {'main_xtal': {'label': 'Main crystal frequency', 'default': 10 * MHZ, 'min': 8 * MHZ, 'max': 20 * MHZ}},
    [
        {'id': 'main_rc', 'label': 'Main RC', 'kind': 'source', 'x': 0, 'y': 0, 'enable': en('CKGR_MOR.MOSCRCEN', 1 << 3, auto='on'),
         'options': [{'id': str(hz), 'label': f'RC {hz} MHz', 'mul': hz * MHZ, 'set': {'CKGR_MOR.MOSCRCF': hexv(code << 4)}}
                     for code, hz in enumerate([4, 8, 10, 12])]},
        external('main_xtal', 'Main crystal', 0, 2, en('CKGR_MOR.MOSCXTEN', 1), tooltip='Crystal or external clock on XIN (CKGR_MOR.MOSCXTEN).'),
        mux('mainck', 'MAINCK', 1, 1, 'CKGR_MOR.MOSCSEL', [('rc', 'Main RC', 'main_rc', 0), ('xtal', 'Main crystal', 'main_xtal', 1 << 24)]),
        {'id': 'slck', 'label': 'Slow clock (MD_SLCK)', 'kind': 'source', 'x': 0, 'y': 4,
         'options': [{'id': 'rc', 'label': 'RC 32 kHz', 'mul': 32000, 'set': {'SUPC_CR.TDXTALSEL': hexv(0)}},
                     {'id': 'xtal', 'label': 'Crystal 32.768 kHz', 'mul': 32768, 'set': {'SUPC_CR.TDXTALSEL': hexv(1 << 3)}}]},
        span('diva', 'PLLA /DIVA', 2, 1, 'mainck', 'CKGR_PLLAR.DIVA', 0, 1, 64, 'div', min=8 * MHZ, max=20 * MHZ,
             tooltip='PLLA input: 8-20 MHz.'),
        span('mula', 'PLLA xMULA', 3, 1, 'diva', 'CKGR_PLLAR.MULA', 16, 2, 57, 'mul', offset=-1, min=40 * MHZ, max=200 * MHZ,
             tooltip='PLLA output: 40-200 MHz; the VCO band (FREQ_VCO) follows it.'),
        mux('css', 'Master clock source', 4, 1, 'PMC_MCKR.CSS', [('slck', 'MD_SLCK', 'slck', 0), ('mainck', 'MAINCK', 'mainck', 1),
                                                                 ('plla', 'PLLA', 'mula', 2)]),
        factors('hclk', 'Processor clock (PRES)', 5, 1, 'css', 'PMC_MCKR.PRES', 4, [(1 << n, n) for n in range(7)], max=100 * MHZ,
                consumer=True, tooltip='Processor clock: at most 100 MHz (RH71) / 50 MHz (RH707).'),
        factors('mck', 'MCK (MDIV)', 6, 1, 'hclk', 'PMC_MCKR.MDIV', 8, [(1, 0), (2, 1)], max=50 * MHZ, consumer=True,
                tooltip='Master clock for the matrix and peripherals.'),
    ],
    settings=['CKGR_MOR.CFDEN', '?CKGR_MOR.MOSCXTBY'],
    derive=[{'field': 'CKGR_PLLAR.FREQ_VCO', 'cases': [{'when': 'f.mula < 75000000', 'value': hexv(0)},
                                                       {'when': 'f.mula < 140000000', 'value': hexv(1 << 14)}],
             'default': hexv(2 << 14)}],
    # RH707: 50 MHz processor clock; its MCK limit is not stated, MDIV /2 (25 MHz) is kept as the bound.
    variants=[{'devices': ['^ATSAMRH707'], 'limits': {'hclk': {'max': 50 * MHZ}, 'mck': {'max': 25 * MHZ}}}])

GRAPHS = [SAM_X7, SAM_G5, SAM_C2X, SAM4_PMC, SAM4L, SAM_D1X, SAM_D20, SAM_L21, SAM_L22, SAM_D5X, SAM_RH]


def main():
    failed = False
    for item in GRAPHS:
        problems = check_graph(item)
        for problem in problems:
            print(f'{item["id"]}: {problem}')
        failed = failed or bool(problems)
        print(f'wrote {write_graph(item, f"microchip_sam/{item["id"]}.json").relative_to(REPO_ROOT)}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
