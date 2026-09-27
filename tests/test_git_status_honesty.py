"""R1/R2/R4 回归：脚本不得把「失败/不可知」报告成「成功/干净」。

一组同源缺陷（v0.24.0 清单 R1/R2/R4）：

* R1 ``git_status`` —— 三个 git 探测命令**都不检查 returncode**
  （``subprocess.run`` 不带 ``check=True`` 时非 0 退出不抛异常），
  且外层还有 ``except Exception: pass``。两者后果相同：
  git 报错/不可用时 ``is_clean`` 仍是 ``True``，对外报告「工作区干净」。
* R2 ``git commit`` 失败仍打印「✅ 已提交」。
* R4 ``git add`` 失败仍计入 ``added``。

这里只对 R1 做可稳定复现的断言（用一个 ``.git`` 为空目录即可让 git 报错）。
R2/R4 需要构造 hook 拒绝/忽略规则等前置条件，故仅由代码审查覆盖。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import git_sync  # noqa: E402


class GitStatusMustNotLieTest(unittest.TestCase):
    def test_broken_repo_reports_unknown_not_clean(self):
        """git 报错时 is_clean 必须是 None（不可知），而不是 True（谎报干净）。"""
        with tempfile.TemporaryDirectory() as d:
            # is_git_repo() 只看「.git 是不是目录」，所以这里能走进探测分支；
            # 而 .git 为空 → git 会以非 0 退出并打印 "Not a git repository"。
            os.makedirs(os.path.join(d, ".git"))

            result = git_sync.git_status(d)

            self.assertIsNone(
                result["is_clean"],
                "git 报错时不能声称工作区干净 —— 这是安全结论反向",
            )
            self.assertTrue(result.get("error"), "必须记录失败原因，便于定位")

    def test_real_clean_repo_still_reports_clean(self):
        """正常路径回归：真正的干净仓库仍应报 is_clean=True（没有误伤）。"""
        import subprocess

        with tempfile.TemporaryDirectory() as d:
            if subprocess.run(["git", "init", "-q"], cwd=d).returncode != 0:
                self.skipTest("本机无 git")
            result = git_sync.git_status(d)
            self.assertIs(result["is_clean"], True, "真干净仓库应报 True")
            self.assertFalse(result["has_changes"])

    def test_non_repo_returns_default_without_error(self):
        """不是仓库时保持原语义（早退），不应被误标为「检查失败」。"""
        with tempfile.TemporaryDirectory() as d:
            result = git_sync.git_status(d)
            self.assertIs(result["is_clean"], True)
            self.assertNotIn("error", result)


if __name__ == "__main__":
    unittest.main()
