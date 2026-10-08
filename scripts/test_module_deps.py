"""The board does not depend on the CLI (LLL-659).

The web board lived in src/commands beside the verbs and called their
private helpers in both directions, so neither half could change, or be
tested, without the other. It now lives in src/serve, and the dependencies
point one way:

    main -> commands -> serve -> (records, writes, tokens, display, ...)

This test holds that shape, reading the `import "..."` lines of every .lis
file, tests included (a test compiles into its module's package):

- only src/main.lis imports `commands`;
- nothing outside src/main.lis and src/commands imports `serve`;
- the module graph has no cycle.

A helper both halves need belongs in the module that owns its subject
(records, writes, tokens, display, ...), not in commands.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
IMPORT = re.compile(r'^import "([a-z_]+)"\s*$', re.M)


def module_of(rel):
    parts = rel.split('/')
    return parts[1] if len(parts) > 2 else 'main'


def imports(root=ROOT):
    """[(rel path, module, imported local module)] for every .lis file."""
    found = []
    for path in sorted((root / 'src').rglob('*.lis')):
        rel = path.relative_to(root).as_posix()
        for name in IMPORT.findall(path.read_text()):
            found.append((rel, module_of(rel), name))
    return found


def violations(edges):
    found = []
    for rel, module, name in edges:
        if name == 'commands' and module != 'main':
            found.append(f'{rel}: imports commands; only src/main.lis may')
        if name == 'serve' and module not in ('main', 'commands'):
            found.append(f'{rel}: imports serve; only commands (lll up) starts the board')
    graph = {}
    for _, module, name in edges:
        if name != module:
            graph.setdefault(module, set()).add(name)
    found += [f'import cycle: {" -> ".join(c)}' for c in cycles(graph)]
    return found


def cycles(graph):
    """One witness path per cycle found by a depth-first walk."""
    out, state = [], {}

    def walk(node, path):
        state[node] = 'open'
        for nxt in sorted(graph.get(node, ())):
            if state.get(nxt) == 'open':
                out.append(path[path.index(nxt):] + [nxt])
            elif nxt not in state:
                walk(nxt, path + [nxt])
        state[node] = 'done'

    for node in sorted(graph):
        if node not in state:
            walk(node, [node])
    return out


class ModuleDepsTest(unittest.TestCase):
    def test_the_board_does_not_depend_on_the_cli(self):
        found = violations(imports())
        self.assertEqual(found, [], 'module dependency rule broken (move the shared helper to the module that owns it):\n' + '\n'.join(found))

    def test_the_board_module_exists_and_is_started_by_commands(self):
        edges = imports()
        self.assertTrue(any(m == 'serve' for _, m, _ in edges), 'src/serve has no imports: did the board move?')
        self.assertIn(('commands', 'serve'), {(m, n) for _, m, n in edges})

    def test_the_check_sees_planted_violations(self):
        planted = [
            [('src/serve/gate.lis', 'serve', 'commands')],
            [('src/serve/gate.test.lis', 'serve', 'commands')],
            [('src/records/x.lis', 'records', 'commands')],
            [('src/records/x.lis', 'records', 'serve')],
            [('src/tokens/x.lis', 'tokens', 'records'), ('src/records/y.lis', 'records', 'tokens')],
        ]
        for edges in planted:
            self.assertTrue(violations(edges), edges)
        clean = [
            ('src/main.lis', 'main', 'commands'),
            ('src/commands/up.lis', 'commands', 'serve'),
            ('src/serve/gate.lis', 'serve', 'records'),
            ('src/records/x.lis', 'records', 'pb'),
        ]
        self.assertEqual(violations(clean), [])


if __name__ == '__main__':
    unittest.main()
