"""Stage-4 skill-state tri-state classification (ADR-17).

enabled / disabled / not_in_repo for each (installed client x repo skill), plus the
client skills-dir link-form (root / per_skill / mixed) used by the toggle gate.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from skill_state import (  # noqa: E402
    classify_skill_state,
    read_nested_meta,
    read_skill_meta,
    read_skill_states,
    repo_skill_names,
    scan_skill_nesting,
    skill_link_form,
    write_skill_state,
)
from checker import _all_entries_point_to_unified, _per_skill_link_states  # noqa: E402


class ReadSkillMetaTest(unittest.TestCase):
    def test_reads_frontmatter_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "alpha").mkdir()
            (repo / "alpha" / "SKILL.md").write_text(
                "---\nname: alpha\ndescription: Does alpha things.\n---\n\n# Alpha\n", encoding="utf-8"
            )
            (repo / "beta").mkdir()
            (repo / "beta" / "SKILL.md").write_text(
                "---\nname: beta\nmetadata:\n  short-description: Short beta blurb.\n---\n\n# Beta\n", encoding="utf-8"
            )
            (repo / "gamma").mkdir()  # no SKILL.md -> empty description, still present
            meta = read_skill_meta(str(repo), ["alpha", "beta", "gamma"])
            self.assertEqual(meta["alpha"]["description"], "Does alpha things.")
            self.assertEqual(meta["alpha"]["homepage"], "")
            self.assertEqual(meta["beta"]["description"], "Short beta blurb.")
            self.assertEqual(meta["gamma"], {"name": "gamma", "description": "", "homepage": ""})

    def test_missing_dir_yields_empty_entries(self):
        meta = read_skill_meta("/no/such/repo", ["foo", "bar"])
        self.assertEqual(meta, {"foo": {"name": "foo", "description": "", "homepage": ""}, "bar": {"name": "bar", "description": "", "homepage": ""}})

    def test_reads_frontmatter_homepage(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "hub").mkdir()
            (repo / "hub" / "SKILL.md").write_text(
                "---\nname: hub\ndescription: H.\nhomepage: https://example.com/hub\n---\n\n# Hub\n", encoding="utf-8"
            )
            (repo / "nested").mkdir()
            (repo / "nested" / "SKILL.md").write_text(
                "---\nname: nested\ndescription: N.\nmetadata:\n  homepage: https://example.com/nested\n---\n\n# Nested\n", encoding="utf-8"
            )
            meta = read_skill_meta(str(repo), ["hub", "nested"])
            self.assertEqual(meta["hub"]["homepage"], "https://example.com/hub")
            self.assertEqual(meta["nested"]["homepage"], "https://example.com/nested")


class RepoInventoryTest(unittest.TestCase):
    def test_returns_non_dot_subdirectories_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "memory-basic").mkdir()
            (repo / "tdai").mkdir()
            (repo / ".hidden").mkdir()
            (repo / "a-file.txt").write_text("x", encoding="utf-8")
            self.assertEqual(repo_skill_names(str(repo)), ["memory-basic", "tdai"])

    def test_missing_dir_yields_empty_list(self):
        self.assertEqual(repo_skill_names(str(Path("/no/such/dir/here"))), [])


class ScanSkillNestingTest(unittest.TestCase):
    def test_maps_container_dirs_to_nested_skill_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "apple").mkdir()
            (repo / "apple" / "SKILL.md").write_text("---\nname: apple\n---\n", encoding="utf-8")
            (repo / "apple" / "apple-notes").mkdir()
            (repo / "apple" / "apple-notes" / "SKILL.md").write_text("n", encoding="utf-8")
            (repo / "leaf").mkdir()
            (repo / "leaf" / "SKILL.md").write_text("---\nname: leaf\n---\n", encoding="utf-8")
            (repo / ".hidden").mkdir()
            (repo / ".hidden" / "sub").mkdir()
            (repo / ".hidden" / "sub" / "SKILL.md").write_text("h", encoding="utf-8")
            nesting = scan_skill_nesting(str(repo))
            self.assertEqual(nesting, {"apple": ["apple/apple-notes"]})

    def test_missing_dir_yields_empty_map(self):
        self.assertEqual(scan_skill_nesting("/no/such/repo"), {})


class ReadNestedMetaTest(unittest.TestCase):
    def test_reads_nested_description_and_display_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "apple").mkdir()
            (repo / "apple" / "apple-notes").mkdir()
            (repo / "apple" / "apple-notes" / "SKILL.md").write_text(
                "---\nname: Apple Notes\ndescription: Manage Apple Notes via the memo CLI.\n---\n\n", encoding="utf-8"
            )
            (repo / "apple" / "findmy").mkdir()
            (repo / "apple" / "findmy" / "SKILL.md").write_text(
                "---\ntitle: Find My\nmetadata:\n  short-description: Track Apple devices.\n---\n\n", encoding="utf-8"
            )
            nesting = {"apple": ["apple/apple-notes", "apple/findmy"]}
            meta = read_nested_meta(str(repo), nesting)
            self.assertEqual(meta["apple/apple-notes"]["name"], "Apple Notes")
            self.assertEqual(meta["apple/apple-notes"]["description"], "Manage Apple Notes via the memo CLI.")
            self.assertEqual(meta["apple/findmy"]["name"], "Find My")
            self.assertEqual(meta["apple/findmy"]["description"], "Track Apple devices.")

    def test_missing_nested_file_yields_directory_name_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "apple").mkdir()
            (repo / "apple" / "apple-notes").mkdir()  # no SKILL.md
            nesting = {"apple": ["apple/apple-notes"]}
            meta = read_nested_meta(str(repo), nesting)
            self.assertEqual(meta["apple/apple-notes"], {
                "name": "apple-notes",
                "description": "",
                "homepage": "",
            })

    def test_empty_nesting_yields_empty_map(self):
        self.assertEqual(read_nested_meta("/no/such/repo", {}), {})
        self.assertEqual(read_nested_meta("/no/such/repo", None), {})


class ClassifySkillStateTest(unittest.TestCase):
    def _build(self, tmp):
        repo = Path(tmp) / "repo"
        repo.mkdir()
        (repo / "memory-basic").mkdir()
        (repo / "tdai").mkdir()
        return repo

    def test_not_in_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._build(tmp)
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            self.assertEqual(
                classify_skill_state(str(client), str(repo), "absent-skill"),
                "not_in_repo",
            )

    def test_disabled_when_client_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._build(tmp)
            client = Path(tmp) / "client" / "skills"  # never created
            self.assertEqual(
                classify_skill_state(str(client), str(repo), "memory-basic"),
                "disabled",
            )

    def test_enabled_for_per_skill_symlink_to_repo_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._build(tmp)
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            # per-skill symlink points at the repo skill dir (DSH-style)
            os.symlink(repo / "memory-basic", client / "memory-basic", target_is_directory=True)
            self.assertEqual(
                classify_skill_state(str(client), str(repo), "memory-basic"),
                "enabled",
            )
            self.assertEqual(
                classify_skill_state(str(client), str(repo), "tdai"),
                "disabled",
            )

    def test_disabled_when_per_skill_symlink_points_wrong_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._build(tmp)
            other = Path(tmp) / "other"
            other.mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            os.symlink(other, client / "memory-basic", target_is_directory=True)
            self.assertEqual(
                classify_skill_state(str(client), str(repo), "memory-basic"),
                "disabled",
            )

    def test_enabled_for_root_symlink_to_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._build(tmp)
            client = Path(tmp) / "client" / "skills"
            client.parent.mkdir(parents=True)
            os.symlink(repo, client, target_is_directory=True)
            # root form => every repo skill is enabled
            self.assertEqual(
                classify_skill_state(str(client), str(repo), "memory-basic"),
                "enabled",
            )
            self.assertEqual(
                classify_skill_state(str(client), str(repo), "tdai"),
                "enabled",
            )

    def test_disabled_when_root_symlink_points_wrong_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._build(tmp)
            wrong = Path(tmp) / "wrong"
            wrong.mkdir()
            client = Path(tmp) / "client" / "skills"
            client.parent.mkdir(parents=True)
            os.symlink(wrong, client, target_is_directory=True)
            self.assertEqual(
                classify_skill_state(str(client), str(repo), "memory-basic"),
                "disabled",
            )


class SkillLinkFormTest(unittest.TestCase):
    def test_root_when_path_is_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            client = Path(tmp) / "client" / "skills"
            client.parent.mkdir(parents=True)
            os.symlink(repo, client, target_is_directory=True)
            self.assertEqual(skill_link_form(str(client), str(repo)), "root")

    def test_per_skill_when_all_entries_are_unified_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            (repo / "tdai").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            os.symlink(repo / "memory-basic", client / "memory-basic", target_is_directory=True)
            os.symlink(repo / "tdai", client / "tdai", target_is_directory=True)
            self.assertEqual(skill_link_form(str(client), str(repo)), "per_skill")

    def test_per_skill_when_dir_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            self.assertEqual(skill_link_form(str(client), str(repo)), "per_skill")

    def test_per_skill_ignores_dot_runtime_entries(self):
        # Real clients drop hidden runtime state into their skills dir (Codex
        # materializes .system/ with its own skills). Hidden entries are not
        # repo skills (dot rule) and must not flip per_skill to mixed.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            os.symlink(repo / "memory-basic", client / "memory-basic", target_is_directory=True)
            (client / ".system").mkdir()
            (client / ".codex-state").mkdir()
            self.assertEqual(skill_link_form(str(client), str(repo)), "per_skill")

    def test_mixed_when_symlinks_and_real_entries_coexist(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            os.symlink(repo / "memory-basic", client / "memory-basic", target_is_directory=True)
            (client / "local-skill").mkdir()  # real dir, not a symlink
            self.assertEqual(skill_link_form(str(client), str(repo)), "mixed")

    def test_mixed_when_real_dir_with_no_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            (client / "local-1").mkdir()
            (client / "local-2").mkdir()
            self.assertEqual(skill_link_form(str(client), str(repo)), "mixed")


class ReadSkillStatesTest(unittest.TestCase):
    def test_only_repo_skills_returned_no_not_in_repo_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            (repo / "tdai").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            os.symlink(repo / "memory-basic", client / "memory-basic", target_is_directory=True)
            states = read_skill_states(str(client), str(repo))
            self.assertEqual(set(states.keys()), {"memory-basic", "tdai"})
            self.assertEqual(states["memory-basic"], "enabled")
            self.assertEqual(states["tdai"], "disabled")

    def test_root_form_marks_all_repo_skills_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "a").mkdir()
            (repo / "b").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.parent.mkdir(parents=True)
            os.symlink(repo, client, target_is_directory=True)
            states = read_skill_states(str(client), str(repo))
            self.assertEqual(states, {"a": "enabled", "b": "enabled"})

    def test_native_disabled_marker_overrides_enabled_link(self):
        # A client-native disable marker (read-only, owned by the client
        # runtime) must win over an otherwise-valid enable link.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "a").mkdir()
            (repo / "b").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            os.symlink(repo / "a", client / "a", target_is_directory=True)
            os.symlink(repo / "b", client / "b", target_is_directory=True)
            states = read_skill_states(str(client), str(repo), native_disabled={"a"})
            self.assertEqual(states, {"a": "disabled", "b": "enabled"})

    def test_default_native_disabled_keeps_link_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "a").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            os.symlink(repo / "a", client / "a", target_is_directory=True)
            states = read_skill_states(str(client), str(repo))
            self.assertEqual(states, {"a": "enabled"})


class PerSkillLinkStatesTest(unittest.TestCase):
    """checker._per_skill_link_states: per-entry symlink state (design §5)."""

    def test_missing_dir_returns_empty_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_per_skill_link_states(str(Path(tmp) / "nope"), tmp), {})

    def test_empty_dir_returns_empty_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = Path(tmp) / "skills"
            client.mkdir()
            self.assertEqual(_per_skill_link_states(str(client), tmp), {})

    def test_mixed_entries_reported_individually(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "a").mkdir(parents=True)
            client = Path(tmp) / "skills"
            client.mkdir()
            os.symlink(repo / "a", client / "a", target_is_directory=True)  # valid
            (client / "real").mkdir()  # real dir -> False
            other = Path(tmp) / "other"
            other.mkdir()
            os.symlink(other, client / "wrong", target_is_directory=True)  # wrong target
            states = _per_skill_link_states(str(client), str(repo))
            self.assertEqual(states, {"a": True, "real": False, "wrong": False})

    def test_all_entries_point_to_unified_reuses_per_entry_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "a").mkdir(parents=True)
            client = Path(tmp) / "skills"
            client.mkdir()
            os.symlink(repo / "a", client / "a", target_is_directory=True)
            self.assertTrue(_all_entries_point_to_unified(str(client), str(repo)))
            (client / "real").mkdir()
            self.assertFalse(_all_entries_point_to_unified(str(client), str(repo)))

    def test_dot_runtime_entries_are_ignored_not_counted_invalid(self):
        # A hidden runtime dir (Codex .system/) must not make an otherwise
        # fully-unified per-skill dir look non-compliant at L2.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "a").mkdir(parents=True)
            client = Path(tmp) / "skills"
            client.mkdir()
            os.symlink(repo / "a", client / "a", target_is_directory=True)
            (client / ".system").mkdir()
            states = _per_skill_link_states(str(client), str(repo))
            self.assertEqual(states, {"a": True})
            self.assertTrue(_all_entries_point_to_unified(str(client), str(repo)))

    def test_link_to_other_skill_or_repo_root_is_not_enabled(self):
        # 链接指向仓库内"另一技能目录"或"仓库根目录"，均不构成该条目的
        # 启用链接（ADR-17 精确匹配：enabled = 链接指向与本条目同名的技能目录）。
        # 此前 commonpath 前缀匹配会把这种情况误判为有效，导致 L2 合规
        # 而 L5 判禁用的分歧（评审 DATA-1/P4-1）。
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "a").mkdir(parents=True)
            (repo / "b").mkdir(parents=True)
            client = Path(tmp) / "skills"
            client.mkdir()
            os.symlink(repo / "b", client / "a", target_is_directory=True)  # a -> repo/b
            os.symlink(repo, client / "b", target_is_directory=True)         # b -> repo root
            states = _per_skill_link_states(str(client), str(repo))
            self.assertEqual(states, {"a": False, "b": False})
            # L2 聚合：非全有效 → 不合规
            self.assertFalse(_all_entries_point_to_unified(str(client), str(repo)))
            # L5 精确语义：a 未启用
            from skill_state import classify_skill_state
            self.assertEqual(classify_skill_state(str(client), str(repo), "a"), "disabled")


class WriteSkillStateTest(unittest.TestCase):
    """skill_state.write_skill_state dispatches to the toggle operations."""

    def test_write_enabled_then_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            t = {"name": "T", "skills_paths": [str(client)], "fix_supported": True}

            result = write_skill_state(t, "memory-basic", "enabled", str(repo))
            self.assertEqual(result["status"], "updated")
            self.assertEqual(
                classify_skill_state(str(client), str(repo), "memory-basic"), "enabled"
            )

            result = write_skill_state(t, "memory-basic", "disabled", str(repo))
            self.assertEqual(result["status"], "updated")
            self.assertEqual(
                classify_skill_state(str(client), str(repo), "memory-basic"), "disabled"
            )

    def test_unknown_state_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = {"name": "T", "skills_paths": [tmp], "fix_supported": True}
            with self.assertRaises(ValueError):
                write_skill_state(t, "x", "maybe", tmp)


if __name__ == "__main__":
    unittest.main()
