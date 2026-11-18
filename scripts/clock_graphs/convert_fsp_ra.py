"""Convert the Renesas FSP RA clock trees into clock graphs (clock_graphs/renesas_ra/*.json).

FSP describes each RA family's clock tree in the <clock> section of
.module_descriptions/Renesas##BSP##<family>##fsp####<version>.xml inside its MCU pack
(Renesas.RA_mcu_<family>.<version>.pack). FSP options emit BSP_CFG_* macros; this script turns
them into NECTO register field values (SYSTEM_* fields of def/<MCU>.json), using the FSP enum
encodings, and drops the peripheral branches the NECTO definitions cannot configure.

  python scripts/clock_graphs/convert_fsp_ra.py --packs <folder with Renesas.RA_mcu_*.pack> \
      --defs <folder with RA def/<MCU>.json files, searched recursively>

The FSP packs come with e2 studio (internal/projectgen/ra/packs) or from the FSP_Packs_<version>.zip
release asset of https://github.com/renesas/fsp.
"""

import argparse
import json
import math
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from graphlib import REPO_ROOT, check_graph, hexv, parse_expression, write_graph

PREFIX = 'board.clock.'

# FSP enum values: they equal the register codes on every RA family.
SOURCE_CODES = {'HOCO': 0, 'MOCO': 1, 'LOCO': 2, 'MAIN_OSC': 3, 'SUBCLOCK': 4, 'PLL': 5, 'PLL1P': 5, 'PLL2': 6,
                'PLL2P': 6, 'PLL1Q': 7, 'PLL1R': 8, 'PLL2Q': 9, 'PLL2R': 10}
SYS_DIV_CODES = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4, 32: 5, 64: 6, 128: 7, 3: 8, 6: 9, 12: 10, 24: 11}
PERIPHERAL_DIV_CODES = {1: 0, 2: 1, 4: 2, 6: 3, 8: 4, 3: 5, 5: 6, 10: 7, 16: 8, 32: 9}
MUL_FRACTION_CODES = {0: 0, 33: 1, 66: 2, 50: 3}

