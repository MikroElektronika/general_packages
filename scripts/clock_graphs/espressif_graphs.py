"""Write the Espressif RISC-V clock graphs (clock_graphs/espressif/*.json).

Hand-written from the ESP32-C2/C3/C5/C6/C61/H2/P4/S31 technical reference manuals (Reset and Clock) and checked
against ESP-IDF (rtc_clk_cpu_freq_mhz_to_config() and clk_tree_ll.h of each chip, Apache-2.0): every CPU frequency
the ESP-IDF clock driver accepts, with the source/divider field values that select it.
The core SystemInit (core_packages RISCV/gcc_clang/system/src/espressif/<chip>/init_clock.c) decodes these fields
into the CPU frequency and lets the ESP-IDF driver power up the PLL and switch. FOSC_KHZ_VALUE is the CPU clock.
Register values are absolute bit values (see clock_graphs/README.md).

Run:  python scripts/clock_graphs/espressif_graphs.py
"""

from graphlib import REPO_ROOT, check_graph, write_graph
from stm32_graphs import MHZ, fixed, graph

# CPU clock roots per chip: (node id, label, frequency in MHz)
ROOTS = {
    'esp32c2': [('pll', 'PLL 480 MHz', 480)],
    'esp32c3': [('pll', 'PLL 480 MHz', 480)],
    'esp32c5': [('pll_f160m', 'PLL_F160M', 160), ('pll_f240m', 'PLL_F240M', 240)],
    'esp32c6': [('pll', 'PLL 480 MHz', 480)],
    'esp32c61': [('pll_f160m', 'PLL_F160M', 160)],
    'esp32h2': [('pll', 'PLL 96 MHz', 96), ('flash_pll', 'FLASH_PLL 64 MHz', 64)],
    'esp32p4': [('cpll', 'CPLL 400 MHz', 400)],
    'esp32s31': [('cpll', 'CPLL 320 MHz', 320), ('pll_f240m', 'PLL_F240M', 240)],
}

# Which root and divider give each option (same order as TABLE options)
SOURCES = {
    'esp32c2': [('xtal', 1), ('pll', 6), ('pll', 4)],
    'esp32c3': [('xtal', 1), ('pll', 6), ('pll', 3)],
    'esp32c5': [('xtal', 1), ('pll_f160m', 2), ('pll_f160m', 1), ('pll_f240m', 1)],
    'esp32c6': [('xtal', 1), ('pll', 6), ('pll', 4), ('pll', 3)],
    'esp32c61': [('xtal', 1), ('pll_f160m', 2), ('pll_f160m', 1)],
    'esp32h2': [('xtal', 1), ('pll', 2), ('flash_pll', 1), ('pll', 1)],
    'esp32p4': [('xtal', 1), ('cpll', 4), ('cpll', 2), ('cpll', 1)],
    'esp32s31': [('xtal', 1), ('cpll', 4), ('cpll', 2), ('pll_f240m', 1), ('cpll', 1)],
}

DEVICES = {
    'esp32c2': ['^ESP8684'], 'esp32c3': ['^ESP32-C3', '^ESP8685'], 'esp32c5': ['^ESP32-C5'], 'esp32c6': ['^ESP32-C6(?!1)'],
    'esp32c61': ['^ESP32-C61'], 'esp32h2': ['^ESP32-H2'], 'esp32p4': ['^ESP32-P4'], 'esp32s31': ['^ESP32-S31'],
}

