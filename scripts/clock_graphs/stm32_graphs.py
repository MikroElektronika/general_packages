"""Write the STM32 clock graphs (clock_graphs/stm32/*.json).

Hand-written from the STM32 reference manuals and datasheets; no STM32CubeMX data is used.
Register values are absolute bit values (see clock_graphs/README.md). Only the system clock
path is described (oscillators, PLL, SYSCLK, AHB and APB prescalers); peripheral kernel clock
muxes stay in the register view.

Run:  python scripts/clock_graphs/stm32_graphs.py
"""

from graphlib import REPO_ROOT, check_graph, hexv, write_graph

MHZ = 1000000

# AHB (HPRE) and APB (PPRE) prescaler encodings, identical across the STM32 families here.
AHB = [(1, 0), (2, 8), (4, 9), (8, 10), (16, 11), (64, 12), (128, 13), (256, 14), (512, 15)]
APB = [(1, 0), (2, 4), (4, 5), (8, 6), (16, 7)]


def option_id(factor):
    return str(factor).replace('.', '_')


def en(field, on, off=0, auto='both'):
    return {'field': field, 'on': hexv(on), 'off': hexv(off), 'auto': auto}


def fixed(node_id, label, x, y, hz, enable=None, tooltip=None):
    node = {'id': node_id, 'label': label, 'kind': 'source', 'x': x, 'y': y,
            'options': [{'id': 'on', 'label': label, 'mul': hz}]}
    if enable:
        node['enable'] = enable
    if tooltip:
        node['tooltip'] = tooltip
    return node


def external(node_id, label, x, y, enable, tooltip=None):
    node = {'id': node_id, 'label': label, 'kind': 'source', 'x': x, 'y': y, 'input': node_id, 'enable': enable}
    if tooltip:
        node['tooltip'] = tooltip
    return node


def mux(node_id, label, x, y, field, choices, **extra):
    """choices: (option id, label, source node, absolute value)."""
    return {'id': node_id, 'label': label, 'kind': 'mux', 'x': x, 'y': y,
            'options': [{'id': oid, 'label': text, 'from': source, 'set': {field: hexv(value)}}
                        for oid, text, source, value in choices], **extra}


def factors(node_id, label, x, y, source, field, lsb, pairs, op='div', extra_set=None, **extra):
    """pairs: (factor, raw field value). A '/1.5' factor is written mul 2 div 3."""
    options = []
    for factor, raw in pairs:
        option = {'id': option_id(factor), 'label': f'{"/" if op == "div" else "x"}{factor}', 'from': source,
                  'set': {field: hexv(raw << lsb)}}
        if extra_set:
            option['set'].update(extra_set(factor, raw))
        if op == 'div':
            if factor == 1.5:
                option.update(mul=2, div=3)
            else:
                option['div'] = factor
        else:
            if factor == 6.5:
                option.update(mul=13, div=2)
            else:
                option['mul'] = factor
        options.append(option)
    return {'id': node_id, 'label': label, 'kind': 'divider' if op == 'div' else 'multiplier', 'x': x, 'y': y,
            'options': options, **extra}


def span(node_id, label, x, y, source, field, lsb, low, high, op, scale=1, offset=0, **extra):
    return {'id': node_id, 'label': label, 'kind': 'divider' if op == 'div' else 'multiplier', 'x': x, 'y': y,
            'range': {'from': source, 'op': op, 'min': low, 'max': high, 'field': field, 'lsb': lsb,
                      'scale': scale, 'offset': offset}, **extra}


def fixed_div(node_id, label, x, y, source, div):
    return {'id': node_id, 'label': label, 'kind': 'divider', 'x': x, 'y': y,
            'options': [{'id': option_id(div), 'label': f'/{div}', 'from': source, 'div': div}]}


def ahb(node_id, label, x, y, source, field, lsb, maximum, **extra):
    return factors(node_id, label, x, y, source, field, lsb, AHB, max=maximum, consumer=True, **extra)


def apb(node_id, label, x, y, source, field, lsb, maximum, **extra):
    return factors(node_id, label, x, y, source, field, lsb, APB, max=maximum, consumer=True, **extra)


def limit(*pairs):
    return {node: {'max': value} for node, value in pairs}


def graph(graph_id, title, source, devices, fosc, inputs, nodes, settings=(), constraints=(), variants=(), derive=()):
    result = {
        'schema': 1, 'id': graph_id, 'title': title, 'vendor': 'STMicroelectronics', 'source': source,
        'devices': list(devices), 'fosc': fosc, 'inputs': inputs, 'settings': list(settings), 'nodes': nodes,
    }
    if derive:
        result['derive'] = list(derive)
    if constraints:
        result['constraints'] = list(constraints)
    if variants:
        result['variants'] = list(variants)
    return result


def hse_input(low, high, default=8 * MHZ):
    return {'hse': {'label': 'HSE frequency', 'default': default, 'min': low, 'max': high}}


def rule(expr, message):
    return {'expr': expr, 'message': message}


# ---------------------------------------------------------------------------------------------