# BSP_CFG_* macro -> (encoding, candidate SYSTEM_* fields; the first one the MCU has is used).
MACROS = {
    'BSP_CFG_CLOCK_SOURCE': ('source', ['SCKSCR.CKSEL']),
    'BSP_CFG_ICLK_DIV': ('sysdiv', ['SCKDIVCR.ICK']),
    'BSP_CFG_PCLKA_DIV': ('sysdiv', ['SCKDIVCR.PCKA']),
    'BSP_CFG_PCLKB_DIV': ('sysdiv', ['SCKDIVCR.PCKB']),
    'BSP_CFG_PCLKC_DIV': ('sysdiv', ['SCKDIVCR.PCKC']),
    'BSP_CFG_PCLKD_DIV': ('sysdiv', ['SCKDIVCR.PCKD']),
    'BSP_CFG_PCLKE_DIV': ('sysdiv', ['SCKDIVCR.PCKE']),
    'BSP_CFG_FCLK_DIV': ('sysdiv', ['SCKDIVCR.FCK']),
    'BSP_CFG_BCLK_DIV': ('sysdiv', ['SCKDIVCR.BCK']),
    'BSP_CFG_MRPCLK_DIV': ('sysdiv', ['SCKDIVCR.MRPCK']),
    'BSP_CFG_CPUCLK_DIV': ('sysdiv', ['SCKDIVCR2.CPUCK', 'SCKDIVCR2.CPUCK0']),
    'BSP_CFG_CPUCLK1_DIV': ('sysdiv', ['SCKDIVCR2.CPUCK1']),
    'BSP_CFG_MRICLK_DIV': ('sysdiv', ['SCKDIVCR2.MRICK']),
    'BSP_CFG_UCLK_DIV': ('minus1', ['SCKDIVCR2.UCK']),
    'BSP_CFG_HOCO_FREQUENCY': ('raw', ['HOCOCR2.HCFRQ0', 'HOCOCR2.HCFRQ1']),
    'BSP_CFG_HOCO_DIV': ('sysdiv', ['HOCODIV.DIV']),
    'BSP_CFG_MOCO_DIV': ('sysdiv', ['MOCODIV.DIV']),
    'BSP_CFG_XTAL_DIV': ('sysdiv', ['MOSCDIV.DIV']),
    'BSP_CFG_PLL_SOURCE': ('pllsource', ['PLLCCR.PLSRCSEL'], 'PLLCR.PLLSTP'),
    'BSP_CFG_PLL2_SOURCE': ('pllsource', ['PLL2CCR.PL2SRCSEL'], 'PLL2CR.PLL2STP'),
    'BSP_CFG_PLL_DIV': ('plldiv', ['PLLCCR.PLIDIV', 'PLLCCR2.PLODIV']),
    'BSP_CFG_PLL2_DIV': ('plldiv', ['PLL2CCR.PL2IDIV']),
    'BSP_CFG_PLL_MUL': ('pllmul', ['PLLCCR.PLLMUL', 'PLLCCR2.PLLMUL']),
    'BSP_CFG_PLL2_MUL': ('pllmul', ['PLL2CCR.PLL2MUL']),
    'BSP_CFG_PLODIVP': ('minus1', ['PLLCCR2.PLODIVP']),
    'BSP_CFG_PLODIVQ': ('minus1', ['PLLCCR2.PLODIVQ']),
    'BSP_CFG_PLODIVR': ('minus1', ['PLLCCR2.PLODIVR']),
    'BSP_CFG_PL2ODIVP': ('minus1', ['PLL2CCR2.PL2ODIVP']),
    'BSP_CFG_PL2ODIVQ': ('minus1', ['PLL2CCR2.PL2ODIVQ']),
    'BSP_CFG_PL2ODIVR': ('minus1', ['PLL2CCR2.PL2ODIVR']),
    'BSP_CFG_CLKOUT_SOURCE': ('clkout', ['CKOCR.CKOSEL']),
    'BSP_CFG_CLKOUT_DIV': ('sysdiv', ['CKOCR.CKODIV']),
    'BSP_CFG_SCICLK_SOURCE': ('source', ['SCICKCR.SCICKSEL', 'SCICKCR.CKSEL']),
    'BSP_CFG_SCICLK_DIV': ('peripheraldiv', ['SCICKDIVCR.SCICKDIV', 'SCICKDIVCR.CKDIV']),
    'BSP_CFG_SPICLK_SOURCE': ('source', ['SPICKCR.SPICKSEL', 'SPICKCR.CKSEL']),
    'BSP_CFG_SPICLK_DIV': ('peripheraldiv', ['SPICKDIVCR.SPICKDIV', 'SPICKDIVCR.CKDIV']),
    'BSP_CFG_I3CCLK_SOURCE': ('source', ['I3CCKCR.I3CCKSEL']),
    'BSP_CFG_I3CCLK_DIV': ('peripheraldiv', ['I3CCKDIVCR.I3CCKDIV']),
    'BSP_CFG_ADCCLK_SOURCE': ('source', ['ADCCKCR.ADCCKSEL']),
    'BSP_CFG_ADCCLK_DIV': ('peripheraldiv', ['ADCCKDIVCR.ADCCKDIV']),
    'BSP_CFG_SCISPICLK_SOURCE': ('source', ['SCISPICKCR.SCISPICKSEL']),
    'BSP_CFG_SCISPICLK_DIV': ('peripheraldiv', ['SCISPICKDIVCR.SCISPICKDIV']),
    'BSP_CFG_IICCLK_SOURCE': ('source', ['IICCKCR.IICCKSEL']),
    'BSP_CFG_IICCLK_DIV': ('peripheraldiv', ['IICCKDIVCR.IICCKDIV']),
}