# Generated from the core definitions (core_packages scripts/espressif_mcus.py): label, CPU MHz, field values
TABLE = {
    'esp32c2': dict(title='ESP32-C2', xtal=40, options=[
        ('XTAL 40 MHz', 40, {'SYSTEM_SYSCLK_CONF.SOC_CLK_SEL': '00000000'}),
        ('PLL 80 MHz', 80, {'SYSTEM_SYSCLK_CONF.SOC_CLK_SEL': '00000400', 'SYSTEM_CPU_PER_CONF.CPUPERIOD_SEL': '00000000'}),
        ('PLL 120 MHz', 120, {'SYSTEM_SYSCLK_CONF.SOC_CLK_SEL': '00000400', 'SYSTEM_CPU_PER_CONF.CPUPERIOD_SEL': '00000001'}),
    ]),
    'esp32c3': dict(title='ESP32-C3', xtal=40, options=[
        ('XTAL 40 MHz', 40, {'SYSTEM_SYSCLK_CONF.SOC_CLK_SEL': '00000000'}),
        ('PLL 80 MHz', 80, {'SYSTEM_SYSCLK_CONF.SOC_CLK_SEL': '00000400', 'SYSTEM_CPU_PER_CONF.CPUPERIOD_SEL': '00000000'}),
        ('PLL 160 MHz', 160, {'SYSTEM_SYSCLK_CONF.SOC_CLK_SEL': '00000400', 'SYSTEM_CPU_PER_CONF.CPUPERIOD_SEL': '00000001'}),
    ]),
    'esp32c5': dict(title='ESP32-C5', xtal=40, options=[
        ('XTAL (40/48 MHz)', 40, {'PCR_SYSCLK_CONF.SOC_CLK_SEL': '00000000', 'PCR_CPU_FREQ_CONF.CPU_DIV_NUM': '00000000'}),
        ('PLL_F160M / 2 = 80 MHz', 80, {'PCR_SYSCLK_CONF.SOC_CLK_SEL': '00020000', 'PCR_CPU_FREQ_CONF.CPU_DIV_NUM': '00000001'}),
        ('PLL_F160M = 160 MHz', 160, {'PCR_SYSCLK_CONF.SOC_CLK_SEL': '00020000', 'PCR_CPU_FREQ_CONF.CPU_DIV_NUM': '00000000'}),
        ('PLL_F240M = 240 MHz', 240, {'PCR_SYSCLK_CONF.SOC_CLK_SEL': '00030000', 'PCR_CPU_FREQ_CONF.CPU_DIV_NUM': '00000000'}),
    ]),
    'esp32c6': dict(title='ESP32-C6', xtal=40, options=[
        ('XTAL 40 MHz', 40, {'PCR_SYSCLK_CONF.SOC_CLK_SEL': '00000000'}),
        ('PLL 480 MHz / 6 = 80 MHz', 80, {'PCR_SYSCLK_CONF.SOC_CLK_SEL': '00010000', 'PCR_CPU_FREQ_CONF.CPU_HS_DIV_NUM': '00000100', 'PCR_CPU_FREQ_CONF.CPU_HS_120M_FORCE': '00000000'}),
        ('PLL 480 MHz / 4 = 120 MHz', 120, {'PCR_SYSCLK_CONF.SOC_CLK_SEL': '00010000', 'PCR_CPU_FREQ_CONF.CPU_HS_DIV_NUM': '00000000', 'PCR_CPU_FREQ_CONF.CPU_HS_120M_FORCE': '00010000'}),
        ('PLL 480 MHz / 3 = 160 MHz', 160, {'PCR_SYSCLK_CONF.SOC_CLK_SEL': '00010000', 'PCR_CPU_FREQ_CONF.CPU_HS_DIV_NUM': '00000000', 'PCR_CPU_FREQ_CONF.CPU_HS_120M_FORCE': '00000000'}),
    ]),
    'esp32c61': dict(title='ESP32-C61', xtal=40, options=[
        ('XTAL 40 MHz', 40, {'PCR_SYSCLK_CONF.SOC_CLK_SEL': '00000000', 'PCR_CPU_FREQ_CONF.CPU_DIV_NUM': '00000000'}),
        ('PLL_F160M / 2 = 80 MHz', 80, {'PCR_SYSCLK_CONF.SOC_CLK_SEL': '00020000', 'PCR_CPU_FREQ_CONF.CPU_DIV_NUM': '00000001'}),
        ('PLL_F160M = 160 MHz', 160, {'PCR_SYSCLK_CONF.SOC_CLK_SEL': '00020000', 'PCR_CPU_FREQ_CONF.CPU_DIV_NUM': '00000000'}),
    ]),
    'esp32h2': dict(title='ESP32-H2', xtal=32, options=[
        ('XTAL 32 MHz', 32, {'PCR_SYSCLK_CONF.SOC_CLK_SEL': '00000000', 'PCR_CPU_FREQ_CONF.CPU_DIV_NUM': '00000000'}),
        ('PLL 96 MHz / 2 = 48 MHz', 48, {'PCR_SYSCLK_CONF.SOC_CLK_SEL': '00010000', 'PCR_CPU_FREQ_CONF.CPU_DIV_NUM': '00000001'}),
        ('FLASH_PLL 64 MHz', 64, {'PCR_SYSCLK_CONF.SOC_CLK_SEL': '00030000', 'PCR_CPU_FREQ_CONF.CPU_DIV_NUM': '00000000'}),
        ('PLL 96 MHz', 96, {'PCR_SYSCLK_CONF.SOC_CLK_SEL': '00010000', 'PCR_CPU_FREQ_CONF.CPU_DIV_NUM': '00000000'}),
    ]),
    'esp32p4': dict(title='ESP32-P4', xtal=40, options=[
        ('XTAL 40 MHz', 40, {'LP_CLKRST_HP_CLK_CTRL.HP_ROOT_CLK_SRC_SEL': '00000000'}),
        ('CPLL 400 MHz / 4 = 100 MHz', 100, {'LP_CLKRST_HP_CLK_CTRL.HP_ROOT_CLK_SRC_SEL': '00000001', 'HP_SYS_CLKRST_ROOT_CLK_CTRL0.CPU_CLK_DIV_NUM': '00000060'}),
        ('CPLL 400 MHz / 2 = 200 MHz', 200, {'LP_CLKRST_HP_CLK_CTRL.HP_ROOT_CLK_SRC_SEL': '00000001', 'HP_SYS_CLKRST_ROOT_CLK_CTRL0.CPU_CLK_DIV_NUM': '00000020'}),
        ('CPLL 400 MHz / 1 = 400 MHz', 400, {'LP_CLKRST_HP_CLK_CTRL.HP_ROOT_CLK_SRC_SEL': '00000001', 'HP_SYS_CLKRST_ROOT_CLK_CTRL0.CPU_CLK_DIV_NUM': '00000000'}),
    ]),
    'esp32s31': dict(title='ESP32-S31', xtal=40, options=[
        ('XTAL 40 MHz', 40, {'HP_SYS_CLKRST_SOC_CLK_SEL.SOC_CLK_SEL': '00000000'}),
        ('CPLL 320 MHz / 4 = 80 MHz', 80, {'HP_SYS_CLKRST_SOC_CLK_SEL.SOC_CLK_SEL': '00000001', 'HP_SYS_CLKRST_CPU_FREQ_CTRL0.CPU_CLK_DIV_NUM': '00000003'}),
        ('CPLL 320 MHz / 2 = 160 MHz', 160, {'HP_SYS_CLKRST_SOC_CLK_SEL.SOC_CLK_SEL': '00000001', 'HP_SYS_CLKRST_CPU_FREQ_CTRL0.CPU_CLK_DIV_NUM': '00000001'}),
        ('PLL_F240M = 240 MHz', 240, {'HP_SYS_CLKRST_SOC_CLK_SEL.SOC_CLK_SEL': '00000003', 'HP_SYS_CLKRST_CPU_FREQ_CTRL0.CPU_CLK_DIV_NUM': '00000000'}),
        ('CPLL 320 MHz', 320, {'HP_SYS_CLKRST_SOC_CLK_SEL.SOC_CLK_SEL': '00000001', 'HP_SYS_CLKRST_CPU_FREQ_CTRL0.CPU_CLK_DIV_NUM': '00000000'}),
    ]),
}


