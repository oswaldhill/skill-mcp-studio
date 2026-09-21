"""A-6 config_codec 单一实现：key 解析逻辑只在 config_codec.py 出现一次。

mcp_checker / legacy_checker / mcp_fixer 的 TOML / Reasonix / cordis 解析器都
委托到 config_codec，因此同一份配置文本经任意链路解析必须得到相同结果。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import config_codec  # noqa: E402


class ParseTomlMcpServersTest(unittest.TestCase):
    def test_basic_section(self):
        text = '[mcp_servers.hermes]\nurl = "https://mcp.example.com/mcp"\n'
        servers = config_codec.parse_toml_mcp_servers(text)
        self.assertEqual(servers, {"hermes": {"url": "https://mcp.example.com/mcp"}})

    def test_env_child_table_collapses_into_env(self):
        text = (
            "[mcp_servers.hermes]\n"
            'url = "https://mcp.example.com/mcp"\n'
            "[mcp_servers.hermes.env]\n"
            'NAS_GATEWAY_URL = "http://nas:8642"\n'
        )
        servers = config_codec.parse_toml_mcp_servers(text)
        self.assertEqual(
            servers["hermes"]["env"],
            {"NAS_GATEWAY_URL": "http://nas:8642"},
        )

    def test_inline_list_value(self):
        text = (
            "[mcp_servers.hermes]\n"
            'args = ["python3", "-m", "hermes_bridge"]\n'
        )
        servers = config_codec.parse_toml_mcp_servers(text)
        self.assertEqual(
            servers["hermes"]["args"],
            ["python3", "-m", "hermes_bridge"],
        )


class ParseReasonixTest(unittest.TestCase):
    def test_reasonix_json_string_array(self):
        text = '{"mcp": ["hermes=python3 ~/.local/bin/hermes-bridge.py --flag"]}'
        servers = config_codec.parse_reasonix_json(text)
        self.assertEqual(
            servers,
            {"hermes": {"command": "python3", "args": ["~/.local/bin/hermes-bridge.py", "--flag"]}},
        )

    def test_reasonix_toml_plugins(self):
        text = (
            "[[plugins]]\n"
            'name = "hermes"\n'
            'type = "http"\n'
            'url = "https://mcp.example.com/mcp"\n'
        )
        servers = config_codec.parse_reasonix_toml(text)
        self.assertEqual(servers, {"hermes": {"type": "http", "url": "https://mcp.example.com/mcp"}})


class ParseCordisYamlTest(unittest.TestCase):
    def test_tolerates_js_tag(self):
        text = "- id: mcp-hermes\n  config:\n    headers:\n      Authorization: !!js env.MCP_TOKEN\n"
        # 不应抛异常（CordisLoader 将 !!js 注册为不透明标量）
        data = config_codec.parse_cordis_yaml(text)
        self.assertIsInstance(data, list)


class CrossModuleConsistencyTest(unittest.TestCase):
    """同一份配置文本经 mcp_checker 与 legacy_checker 两条链路解析结果一致。"""

    def _loaders(self):
        import mcp_checker
        import legacy_checker
        return mcp_checker, legacy_checker

    def test_toml_parsers_agree(self):
        mcp_checker, legacy_checker = self._loaders()
        text = '[mcp_servers.hermes]\nurl = "https://mcp.example.com/mcp"\n'
        a = mcp_checker._load_simple_toml_servers(text)
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(text)
            path = fh.name
        try:
            b = legacy_checker._load_toml_mcp_servers(path)
        finally:
            os.unlink(path)
        self.assertEqual(a, b)

    def test_reasonix_toml_parsers_agree(self):
        mcp_checker, legacy_checker = self._loaders()
        text = (
            "[[plugins]]\n"
            'name = "hermes"\n'
            'type = "http"\n'
            'url = "https://mcp.example.com/mcp"\n'
        )
        a = mcp_checker._load_reasonix_toml(text)
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(text)
            path = fh.name
        try:
            b = legacy_checker._load_reasonix_plugins(path)
        finally:
            os.unlink(path)
        self.assertEqual(a, b)

    def test_reasonix_json_parsers_agree(self):
        mcp_checker, legacy_checker = self._loaders()
        text = '{"mcp": ["hermes=python3 bridge.py"]}'
        a = mcp_checker._load_reasonix(text)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write(text)
            path = fh.name
        try:
            b = legacy_checker._load_reasonix_json_mcp(path)
        finally:
            os.unlink(path)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()