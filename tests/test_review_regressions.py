"""Regression locks for the 2026-09-04 review remediation (评审整改).

Locks the defect paths surfaced by the design-vs-implementation review:

- CLI-3 / TST-2: ``--strict-skill-state`` must reach ``result_ok`` on ALL three
  exit-code paths (main flow, ``--all-profiles``, single-profile snapshot).
- CLI-2: an illegal ``transport`` value must fail fast at profile load (exit 2
  channel), never silently probe as HTTP; ``probe_mcp`` itself also refuses it.
- CLI-1 / TST-1: ``--all-profiles`` maps profile/template load failures and
  audit-execution exceptions to exit code 2, while a pure probe failure stays 1.
- DATA-1 / P4-1: L2 ``checker._per_skill_link_states`` and L5
  ``classify_skill_state`` use the SAME exact-match rule (a link pointing at a
  different repo skill is not that entry's enable link). Locked in
  tests/test_skill_state.py::test_link_to_other_skill_or_repo_root_is_not_enabled.
"""

import sys
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

import scan  # noqa: E402
from profile_loader import ProfileError, load_profile  # noqa: E402
from mcp_probe import probe_mcp  # noqa: E402


def _args(**overrides):
    values = {
        "profile": None,
        "config": "config.yaml",
        "discover": False,
        "format": "json",
        "strict_skill_state": False,
    }
    values.update(overrides)
    return Namespace(**values)


def _compliant_result(skill_state_consistent=True):
    return {
        "probe": {"error": ""},
        "records": [],
        "unmanaged": [],
        "summary": {"skill_state_consistent": skill_state_consistent},
    }


class StrictSkillStatePassthroughTest(unittest.TestCase):
    """--strict-skill-state must affect the ok judgment on every export path."""

    def test_all_profiles_strict_fails_on_drift(self):
        with mock.patch.object(scan, "run_scan", return_value={}), \
                mock.patch.object(scan, "list_profiles", return_value=["p1"]), \
                mock.patch.object(scan, "load_profile", return_value={"name": "p1", "profile": {}}), \
                mock.patch.object(scan, "check_agents", return_value=_compliant_result(False)), \
                mock.patch.object(scan, "report_all_profiles", return_value=""):
            # 无漂移判定：不带 --strict → 0；带 --strict → 1（漂移纳入判定）
            self.assertEqual(scan._run_all_profiles(_args(), {}, "config.yaml"), 0)
            self.assertEqual(
                scan._run_all_profiles(_args(strict_skill_state=True), {}, "config.yaml"), 1
            )

    def test_single_profile_snapshot_strict_fails_on_drift(self):
        with mock.patch.object(scan, "load_profile", return_value={"name": "p1", "profile": {}}), \
                mock.patch.object(scan, "run_scan", return_value={}), \
                mock.patch.object(scan, "check_agents", return_value=_compliant_result(False)), \
                mock.patch.object(scan, "report_all_profiles", return_value=""):
            self.assertEqual(scan._run_single_profile_snapshot(_args(), {}, "config.yaml"), 0)
            self.assertEqual(
                scan._run_single_profile_snapshot(_args(strict_skill_state=True), {}, "config.yaml"), 1
            )


class TransportWhitelistTest(unittest.TestCase):
    """Illegal transport values must fail fast (exit-2 channel), not probe as HTTP."""

    def test_profile_loader_rejects_illegal_transport(self):
        config = {
            "profiles": {"p": {"name": "p", "transport": "sse", "url": "https://x/mcp"}},
            "active_profile": "p",
        }
        with self.assertRaises(ProfileError):
            load_profile(config)

    def test_probe_mcp_refuses_illegal_transport(self):
        result = probe_mcp("https://x/mcp", transport="stream")
        self.assertFalse(result["initialize_ok"])
        self.assertIn("unsupported transport", result["error"])


class AllProfilesInternalErrorTest(unittest.TestCase):
    """Audit-execution exceptions inside --all-profiles map to exit code 2."""

    def test_check_agents_exception_returns_2(self):
        with mock.patch.object(scan, "run_scan", return_value={}), \
                mock.patch.object(scan, "list_profiles", return_value=["p1"]), \
                mock.patch.object(scan, "load_profile", return_value={"name": "p1", "profile": {}}), \
                mock.patch.object(scan, "check_agents", side_effect=RuntimeError("boom")), \
                mock.patch.object(scan, "report_all_profiles", return_value=""):
            self.assertEqual(scan._run_all_profiles(_args(), {}, "config.yaml"), 2)

    def test_probe_failure_stays_exit_1(self):
        # 端点探测失败（非配置错误、非内部异常）仍为 1：分层语义锁定。
        with mock.patch.object(scan, "run_scan", return_value={}), \
                mock.patch.object(scan, "list_profiles", return_value=["p1"]), \
                mock.patch.object(scan, "load_profile", return_value={"name": "p1", "profile": {}}), \
                mock.patch.object(scan, "check_agents",
                                  return_value={"probe": {"error": "connect fail"},
                                                "records": [], "unmanaged": [], "summary": {}}), \
                mock.patch.object(scan, "report_all_profiles", return_value=""):
            self.assertEqual(scan._run_all_profiles(_args(), {}, "config.yaml"), 1)


if __name__ == "__main__":
    unittest.main()
