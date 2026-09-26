"""整理建议的执行入口（FEAT-12）：前端契约。"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "gui" / "dashboard.html"


def _src() -> str:
    return HTML.read_text(encoding="utf-8")


def _fn(name: str) -> str:
    """取出一个函数体（面板 JS 缩进两空格，函数以 `\n  }` 收尾）。"""
    s = _src()
    i = s.index("function " + name + "(")
    j = s.index("\n  }", i)
    return s[i:j]


class MergeUiTest(unittest.TestCase):
    """用户要求"不能只给建议"，界面必须真的能执行。"""

    def test_html_exists(self):
        self.assertTrue(HTML.exists(), "缺少 gui/dashboard.html")

    def test_each_card_has_merge_button(self):
        body = _fn("renderAdvice")
        self.assertIn("merge-group", body, "卡片里没有逐组执行入口")
        self.assertIn('dataset.action = "merge-group"', body,
                      "按钮必须设 dataset.action，否则事件委托收不到")
        self.assertIn("dataset.keep", body, "按钮要带上保留方")
        self.assertIn("dataset.fold", body, "按钮要带上要归并的清单")

    def test_merge_all_entry_exists(self):
        body = _fn("renderAdvice")
        self.assertIn("merge-all", body, "缺少「全部合并」入口")

    def test_delegation_handles_both_actions(self):
        s = _src()
        for act in ('a === "merge-group"', 'a === "merge-all"'):
            self.assertIn(act, s, f"事件委托缺少分支 {act}")

    def test_uses_merge_skills_cli(self):
        body = _fn("runMergeGroup") + _fn("runMergeAll")
        self.assertIn('"--merge-skills"', body, "必须走后端合并出口")
        self.assertIn("--merge-keep", body, "缺少 --merge-keep")
        self.assertIn("--merge-fold", body, "缺少 --merge-fold")
        # 前端不得自己拼删除/移动命令绕过后端判定
        for bad in ("--delete-skill", "rm -rf", "--remove-skill"):
            self.assertNotIn(bad, body, f"前端不应自己调用 {bad}")

    def test_confirmation_before_write(self):
        body = _fn("runMergeGroup")
        self.assertIn("confirmModal", body, "写操作前必须二次确认")
        self.assertIn("_trash", body, "确认文案要说清去处（_trash 可恢复）")
        body2 = _fn("runMergeAll")
        self.assertIn("confirmModal", body2, "全部合并前必须二次确认")

    def test_dry_run_available_for_guarded_mode(self):
        """浏览器预览模式（无 tauriInvoke）不得静默执行写操作。"""
        for name in ("runMergeGroup", "runMergeAll"):
            body = _fn(name)
            self.assertIn("tauriInvoke", body,
                          f"{name} 未拦截浏览器预览模式，会静默失败或误执行")

    def test_reruns_advice_and_verifies_after_write(self):
        """用户要求：执行后自动重跑并核对。"""
        s = _src()
        self.assertIn("refreshAdviceAfterWrite", s, "缺少写后重跑判据")
        self.assertIn("verifyMerge", s, "缺少执行后核对")
        # 重跑必须复用同一个统计出口（--skill-insight），且要走带进度的标准路径：
        # 合并入口与统计入口共用一次扫描，另起一条通道就会重复通读会话日志。
        self.assertIn("runSkillInsight", _fn("refreshAdviceAfterWrite"),
                      "重跑应复用 runSkillInsight（同一出口 + 标准进度），"
                      "而不是自己调 runCli 静默等待")
        self.assertNotIn('"--merge-advice"', _fn("refreshAdviceAfterWrite"),
                         "重跑不该另调 --merge-advice")
        body = _fn("verifyMerge")
        self.assertIn("actionable", body, "核对必须看新的 actionable")
        self.assertIn("showToast", body, "核对结果要反馈给用户")

    def test_no_stale_readonly_claim(self):
        """旧的"只读/不会替你执行"文案必须消失，否则界面在说谎。"""
        s = _src()
        for stale in ("本面板不会替你执行", "本面板全程只读", "仅标注供人工复核"):
            self.assertNotIn(stale, s, f"仍留有失效文案：{stale}")

    def test_judgement_stays_in_backend(self):
        """判据与执行都归后端：前端不得自己判断"这组能合"。"""
        body = _fn("runMergeGroup")
        for bad in ("jaccard", "相似度", "rule === ", "compareDesc"):
            self.assertNotIn(bad, body, f"前端不应自行判定：{bad}")


if __name__ == "__main__":
    unittest.main()
