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


class NestedSubTableTest(unittest.TestCase):
    """Codex 的 ``[mcp_servers.<name>.tools.<tool>]`` 子表不得被当作独立 server。

    历史缺陷：只有 ``.env`` 被特判，其余子表（``tools.list_clusters`` 等）都被
    解析成新 server，凭空多出「未纳管」条目；界面随后提供「清理未纳管」，会把这
    些子表里的 ``approval_mode`` 审批设置一并删除（真实数据损失）。
    """

    def test_tools_subtable_is_not_a_server(self):
        text = (
            "[mcp_servers.K8s-uat]\n"
            'url = "https://k8s.example.com/mcp"\n'
            "[mcp_servers.K8s-uat.tools.list_clusters]\n"
            'approval_mode = "approve"\n'
            "[mcp_servers.K8s-uat.tools.get_pod_logs]\n"
            'approval_mode = "approve"\n'
        )
        servers = config_codec.parse_toml_mcp_servers(text)
        self.assertEqual(list(servers), ["K8s-uat"])
        self.assertEqual(servers["K8s-uat"]["url"], "https://k8s.example.com/mcp")

    def test_subtable_fields_do_not_pollute_server(self):
        text = (
            "[mcp_servers.hermes]\n"
            'url = "https://mcp.example.com/mcp"\n'
            "[mcp_servers.hermes.tools.ai_memory_query]\n"
            'approval_mode = "approve"\n'
        )
        servers = config_codec.parse_toml_mcp_servers(text)
        self.assertEqual(servers["hermes"], {"url": "https://mcp.example.com/mcp"})
        self.assertNotIn("approval_mode", servers["hermes"])

    def test_env_still_collapses_while_tools_does_not(self):
        text = (
            "[mcp_servers.node_repl]\n"
            'command = "/usr/local/bin/node_repl"\n'
            "[mcp_servers.node_repl.env]\n"
            'CODEX_HOME = "/tmp/codex"\n'
            "[mcp_servers.node_repl.tools.run]\n"
            'approval_mode = "approve"\n'
        )
        servers = config_codec.parse_toml_mcp_servers(text)
        self.assertEqual(list(servers), ["node_repl"])
        self.assertEqual(servers["node_repl"]["env"], {"CODEX_HOME": "/tmp/codex"})
        self.assertNotIn("tools", servers["node_repl"])

    def test_deeply_nested_subtable_is_not_a_server(self):
        text = (
            "[mcp_servers.a]\n"
            'url = "https://a.example.com/mcp"\n'
            "[mcp_servers.a.tools.b.c.d]\n"
            'x = "1"\n'
        )
        servers = config_codec.parse_toml_mcp_servers(text)
        self.assertEqual(list(servers), ["a"])

    def test_subtable_without_parent_declares_no_server(self):
        """只有子表、没有 ``[mcp_servers.<name>]`` 时不应凭空造出 server。"""
        text = '[mcp_servers.ghost.tools.x]\napproval_mode = "approve"\n'
        servers = config_codec.parse_toml_mcp_servers(text)
        self.assertEqual(servers, {})

    def test_quoted_dotted_server_name_is_one_server(self):
        text = '[mcp_servers."my.server"]\nurl = "https://s.example.com/mcp"\n'
        servers = config_codec.parse_toml_mcp_servers(text)
        self.assertEqual(list(servers), ["my.server"])

    def test_real_codex_shape_yields_only_real_servers(self):
        """回归：真实 Codex 配置形状（含 node_repl.env 与 tools.* 子表）。"""
        text = (
            "[mcp_servers.node_repl]\n"
            "args = []\n"
            'command = "/Applications/ChatGPT.app/bin/node_repl"\n'
            "[mcp_servers.node_repl.env]\n"
            'CODEX_HOME = "/Users/x/.codex"\n'
            "[mcp_servers.K8s-uat]\n"
            'url = "https://k8s.example.com/mcp"\n'
            "[mcp_servers.K8s-uat.tools.list_clusters]\n"
            'approval_mode = "approve"\n'
            "[mcp_servers.K8s-uat.tools.get_k8s]\n"
            'approval_mode = "approve"\n'
            "[mcp_servers.hermes]\n"
            'url = "https://hermes.example.com/mcp"\n'
            "[mcp_servers.hermes.tools.ai_memory_query]\n"
            'approval_mode = "approve"\n'
        )
        servers = config_codec.parse_toml_mcp_servers(text)
        self.assertEqual(list(servers), ["node_repl", "K8s-uat", "hermes"])
        self.assertEqual(servers["K8s-uat"], {"url": "https://k8s.example.com/mcp"})
        self.assertEqual(servers["hermes"], {"url": "https://hermes.example.com/mcp"})


class TomlSectionHygieneTest(unittest.TestCase):
    """段头容忍与跨段字段泄漏。"""

    def test_header_with_trailing_comment_is_recognised(self):
        text = '[mcp_servers.hermes]  # primary\nurl = "https://mcp.example.com/mcp"\n'
        servers = config_codec.parse_toml_mcp_servers(text)
        self.assertEqual(servers, {"hermes": {"url": "https://mcp.example.com/mcp"}})

    def test_fields_do_not_leak_across_foreign_sections(self):
        """非 mcp_servers 段之后的字段不得混入上一个 server。"""
        text = (
            "[mcp_servers.hermes]\n"
            'url = "https://mcp.example.com/mcp"\n'
            "[projects.\"/some/path\"]\n"
            'trust_level = "trusted"\n'
        )
        servers = config_codec.parse_toml_mcp_servers(text)
        self.assertEqual(servers, {"hermes": {"url": "https://mcp.example.com/mcp"}})

    def test_container_header_resets_context(self):
        text = (
            "[mcp_servers.hermes]\n"
            'url = "https://mcp.example.com/mcp"\n'
            "[mcp_servers]\n"
            'stray = "value"\n'
        )
        servers = config_codec.parse_toml_mcp_servers(text)
        self.assertEqual(servers, {"hermes": {"url": "https://mcp.example.com/mcp"}})


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

    def test_toml_parsers_agree_on_nested_subtables(self):
        """嵌套子表场景下两条链路也必须一致（P0 回归护栏）。"""
        mcp_checker, legacy_checker = self._loaders()
        text = (
            "[mcp_servers.K8s-uat]\n"
            'url = "https://k8s.example.com/mcp"\n'
            "[mcp_servers.K8s-uat.tools.list_clusters]\n"
            'approval_mode = "approve"\n'
        )
        a = mcp_checker._load_simple_toml_servers(text)
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(text)
            path = fh.name
        try:
            b = legacy_checker._load_toml_mcp_servers(path)
        finally:
            os.unlink(path)
        self.assertEqual(a, b)
        self.assertEqual(list(a), ["K8s-uat"])

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
