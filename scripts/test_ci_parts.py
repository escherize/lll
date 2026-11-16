"""CI runs the gate as parallel parts (LLL-805). Those parts must add up to
what `mise run gate` runs locally, or a suite passes locally and never in CI."""
import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
STANDALONE = ROOT / "scripts" / "e2e_standalone.sh"


def listed(*args):
    out = subprocess.run(
        ["bash", str(STANDALONE), "--list", *args],
        check=True, capture_output=True, text=True,
    ).stdout
    return out.splitlines()


class CIParts(unittest.TestCase):
    def test_shards_partition_the_standalone_suites(self):
        everything = listed()
        self.assertEqual(len(everything), len(set(everything)), "a suite is listed twice")
        for n in (2, 3):
            shards = [listed("--shard", f"{i}/{n}") for i in range(1, n + 1)]
            self.assertEqual(sorted(sum(shards, [])), sorted(everything))

    def test_every_listed_suite_exists(self):
        for entry in listed():
            self.assertTrue((ROOT / "scripts" / entry.split()[0]).is_file(), entry)

    def test_e2e_runs_each_binary_only_suite_through_the_standalone_script(self):
        text = (ROOT / "scripts" / "e2e.sh").read_text()
        direct = re.findall(
            r'^python3 "\$REPO_ROOT"/scripts/(test_\w+\.py) "\$(?:LLL_ABS|LIN)"(?: [\w-]+)?$',
            text, re.M,
        )
        self.assertEqual(direct, [], "binary-only suites belong in e2e_standalone.sh")
        self.assertIn('scripts/e2e_standalone.sh --prebuilt "$LLL_ABS"', text)
        self.assertIn('"$REPO_ROOT"/scripts/e2e_web.sh', text)
        self.assertIn('"$REPO_ROOT"/scripts/e2e_up.sh', text)

    def test_workflow_runs_every_part(self):
        workflow = (ROOT / ".github" / "workflows" / "gate.yml").read_text()
        shards = sorted(re.findall(r"E2E_SHARD=(\d)/(\d) mise run e2e-standalone", workflow))
        self.assertTrue(shards, "no standalone shard in the workflow")
        total = shards[0][1]
        self.assertEqual(shards, [(str(i), total) for i in range(1, int(total) + 1)])
        for part in ("build test", "e2e-core", "e2e-web", "e2e-up"):
            self.assertRegex(workflow, rf"mise run {part}\b")

    def test_full_gate_still_runs_everything(self):
        mise = (ROOT / "mise.toml").read_text()
        self.assertIn('depends = ["build", "test", "e2e"]', mise)
        self.assertIn('LLL_CONFIG_HOME; bash scripts/e2e.sh"', mise)


if __name__ == "__main__":
    unittest.main()
