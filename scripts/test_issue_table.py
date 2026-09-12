#!/usr/bin/env python3
"""Check real list output against known display widths, without a width oracle."""
import json
import os
import re
import subprocess
import sys

binary, api = sys.argv[1:]
env = dict(os.environ, LLL_URL=api, LLL_TEAM='ENG')

def run(*args):
    result = subprocess.run([binary, *args], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return result.stdout

run('member', 'add', '-n', 'Width Marker')
prefix = 'Width probe '
cases = [('ASCII', 5), ('漢字', 4), ('🔥', 2), ('👨‍👩‍👧‍👦', 2), ('é', 1), ('🇺🇸', 2), ('👍🏽', 2)]
for text, _ in cases:
    run('issue', 'create', prefix + text, '--assignee', 'Width Marker')
output = run('issue', 'list', '--search', prefix)
assert len(output.splitlines()) == len(cases), output
for text, width in cases:
    match = re.search(re.escape(prefix + text) + r'( +)Width Marker', output)
    assert match and len(match[1]) == 5 - width + 2, (text, output)
records = json.loads(run('issue', 'list', '--search', prefix, '--json'))
assert {item['title'] for item in records['items']} == {prefix + text for text, _ in cases}
print('Issue table: CJK, emoji, combining marks and ZWJ columns align; JSON preserves text')