# RA0: one ICLK source choice spans the FOCO/FMAIN/FSUB/ICLK selectors (FSP code -> field raw values).
RA0_ICLK = {
    0: {'FOCOSCR.CKSEL': 0, 'FMAINSCR.CKSEL': 0, 'ICLKSCR.CKSEL': 0},  # HOCO
    1: {'FOCOSCR.CKSEL': 1, 'FMAINSCR.CKSEL': 0, 'ICLKSCR.CKSEL': 0},  # MOCO
    2: {'FSUBSCR.CKSEL': 1, 'ICLKSCR.CKSEL': 1},                       # LOCO
    3: {'FMAINSCR.CKSEL': 1, 'ICLKSCR.CKSEL': 0},                      # main oscillator
    4: {'FSUBSCR.CKSEL': 0, 'ICLKSCR.CKSEL': 1},                       # sub-clock
}

# Oscillator/PLL nodes -> stop bit (on = running). HOCO/MOCO/LOCO may clock the reset code, so they
# are never stopped automatically.
ENABLES = {
    'xtal_freq': ('MOSCCR.MOSTP', 'both'), 'subclk_freq': ('SOSCCR.SOSTP', 'both'),
    'hoco_freq': ('HOCOCR.HCSTP', 'on'), 'moco_freq': ('MOCOCR.MCSTP', 'on'), 'loco_freq': ('LOCOCR.LCSTP', 'on'),
    # PLLs are stopped by their source's "Disabled" option, never automatically: an unused PLL the
    # user set up (PLL2 for peripheral clocks) keeps running.
    'pll_display': ('PLLCR.PLLSTP', 'on'), 'pll1_display': ('PLLCR.PLLSTP', 'on'),
    'pll2_display': ('PLL2CR.PLL2STP', 'on'),
}


def short(identifier):
    text = identifier[len(PREFIX):] if identifier.startswith(PREFIX) else identifier
    return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')


class Definition:
    """Visible SYSTEM_* fields of one NECTO RA definition: name -> (mask, allowed absolute values)."""

    def __init__(self, path):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        self.mcu = data.get('mcu') or Path(path).stem
        self.fields = {}
        self.divisors = {}  # name -> {N: raw} from settings labelled '/N' or '1/N'
        for register in data.get('config_registers') or []:
            for field in register.get('fields') or []:
                if field.get('hidden'):
                    continue
                values = {int(str(item['value']), 16) for item in field.get('settings') or [] if str(item.get('value', '')).strip()}
                name = f'{register["key"].removeprefix("SYSTEM_")}.{field["key"]}'
                mask = int(str(field['mask']), 16)
                self.fields[name] = (mask, values)
                shift = (mask & -mask).bit_length() - 1
                for item in field.get('settings') or []:
                    label = re.fullmatch(r'\s*(?:1)?/(\d+)\s*', str(item.get('label', '')))
                    if label and str(item.get('value', '')).strip():
                        self.divisors.setdefault(name, {})[int(label.group(1))] = (int(str(item['value']), 16) & mask) >> shift

    def pick(self, candidates):
        return next((name for name in candidates if name in self.fields), None)

    def absolute(self, field, raw):
        mask = self.fields[field][0]
        return (raw << ((mask & -mask).bit_length() - 1)) & mask


def macro_code(value):
    """The enum name or number inside an FSP macro value such as '(BSP_CLOCKS_SYS_CLOCK_DIV_2)'."""
    text = value.strip().strip('()').strip()
    return text


