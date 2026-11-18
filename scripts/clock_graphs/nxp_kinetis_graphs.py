"""Write the NXP Kinetis MCG clock graphs (clock_graphs/nxp_kinetis/*.json).

Hand-written from the Kinetis K20/K60, K22F/K64F, K65/K66, K80/K82, KV4x and KV5x reference manuals
(MCG, OSC and SIM chapters) for the families whose core systemInit applies the MCG registers
(system_nxp_mk*.c). MCG_MODE is a NECTO pseudo-register that tells systemInit which mode sequence to
run (FEI/FEE/FBI/FBE/PEE); the graph derives it from the chosen MCGOUTCLK source.
Register values are absolute bit values (see clock_graphs/README.md).

Run:  python scripts/clock_graphs/nxp_kinetis_graphs.py
"""

from graphlib import REPO_ROOT, check_graph, hexv, write_graph
from stm32_graphs import MHZ, en, external, factors, fixed, graph, mux, rule, span

PRDIV = 'MCG_C5.PRDIV0|MCG_C5.PRDIV'
VDIV = 'MCG_C6.VDIV0|MCG_C6.VDIV'
PLLCLKEN = 'MCG_C5.PLLCLKEN0|MCG_C5.PLLCLKEN'
FRDIV_LOW = [1, 2, 4, 8, 16, 32, 64, 128]            # 32 kHz oscillator (RANGE 0 or OSCSEL = RTC)
FRDIV_HIGH = [32, 64, 128, 256, 512, 1024, 1280, 1536]  # MHz oscillators
MCG_MODES = {'FEI': 0, 'FBI': 1, 'FEE': 3, 'FBE': 4, 'PEE': 7}


