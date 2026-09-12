"""Launch an owned browser session and retain actionable, redacted failures."""
import os
import subprocess
import urllib.parse


def diagnostic(output, url, secrets):
    if isinstance(output, bytes):
        output = output.decode('utf-8', errors='replace')
    output = output or ''
    parts = urllib.parse.urlsplit(url)
    safe_url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
    output = output.replace(url, safe_url)
    values = list(secrets) + urllib.parse.parse_qs(parts.query).get('board_token', [])
    for value in sorted({v for v in values if v}, key=len, reverse=True):
        output = output.replace(value, '[redacted]')
    if len(output) > 12000:
        output = output[:6000] + '\n[diagnostic truncated]\n' + output[-6000:]
    return output


def open_session(session, url, timeout=30):
    secrets = [os.environ.get(name, '') for name in
               ('LLL_TOKEN', 'LLL_BOARD_TOKEN', 'LLL_TEST_BOARD_TOKEN', 'LLL_ADMIN_PASSWORD')]
    try:
        result = subprocess.run(['playwright-cli', '-s=' + session, 'open', url],
                                capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        details = diagnostic(error.stdout, url, secrets) + diagnostic(error.stderr, url, secrets)
        raise AssertionError(f'browser launch {session} exceeded {timeout}s\n{details}') from None
    output = result.stdout + result.stderr
    if result.returncode != 0 or '### Error' in output:
        details = diagnostic(output, url, secrets)
        raise AssertionError(f'browser launch {session} failed (exit {result.returncode})\n{details}')
