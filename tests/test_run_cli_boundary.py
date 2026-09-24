"""CLI 出口与 run_cli 安全边界的一致性契约。

`run_cli` 是 webview 调 CLI 的唯一通道，带白名单（安全边界）。前端能用到的
出口必须同时满足：
  1. 在 Rust `ALLOWED` 白名单里（否则被拦，用户看到"不在白名单内"）
  2. 若是扫描类命令，还要挂上进度文件（否则进度条永远不动）

这两处都在 Rust 里，与 Python 侧新增出口的时机不同步，很容易漏。本测试把
"前端实际调用的 flag" 作为唯一事实来源，反向校验两侧都已登记。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB_RS = ROOT / "src-tauri" / "src" / "lib.rs"
HTML = ROOT / "gui" / "dashboard.html"


def _rs() -> str:
    return LIB_RS.read_text(encoding="utf-8")


def _allowed_block() -> str:
    src = _rs()
    i = src.index("const ALLOWED: &[&str] = &[")
    j = src.index("];", i)
    return src[i:j]


def _frontend_flags() -> set:
    """前端 runCli 实际传入的第一位 flag。"""
    return set(re.findall(r'runCli\(\s*\[\s*"(--[a-z-]+)"',
                          HTML.read_text(encoding="utf-8")))


class RunCliBoundaryTest(unittest.TestCase):
    """前端能调的出口必须在安全边界里登记，且扫描类要挂进度文件。"""

    def test_lib_and_html_exist(self):
        self.assertTrue(LIB_RS.exists(), "缺少 src-tauri/src/lib.rs")
        self.assertTrue(HTML.exists(), "缺少 gui/dashboard.html")

    def test_frontend_flags_are_allowlisted(self):
        """前端调的每个出口都必须在 ALLOWED 里，否则用户会撞上安全边界。"""
        allowed = _allowed_block()
        missing = sorted(f for f in _frontend_flags() if f'"{f}"' not in allowed)
        self.assertFalse(
            missing,
            f"这些前端出口未登记进 run_cli 白名单，调用会被拦截: {missing}",
        )

    def test_scan_commands_inject_progress_file(self):
        """扫描类出口必须挂进度文件，否则长任务进度条不动。"""
        m = re.search(r"let is_scan = (.+?);\n", _rs(), re.S)
        self.assertIsNotNone(m, "找不到 is_scan 判定")
        block = m.group(0)
        for flag in ("--skill-usage", "--merge-advice", "--skill-insight"):
            self.assertIn(flag, block,
                          f"{flag} 是扫描类命令，未挂进度文件会导致进度条不动")

    def test_insight_is_read_only_like_its_parts(self):
        """组合出口的能力不得超出它拼起来的两条只读出口。"""
        allowed = _allowed_block()
        for flag in ("--skill-usage", "--merge-advice", "--skill-insight"):
            self.assertIn(f'"{flag}"', allowed, f"{flag} 应在白名单内")
        scan = (ROOT / "scan.py").read_text(encoding="utf-8")
        body = scan[scan.index("def _run_skill_insight"):
                    scan.index("def summarize_insight_text")]
        for fn in ("scan_usage", "scan_advice"):
            self.assertIn(fn, body, f"组合出口应调用 {fn}")
        for writer in ("unlink", "rmtree", "shutil.move", "write_text"):
            self.assertNotIn(writer, body, f"组合出口是只读的，不应出现 {writer}")


if __name__ == "__main__":
    unittest.main()