def kinetis(graph_id, title, source, devices, pll, limits, oscsel=True, irc48m=True, variants=()):
    """pll: ('a', ...) PRDIV0 1-25 x VDIV0 24-55; ('b', ...) PRDIV 1-8 x VDIV 16-47, VCO / 2.
    limits: core, bus, flexbus, flash maxima in Hz."""
    kind, ref_min, ref_max, out_min, out_max = pll
    core_max, bus_max, flexbus_max, flash_max = limits
    eref = 'oscsel' if oscsel else 'osc0'
    nodes = [
        external('osc0', 'OSC0', 0, 0, None, tooltip='System oscillator (crystal or external clock, 3-32 MHz).'),
        fixed('irc_slow', 'Slow IRC 32.768 kHz', 0, 4, 32768),
        fixed('irc_fast', 'Fast IRC 4 MHz', 0, 5, 4 * MHZ),
        factors('fcrdiv', 'FCRDIV', 1, 5, 'irc_fast', 'MCG_SC.FCRDIV', 1, [(1 << n, n) for n in range(8)]),
        mux('mcgirclk', 'MCGIRCLK', 2, 4, 'MCG_C2.IRCS', [('slow', 'Slow IRC', 'irc_slow', 0), ('fast', 'Fast IRC', 'fcrdiv', 1)]),
    ]
    del nodes[0]['enable']
    if oscsel:
        nodes.append(fixed('rtc32k', 'RTC oscillator 32.768 kHz', 0, 1, 32768))
        choices = [('osc0', 'OSC0', 'osc0', 0), ('rtc', 'RTC 32 kHz', 'rtc32k', 1)]
        if irc48m:
            nodes.append(fixed('irc48m', 'IRC48M 48 MHz', 0, 2, 48 * MHZ))
            choices.append(('irc48m', 'IRC48M', 'irc48m', 2))
        nodes.append(mux('oscsel', 'External reference (OSCSEL)', 1, 1, 'MCG_C7.OSCSEL', choices))
    # FLL reference: slow IRC, or the external reference divided by FRDIV (factor depends on the source).
    frdiv_options = []
    for code in range(8):
        for scale, table, condition in (('low', FRDIV_LOW, "sel.oscsel == 'rtc'"), ('high', FRDIV_HIGH, "sel.oscsel != 'rtc'")):
            if not oscsel and scale == 'low':
                continue
            option = {'id': f'{scale}{code}', 'label': f'/{table[code]}', 'from': eref, 'div': table[code],
                      'set': {'MCG_C1.FRDIV': hexv(code << 3)}}
            if oscsel:
                option['when'] = condition
            frdiv_options.append(option)
    nodes += [
        {'id': 'frdiv', 'label': 'FRDIV', 'kind': 'divider', 'x': 2, 'y': 2, 'options': frdiv_options},
        mux('fllref', 'FLL reference', 3, 3, 'MCG_C1.IREFS', [('irc', 'Slow IRC', 'irc_slow', 1 << 2), ('ext', 'External / FRDIV', 'frdiv', 0)],
            min=31250, max=39063, tooltip='FLL reference: 31.25-39.0625 kHz.'),
        {'id': 'fll', 'label': 'FLL (DRS, DMX32)', 'kind': 'multiplier', 'x': 4, 'y': 3,
         'options': [{'id': str(factor), 'label': f'x{factor}', 'from': 'fllref', 'mul': factor,
                      'set': {'MCG_C4.DRST_DRS': hexv(drs << 5), 'MCG_C4.DMX32': hexv(dmx << 7)}}
                     for factor, drs, dmx in [(640, 0, 0), (732, 0, 1), (1280, 1, 0), (1464, 1, 1)]]},
    ]
    if kind == 'a':
        nodes += [
            span('prdiv', 'PLL /PRDIV', 3, 1, eref, PRDIV, 0, 1, 25, 'div', offset=-1, min=ref_min, max=ref_max,
                 tooltip=f'PLL reference: {ref_min / MHZ:g}-{ref_max / MHZ:g} MHz.'),
            span('pll', 'PLL xVDIV', 4, 1, 'prdiv', VDIV, 0, 24, 55, 'mul', offset=-24, min=out_min, max=out_max,
                 enable=en(PLLCLKEN, 1 << 6)),
        ]
        pll_out = 'pll'
    else:
        nodes += [
            span('prdiv', 'PLL /PRDIV', 3, 1, eref, PRDIV, 0, 1, 8, 'div', offset=-1, min=ref_min, max=ref_max,
                 tooltip=f'PLL reference: {ref_min / MHZ:g}-{ref_max / MHZ:g} MHz.'),
            span('vco', 'PLL xVDIV (VCO)', 4, 1, 'prdiv', VDIV, 0, 16, 47, 'mul', offset=-16, min=out_min * 2, max=out_max * 2,
                 enable=en(PLLCLKEN, 1 << 6)),
            {'id': 'pll', 'label': 'MCGPLLCLK (VCO/2)', 'kind': 'divider', 'x': 5, 'y': 1,
             'options': [{'id': '2', 'label': '/2', 'from': 'vco', 'div': 2}]},
        ]
        pll_out = 'pll'
    nodes += [
        {'id': 'mcgout', 'label': 'MCGOUTCLK', 'kind': 'mux', 'x': 6, 'y': 2,
         'options': [
             {'id': 'pll', 'label': 'PLL (PEE)', 'from': pll_out, 'set': {'MCG_C1.CLKS': hexv(0), 'MCG_C6.PLLS': hexv(1 << 6)}},
             {'id': 'fll', 'label': 'FLL (FEI/FEE)', 'from': 'fll', 'set': {'MCG_C1.CLKS': hexv(0), 'MCG_C6.PLLS': hexv(0)}},
             {'id': 'irc', 'label': 'Internal reference (FBI)', 'from': 'mcgirclk', 'set': {'MCG_C1.CLKS': hexv(1 << 6), 'MCG_C6.PLLS': hexv(0)}},
             {'id': 'ext', 'label': 'External reference (FBE)', 'from': eref, 'set': {'MCG_C1.CLKS': hexv(2 << 6), 'MCG_C6.PLLS': hexv(0)}},
         ]},
        span('core', 'Core/system (OUTDIV1)', 7, 0, 'mcgout', 'SIM_CLKDIV1.OUTDIV1', 28, 1, 16, 'div', offset=-1, max=core_max, consumer=True),
        span('bus', 'Bus (OUTDIV2)', 7, 1, 'mcgout', 'SIM_CLKDIV1.OUTDIV2', 24, 1, 16, 'div', offset=-1, max=bus_max, consumer=True),
        # FlexBus only matters when it is used, so its limit does not block a build.
        span('flexbus', 'FlexBus (OUTDIV3)', 7, 2, 'mcgout', 'SIM_CLKDIV1.OUTDIV3', 20, 1, 16, 'div', offset=-1,
             tooltip=f'FlexBus clock: at most {flexbus_max / MHZ:g} MHz when the FlexBus is used.'),
        span('flash', 'Flash (OUTDIV4)', 7, 3, 'mcgout', 'SIM_CLKDIV1.OUTDIV4', 16, 1, 16, 'div', offset=-1, max=flash_max, consumer=True),
    ]
    peripheral = [('fll', 'MCGFLLCLK', 'fll', 0), ('pll', 'MCGPLLCLK', pll_out, 1 << 16)]
    if irc48m:
        peripheral.append(('irc48m', 'IRC48M', 'irc48m', 3 << 16))
    nodes.append(mux('pllfllsel', 'Peripheral clock (PLLFLLSEL)', 7, 5, 'SIM_SOPT2.PLLFLLSEL', peripheral))
    constraints = [
        rule('f.core >= f.bus && f.bus >= f.flash', 'The core clock must be at least the bus clock, and the bus clock at least the flash clock.'),
        rule("sel.mcgout != 'pll' || in.osc0 >= 3000000" + (" || sel.oscsel != 'osc0'" if oscsel else ''),
             'The PLL reference needs OSC0 at 3 MHz or more.'),
    ]
    derive = [
        {'field': 'MCG_MODE.MCGMODE', 'cases': [
            {'when': "sel.mcgout == 'pll'", 'value': hexv(MCG_MODES['PEE'])},
            {'when': "sel.mcgout == 'fll' && sel.fllref == 'irc'", 'value': hexv(MCG_MODES['FEI'])},
            {'when': "sel.mcgout == 'fll'", 'value': hexv(MCG_MODES['FEE'])},
            {'when': "sel.mcgout == 'irc'", 'value': hexv(MCG_MODES['FBI'])}],
         'default': hexv(MCG_MODES['FBE'])},
        # Crystal range: very high above 8 MHz, high from 3 MHz.
        {'field': 'MCG_C2.RANGE', 'cases': [{'when': 'in.osc0 > 8000000', 'value': hexv(2 << 4)}], 'default': hexv(1 << 4)},
    ]
    result = graph(graph_id, title, source, devices, 'core',
                   {'osc0': {'label': 'OSC0 frequency', 'default': 8 * MHZ, 'min': 3 * MHZ, 'max': 32 * MHZ}}, nodes,
                   settings=['MCG_C2.EREFS', 'OSC_CR.ERCLKEN'], derive=derive, constraints=constraints, variants=variants)
    result['vendor'] = 'NXP'
    return result