def f2_f4_f7(graph_id, title, source, devices, sys_max, apb1_max, apb2_max, vco_min, variants):
    """F2/F4/F7: HSI 16 MHz, HSE, one main PLL (M, N, P, Q)."""
    nodes = [
        fixed('hsi', 'HSI 16 MHz', 0, 0, 16 * MHZ, en('RCC_CR.HSION', 1, auto='on')),
        external('hse', 'HSE', 0, 2, en('RCC_CR.HSEON', 1 << 16)),
        mux('pllsrc', 'PLL source', 1, 1, 'RCC_PLLCFGR.PLLSRC', [('hsi', 'HSI', 'hsi', 0), ('hse', 'HSE', 'hse', 1 << 22)]),
        span('pllm', '/M', 2, 1, 'pllsrc', 'RCC_PLLCFGR.PLLM', 0, 2, 63, 'div', min=950000, max=2100000,
             tooltip='VCO input: 0.95-2.1 MHz (2 MHz limits PLL jitter).'),
        span('plln', 'xN', 3, 1, 'pllm', 'RCC_PLLCFGR.PLLN', 6, 50, 432, 'mul', min=vco_min, max=432 * MHZ,
             enable=en('RCC_CR.PLLON', 1 << 24), tooltip='VCO output frequency.'),
        factors('pllp', '/P', 4, 1, 'plln', 'RCC_PLLCFGR.PLLP', 16, [(2, 0), (4, 1), (6, 2), (8, 3)], max=sys_max),
        span('pllq', '/Q', 4, 3, 'plln', 'RCC_PLLCFGR.PLLQ', 24, 2, 15, 'div', max=48 * MHZ,
             tooltip='PLL48CK: USB OTG FS, SDIO and RNG need 48 MHz.'),
        mux('sysclk', 'SYSCLK', 5, 0, 'RCC_CFGR.SW', [('hsi', 'HSI', 'hsi', 0), ('hse', 'HSE', 'hse', 1), ('pll', 'PLL', 'pllp', 2)],
            max=sys_max),
        ahb('hclk', 'HCLK (AHB)', 6, 0, 'sysclk', 'RCC_CFGR.HPRE', 4, sys_max),
        apb('pclk1', 'PCLK1 (APB1)', 7, 0, 'hclk', 'RCC_CFGR.PPRE1', 10, apb1_max),
        apb('pclk2', 'PCLK2 (APB2)', 7, 1, 'hclk', 'RCC_CFGR.PPRE2', 13, apb2_max),
    ]
    return graph(graph_id, title, source, devices, 'hclk', hse_input(4 * MHZ, 26 * MHZ), nodes,
                 settings=['RCC_CR.HSEBYP', 'SVRANGE.VRANGE'], variants=variants)


STM32F2 = f2_f4_f7('stm32f2', 'STM32F2 system clock tree', 'RM0033, DS6329', ['^STM32F2'],
                   120 * MHZ, 30 * MHZ, 60 * MHZ, 192 * MHZ, [])

STM32F4 = f2_f4_f7('stm32f4', 'STM32F4 system clock tree', 'RM0090, RM0368, RM0383, RM0390, RM0386, RM0401, RM0402, RM0430',
                   ['^STM32F4'], 180 * MHZ, 45 * MHZ, 90 * MHZ, 100 * MHZ, [
                       {'devices': ['^STM32F401'], 'limits': {**limit(('sysclk', 84 * MHZ), ('pllp', 84 * MHZ), ('hclk', 84 * MHZ),
                                                                      ('pclk1', 42 * MHZ), ('pclk2', 84 * MHZ)), 'plln': {'min': 192 * MHZ}}},
                       {'devices': ['^STM32F41[0-3]', '^STM32F423'],
                        'limits': limit(('sysclk', 100 * MHZ), ('pllp', 100 * MHZ), ('hclk', 100 * MHZ), ('pclk1', 50 * MHZ), ('pclk2', 100 * MHZ))},
                       {'devices': ['^STM32F4[01][57]'],
                        'limits': {**limit(('sysclk', 168 * MHZ), ('pllp', 168 * MHZ), ('hclk', 168 * MHZ), ('pclk1', 42 * MHZ), ('pclk2', 84 * MHZ)),
                                   'plln': {'min': 192 * MHZ}}},
                   ])

STM32F7 = f2_f4_f7('stm32f7', 'STM32F7 system clock tree', 'RM0385, RM0410, RM0431', ['^STM32F7'],
                   216 * MHZ, 54 * MHZ, 108 * MHZ, 100 * MHZ, [])


def f1_common_tail(pll_node, sys_max, apb1_max, adc_max):
    return [
        mux('sysclk', 'SYSCLK', 5, 0, 'RCC_CFGR.SW', [('hsi', 'HSI', 'hsi', 0), ('hse', 'HSE', 'hse', 1), ('pll', 'PLL', pll_node, 2)],
            max=sys_max),
        ahb('hclk', 'HCLK (AHB)', 6, 0, 'sysclk', 'RCC_CFGR.HPRE', 4, sys_max),
        apb('pclk1', 'PCLK1 (APB1)', 7, 0, 'hclk', 'RCC_CFGR.PPRE1', 8, apb1_max),
        apb('pclk2', 'PCLK2 (APB2)', 7, 1, 'hclk', 'RCC_CFGR.PPRE2', 11, sys_max),
        factors('adcclk', 'ADC prescaler', 8, 1, 'pclk2', 'RCC_CFGR.ADCPRE', 14, [(2, 0), (4, 1), (6, 2), (8, 3)], max=adc_max),
    ]


PLL_MUL_2_16 = [(n, n - 2) for n in range(2, 17)]