def encode(kind, option, macro_value, definition, field):
    """Raw field value for one FSP option, or None when it does not translate."""
    code = macro_code(macro_value)
    number = re.fullmatch(r'(0x[0-9a-fA-F]+|\d+)U?', code)
    if kind == 'raw':
        return int(number.group(1), 0) if number else None
    if kind in ('source', 'clkout', 'pllsource'):
        match = re.fullmatch(r'BSP_CLOCKS_SOURCE_CLOCK_([A-Z0-9_]+)', code)
        if not match or match.group(1) not in SOURCE_CODES:
            return None
        if kind == 'pllsource':
            return {'MAIN_OSC': 0, 'HOCO': 1}.get(match.group(1))
        return SOURCE_CODES[match.group(1)]
    divisor = re.search(r'_DIV_(\d+)$', code)
    if kind == 'sysdiv':
        if number:
            return int(number.group(1), 0)
        return SYS_DIV_CODES.get(int(divisor.group(1))) if divisor else None
    if kind == 'peripheraldiv':
        return PERIPHERAL_DIV_CODES.get(int(divisor.group(1))) if divisor else None
    if kind == 'minus1':
        if not divisor and not option.get('div'):
            return None
        value = float(option.get('div') or divisor.group(1))
        return 9 if value == 1.5 else int(value) - 1
    if kind == 'plldiv':
        value = int(divisor.group(1)) if divisor else None
        if value is None:
            return None
        if value in definition.divisors.get(field, {}):  # the PLL input divider codes differ by family (RA4L1: /1 /4 /6 = 0 1 2)
            return definition.divisors[field][value]
        return value - 1 if field.endswith('IDIV') else int(math.log2(value))
    return None


def encode_pll_mul(macro_value, definition, field):
    """PLL multipliers: {field: raw} (RA8 splits the fraction into PLLMULNF)."""
    match = re.search(r'BSP_CLOCKS_PLL_MUL\((\d+)U?,\s*(\d+)U?\)', macro_value)
    if not match:
        return None
    whole, fraction = int(match.group(1)), int(match.group(2))
    if definition.mcu.upper().startswith('R7FA2A2'):  # RA2A2 FLL: x732 (24 MHz from SUBCLK) is code 158
        return {field: whole - 574}
    fraction_field = field.replace('MUL', 'MULNF')
    if fraction_field in definition.fields:
        if fraction not in MUL_FRACTION_CODES:
            return None
        return {field: whole - 1, fraction_field: MUL_FRACTION_CODES[fraction]}
    if field.startswith(('PLLCCR.', 'PLL2CCR.')):    # RA4/RA6 PLLCCR: x4.0/x10.0 upwards in 0.5 steps
        if fraction not in (0, 50):
            return None
        return {field: whole * 2 - 1 + (1 if fraction == 50 else 0)}
    if fraction:
        return None
    return {field: whole - 1}


def label_parts(node_element):
    displays = [option.get('display', '') for option in node_element.findall('option')]
    first = displays[0] if displays else node_element.get('id')
    base = re.sub(r'\$\{value\}\s*Hz', '', first).strip()
    base = re.split(r':|\s/\d|\sx\d|\sDiv\b|\sMul\b|\sDisabled\b|\sEnabled\b', base)[0].strip() or short(node_element.get('id'))
    return base


def option_label(display, base):
    text = re.sub(r'\$\{value\}\s*Hz', '', display or '').strip()
    for prefix in (base + ' Src:', base + ':', base + ' Div', base + ' Mul', base):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    return text or display


