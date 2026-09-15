#!/usr/bin/env python3
"""Generate src/commands/api_schema.lis from the real schema the migrations build.

Boots a throwaway board from the migrations embedded in the binary (same
isolation as scripts/scratch.sh: free ports, temp dir, scoped HOME, every LLL_*
variable unset), reads GET /api/collections as superuser, and writes the
collection/field reference as a Lisette string constant the `lll api --schema`
command prints. The live schema is the source rather than the migration
scripts themselves: the migrations span many files of creates, edits and rule
changes, and what PocketBase actually enforces is their end state.

Run with `mise run api-schema` (which builds first) or
`python3 scripts/gen_api_schema.py` against an existing target/.lisette/bin/lll.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BINARY = os.path.join(ROOT, "target", ".lisette", "bin", "lll")
OUT = os.path.join(ROOT, "src", "commands", "api_schema.lis")

ADMIN_EMAIL = "admin@local.dev"
ADMIN_PASSWORD = "admin-local-123"  # the same pair scripts/scratch.sh prints


def free_port(low, high):
    """Bind to claim a port, then release it: the probe cannot tell a free
    port from a stranger's server, and a listener of our own is stranger here
    too once the board boots."""
    for port in range(low, high):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise SystemExit(f"no free port in {low}..{high}")


def get(url, token=None):
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def wait_healthy(url, deadline_s=30):
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        try:
            get(url + "/api/health")
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.25)
    raise SystemExit(f"board did not become healthy at {url} within {deadline_s}s")


def boot_board():
    db_port = free_port(20000, 39999)
    web_port = free_port(40000, 59999)
    scratch = tempfile.mkdtemp(prefix="lll-apischema.")
    home = os.path.join(scratch, "home")
    os.mkdir(home)
    url = f"http://127.0.0.1:{db_port}"
    # Env beats files: unset every inherited LLL_* variable so a hosted url or
    # token cannot steer the throwaway board, then pin the scratch values.
    env = {k: v for k, v in os.environ.items() if not k.startswith("LLL_")}
    env.update(
        HOME=home,
        LLL_URL=url,
        LLL_TEAM="SCHEM",
        LLL_ME=ADMIN_EMAIL,
        LLL_BIND="127.0.0.1",
        LLL_ADMIN_EMAIL=ADMIN_EMAIL,
        LLL_ADMIN_PASSWORD=ADMIN_PASSWORD,
    )
    proc = subprocess.Popen(
        [BINARY, "up", "--port", str(web_port), "--pb-dir", os.path.join(scratch, "pb_data")],
        cwd=home, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_healthy(url)
    except BaseException:
        proc.terminate()
        raise
    return proc, url, scratch


def superuser_token(url):
    payload = json.dumps({"identity": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).encode()
    request = urllib.request.Request(
        url + "/api/collections/_superusers/auth-with-password", data=payload,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)["token"]


def collections(url, token):
    rows, page = [], 1
    while True:
        body = get(f"{url}/api/collections?perPage=200&page={page}", token)
        rows.extend(body["items"])
        if page * body["perPage"] >= body["totalItems"]:
            return rows
        page += 1


def field_notes(field, by_id):
    notes = []
    if field.get("maxSelect") not in (None, 1):
        notes.append(f"maxSelect: {field['maxSelect']}")
    if field.get("values"):
        notes.append("values: " + ", ".join(field["values"]))
    target = field.get("collectionId")
    if target:
        notes.append("relation to " + by_id.get(target, target))
    when = []
    if field.get("onCreate"):
        when.append("set on create")
    if field.get("onUpdate"):
        when.append("refreshed on update")
    if when:
        notes.append("; ".join(when))
    return "; ".join(notes)


def rule_text(rule):
    if rule is None:
        return "(superuser only)"
    if rule == "":
        return "(any)"
    return rule


def render(collections_json):
    # PocketBase seeds its own support collections (_authOrigins, _mfas, ...)
    # and a default `users` auth collection lll never touches; lll's own auth
    # collection is `members`. The reference is for integrators of lll's data,
    # so those stay out.
    collections_json = [
        c for c in collections_json
        if not c["name"].startswith("_") and c["name"] != "users"
    ]
    by_id = {c["id"]: c["name"] for c in collections_json}
    out = []
    out.append("lll board API - collection and field reference")
    out.append("")
    out.append("Generated from a board booted from pb/pb_migrations (the schema the")
    out.append("server enforces) by scripts/gen_api_schema.py; regenerate with")
    out.append("`mise run api-schema`. Never edit this output by hand.")
    out.append("")
    out.append("Every collection is served under /api/collections/<name>/records with")
    out.append("list/view/create/update/delete, filtered by PocketBase filter")
    out.append("expressions: ?filter=(state='todo' && title~'login'), sorted with")
    out.append("?sort=-created. Rules name who may call each verb: (any) is every")
    out.append("authenticated member, (superuser only) is nobody else, anything else")
    out.append("is the rule itself. Auth is the member token the CLI stores")
    out.append("(lll login, or lll token create), as `Authorization: Bearer <token>`;")
    out.append("`lll api METHOD PATH` sends it for you.")
    out.append("")
    for c in sorted(collections_json, key=lambda c: c["name"]):
        out.append(f"## {c['name']} ({c['type']})")
        out.append("")
        rules = " ".join(
            f"{verb} {rule_text(c.get(verb + 'Rule'))}"
            for verb in ("list", "view", "create", "update", "delete")
        )
        out.append(f"Rules: {rules}")
        out.append("")
        out.append("| field | type | required | notes |")
        out.append("|-------|------|----------|-------|")
        for f in c["fields"]:
            if f["name"] == "id":
                continue
            required = "yes" if f.get("required") else ""
            out.append(f"| {f['name']} | {f['type']} | {required} | {field_notes(f, by_id)} |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def lisette_constant(markdown):
    """Escape for a Lisette multiline string. It processes backslash escapes,
    and a bare quote ANYWHERE terminates the literal - a mid-line `"` ends the
    string and the rest fails to parse (verified against lis 0.12.0) - so
    backslashes double first and then every quote escapes, exactly as a Go
    literal would. The file is generated; readability is not its job."""
    body = markdown.replace("\\", "\\\\").replace('"', '\\"')
    return (
        "// GENERATED by scripts/gen_api_schema.py from the migrations' end state -\n"
        "// do not edit. Regenerate with: mise run api-schema\n"
        "\n"
        "/// The collection/field reference `lll api --schema` prints.\n"
        "pub fn schema_reference() -> string {\n"
        '  "\n' + body.rstrip("\n") + '\n"\n'
        "}\n"
    )


def main():
    if not os.access(BINARY, os.X_OK):
        raise SystemExit(f"{BINARY} is missing - run `mise run build` first")
    proc, url, scratch = boot_board()
    try:
        token = superuser_token(url)
        markdown = render(collections(url, token))
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(scratch, ignore_errors=True)
    with open(OUT, "w") as f:
        f.write(lisette_constant(markdown))
    print(f"wrote {os.path.relpath(OUT, ROOT)} ({len(markdown.splitlines())} lines)")


if __name__ == "__main__":
    main()
