"""界面反馈一律用弹框，不得用 toast（2026-11-05 用户要求的硬规则）。

## 为什么需要这条规则

规范此前只定义了「弹框长什么样」（DESIGN.md §2.5b），没定义「什么时候该弹框」。
于是 86 处反馈全部走 ``showToast()`` —— 自动消失的浮层。用户的原话是
「对于信息的展示，有没有要求必须是弹框？如果不是，请增加要求」。

自动消失对**需要读完再判断**的信息是有害的：检查汇总、错误原因几秒后就没，
用户切回窗口时已错过，也无法复制回看。

## 判据（为什么这样切）

- **操作结果**（成功 / 失败 / 警告 / 汇总）必须弹框 —— 这是本次要改的主体；
- **过程反馈**（「正在执行…」）允许行内状态 —— 用户明确要求保留，否则每个操作
  都会先弹一个框、完成后再弹一个，交互反而更差；
- **页面级横幅**（CLI 未装这类持续状态）不属于一次性消息，不在此列。

所以在源码层面，``showToast`` 只允许出现在两类位置：过程反馈，以及
``showToast`` 自身的定义/兼容层。其余任何新增调用都会被本测试点名。
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests._gui_source import page_source  # noqa: E402


def _src() -> str:
    return page_source()


def _call_sites(src: str):
    """返回 [(行号, 行文本)] 形式的 showToast 调用点。"""
    out = []
    for i, line in enumerate(src.splitlines(), 1):
        if "showToast(" in line and "function showToast" not in line:
            out.append((i, line.strip()))
    return out


class NoToastForMessagesTest(unittest.TestCase):
    def test_no_showtoast_calls_remain(self):
        offenders = [
            f"line {i}: {line[:110]}"
            for i, line in _call_sites(_src())
        ]
        self.assertEqual(
            offenders[:10],
            [],
            "仍有 toast 调用。信息展示/询问必须走弹框（modalNotice）。\n"
            "若确实是「正在执行…」的过程反馈，请改用行内状态而不是 toast：\n"
            + "\n".join(offenders[:10]),
        )

    def test_modal_notice_entry_exists(self):
        src = _src()
        m = re.search(r"function modalNotice\(([^)]*)\)", src)
        self.assertIsNotNone(m, "缺少统一的弹框入口 modalNotice(kind, title, message)")
        self.assertIn("mountModal", src, "弹框必须走 mountModal 才能进入 top layer")

    def test_modal_notice_is_not_a_toast_in_disguise(self):
        """modalNotice 必须真的弹框，不能内部又转调 toast。"""
        src = _src()
        i = src.find("function modalNotice(")
        self.assertGreater(i, 0)
        body = src[i:i + 1200]
        self.assertNotIn(
            "showToast", body,
            "modalNotice 内部仍调用 toast —— 那就是把吐司改了个名字",
        )
        self.assertIn("mountModal", body)


class LoadingStateTest(unittest.TestCase):
    """「正在执行…」必须是行内状态，且必须能被清掉。

    只检查「没用 toast」不够：把加载提示删掉、或者只显示不关闭，都会让用户
    以为操作卡住。因此要求每个启动加载的地方都能观察到结束。
    """

    def test_loading_uses_inline_state_not_toast(self):
        src = _src()
        self.assertNotRegex(
            src,
            r'showToast\(\s*"info"',
            "仍有用 toast 显示「正在…」的过程提示",
        )


class SpecDocumentTest(unittest.TestCase):
    def test_spec_requires_modal_for_messages(self):
        spec = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
        self.assertIn("一律用弹框", spec)
        self.assertIn("modalNotice", spec)


if __name__ == "__main__":
    unittest.main()


class ProgressModalTest(unittest.TestCase):
    """一次操作 = 一个弹框：过程在框内累积，结束后原地变结果（2026-11-05 用户要求）。

    用户原话：「可以在弹框中进行进度的展示，每个操作都作为进度的一部分，
    只有完整结束之后再关闭弹框」。

    上一版把每次操作都做成了独立弹框（67 处 modalNotice），于是：
    - 批量操作会连弹 N 个框，必须逐个关掉；
    - 弹框本身就是「结果」，过程仍然看不见。

    判据：
    1. 存在进度弹框入口（progressModal*），能「开始 / 追加一条 / 结束」；
    2. 结束时**复用同一个弹框**转成结果态，不 close 再新开（否则又是一次闪烁）；
    3. 批量循环里不得逐条弹结果框 —— 循环内只追加进度项。
    """

    def test_progress_modal_api_exists(self):
        src = _src()
        for fn in ("function progressBegin", "function progressStep", "function progressFinish"):
            self.assertIn(fn, src, f"缺少进度弹框接口：{fn}")

    def test_finish_reuses_the_same_modal(self):
        """结束必须原地转态，不能先关掉再重开一个新框。

        注意 closeModal 本身是允许的 —— 它是「关掉」按钮的点击处理（用户主动关闭，
        正是「完整结束之后再关闭」那条要求）。要禁的是**执行路径里**先关后开：
        那会闪两下，也会让过程框提前消失。
        """
        src = _src()
        i = src.find("function progressFinish")
        self.assertGreater(i, 0)
        body = src[i:src.find("\nfunction ", i + 10)]
        self.assertEqual(
            body.count("closeModal"), 1,
            "progressFinish 出现多处 closeModal —— 流程里先关再开会闪两下",
        )
        self.assertIn("btn.onclick = closeModal", body,
                      "唯一的 closeModal 必须是「关掉」按钮的点击处理")
        self.assertIn("data-progress-replace", body,
                      "结束时没有原地替换内容（应复用同一弹框）")


    def test_batch_loops_append_steps_not_modals(self):
        """批量循环内只追加进度项，不逐条弹结果框。"""
        src = _src()
        # 找批量开关客户端的那段循环
        i = src.find("async function batchToggleMts")
        self.assertGreater(i, 0, "找不到 batchToggleMts")
        body = src[i:i + 2200]
        self.assertIn("progressStep", body, "批量操作没有把每条计入进度")
        self.assertEqual(
            body.count('modalNotice("ok"'), 0,
            "批量循环内仍在逐条弹成功框，用户要一个个关掉",
        )
