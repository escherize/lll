"""Verify the owned process bound the board endpoint a fixture will use."""
from pathlib import Path
import json
import re
import sys
import time


def wait_for_endpoints(log_path, timeout=30):
    """Read both endpoints from the owned process before fixture requests."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            output = Path(log_path).read_text(errors='replace')
        except FileNotFoundError:
            output = ''
        api = re.search(r'^api    (http://127\.0\.0\.1:\d+)(?: |$)', output, re.M)
        board = re.search(r'^board  (http://127\.0\.0\.1:\d+)$', output, re.M)
        login = re.search(r'^board  login (http://127\.0\.0\.1:\d+)/\?board_token=([^ )\s]+)', output, re.M)
        if api and board and login:
            if board[1] != login[1]:
                raise AssertionError('owned board endpoint differs from its login URL')
            return {'db_url': api[1], 'board_url': board[1], 'board_token': login[2]}
        if time.monotonic() >= deadline:
            raise AssertionError(f'owned process did not announce both endpoints within {timeout}s; see {log_path}')
        time.sleep(.1)


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
    if sys.argv[1] == '--endpoints':
        print(json.dumps(wait_for_endpoints(sys.argv[2])))
    else:
        wait_for_board(sys.argv[1], sys.argv[2])
