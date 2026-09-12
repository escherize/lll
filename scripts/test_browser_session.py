import os
import subprocess
import unittest
from unittest.mock import patch

from browser_session import diagnostic, new_session, open_session, require_result


class BrowserSessionTests(unittest.TestCase):
    def test_success_requires_the_actual_returned_value(self):
        require_result(subprocess.CompletedProcess([], 0, '### Result\n"verified"\n', ''),
                       'verified', 'http://localhost/')
        for output in ('### Ran Playwright code\nreturn "verified";',
                       '### Ran Playwright code\n### Result\n"verified"',
                       '### Result\n"not verified"',
                       '### Result\nundefined'):
            with self.subTest(output=output), self.assertRaises(AssertionError):
                require_result(subprocess.CompletedProcess([], 0, output, ''),
                               'verified', 'http://localhost/')

    def test_action_failure_exposes_the_redacted_tool_error(self):
        url = 'http://localhost/?board_token=handoff-secret'
        for code in (0, 1):
            with self.subTest(code=code), self.assertRaises(AssertionError) as caught:
                require_result(subprocess.CompletedProcess([], code,
                    '### Error\nTimeout waiting for card at ' + url, ''), 'verified', url)
            self.assertIn('Timeout waiting for card', str(caught.exception))
            self.assertNotIn('handoff-secret', str(caught.exception))

    def test_session_names_fit_the_macos_socket_budget_and_are_distinct(self):
        names = {new_session() for _ in range(100)}
        self.assertEqual(len(names), 100)
        prefix = '/var/folders/dw/_2dd8rzs1_1dvtbbt2tdsxy80000gn/T/pw-2a0249a4/cli/99f6e7029aa6be60-'
        for name in names:
            self.assertRegex(name, r'^[0-9a-f]{14}$')
            self.assertLess(len((prefix + name + '.sock').encode()), 104)

    def test_preserves_failure_and_redacts_credentials(self):
        url = 'http://localhost:8100/?board_token=board-secret'
        text = 'EADDRINUSE /tmp/session.sock ' + url + ' board-secret member-secret'
        result = subprocess.CompletedProcess([], 1, '', text)
        with patch.dict(os.environ, {'LLL_TOKEN': 'member-secret'}), patch('browser_session.subprocess.run', return_value=result):
            with self.assertRaises(AssertionError) as caught:
                open_session('owned-session', url)
        message = str(caught.exception)
        self.assertIn('EADDRINUSE /tmp/session.sock', message)
        self.assertIn('exit 1', message)
        self.assertNotIn('board-secret', message)
        self.assertNotIn('member-secret', message)

    def test_tool_error_is_failure_even_with_exit_zero(self):
        result = subprocess.CompletedProcess([], 0, '### Error\nBrowser failed', '')
        with patch('browser_session.subprocess.run', return_value=result):
            with self.assertRaisesRegex(AssertionError, 'Browser failed'):
                open_session('owned-session', 'http://localhost/')

    def test_timeout_keeps_partial_diagnostic_without_command_arguments(self):
        error = subprocess.TimeoutExpired(['open', 'secret-command-arg'], 2,
                                          output=b'partial startup', stderr=b' connection stalled')
        with patch('browser_session.subprocess.run', side_effect=error):
            with self.assertRaises(AssertionError) as caught:
                open_session('owned-session', 'http://localhost/', timeout=2)
        self.assertIn('partial startup connection stalled', str(caught.exception))
        self.assertNotIn('secret-command-arg', str(caught.exception))

    def test_success_and_bounded_diagnostic(self):
        with patch('browser_session.subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'Opened', '')):
            open_session('owned-session', 'http://localhost/')
        result = diagnostic('start' + 'x' * 20000 + 'end', 'http://localhost/', [])
        self.assertTrue(result.startswith('start') and result.endswith('end'))
        self.assertLess(len(result), 12100)
