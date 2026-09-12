"""Verify the owned process bound the board endpoint a fixture will use."""
from pathlib import Path
import re
import sys
import time


def wait_for_board(log_path, expected, timeout=20):
    deadline = time.monotonic() + timeout
    while True:
        output = Path(log_path).read_text(errors='replace')
        match = re.search(r'^board  (http://\S+)$', output, re.M)
        if match:
            actual = match[1]
            if actual != expected:
                raise AssertionError(
                    f'owned board bound {actual}, expected {expected}; '
                    'the selected port was occupied; refusing fixture requests to another listener')
            return
        if time.monotonic() >= deadline:
            raise AssertionError(f'owned board did not announce {expected} within {timeout}s; see {log_path}')
        time.sleep(.1)


if __name__ == '__main__':
    wait_for_board(sys.argv[1], sys.argv[2])
