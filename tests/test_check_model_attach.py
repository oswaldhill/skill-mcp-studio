"""Stage-5 P2: check_agents per-client attachment filtering."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from combined_checker import check_agents  # noqa: E402


def _scan_result(unified="~/.skills-manager/skills"):
    return {
        "unified_dir": unified,
        "results": [
            {"tool_name": "Cursor", "status": "correct", "is_installed": True,
             "expanded_path": "~/.cursor/skills"},
            {"tool_name": "Claude", "status": "correct", "is_installed": True,
             "expanded_path": "~/.claude/skills"},
        ],
    }


def _config():
    return {
        "schema_version": 2,
        "active_profile": "a",
        "profiles": {
            "a": {"name": "mcp-a", "url": "https://a.example.com/mcp", "required_capabilities": {}},
            "b": {"name": "mcp-b", "url": "https://b.example.com/mcp", "required_capabilities": {}},
        },
        "mcp_tools": [
            {"name": "Cursor", "config_path": "~/.cursor/mcp.json", "format": "json",
             "mcp_key_path": ["mcpServers"], "mcp_attach": ["a"]},
            {"name": "Claude", "config_path": "~/.claude.json", "format": "json",
             "mcp_key_path": ["mcpServers"], "mcp_attach": ["b"]},
        ],
        "tools": [],
    }


def _probe_urls():
    raise AssertionError("should not probe when live_probe=False")


class AttachmentFilterTest(unittest.TestCase):
    def test_default_full_matrix_when_no_attach(self):
        config = _config()
        for tool in config["mcp_tools"]:
            tool.pop("mcp_attach")
        with patch("config_store.load_discovered", return_value=[]):
            result = check_agents(
                config, _scan_result(), live_probe=False,
                profile=config["profiles"]["a"], endpoint_key="a",
            )
        names = sorted(r["name"] for r in result["records"])
        self.assertEqual(names, ["Claude", "Cursor"])  # byte-for-byte stage-2 behaviour

    def test_explicit_attach_narrows_records(self):
        result = check_agents(
            _config(), _scan_result(), live_probe=False,
            profile=_config()["profiles"]["a"], endpoint_key="a",
        )
        names = sorted(r["name"] for r in result["records"])
        self.assertEqual(names, ["Cursor"])  # only Cursor attaches to endpoint a

    def test_explicit_attach_other_endpoint(self):
        result = check_agents(
            _config(), _scan_result(), live_probe=False,
            profile=_config()["profiles"]["b"], endpoint_key="b",
        )
        names = sorted(r["name"] for r in result["records"])
        self.assertEqual(names, ["Claude"])

    def test_no_endpoint_key_keeps_full_matrix_even_with_attach(self):
        # endpoint_key=None (e.g. legacy single-profile paths) never filters.
        with patch("config_store.load_discovered", return_value=[]):
            result = check_agents(
                _config(), _scan_result(), live_probe=False,
                profile=_config()["profiles"]["a"], endpoint_key=None,
            )
        names = sorted(r["name"] for r in result["records"])
        self.assertEqual(names, ["Claude", "Cursor"])

    def test_arch6_attach_filter_applied_flag(self):
        """ARCH-6: summary carries attach_filter_applied so callers can see whether narrowing happened."""
        # explicit attach present -> filter applied
        narrowed = check_agents(
            _config(), _scan_result(), live_probe=False,
            profile=_config()["profiles"]["a"], endpoint_key="a",
        )
        self.assertTrue(narrowed["summary"]["attach_filter_applied"])

        # no mcp_attach declared anywhere -> full matrix, filter NOT applied
        config = _config()
        for tool in config["mcp_tools"]:
            tool.pop("mcp_attach", None)
        full = check_agents(
            config, _scan_result(), live_probe=False,
            profile=config["profiles"]["a"], endpoint_key="a",
        )
        self.assertFalse(full["summary"]["attach_filter_applied"])

        # endpoint_key=None -> never applied
        no_key = check_agents(
            _config(), _scan_result(), live_probe=False,
            profile=_config()["profiles"]["a"], endpoint_key=None,
        )
        self.assertFalse(no_key["summary"]["attach_filter_applied"])


class OverlayValidationTest(unittest.TestCase):
    """ARCH-4: apply_profile_sources must validate overlay endpoint keys."""

    def test_unknown_endpoint_in_overlay_raises(self):
        from profile_loader import apply_profile_sources, ProfileError

        config = {
            "profiles": {"a": {"name": "mcp-a", "url": "https://a/mcp"}},
            "mcp_tools": [{"name": "Cursor", "mcp_key_path": ["mcpServers"]}],
            "profile_sources": [],  # inline overlay below via direct call
        }
        # simulate an overlay dict referencing an endpoint that doesn't exist
        import tempfile
        import os
        import yaml

        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump({"client_mcp_attach": {"Cursor": ["a", "nonexistent"]}}, f)
            path = f.name
        try:
            config["profile_sources"] = [path]
            with self.assertRaises(ProfileError):
                apply_profile_sources(config)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