def convert_constraint(text, nodes, option_ids):
    expr = ' '.join(text.split())
    expr = re.sub(r'\$\{value:' + re.escape(PREFIX) + r'([a-z0-9._]+)\}', lambda m: f'f.{short(PREFIX + m.group(1))}', expr)
    expr = re.sub(r'"\$\{' + re.escape(PREFIX) + r'([a-z0-9._]+)\}"', lambda m: f'sel.{short(PREFIX + m.group(1))}', expr)
    expr = re.sub(r'\$\{' + re.escape(PREFIX) + r'([a-z0-9._]+)\}', lambda m: f'sel.{short(PREFIX + m.group(1))}', expr)

    def literal(match):
        full = match.group(1)
        if full in option_ids:
            return "'" + option_ids[full] + "'"
        return match.group(0)

    expr = re.sub(r'"(' + re.escape(PREFIX) + r'[a-z0-9._]+)"', literal, expr)
    expr = re.sub(r'"(-?\d+(?:\.\d+)?)"', r'\1', expr)
    expr = expr.replace('===', '==').replace('!==', '!=')
    # FSP's testOption(selection, 'option') is a selection comparison.
    expr = re.sub(r"testOption\(\s*(sel\.[a-z0-9_]+)\s*,\s*('[^']*')\s*\)", r'(\1 == \2)', expr)
    names = parse_expression(expr)
    if any(scope in ('f', 'sel') and name not in nodes for scope, name in names):
        raise ValueError('references a node that was not converted')
    return expr


