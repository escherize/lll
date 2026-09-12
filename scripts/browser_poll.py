#!/usr/bin/env python3
"""Poll a browser condition with one deadline, including CLI process time."""
import argparse
import os
import signal
import subprocess
import sys
import time


def result_line(output):
    lines = output.splitlines()
    for index, line in enumerate(lines[:-1]):
        if line == '### Result':
            return lines[index + 1].replace('\\', '')
    return ''


def run_before(command, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        out, err = process.communicate(timeout=max(0, deadline - time.monotonic()))
        return process.returncode, out, err
    except subprocess.TimeoutExpired:
        # Kill only this invocation and its children, never the persistent
        # browser session or sibling suites. Descendants may hold our pipes.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        return None


def poll(command, expression, needle, timeout, click=None):
    start = time.monotonic()
    deadline = start + timeout
    next_click = start
    last = ''
    error = ''
    while time.monotonic() < deadline:
        if click and time.monotonic() >= next_click:
            attempt = run_before([*command, 'click', click], deadline)
            if attempt is None:
                error = 'click invocation exceeded the deadline'
                break
            # Never increase the former ten-second minimum between retries.
            next_click = time.monotonic() + 10
        attempt = run_before([*command, 'eval', expression], deadline)
        if attempt is None:
            error = 'evaluation invocation exceeded the deadline'
            break
        code, out, err = attempt
        value = result_line(out)
        if code == 0 and value:
            last = value
            if needle in value:
                return value, ''
        else:
            error = (err or out or 'evaluation returned no result')[-500:]
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.25, remaining))
    diagnostic = (f'browser poll timed out after {time.monotonic() - start:.2f}s '
                  f'waiting for {needle!r}; last result: {last!r}')
    if error:
        diagnostic += f'; last error: {error}'
    return last, diagnostic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session')
    parser.add_argument('expression')
    parser.add_argument('needle')
    parser.add_argument('--timeout', type=float, default=10)
    parser.add_argument('--click')
    args = parser.parse_args()
    if not 0 < args.timeout < float('inf'):
        parser.error('--timeout must be positive and finite')
    value, error = poll(['playwright-cli', '-s=' + args.session], args.expression,
                        args.needle, args.timeout, args.click)
    sys.stdout.write(value)
    if error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
