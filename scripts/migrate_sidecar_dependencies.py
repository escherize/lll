#!/usr/bin/env python3
"""Reconcile imported dependency prose with issue links; preview unless --apply."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

from import_sidecar import Lll, pb_list

ORIGIN = re.compile(r'^Origin: sidecar (TASK-\d+)[ \t]*$', re.M)
DEPENDENCY = re.compile(r'^Blocked by (TASK-\d+)[ \t]*$', re.M)


def plan(records, team):
    """Resolve legacy IDs and validate the complete graph before any writes."""
    by_id = {record['id']: record for record in records}
    origins = {}
    imported = []
    for record in records:
        matches = ORIGIN.findall(record.get('description', ''))
        if not matches:
            continue
        if len(matches) != 1 or matches[0] in origins:
            raise ValueError(f'ambiguous sidecar origin on {team}-{record["number"]}')
        origins[matches[0]] = record
        imported.append(record)
    graph = {record['id']: set(record.get('blocked_by', [])) for record in records}
    additions = []
    for record in sorted(imported, key=lambda row: row['number']):
        for dependency in dict.fromkeys(DEPENDENCY.findall(record.get('description', ''))):
            if dependency not in origins:
                raise ValueError(f'{team}-{record["number"]}: unresolved {dependency}')
            target = origins[dependency]
            if target['id'] not in graph[record['id']]:
                additions.append((f'{team}-{record["number"]}', f'{team}-{target["number"]}', dependency))
                graph[record['id']].add(target['id'])

    active, visited = set(), set()
    def visit(node):
        if node in active:
            number = by_id[node]['number'] if node in by_id else node
            raise ValueError(f'dependency cycle involving {team}-{number}')
        if node in visited:
            return
        active.add(node)
        for target in graph.get(node, ()):
            visit(target)
        active.remove(node)
        visited.add(node)
    for node in graph:
        visit(node)
    return additions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--team', default='LLL')
    parser.add_argument('--lll', default=str(Path(__file__).resolve().parents[1] / 'target/.lisette/bin/lll'))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    token = os.environ.get('LLL_TOKEN', '')
    if not token:
        parser.error('LLL_TOKEN is required')
    url = args.url.rstrip('/')
    def snapshot():
        return pb_list(url, token, 'issues', f'team.key={json.dumps(args.team)}')
    additions = plan(snapshot(), args.team)
    for source, target, legacy in additions:
        print(f'{source} blocked by {target} (origin {legacy})')
    print(f'{len(additions)} missing dependency links')
    if args.apply:
        cli = Lll(args.lll, url, token)
        cli.env['LLL_TEAM'] = args.team
        for source, target, _ in additions:
            cli.run(['issue', 'block', source, target])
        remaining = plan(snapshot(), args.team)
        if remaining:
            raise RuntimeError(f'{len(remaining)} dependency links remain; rerun to reconcile')
        print(f'applied {len(additions)} links; fresh snapshot confirms zero missing')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError) as error:
        sys.exit(str(error))
