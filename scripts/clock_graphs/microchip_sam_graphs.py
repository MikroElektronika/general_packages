"""Write the Microchip SAM clock graphs (clock_graphs/microchip_sam/*.json).

Hand-written from the SAM E70/S70/V70/V71 and SAM G5x datasheets (PMC chapter). Only families
whose NECTO definitions carry the PMC registers and whose core systemInit applies them are
described: SAM E70/S70/V70/V71 and SAM G53/G54/G55. Register values are absolute bit values
(see clock_graphs/README.md).

Run:  python scripts/clock_graphs/microchip_sam_graphs.py
"""

from graphlib import REPO_ROOT, check_graph, hexv, write_graph
from stm32_graphs import MHZ, en, external, factors, fixed, graph, mux, rule, span

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
    'sam_g5x', 'SAM G53/G54/G55 clock tree', 'SAM G53/G54/G55 datasheets, PMC', ['^ATSAMG5[345]'], 'hclk', xtal_input(12 * MHZ),
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
        {'devices': ['^ATSAMG53'], 'limits': {'plla': {'max': 48 * MHZ}, 'hclk': {'max': 48 * MHZ}}},
        {'devices': ['^ATSAMG54'], 'limits': {'plla': {'max': 96 * MHZ}, 'hclk': {'max': 96 * MHZ}}},
    ])

LOG2 = [(1 << n, n) for n in range(8)]

# SAM D21/DA1 (Atmel START system code): oscillators and DFLL48M (open loop on the factory
# calibration) feed generic clock generator 0, which clocks the CPU (CPUDIV) and the APB buses.
# FDPLL96M is left out: the definitions' DPLLRATIO.LDR and DPLLCTRLB.DIV masks do not match the
# hardware. Flash wait states follow the CPU clock (1 above 24 MHz).
SAM_D21 = sam(
    'sam_d21_da1', 'SAM D21/DA1 clock tree', 'SAM D21/DA1 datasheet DS40001882, SYSCTRL/GCLK/PM', ['^ATSAM(D21|DA1)'], 'cpu',
    {'xosc': {'label': 'XOSC frequency', 'default': 16 * MHZ, 'min': 400000, 'max': 32 * MHZ}},
    [
        fixed('osc8m', 'OSC8M 8 MHz', 0, 0, 8 * MHZ, en('OSC8M.ENABLE', 1 << 1, auto='on')),
        factors('osc8m_presc', 'OSC8M prescaler', 1, 0, 'osc8m', 'OSC8M.PRESC', 8, [(1, 0), (2, 1), (4, 2), (8, 3)]),
        external('xosc', 'XOSC', 0, 1, en('XOSC.ENABLE', 1 << 1), tooltip='External crystal or clock, 0.4-32 MHz.'),
        fixed('xosc32k', 'XOSC32K 32.768 kHz', 0, 2, 32768, en('XOSC32K.ENABLE', 1 << 1)),
        fixed('osc32k', 'OSC32K 32.768 kHz', 0, 3, 32768, en('OSC32K.ENABLE', 1 << 1)),
        fixed('osculp32k', 'OSCULP32K 32.768 kHz', 0, 4, 32768),
        fixed('dfll48m', 'DFLL48M 48 MHz', 1, 5, 48 * MHZ, en('DFLLCTRL.ENABLE', 1 << 1),
              tooltip='Open loop on the factory calibration (DFLLVAL 0). Closed-loop operation is set in the register view.'),
        mux('gclk0', 'GCLK0 source', 2, 2, 'GENCTRL0.SRC', [('osc8m', 'OSC8M', 'osc8m_presc', 6 << 8), ('xosc', 'XOSC', 'xosc', 0),
                                                         ('xosc32k', 'XOSC32K', 'xosc32k', 5 << 8), ('osc32k', 'OSC32K', 'osc32k', 4 << 8),
                                                         ('osculp32k', 'OSCULP32K', 'osculp32k', 3 << 8), ('dfll48m', 'DFLL48M', 'dfll48m', 7 << 8)]),
        factors('cpu', 'CPU (CPUDIV)', 3, 1, 'gclk0', 'CPUSEL.CPUDIV', 0, LOG2, max=48 * MHZ, consumer=True),
        factors('apba', 'APBA (APBADIV)', 4, 1, 'cpu', 'APBASEL.APBADIV', 0, LOG2, max=48 * MHZ, consumer=True),
        factors('apbb', 'APBB (APBBDIV)', 4, 2, 'cpu', 'APBBSEL.APBBDIV', 0, LOG2, max=48 * MHZ, consumer=True),
        factors('apbc', 'APBC (APBCDIV)', 4, 3, 'cpu', 'APBCSEL.APBCDIV', 0, LOG2, max=48 * MHZ, consumer=True),
    ],
    settings=['XOSC.XTALEN', 'XOSC32K.XTALEN', 'DFLLCTRL.MODE'],
    derive=[
        {'field': 'NVMCTRL_CTRLB.RWS', 'cases': [{'when': 'f.cpu <= 24000000', 'value': hexv(0)}], 'default': hexv(1 << 1)},
        {'field': 'XOSC.GAIN', 'cases': [{'when': f'in.xosc <= {limit}', 'value': hexv(code << 8)}
                                         for code, limit in enumerate([2 * MHZ, 4 * MHZ, 8 * MHZ, 16 * MHZ])],
         'default': hexv(4 << 8)},
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

GRAPHS = [SAM_X7, SAM_G5, SAM_D21, SAM_C2X]


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
