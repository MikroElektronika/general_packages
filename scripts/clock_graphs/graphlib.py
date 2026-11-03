"""Shared helpers for clock graph generators and the validator (see clock_graphs/README.md)."""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPHS_ROOT = REPO_ROOT / 'clock_graphs'
NODE_ID = re.compile(r'^[a-z0-9_]+$')
KINDS = {'source', 'mux', 'divider', 'multiplier', 'output'}


def hexv(value):
    """Absolute register value as the 8-digit hex string NECTO definitions use."""
    return f'{int(value) & 0xFFFFFFFF:08X}'


def dump_graph(graph):
    """Pretty JSON with one line per option, constraint and variant, so diffs stay readable."""
    def compact(value):
        return json.dumps(value, separators=(', ', ': '))

    lines = ['{']
    keys = list(graph)
    for index, key in enumerate(keys):
        comma = ',' if index < len(keys) - 1 else ''
        value = graph[key]
        if key == 'nodes':
            lines.append('  "nodes": [')
            for node_index, node in enumerate(value):
                node_comma = ',' if node_index < len(value) - 1 else ''
                fields = list(node)
                lines.append('    {')
                for field_index, field in enumerate(fields):
                    field_comma = ',' if field_index < len(fields) - 1 else ''
                    if field == 'options':
                        lines.append('      "options": [')
                        lines.extend(f'        {compact(option)}{"," if option_index < len(node[field]) - 1 else ""}'
                                     for option_index, option in enumerate(node[field]))
                        lines.append(f'      ]{field_comma}')
                    else:
                        lines.append(f'      {json.dumps(field)}: {compact(node[field])}{field_comma}')
                lines.append(f'    }}{node_comma}')
            lines.append(f'  ]{comma}')
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            lines.append(f'  {json.dumps(key)}: [')
            lines.extend(f'    {compact(item)}{"," if item_index < len(value) - 1 else ""}' for item_index, item in enumerate(value))
            lines.append(f'  ]{comma}')
        elif isinstance(value, dict) and value:
            lines.append(f'  {json.dumps(key)}: {{')
            items = list(value.items())
            lines.extend(f'    {json.dumps(name)}: {compact(item)}{"," if item_index < len(items) - 1 else ""}'
                         for item_index, (name, item) in enumerate(items))
            lines.append(f'  }}{comma}')
        else:
            lines.append(f'  {json.dumps(key)}: {compact(value)}{comma}')
    lines.append('}')
    text = '\n'.join(lines) + '\n'
    assert json.loads(text) == graph
    return text


def write_graph(graph, relative_path):
    path = GRAPHS_ROOT / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_graph(graph), encoding='utf-8')
    return path


def load_graphs():
    """Every graph file under clock_graphs/, keyed by its path relative to clock_graphs/."""
    graphs = {}
    for path in sorted(GRAPHS_ROOT.rglob('*.json')):
        if path.name in ('manifest.json', 'index.json'):
            continue
        graphs[path.relative_to(GRAPHS_ROOT).as_posix()] = json.loads(path.read_text(encoding='utf-8'))
    return graphs


# ---------------------------------------------------------------------------------------------
# Expressions: the same grammar the extension evaluates (media/clock_graph.js).

TOKEN = re.compile(r"""\s*(?:
    (?P<number>0x[0-9a-fA-F]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?) |
    (?P<string>'[^']*'|"[^"]*") |
    (?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)?) |
    (?P<op>&&|\|\||==|!=|<=|>=|[-+*/%<>!(),])
)""", re.VERBOSE)


def tokenize(text):
    tokens, position = [], 0
    text = str(text)
    while position < len(text):
        if text[position:].strip() == '':
            break
        match = TOKEN.match(text, position)
        if not match or match.end() == position:
            raise ValueError(f'unexpected character at {position}: {text[position:position + 12]!r}')
        position = match.end()
        kind = match.lastgroup
        tokens.append((kind, match.group(kind)))
    return tokens


BINARY = [['||'], ['&&'], ['==', '!='], ['<', '<=', '>', '>='], ['+', '-'], ['*', '/', '%']]


def parse_expression(text):
    """Parse an expression; returns the set of names it references. Raises ValueError."""
    tokens = tokenize(text)
    names = set()
    position = 0

    def peek():
        return tokens[position] if position < len(tokens) else (None, None)

    def take(expected=None):
        nonlocal position
        token = peek()
        if token[0] is None or (expected is not None and token[1] != expected):
            raise ValueError(f'expected {expected or "a value"} in {text!r}')
        position += 1
        return token

    def level(index):
        if index == len(BINARY):
            return unary()
        level(index + 1)
        while peek()[0] == 'op' and peek()[1] in BINARY[index]:
            take()
            level(index + 1)

    def unary():
        if peek() == ('op', '!') or peek() == ('op', '-'):
            take()
            return unary()
        return primary()

    def primary():
        kind, value = take()
        if kind in ('number', 'string'):
            return
        if kind == 'op' and value == '(':
            level(0)
            take(')')
            return
        if kind == 'name':
            if value == 'reg':
                take('(')
                field_kind, field = take()
                if field_kind != 'string':
                    raise ValueError(f'reg() takes a quoted field name in {text!r}')
                names.add(('reg', field.strip('\'"')))
                take(')')
                return
            scope, _, name = value.partition('.')
            if scope not in ('f', 'sel', 'in') or not name:
                raise ValueError(f'unknown name {value!r} in {text!r}')
            names.add((scope, name))
            return
        raise ValueError(f'unexpected {value!r} in {text!r}')

    level(0)
    if position != len(tokens):
        raise ValueError(f'unexpected {tokens[position][1]!r} in {text!r}')
    return names


