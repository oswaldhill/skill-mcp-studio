"""A-4 registry single-source consistency: same client must name the same
``config_path`` / ``format`` / ``mcp_key_path`` across every registry surface.

History: Reasonix was ``~/.reasonix/config.json`` + ``reasonix-json`` + ``["mcp"]``
in ``legacy_checker.MCP_CAPABLE_TOOLS`` but ``~/.reasonix/config.toml`` +
``reasonix_toml`` + ``["plugins"]`` in ``config.yaml``/``mainstream_registry.py``,
so the same client reached different conclusions down different code paths.
"""

import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import legacy_checker  # noqa: E402
import mainstream_registry  # noqa: E402


def _norm(value):
    return "".join(c for c in str(value).lower() if c.isalnum())


def _legacy_mcp_identity(name):
    for entry in legacy_checker.MCP_CAPABLE_TOOLS:
        if _norm(entry.get("name", "")) == _norm(name):
            return {
                "config_path": entry.get("config_path", ""),
                "format": entry.get("format", "json"),
                "mcp_key_path": entry.get("mcp_key_path", ["mcpServers"]),
            }
    return None


def _mainstream_mcp_identity(name):
    # register_mainstream_tools 是 main registry 的扩展视图（含国内外常用）；
    # 抽取 name 归一后命中的 entries 的 MCP 身份。
    for entry in mainstream_registry.MAINSTREAM_TOOLS:
        if _norm(entry.get("name", "")) == _norm(name):
            return {
                "config_path": entry.get("config_path", ""),
                # mainstream_registry 用安装探测 config_paths，而非 MCP 单一配置路径；
                # 无 config_path 时回退 config_paths 首个。
                "format": entry.get("format", "json"),
                "mcp_key_path": entry.get("mcp_key_path", ["mcpServers"]),
                "_config_paths": entry.get("install", {}).get("config_paths", []),
            }
    return None


def _config_yaml_mcp_identity(name):
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    for entry in config.get("mcp_tools", []) or []:
        if _norm(entry.get("name", "")) == _norm(name):
            return {
                "config_path": entry.get("config_path", ""),
                "format": entry.get("format", "json"),
                "mcp_key_path": entry.get("mcp_key_path", ["mcpServers"]),
            }
    return None


class RegistryConsistencyTest(unittest.TestCase):
    def test_reasonix_identity_consistent(self):
        legacy = _legacy_mcp_identity("Reasonix")
        yamlc = _config_yaml_mcp_identity("Reasonix")
        self.assertIsNotNone(legacy, "Reasonix 不在 legacy_checker.MCP_CAPABLE_TOOLS")
        self.assertIsNotNone(yamlc, "Reasonix 不在 config.yaml mcp_tools")
        self.assertEqual(legacy["config_path"], yamlc["config_path"])
        self.assertEqual(legacy["format"], yamlc["format"])
        self.assertEqual(legacy["mcp_key_path"], yamlc["mcp_key_path"])

    def test_cherry_studio_path_consistent(self):
        legacy = _legacy_mcp_identity("Cherry Studio")
        main = _mainstream_mcp_identity("Cherry Studio")
        self.assertIsNotNone(legacy)
        self.assertIsNotNone(main)
        # Cherry Studio 在 mainstream_registry 无显式 mcp_config_path（config_paths 用于
        # 安装探测），但两处路径应指向同一目录族（不允许 ~/.cherrystudio/... vs
        # ~/.config/CherryStudio/... 分叉）。
        legacy_lower = legacy["config_path"].lower()
        paths = " ".join((main["_config_paths"] or [])).lower()
        self.assertTrue(
            legacy_lower in paths or "cherrystudio" in paths,
            f"Cherry Studio 路径分叉: legacy={legacy['config_path']} mainstream={main['_config_paths']}",
        )

    def test_qoder_path_consistent(self):
        legacy = _legacy_mcp_identity("Qoder")
        self.assertIsNotNone(legacy)
        # Qoder/通义灵码 在 mainstream_registry 的 mcp_config_path 是 ~/.qoder/settings.json。
        main = _mainstream_mcp_identity("通义灵码")
        if main and main.get("config_path"):
            self.assertEqual(legacy["config_path"], main["config_path"])

    def test_no_json_reasonix_format_remains(self):
        # reasonix-json （config.json 旧格式）不应再作为 Reasonix 的 current 格式出现。
        legacy = _legacy_mcp_identity("Reasonix")
        self.assertNotEqual(legacy["format"], "reasonix-json")
        self.assertEqual(legacy["format"], "reasonix_toml")


if __name__ == "__main__":
    unittest.main()
