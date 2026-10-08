#!/usr/bin/env python3
"""LLL-631: list references that cross teams. READ-ONLY.

Since LLL-631 the server refuses a reference from one team's record to
another team's (an issue's labels, project or blockers, a doc's issues, a
webhook's project) for every writer. References made before that stay in
the database, and an unrelated edit does not remove them. This lists them so
the owner can detach each one before or after rolling the rule out.

It only sends GET requests. It changes nothing.

Usage:
    LLL_URL=https://board.example LLL_TOKEN=<all-scope member or superuser token> \\
        python3 scripts/audit_cross_team_refs.py [--json]

The token must see every team: a team-scoped token would miss the
references it cannot see, so the script refuses one.

Exit status: 0 when nothing crosses teams, 1 when something does (one line
per reference, or a JSON list with --json), 2 when the audit could not run.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

# collection -> field -> target collection: the server's scopedRefs
# (gopb/team_scope.go).
REFS = {
    'issues': {'labels': 'labels', 'project': 'projects', 'blocked_by': 'issues'},
    'docs': {'issues': 'issues'},
    'webhooks': {'project': 'projects'},
}


def get(base, token, path):
    req = urllib.request.Request(base + path, headers={'Authorization': 'Bearer ' + token})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def fetch_all(base, token, collection):
    out, page = [], 1
    while True:
        query = urllib.parse.urlencode({'page': page, 'perPage': 500, 'sort': 'id'})
        body = get(base, token, f'/api/collections/{collection}/records?{query}')
        out.extend(body['items'])
        if page >= body.get('totalPages', 1):
            return out
        page += 1


def name(collection, record, team_keys):
    key = team_keys.get(record.get('team'), '?')
    if collection == 'issues':
        return f"issue {key}-{record.get('number')}"
    if collection == 'docs':
        return f"doc {key}/{record.get('slug')}"
    if collection == 'webhooks':
        return f"webhook {record['id']} ({key})"
    return f"{collection[:-1]} {record.get('name')!r} ({key})"


def main(argv):
    base = os.environ.get('LLL_URL', '').rstrip('/')
    token = os.environ.get('LLL_TOKEN', '')
    if not base or not token:
        print('set LLL_URL and LLL_TOKEN (an all-scope member or superuser token)', file=sys.stderr)
        return 2
    try:
        access = get(base, token, '/api/lll/access')
        if not access.get('all'):
            print(f"token for {access.get('name')} sees only some teams; the audit needs one that sees every team", file=sys.stderr)
            return 2
    except urllib.error.HTTPError as e:
        if e.code != 401:  # 401: a superuser token, which names no member
            print(f'GET /api/lll/access: {e}', file=sys.stderr)
            return 2
    try:
        teams = fetch_all(base, token, 'teams')
        records = {c: {r['id']: r for r in fetch_all(base, token, c)}
                   for c in ['labels', 'projects', 'issues', 'docs', 'webhooks']}
    except (urllib.error.URLError, KeyError, ValueError) as e:
        print(f'reading the board: {e}', file=sys.stderr)
        return 2
    team_keys = {t['id']: t['key'] for t in teams}
    found = []
    for collection, fields in REFS.items():
        for record in records[collection].values():
            for field, target in fields.items():
                ids = record.get(field) or []
                for ref_id in [ids] if isinstance(ids, str) else ids:
                    ref = records[target].get(ref_id)
                    if ref is None or ref.get('team') == record.get('team'):
                        continue
                    found.append({
                        'holder': name(collection, record, team_keys), 'holder_id': record['id'],
                        'collection': collection, 'field': field,
                        'ref': name(target, ref, team_keys), 'ref_id': ref_id,
                    })
    if '--json' in argv:
        print(json.dumps(found, indent=2))
    else:
        for f in found:
            print(f"{f['holder']} {f['field']} -> {f['ref']}  [{f['collection']}/{f['holder_id']} -> {f['ref_id']}]")
        print(f'{len(found)} cross-team reference(s)', file=sys.stderr)
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
