"""验收：JSON/JSONC 客户端的 MCP 条目必须带正确的 ``type``（OpenCode 判别联合）。

为什么需要这组用例：OpenCode 的 ``mcp`` 段是**判别联合** —— 官方 schema
(``https://opencode.ai/config.json``) 里 ``McpRemoteConfig`` 的 ``required`` 是
``["type", "url"]``、``McpLocalConfig`` 是 ``["type", "command"]``。缺 ``type`` 时
OpenCode **不是忽略该条目，而是把整份配置判为无效**：

    $ opencode debug config
    Error: Configuration is invalid at ~/.config/opencode/opencode.json
    ↳ Expected { readonly "type": "local", ... } | { readonly "type": "remote", ... }
      got {"url":"https://..."} mcp.hermes-unified
    ↳ Missing key mcp.hermes-unified.enabled

后果是**所有** MCP 端点一起失效，而面板上仍显示「已接入」—— 因为判定只看 URL
字符串是否匹配。这正是「以设置中的 MCP 为准」这条口径下最危险的一类假阳性：
字符串对上了，配置其实加载不了。

修法是按客户端声明连接类型（``config.yaml`` 的 ``mcp_entry_type``），而不是在渲染层
统一硬编码 —— 因为 ``mcpServers`` 型客户端（Claude Code / Cursor / WorkBuddy）的
条目**只需 url**，多写 ``type`` 是多余字段（用户手写的 WorkBuddy 条目就是 ``{url}``）。

反向验证：把 ``_render_json`` 里的 ``entry_type`` 处理去掉（回到
``entry = {"url": url}``），``OpenCodeEntryTypeTest`` 会立即失败。
"""

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import mcp_fixer_render as render  # noqa: E402


#: OpenCode 的工具定义（取自 config.yaml 的 mcp_tools OpenCode 条目）
OPENCODE_TOOL = {
    "name": "OpenCode",
    "format": "jsonc",
    "mcp_key_path": ["mcp"],
    "mcp_entry_type": "remote",
    "unified_name": "hermes-unified",
}

#: mcpServers 型客户端（Claude Code / Cursor / WorkBuddy 共用的形状）
MCPSERVERS_TOOL = {
    "name": "WorkBuddy",
    "format": "json",
    "mcp_key_path": ["mcpServers"],
}

#: 官方 McpRemoteConfig 的 required
REMOTE_REQUIRED = ["type", "url"]
#: 官方 McpLocalConfig 的 required
LOCAL_REQUIRED = ["type", "command"]


def _render(tool, start, name, url, token=""):
    return json.loads(render._render(tool, start, name, url, token))


class OpenCodeEntryTypeTest(unittest.TestCase):
    """OpenCode：条目必须含 type，否则整份配置无效。"""

    EMPTY = '{"$schema": "https://opencode.ai/config.json", "mcp": {}}'

    def test_remote_entry_carries_type(self):
        d = _render(OPENCODE_TOOL, self.EMPTY, "hermes-unified",
                    "https://hermes-mcp.pd-h.top/mcp")
        entry = d["mcp"]["hermes-unified"]
        self.assertEqual(entry.get("type"), "remote")
        for key in REMOTE_REQUIRED:
            with self.subTest(key=key):
                self.assertIn(key, entry)

    def test_remote_entry_with_token_keeps_type_and_key_order(self):
        d = _render(OPENCODE_TOOL, self.EMPTY, "K8s-uat",
                    "https://k8s.carobo.cn/mcp", "tok")
        entry = d["mcp"]["K8s-uat"]
        # type 必须排在 url 之前（与官方示例一致，也便于人读）
        self.assertEqual(list(entry.keys()), ["type", "url", "headers"])
        self.assertEqual(entry["type"], "remote")
        self.assertEqual(entry["headers"]["Authorization"], "Bearer tok")

    def test_written_config_stays_loadable_shape(self):
        """连续写两个端点后，每个条目的 required 字段都在。"""
        text = self.EMPTY
        text = render._render(OPENCODE_TOOL, text, "hermes-unified",
                              "https://hermes-mcp.pd-h.top/mcp")
        text = render._render(OPENCODE_TOOL, text, "K8s-uat",
                              "https://k8s.carobo.cn/mcp", "tok")
        d = json.loads(text)
        self.assertEqual(set(d["mcp"]), {"hermes-unified", "K8s-uat"})
        for name, entry in d["mcp"].items():
            with self.subTest(name=name):
                self.assertEqual(entry.get("type"), "remote")
                self.assertIn("url", entry)

    def test_start_from_empty_string(self):
        """OpenCode 配置不存在时从空串起步，也要产出带 type 的合法 JSON。"""
        d = json.loads(render._render(OPENCODE_TOOL, "{}", "hermes-unified",
                                      "https://hermes-mcp.pd-h.top/mcp"))
        self.assertEqual(d["mcp"]["hermes-unified"]["type"], "remote")


class NonJudgedUnionClientTest(unittest.TestCase):
    """mcpServers 型客户端：不得多写 type（保持既有字节级行为）。"""

    EMPTY = '{"mcpServers": {}}'

    def test_entry_has_no_type(self):
        d = _render(MCPSERVERS_TOOL, self.EMPTY, "hermes",
                    "https://hermes-mcp.pd-h.top/mcp")
        entry = d["mcpServers"]["hermes"]
        self.assertNotIn("type", entry)
        self.assertEqual(entry, {"url": "https://hermes-mcp.pd-h.top/mcp"})

    def test_entry_with_token_has_no_type(self):
        d = _render(MCPSERVERS_TOOL, self.EMPTY, "K8s-uat",
                    "https://k8s.carobo.cn/mcp", "tok")
        entry = d["mcpServers"]["K8s-uat"]
        self.assertNotIn("type", entry)
        self.assertEqual(list(entry.keys()), ["url", "headers"])


class RealConfigTest(unittest.TestCase):
    """真实 config.yaml：OpenCode 必须声明 mcp_entry_type，其他 JSON 客户端不必。"""

    def test_opencode_declares_remote_type(self):
        import yaml

        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        tools = cfg.get("mcp_tools") or []
        oc = next((t for t in tools if t.get("name") == "OpenCode"), None)
        self.assertIsNotNone(oc, "config.yaml 应有 OpenCode 条目")
        self.assertEqual(oc.get("mcp_entry_type"), "remote")
        # 判据是判别联合：必须是 mcp 段（而非 mcpServers）
        self.assertEqual(oc.get("mcp_key_path"), ["mcp"])

    def test_mcpservers_clients_do_not_declare_type(self):
        import yaml

        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        for tool in (cfg.get("mcp_tools") or []):
            fmt = tool.get("format")
            if fmt in ("json", "jsonc") and tool.get("mcp_key_path") == ["mcpServers"]:
                with self.subTest(tool=tool.get("name")):
                    self.assertFalsy(tool.get("mcp_entry_type"))

    def assertFalsy(self, value):
        self.assertFalse(value, f"mcpServers 型客户端不应声明 mcp_entry_type，得到 {value!r}")


if __name__ == "__main__":
    unittest.main()