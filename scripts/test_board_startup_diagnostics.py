import tempfile
import unittest
from pathlib import Path

from board_startup import wait_for_board, wait_for_endpoints


class StartupDiagnosticsTests(unittest.TestCase):
    def test_failure_evidence_survives_fixture_cleanup_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'up.log'
            log.write_text('board  login http://127.0.0.1:8100/?board_token=hidden-board-token\n'
                           'scratch admin  admin@local.invalid / hidden-password (shown once)\n'
                           'LLL_TOKEN=hidden-member-token\n'
                           'Authorization: Bearer hidden-header-token\n'
                           'database initialization failed: permission denied\n')
            for wait in (lambda: wait_for_endpoints(log, timeout=0),
                         lambda: wait_for_board(log, 'http://127.0.0.1:8100', timeout=0)):
                with self.assertRaises(AssertionError) as caught:
                    wait()
                message = str(caught.exception)
                self.assertIn('permission denied', message)
                self.assertIn('[credential line redacted]', message)
                for secret in ('hidden-board-token', 'hidden-password', 'hidden-member-token', 'hidden-header-token'):
                    self.assertNotIn(secret, message)
        self.assertFalse(log.exists())
        self.assertIn('permission denied', message)

    def test_empty_output_explains_the_missing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AssertionError, 'no startup output captured'):
                wait_for_endpoints(Path(directory) / 'missing.log', timeout=0)

    def test_large_logs_keep_the_recent_failure_and_bound_the_message(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'up.log'
            log.write_text('x' * 10000 + '\nstartup failed at the final step\n')
            with self.assertRaises(AssertionError) as caught:
                wait_for_endpoints(log, timeout=0)
            message = str(caught.exception)
            self.assertIn('startup failed at the final step', message)
            self.assertLess(len(message), 4400)
