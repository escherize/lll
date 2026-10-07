#!/usr/bin/env python3
"""LLL-620: release_check's table and exit-code logic, with stubbed answers.

No network, no git, no servers: each judge gets the shape the real source
(gh, the hosted board, the CLI) returns, including the failing ones.
"""
from pathlib import Path
import unittest

import release_check as rc
from release_check import FAIL, PASS, WARN, Row


def issue(number, state, priority=0, title='t'):
    return {'number': number, 'state': state, 'priority': priority, 'title': title,
            'expand': {'team': {'key': 'LLL'}}}


JOBS = [{'name': 'gate', 'conclusion': 'success'},
        {'name': 'Linux container and browser gate', 'conclusion': 'success'},
        {'name': rc.DEPLOY_JOB, 'conclusion': 'success'}]
RUN = {'databaseId': 7, 'status': 'completed', 'conclusion': 'success', 'url': 'u', 'createdAt': 'x'}


class ExitCode(unittest.TestCase):
    def test_fail_exits_nonzero_warn_does_not(self):
        self.assertEqual(rc.exit_code([Row('2', 'a', PASS, ''), Row('3', 'b', WARN, '')]), 0)
        self.assertEqual(rc.exit_code([Row('2', 'a', PASS, ''), Row('3', 'b', FAIL, '')]), 1)
        self.assertEqual(rc.exit_code([]), 0)

    def test_summary_counts(self):
        rows = [Row('2', 'a', PASS, ''), Row('3', 'b', WARN, ''), Row('4', 'c', FAIL, '')]
        self.assertEqual(rc.summary(rows), 'release-check: 1 PASS, 1 WARN, 1 FAIL -> exit 1')

    def test_render_escapes_pipes_and_flattens_newlines(self):
        table = rc.render([Row('2', 'a|b', FAIL, 'line one\nline | two')])
        self.assertEqual(table.splitlines()[2], '| 2 | a\\|b | FAIL | line one line \\| two |')


class Args(unittest.TestCase):
    def test_cut_required_and_key_value_only(self):
        self.assertEqual(rc.parse_args(['CUT=abc']), {'CUT': 'abc'})
        for bad in [[], ['abc'], ['CUT='], ['NOPE=1', 'CUT=a'], ['CUT=a', 'BOARD_URL=http://x']]:
            with self.assertRaises(ValueError, msg=bad):
                rc.parse_args(bad)
        self.assertEqual(rc.parse_args(['CUT=a', 'BOARD_URL=u', 'BOARD_TEAM=T'])['BOARD_TEAM'], 'T')

    def test_asset_names_match_release_yml(self):
        self.assertEqual(rc.asset_name('Darwin', 'arm64'), 'lll-darwin-arm64')
        self.assertEqual(rc.asset_name('Linux', 'x86_64'), 'lll-linux-amd64')
        self.assertEqual(rc.asset_name('Linux', 'aarch64'), 'lll-linux-arm64')


class Step2(unittest.TestCase):
    def test_cut_not_on_main_fails(self):
        self.assertEqual(rc.judge_on_main('a' * 40, False, 'b' * 40).status, FAIL)
        self.assertEqual(rc.judge_on_main('a' * 40, True, 'b' * 40).status, PASS)

    def test_gate_run(self):
        self.assertEqual(rc.judge_gate_run([RUN], JOBS).status, PASS)
        self.assertEqual(rc.judge_gate_run([], None).status, FAIL)
        self.assertEqual(rc.judge_gate_run([dict(RUN, status='in_progress')], JOBS).status, FAIL)
        skipped = JOBS[:2] + [{'name': rc.DEPLOY_JOB, 'conclusion': 'skipped'}]
        row = rc.judge_gate_run([dict(RUN, conclusion='success')], skipped)
        self.assertEqual(row.status, FAIL)
        self.assertIn(f'{rc.DEPLOY_JOB}=skipped', row.evidence)
        self.assertEqual(rc.judge_gate_run([RUN], JOBS[:2]).status, FAIL, 'a run with no deploy job is not deployed')

    def test_discovery(self):
        self.assertEqual(rc.judge_discovery('u', {'service': 'lll', 'version': '1.0.0'}, '1.0.0').status, PASS)
        self.assertEqual(rc.judge_discovery('u', {'service': 'lll', 'version': '1.0.1'}, '1.0.0').status, WARN)
        self.assertEqual(rc.judge_discovery('u', {'service': 'lll'}, '1.0.0').status, FAIL)
        self.assertEqual(rc.judge_discovery('u', {'service': 'other', 'version': '1'}, '1').status, FAIL)

    def test_whoami_needs_an_access_line(self):
        out = 'me <me@x>\nserver  u\naccess  read-write, every team (server-wide)\n'
        self.assertEqual(rc.judge_whoami(0, out, '').status, PASS)
        self.assertEqual(rc.judge_whoami(0, 'me <me@x>\n', '').status, FAIL)
        self.assertEqual(rc.judge_whoami(1, out, 'boom').status, FAIL)

    def test_guest_refusal(self):
        err = "Error: no team 'OTHER' among the teams you can see (SCRAT)."
        self.assertEqual(rc.judge_guest_refusal(1, '', err).status, PASS)
        self.assertEqual(rc.judge_guest_refusal(0, 'no issues', '').status, FAIL, 'a guest that can list OTHER leaks')
        self.assertEqual(rc.judge_guest_refusal(1, '', 'connection refused').status, FAIL)


