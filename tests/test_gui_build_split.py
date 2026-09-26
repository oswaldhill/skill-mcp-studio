"""S10 构建期拆分：源文件保持单文件，发布产物拆分（既有测试零改动）。

`scripts/build_gui.py` 把 `gui/dashboard.html` 的内联 `<script>` 切成
`gui/dist/index.html` + `gui/dist/app.js`。本文件守两条不变量：

1. **产物里没有内联 `<script>`** —— 这是「关掉 CSP `'unsafe-inline'`」的前置条件之一
   （外置脚本后 `script-src` 才可能不再需要 `'unsafe-inline'`；样式仍受 77 处内联
   `style=` 属性约束，见清单的 S2 专节）。顺带这条断言本身也防止「有人图省事
   又把脚本塞回 index.html」。
2. **拆分无损** —— 把 `<script src="app.js" defer></script>` 换回
   `<script>脚本体</script>` 必须**逐字节还原**源文件。拆分不能丢内容、不能改空白，
   否则发布产物与测试所测的源文件就不是同一个东西了。

另外测 `--check`：CI 用它判断 `gui/dist/` 是否与源文件同步（防止有人改了源文件却忘了重新构建）。
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests._gui_source import page_source  # noqa: E402

BUILD = ROOT / "scripts" / "build_gui.py"
DIST = ROOT / "gui" / "dist"
INDEX = DIST / "index.html"
APP_JS = DIST / "app.js"
SCRIPT_TAG = '<script src="app.js" defer></script>'


class BuildSplitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(
            [sys.executable, str(BUILD)], cwd=ROOT, capture_output=True, text=True
        )
        if r.returncode != 0:
            raise AssertionError(f"构建失败：\n{r.stdout}\n{r.stderr}")

    def test_dist_files_exist(self):
        self.assertTrue(INDEX.is_file(), "缺少 gui/dist/index.html")
        self.assertTrue(APP_JS.is_file(), "缺少 gui/dist/app.js")

    def test_dist_index_has_no_inline_script(self):
        index = INDEX.read_text(encoding="utf-8")
        inline = re.findall(r"<script(?![^>]*\bsrc=)", index)
        self.assertEqual(inline, [], f"发布产物里仍有内联 <script>：{inline}")

    def test_dist_index_references_external_script(self):
        index = INDEX.read_text(encoding="utf-8")
        self.assertIn(SCRIPT_TAG, index, "发布产物没有引用外置脚本")

    def test_dist_app_js_carries_the_page_script(self):
        app = APP_JS.read_text(encoding="utf-8")
        # 抽一个真实存在的顶层函数，确认搬过去的是页面脚本本体而不是空文件
        self.assertIn("function renderMcpClients", app)

    def test_split_is_lossless(self):
        """把产物拼回单文件形态，必须与源文件逐字节一致。"""
        index = INDEX.read_text(encoding="utf-8")
        app = APP_JS.read_text(encoding="utf-8")
        rebuilt = index.replace(SCRIPT_TAG, "<script>" + app + "</script>", 1)
        self.assertEqual(rebuilt, page_source(), "拆分不是无损的（内容/空白被改动）")

    def test_check_mode_passes_when_in_sync(self):
        r = subprocess.run(
            [sys.executable, str(BUILD), "--check"], cwd=ROOT, capture_output=True, text=True
        )
        self.assertEqual(r.returncode, 0, f"--check 应通过：\n{r.stdout}\n{r.stderr}")

    def test_check_mode_detects_drift(self):
        """临时改动产物后 `--check` 必须报不同步，然后恢复。"""
        original = APP_JS.read_text(encoding="utf-8")
        try:
            APP_JS.write_text(original + "\n// drift\n", encoding="utf-8")
            r = subprocess.run(
                [sys.executable, str(BUILD), "--check"], cwd=ROOT, capture_output=True, text=True
            )
            self.assertNotEqual(r.returncode, 0, "--check 未发现产物漂移")
        finally:
            APP_JS.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main(verbosity=2)