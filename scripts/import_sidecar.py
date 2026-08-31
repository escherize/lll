#!/usr/bin/env python3
"""Import the .private sidecar tracker into a hosted lll instance (TASK-199).

Moves this project's own record onto an lll board: every sidecar task
(backlog/tasks + backlog/completed) becomes an issue on team LLL, and the
knowledge layers (wiki/, decisions/, findings/, backlog/docs) become lll docs.

Idempotent: every imported issue carries an 'Origin: sidecar TASK-nnn' body
line and every doc an 'Origin: sidecar <path>' line; a re-run lists what is
already there and creates nothing for records whose origin is present
(docs are additionally keyed by slug, which is UNIQUE per team).

Import order: team, members, labels, projects, issues (ascending by task
number), docs, then issue->doc links.

Worklogs (.private/worklogs/) are NOT imported: lll has no worklog doc type
and the sidecar remains the archive for them.

Usage:
    LLL_TOKEN=<member or superuser token> \
    python3 scripts/import_sidecar.py --url https://target.example

--url is required on purpose: this script refuses to guess an instance, so it
can never accidentally write into a local board someone else is running.
It only ever writes to team LLL (creating it if absent).

Re-run: the same command; the report prints created vs skipped-existing per
collection and a re-run against an already-imported instance creates zero.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

STATE_MAP = {"To Do": "todo", "In Progress": "in-progress", "Done": "done"}
PRIORITY_MAP = {"high": "2", "medium": "3", "low": "4"}
TEAM_KEY = "LLL"


# --- tiny YAML-subset frontmatter parser -------------------------------------
# Backlog.md task files use: plain/quoted scalars, '[]', block lists of
# scalars, and '>-' / '|-' block scalars for long titles. Nothing else.

def unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == "'" and v[-1] == "'":
        return v[1:-1].replace("''", "'")
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        try:
            return json.loads(v)
        except ValueError:
            return v[1:-1]
    return v


def parse_frontmatter(text, path):
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        raise ValueError(f"{path}: no frontmatter")
    fields, body = {}, text[m.end():]
    lines = m.group(1).split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        km = re.match(r"^([A-Za-z_]+):(.*)$", line)
        if not km:
            i += 1
            continue
        key, val = km.group(1), km.group(2).strip()
        if val in (">", ">-", "|", "|-"):
            block = []
            i += 1
            while i < len(lines) and (lines[i].startswith("  ") or lines[i] == ""):
                block.append(lines[i].strip())
                i += 1
            joiner = " " if val.startswith(">") else "\n"
            fields[key] = joiner.join(block).strip()
            continue
        if val == "[]":
            fields[key] = []
        elif val == "":
            items = []
            i += 1
            while i < len(lines) and re.match(r"^\s+- ", lines[i]):
                items.append(unquote(re.sub(r"^\s+- ", "", lines[i])))
                i += 1
            fields[key] = items
            continue
        else:
            fields[key] = unquote(val)
        i += 1
    return fields, body


MARKER_RE = re.compile(r"^<!-- (?:SECTION:[A-Z_]+|AC|COMMENTS):(?:BEGIN|END) -->\s*$")


def clean_body(body):
    lines = [l for l in body.split("\n") if not MARKER_RE.match(l)]
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return out.strip()


# --- PocketBase reads (idempotency checks) -----------------------------------

def pb_list(url, token, collection, flt=""):
    items, page = [], 1
    while True:
        q = {"page": page, "perPage": 200, "skipTotal": 1}
        if flt:
            q["filter"] = flt
        req = urllib.request.Request(
            f"{url}/api/collections/{collection}/records?{urllib.parse.urlencode(q)}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req) as resp:
            got = json.load(resp)["items"]
        items += got
        if len(got) < 200:
            return items
        page += 1


# --- CLI wrapper --------------------------------------------------------------

class Lll:
    def __init__(self, binary, url, token):
        self.binary = binary
        self.env = dict(os.environ, LLL_URL=url, LLL_TEAM=TEAM_KEY, LLL_TOKEN=token)

    def run(self, args, stdin=None):
        r = subprocess.run(
            [self.binary] + args, input=stdin, env=self.env,
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"lll {' '.join(args[:3])}...: {r.stderr.strip() or r.stdout.strip()}")
        return r.stdout


# --- source parsing -----------------------------------------------------------

def load_tasks(private):
    tasks = []
    for sub in ("backlog/tasks", "backlog/completed"):
        d = os.path.join(private, sub)
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if not name.endswith(".md"):
                continue
            path = os.path.join(d, name)
            with open(path) as f:
                fields, body = parse_frontmatter(f.read(), path)
            num = int(fields["id"].split("-")[1])
            tasks.append((num, fields, body, path))
    tasks.sort(key=lambda t: t[0])
    return tasks


def load_milestones(private):
    """m-0 -> project title, from the milestone files' frontmatter."""
    out = {}
    d = os.path.join(private, "backlog/milestones")
    if not os.path.isdir(d):
        return out
    for name in os.listdir(d):
        if not name.endswith(".md"):
            continue
        path = os.path.join(d, name)
        with open(path) as f:
            fields, _ = parse_frontmatter(f.read(), path)
        out[fields["id"]] = fields.get("title") or fields["id"]
    return out


