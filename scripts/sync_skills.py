#!/usr/bin/env python3
"""Mirror the portable skills into skills/, which the binary embeds (LLL-404).

`.claude/skills/` stays the single editable source: it is where the harness
discovers them and where they are reviewed. The mirror exists because the copy
is forced, not preferred - `go help packages` says files and directories whose
names begin with "." or "_" are ignored by the go tool, so no package can live
under `.claude/`, and embed patterns may not contain ".." so none can reach in
from outside. There is no route that embeds `.claude/skills/` directly.

The mirror is committed rather than generated at build time, which is what
tracker-records-source-files-and-generated-mirrors allows, so that a clone
builds without a pre-step and the deploy context - an archive of HEAD - carries
it. `--check` is what stops a committed copy from becoming a second editable
source: it fails when the two differ, the same bargain check_assets.py and
protect_archive.py --check already make.

PORTABLE lists what ships. It is here rather than in each skill's frontmatter
on purpose: the harness parses that frontmatter, and an unrecognised key is a
risk taken for no gain when the set is this small and wants reviewing anyway.
Only skills about USING lll belong here. Skills about THIS codebase -
lisette-interop, datastar-fragments, pocketbase - are noise or worse inside a
binary someone runs against a different repo.
"""
import re
import shutil
import sys
from pathlib import Path

PORTABLE = ["software-factory", "lll", "backlog-loop", "merge-gate", "codebase-skills", "verify-gate"]

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".claude" / "skills"
MIRROR = ROOT / "skills"


def wanted() -> dict[str, str]:
    out = {}
    for name in PORTABLE:
        skill = SOURCE / name / "SKILL.md"
        if not skill.is_file():
            sys.exit(f"sync_skills: {skill.relative_to(ROOT)} does not exist")
        out[name] = skill.read_text()
    return out


def present() -> dict[str, str]:
    if not MIRROR.is_dir():
        return {}
    return {
        d.name: (d / "SKILL.md").read_text()
        for d in sorted(MIRROR.iterdir())
        if (d / "SKILL.md").is_file()
    }


def leaks(want: dict[str, str], repo_only: list[str]) -> list[str]:
    """What in the shipped bodies points at something the binary does not carry.

    Only SKILL.md is mirrored, so every relative link in a shipped skill is
    dead in every other repo (LLL-538), whether it names a sibling skill or a
    file beside it. And a repo-only skill named at all, linked, backticked or
    bare in a stage table, reads as "go read it" where there is nothing to read
    (LLL-647, LLL-703: the old map listed lisette-interop, datastar-fragments
    and pocketbase as plain text inside a code block).
    """
    out = []
    for name, text in want.items():
        # Inline links, angle brackets stripped, and reference definitions.
        targets = re.findall(r"\]\(<?([^)\s>]+)>?", text)
        targets += re.findall(r"(?m)^\s*\[[^\]]+\]:\s*<?([^\s>]+)", text)
        for target in targets:
            if not re.match(r"[a-z][a-z0-9+.-]*:|#", target):
                out.append(f"{name} links to {target}; a relative link is dead outside this repo")
        for other in repo_only:
            # Case-sensitive, and not inside a url or path (pocketbase.io/docs).
            if re.search(rf"(?<![\w./-]){re.escape(other)}(?![\w/-])", text):
                out.append(f"{name} names {other}, which does not ship")
    return out


def main() -> None:
    check = "--check" in sys.argv[1:]
    want, have = wanted(), present()

    # Repo specifics belong in the lll-repo overlay, which does not ship.
    repo_only = sorted(
        d.name for d in SOURCE.iterdir()
        if (d / "SKILL.md").is_file() and d.name not in PORTABLE
    )
    dead = leaks(want, repo_only)
    if dead:
        for line in dead:
            print(f"  {line}", file=sys.stderr)
        sys.exit("shipped skills point at skills that do not ship; move repo specifics to .claude/skills/lll-repo")

    if check:
        if want == have:
            print(f"skills mirror is current ({len(want)} portable)")
            return
        missing = sorted(set(want) - set(have))
        extra = sorted(set(have) - set(want))
        stale = sorted(n for n in set(want) & set(have) if want[n] != have[n])
        for n in missing:
            print(f"  missing from skills/: {n}", file=sys.stderr)
        for n in extra:
            print(f"  in skills/ but not portable: {n}", file=sys.stderr)
        for n in stale:
            print(f"  out of date in skills/: {n}", file=sys.stderr)
        sys.exit("skills mirror is stale — run 'python3 scripts/sync_skills.py'")

    # Remove only the skill directories, never the whole mirror: skills.go and
    # go.mod live here too, and an earlier rmtree of MIRROR deleted them - the
    # gate caught it as "local module ... has no go.mod". A skill dropped from
    # PORTABLE still leaves the binary, which is the property this needs.
    for existing in sorted(MIRROR.glob("*/SKILL.md")):
        shutil.rmtree(existing.parent)
    for name, text in want.items():
        target = MIRROR / name / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    print(f"mirrored {len(want)} portable skills into skills/")


if __name__ == "__main__":
    main()
