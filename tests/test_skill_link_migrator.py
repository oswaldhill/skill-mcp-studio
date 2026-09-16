"""Stage-4 follow-up: root -> per_skill link migration (design §14.1 P2).

Single-skill enable/disable requires the per-skill symlink form; every real
client today is root form. ``migrate_client_links`` converts one client with
the mcp_fixer safety shape: staging build -> backup root link -> atomic swap
-> post-write validate -> rollback on failure.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from skill_link_migrator import migrate_client_links  # noqa: E402
from skill_state import classify_skill_state, skill_link_form  # noqa: E402


def build_env(tmp):
    """repo with two skills; client as a root symlink at the repo."""
    repo = Path(tmp) / "repo"
    (repo / "memory-basic").mkdir(parents=True)
    (repo / "tdai").mkdir()
    client_parent = Path(tmp) / "client"
    client_parent.mkdir()
    client = client_parent / "skills"
    os.symlink(repo, client, target_is_directory=True)
    return repo, client


def tool(client):
    return {"name": "T", "skills_paths": [str(client)], "fix_supported": True}


class MigrateClientLinksTest(unittest.TestCase):
    def test_root_form_migrates_to_per_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, client = build_env(tmp)
            result = migrate_client_links(tool(client), str(repo))
            self.assertEqual(result["status"], "migrated")
            self.assertFalse(os.path.islink(str(client)))
            self.assertTrue(os.path.isdir(str(client)))
            self.assertEqual(skill_link_form(str(client), str(repo)), "per_skill")
            for skill in ("memory-basic", "tdai"):
                link = client / skill
                self.assertTrue(os.path.islink(str(link)))
                self.assertEqual(
                    classify_skill_state(str(client), str(repo), skill), "enabled"
                )
            # original root link backed up then dropped on success
            leftovers = [
                p for p in os.listdir(str(client.parent)) if p != "skills"
            ]
            self.assertEqual(leftovers, [])

    def test_repo_is_not_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, client = build_env(tmp)
            migrate_client_links(tool(client), str(repo))
            self.assertEqual(sorted(os.listdir(str(repo))), ["memory-basic", "tdai"])
            self.assertTrue(os.path.isdir(repo / "memory-basic"))

    def test_dry_run_leaves_root_link_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, client = build_env(tmp)
            result = migrate_client_links(tool(client), str(repo), dry_run=True)
            self.assertEqual(result["status"], "dry-run")
            self.assertTrue(os.path.islink(str(client)))
            self.assertEqual(skill_link_form(str(client), str(repo)), "root")

    def test_already_per_skill_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, client = build_env(tmp)
            os.unlink(str(client))
            client.mkdir()
            os.symlink(repo / "tdai", client / "tdai", target_is_directory=True)
            result = migrate_client_links(tool(client), str(repo))
            self.assertEqual(result["status"], "unchanged")
            self.assertTrue(os.path.islink(str(client / "tdai")))

    def test_mixed_form_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, client = build_env(tmp)
            os.unlink(str(client))
            client.mkdir()
            (client / "real-entry").mkdir()
            os.symlink(repo / "tdai", client / "tdai", target_is_directory=True)
            result = migrate_client_links(tool(client), str(repo))
            self.assertEqual(result["status"], "skip")
            self.assertTrue((client / "real-entry").is_dir())

    def test_fix_unsupported_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, client = build_env(tmp)
            t = tool(client)
            t["fix_supported"] = False
            result = migrate_client_links(t, str(repo))
            self.assertEqual(result["status"], "unsupported")
            self.assertTrue(os.path.islink(str(client)))

    def test_no_skills_paths_errors(self):
        result = migrate_client_links({"name": "T", "skills_paths": []}, "/tmp")
        self.assertEqual(result["status"], "error")

    def test_empty_repo_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "empty-repo"
            repo.mkdir()
            _, client = build_env(tmp)
            os.unlink(str(client))
            os.symlink(repo, client, target_is_directory=True)
            result = migrate_client_links(tool(client), str(repo))
            self.assertEqual(result["status"], "error")
            self.assertIn("no skills", result["message"])
            self.assertTrue(os.path.islink(str(client)))

    def test_validate_failure_rolls_back_to_root_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, client = build_env(tmp)
            with mock.patch(
                "skill_link_migrator._validate_migration", return_value=False
            ):
                result = migrate_client_links(tool(client), str(repo))
            self.assertEqual(result["status"], "error")
            self.assertIn("rolled back", result["message"])
            self.assertTrue(os.path.islink(str(client)))
            self.assertEqual(
                os.path.realpath(str(client)), os.path.realpath(str(repo))
            )
            leftovers = [p for p in os.listdir(str(client.parent)) if p != "skills"]
            self.assertEqual(leftovers, [])

    def test_rollback_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, client = build_env(tmp)
            # swap (2x os.replace) succeeds; the rollback restore (3rd) fails
            with mock.patch(
                "skill_link_migrator._validate_migration", return_value=False
            ), mock.patch(
                "os.replace", side_effect=[None, None, OSError("denied")]
            ):
                result = migrate_client_links(tool(client), str(repo))
            self.assertEqual(result["status"], "error")
            self.assertIn("rollback failed", result["message"])


if __name__ == "__main__":
    unittest.main()