def espressif(chip):
    t = TABLE[chip]
    nodes = []
    if chip == 'esp32c5':
        nodes.append({'id': 'xtal', 'label': 'XTAL', 'kind': 'source', 'x': 0, 'y': 0, 'input': 'xtal',
                      'tooltip': 'ESP32-C5 runs from a 40 MHz or 48 MHz crystal.'})
        inputs = {'xtal': {'label': 'XTAL frequency', 'default': 40 * MHZ, 'min': 40 * MHZ, 'max': 48 * MHZ}}
    else:
        nodes.append(fixed('xtal', f'XTAL {t["xtal"]} MHz', 0, 0, t['xtal'] * MHZ))
        inputs = {}
    for row, (node_id, label, mhz) in enumerate(ROOTS[chip], start=1):
        nodes.append(fixed(node_id, label, 0, row, mhz * MHZ,
                           tooltip='Powered up and calibrated by SystemInit when the CPU clock uses it.'))
    options = []
    for (label, mhz, values), (source, div) in zip(t['options'], SOURCES[chip]):
        option = {'id': f'{source}_{mhz}' if source != 'xtal' else 'xtal', 'label': label, 'from': source, 'set': values}
        if div != 1:
            option['div'] = div
        options.append(option)
    top = max(mhz for _, mhz, _ in t['options'])
    nodes.append({'id': 'cpu', 'label': 'CPU clock', 'kind': 'mux', 'x': 2, 'y': 0, 'options': options,
                  'consumer': True, 'max': top * MHZ,
                  'tooltip': 'CPU frequencies supported by the ESP-IDF clock driver; FOSC_KHZ_VALUE follows this node.'})
    constraints = []
    if chip == 'esp32c5':
        constraints.append({'expr': 'in.xtal == 40e6 || in.xtal == 48e6', 'message': 'The ESP32-C5 crystal must be 40 MHz or 48 MHz.'})
    result = graph(chip, f'{t["title"]} clock tree', f'{t["title"]} Technical Reference Manual (Reset and Clock); ESP-IDF rtc_clk.c',
                   DEVICES[chip], 'cpu', inputs, nodes, constraints=constraints)
    result['vendor'] = 'Espressif'
    return result


GRAPHS = [espressif(chip) for chip in TABLE]


def main():
    failed = False
    for item in GRAPHS:
        problems = check_graph(item)
        for problem in problems:
            print(f'{item["id"]}: {problem}')
        failed = failed or bool(problems)
        print(f'wrote {write_graph(item, f"espressif/{item["id"]}.json").relative_to(REPO_ROOT)}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
