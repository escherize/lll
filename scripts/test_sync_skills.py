"""The shipped skills name only shipped skills, and the mirror is the source (LLL-703).

An agent in another repo ran /software-factory and got lll's own stage-3 list
(lisette-interop, datastar-fragments, pocketbase) and verify-gate, none of
which it could read. The old check only caught `../X/SKILL.md` links and
backticked names, so a bare list inside the stage table passed it.
"""
import unittest

import sync_skills
from sync_skills import MIRROR, PORTABLE, SOURCE, leaks

REPO_ONLY = ["datastar-fragments", "lisette-interop", "lll-repo", "parallel-work", "pocketbase"]

# The stage table the 0.x binaries shipped, verbatim.
OLD_MAP = """
```
  2 isolate     parallel-work    where do I work without colliding?
  3 build       (this codebase)  lisette-interop, datastar-fragments, pocketbase
```

[verify-gate](../verify-gate/SKILL.md)
"""


class LeakTests(unittest.TestCase):
    def test_the_old_map_is_caught(self):
        found = leaks({"software-factory": OLD_MAP}, REPO_ONLY)
        for name in ["parallel-work", "lisette-interop", "datastar-fragments", "pocketbase"]:
            self.assertIn(f"software-factory names {name}, which does not ship", found)
        self.assertIn("software-factory links to ../verify-gate/SKILL.md; a relative link is dead outside this repo", found)

    def test_a_relative_link_to_a_file_beside_the_skill_is_dead(self):
        # Only SKILL.md is mirrored; a features/ directory next to it is not.
        found = leaks({"verify-gate": "The map is in [features/](features/README.md)."}, REPO_ONLY)
        self.assertEqual(found, ["verify-gate links to features/README.md; a relative link is dead outside this repo"])

    def test_reference_and_angle_bracket_links_are_read(self):
        text = "See [map][m] and [up](<../lll/SKILL.md>).\n\n[m]: features/README.md\n"
        self.assertEqual(sorted(leaks({"verify-gate": text}, REPO_ONLY)), [
            "verify-gate links to ../lll/SKILL.md; a relative link is dead outside this repo",
            "verify-gate links to features/README.md; a relative link is dead outside this repo",
        ])

    def test_urls_anchors_and_longer_names_pass(self):
        text = ("See [docs](https://example.com/x) and [below](#cleanup) and [pb](<https://a.b>). "
                "The vendor docs are at https://pocketbase.io/docs. "
                "A pocketbase-adapter or my-parallel-work-tool is not a skill name. PocketBase is prose.")
        self.assertEqual(leaks({"lll": text}, REPO_ONLY), [])


class TreeTests(unittest.TestCase):
    def test_this_tree_ships_nothing_it_does_not_carry(self):
        repo_only = sorted(d.name for d in SOURCE.iterdir()
                           if (d/"SKILL.md").is_file() and d.name not in PORTABLE)
        self.assertEqual(leaks(sync_skills.wanted(), repo_only), [])

    def test_verify_gate_ships(self):
        self.assertIn("verify-gate", PORTABLE)

    def test_every_mirrored_copy_is_its_source(self):
        # software-factory above all: the repo-local copy is the shipped one.
        for name in PORTABLE:
            source = (SOURCE/name/"SKILL.md").read_text()
            mirror = (MIRROR/name/"SKILL.md").read_text()
            self.assertEqual(source, mirror, f"{name}: run 'python3 scripts/sync_skills.py'")


if __name__ == "__main__":
    unittest.main()
