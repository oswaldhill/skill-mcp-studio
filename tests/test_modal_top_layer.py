"""确认框必须与结果面板同处 top layer。

背景（真实故障）：整理建议的确认框挂在普通 <div id="modal-root"> 里，而结果面板
（使用分析）是 showModal() 的 <dialog>。top layer 内的元素一律绘制在所有普通浮层
之上，于是确认框被面板整个盖住：用户点「执行合并」看不到任何确认框，只觉得
"闪了一下、没执行"。DOM 里有 cfm-card，屏幕上却没有——只断言 DOM 存在的测试
抓不到这个 bug，所以这里断言的是"挂载方式本身"。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "gui" / "dashboard.html").read_text(encoding="utf-8")


class TestModalLayer(unittest.TestCase):
    def test_modal_root_is_a_dialog(self):
        """承载确认框的容器必须是 <dialog>，否则进不了 top layer。"""
        m = re.search(r'<dialog id="modal-root"[^>]*>', HTML)
        self.assertIsNotNone(
            m, "modal-root 必须是 <dialog>：普通 div 会被 top layer 的结果面板盖住")
        self.assertNotIn(
            '<div id="modal-root"', HTML, "modal-root 不得退回普通 div")

    def test_mount_modal_calls_showmodal(self):
        """mountModal 必须真正调用 showModal()，仅改标签名不足以进入 top layer。"""
        m = re.search(r"function mountModal\(html\)\s*\{(.*?)\n\}", HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("showModal", body,
                      "mountModal 必须 showModal()，否则确认框仍在普通文档流")
        self.assertIn("openOverlay", body)

    def test_close_modal_exits_top_layer(self):
        m = re.search(r"function closeModal\(\)\s*\{(.*?)\n\}", HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("closeOverlay", body,
                      "closeModal 必须 closeOverlay()，否则 dialog 残留阻断交互")
        # 结算挂起的 confirm Promise 这一既有契约不能丢（Esc/backdrop 关闭时防悬空）
        self.assertIn("_pendingConfirm", body)

    def test_modal_layer_style_is_fullscreen_transparent(self):
        """dialog 有默认边框/内边距/居中，不重置会破坏既有弹窗外观。"""
        m = re.search(r"dialog\.modal-layer\s*\{(.*?)\n  \}", HTML, re.S)
        self.assertIsNotNone(m, "缺少 dialog.modal-layer 样式")
        css = m.group(1)
        for prop in ("max-width: none", "max-height: none", "border: none"):
            self.assertIn(prop, css, f"modal-layer 需要 {prop}")
        # 遮罩交给内部 .modal-backdrop，dialog 自身不该再画一层
        m2 = re.search(r"dialog\.modal-layer::backdrop\s*\{([^}]*)\}", HTML)
        self.assertIsNotNone(m2)
        self.assertIn("transparent", m2.group(1))

    def test_confirm_dialog_mounts_via_mountModal(self):
        """confirmModal 必须走 mountModal，不能自己写 innerHTML。

        这是真实故障点：mountModal 里有 showModal()，直接写 innerHTML 则没有，
        确认框就留在普通文档流、被 top layer 的结果面板盖住。
        只断言"提到了 modal-root"抓不到它——必须断言挂载方式。
        """
        m = re.search(r"function confirmModal\([^)]*\)\s*\{(.*?)\n\}", HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("mountModal(", body,
                      "confirmModal 必须用 mountModal 挂载，否则不会 showModal()")
        self.assertNotIn('$("modal-root").innerHTML', body,
                         'confirmModal 不得直接写 modal-root.innerHTML（绕过 showModal）')

    def test_no_dialog_bypasses_mountModal(self):
        """除 mountModal 自身外，任何弹窗都不得直接写 modal-root.innerHTML。

        否则那个弹窗同样进不了 top layer，在结果面板打开时不可见。
        """
        offenders = []
        for fn in re.finditer(r"function (\w+)\([^)]*\)\s*\{(.*?)\n\}", HTML, re.S):
            name, body = fn.group(1), fn.group(2)
            if name == "mountModal":
                continue
            if '$("modal-root").innerHTML' in body:
                offenders.append(name)
        self.assertEqual(offenders, [],
                         f"这些函数绕过了 mountModal，会被 top layer 遮挡: {offenders}")


if __name__ == "__main__":
    unittest.main()