STM32F1 = graph(
    'stm32f1', 'STM32F101/F102/F103 system clock tree', 'RM0008, DS5319', ['^STM32F10[123]'], 'hclk',
    hse_input(4 * MHZ, 16 * MHZ),
    [
        fixed('hsi', 'HSI 8 MHz', 0, 0, 8 * MHZ, en('RCC_CR.HSION', 1, auto='on')),
        fixed_div('hsi_div2', 'HSI/2', 1, 0, 'hsi', 2),
        external('hse', 'HSE', 0, 2, en('RCC_CR.HSEON', 1 << 16)),
        factors('pllxtpre', 'HSE prescaler', 1, 2, 'hse', 'RCC_CFGR.PLLXTPRE', 17, [(1, 0), (2, 1)]),
        mux('pllsrc', 'PLL source', 2, 1, 'RCC_CFGR.PLLSRC', [('hsi2', 'HSI/2', 'hsi_div2', 0), ('hse', 'HSE', 'pllxtpre', 1 << 16)]),
        factors('pllmul', 'PLLMUL', 3, 1, 'pllsrc', 'RCC_CFGR.PLLMUL', 18, PLL_MUL_2_16, op='mul', max=72 * MHZ,
                enable=en('RCC_CR.PLLON', 1 << 24)),
        factors('usbclk', 'USB prescaler', 4, 3, 'pllmul', 'RCC_CFGR.USBPRE', 22, [(1.5, 0), (1, 1)], max=48 * MHZ,
                tooltip='USB needs exactly 48 MHz.'),
        *f1_common_tail('pllmul', 72 * MHZ, 36 * MHZ, 14 * MHZ),
    ],
    settings=['RCC_CR.HSEBYP'],
    constraints=[rule("sel.sysclk != 'pll' || f.pllmul >= 16000000", 'PLL output must be at least 16 MHz.')],
    variants=[
        {'devices': ['^STM32F101'], 'limits': limit(('sysclk', 36 * MHZ), ('pllmul', 36 * MHZ), ('hclk', 36 * MHZ), ('pclk2', 36 * MHZ))},
        {'devices': ['^STM32F102'], 'limits': limit(('sysclk', 48 * MHZ), ('pllmul', 48 * MHZ), ('hclk', 48 * MHZ), ('pclk2', 48 * MHZ),
                                                    ('pclk1', 24 * MHZ))},
    ])

STM32F100 = graph(
    'stm32f100', 'STM32F100 value line system clock tree', 'RM0041, DS6517', ['^STM32F100'], 'hclk',
    hse_input(4 * MHZ, 24 * MHZ),
    [
        fixed('hsi', 'HSI 8 MHz', 0, 0, 8 * MHZ, en('RCC_CR.HSION', 1, auto='on')),
        fixed_div('hsi_div2', 'HSI/2', 1, 0, 'hsi', 2),
        external('hse', 'HSE', 0, 2, en('RCC_CR.HSEON', 1 << 16)),
        span('prediv1', 'PREDIV1', 1, 2, 'hse', 'RCC_CFGR2.PREDIV1', 0, 1, 16, 'div', offset=-1),
        mux('pllsrc', 'PLL source', 2, 1, 'RCC_CFGR.PLLSRC', [('hsi2', 'HSI/2', 'hsi_div2', 0), ('prediv1', 'PREDIV1', 'prediv1', 1 << 16)]),
        factors('pllmul', 'PLLMUL', 3, 1, 'pllsrc', 'RCC_CFGR.PLLMUL', 18, PLL_MUL_2_16, op='mul', min=16 * MHZ, max=24 * MHZ,
                enable=en('RCC_CR.PLLON', 1 << 24)),
        *f1_common_tail('pllmul', 24 * MHZ, 24 * MHZ, 12 * MHZ),
    ],
    settings=['RCC_CR.HSEBYP'])

STM32F105_107 = graph(
    'stm32f105_107', 'STM32F105/F107 connectivity line system clock tree', 'RM0008, DS6014', ['^STM32F10[57]'], 'hclk',
    hse_input(3 * MHZ, 25 * MHZ, 25 * MHZ),
    [
        fixed('hsi', 'HSI 8 MHz', 0, 0, 8 * MHZ, en('RCC_CR.HSION', 1, auto='on')),
        fixed_div('hsi_div2', 'HSI/2', 2, 0, 'hsi', 2),
        external('hse', 'HSE', 0, 2, en('RCC_CR.HSEON', 1 << 16)),
        span('prediv2', 'PREDIV2', 1, 4, 'hse', 'RCC_CFGR2.PREDIV2', 4, 1, 16, 'div', offset=-1, min=3 * MHZ, max=5 * MHZ,
             tooltip='PLL2 input: 3-5 MHz.'),
        factors('pll2mul', 'PLL2MUL', 2, 4, 'prediv2', 'RCC_CFGR2.PLL2MUL', 8,
                [(8, 6), (9, 7), (10, 8), (11, 9), (12, 10), (13, 11), (14, 12), (16, 14), (20, 15)], op='mul',
                min=40 * MHZ, max=74 * MHZ, enable=en('RCC_CR.PLL2ON', 1 << 26)),
        mux('prediv1src', 'PREDIV1 source', 1, 2, 'RCC_CFGR2.PREDIV1SRC', [('hse', 'HSE', 'hse', 0), ('pll2', 'PLL2', 'pll2mul', 1 << 16)]),
        span('prediv1', 'PREDIV1', 2, 2, 'prediv1src', 'RCC_CFGR2.PREDIV1', 0, 1, 16, 'div', offset=-1),
        mux('pllsrc', 'PLL source', 3, 1, 'RCC_CFGR.PLLSRC', [('hsi2', 'HSI/2', 'hsi_div2', 0), ('prediv1', 'PREDIV1', 'prediv1', 1 << 16)],
            min=3 * MHZ, max=12 * MHZ, tooltip='PLL input: 3-12 MHz.'),
        factors('pllmul', 'PLLMUL', 4, 1, 'pllsrc', 'RCC_CFGR.PLLMUL', 18,
                [(4, 2), (5, 3), (6, 4), (6.5, 13), (7, 5), (8, 6), (9, 7)], op='mul', min=18 * MHZ, max=72 * MHZ,
                enable=en('RCC_CR.PLLON', 1 << 24)),
        factors('otgfsclk', 'USB OTG prescaler', 5, 3, 'pllmul', 'RCC_CFGR.OTGFSPRE', 22, [(1.5, 0), (1, 1)], max=48 * MHZ,
                tooltip='USB OTG FS needs exactly 48 MHz.'),
        *f1_common_tail('pllmul', 72 * MHZ, 36 * MHZ, 14 * MHZ),
    ],
    settings=['RCC_CR.HSEBYP'])


