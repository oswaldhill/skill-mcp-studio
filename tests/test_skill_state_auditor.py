"""Stage-4 skill-state auditor: drift detection + disable-effective + idempotent gate."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from skill_state_auditor import (  # noqa: E402
    audit_skill_states,
    verify_disable_effective,
    verify_rollback_idempotent,
)


def rec(name, skill_states=None, installed=True):
    return {
        "name": name,
        "installed": installed,
        "skill_states": skill_states or {},
        "skill_link_form": "per_skill",
        "skills_total": len(skill_states or {}),
        "skills_enabled_count": sum(1 for v in (skill_states or {}).values() if v == "enabled"),
    }


class DriftAuditTest(unittest.TestCase):
    def test_no_drift_when_all_clients_agree(self):
        result = {
            "records": [
                rec("Claude Code", {"memory-basic": "enabled", "tdai": "enabled"}),
                rec("Cursor", {"memory-basic": "enabled", "tdai": "enabled"}),
            ],
            "unmanaged": [],
        }
        audit = audit_skill_states(result)
        self.assertEqual(audit["skill_state_drift"], [])
        self.assertTrue(audit["skill_state_consistent"])

    def test_drift_detected_when_one_client_disagrees(self):
        result = {
            "records": [
                rec("Claude Code", {"memory-basic": "enabled"}),
                rec("Cursor", {"memory-basic": "disabled"}),
                rec("Codex", {"memory-basic": "enabled"}),
            ],
            "unmanaged": [],
        }
        audit = audit_skill_states(result)
        self.assertFalse(audit["skill_state_consistent"])
        self.assertEqual(len(audit["skill_state_drift"]), 1)
        drift = audit["skill_state_drift"][0]
        self.assertEqual(drift["skill"], "memory-basic")
        self.assertFalse(drift["consistent"])
        # Cursor is the odd one out (the minority)
        self.assertEqual(drift["drift_clients"], ["Cursor"])

    def test_drift_ignores_uninstalled_clients(self):
        result = {
            "records": [
                rec("Claude Code", {"memory-basic": "enabled"}, installed=True),
                rec("Cursor", {"memory-basic": "disabled"}, installed=False),
            ],
            "unmanaged": [],
        }
        audit = audit_skill_states(result)
        self.assertTrue(audit["skill_state_consistent"])
        self.assertEqual(audit["skill_state_drift"], [])

    def test_drift_ignores_clients_without_skill_states(self):
        result = {
            "records": [
                rec("Claude Code", {"memory-basic": "enabled"}),
                rec("Reasonix", {}),  # no skills dir registered
            ],
            "unmanaged": [],
        }
        audit = audit_skill_states(result)
        self.assertTrue(audit["skill_state_consistent"])
        self.assertEqual(audit["skill_state_drift"], [])

    def test_consistent_when_single_client(self):
        result = {
            "records": [rec("Claude Code", {"memory-basic": "enabled", "tdai": "disabled"})],
            "unmanaged": [],
        }
        audit = audit_skill_states(result)
        self.assertTrue(audit["skill_state_consistent"])


class DisableEffectiveTest(unittest.TestCase):
    def test_effective_when_disabled_and_no_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            # no symlink -> disabled -> effective
            self.assertTrue(verify_disable_effective(str(client), str(repo), "memory-basic"))

    def test_not_effective_when_disabled_but_symlink_remains(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            # symlink present but points elsewhere -> state disabled, but link exists
            other = Path(tmp) / "other"
            other.mkdir()
            os.symlink(other, client / "memory-basic", target_is_directory=True)
            self.assertFalse(verify_disable_effective(str(client), str(repo), "memory-basic"))

    def test_not_applicable_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            os.symlink(repo / "memory-basic", client / "memory-basic", target_is_directory=True)
            # enabled skill: disable-effective is not applicable -> True (vacuously ok)
            self.assertTrue(verify_disable_effective(str(client), str(repo), "memory-basic"))


class RollbackIdempotentTest(unittest.TestCase):
    def test_enable_disable_enable_restores_state_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            tool = {"name": "T", "skills_paths": [str(client)], "fix_supported": True}

            gate = verify_rollback_idempotent(tool, "memory-basic", str(repo))

            self.assertTrue(gate["ok"], gate.get("message", ""))
            # final state restored to disabled (started disabled)
            from skill_state import classify_skill_state
            self.assertEqual(classify_skill_state(str(client), str(repo), "memory-basic"), "disabled")

    def test_gate_is_non_destructive_on_real_client_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "memory-basic").mkdir()
            client = Path(tmp) / "client" / "skills"
            client.mkdir(parents=True)
            # pre-existing unrelated entry must survive the gate
            (client / "unrelated").mkdir()
            tool = {"name": "T", "skills_paths": [str(client)], "fix_supported": True}

            verify_rollback_idempotent(tool, "memory-basic", str(repo))

            self.assertTrue((client / "unrelated").exists())


if __name__ == "__main__":
    unittest.main()
