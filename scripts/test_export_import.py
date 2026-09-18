#!/usr/bin/env python3
"""The export/import loop: a team out to Markdown and back, byte for byte.

The property under test is that `lll export` -> `lll import dir --replace` ->
`lll export` reproduces the first tree. That covers more than it looks:
matching trees mean the numbers, sort order, states, priorities, labels,
assignees, emoji and descriptions all survived, because any one of them
coming back wrong changes a file.

Three things deliberately do not survive, and each is asserted separately
rather than quietly excluded:

  comments         export-only; nothing can forge another member's authorship
  created/updated  a restored record is a NEW record, so PocketBase stamps it
                   now (checked for shape, not for equality)
  blob filenames   PocketBase renames on upload (the BYTES are compared)
"""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zlib

binary, api = sys.argv[1:]

# A config home of its own, so the developer's real ~/.config/lll/lll.toml
# cannot supply a `me` or a url that this run never asked for. Kept alive for
# the whole script by the module-level reference.
_config_home = tempfile.TemporaryDirectory(prefix='lll-rtrip-config-')
env = dict(os.environ, LLL_URL=api, LLL_TEAM='RTRIP',
           LLL_CONFIG_HOME=_config_home.name)


def cli(*args, check=True, team='RTRIP'):
    run = subprocess.run([binary, *args], env=dict(env, LLL_TEAM=team),
                         text=True, capture_output=True, timeout=120)
    if check and run.returncode:
        raise AssertionError(f'lll {" ".join(args)} failed: {run.stderr.strip()}')
    return run


def post(collection, body):
    request = urllib.request.Request(
        api + '/api/collections/' + collection + '/records',
        data=json.dumps(body).encode(),
        headers={'Authorization': 'Bearer ' + env['LLL_TOKEN'],
                 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise AssertionError(
            f'POST {collection} -> {error.code}: '
            f'{error.read().decode("utf-8", "replace")[:400]}') from None


def tree(root):
    """Every file under root as {relative path: bytes}."""
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(Path(root).rglob('*')) if p.is_file()}


def chunk(kind, payload):
    return (struct.pack('>I', len(payload)) + kind + payload
            + struct.pack('>I', zlib.crc32(kind + payload)))


def api_request(path, method='GET', body=None):
    request = urllib.request.Request(
        api + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Authorization': 'Bearer ' + env['LLL_TOKEN'],
                 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raise AssertionError(
            f'{method} {path} -> {error.code}: '
            f'{error.read().decode("utf-8", "replace")[:400]}') from None


# Re-runnable against a server that already saw a failed attempt: the gate
# gets a fresh scratch database, a developer iterating does not. The team
# itself is reused rather than deleted — PocketBase refuses to drop a record
# other collections still reference, and emptying it is what matters here.
stale = api_request("/api/collections/teams/records?filter=key='RTRIP'")['items']
if stale:
    team = stale[0]
    for collection in ('issues', 'docs', 'labels', 'projects'):
        for record in api_request(
                f"/api/collections/{collection}/records"
                f"?filter=team='{team['id']}'&perPage=500")['items']:
            api_request(f'/api/collections/{collection}/records/' + record['id'], 'DELETE')
else:
    team = post('teams', {'key': 'RTRIP', 'name': 'Round trip'})
# Comments need an author, and the export has to prove it does NOT bring one
# back, so the member has to exist before anything is written.
if not api_request("/api/collections/members/records?filter=name='rtrip-bot'")['items']:
    cli('member', 'add', '-n', 'rtrip-bot')
bot = api_request("/api/collections/members/records?filter=name='rtrip-bot'")['items'][0]
label = post('labels', {'team': team['id'], 'name': 'evidence', 'color': '#f0883e'})
project = post('projects', {'team': team['id'], 'name': 'Round trip project',
                            'status': 'started'})

# Hostile-on-purpose content: the things that break a naive front matter
# format. Each is a field the round trip has to carry unchanged.
issues = [
    {'title': 'LLL-1: a title with: colons and "quotes"', 'state': 'todo',
     'priority': 2, 'description': 'plain body'},
    {'title': 'ünïcødé — em dash, café, 日本語', 'state': 'in-progress',
     'priority': 1, 'emoji': '🐛', 'description': 'описание\n\nsecond para'},
    {'title': 'body holds its own front matter', 'state': 'done', 'priority': 0,
     'description': 'intro\n\n---\nkey: not-real\nstate: fake\n---\n\ntail'},
    {'title': 'empty description', 'state': 'backlog', 'priority': 4,
     'description': ''},
    # project and creator are NAMES in the mirror, and both come from
    # relation expansions the board's own query does not ask for. Without an
    # issue that has them, an export emitting blanks passes unnoticed.
    {'title': 'labelled, projected and assigned', 'state': 'in-review',
     'priority': 3, 'description': '## Acceptance Criteria\n- [ ] #1 a\n- [ ] #2 b',
     'labels': [label['id']], 'project': project['id'],
     # A real creation context, so "the restore must not overwrite it with
     # this machine's" is a claim the assertion can actually test.
     'origin': {'host': 'filing-box', 'cwd': '/src/elsewhere',
                'branch': 'feature/x', 'sha': 'deadbee', 'tool': 'codex'}},
]
# creator explicitly: these go in over the raw API, which does not fill it
# the way `lll issue create` does, and the mirror writes the creator NAME.
created = [post('issues', dict(team=team['id'], creator=bot['id'], **i))
           for i in issues]

# A deliberate gap in the numbering: delete one, so a restore that renumbers
# instead of reproducing numbers cannot pass by accident.
urllib.request.urlopen(urllib.request.Request(
    api + '/api/collections/issues/records/' + created[3]['id'],
    method='DELETE', headers={'Authorization': 'Bearer ' + env['LLL_TOKEN']}), timeout=30)
numbers = sorted(i['number'] for i in created if i['id'] != created[3]['id'])
assert numbers == [1, 2, 3, 5], f'expected a gap at 4, got {numbers}'

png = (b'\x89PNG\r\n\x1a\n'
       + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 2, 0, 0, 0))
       + chunk(b'IDAT', zlib.compress(b'\0\x28\x5a\x82\x28\x5a\x82\0\x28\x5a\x82\x28\x5a\x82'))
       + chunk(b'IEND', b''))

