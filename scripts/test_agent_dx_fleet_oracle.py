#!/usr/bin/env python3
"""Reject adversarial false positives in the independent fleet oracle."""
import copy
from agent_dx_fleet import COLLECTIONS, Instance

def exercise_oracle(root):
    i = Instance.__new__(Instance)
    i.worker = root / 'oracle'
    i.worker.mkdir()
    i.number, i.bot_id, i.target = '01', 'bot', 'target'
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
        return i.judge(case)
    assert judge('01')['pass'] and judge('05')['pass']
    assert not judge('01', lambda a: a['comments'][0].update(author='wrong'))['pass']
    assert not judge('01', lambda a: a['comments'].append({'id': 'extra', 'body': 'unmatched'}))['pass']
    assert not judge('01', lambda a: a['issues'][0].update(title='changed'))['pass']
    assert not judge('01', lambda a: a['webhooks'].append({'id': 'extra-hook', 'secret': 'fixture'}))['pass']
    assert not judge('05', lambda a: a['issues'].append({'id': 'wrong-title-duplicate', 'title': 'Unmatched'}))['pass']
    for field, value in [('creator','wrong'),('state','done'),('priority',3),('labels',[]),('project',''),('description','changed')]:
        assert not judge('05', lambda a, f=field, v=value: a['issues'][1].update({f:v}))['pass'], field
    assert i.before['issues'][0]['title'] == 'Seed'
    print('Fleet oracle: exact artifacts accepted; wrong author/creator/fields, unmatched duplicates, seed edits and extra webhooks rejected.')

if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory(prefix="lll-fleet-oracle-") as directory:
        exercise_oracle(Path(directory))
