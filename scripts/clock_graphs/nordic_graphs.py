"""Write the Nordic Semiconductor clock graphs (clock_graphs/nordic/*.json).

Hand-written from the nRF51, nRF52, nRF5340, nRF91 and nRF54L product specifications (CLOCK and
OSCILLATORS chapters) for the CLOCK/OSCILLATORS fields the NECTO definitions expose and the core
SystemInit (core_packages ARM/gcc_clang/system/src/nordic/<series>/init_clock.c) applies.
Register addresses and reset values were checked against the Nordic MDK (nrfx bsp/stable/mdk).

Nordic CPUs run from a fixed-frequency HFCLK: the choices are the HFCLK reference (internal HFINT or
the HFXO crystal, started by a task), the CPU divider on nRF5340/nRF54L, and the LFCLK source.
A "TASKS_*" register field set to 1 means SystemInit triggers that task. FOSC_KHZ_VALUE is the CPU clock.
Register values are absolute bit values (see clock_graphs/README.md).

Run:  python scripts/clock_graphs/nordic_graphs.py
"""

from graphlib import REPO_ROOT, check_graph, hexv, write_graph
from stm32_graphs import MHZ, factors, fixed, graph

LF = 32768


def hf_mux(node_id, label, x, y, task_field, choices, **extra):
    """choices: (option id, label, source node, mul, div, extra set). task_field is 1 for the crystal options."""
    options = []
    for oid, text, source, mul, div, extra_set in choices:
        option = {'id': oid, 'label': text, 'from': source,
                  'set': {task_field: hexv(0 if oid == 'hfint' else 1), **extra_set}}
        if mul != 1:
            option['mul'] = mul
        if div != 1:
            option['div'] = div
        options.append(option)
    return {'id': node_id, 'label': label, 'kind': 'mux', 'x': x, 'y': y, 'options': options, **extra}


def lf_mux(field, choices, synth_from, synth_mul, synth_div, synth_value=None):
    """LFCLK source. choices: (option id, label, source node, field value)."""
    options = [{'id': oid, 'label': text, 'from': source, 'set': {field: hexv(value)}} for oid, text, source, value in choices]
    if synth_value is not None:
        options.append({'id': 'synth', 'label': 'Synthesized from HFCLK', 'from': synth_from, 'mul': synth_mul, 'div': synth_div,
                        'set': {field: hexv(synth_value)}})
    return {'id': 'lfclk', 'label': 'LFCLK (32.768 kHz)', 'kind': 'mux', 'x': 2, 'y': 3, 'options': options,
            'tooltip': 'Low frequency clock for RTC, WDT and timers. It runs only when "Start LFCLK in SystemInit" is chosen; '
                       'the synthesized source is only as accurate as HFCLK, so start the HFXO with it.'}


def lf_sources():
    return [fixed('lfrc', 'LFRC 32.768 kHz RC', 0, 3, LF),
            fixed('lfxo', 'LFXO 32.768 kHz crystal', 0, 4, LF, tooltip='External 32.768 kHz crystal on XL1/XL2.')]


def nordic(graph_id, title, source, devices, fosc, nodes, settings, constraints=()):
    result = graph(graph_id, title, source, devices, fosc, {}, nodes, settings=settings, constraints=constraints)
    result['vendor'] = 'Nordic Semiconductor'
    return result


LF_START = 'CLOCK_TASKS_LFCLKSTART.TASKS_LFCLKSTART'

# nRF51: 16 MHz CPU from the 16 MHz RC or a 16/32 MHz crystal (XTALFREQ tells the HFXO which one is fitted).
NRF51 = nordic(
    'nrf51', 'nRF51 clock tree', 'nRF51 Series Reference Manual v3.0, CLOCK', ['^NRF51'], 'hfclk',
    [
        fixed('hfint', 'HFINT 16 MHz RC', 0, 0, 16 * MHZ),
        fixed('hfxo16', 'HFXO 16 MHz crystal', 0, 1, 16 * MHZ),
        fixed('hfxo32', 'HFXO 32 MHz crystal', 0, 2, 32 * MHZ),
        hf_mux('hfclk', 'HFCLK (CPU 16 MHz)', 1, 0, 'CLOCK_TASKS_HFCLKSTART.TASKS_HFCLKSTART', [
            ('hfint', 'HFINT RC oscillator', 'hfint', 1, 1, {}),
            ('hfxo16', 'HFXO 16 MHz crystal', 'hfxo16', 1, 1, {'CLOCK_XTALFREQ.XTALFREQ': hexv(0xFF)}),
            ('hfxo32', 'HFXO 32 MHz crystal / 2', 'hfxo32', 1, 2, {'CLOCK_XTALFREQ.XTALFREQ': hexv(0x00)}),
        ], consumer=True, max=16 * MHZ,
            tooltip='The CPU always runs at 16 MHz; the crystal makes HFCLK accurate (needed by the radio).'),
        *lf_sources(),
        lf_mux('CLOCK_LFCLKSRC.SRC', [('lfrc', 'LFRC', 'lfrc', 0), ('lfxo', 'LFXO', 'lfxo', 1)], 'hfclk', 256, 125000, 2),
    ],
    [LF_START])

