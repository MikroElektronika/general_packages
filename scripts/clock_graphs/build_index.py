"""Write clock_graphs/index.json: which graph serves which MCU names.

  python scripts/clock_graphs/build_index.py
"""

import json

from graphlib import GRAPHS_ROOT, load_graphs


def build_index(graphs):
    entries = [{'id': graph['id'], 'file': relative, 'vendor': graph['vendor'], 'title': graph['title'], 'devices': graph['devices']}
               for relative, graph in sorted(graphs.items())]
    return {'schema': 1, 'graphs': entries}


def main():
    index = build_index(load_graphs())
    (GRAPHS_ROOT / 'index.json').write_text(json.dumps(index, indent=2) + '\n', encoding='utf-8')
    print(f'Indexed {len(index["graphs"])} clock graphs in clock_graphs/index.json')


if __name__ == '__main__':
    main()