def predivided(source_field, choices, sys_max, apb1_max, prediv_field, pllxtpre=False, hsi48=False, pll_min=16 * MHZ):
    """F0/F3: PLLSRC chooses HSI/2 (no PREDIV) or a source divided by PREDIV."""
    mirror = (lambda factor, raw: {'RCC_CFGR.PLLXTPRE': hexv((raw & 1) << 17)}) if pllxtpre else None
    nodes = [
        fixed('hsi', 'HSI 8 MHz', 0, 0, 8 * MHZ, en('RCC_CR.HSION', 1, auto='on')),
        fixed_div('hsi_div2', 'HSI/2', 1, 0, 'hsi', 2),
        external('hse', 'HSE', 0, 2, en('RCC_CR.HSEON', 1 << 16)),
    ]
    if hsi48:
        nodes.append(fixed('hsi48', 'HSI48 48 MHz', 0, 4, 48 * MHZ, en('RCC_CR2.HSI48ON', 1 << 16)))
    nodes += [
        mux('pllsrc', 'PLL source', 2, 1, source_field, choices),
        factors('prediv', 'PREDIV', 3, 1, 'pllsrc', prediv_field, 0, [(n, n - 1) for n in range(1, 17)], extra_set=mirror,
                bypass="sel.pllsrc == 'hsi2'", tooltip='Not used with HSI/2.'),
        factors('pllmul', 'PLLMUL', 4, 1, 'prediv', 'RCC_CFGR.PLLMUL', 18, PLL_MUL_2_16, op='mul', min=pll_min, max=sys_max,
                enable=en('RCC_CR.PLLON', 1 << 24)),
    ]
    sys_choices = [('hsi', 'HSI', 'hsi', 0), ('hse', 'HSE', 'hse', 1), ('pll', 'PLL', 'pllmul', 2)]
    if hsi48:
        sys_choices.append(('hsi48', 'HSI48', 'hsi48', 3))
    nodes.append(mux('sysclk', 'SYSCLK', 5, 0, 'RCC_CFGR.SW', sys_choices, max=sys_max))
    nodes.append(ahb('hclk', 'HCLK (AHB)', 6, 0, 'sysclk', 'RCC_CFGR.HPRE', 4, sys_max))
    return nodes


STM32F0 = graph(
    'stm32f0', 'STM32F0 system clock tree', 'RM0360, RM0091, DS9773', ['^STM32F0'], 'hclk',
    hse_input(4 * MHZ, 32 * MHZ),
    [
        *predivided('RCC_CFGR.PLLSRC', [('hsi2', 'HSI/2', 'hsi_div2', 0), ('hsi', 'HSI', 'hsi', 1 << 15),
                                        ('hse', 'HSE', 'hse', 2 << 15), ('hsi48', 'HSI48', 'hsi48', 3 << 15)],
                    48 * MHZ, 48 * MHZ, 'RCC_CFGR2.PREDIV', hsi48=True),
        apb('pclk', 'PCLK (APB)', 7, 0, 'hclk', 'RCC_CFGR.PPRE', 8, 48 * MHZ),
    ],
    settings=['RCC_CR.HSEBYP'],
    constraints=[rule("sel.sysclk != 'pll' || (f.prediv >= 1000000 && f.prediv <= 24000000)", 'PLL input must be 1-24 MHz.')])

STM32F3 = graph(
    'stm32f3', 'STM32F3 system clock tree', 'RM0316, RM0313, RM0364, RM0365, RM0366', ['^STM32F3'], 'hclk',
    hse_input(4 * MHZ, 32 * MHZ),
    [
        *predivided('RCC_CFGR.PLLSRC', [('hsi2', 'HSI/2', 'hsi_div2', 0), ('hsi', 'HSI', 'hsi', 1 << 15), ('hse', 'HSE', 'hse', 2 << 15)],
                    72 * MHZ, 36 * MHZ, 'RCC_CFGR2.PREDIV|RCC_CFGR2.PREDIV1', pllxtpre=True),
        apb('pclk1', 'PCLK1 (APB1)', 7, 0, 'hclk', 'RCC_CFGR.PPRE1', 8, 36 * MHZ),
        apb('pclk2', 'PCLK2 (APB2)', 7, 1, 'hclk', 'RCC_CFGR.PPRE2', 11, 72 * MHZ),
        factors('usbclk', 'USB prescaler', 5, 3, 'pllmul', 'RCC_CFGR.USBPRE', 22, [(1.5, 0), (1, 1)], max=48 * MHZ,
                tooltip='USB needs exactly 48 MHz.'),
    ],
    settings=['RCC_CR.HSEBYP'],
    constraints=[rule("sel.sysclk != 'pll' || (f.prediv >= 1000000 && f.prediv <= 24000000)", 'PLL input must be 1-24 MHz.')])


