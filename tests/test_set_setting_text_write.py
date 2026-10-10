"""``--set-setting`` 的文本级写入回归。

背景（两个真实缺陷，均由实测暴露）：

1. **密钥污染**：``--set-setting`` 曾把内存里的 ``config`` 整体 ``yaml.safe_dump``
   回写。而 ``core/scanner.run_scan`` 会原地 ``apply_profile_sources``，把
   ``profile_sources``（仓库外的个人拓扑文件）并进该对象 —— 于是一次「开巡检」
   就把真实 ``auth_token`` 写进了主干 ``config.yaml``。个人端点与凭据的正确
   归处是仓库外覆盖文件（见 ``core/profile_loader`` 的
   "trunk config.yaml stays free of personal endpoints"）。

2. **格式与注释丢失**：``yaml.safe_dump`` 会重新序列化整份文件 —— 内联数组
   被拆成多行、**所有注释被抹掉**。实测改一个布尔值产生 383 行 diff、50 行
   注释全部丢失，等于每次改设置都毁掉配置里的文档。

修法是文本级改写：只动 ``settings`` 段的目标行，其余文本一字不动。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT))

import scan  # noqa: E402


class SetSettingInTextTest(unittest.TestCase):
    """``_set_setting_in_text`` 的行为契约。"""

    def test_replaces_existing_key_and_keeps_everything_else(self):
        src = (
            "# 顶层注释\n"
            "other: 1\n"
            "settings:\n"
            "  patrol_enabled: false\n"
            "  patrol_interval_minutes: 15\n"
        )
        out = scan._set_setting_in_text(src, "patrol_enabled", True)
        self.assertIn("patrol_enabled: true", out)
        self.assertIn("patrol_interval_minutes: 15", out)
        self.assertIn("# 顶层注释", out)
        self.assertIn("other: 1", out)

    def test_appends_missing_key_inside_existing_section(self):
        src = "settings:\n  patrol_enabled: false\n"
        out = scan._set_setting_in_text(src, "patrol_interval_minutes", 30)
        self.assertIn("patrol_interval_minutes: 30", out)
        self.assertIn("patrol_enabled: false", out)

    def test_creates_section_when_absent(self):
        src = "other: 1\n"
        out = scan._set_setting_in_text(src, "patrol_enabled", True)
        self.assertIn("settings:", out)
        self.assertIn("patrol_enabled: true", out)
        self.assertIn("other: 1", out)

    def test_does_not_bleed_into_following_top_level_section(self):
        """段边界必须止于下一个顶格键，不能误改别的段。"""
        src = "settings:\n  a: 1\ntools:\n  name: x\n  a: 1\n"
        out = scan._set_setting_in_text(src, "a", 2)
        self.assertIn("settings:\n  a: 2", out)
        # tools 段里的同名键必须原样
        self.assertIn("tools:\n  name: x\n  a: 1", out)

    def test_comment_lines_inside_section_are_preserved(self):
        src = (
            "settings:\n"
            "  # 巡检总开关\n"
            "  patrol_enabled: false\n"
        )
        out = scan._set_setting_in_text(src, "patrol_enabled", True)
        self.assertIn("  # 巡检总开关", out)
        self.assertIn("patrol_enabled: true", out)

    def test_output_ends_with_exactly_one_newline(self):
        for src in ("settings:\n  a: 1\n", "settings:\n  a: 1", "other: 1\n"):
            with self.subTest(src=src):
                out = scan._set_setting_in_text(src, "a", 1)
                self.assertTrue(out.endswith("\n"))
                self.assertFalse(out.endswith("\n\n"))


class RenderScalarTest(unittest.TestCase):
    def test_bool_renders_lowercase(self):
        """与仓库既有 config.yaml 的写法一致（true/false，非 True/False）。"""
        self.assertEqual(scan._render_scalar(True), "true")
        self.assertEqual(scan._render_scalar(False), "false")

    def test_number_renders_plain(self):
        self.assertEqual(scan._render_scalar(15), "15")


class TrunkConfigStaysCleanTest(unittest.TestCase):
    """主干 config.yaml 必须不含个人端点与明文凭据。"""

    def test_tracked_config_has_no_plaintext_credential(self):
        raw = (ROOT / "config.yaml").read_text(encoding="utf-8")
        self.assertNotIn(
            "auth_token:",
            raw,
            "主干 config.yaml 不应含明文 auth_token；个人端点走 profile_sources 覆盖文件",
        )

    def test_tracked_config_declares_profile_sources(self):
        raw = (ROOT / "config.yaml").read_text(encoding="utf-8")
        self.assertIn("profile_sources:", raw)


if __name__ == "__main__":
    unittest.main()