def convert_family(family, xml_text, fsp_version, definition):
    root = ElementTree.fromstring(xml_text)
    clock = root.find('.//clock')
    if clock is None:
        return None, ['no <clock> section']
    notes = []
    nodes, option_ids, inputs = {}, {}, {}
    for element in clock.findall('node'):
        node_id = short(element.get('id'))
        base = label_parts(element)
        node = {'id': node_id, 'label': base, 'kind': 'output', 'x': int(element.get('xhint', 0)), 'y': int(element.get('yhint', 0))}
        if element.get('tooltip'):
            node['tooltip'] = element.get('tooltip').replace('\\n', '\n').strip()
        options = []
        bound = False
        for item in element.findall('option'):
            if item.get('id') == '_edit':
                inputs[node_id] = {'label': f'{base} frequency', 'default': int(element.get('default') or 0)}
                node['input'] = node_id
                node['kind'] = 'source'
                break
            full = item.get('id')
            option_id = short(full[len(element.get('id')) + 1:] if full.startswith(element.get('id') + '.') else full) or 'value'
            option_ids[full] = option_id
            option = {'id': option_id, 'label': option_label(item.get('display'), base)}
            source = item.get('input')
            if source and source != '0':
                option['from'] = short(source)
            if source == '0' or item.get('mul') == '0':
                option['mul'] = 0
            else:
                for key in ('mul', 'div'):
                    if item.get(key):
                        value = float(item.get(key))
                        option[key] = int(value) if value.is_integer() else value
            if item.get('minValue'):
                node['min'] = int(item.get('minValue'))
            if item.get('maxValue'):
                node['max'] = int(item.get('maxValue'))
            macro, value = item.get('macroName'), item.get('macroValue', '')
            writes = translate(family, macro, value, item.attrib, definition)
            if writes:
                option['set'] = {f'SYSTEM_{field}': hexv(definition.absolute(field, raw)) for field, raw in writes.items()}
                bound = True
            option['_macro'] = macro
            option['_disabled'] = 'CLOCK_DISABLED' in value
            options.append(option)
        if 'input' not in node:
            node['options'] = options
            node['_bound'] = bound
            if element.get('default') in option_ids:
                node['default'] = option_ids[element.get('default')]
        nodes[node_id] = node

    # Unbound choices cannot be configured: a choice between "disabled" and one clock becomes that
    # clock, other unbound choices (peripheral clocks without NECTO registers) are dropped with
    # everything that depends on them.
    for node in list(nodes.values()):
        options = node.get('options', [])
        if node.get('_bound'):
            dropped = [option['id'] for option in options if not option.get('set')]
            node['options'] = [option for option in options if option.get('set')]
            if dropped:
                notes.append(f'{node["id"]}: options without registers dropped: {", ".join(dropped)}')
            if node.get('default') not in {option['id'] for option in node['options']}:
                node.pop('default', None)
        elif len(options) > 1:
            real = [option for option in options if not option['_disabled']]
            if len(real) == 1:
                node['options'] = real
                node.pop('default', None)
            else:
                del nodes[node['id']]
    changed = True
    while changed:
        changed = False
        for node in list(nodes.values()):
            sources = [option.get('from') for option in node.get('options', []) if option.get('from')]
            kept = [option for option in node.get('options', []) if not option.get('from') or option['from'] in nodes]
            if 'options' in node and (not kept or len(kept) != len(node['options'])):
                if not kept:
                    del nodes[node['id']]
                    changed = True
                    continue
                node['options'] = kept
                changed = True
            if sources and not kept:
                del nodes[node['id']]
                changed = True

    users = {source for node in nodes.values() for option in node.get('options', []) for source in [option.get('from')] if source}
    for node in nodes.values():
        options = node.get('options')
        if options is not None:
            for option in options:
                option.pop('_macro', None)
                option.pop('_disabled', None)
            node.pop('_bound', None)
            froms = {option.get('from') for option in options}
            if node.get('kind') != 'source':
                if all(not option.get('from') for option in options):
                    node['kind'] = 'source'
                elif len(froms) > 1:
                    node['kind'] = 'mux'
                elif len(options) > 1 and all(option.get('mul', 1) / option.get('div', 1) <= 1 for option in options):
                    node['kind'] = 'divider'
                elif len(options) > 1 and all(option.get('mul', 1) / option.get('div', 1) >= 1 for option in options):
                    node['kind'] = 'multiplier'
                elif len(options) > 1:
                    node['kind'] = 'mux'
        # FSP names a divider and its output alike ("PCLKB"): say which is which.
        node['label'] = node['label'].replace(' Src', ' source')
        if len(node.get('options', [])) > 1:
            node['label'] = re.sub(r'\s[\d.]+\s*[kM]?Hz$', '', node['label'])
        if node['id'].endswith('_source') and 'source' not in node['label'].lower():
            node['label'] += ' source'
        suffix = {'divider': ' divider', 'multiplier': ' multiplier'}.get(node.get('kind'))
        if suffix and not node['label'].lower().endswith(suffix.strip()):
            node['label'] += suffix
        if node['id'] not in users and node.get('kind') == 'output':
            node['consumer'] = True
        if node['id'] in ENABLES:
            field, auto = ENABLES[node['id']]
            if field in definition.fields:
                node['enable'] = {'field': f'SYSTEM_{field}', 'on': hexv(0), 'off': hexv(definition.absolute(field, 1)), 'auto': auto}

    constraints = []
    for element in clock.findall('constraint'):
        message = element.get('display', '').strip()
        try:
            constraints.append({'expr': convert_constraint(element.text or '', nodes, option_ids), 'message': message})
        except ValueError as error:
            notes.append(f'constraint dropped ({error}): {message}')

    # Input bounds from constraints of the form f.xtal_freq <= N / >= N.
    for node_id, spec in inputs.items():
        for constraint in constraints:
            for op, number in re.findall(rf'f\.{node_id}\s*(<=|>=|<|>)\s*(\d+)', constraint['expr']):
                spec['max' if op.startswith('<') else 'min'] = int(number)
        spec.setdefault('min', 1)

    fosc = next((candidate for candidate in ('cpuclk_display', 'iclk_display') if candidate in nodes), None)
    if not fosc:
        return None, notes + ['no ICLK/CPUCLK output survived the conversion']
    graph = {
        'schema': 1, 'id': family, 'title': f'Renesas {family.upper()} clock tree', 'vendor': 'Renesas',
        'source': f'Renesas FSP {fsp_version} (BSD-3-Clause), Renesas##BSP##{family}##fsp####{fsp_version}.xml',
        'devices': [f'^R7[FK]A{family[2:].upper()}'], 'fosc': fosc, 'inputs': inputs, 'settings': [],
        'nodes': list(nodes.values()), 'constraints': constraints,
    }
    return graph, notes