HSIDIV = [(1 << n, n) for n in range(8)]

STM32C0 = graph(
    'stm32c0', 'STM32C0 system clock tree', 'RM0490, DS13866', ['^STM32C0'], 'hclk', hse_input(4 * MHZ, 48 * MHZ),
    [
        fixed('hsi48', 'HSI48 48 MHz', 0, 0, 48 * MHZ, en('RCC_CR.HSION', 1 << 8, auto='on')),
        factors('hsisys', 'HSIDIV', 1, 0, 'hsi48', 'RCC_CR.HSIDIV', 11, HSIDIV),
        external('hse', 'HSE', 0, 2, en('RCC_CR.HSEON', 1 << 16)),
        fixed('lsi', 'LSI 32 kHz', 0, 3, 32000, en('RCC_CSR2.LSION', 1)),
        fixed('lse', 'LSE 32.768 kHz', 0, 4, 32768, en('RCC_CSR1.LSEON', 1)),
        mux('sysclk', 'SYSCLK', 2, 0, 'RCC_CFGR.SW', [('hsisys', 'HSISYS', 'hsisys', 0), ('hse', 'HSE', 'hse', 1),
                                                     ('lsi', 'LSI', 'lsi', 3), ('lse', 'LSE', 'lse', 4)], max=48 * MHZ),
        ahb('hclk', 'HCLK (AHB)', 3, 0, 'sysclk', 'RCC_CFGR.HPRE', 8, 48 * MHZ),
        apb('pclk', 'PCLK (APB)', 4, 0, 'hclk', 'RCC_CFGR.PPRE', 12, 48 * MHZ),
    ],
    settings=['RCC_CR.HSEBYP'])

STM32G0 = graph(
    'stm32g0', 'STM32G0 system clock tree', 'RM0444, RM0454', ['^STM32G0'], 'hclk', hse_input(4 * MHZ, 48 * MHZ),
    [
        fixed('hsi16', 'HSI16 16 MHz', 0, 0, 16 * MHZ, en('RCC_CR.HSION', 1 << 8, auto='on')),
        factors('hsisys', 'HSIDIV', 1, 0, 'hsi16', 'RCC_CR.HSIDIV', 11, HSIDIV),
        external('hse', 'HSE', 0, 2, en('RCC_CR.HSEON', 1 << 16)),
        fixed('lsi', 'LSI 32 kHz', 0, 4, 32000, en('RCC_CSR.LSION', 1)),
        fixed('lse', 'LSE 32.768 kHz', 0, 5, 32768, en('RCC_BDCR.LSEON', 1)),
        mux('pllsrc', 'PLL source', 1, 2, 'RCC_PLLSYSCFGR.PLLSRC', [('hsi16', 'HSI16', 'hsi16', 2), ('hse', 'HSE', 'hse', 3)]),
        factors('pllm', '/M', 2, 2, 'pllsrc', 'RCC_PLLSYSCFGR.PLLM', 4, [(n, n - 1) for n in range(1, 9)], min=2660000, max=16 * MHZ,
                tooltip='VCO input: 2.66-16 MHz.'),
        span('plln', 'xN', 3, 2, 'pllm', 'RCC_PLLSYSCFGR.PLLN', 8, 8, 86, 'mul', min=64 * MHZ, max=344 * MHZ,
             enable=en('RCC_CR.PLLON', 1 << 24)),
        factors('pllr', '/R', 4, 2, 'plln', 'RCC_PLLSYSCFGR.PLLR', 29, [(n, n - 1) for n in range(2, 9)], max=64 * MHZ,
                enable=en('RCC_PLLSYSCFGR.PLLREN', 1 << 28)),
        mux('sysclk', 'SYSCLK', 5, 0, 'RCC_CFGR.SW', [('hsisys', 'HSISYS', 'hsisys', 0), ('hse', 'HSE', 'hse', 1), ('pll', 'PLLRCLK', 'pllr', 2),
                                                     ('lsi', 'LSI', 'lsi', 3), ('lse', 'LSE', 'lse', 4)], max=64 * MHZ),
        ahb('hclk', 'HCLK (AHB)', 6, 0, 'sysclk', 'RCC_CFGR.HPRE', 8, 64 * MHZ),
        apb('pclk', 'PCLK (APB)', 7, 0, 'hclk', 'RCC_CFGR.PPRE', 12, 64 * MHZ),
    ],
    settings=['RCC_CR.HSEBYP', 'PWR_CR1.VCORE'],
    constraints=[rule('reg("PWR_CR1.VCORE") != 0x400 || f.sysclk <= 16000000', 'Voltage range 2 limits SYSCLK to 16 MHz.')])

