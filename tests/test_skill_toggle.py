"""Stage-4 skill enable/disable (ADR-18 / ADR-21).

Toggles reuse the mcp_fixer backup -> atomic write -> validate -> rollback
shape, but the "atomic write" of a symlink is ``os.symlink(temp) + os.replace``
(ADR-21) so there is no unlink/symlink window. Disable records the prior link
target so a failed validate can restore it exactly.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from skill_toggle import disable_skill, enable_skill  # noqa: E402
from skill_state import classify_skill_state  # noqa: E402


def tool(skills_dir, **overrides):
    value = {
        "name": "Test Client",
        "skills_paths": [str(skills_dir)],
        "fix_supported": True,
    }
    value.update(overrides)
    return value


class EnableSkillTest(unittest.TestCase):
    def test_enable_creates_per_skill_symlink_pointing_at_repo_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)

            result = enable_skill(tool(client), "memory-basic", str(repo))

            self.assertEqual(result["status"], "updated")
            link = client / "memory-basic"
            self.assertTrue(link.is_symlink())
            self.assertEqual(os.path.realpath(link), os.path.realpath(repo / "memory-basic"))

    def test_enable_refuses_when_skill_not_in_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)

            result = enable_skill(tool(client), "absent", str(repo))

            self.assertEqual(result["status"], "error")
            self.assertIn("not in repo", result["message"].lower())
            self.assertFalse((client / "absent").exists())

    def test_enable_skips_root_form_client_with_no_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.parent.mkdir(parents=True)
            os.symlink(repo, client, target_is_directory=True)  # root form

            result = enable_skill(tool(client), "memory-basic", str(repo))

            self.assertEqual(result["status"], "skip")
            self.assertIn("root", result["message"].lower())

    def test_enable_refuses_when_fix_not_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)

            result = enable_skill(tool(client, fix_supported=False), "memory-basic", str(repo))

            self.assertEqual(result["status"], "unsupported")
            self.assertFalse((client / "memory-basic").exists())

    def test_enable_unchanged_when_already_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            os.symlink(repo / "memory-basic", client / "memory-basic", target_is_directory=True)

            result = enable_skill(tool(client), "memory-basic", str(repo))

            self.assertEqual(result["status"], "unchanged")

    def test_enable_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)

            result = enable_skill(tool(client), "memory-basic", str(repo), dry_run=True)

            self.assertEqual(result["status"], "dry-run")
            self.assertFalse((client / "memory-basic").exists())

    def test_enable_replaces_wrong_target_and_rolls_back_on_validate_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            other = Path(tmp) / "other"
            other.mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            os.symlink(other, client / "memory-basic", target_is_directory=True)

            # force the post-write validate to fail (the new link resolves fine,
            # but classify must say enabled; make realpath mismatch by patching
            # classify_skill_state to report disabled)
            with patch("skill_toggle.classify_skill_state", return_value="disabled"):
                result = enable_skill(tool(client), "memory-basic", str(repo))

            self.assertEqual(result["status"], "error")
            self.assertIn("rolled back", result["message"].lower())
            # original wrong link restored exactly
            self.assertEqual(os.readlink(client / "memory-basic"), str(other))

    def test_enable_survives_symlinked_path_depth_mismatch(self):
        # macOS /var -> /private/var (and any symlinked dir prefix) makes a
        # client dir's *logical* path shallower than its *physical* path. A
        # relative link target computed from logical paths then resolves from
        # the physical location and misses the repo by the prefix depth. The
        # target must be computed against realpath on both sides.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            (repo / "memory-basic").mkdir(parents=True)
            deep = base / "a" / "b"          # physical parent: two components
            deep.mkdir(parents=True)
            alias = base / "x"               # logical parent: one component
            os.symlink(deep, alias, target_is_directory=True)
            client = alias / "skills"        # logical base/x/skills, physical base/a/b/skills
            client.mkdir()

            result = enable_skill(tool(client), "memory-basic", str(repo))

            self.assertEqual(result["status"], "updated")
            link = client / "memory-basic"
            self.assertTrue(link.is_symlink())
            self.assertEqual(
                os.path.realpath(str(link)), os.path.realpath(str(repo / "memory-basic"))
            )
            self.assertEqual(
                classify_skill_state(str(client), str(repo), "memory-basic"), "enabled"
            )


class DisableSkillTest(unittest.TestCase):
    def test_disable_removes_per_skill_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            os.symlink(repo / "memory-basic", client / "memory-basic", target_is_directory=True)

            result = disable_skill(tool(client), "memory-basic", str(repo))

            self.assertEqual(result["status"], "updated")
            self.assertFalse((client / "memory-basic").is_symlink())

    def test_disable_unchanged_when_already_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)

            result = disable_skill(tool(client), "memory-basic", str(repo))

            self.assertEqual(result["status"], "unchanged")

    def test_disable_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            os.symlink(repo / "memory-basic", client / "memory-basic", target_is_directory=True)

            result = disable_skill(tool(client), "memory-basic", str(repo), dry_run=True)

            self.assertEqual(result["status"], "dry-run")
            self.assertTrue((client / "memory-basic").is_symlink())

    def test_disable_rolls_back_on_validate_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            os.symlink(repo / "memory-basic", client / "memory-basic", target_is_directory=True)
            original_target = os.readlink(client / "memory-basic")

            with patch("skill_toggle.classify_skill_state", return_value="enabled"):
                result = disable_skill(tool(client), "memory-basic", str(repo))

            self.assertEqual(result["status"], "error")
            self.assertIn("rolled back", result["message"].lower())
            # link restored with original target
            self.assertTrue((client / "memory-basic").is_symlink())
            self.assertEqual(os.readlink(client / "memory-basic"), original_target)

    def test_disable_skips_root_form_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.parent.mkdir(parents=True)
            os.symlink(repo, client, target_is_directory=True)

            result = disable_skill(tool(client), "memory-basic", str(repo))

            self.assertEqual(result["status"], "skip")
            self.assertIn("root", result["message"].lower())


if __name__ == "__main__":
    unittest.main()
