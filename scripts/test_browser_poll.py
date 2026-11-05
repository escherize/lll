import pathlib
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from browser_poll import poll, result_line


class Clock:
    now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class BrowserPollTest(unittest.TestCase):
    def test_preserves_existing_result_format(self):
        self.assertEqual(result_line('noise\n### Result\n"{\\"ready\\":true}"\nrest'),
                         '"{"ready":true}"')
        self.assertEqual(result_line('navigation interrupted'), '')

    def test_success_requires_a_successful_evaluation(self):
        with tempfile.TemporaryDirectory() as temp:
            script = pathlib.Path(temp) / 'eval.py'
            script.write_text('import time\ntime.sleep(.03)\nprint("### Result\\nready")\n')
            self.assertEqual(poll([sys.executable, str(script)], 'probe', 'ready', 2), ('ready', ''))
            script.write_text('import sys\nprint("### Result\\nready")\nsys.exit(1)\n')
            value, error = poll([sys.executable, str(script)], 'probe', 'ready', .15)
            self.assertEqual(value, '')
            self.assertIn('waiting for', error)

    def test_deadline_includes_hung_cli_and_its_descendants(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = pathlib.Path(temp) / 'escaped-child'
            script = pathlib.Path(temp) / 'hung.py'
            child = f'import time,pathlib; time.sleep(.6); pathlib.Path({str(marker)!r}).touch()'
            script.write_text(f'import subprocess,sys,time\nsubprocess.Popen([sys.executable,"-c",{child!r}])\ntime.sleep(20)\n')
            start = time.monotonic()
            value, error = poll([sys.executable, str(script)], 'probe', 'ready', .15)
            self.assertLess(time.monotonic() - start, 1.5)
            self.assertEqual(value, '')
            self.assertIn('evaluation invocation exceeded', error)
            time.sleep(.65)
            self.assertFalse(marker.exists())

    def test_timeout_retains_last_observation(self):
        # Observation retention must not depend on how quickly Python starts.
        # The real process/descendant deadline is exercised above.
        for final in (None, (1, '', 'navigation interrupted')):
            with self.subTest(final=final):
                clock = Clock()
                attempts = iter(((0, '### Result\nnot yet', ''), final))

                def evaluate(command, deadline):
                    result = next(attempts)
                    clock.now = deadline if result is None or result[0] != 0 else .1
                    return result

                with patch('browser_poll.time', clock), \
                     patch('browser_poll.run_before', side_effect=evaluate):
                    value, error = poll(['fixture-browser'], 'probe', 'ready', 1)
                self.assertEqual(value, 'not yet')
                self.assertIn("waiting for 'ready'", error)
                self.assertIn('not yet', error)
                self.assertIn('last error:', error)


if __name__ == '__main__':
    unittest.main()