STM32G4 = graph(
    'stm32g4', 'STM32G4 system clock tree', 'RM0440, DS12288', ['^STM32G4'], 'hclk', hse_input(4 * MHZ, 48 * MHZ),
    [
        fixed('hsi16', 'HSI16 16 MHz', 0, 0, 16 * MHZ, en('RCC_CR.HSION', 1 << 8, auto='on')),
        external('hse', 'HSE', 0, 2, en('RCC_CR.HSEON', 1 << 16)),
        mux('pllsrc', 'PLL source', 1, 1, 'RCC_PLLCFGR.PLLSRC', [('hsi16', 'HSI16', 'hsi16', 2), ('hse', 'HSE', 'hse', 3)]),
        factors('pllm', '/M', 2, 1, 'pllsrc', 'RCC_PLLCFGR.PLLM', 4, [(n, n - 1) for n in range(1, 17)], min=2660000, max=16 * MHZ,
                tooltip='VCO input: 2.66-16 MHz.'),
        span('plln', 'xN', 3, 1, 'pllm', 'RCC_PLLCFGR.PLLN', 8, 8, 127, 'mul', min=96 * MHZ, max=344 * MHZ,
             enable=en('RCC_CR.PLLON', 1 << 24)),
        factors('pllr', '/R', 4, 1, 'plln', 'RCC_PLLCFGR.PLLR', 25, [(2, 0), (4, 1), (6, 2), (8, 3)], max=170 * MHZ,
                enable=en('RCC_PLLCFGR.PLLREN', 1 << 24)),
        mux('sysclk', 'SYSCLK', 5, 0, 'RCC_CFGR.SW', [('hsi16', 'HSI16', 'hsi16', 1), ('hse', 'HSE', 'hse', 2), ('pll', 'PLL', 'pllr', 3)],
            max=170 * MHZ, tooltip='Above 150 MHz the core runs in range 1 boost mode.'),
        ahb('hclk', 'HCLK (AHB)', 6, 0, 'sysclk', 'RCC_CFGR.HPRE', 4, 170 * MHZ),
        apb('pclk1', 'PCLK1 (APB1)', 7, 0, 'hclk', 'RCC_CFGR.PPRE1', 8, 170 * MHZ),
        apb('pclk2', 'PCLK2 (APB2)', 7, 1, 'hclk', 'RCC_CFGR.PPRE2', 11, 170 * MHZ),
    ],
    settings=['RCC_CR.HSEBYP'])

MSI_RANGES = [100000, 200000, 400000, 800000, 1 * MHZ, 2 * MHZ, 4 * MHZ, 8 * MHZ, 16 * MHZ, 24 * MHZ, 32 * MHZ, 48 * MHZ]


def msi_label(hz):
    return f'MSI {hz // 1000} kHz' if hz < MHZ else f'MSI {hz // MHZ} MHz'


STM32L4 = graph(
    'stm32l4', 'STM32L4/L4+ system clock tree', 'RM0394, RM0351, RM0432', ['^STM32L4'], 'hclk', hse_input(4 * MHZ, 48 * MHZ),
    [
        {'id': 'msi', 'label': 'MSI', 'kind': 'source', 'x': 0, 'y': 0, 'enable': en('RCC_CR.MSION', 1, auto='on'),
         'options': [{'id': str(index), 'label': msi_label(hz), 'mul': hz,
                      'set': {'RCC_CR.MSIRANGE': hexv(index << 4), 'RCC_CR.MSIRGSEL': hexv(1 << 3)}}
                     for index, hz in enumerate(MSI_RANGES)]},
        fixed('hsi16', 'HSI16 16 MHz', 0, 2, 16 * MHZ, en('RCC_CR.HSION', 1 << 8)),
        external('hse', 'HSE', 0, 3, en('RCC_CR.HSEON', 1 << 16)),
        mux('pllsrc', 'PLL source', 1, 2, 'RCC_PLLCFGR.PLLSRC', [('msi', 'MSI', 'msi', 1), ('hsi16', 'HSI16', 'hsi16', 2), ('hse', 'HSE', 'hse', 3)]),
        factors('pllm', '/M', 2, 2, 'pllsrc', 'RCC_PLLCFGR.PLLM', 4, [(n, n - 1) for n in range(1, 17)], min=4 * MHZ, max=16 * MHZ,
                tooltip='VCO input: 4-16 MHz (2.66-16 MHz on L4+).'),
        span('plln', 'xN', 3, 2, 'pllm', 'RCC_PLLCFGR.PLLN', 8, 8, 127, 'mul', min=64 * MHZ, max=344 * MHZ,
             enable=en('RCC_CR.PLLON', 1 << 24)),
        factors('pllr', '/R', 4, 2, 'plln', 'RCC_PLLCFGR.PLLR', 25, [(2, 0), (4, 1), (6, 2), (8, 3)], max=80 * MHZ,
                enable=en('RCC_PLLCFGR.PLLREN', 1 << 24)),
        mux('sysclk', 'SYSCLK', 5, 0, 'RCC_CFGR.SW', [('msi', 'MSI', 'msi', 0), ('hsi16', 'HSI16', 'hsi16', 1), ('hse', 'HSE', 'hse', 2),
                                                     ('pll', 'PLL', 'pllr', 3)], max=80 * MHZ),
        ahb('hclk', 'HCLK (AHB)', 6, 0, 'sysclk', 'RCC_CFGR.HPRE', 4, 80 * MHZ),
        apb('pclk1', 'PCLK1 (APB1)', 7, 0, 'hclk', 'RCC_CFGR.PPRE1', 8, 80 * MHZ),
        apb('pclk2', 'PCLK2 (APB2)', 7, 1, 'hclk', 'RCC_CFGR.PPRE2', 11, 80 * MHZ),
    ],
    settings=['RCC_CR.HSEBYP', 'PWR_CR1.VCORE'],
    constraints=[rule('reg("PWR_CR1.VCORE") != 0x400 || f.sysclk <= 26000000', 'Voltage range 2 limits SYSCLK to 26 MHz.')],
    variants=[{'devices': ['^STM32L4[RSPQ]'],
               'limits': {**limit(('pllr', 120 * MHZ), ('sysclk', 120 * MHZ), ('hclk', 120 * MHZ), ('pclk1', 120 * MHZ), ('pclk2', 120 * MHZ)),
                          'pllm': {'min': 2660000}}}])