def doc_slug(stem):
    slug = re.sub(r"[^a-z0-9-]+", "-", stem.lower()).strip("-")
    return slug[:80].rstrip("-")


def load_docs(private):
    """(slug, kind, title, body, area, origin, doc_id) for every knowledge file."""
    docs = []

    def first_h1(text, fallback):
        m = re.search(r"^# (.+)$", text, re.M)
        return m.group(1).strip() if m else fallback

    def add(path, kind, stem, doc_id=None):
        rel = os.path.relpath(path, private)
        with open(path) as f:
            text = f.read()
        area = ""
        am = re.search(r"^area: (\S+)$", text, re.M)
        if kind == "finding" and am:
            area = am.group(1)
        docs.append({
            "slug": doc_slug(stem), "kind": kind,
            "title": first_h1(text, stem), "body": text.rstrip("\n"),
            "area": area, "origin": rel, "doc_id": doc_id,
        })

    for name in sorted(os.listdir(os.path.join(private, "wiki"))):
        if name.endswith(".md"):
            add(os.path.join(private, "wiki", name), "wiki", name[:-3])
    for name in sorted(os.listdir(os.path.join(private, "decisions"))):
        if name.endswith(".md"):
            add(os.path.join(private, "decisions", name), "decision", name[:-3])
    fdir = os.path.join(private, "findings")
    for agent in sorted(os.listdir(fdir)):
        adir = os.path.join(fdir, agent)
        if not os.path.isdir(adir):
            continue
        for name in sorted(os.listdir(adir)):
            if name.endswith(".md"):
                add(os.path.join(adir, name), "finding", name[:-3])
    bdocs = os.path.join(private, "backlog/docs")
    if os.path.isdir(bdocs):
        for name in sorted(os.listdir(bdocs)):
            if not name.endswith(".md"):
                continue
            path = os.path.join(bdocs, name)
            with open(path) as f:
                fields, _ = parse_frontmatter(f.read(), path)
            stem = re.sub(r"^doc-\d+ - ", "", name[:-3])
            add(path, "prd", stem, doc_id=fields.get("id"))
    return docs