class Step3(unittest.TestCase):
    def test_in_review_security_issue_fails(self):
        rows = rc.judge_security(['security'], [issue(9, 'in-review')], [issue(9, 'in-review')])
        self.assertEqual([r.status for r in rows], [PASS, FAIL, PASS])
        self.assertIn('LLL-9 in-review', rows[1].evidence)
        self.assertEqual(rc.exit_code(rows), 1)

    def test_open_urgent_or_high_warns_only(self):
        open_issues = [issue(1, 'todo', 1), issue(2, 'backlog', 2), issue(3, 'todo', 3), issue(4, 'todo', 0)]
        rows = rc.judge_security(['security'], [], open_issues)
        self.assertEqual([r.status for r in rows], [PASS, PASS, WARN])
        self.assertIn('LLL-1 urgent', rows[2].evidence)
        self.assertIn('LLL-2 high', rows[2].evidence)
        self.assertNotIn('LLL-3', rows[2].evidence)
        self.assertEqual(rc.exit_code(rows), 0)

    def test_quiet_board_passes(self):
        self.assertEqual([r.status for r in rc.judge_security(['security', 'bug'], [], [])], [PASS, PASS, PASS])

    def test_missing_label_warns(self):
        rows = rc.judge_security(['bug'], [], [])
        self.assertEqual([r.status for r in rows], [WARN])

    def test_full_page_is_flagged_as_possibly_truncated(self):
        rows = rc.judge_security(['security'], [], [issue(n, 'todo', 3) for n in range(rc.SECURITY_LIMIT)])
        self.assertIn('truncated', rows[2].evidence)


class Step4(unittest.TestCase):
    def test_commands_pass_only_when_all_exit_zero(self):
        ok = [(['whoami'], 0, 'me', ''), (['issue', 'list', '--limit', '5'], 0, '', ''),
              (['issue', 'claim', 'S-1'], 0, 'Claimed', '')]
        row = rc.judge_commands('c', ok, 'v')
        self.assertEqual(row.status, PASS)
        self.assertIn('whoami, issue list, issue claim', row.evidence)
        bad = ok[:2] + [(['issue', 'claim', 'S-1'], 1, '', 'unknown route')]
        row = rc.judge_commands('c', bad, 'v')
        self.assertEqual(row.status, FAIL)
        self.assertIn('`lll issue claim S-1` exit 1: unknown route', row.evidence)

    def test_skew(self):
        warn = 'lll: this lll is 0.6.1; http://x runs 99.0.0, which may ... Upgrade: lll upgrade'
        self.assertEqual(rc.judge_skew('0.6.1', warn, '').status, PASS)
        self.assertEqual(rc.judge_skew('0.6.1', '', '').status, FAIL)
        self.assertEqual(rc.judge_skew('0.6.1', warn, warn).status, FAIL)

    def test_upgrade(self):
        asset = 'lll-darwin-arm64'
        out = ('lll was installed from a release download; lll does not replace its own binary. Run:\n'
               f'  curl -LsSf -o /h/bin/lll https://github.com/escherize/lll/releases/latest/download/{asset} && chmod +x /h/bin/lll\n')
        self.assertEqual(rc.judge_upgrade(out, asset, [asset]).status, PASS)
        self.assertEqual(rc.judge_upgrade(out, asset, None).status, WARN)
        self.assertEqual(rc.judge_upgrade(out, asset, ['lll-linux-amd64']).status, FAIL)
        self.assertEqual(rc.judge_upgrade('cd repo && git pull && mise run build', asset, [asset]).status, FAIL)

    def test_isolation(self):
        path = Path('/home/.config/lll/lll.toml')
        before = [('lll.toml', 1, 'h'), ('version-checks', 1, '')]
        self.assertEqual(rc.judge_isolation(before, list(before), path).status, PASS)
        row = rc.judge_isolation(before, before + [('version-checks/127.0.0.1_1', 2, 'x')], path)
        self.assertEqual(row.status, FAIL)
        self.assertIn('version-checks/127.0.0.1_1', row.evidence)


class Attempt(unittest.TestCase):
    def test_an_exception_is_that_checks_fail(self):
        rows = []
        rc.attempt(rows, '4', 'boom', lambda: (_ for _ in ()).throw(RuntimeError('scratch did not start')))
        self.assertEqual(rows, [Row('4', 'boom', FAIL, 'RuntimeError: scratch did not start')])


if __name__ == '__main__':
    unittest.main()