def l0_l1(graph_id, title, source, devices, hsi_enable, hsi_divider, hse_max, vcore_field, vcore_limits):
    nodes = [
        fixed('msi', 'MSI 2.097 MHz', 0, 0, 2097000, en('RCC_CR.MSION', 1 << 8, auto='on'),
              tooltip='MSI range 5 (reset value); other MSI ranges are set in RCC_ICSCR.'),
        fixed('hsi16', 'HSI16 16 MHz', 0, 1, 16 * MHZ, hsi_enable),
    ]
    hsi_out = 'hsi16'
    if hsi_divider:
        nodes.append({'id': 'hsi16div', 'label': 'HSI16 divider', 'kind': 'divider', 'x': 1, 'y': 1,
                      'options': [{'id': '1', 'label': '/1', 'from': 'hsi16', 'set': {'RCC_CR.HSI16DIVEN': hexv(0)}},
                                  {'id': '4', 'label': '/4', 'from': 'hsi16', 'div': 4, 'set': {'RCC_CR.HSI16DIVEN': hexv(1 << 3)}}]})
        hsi_out = 'hsi16div'
    nodes += [
        external('hse', 'HSE', 0, 3, en('RCC_CR.HSEON', 1 << 16)),
        mux('pllsrc', 'PLL source', 2, 2, 'RCC_CFGR.PLLSRC', [('hsi16', 'HSI16', hsi_out, 0), ('hse', 'HSE', 'hse', 1 << 16)],
            min=2 * MHZ, max=24 * MHZ, tooltip='PLL input: 2-24 MHz.'),
        factors('pllmul', 'PLLMUL', 3, 2, 'pllsrc', 'RCC_CFGR.PLLMUL', 18,
                [(3, 0), (4, 1), (6, 2), (8, 3), (12, 4), (16, 5), (24, 6), (32, 7), (48, 8)], op='mul', max=96 * MHZ,
                enable=en('RCC_CR.PLLON', 1 << 24), tooltip='PLLVCO: at most 96 MHz (48 MHz in range 2, 24 MHz in range 3).'),
        factors('plldiv', 'PLLDIV', 4, 2, 'pllmul', 'RCC_CFGR.PLLDIV', 22, [(2, 1), (3, 2), (4, 3)], max=32 * MHZ),
        mux('sysclk', 'SYSCLK', 5, 0, 'RCC_CFGR.SW', [('msi', 'MSI', 'msi', 0), ('hsi16', 'HSI16', hsi_out, 1), ('hse', 'HSE', 'hse', 2),
                                                     ('pll', 'PLL', 'plldiv', 3)], max=32 * MHZ),
        ahb('hclk', 'HCLK (AHB)', 6, 0, 'sysclk', 'RCC_CFGR.HPRE', 4, 32 * MHZ),
        apb('pclk1', 'PCLK1 (APB1)', 7, 0, 'hclk', 'RCC_CFGR.PPRE1', 8, 32 * MHZ),
        apb('pclk2', 'PCLK2 (APB2)', 7, 1, 'hclk', 'RCC_CFGR.PPRE2', 11, 32 * MHZ),
    ]
    constraints = []
    for value, sys_max, vco_max, name in vcore_limits:
        constraints.append(rule(f'reg("{vcore_field}") != {value} || (f.sysclk <= {sys_max} && (sel.sysclk != \'pll\' || f.pllmul <= {vco_max}))',
                                f'{name} limits SYSCLK to {sys_max / MHZ:g} MHz and PLLVCO to {vco_max / MHZ:g} MHz.'))
    return graph(graph_id, title, source, devices, 'hclk', hse_input(1 * MHZ, hse_max), nodes,
                 settings=['RCC_CR.HSEBYP', vcore_field], constraints=constraints)


STM32L0 = l0_l1('stm32l0', 'STM32L0 system clock tree', 'RM0451, RM0377, RM0367, RM0376', ['^STM32L0'],
                en('RCC_CR.HSI16ON', 1), True, 32 * MHZ, 'PWR_CR.VCORE',
                [(0x1000, 16 * MHZ, 48 * MHZ, 'Range 2 (1.5 V)'), (0x1800, 4200000, 24 * MHZ, 'Range 3 (1.2 V)')])

STM32L1 = l0_l1('stm32l1', 'STM32L1 system clock tree', 'RM0038', ['^STM32L1'],
                en('RCC_CR.HSION', 1), False, 24 * MHZ, 'SVCORE.VCORE',
                [(1, 16 * MHZ, 48 * MHZ, 'Range 2 (1.5 V)'), (0, 4200000, 24 * MHZ, 'Range 3 (1.2 V)')])

DIVP1 = [(n, n - 1) for n in range(2, 129, 2)]

