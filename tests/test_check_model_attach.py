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


class UnifiedNameScopeTest(unittest.TestCase):
    """回归（2026-10-08 实测）：``unified_name`` 只对**统一端点**成立。

    ``unified_name`` 是「统一 Hermes 端点」在该客户端里的条目别名（config.yaml：
    「统一端点用独立 key 写入，避免覆盖本地桥」），但端点库里不止一个端点。
    早先的实现写成 ``tool.get("unified_name") or expected_name``，等于把别名无条件
    套到**每个**端点上 —— 审计 K8s 这类工具端点时也去查 ``hermes-unified``，读到的是
    hermes 的 URL，URL 校验必然失败，于是把已正确接入的端点判成「未配置」。实测
    Codex / OpenCode 因此长期停在 1/2（界面上就是「仍然只有一半」）。
    """

    def _config_with_unified(self):
        config = {
            "schema_version": 2,
            "active_profile": "hermes-home",
            "profiles": {
                "K8s-uat": {"name": "K8s", "url": "https://k8s.example.com/mcp",
                            "required_capabilities": {}},
                "hermes-home": {"name": "hermes", "url": "https://hermes.example.com/mcp",
                                "required_capabilities": {}},
            },
            "mcp_tools": [
                {"name": "Cursor", "config_path": "~/.cursor/mcp.json", "format": "json",
                 "mcp_key_path": ["mcpServers"], "unified_name": "hermes-unified"},
            ],
            "tools": [],
        }
        return config

    def _servers(self):
        # 客户端已按「统一端点用别名、其余用正典名」正确落库
        return {
            "K8s": {"url": "https://k8s.example.com/mcp"},
            "hermes-unified": {"url": "https://hermes.example.com/mcp"},
        }

    def test_non_unified_endpoint_is_not_checked_under_unified_name(self):
        """审计 K8s 端点时必须查 `K8s`，而不是 `hermes-unified`。"""
        config = self._config_with_unified()
        with patch("config_store.load_discovered", return_value=[]), \
                patch("combined_checker._load_tool_servers", return_value=self._servers()):
            result = check_agents(
                config, _scan_result(), live_probe=False,
                profile=config["profiles"]["K8s-uat"], endpoint_key="K8s-uat",
            )
        record = next(r for r in result["records"] if r["name"] == "Cursor")
        self.assertTrue(
            record["mcp_configured"],
            "K8s 端点已按正典名接入，不应因为 unified_name 而判为未配置",
        )
        self.assertEqual(record["configured_url"], "https://k8s.example.com/mcp")

    def test_unified_endpoint_still_uses_unified_name(self):
        """统一端点（active_profile）仍必须用别名核对，保住「不覆盖本地桥」的初衷。"""
        config = self._config_with_unified()
        with patch("config_store.load_discovered", return_value=[]), \
                patch("combined_checker._load_tool_servers", return_value=self._servers()):
            result = check_agents(
                config, _scan_result(), live_probe=False,
                profile=config["profiles"]["hermes-home"], endpoint_key="hermes-home",
            )
        record = next(r for r in result["records"] if r["name"] == "Cursor")
        self.assertTrue(record["mcp_configured"])
        self.assertEqual(record["configured_url"], "https://hermes.example.com/mcp")

    def test_both_endpoints_report_configured(self):
        """同一次遍历里两个端点都应判为已接入（即界面上的 2/2，而不是 1/2）。"""
        config = self._config_with_unified()
        flags = {}
        with patch("config_store.load_discovered", return_value=[]), \
                patch("combined_checker._load_tool_servers", return_value=self._servers()):
            for key in ("K8s-uat", "hermes-home"):
                result = check_agents(
                    config, _scan_result(), live_probe=False,
                    profile=config["profiles"][key], endpoint_key=key,
                )
                rec = next(r for r in result["records"] if r["name"] == "Cursor")
                flags[key] = rec["mcp_configured"]
        self.assertEqual(flags, {"K8s-uat": True, "hermes-home": True})


if __name__ == "__main__":
    unittest.main()
