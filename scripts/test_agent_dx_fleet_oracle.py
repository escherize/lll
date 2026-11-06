#!/usr/bin/env python3
"""Reject adversarial false positives in the independent fleet oracle."""
import copy
import json
from agent_dx_fleet import COLLECTIONS, Board, Seat, audit_path, private_dir, private_write, judge_17, diff

def exercise_oracle(root):
    i = Board.__new__(Board)
    seat = Seat(root / 'oracle' / '01', '01')
    seat.worker.mkdir(parents=True)
    seat.member_id = 'bot'
    i.seats = [seat]
    i.binary = root / 'lll'
    audit = audit_path(i.binary, seat.worker)
    private_dir(audit.parent)
    private_write(audit, '')
    i.target = 'target'
    i.team, i.bug, i.project = 'team', 'bug', 'project'
    i.before = {name: [] for name in COLLECTIONS}
    i.before['issues'] = [{'id': 'target', 'title': 'Seed', 'state': 'todo'}]
    comment = {'id': 'comment', 'issue': 'target', 'author': 'bot',
               'body': 'fleet-01-01: A socket reset made the retry skip the comment; preserve one comment and report the saved result.'}
    issue = {'id': 'new', 'team': 'team', 'creator': 'bot', 'state': 'todo', 'priority': 2,
             'title': 'Repair flaky upload retry (worker 01)',
             'description': 'Retry a dropped upload once and preserve the saved attachment.',
             'labels': ['bug'], 'project': 'project'}
    def judge(case, mutate=None):
        after = copy.deepcopy(i.before)
        after['comments' if case == '01' else 'issues'].append(copy.deepcopy(comment if case == '01' else issue))
        if mutate: mutate(after)
        i.snapshot = lambda: after
        i.case = case
        return i.judge()
    assert judge('01')['pass'] and judge('06')['pass']
    assert not judge('01', lambda a: a['comments'][0].update(author='wrong'))['pass']
    assert not judge('01', lambda a: a['comments'].append({'id': 'extra', 'body': 'unmatched'}))['pass']
    assert not judge('01', lambda a: a['issues'][0].update(title='changed'))['pass']
    assert not judge('01', lambda a: a['webhooks'].append({'id': 'extra-hook', 'secret': 'fixture'}))['pass']
    assert not judge('06', lambda a: a['issues'].append({'id': 'wrong-title-duplicate', 'title': 'Unmatched'}))['pass']
    for field, value in [('creator','wrong'),('state','done'),('priority',3),('labels',[]),('project',''),('description','changed')]:
        assert not judge('06', lambda a, f=field, v=value: a['issues'][1].update({f:v}))['pass'], field
    assert i.before['issues'][0]['title'] == 'Seed'
    # Correct final descriptions alone must not pass the guarded race case.
    pair = Board.__new__(Board)
    pair.binary = root / 'pair-controller' / 'lll'
    pair.seats = [Seat(root / 'case-17-run-1' / n, n) for n in ('01', '02')]
    pair.fixtures = {'issue': 'append', 'guarded': 'guarded'}
    pair.before = {name: [] for name in COLLECTIONS}
    pair.before['issues'] = [{'id': name, 'number': n, 'updated': '2026-11-06 00:00:00.000Z',
                              'description': 'Release notes:'} for n, name in enumerate(('append', 'guarded'), 1)]
    after = copy.deepcopy(pair.before)
    for issue in after['issues']:
        issue['description'] += '\nfleet-17-01: role A checked the upload path.\nfleet-17-02: role B checked the upload path.'
    changes = diff(pair.before, after)
    audits = []
    for index, seat in enumerate(pair.seats):
        seat.worker.mkdir(parents=True)
        path = audit_path(pair.binary, seat.worker)
        private_dir(path.parent)
        command = ['lll', 'issue', 'update', 'FLEET-2', '--description=body',
                   '--if-unchanged-since=2026-11-06T00:00:00Z']
        calls = [{'command': command, 'exit_code': 0 if index == 0 else 4, 'stdout': '', 'stderr': ''}]
        if index:
            calls.append({'command': command, 'exit_code': 0, 'stdout': '', 'stderr': ''})
        audits.append((path, calls))
        private_write(path, ''.join(json.dumps(call) + '\n' for call in calls))
        for stage in ('append', 'guarded'):
            directory = pair.binary.parent / 'barriers' / seat.worker.parent.name / '01' / stage
            private_dir(directory)
            private_write(directory / f'{seat.number}.arrived', '1')
            private_write(directory / f'{seat.number}.released', '2')
    assert judge_17(pair, changes, after) == []
    path, valid = audits[0]
    for omitted in ('--if-unchanged-since=', '--description='):
        bad = copy.deepcopy(valid)
        bad[0]['command'] = [arg for arg in bad[0]['command'] if not arg.startswith(omitted)]
        private_write(path, ''.join(json.dumps(call) + '\n' for call in bad))
        assert judge_17(pair, changes, after), f'accepted missing {omitted} with correct artifacts'
    private_write(path, ''.join(json.dumps(call) + '\n' for call in valid))
    directory = pair.binary.parent / 'barriers' / pair.seats[0].worker.parent.name / '01' / 'guarded'
    private_write(directory / '01.released', '0')
    assert any('before both readers' in error for error in judge_17(pair, changes, after))
    print('Fleet oracle: exact artifacts accepted; wrong author/creator/fields, unmatched duplicates, seed edits and extra webhooks rejected.')

if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory(prefix="lll-fleet-oracle-") as directory:
        exercise_oracle(Path(directory))