STM32H7 = graph(
    'stm32h7', 'STM32H742/H743/H750/H753 system clock tree', 'RM0433, DS12110', ['^STM32H7(4[23]|5[03])'], 'sysclk',
    hse_input(4 * MHZ, 48 * MHZ, 25 * MHZ),
    [
        fixed('hsi', 'HSI 64 MHz', 0, 0, 64 * MHZ, en('RCC_CR.HSION', 1, auto='on')),
        factors('hsidiv', 'HSIDIV', 1, 0, 'hsi', 'RCC_CR.HSIDIV', 3, [(1, 0), (2, 1), (4, 2), (8, 3)]),
        fixed('csi', 'CSI 4 MHz', 0, 1, 4 * MHZ, en('RCC_CR.CSION', 1 << 7)),
        external('hse', 'HSE', 0, 2, en('RCC_CR.HSEON', 1 << 16)),
        mux('pllsrc', 'PLL source', 2, 1, 'RCC_PLLCKSELR.PLLSRC', [('hsi', 'HSI', 'hsidiv', 0), ('csi', 'CSI', 'csi', 1), ('hse', 'HSE', 'hse', 2)]),
        span('divm1', '/M1', 3, 1, 'pllsrc', 'RCC_PLLCKSELR.DIVM1', 4, 1, 63, 'div', min=1 * MHZ, max=16 * MHZ,
             tooltip='PLL1 input: 1-16 MHz. PLL1RGE and PLL1VCOSEL follow it automatically.'),
        span('divn1', 'xN1', 4, 1, 'divm1', 'RCC_PLL1DIVR.DIVN1', 0, 4, 512, 'mul', offset=-1, min=150 * MHZ, max=960 * MHZ,
             enable=en('RCC_CR.PLL1ON', 1 << 24)),
        factors('divp1', '/P1', 5, 1, 'divn1', 'RCC_PLL1DIVR.DIVP1', 9, DIVP1, max=480 * MHZ, enable=en('RCC_PLLCFGR.DIVP1EN', 1 << 16)),
        mux('sysclk', 'SYSCLK', 6, 0, 'RCC_CFGR.SW', [('hsi', 'HSI', 'hsidiv', 0), ('csi', 'CSI', 'csi', 1), ('hse', 'HSE', 'hse', 2),
                                                     ('pll1', 'PLL1 P', 'divp1', 3)], max=480 * MHZ),
        ahb('cpuclk', 'CPU clock (D1CPRE)', 7, 0, 'sysclk', 'RCC_D1CFGR.D1CPRE', 8, 480 * MHZ),
        ahb('hclk', 'HCLK (HPRE)', 8, 0, 'cpuclk', 'RCC_D1CFGR.HPRE', 0, 240 * MHZ),
        apb('pclk3', 'PCLK3 (D1PPRE)', 9, 0, 'hclk', 'RCC_D1CFGR.D1PPRE', 4, 120 * MHZ),
        apb('pclk1', 'PCLK1 (D2PPRE1)', 9, 1, 'hclk', 'RCC_D2CFGR.D2PPRE1', 4, 120 * MHZ),
        apb('pclk2', 'PCLK2 (D2PPRE2)', 9, 2, 'hclk', 'RCC_D2CFGR.D2PPRE2', 8, 120 * MHZ),
        apb('pclk4', 'PCLK4 (D3PPRE)', 9, 3, 'hclk', 'RCC_D3CFGR.D3PPRE', 4, 120 * MHZ),
    ],
    settings=['RCC_CR.HSEBYP', 'PWR_D3CR.VRANGE'],
    derive=[
        {'field': 'RCC_PLLCFGR.PLL1RGE', 'cases': [{'when': 'f.divm1 < 2000000', 'value': hexv(0)},
                                                   {'when': 'f.divm1 < 4000000', 'value': hexv(1 << 2)},
                                                   {'when': 'f.divm1 < 8000000', 'value': hexv(2 << 2)}],
         'default': hexv(3 << 2)},
        {'field': 'RCC_PLLCFGR.PLL1VCOSEL', 'cases': [{'when': 'f.divm1 < 2000000', 'value': hexv(1 << 1)}], 'default': hexv(0)},
    ],
    constraints=[
        rule("sel.sysclk != 'pll1' || f.divm1 < 2000000 || f.divn1 >= 192000000",
             'Wide VCO range (PLL1 input >= 2 MHz) needs 192-960 MHz.'),
        rule("sel.sysclk != 'pll1' || f.divm1 >= 2000000 || f.divn1 <= 420000000",
             'Medium VCO range (PLL1 input < 2 MHz) needs 150-420 MHz.'),
        rule('reg("PWR_D3CR.VRANGE") != 0xC000 || (f.cpuclk <= 400000000 && f.hclk <= 200000000 && f.pclk1 <= 100000000 && f.pclk2 <= 100000000 && f.pclk3 <= 100000000 && f.pclk4 <= 100000000)',
             'VOS1 limits the CPU to 400 MHz, HCLK to 200 MHz and the APB clocks to 100 MHz.'),
        rule('reg("PWR_D3CR.VRANGE") != 0x8000 || (f.cpuclk <= 300000000 && f.hclk <= 150000000 && f.pclk1 <= 75000000 && f.pclk2 <= 75000000 && f.pclk3 <= 75000000 && f.pclk4 <= 75000000)',
             'VOS2 limits the CPU to 300 MHz, HCLK to 150 MHz and the APB clocks to 75 MHz.'),
        rule('reg("PWR_D3CR.VRANGE") != 0x4000 || (f.cpuclk <= 200000000 && f.hclk <= 100000000 && f.pclk1 <= 50000000 && f.pclk2 <= 50000000 && f.pclk3 <= 50000000 && f.pclk4 <= 50000000)',
             'VOS3 limits the CPU to 200 MHz, HCLK to 100 MHz and the APB clocks to 50 MHz.'),
    ])

GRAPHS = [STM32C0, STM32F0, STM32F1, STM32F100, STM32F105_107, STM32F2, STM32F3, STM32F4, STM32F7,
          STM32G0, STM32G4, STM32H7, STM32L0, STM32L1, STM32L4]


def main():
    failed = False
    for item in GRAPHS:
        problems = check_graph(item)
        for problem in problems:
            print(f'{item["id"]}: {problem}')
        failed = failed or bool(problems)
        print(f'wrote {write_graph(item, f"stm32/{item["id"]}.json").relative_to(REPO_ROOT)}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
