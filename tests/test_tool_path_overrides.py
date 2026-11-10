"""路径覆盖层测试（v0.39.0）。

背景：用户问「默认获取的路径是这个，但实际上可能是另外一个，我该怎么修改？
这个功能是否缺失了？」——此前确实缺失：内置注册表的路径没有任何修正入口。
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

import tool_path_overrides as tpo  # noqa: E402


class _TmpOverrides(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "local_overrides.yaml")
        self.patch = mock.patch.object(tpo, "_overrides_file", lambda: self.path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()


class SetResetTest(_TmpOverrides):
    def test_set_then_apply_then_reset(self):
        tools = [{"name": "TRAE", "install": {"config_paths": ["~/default.json"]}}]
        self.assertEqual(tpo.apply_overrides(tools)[0]["install"]["config_paths"], ["~/default.json"])

        res = tpo.set_tool_path("TRAE", "config_paths", "~/custom.json")
        self.assertTrue(res["ok"])
        self.assertEqual(tpo.apply_overrides(tools)[0]["install"]["config_paths"], ["~/custom.json"])
        # 原列表不被污染（覆盖必须深拷贝）
        self.assertEqual(tools[0]["install"]["config_paths"], ["~/default.json"])

        res = tpo.reset_tool_path("TRAE", "config_paths")
        self.assertTrue(res["ok"])
        self.assertEqual(tpo.apply_overrides(tools)[0]["install"]["config_paths"], ["~/default.json"])

    def test_multiline_value_becomes_list(self):
        tpo.set_tool_path("X", "rules_paths", "~/a.md\n~/b.md")
        self.assertEqual(tpo.load_tool_paths()["X"]["rules_paths"], ["~/a.md", "~/b.md"])

    def test_mcp_config_path_is_scalar(self):
        tpo.set_tool_path("X", "mcp_config_path", "~/mcp.json")
        tools = [{"name": "X", "config_path": ""}]
        self.assertEqual(tpo.apply_overrides(tools)[0]["config_path"], "~/mcp.json")

    def test_unknown_field_rejected(self):
        res = tpo.set_tool_path("X", "name", "hacked")
        self.assertFalse(res["ok"])
        self.assertIn("不支持的字段", res["reason"])

    def test_reset_whole_tool(self):
        tpo.set_tool_path("X", "config_paths", "~/a.json")
        tpo.set_tool_path("X", "skills_path", "~/skills")
        self.assertTrue(tpo.reset_tool_path("X")["ok"])
        self.assertEqual(tpo.load_tool_paths(), {})

    def test_reset_missing_tool_is_not_ok(self):
        self.assertFalse(tpo.reset_tool_path("Nope")["ok"])

    def test_corrupt_yaml_does_not_raise(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("tool_paths: [unclosed\n")
        self.assertEqual(tpo.load_tool_paths(), {})

    def test_overrides_preserve_other_keys(self):
        import yaml

        with open(self.path, "w", encoding="utf-8") as handle:
            yaml.safe_dump({"active_profile": "hermes-home"}, handle)
        tpo.set_tool_path("X", "config_paths", "~/a.json")
        with open(self.path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        self.assertEqual(data["active_profile"], "hermes-home")
        self.assertIn("tool_paths", data)


class RegistryWiringTest(unittest.TestCase):
    def test_register_mainstream_tools_applies_overrides(self):
        """register_mainstream_tools 必须走覆盖层（否则改了也不生效）。"""
        import inspect

        import mainstream_registry

        src = inspect.getsource(mainstream_registry.register_mainstream_tools)
        self.assertIn("apply_overrides", src)
        self.assertIn("deepcopy", src)

    def test_gui_has_edit_entry(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "gui", "dashboard.html"), "r", encoding="utf-8") as handle:
            html = handle.read()
        # 精确匹配函数定义：子串断言在改名成 openToolPathEditorX 时仍会通过
        self.assertIn("function openToolPathEditor(name) {", html,
                      "详情弹框应有「编辑路径」入口")
        self.assertIn("ad-edit-paths", html)
        self.assertIn("--set-tool-path", html)
        self.assertIn("--reset-tool-path", html)

    def test_rust_whitelist(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "src-tauri", "src", "lib.rs"), "r", encoding="utf-8") as handle:
            rs = handle.read()
        for flag in ("--set-tool-path", "--reset-tool-path", "--list-tool-paths"):
            self.assertIn(flag, rs, f"Rust 白名单缺 {flag}")

    def test_cli_accepts_flags(self):
        import subprocess

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        res = subprocess.run([sys.executable, "scan.py", "--list-tool-paths"],
                             capture_output=True, text=True, cwd=root)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("路径覆盖", res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