# nRF52: 64 MHz CPU from HFINT or the 32 MHz HFXO (PLL x2).
NRF52 = nordic(
    'nrf52', 'nRF52 clock tree', 'nRF52805/810/811/820/832/833/840 product specifications, CLOCK', ['^NRF528'], 'hfclk',
    [
        fixed('hfint', 'HFINT 64 MHz RC', 0, 0, 64 * MHZ),
        fixed('hfxo', 'HFXO 32 MHz crystal', 0, 1, 32 * MHZ),
        hf_mux('hfclk', 'HFCLK (CPU 64 MHz)', 1, 0, 'CLOCK_TASKS_HFCLKSTART.TASKS_HFCLKSTART', [
            ('hfint', 'HFINT RC oscillator', 'hfint', 1, 1, {}),
            ('hfxo', 'HFXO crystal (x2)', 'hfxo', 2, 1, {}),
        ], consumer=True, max=64 * MHZ,
            tooltip='The CPU always runs at 64 MHz; the crystal makes HFCLK accurate (needed by the radio and USB).'),
        *lf_sources(),
        lf_mux('CLOCK_LFCLKSRC.SRC', [('lfrc', 'LFRC', 'lfrc', 0), ('lfxo', 'LFXO', 'lfxo', 1)], 'hfclk', 8, 15625, 2),
    ],
    [LF_START, 'CLOCK_LFCLKSRC.BYPASS', 'CLOCK_LFCLKSRC.EXTERNAL'])

# nRF5340 application core: HFCLK128M from HFINT or HFXO, HCLK = /1 (128 MHz) or /2 (64 MHz).
NRF53 = nordic(
    'nrf53', 'nRF5340 application core clock tree', 'nRF5340 product specification, CLOCK (application core)', ['^NRF5340'], 'hclk',
    [
        fixed('hfint', 'HFINT 128 MHz', 0, 0, 128 * MHZ),
        fixed('hfxo', 'HFXO 32 MHz crystal', 0, 1, 32 * MHZ),
        hf_mux('hfclk128m', 'HFCLK128M (HFCLKSRC)', 1, 0, 'CLOCK_TASKS_HFCLKSTART.TASKS_HFCLKSTART', [
            ('hfint', 'HFINT RC oscillator', 'hfint', 1, 1, {'CLOCK_HFCLKSRC.SRC': hexv(0)}),
            ('hfxo', 'HFXO crystal (x4)', 'hfxo', 4, 1, {'CLOCK_HFCLKSRC.SRC': hexv(1)}),
        ]),
        factors('hclk', 'HCLK (HFCLKCTRL)', 2, 0, 'hfclk128m', 'CLOCK_HFCLKCTRL.HCLK', 0, [(1, 0), (2, 1)],
                consumer=True, max=128 * MHZ),
        *lf_sources(),
        lf_mux('CLOCK_LFCLKSRC.SRC', [('lfrc', 'LFRC', 'lfrc', 1), ('lfxo', 'LFXO (P0.00/P0.01)', 'lfxo', 2)], 'hfclk128m', 4, 15625, 3),
    ],
    [LF_START])

# nRF91 application core: 64 MHz CPU from HFINT or the HFXO.
NRF91 = nordic(
    'nrf91', 'nRF91 application core clock tree', 'nRF9160/nRF9161/nRF9151 product specifications, CLOCK', ['^NRF91'], 'hfclk',
    [
        fixed('hfint', 'HFINT 64 MHz RC', 0, 0, 64 * MHZ),
        fixed('hfxo', 'HFXO 32 MHz crystal', 0, 1, 32 * MHZ),
        hf_mux('hfclk', 'HFCLK (CPU 64 MHz)', 1, 0, 'CLOCK_TASKS_HFCLKSTART.TASKS_HFCLKSTART', [
            ('hfint', 'HFINT RC oscillator', 'hfint', 1, 1, {}),
            ('hfxo', 'HFXO crystal (x2)', 'hfxo', 2, 1, {}),
        ], consumer=True, max=64 * MHZ),
        *lf_sources(),
        lf_mux('CLOCK_LFCLKSRC.SRC', [('lfrc', 'LFRC', 'lfrc', 1), ('lfxo', 'LFXO', 'lfxo', 2)], None, 1, 1),
    ],
    [LF_START])

# nRF54L: PLL (128 MHz) referenced to HFINT or the HFXO, CPU = PLL.FREQ CK128M or CK64M.
NRF54L = nordic(
    'nrf54l', 'nRF54L clock tree', 'nRF54L05/L10/L15/LM20A/LM20B datasheets, CLOCK and OSCILLATORS', ['^NRF54L'], 'cpu',
    [
        fixed('hfint', 'HFINT 128 MHz', 0, 0, 128 * MHZ),
        fixed('hfxo', 'HFXO 32 MHz crystal', 0, 1, 32 * MHZ),
        hf_mux('pll', 'PLL 128 MHz (XOSTART)', 1, 0, 'CLOCK_TASKS_XOSTART.TASKS_XOSTART', [
            ('hfint', 'HFINT RC oscillator', 'hfint', 1, 1, {}),
            ('hfxo', 'HFXO crystal (x4)', 'hfxo', 4, 1, {}),
        ]),
        factors('cpu', 'CPU (PLL.FREQ)', 2, 0, 'pll', 'OSCILLATORS_PLL_FREQ.FREQ', 0, [(1, 1), (2, 3)],
                consumer=True, max=128 * MHZ),
        *lf_sources(),
        lf_mux('CLOCK_LFCLK_SRC.SRC', [('lfrc', 'LFRC', 'lfrc', 0), ('lfxo', 'LFXO', 'lfxo', 1)], 'pll', 4, 15625, 2),
    ],
    [LF_START])

GRAPHS = [NRF51, NRF52, NRF53, NRF91, NRF54L]


def main():
    failed = False
    for item in GRAPHS:
        problems = check_graph(item)
        for problem in problems:
            print(f'{item["id"]}: {problem}')
        failed = failed or bool(problems)
        print(f'wrote {write_graph(item, f"nordic/{item["id"]}.json").relative_to(REPO_ROOT)}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
