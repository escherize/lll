import unittest

from migrate_sidecar_dependencies import plan


def issue(number, origin, dependencies='', blocked=()):
    return {'id': str(number), 'number': number, 'description': f'{dependencies}\nOrigin: sidecar {origin}', 'blocked_by': list(blocked)}


class DependencyPlanTest(unittest.TestCase):
    def test_origin_mapping_not_issue_numbers_and_idempotency(self):
        rows = [issue(40, 'TASK-2', 'Blocked by TASK-9\nBlocked by TASK-9'), issue(7, 'TASK-9')]
        self.assertEqual(plan(rows, 'LLL'), [('LLL-40', 'LLL-7', 'TASK-9')])
        rows[0]['blocked_by'] = ['7', 'unrelated']
        self.assertEqual(plan(rows, 'LLL'), [])
        self.assertEqual(rows[0]['blocked_by'], ['7', 'unrelated'])

    def test_only_imported_exact_dependency_lines(self):
        rows = [issue(1, 'TASK-1', 'Discuss Blocked by TASK-99\n> Blocked by TASK-98'),
                {'id': '2', 'number': 2, 'description': 'Blocked by TASK-99'}]
        self.assertEqual(plan(rows, 'LLL'), [])

    def test_missing_and_ambiguous_origins_refuse(self):
        for rows in ([issue(1, 'TASK-1', 'Blocked by TASK-9')],
                     [issue(1, 'TASK-1'), issue(2, 'TASK-1')],
                     [issue(1, 'TASK-1', 'Origin: sidecar TASK-2')]):
            with self.assertRaises(ValueError):
                plan(rows, 'LLL')

    def test_self_reference_and_cycles_refuse_before_writes(self):
        for rows in ([issue(1, 'TASK-1', 'Blocked by TASK-1')],
                     [issue(1, 'TASK-1', 'Blocked by TASK-2'), issue(2, 'TASK-2', blocked=['1'])]):
            with self.assertRaisesRegex(ValueError, 'cycle'):
                plan(rows, 'LLL')
