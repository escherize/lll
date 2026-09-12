import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import import_sidecar


class ImportAuthorityTest(unittest.TestCase):
    def test_existing_hosted_records_survive_conflicting_archive_states(self):
        for hosted, archived in [('done', 'To Do'), ('in-progress', 'Done'), ('cancelled', 'In Progress')]:
            with self.subTest(hosted=hosted), tempfile.TemporaryDirectory() as temp:
                records = [{'number': 7, 'state': hosted, 'description': 'Current text\nOrigin: sidecar TASK-1',
                            'blocked_by': ['keep-this'], 'title': 'Current title'}]
                before = json.dumps(records, sort_keys=True)
                calls = self.invoke(temp, records, archived)
                self.assertEqual(calls, [])
                self.assertEqual(json.dumps(records, sort_keys=True), before)

    def test_new_record_gets_historical_state_then_rerun_preserves_hosted_change(self):
        with tempfile.TemporaryDirectory() as temp:
            records = []
            calls = self.invoke(temp, records, 'Done')
            self.assertEqual(calls[-1], ['issue', 'update', 'LLL-99', '--state', 'done'])
            self.assertEqual(records[0]['state'], 'done')
            records[0]['state'] = 'in-progress'
            self.assertEqual(self.invoke(temp, records, 'Done'), [])
            self.assertEqual(records[0]['state'], 'in-progress')

    def invoke(self, temp, records, status):
        root = Path(temp)
        (root / 'backlog/tasks').mkdir(parents=True, exist_ok=True)
        binary = root / 'lll'
        binary.touch()
        calls = []
        class CLI:
            def run(self, args, stdin=None):
                calls.append(args)
                if args[:2] == ['issue', 'create']:
                    record = {'number': 99, 'state': 'todo', 'description': stdin}
                    records.append(record)
                    return json.dumps(record)
                if args[:2] == ['issue', 'update']:
                    records[0]['state'] = args[-1]
                    return ''
                raise AssertionError(f'unexpected write: {args}')
        def read(_url, _token, collection, _filter=''):
            return {'teams': [{'key': 'LLL'}], 'issues': records}.get(collection, [])
        task = (1, {'id': 'TASK-1', 'title': 'Archive title', 'status': status}, 'Archive body', 'task.md')
        with patch.dict(os.environ, {'LLL_TOKEN': 'fixture'}), \
             patch('sys.argv', ['import_sidecar.py', '--url', 'https://fixture.invalid', '--private', temp, '--lll', str(binary)]), \
             patch.object(import_sidecar, 'pb_list', side_effect=read), \
             patch.object(import_sidecar, 'Lll', return_value=CLI()), \
             patch.object(import_sidecar, 'load_tasks', return_value=[task]), \
             patch.object(import_sidecar, 'load_milestones', return_value={}), \
             patch.object(import_sidecar, 'load_docs', return_value=[]), \
             contextlib.redirect_stdout(io.StringIO()):
            import_sidecar.main()
        return calls
