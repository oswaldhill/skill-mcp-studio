import sys
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from cli_modes import resolve_modes  # noqa: E402


def args(**overrides):
    values = {
        "full": False,
        "skills": False,
        "mcp": False,
        "hooks": False,
        "probe_mcp": False,
        "report": False,
        "sync": False,
        "clean": False,
        "push": False,
        "fix": False,
        "fix_skills": False,
        "fix_mcp": False,
        "remove_legacy_mcp": False,
        "setup_all": False,
        "hermes": False,
        "ai_memory": False,
        "all_profiles": False,
    }
    values.update(overrides)
    return Namespace(**values)


class CliModesTest(unittest.TestCase):
    def test_default_is_read_only_combined_check(self):
        result = resolve_modes(args())
        self.assertTrue(result.skills)
        self.assertTrue(result.mcp)
        self.assertTrue(result.hooks)
        self.assertFalse(result.sync)
        self.assertFalse(result.clean)
        self.assertFalse(result.push)
        self.assertFalse(result.fix_skills)
        self.assertFalse(result.fix_mcp)

    def test_full_has_no_git_or_fix_side_effects(self):
        result = resolve_modes(args(full=True))
        self.assertTrue(result.skills)
        self.assertTrue(result.mcp)
        self.assertTrue(result.hooks)
        self.assertTrue(result.probe_mcp)
        self.assertTrue(result.report)
        self.assertFalse(result.sync)
        self.assertFalse(result.clean)
        self.assertFalse(result.push)
        self.assertFalse(result.fix_skills)
        self.assertFalse(result.fix_mcp)

    def test_legacy_flags_map_to_new_modes(self):
        result = resolve_modes(args(hermes=True, ai_memory=True, fix=True))
        self.assertTrue(result.mcp)
        self.assertTrue(result.hooks)
        self.assertTrue(result.fix_skills)

    def test_remove_legacy_requires_live_mcp_probe(self):
        result = resolve_modes(args(remove_legacy_mcp=True))
        self.assertTrue(result.mcp)
        self.assertTrue(result.probe_mcp)

    def test_setup_all_enables_repairs_and_post_repair_checks(self):
        result = resolve_modes(args(setup_all=True))
        self.assertTrue(result.skills)
        self.assertTrue(result.mcp)
        self.assertTrue(result.hooks)
        self.assertTrue(result.probe_mcp)
        self.assertTrue(result.fix_skills)
        self.assertTrue(result.fix_mcp)
        self.assertFalse(result.remove_legacy_mcp)

    def test_all_profiles_runs_full_probe_each_profile(self):
        result = resolve_modes(args(all_profiles=True))
        self.assertTrue(result.mcp)
        self.assertTrue(result.hooks)
        self.assertTrue(result.probe_mcp)

    def test_migrate_skill_links_is_explicit_write_mode(self):
        # --migrate-skill-links is an early-return write mode like the stage-4
        # toggles: the default skills/mcp/hooks checks must not also kick in.
        result = resolve_modes(args(migrate_skill_links=True))
        self.assertFalse(result.skills)
        self.assertFalse(result.mcp)
        self.assertFalse(result.hooks)


if __name__ == "__main__":
    unittest.main()