with tempfile.TemporaryDirectory() as work:
    work = Path(work)
    shot = work / 'shot.png'
    shot.write_bytes(png)
    cli('issue', 'attach', 'RTRIP-1', str(shot))
    cli('issue', 'comment', 'RTRIP-1', '-b', 'a comment that must NOT round trip')
    cli('doc', 'create', '-s', 'round-trip-doc', '-t', 'Round trip doc',
        '-b', 'document body')
    # A doc with retrieval coordinates and an issue link: the link is the
    # interesting part, because it survives only if issue numbers do.
    cli('finding', 'new', '-s', 'round-trip-finding', '-t', 'Round trip finding',
        '-a', 'evidence', '-p', 'src/mirror', '-b', 'finding body')
    cli('doc', 'link', 'round-trip-finding', 'RTRIP-5')

    # Refs are how `lll import github` knows what it already brought in, so
    # losing them turns a later re-import into a duplicate import.
    cli('issue', 'ref', 'RTRIP-5', 'gh#41')
    # A dependency link pointing BACKWARD across the numbering gap, so the
    # second pass has to resolve a key that is not simply the next record.
    cli('issue', 'block', 'RTRIP-5', 'RTRIP-1')

    first = work / 'first'
    cli('export', str(first))
    before = tree(first)

    # Guard the blanks directly: an unexpanded relation renders as an empty
    # string and nothing fails, so assert the names are actually in the file.
    five = before['issues/RTRIP-5.md'].decode()
    assert 'project: Round trip project' in five, five.split('---')[1]
    assert 'refs: gh#41' in five, five.split('---')[1]
    assert 'host: filing-box' in five and 'sha: deadbee' in five, five.split('---')[1]
    # Whoever the server recorded as creator, by NAME. Not a fixed name:
    # gopb/provenance.go attributes a create to the authenticated member, so
    # the actor differs between a superuser token and the e2e harness's.
    filed_by = api_request('/api/collections/members/records/'
                           + json.loads(cli('issue', 'view', 'RTRIP-5',
                                            '--json').stdout)['creator'])['name']
    assert filed_by, 'the issue has no creator to check'
    assert f'creator: {filed_by}' in five, five.split('---')[1]
    assert 'issues/RTRIP-1.md' in before, sorted(before)
    assert 'issues/RTRIP-4.md' not in before, 'the deleted issue was exported'

    # AC6: attachment bytes, not a filename. PocketBase assigns its own
    # stored name on upload (shot.png -> shot_ab12cd34.png), so the blob is
    # found by its directory, never by the name it was uploaded under.
    blobs = {k: v for k, v in before.items() if k.startswith('issues/RTRIP-1/')}
    assert len(blobs) == 1, f'expected one attachment, got {sorted(blobs)}'
    assert list(blobs.values())[0] == png, 'attachment bytes changed on export'

    # Comments are exported but are export-only; they must not come back in.
    assert 'issues/RTRIP-1.comments.md' in before
    assert b'must NOT round trip' in before['issues/RTRIP-1.comments.md']

    # AC2 again, locally: a second export of unchanged state is identical.
    second = work / 'second'
    cli('export', str(second))
    assert tree(second) == before, 'export is not byte-stable'

    # AC4: a team with issues refuses, and names both the count and the fix.
    refused = cli('import', 'dir', str(first), check=False)
    assert refused.returncode != 0, 'import into a non-empty team was allowed'
    assert '4 issues' in refused.stderr and '--replace' in refused.stderr, refused.stderr
    assert tree(first) == before, 'a refused import touched the mirror'
    live = json.loads(cli('issue', 'list', '--json').stdout)['items']
    assert len(live) == 4, f'a refused import changed the team: {len(live)}'

    # AC5 + AC3: --replace rebuilds the team, and re-exporting matches byte
    # for byte. Numbers, sort, state, priority, labels, emoji and text all
    # ride on this one assertion.
    cli('import', 'dir', str(first), '--replace')
    third = work / 'third'
    cli('export', str(third))
    after = tree(third)

    # Two things legitimately do not survive, and both are compared apart
    # from the byte-for-byte assertion rather than quietly excused:
    #
    #   comments  - export-only, because nothing can forge authorship
    #   blob NAMES - PocketBase renames on upload, so a restored attachment
    #                has a new stored filename (its BYTES are checked below)
    #   created/updated - a restored record IS a new record, so PocketBase
    #                     stamps it now. Inherent, not a defect: these are
    #                     facts about the row, not about the issue. They are
    #                     checked for shape below instead.
    def strip_stamps(text):
        return b'\n'.join(l for l in text.split(b'\n')
                          if not l.startswith(b'created:')
                          and not l.startswith(b'updated:'))

    def comparable(t):
        return {k: strip_stamps(v) for k, v in t.items()
                if not k.endswith('.comments.md')
                and not k.startswith('issues/RTRIP-1/')
                and k != 'issues/RTRIP-1.md'}

    if comparable(after) != comparable(before):
        import difflib
        report = []
        for k in sorted(set(comparable(before)) | set(comparable(after))):
            b = comparable(before).get(k, b'<absent>').decode('utf-8', 'replace')
            a = comparable(after).get(k, b'<absent>').decode('utf-8', 'replace')
            if a != b:
                report += [f'--- {k}'] + list(difflib.unified_diff(
                    b.splitlines(), a.splitlines(), 'export', 'reimport', lineterm='', n=1))
        raise AssertionError('round trip differs:\n' + '\n'.join(report))
    assert not any(k.endswith('.comments.md') for k in after), \
        'comments came back in, but nothing can forge authorship'

    # AC6 proper: the blob came back, byte for byte, under a new stored name.
    after_blobs = {k: v for k, v in after.items() if k.startswith('issues/RTRIP-1/')}
    assert len(after_blobs) == 1, f'attachment not restored: {sorted(after_blobs)}'
    assert list(after_blobs.values())[0] == png, 'attachment bytes changed on import'

    # RTRIP-1.md is excluded above only because its `attachments:` line names
    # that renamed file. Everything else in it must still match exactly.
    def without_attachments(text):
        return strip_stamps(b'\n'.join(
            l for l in text.split(b'\n')
            if not l.startswith(b'    - shot') and not l.startswith(b'attachments:')))
    assert without_attachments(after['issues/RTRIP-1.md']) == \
        without_attachments(before['issues/RTRIP-1.md']), \
        'the attached issue changed beyond its attachment name'

    # The stamps that were excluded above are still required to be there and
    # to be PocketBase stamps, so dropping the fields entirely cannot pass.
    for name, text in after.items():
        if not name.startswith('issues/') or not name.endswith('.md'):
            continue
        if name.endswith('.comments.md'):
            continue
        head = text.decode().split('---')[1]
        for field in ('created:', 'updated:'):
            line = next(l for l in head.splitlines() if l.startswith(field))
            stamp = line.split(' ', 1)[1].strip()
            assert stamp.endswith('Z') and len(stamp) >= 20, f'{name}: {line}'

    # Docs come back too, with their kind, coordinates and issue links. The
    # link is stored as a record id, so it can only survive by being written
    # as KEY and re-resolved — which works because numbers round-trip.
    docs = json.loads(cli('doc', 'list', '--json').stdout)['items']
    by_slug = {d['slug']: d for d in docs}
    assert 'round-trip-doc' in by_slug and 'round-trip-finding' in by_slug, sorted(by_slug)
    finding = by_slug['round-trip-finding']
    assert finding['kind'] == 'finding', finding['kind']
    assert finding['area'] == 'evidence' and finding['paths'] == 'src/mirror', finding
    rtrip5 = next(i for i in json.loads(cli('issue', 'list', '--json').stdout)['items']
                  if i['number'] == 5)
    assert finding['issues'] == [rtrip5['id']], \
        f"doc issue link did not re-resolve: {finding['issues']} vs {rtrip5['id']}"

    # The dependency graph came back, re-resolved from keys to new ids.
    blocked = json.loads(cli('issue', 'view', 'RTRIP-5', '--json').stdout)
    rtrip1 = next(i for i in json.loads(cli('issue', 'list', '--json').stdout)['items']
                  if i['number'] == 1)
    assert blocked['blocked_by'] == [rtrip1['id']], \
        f"blocked_by did not re-resolve: {blocked['blocked_by']} vs {rtrip1['id']}"

    # Provenance survives, and the restore does NOT rewrite it to say the
    # issue was filed by whoever ran the import, on their machine.
    restored_five = json.loads(cli('issue', 'view', 'RTRIP-5', '--json').stdout)
    assert restored_five['refs'] == 'gh#41', restored_five['refs']
    assert restored_five['expand']['project']['name'] == 'Round trip project'
    # Origin survives: the restore must NOT rewrite it to this machine.
    assert restored_five['origin'] == created[4]['origin'], restored_five['origin']
    # Creator deliberately is NOT asserted to survive. gopb/provenance.go
    # attributes every member-authenticated create to the actor, so a restore
    # run by a member is recorded as filed by that member. The mirror carries
    # the original name for a reader; only a superuser-backed import can put
    # it back. Asserted here as "present and a real member", not as equal.
    assert api_request('/api/collections/members/records/'
                       + restored_five['creator'])['name'], 'restored creator is not a member'

    # AC3 explicitly: the gap survived, so cross-references still point right.
    restored_numbers = sorted(i['number'] for i in
                              json.loads(cli('issue', 'list', '--json').stdout)['items'])
    assert restored_numbers == [1, 2, 3, 5], restored_numbers

    # A malformed file fails the whole import, leaving nothing written.
    broken = work / 'broken'
    subprocess.run(['cp', '-R', str(first), str(broken)], check=True)
    (broken / 'issues' / 'RTRIP-2.md').write_text('no front matter here\n')
    cli('import', 'dir', str(broken), '--replace', check=False)
    still = sorted(i['number'] for i in
                   json.loads(cli('issue', 'list', '--json').stdout)['items'])
    assert still == [1, 2, 3, 5], f'a malformed mirror half-applied: {still}'

print('test_export_import: round trip identical but for server-assigned '
      'stamps and blob names, non-empty team refused, blob bytes exact')
