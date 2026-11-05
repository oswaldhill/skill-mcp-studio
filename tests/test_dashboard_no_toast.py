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
