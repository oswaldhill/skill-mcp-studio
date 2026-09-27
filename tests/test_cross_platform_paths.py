"""T-10: 跨平台路径展开 / 缩写回归测试。

覆盖 ``tool_registry.expand_path``（``%VAR%`` / ``~`` / unset 变量语义）与
``_abbreviate_home``（跨设备展示地址缩写）。Windows junction 与 chmod 语义
属平台专属行为，由平台 CI runner 负责，本文件锁定可跨平台断言的纯粹部分。
"""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from tool_registry import _abbreviate_home, expand_path  # noqa: E402


class ExpandPathTest(unittest.TestCase):
    def test_expands_windows_var_on_non_windows_host(self):
        # 非 Windows 主机上 os.path.expandvars 不解 %NAME%，但展开器应回退到
        # 字面 %…% 展开，使 Windows 风格注册表路径也可解析。
        env = {"APPDATA": r"C:\Users\test\AppData\Roaming"}
        got = expand_path(r"%APPDATA%\Cursor\User\settings.json", environ=env)
        self.assertEqual(got, r"C:\Users\test\AppData\Roaming\Cursor\User\settings.json")

    def test_unset_var_keeps_literal_token(self):
        # 未设置变量保留字面 %NAME%，避免崩溃（对齐 os.path.expandvars 语义）。
        got = expand_path(r"%NO_SUCH_VAR%\x", environ={})
        self.assertEqual(got, r"%NO_SUCH_VAR%\x")

    def test_expands_tilde(self):
        home = os.path.expanduser("~")
        self.assertEqual(expand_path("~/skills"), os.path.join(home, "skills"))

    def test_empty_path_is_identity(self):
        self.assertEqual(expand_path(""), "")

    def test_mixed_windows_var_and_tilde(self):
        # %USERPROFILE% 展开为 /home/test；后续 path 里的 ~（非行首）按 expanduser
        # 语义保持原样，不做二次展开。
        env = {"USERPROFILE": "/home/test"}
        got = expand_path("%USERPROFILE%/skills", environ=env)
        self.assertEqual(got, "/home/test/skills")


class AbbreviateHomeTest(unittest.TestCase):
    def test_home_prefix_abbreviates_to_tilde(self):
        home = "/Users/alice"
        self.assertEqual(_abbreviate_home("/Users/alice/skills", home), "~/skills")

    def test_non_home_absolute_unchanged(self):
        self.assertEqual(_abbreviate_home("/Applications/X", "/Users/alice"), "/Applications/X")

    def test_no_false_prefix_abbreviation(self):
        # /Users/alice 不能误缩 /Users/alicebob 的前缀。
        self.assertEqual(_abbreviate_home("/Users/alicebob/x", "/Users/alice"), "/Users/alicebob/x")


if __name__ == "__main__":
    unittest.main()
