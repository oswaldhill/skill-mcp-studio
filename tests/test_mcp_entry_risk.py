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


if __name__ == "__main__":
    unittest.main()