# --- import phases ------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", required=True,
                    help="lll/PocketBase base URL; required, never defaulted")
    ap.add_argument("--private", default=None, help="path to the .private sidecar")
    ap.add_argument("--lll", default=None, help="path to the lll binary")
    args = ap.parse_args()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    private = args.private or os.path.join(repo, ".private")
    binary = args.lll or os.path.join(repo, "target/.lisette/bin/lll")
    url = args.url.rstrip("/")
    token = os.environ.get("LLL_TOKEN", "")
    if not token:
        sys.exit("LLL_TOKEN is not set; mint one with 'lll token create' "
                 "(superuser) and export it")
    if not os.path.isdir(os.path.join(private, "backlog/tasks")):
        sys.exit(f"{private}/backlog/tasks not found — pass --private")
    if not os.path.isfile(binary):
        sys.exit(f"{binary} not found — 'lis build' first, or pass --lll")

    lll = Lll(binary, url, token)
    report = {}  # kind -> [source, created, skipped]

    def note(kind, source, created, skipped):
        report[kind] = [source, created, skipped]

    # -- team ------------------------------------------------------------
    teams = pb_list(url, token, "teams", f"key='{TEAM_KEY}'")
    if teams:
        note("teams", 1, 0, 1)
    else:
        lll.run(["team", "create", "-k", TEAM_KEY, "-n", "lisette-linear-like"])
        note("teams", 1, 1, 0)

    tasks = load_tasks(private)
    milestones = load_milestones(private)
    docs = load_docs(private)

    # -- members (distinct assignees, '@' is backlog syntax, not the name) -
    wanted_members = sorted({a.lstrip("@") for _, f, _, _ in tasks
                             for a in (f.get("assignee") or [])})
    have = {m["name"] for m in pb_list(url, token, "members")}
    created = 0
    for name in wanted_members:
        if name not in have:
            lll.run(["member", "add", "-n", name])
            created += 1
    note("members", len(wanted_members), created, len(wanted_members) - created)

    # -- labels ------------------------------------------------------------
    wanted_labels = sorted({l for _, f, _, _ in tasks for l in (f.get("labels") or [])})
    have = {l["name"] for l in pb_list(url, token, "labels", f"team.key='{TEAM_KEY}'")}
    created = 0
    for name in wanted_labels:
        if name not in have:
            lll.run(["label", "create", "-n", name])
            created += 1
    note("labels", len(wanted_labels), created, len(wanted_labels) - created)

    # -- projects (milestones) ----------------------------------------------
    have = {p["name"] for p in pb_list(url, token, "projects", f"team.key='{TEAM_KEY}'")}
    created = 0
    for mid in sorted(milestones):
        if milestones[mid] not in have:
            lll.run(["project", "create", "-n", milestones[mid]])
            created += 1
    note("projects", len(milestones), created, len(milestones) - created)

    # -- issues ---------------------------------------------------------------
    origin_re = re.compile(r"^Origin: sidecar (TASK-\d+)\s*$", re.M)
    existing = {}
    for rec in pb_list(url, token, "issues", f"team.key='{TEAM_KEY}'"):
        m = origin_re.search(rec.get("description", ""))
        if m:
            existing[m.group(1)] = rec["number"]
    created = skipped = 0
    made_keys = {}  # TASK-nnn -> LLL-n created THIS run (for the link pass)
    for num, f, body, path in tasks:
        origin = f["id"]
        if origin in existing:
            skipped += 1
            continue
        desc = clean_body(body)
        deps = f.get("dependencies") or []
        if deps:
            desc += "\n\n" + "\n".join(f"Blocked by {d}" for d in deps)
        desc += f"\n\nOrigin: sidecar {origin}"
        if f.get("created_date"):
            desc += f"\nCreated: {f['created_date']}"
        cmd = ["issue", "create", "-t", f["title"], "-d", "-", "--json"]
        prio = PRIORITY_MAP.get(str(f.get("priority", "")).lower())
        if prio:
            cmd += ["--priority", prio]
        assignees = f.get("assignee") or []
        if assignees:
            cmd += ["--assignee", assignees[0].lstrip("@")]
        if len(assignees) > 1:
            print(f"  note: {origin} has {len(assignees)} assignees; kept the first")
        for lab in f.get("labels") or []:
            cmd += ["--label", lab]
        mid = f.get("milestone")
        if mid:
            cmd += ["--project", milestones[mid]]
        rec = json.loads(lll.run(cmd, stdin=desc))
        key = f"{TEAM_KEY}-{rec['number']}"
        made_keys[origin] = key
        state = STATE_MAP[f["status"]]
        if state != "todo":
            lll.run(["issue", "update", key, "--state", state])
        created += 1
        print(f"  {origin} -> {key}")
    note("issues", len(tasks), created, skipped)

    # -- docs -------------------------------------------------------------
    have = {d["slug"] for d in pb_list(url, token, "docs", f"team.key='{TEAM_KEY}'")}
    created = skipped = 0
    docid_to_slug = {}
    for d in docs:
        if d["doc_id"]:
            docid_to_slug[d["doc_id"]] = d["slug"]
        if d["slug"] in have:
            skipped += 1
            continue
        body = d["body"] + f"\n\nOrigin: sidecar {d['origin']}\n"
        cmd = ["doc", "new", "-s", d["slug"], "-t", d["title"], "-k", d["kind"], "-b", "-"]
        if d["area"]:
            cmd += ["-a", d["area"]]
        lll.run(cmd, stdin=body)
        created += 1
    note("docs", len(docs), created, skipped)

    # -- issue->doc links (backlog 'documentation:' field, e.g. doc-1) -----
    linked = 0
    for num, f, body, path in tasks:
        key = made_keys.get(f["id"])
        if not key:
            continue  # pre-existing issue: assume its links were made with it
        for did in f.get("documentation") or []:
            slug = docid_to_slug.get(did)
            if slug:
                lll.run(["issue", "link", key, slug])
                linked += 1
    if linked:
        print(f"  linked {linked} issue->doc references")

    # -- report -------------------------------------------------------------
    print(f"\nimport into {url} team {TEAM_KEY}:")
    print(f"  {'collection':<10} {'source':>6} {'created':>8} {'skipped':>8}")
    for kind in ("teams", "members", "labels", "projects", "issues", "docs"):
        s, c, k = report[kind]
        print(f"  {kind:<10} {s:>6} {c:>8} {k:>8}")


if __name__ == "__main__":
    main()