# ---------------------------------------------------------------------------------------------
# Structure checks shared by the generators and validate.py.

def check_graph(graph):
    """Structural problems of one graph, as a list of strings (empty when valid)."""
    problems = []
    nodes = {node.get('id'): node for node in graph.get('nodes', [])}
    if graph.get('schema') != 1:
        problems.append('schema must be 1')
    for key in ('id', 'title', 'vendor', 'devices', 'fosc', 'nodes'):
        if not graph.get(key):
            problems.append(f'missing {key}')
    for pattern in graph.get('devices', []):
        try:
            re.compile(pattern)
        except re.error as error:
            problems.append(f'bad devices pattern {pattern!r}: {error}')
    if graph.get('fosc') not in nodes:
        problems.append(f'fosc {graph.get("fosc")!r} is not a node')
    if len(nodes) != len(graph.get('nodes', [])):
        problems.append('duplicate node ids')

    def check_names(text, where):
        try:
            for scope, name in parse_expression(text):
                if scope in ('f', 'sel') and name not in nodes:
                    problems.append(f'{where}: unknown node {name!r}')
                if scope == 'in' and name not in graph.get('inputs', {}):
                    problems.append(f'{where}: unknown input {name!r}')
        except ValueError as error:
            problems.append(f'{where}: {error}')

    for node_id, node in nodes.items():
        where = f'node {node_id}'
        if not NODE_ID.match(str(node_id)):
            problems.append(f'{where}: id must match [a-z0-9_]+')
        if node.get('kind') not in KINDS:
            problems.append(f'{where}: kind must be one of {sorted(KINDS)}')
        sources = [key for key in ('options', 'range', 'input') if key in node]
        if len(sources) != 1:
            problems.append(f'{where}: needs exactly one of options, range, input')
        if 'input' in node and node['input'] not in graph.get('inputs', {}):
            problems.append(f'{where}: input {node["input"]!r} is not in inputs')
        option_ids = set()
        for option in node.get('options', []):
            if option.get('id') in option_ids:
                problems.append(f'{where}: duplicate option {option.get("id")!r}')
            option_ids.add(option.get('id'))
            if option.get('from') is not None and option['from'] not in nodes:
                problems.append(f'{where}: option {option.get("id")} reads unknown node {option["from"]!r}')
            for kept in option.get('keeps', []):
                if kept not in nodes:
                    problems.append(f'{where}: option {option.get("id")} keeps unknown node {kept!r}')
            for field, value in (option.get('set') or {}).items():
                if not re.match(r'^[0-9A-F]{8}$', str(value)):
                    problems.append(f'{where}: {field} value {value!r} must be 8 hex digits')
        if 'range' in node:
            spec = node['range']
            if spec.get('from') not in nodes:
                problems.append(f'{where}: range reads unknown node {spec.get("from")!r}')
            if spec.get('op') not in ('mul', 'div'):
                problems.append(f'{where}: range op must be mul or div')
            if not (isinstance(spec.get('min'), int) and isinstance(spec.get('max'), int) and spec['min'] <= spec['max']):
                problems.append(f'{where}: range needs integer min <= max')
        if node.get('default') is not None and node.get('options') and node['default'] not in option_ids:
            problems.append(f'{where}: default {node["default"]!r} is not an option')
        if node.get('enable'):
            enable = node['enable']
            if enable.get('auto') not in ('both', 'on'):
                problems.append(f'{where}: enable.auto must be both or on')
            for key in ('on', 'off'):
                if not re.match(r'^[0-9A-F]{8}$', str(enable.get(key, ''))):
                    problems.append(f'{where}: enable.{key} must be 8 hex digits')
        if node.get('bypass'):
            check_names(node['bypass'], f'{where} bypass')
    for index, rule in enumerate(graph.get('derive', [])):
        for case in rule.get('cases', []):
            check_names(case.get('when', ''), f'derive {rule.get("field")} #{index}')
    for constraint in graph.get('constraints', []):
        check_names(constraint.get('expr', ''), f'constraint {constraint.get("message")!r}')
    for variant in graph.get('variants', []):
        for node_id in (variant.get('limits') or {}):
            if node_id not in nodes:
                problems.append(f'variant {variant.get("devices")}: unknown node {node_id!r}')
        for constraint in variant.get('constraints', []):
            check_names(constraint.get('expr', ''), f'variant constraint {constraint.get("message")!r}')
    # Every option/range input must be reachable without cycles.
    state = {}

    def visit(node_id, trail):
        if state.get(node_id) == 'done':
            return
        if state.get(node_id) == 'open':
            problems.append(f'cycle through {" -> ".join(trail + [node_id])}')
            return
        state[node_id] = 'open'
        node = nodes[node_id]
        inputs = [option.get('from') for option in node.get('options', [])] + [node.get('range', {}).get('from')]
        for source in filter(None, inputs):
            if source in nodes:
                visit(source, trail + [node_id])
        state[node_id] = 'done'

    for node_id in nodes:
        visit(node_id, [])
    return problems


def bound_fields(graph):
    """Every register field id a graph can write (alternatives split)."""
    fields = set()
    for node in graph.get('nodes', []):
        for option in node.get('options', []):
            fields.update(option.get('set', {}).keys())
        if node.get('range'):
            fields.add(node['range']['field'])
        if node.get('enable'):
            fields.add(node['enable']['field'])
    fields.update(rule['field'] for rule in graph.get('derive', []))
    return {alternative for field in fields for alternative in field.split('|')}
