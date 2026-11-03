# Clock graphs

Graphical clock-tree descriptions for the MikroE VS Code extension (and any other tool that
edits NECTO `def/<MCU>.json` clock registers). A graph never replaces the register
definitions: every choice in the diagram resolves to `config_registers` field values of the
MCU's definition, so the generated `core_header.h` (`VALUE_<REG>` + `FOSC_KHZ_VALUE`) and the
core's `systemInit` stay exactly as they are.

```
clock_graphs/
  manifest.json        packaging manifest: scripts/package.py releases this folder as clock_graphs.7z
  index.json           generated: which graph serves which MCU (scripts/clock_graphs/build_index.py)
  stm32/*.json         written by scripts/clock_graphs/stm32_graphs.py
  microchip_sam/*.json written by scripts/clock_graphs/microchip_sam_graphs.py
  renesas_ra/*.json    converted from Renesas FSP packs by scripts/clock_graphs/convert_fsp_ra.py
```

Do not edit the JSON files by hand: change the generator and run it again, then
`python scripts/clock_graphs/build_index.py` and `python scripts/clock_graphs/validate.py`.
The `Clock graphs` workflow fails a pull request whose `index.json` is stale or whose graphs
do not validate.

## Data sources and licensing

* **STM32** graphs are written by hand from the STM32 reference manuals and datasheets. No
  STM32CubeMX database content is used (its SLA0048 license forbids open-source
  redistribution).
* **Microchip SAM** graphs (SAM E70/S70/V70/V71, SAM G53/G54/G55) are written by hand from the
  datasheets' PMC chapters.
* **Renesas RA** graphs are converted from the `<clock>` section of the FSP MCU packs
  (`.module_descriptions/Renesas##BSP##<family>##fsp####<version>.xml`), part of the RA MCU BSP
  released by Renesas under BSD-3-Clause (see https://github.com/renesas/fsp/blob/master/LICENSE.md).
  Each converted file names its FSP version in `source`.

## Graph format (schema 1)

A graph is a directed graph of nodes. Every node outputs one frequency (Hz). Frequencies flow
from sources through muxes, dividers and multipliers to outputs.

```jsonc
{
  "schema": 1,
  "id": "stm32f4",                       // unique, also the file name
  "title": "STM32F4 system clock tree",
  "vendor": "STMicroelectronics",
  "source": "RM0090 / RM0368 / RM0383 / RM0390 / RM0402 / RM0430",
  "devices": ["^STM32F4"],               // regular expressions on the MCU name (MCU_NAME)
  "fosc": "hclk",                        // node whose frequency becomes FOSC_KHZ_VALUE
  "inputs": {                            // user-entered frequencies, one per source node
    "hse": { "label": "HSE", "default": 8000000, "min": 4000000, "max": 26000000 }
  },
  "settings": ["RCC_CR.HSEBYP", "SVRANGE.VRANGE"],  // plain field dropdowns shown with the diagram
  "nodes": [ ... ],
  "derive": [ ... ],
  "constraints": [ ... ],
  "variants": [ ... ]
}
```

### Nodes

```jsonc
{
  "id": "pllm",                 // [a-z0-9_]+
  "label": "/M",
  "kind": "divider",            // source | mux | divider | multiplier | output (drawing hint only)
  "x": 2, "y": 3,               // grid position (column, row)
  "tooltip": "VCO input must be 1-2 MHz",
  "options": [ ... ],           // or "range", or "input" (source fed by inputs[id])
  "default": "8",               // option chosen when no bound field decides (unbound nodes)
  "min": 950000, "max": 2100000,  // allowed output frequency (Hz)
  "consumer": true,             // the clock is used: keeps everything feeding it enabled
  "enable": { "field": "RCC_CR.PLLON", "on": "01000000", "off": "00000000", "auto": "both" },
  "bypass": "sel.pllsrc == 'hsi2'"  // expression: when true the node passes its input through
}
```

**Options.** The node outputs `base * mul / div` of its selected option, where `base` is the
frequency of node `from`, or 1 Hz when `from` is absent (so a fixed oscillator is an option
with `"mul": 16000000`). `"mul": 0` turns the clock off.

```jsonc
{ "id": "hse", "label": "HSE", "from": "hse", "mul": 1, "div": 1,
  "set": { "RCC_PLLCFGR.PLLSRC": "00400000" } }
```

`keeps` (optional) lists nodes the option needs running although it does not take its frequency
from them, e.g. a 480 MHz USB PLL that needs the main crystal: `"keeps": ["main_xtal"]`.

`set` lists the register field values the option writes. **Values are absolute register bit
values in hex**, exactly like `config_registers[].fields[].settings[].value` in the NECTO
definitions (already shifted into position), so one value fits every MCU of a family even when
a field is wider on some parts. A field written `A|B` means "field A, or field B on MCUs that
name it so".

The selected option is the one whose `set` matches the current register values; an option
whose values the MCU definition does not offer is unavailable on that MCU.

**Range.** Long numeric factors are written as a range instead of a list:

```jsonc
"range": { "from": "pllm", "op": "mul", "min": 50, "max": 432,
           "field": "RCC_PLLCFGR.PLLN", "lsb": 6, "scale": 1, "offset": 0 }
```

Factor `n` writes `(n * scale + offset) << lsb` to `field`.

**Enable.** Oscillators, PLLs and PLL outputs are switched by usage. A node is *active* when a
`consumer` node reaches it through the selected options and its frequency is not 0. An active
node writes `enable.on`; an inactive one writes `enable.off` when `auto` is `both` (`on` never
switches the clock off, for clocks the reset code runs from).

### Derived fields

Fields that follow from frequencies (for example the H7 PLL input range) are written by the
graph, never by the user:

```jsonc
{ "field": "RCC_PLLCFGR.PLL1RGE", "cases": [
    { "when": "f.divm1 < 2000000", "value": "00000000" },
    { "when": "f.divm1 < 4000000", "value": "00000004" } ],
  "default": "0000000C" }
```

### Constraints

```jsonc
{ "expr": "f.pllm >= 950000 && f.pllm <= 2100000", "message": "VCO input must be 0.95-2.1 MHz" }
```

Expressions use numbers (`48e6`, `0x400`), strings (`'hse'`), `f.<node>` (frequency in Hz),
`sel.<node>` (selected option id), `in.<input>` (input frequency), `reg("REG.FIELD")`
(current absolute field value), `!`, unary `-`, `* / %`, `+ -`, `< <= > >=`, `== !=`, `&&`,
`||` and parentheses. A false constraint is shown as an error and blocks the build.

### Variants

Per-part limits inside a family; every variant whose `devices` match applies, in order:

```jsonc
{ "devices": ["^STM32F401"], "limits": { "hclk": { "max": 84000000 } },
  "constraints": [ ... ], "inputs": { "hse": { "max": 26000000 } } }
```

## index.json

Generated, never edited:

```json
{ "schema": 1, "graphs": [ { "id": "stm32f4", "file": "stm32/stm32f4.json", "vendor": "STMicroelectronics", "devices": ["^STM32F4"] } ] }
```

A tool picks the first graph with a `devices` expression matching the MCU name, then checks
every bound field against the MCU definition. MCUs without a matching graph keep the register
view.
