"""S7 P04: canonical Devtool adoption on a real Go/Android-split consumer."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "Mikeyphw/chroot-ctl"


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True, timeout=30).stdout.strip()


def devtool(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-B", "-m", "devtool", "--repo", str(root), *args],
                            capture_output=True, text=True, timeout=100, env=env)
    if check and result.returncode:
        raise AssertionError("Devtool command refused: " + result.stdout[-1600:] + result.stderr[-1600:])
    return result


class GoConsumerPilot(unittest.TestCase):
    def test_go_target_retains_authoritative_separation(self):
        # Do not migrate/alter the Android module or supported release target.
        source = (ROOT / ".devtool.toml").read_text(encoding="utf8")
        mod = (ROOT / "go.mod").read_text(encoding="utf8")
        self.assertIn("module chrootctl", mod)
        self.assertIn("[targets.chrootctl_go]", source)
        self.assertIn("[targets.chrootctl_root_module]", source)
        self.assertIn("runner = \"go\"", source)
        self.assertTrue((ROOT / "devtoolw").exists())
        self.assertTrue((ROOT / ".github/workflows/ci.yml").is_file())
        self.assertTrue((ROOT / ".github/workflows/devtool-chrootctl-build.yml").is_file())

    def test_exact_source_go_audit_does_not_modify_repository_or_qualify_release(self):
        before = git(ROOT, "status", "--porcelain", "--untracked-files=all")
        audit = devtool(ROOT, "delivery", "adoption", "audit", "--json")
        value = json.loads(audit.stdout)
        self.assertEqual(value["schema"], "devtool.delivery-adoption-audit.v1")
        self.assertEqual(value["repository"], REPOSITORY)
        self.assertEqual(value["source_sha"], git(ROOT, "rev-parse", "HEAD"))
        self.assertTrue(value["worktree_clean"])
        self.assertTrue(value["scaffolding_ready"])
        self.assertTrue(value["devtool_config_present"])
        self.assertFalse(value["ci_qualified"])
        self.assertFalse(value["release_qualified"])
        self.assertEqual(before, git(ROOT, "status", "--porcelain", "--untracked-files=all"))

    def test_native_scaffold_and_stale_exact_tree_refusal(self):
        with tempfile.TemporaryDirectory(prefix="s7-p04-go-") as td:
            p = Path(td)
            repo, payload = p / "source", p / "payload"
            repo.mkdir()
            payload.mkdir()
            git(repo, "init", "-b", "main")
            git(repo, "config", "user.name", "Go Pilot")
            git(repo, "config", "user.email", "go-pilot@example.invalid")
            git(repo, "remote", "add", "origin", "https://github.com/Mikeyphw/chroot-ctl.git")
            (repo / "README.md").write_text("baseline\n", encoding="utf8")
            (repo / ".gitignore").write_text(".devtool/\n", encoding="utf8")
            (repo / ".devtool.toml").write_text(
                '[project]\nrunner = "go"\nplatform = "repository"\n'
                '[targets.chrootctl_go]\nrunner = "go"\nplatform = "cli"\n',
                encoding="utf8")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "base")
            sha = git(repo, "rev-parse", "HEAD")
            (payload / "go.txt").write_text("source-bound-go\n", encoding="utf8")
            plan = p / "plan.json"
            plan.write_text(json.dumps({"schema_version": 1,
                                        "changes": [{"path": "go.txt", "action": "add"}]}))
            output = p / "go-adoption.zip"
            result = devtool(repo, "delivery", "adoption", "scaffold", "--payload", str(payload),
                             "--plan", str(plan), "--output", str(output),
                             "--expected-head", sha, "--json")
            self.assertEqual(json.loads(result.stdout)["source_sha"], sha)
            self.assertEqual(git(repo, "status", "--porcelain"), "")
            with zipfile.ZipFile(output) as z:
                self.assertIsNone(z.testzip())
                manifest = json.loads(z.read(".devtool-artifact.json"))
                self.assertEqual(manifest["base_commit"], sha)
                self.assertEqual(manifest["base_contract_mode"], "exact-tree")
                self.assertEqual(manifest["base_tree"], git(repo, "rev-parse", "HEAD^{tree}"))
            devtool(repo, "--target", "chrootctl_go", "validate", "overlay", str(output))
            (repo / "README.md").write_text("new clean HEAD\n", encoding="utf8")
            git(repo, "add", "README.md")
            git(repo, "commit", "-m", "drift")
            refused = devtool(repo, "--target", "chrootctl_go", "validate", "overlay", str(output), check=False)
            self.assertNotEqual(refused.returncode, 0)
            self.assertFalse((repo / "go.txt").exists())
            self.assertEqual(git(repo, "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