GRAPHS = [
    kinetis('kinetis_k20_k5x_k60', 'Kinetis K20/K51/K53/K60 MCG clock tree', 'K20 (K20P64M50SF0RM), K60 (K60P144M100SF2V2RM) reference manuals',
            ['^MK20D[NX](32|64|128)V', '^MK5[13]D', '^MK60D'], ('a', 2 * MHZ, 4 * MHZ, 48 * MHZ, 100 * MHZ),
            (100 * MHZ, 50 * MHZ, 50 * MHZ, 25 * MHZ), irc48m=False,
            variants=[{'devices': ['^MK20D[NX](32|64|128)V'], 'limits': {'core': {'max': 50 * MHZ}, 'pll': {'max': 50 * MHZ}}}]),
    kinetis('kinetis_k22f_k64f', 'Kinetis K22F/K64F MCG clock tree', 'K22F (K22P121M120SF7RM), K64F (K64P144M120SF5RM) reference manuals',
            ['^MK22F', '^MK64F'], ('a', 2 * MHZ, 4 * MHZ, 48 * MHZ, 120 * MHZ), (120 * MHZ, 60 * MHZ, 50 * MHZ, 25 * MHZ),
            variants=[{'devices': ['^MK22FN128V'], 'limits': {'core': {'max': 100 * MHZ}, 'pll': {'max': 100 * MHZ}, 'bus': {'max': 50 * MHZ}}}]),
    kinetis('kinetis_k65_k66', 'Kinetis K65/K66 MCG clock tree', 'K66 reference manual K66P144M180SF5RMV2', ['^MK6[56]F'],
            ('b', 8 * MHZ, 16 * MHZ, 90 * MHZ, 180 * MHZ), (180 * MHZ, 60 * MHZ, 60 * MHZ, 28 * MHZ)),
    kinetis('kinetis_k80_k82', 'Kinetis K80/K82 MCG clock tree', 'K80/K82 reference manual K80P121M150SF5RM', ['^MK8[02]F'],
            ('b', 8 * MHZ, 16 * MHZ, 90 * MHZ, 150 * MHZ), (150 * MHZ, 75 * MHZ, 75 * MHZ, 25 * MHZ)),
    kinetis('kinetis_kv4x', 'Kinetis KV4x MCG clock tree', 'KV4x reference manual KV4XP100M168RM', ['^MKV4[246]F'],
            ('b', 8 * MHZ, 16 * MHZ, 90 * MHZ, 168 * MHZ), (168 * MHZ, 84 * MHZ, 84 * MHZ, 24 * MHZ), oscsel=False, irc48m=False),
    kinetis('kinetis_kv5x', 'Kinetis KV5x MCG clock tree', 'KV5x reference manual KV5XP144M240RM', ['^MKV5[68]F'],
            ('b', 8 * MHZ, 16 * MHZ, 90 * MHZ, 240 * MHZ), (240 * MHZ, 120 * MHZ, 60 * MHZ, 25 * MHZ), oscsel=False, irc48m=False),
]


def main():
    failed = False
    for item in GRAPHS:
        problems = check_graph(item)
        for problem in problems:
            print(f'{item["id"]}: {problem}')
        failed = failed or bool(problems)
        print(f'wrote {write_graph(item, f"nxp_kinetis/{item["id"]}.json").relative_to(REPO_ROOT)}')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