def translate(family, macro, value, attrs, definition):
    """{field: raw} written by one FSP option, or None."""
    if not macro:
        return None
    if macro == 'BSP_CFG_CLOCK_SOURCE' and family.startswith('ra0'):
        code = re.fullmatch(r'\(?(\d+)\)?', value.strip())
        writes = RA0_ICLK.get(int(code.group(1))) if code else None
        return {field: raw for field, raw in (writes or {}).items() if field in definition.fields} or None
    spec = MACROS.get(macro)
    if not spec:
        return None
    kind, candidates = spec[0], spec[1]
    field = definition.pick(candidates)
    if kind == 'pllsource' and 'CLOCK_DISABLED' in value:
        stop = spec[2]
        return {stop: 1} if stop in definition.fields else None
    if kind == 'clkout':
        enable = 'CKOCR.CKOEN' if 'CKOCR.CKOEN' in definition.fields else None
        if 'CLOCK_DISABLED' in value:
            return {enable: 0} if enable else None
        raw = encode(kind, attrs, value, definition, field) if field else None
        if raw is None:
            return None
        return {field: raw, **({enable: 1} if enable else {})}
    if kind == 'pllsource':
        # Families without a PLL source select (RA4M1, RA4W1) run the PLL from the main oscillator.
        raw = encode(kind, attrs, value, definition, field) if field else None
        writes = {field: raw} if field and raw is not None else {}
        if field and raw is None:
            return None
        if spec[2] in definition.fields:
            writes[spec[2]] = 0
        return writes or None
    if not field:
        return None
    if kind == 'pllmul':
        return encode_pll_mul(value, definition, field)
    raw = encode(kind, attrs, value, definition, field)
    if raw is None:
        return None
    return {field: raw}


def find_definitions(root):
    """Family pattern -> first matching Definition (families share one register layout)."""
    files = sorted(path for path in Path(root).rglob('R7*.json') if 'def' in path.parts)
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--packs', required=True, help='folder with Renesas.RA_mcu_<family>.<version>.pack files')
    parser.add_argument('--defs', required=True, help='folder with RA NECTO definitions (def/R7FA*.json)')
    args = parser.parse_args()

    definition_files = find_definitions(args.defs)
    written = 0
    for pack in sorted(Path(args.packs).glob('Renesas.RA_mcu_*.pack')):
        match = re.match(r'Renesas\.RA_mcu_([a-z0-9]+)\.(\d+\.\d+\.\d+)\.pack$', pack.name)
        if not match:
            continue
        family, version = match.groups()
        pattern = re.compile(f'^R7[FK]A{family[2:].upper()}')
        definition_path = next((path for path in definition_files if pattern.match(path.stem)), None)
        if not definition_path:
            print(f'{family}: skipped, no NECTO definition')
            continue
        member = f'.module_descriptions/Renesas##BSP##{family}##fsp####{version}.xml'
        with zipfile.ZipFile(pack) as archive:
            if member not in archive.namelist():
                print(f'{family}: skipped, {member} not in pack')
                continue
            xml_text = archive.read(member).decode('utf-8')
        graph, notes = convert_family(family, xml_text, version, Definition(definition_path))
        if graph is None:
            print(f'{family}: skipped, {"; ".join(notes)}')
            continue
        problems = check_graph(graph)
        if problems:
            print(f'{family}: NOT written, {"; ".join(problems)}')
            continue
        write_graph(graph, f'renesas_ra/{family}.json')
        written += 1
        bound = sum(1 for node in graph['nodes'] if any(option.get('set') for option in node.get('options', [])))
        print(f'{family}: {len(graph["nodes"])} nodes ({bound} configurable), {len(graph["constraints"])} constraints, '
              f'fosc {graph["fosc"]}, checked against {definition_path.stem}')
        for note in notes:
            print(f'    {note}')
    print(f'Wrote {written} RA clock graphs to {(REPO_ROOT / "clock_graphs" / "renesas_ra").relative_to(REPO_ROOT)}')


if __name__ == '__main__':
    main()
