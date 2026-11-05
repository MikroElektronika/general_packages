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
  ti/*.json            written by scripts/clock_graphs/ti_graphs.py
  nxp_kinetis/*.json   written by scripts/clock_graphs/nxp_kinetis_graphs.py
  toshiba/*.json       written by scripts/clock_graphs/toshiba_graphs.py
  nuvoton/*.json       written by scripts/clock_graphs/nuvoton_graphs.py
  adi/*.json           written by scripts/clock_graphs/adi_graphs.py
  gigadevice/*.json    written by scripts/clock_graphs/gigadevice_graphs.py (GD32VF103, RISC-V)
  renesas_rx/*.json    written by scripts/clock_graphs/renesas_rx_graphs.py
  renesas_rl78/*.json  written by scripts/clock_graphs/renesas_rl78_graphs.py
  microchip_pic32/*.json written by scripts/clock_graphs/microchip_pic32_graphs.py (mikroC and XC32)
  microchip_pic32c/*.json written by scripts/clock_graphs/microchip_pic32c_graphs.py (ARM PIC32C)
  avr/*.json           converted from the mikroC AVR definitions by scripts/clock_graphs/convert_avr.py
  microchip_pic/*.json converted from the mikroC/XC8 PIC definitions by scripts/clock_graphs/convert_pic.py
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
* **Toshiba** graphs (TMPM3H, TMPM4K, TMPM4L) and **NXP Kinetis** MCG graphs (K20/K5x/K60, K22F/K64F,
  K65/K66, K80/K82, KV4x, KV5x) are written by hand from the reference manuals.
* **Texas Instruments** graphs (TM4C123, TM4C129, MSPM0, MSPM0C1103/C1104), **Nuvoton** (M2354) and **Analog
  Devices** (MAX32690) graphs are written by hand from the datasheets / reference manuals.
* **Microchip SAM** graphs (SAM E70/S70/V70/V71/V71RT, G51/G53/G54/G55, SAM4E/4N/4S/4SA/4SD, SAM4L,
  D09/D10/D11/D20/D21/DA1/R21/HA0/HA1, C20/C21, L21/L22/R30/R34/R35, D51/E51/E53/E54, RH71/RH707) are
  written by hand from the datasheets' clock chapters (PMC, SYSCTRL/GCLK/PM, OSCCTRL/GCLK/MCLK, SCIF/PM/BPM).
* **Microchip PIC32C** (ARM) graphs (PIC32CX SG41/SG60/SG61, PIC32CZ CA70/MC70, PIC32CX MTC/MTG/MTSH,
  PIC32CX SG12, PIC32CX BZ2/BZ3/BZ6, PIC32CZ CA80/CA90/CA91) are written by hand from the datasheets'
  clock chapters; SG41/SG6x and CA70/MC70 reuse the SAM D5x/E5x and SAM E70 clock trees they share.
  MPLAB Harmony csp clock plibs were used only to cross-check defaults and limits.
* **Renesas RX/RL78**, **GigaDevice GD32VF103** and **Microchip PIC32** graphs are written by hand from
  the hardware manuals / family reference manuals (Renesas Smart Configurator data was used only to
  cross-check limits, never copied).
* **AVR** and **PIC10/12/16/18** graphs are converted from the oscillator fuses of MikroE's own NECTO
  definitions (`convert_avr.py`, `convert_pic.py`, run locally against core_packages); their
  internal-oscillator frequency, when chosen at runtime, is entered by the user.
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

`when` (optional) is an expression: the option is offered only while it holds. Use it when one
field value means different factors depending on another choice, e.g. the Kinetis FLL divider
`MCG_C1.FRDIV` (/1-128 from the 32 kHz oscillator, /32-1536 from a MHz oscillator).

`keeps` (optional) lists nodes the option needs running although it does not take its frequency
from them, e.g. a 480 MHz USB PLL that needs the main crystal: `"keeps": ["main_xtal"]`.

`set` lists the register field values the option writes. **Values are absolute register bit
values in hex**, exactly like `config_registers[].fields[].settings[].value` in the NECTO
definitions (already shifted into position), so one value fits every MCU of a family even when
a field is wider on some parts. A field written `A|B` means "field A, or field B on MCUs that
name it so"; a leading `?` (`?MCLKCFG.USEHSCLK`) means "write it when the MCU has it" (a missing
optional field does not make the option unavailable). A value written `VALUE/MASK`
(`00000008/0000000E`) sets only the masked bits and keeps the rest of the field, e.g. an AVR clock
source inside `SUT_CKSEL` that keeps the chosen start-up time.

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

### Symbolic fuses

XC compilers name configuration fuses (`config_words`, field `<label_group>.<key>`) with symbols
instead of numbers (`DEVCFG1.FNOSC = PRIPLL`). A graph lists them once, mapped to the numeric
values it is written in, so the same graph drives mikroC (numeric `config_registers`) and XC:

```jsonc
"symbols": { "DEVCFG1.FNOSC": { "FRC": "00000000", "FRCPLL": "00000001", "PRI": "00000002", "PRIPLL": "00000003" } }
```

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

## Compilers

A graph only drives definition fields, so it serves every compiler whose definition has them:
GCC/Clang/LLVM cores apply the values in their system code, mikroC writes `config_registers`
itself (from the generated `.jcfg`), and XC8/XC32 turn `config_words` into fuse pragmas (through
`symbols`).

## index.json

Generated, never edited:

```json
{ "schema": 1, "graphs": [ { "id": "stm32f4", "file": "stm32/stm32f4.json", "vendor": "STMicroelectronics", "devices": ["^STM32F4"] } ] }
```

A tool picks the first graph with a `devices` expression matching the MCU name, then checks
every bound field against the MCU definition. MCUs without a matching graph keep the register
view.
