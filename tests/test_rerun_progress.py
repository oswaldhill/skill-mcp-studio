"""重跑建议必须复用标准进度展示。

背景（用户反馈）：合并完成后会重跑一次建议（要通读会话日志，约一分钟）。
原实现自己调 runCli 且不传进度参数，整分钟静默等待，用户看到的是"卡住了"。
另外阶段框里原本还挂着"重跑建议核对"这一项，而它实际发生在结果之后，
于是最后一项永远停在原地，更像卡死。

这里断言的是"重跑走的是哪条路径"，而不是文案——路径错了就没有进度框。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "gui" / "dashboard.html").read_text(encoding="utf-8")


def _fn(name):
    m = re.search(r"(?:async )?function " + name + r"\([^)]*\)\s*\{(.*?)\n  \}", HTML, re.S)
    assert m, f"找不到函数 {name}"
    return m.group(1)


class TestRerunProgress(unittest.TestCase):
    def test_rerun_uses_runSkillInsight(self):
        """重跑必须走 runSkillInsight（自带 busy 进度框），不能自己调 runCli。"""
        body = _fn("refreshAdviceAfterWrite")
        self.assertIn("runSkillInsight(", body,
                      "重跑必须复用 runSkillInsight，否则没有进度展示")
        self.assertIn("busy: true", body,
                      "重跑要显示标准进度框（与强制重新统计一致）")
        self.assertNotIn("runCli(", body,
                         "重跑不得自己调 runCli：不传进度参数就是一分钟静默")

    def test_runSkillInsight_busy_shows_progress(self):
        """busy 路径必须真的把进度文案交给 runCli 的 progress 参数。"""
        body = _fn("runSkillInsight")
        self.assertIn("withBusy", body)
        self.assertIn("runCli(args, withBusy", body,
                      "busy 时必须把进度文案传给 runCli，才会 showBusy")

    def test_stage_list_excludes_rerun(self):
        """合并的阶段框不得包含"重跑"：它发生在结果之后，会让最后一项停住。"""
        for fn in ("runMergeGroup", "runMergeAll"):
            body = _fn(fn)
            stages = re.findall(r"\[([^\]]*)\]\)", body)
            joined = " ".join(stages)
            self.assertNotIn("重跑", joined,
                             f"{fn} 的阶段列表不应包含重跑（它有自己的进度框）")
            self.assertIn("复核判据", joined,
                          f"{fn} 的阶段列表应仍描述归并过程")

    def test_verify_functions_call_rerun(self):
        """核对必须基于重跑后的新数据，不能拿旧快照自证。"""
        for fn in ("verifyMerge", "verifyMergeAll"):
            body = _fn(fn)
            self.assertIn("refreshAdviceAfterWrite()", body,
                          f"{fn} 必须先重跑再核对")
            self.assertIn("ADVICE_DATA", body,
                          f"{fn} 应基于重跑后的 ADVICE_DATA 判断")


if __name__ == "__main__":
    unittest.main()
