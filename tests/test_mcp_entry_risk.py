import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from mcp_entry_risk import is_high_risk_entry  # noqa: E402


class HighRiskEntryTest(unittest.TestCase):
    """R1/R2/R3 各一例 + 真实反例（本机 2026-09-20 实测条目）。"""

    def setUp(self):
        # 注册表真实形状（config.yaml:106-118）
        self.codex = {
            "name": "Codex",
            "aliases": ["codex"],
            "app_bundles": ["/Applications/Codex.app", "/Applications/ChatGPT.app"],
        }

    def test_r1_absolute_command_inside_app_bundle(self):
        entry = {
            "key": "node_repl",
            "command": "/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node_repl",
            "args": [],
        }
        high, reason = is_high_risk_entry(entry, self.codex)
        self.assertTrue(high)
        self.assertIn("/Applications/ChatGPT.app", reason)

    def test_r1_absolute_path_in_args_inside_app_bundle(self):
        entry = {
            "key": "helper",
            "command": "node",
            "args": ["/Applications/ChatGPT.app/Contents/Resources/tool.js"],
        }
        high, reason = is_high_risk_entry(entry, self.codex)
        self.assertTrue(high)
        self.assertIn("/Applications/ChatGPT.app", reason)

    def test_r2_relative_path_into_app_contents(self):
        entry = {
            "key": "computer-use",
            "command": "./Codex Computer Use.app/Contents/SharedSupport/SkyComputerUseClient",
            "args": [],
        }
        high, reason = is_high_risk_entry(entry, self.codex)
        self.assertTrue(high)
        self.assertIn("应用包", reason)

    def test_r3_key_equals_client_name(self):
        high, reason = is_high_risk_entry({"key": "Codex", "command": "", "args": []}, self.codex)
        self.assertTrue(high)
        self.assertIn("同名", reason)

    def test_r3_key_equals_client_alias(self):
        high, _ = is_high_risk_entry({"key": "codex", "command": "", "args": []}, self.codex)
        self.assertTrue(high)

    # ---- 原生接入客户端：attached 条目豁免 R3（2026-11-09 用户反馈） ----
    # WorkBuddy 5.9.3 的约定是「连接键使用 WorkBuddy，保留其原生 Agent 名称」
    # （docs/NATIVE-MCP-IDENTITY.md）。这类条目 key 与客户端同名，但它是本工具
    # 写入并挂在端点库上的，不是「客户端自带」——不豁免会被 R3 误判，进而在
    # MCP 页最后一列与表头端点列重复显示，看起来像「多了一个 WorkBuddy 已挂载」。

    def test_r3_exempt_for_attached_entry(self):
        workbuddy = {"name": "WorkBuddy", "aliases": ["workbuddy"]}
        entry = {
            "key": "WorkBuddy",
            "command": "",
            "args": [],
            "url": "https://hermes-mcp.pd-h.top/mcp",
        }
        high, reason = is_high_risk_entry(entry, workbuddy, is_attached=True)
        self.assertFalse(high, "已挂载到端点库的同名条目不应判为客户端自带")
        self.assertEqual(reason, "")

    def test_attached_does_not_exempt_r1_app_bundle(self):
        """豁免只针对 R3：命令落在客户端 app bundle 内仍算自带能力。"""
        workbuddy = {
            "name": "WorkBuddy",
            "aliases": ["workbuddy"],
            "app_bundles": ["/Applications/WorkBuddy.app"],
        }
        entry = {
            "key": "WorkBuddy",
            "command": "/Applications/WorkBuddy.app/Contents/MacOS/helper",
            "args": [],
        }
        high, reason = is_high_risk_entry(entry, workbuddy, is_attached=True)
        self.assertTrue(high)
        self.assertIn("/Applications/WorkBuddy.app", reason)

    def test_r3_still_applies_when_not_attached(self):
        """未挂载的同名条目（真正的客户端自带）保持原有判定。"""
        workbuddy = {"name": "WorkBuddy", "aliases": ["workbuddy"]}
        high, reason = is_high_risk_entry(
            {"key": "WorkBuddy", "command": "", "args": []}, workbuddy)
        self.assertTrue(high)
        self.assertIn("同名", reason)

    def test_user_entry_is_not_high_risk(self):
        dsh = {
            "name": "DeepSeek Harness",
            "app_bundles": ["/Applications/DeepSeek Harness.app"],
        }
        entry = {
            "key": "image-vision",
            "command": "/usr/local/bin/python3",
            "args": ["/opt/vision/server.py"],
        }
        high, reason = is_high_risk_entry(entry, dsh)
        self.assertFalse(high)
        self.assertEqual(reason, "")

    def test_bare_command_name_is_not_high_risk(self):
        wb = {"name": "WorkBuddy", "app_bundles": ["/Applications/WorkBuddy.app"]}
        high, _ = is_high_risk_entry({"key": "context7", "command": "npx", "args": []}, wb)
        self.assertFalse(high)

    def test_near_miss_path_prefix_does_not_match(self):
        """前缀必须是目录边界，'/Applications/ChatGPT.app-evil' 不算。"""
        entry = {
            "key": "sneaky",
            "command": "/Applications/ChatGPT.app-evil/bin/x",
            "args": [],
        }
        high, _ = is_high_risk_entry(entry, self.codex)
        self.assertFalse(high)


class RiskCallSiteTest(unittest.TestCase):
    """调用处必须把 attached 状态传下去。

    只给函数加参数、不改调用点，等于没修：判定仍然按「同名即高危」执行，
    WorkBuddy 条目会继续在 MCP 页最后一列重复出现。
    """

    def test_call_sites_pass_is_attached(self):
        import inspect

        import management_snapshot
        import mcp_entry_removal

        for module in (management_snapshot, mcp_entry_removal):
            src = inspect.getsource(module)
            self.assertIn(
                "is_attached=", src,
                f"{module.__name__} 未把 attached 状态传给 is_high_risk_entry")


if __name__ == "__main__":
    unittest.main()
