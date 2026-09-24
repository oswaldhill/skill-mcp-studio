"""CSP × inline style 回归护栏（一次真实事故的固化）。

事故现象：技能统计弹窗里的「强度」条，在浏览器预览下长短分明，装进 App 后
13 条全长一个样（逐像素测过：全部 236px）。样式没写错，百分比也算对了
（100/52/39/38/29...），问题出在 CSP。

根因链：
1. tauri.conf.json 声明 style-src 'self' 'unsafe-inline'；
2. Tauri 构建期调用 inject_nonce_token，给每个 <style> 元素注入 nonce
   （dangerousDisableAssetCspModification 默认 false 时启用）；
3. 运行时 CSP 变成 style-src 'self' 'unsafe-inline' 'nonce-…'；
4. CSP 规范规定：指令里一旦出现 nonce/hash，'unsafe-inline' 即被忽略；
5. <style> 块靠 nonce 存活（所以整站样式看起来完全正常），
   而所有 style="…" 属性被静默拦截 —— 宽度失效后 <i> 退化成撑满整列。

这类缺陷的危险之处是"看起来没坏"：样式仍在、数字仍在，只有尺寸语义悄悄丢了。
所以本文件锁死两件事：

* 配置层：必须关掉资产 CSP 改写，让声明的 'unsafe-inline' 真正生效；
* 代码层：关键尺寸不得交给 style 属性，改用 CSSOM（el.style.x = ...），
  它对 style-src 免疫 —— 万一配置再次被改回去也不至于重演。
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "gui" / "dashboard.html"
CONF = ROOT / "src-tauri" / "tauri.conf.json"
RS = ROOT / "src-tauri" / "src" / "lib.rs"


def _src() -> str:
    return HTML.read_text(encoding="utf-8")


def _fn(name: str) -> str:
    m = re.search(r"(async\s+)?function " + name + r"\(.*?\n  \}", _src(), re.S)
    if not m:
        raise AssertionError(f"未找到函数 {name}")
    return m.group(0)


class TauriCspConfigTest(unittest.TestCase):
    def setUp(self):
        self.conf = json.loads(CONF.read_text(encoding="utf-8"))

    def test_asset_csp_modification_is_disabled(self):
        """核心护栏：不改写 CSP，'unsafe-inline' 才不会被 nonce 挤掉。"""
        sec = self.conf["app"]["security"]
        self.assertIs(
            sec.get("dangerousDisableAssetCspModification"), True,
            "必须显式关闭 Tauri 的资产 CSP 改写：否则 <style> 会被注入 nonce，"
            "CSP 里的 'unsafe-inline' 随之失效，全站 style=\"…\" 属性被静默拦截"
            "（症状：强度条全部等长）",
        )

    def test_csp_still_allows_inline_style(self):
        csp = self.conf["app"]["security"]["csp"]
        self.assertIn("style-src 'self' 'unsafe-inline'", csp)

    def test_csp_does_not_whitelist_network(self):
        """顺手确认这次改动没有把网络边界放开。"""
        csp = self.conf["app"]["security"]["csp"]
        self.assertIn("connect-src 'none'", csp)
        self.assertIn("default-src 'self'", csp)


class InlineStyleAttributeTest(unittest.TestCase):
    def test_usage_bar_does_not_use_style_attribute_for_width(self):
        body = _fn("renderUsage")
        self.assertNotIn(
            '<i style="width:', body,
            "强度条宽度不能写成 style 属性：CSP 的 style-src 会把它整条丢掉，"
            "<i> 会退化成撑满整列，整列条长得一模一样",
        )
        self.assertIn("data-pct", body, "宽度应经 data-pct 传递，再用 CSSOM 落地")

    def test_usage_bar_width_is_applied_via_cssom(self):
        body = _fn("renderUsage")
        self.assertIn(".style.width", body,
                      "宽度必须用 CSSOM 赋值（el.style.width），它对 CSP 免疫")

    def test_busy_progress_width_is_applied_via_cssom(self):
        body = _fn("setBusyProgress")
        self.assertIn("busy-bar-fill", body)
        self.assertIn(".style.width", body,
                      "进度条宽度同样必须走 CSSOM，否则准确进度条在 App 里会一直是空的")


class CancelAndProgressPlumbingTest(unittest.TestCase):
    """关闭进度框 = 终止子进程；扫描进度 = 后端可算的准确 N/total。"""

    def test_rust_registers_cancel_and_progress_commands(self):
        src = RS.read_text(encoding="utf-8")
        m = re.search(r"generate_handler!\[(.*?)\]", src, re.S)
        self.assertIsNotNone(m, "未找到 invoke_handler 注册表")
        handlers = m.group(1)
        self.assertIn("cancel_cli", handlers)
        self.assertIn("read_scan_progress", handlers)

    def test_rust_forces_progress_file_path(self):
        """进度文件路径必须由 shell 决定：不能让 webview 指定任意写盘目标。"""
        src = RS.read_text(encoding="utf-8")
        self.assertIn("fn progress_file_path()", src)
        self.assertIn("--progress-file", src)
        self.assertNotIn(
            'args: Vec<String>, progress_path', src,
            "run_cli 不应接受调用方传入的进度文件路径",
        )

    def test_rust_kills_whole_process_group(self):
        src = RS.read_text(encoding="utf-8")
        self.assertIn("process_group(0)", src,
                      "子进程要独立进程组，取消时才能连子孙一起收掉")
        self.assertIn("fn kill_child(", src)

    def test_frontend_cancel_is_wired(self):
        src = _src()
        self.assertIn('id="busy-cancel"', src, "进度框必须有取消按钮")
        self.assertIn("cancel_cli", src, "取消按钮必须真的终止子进程")
        self.assertIn("busy-cancel", src)

    def test_frontend_shows_exact_progress(self):
        body = _fn("pollScanProgress")
        self.assertIn("read_scan_progress", body)
        self.assertIn("total", body, "有总量时才能显示准确进度")

    def test_scan_flag_is_forwarded_to_cli(self):
        src = ROOT.joinpath("scan.py").read_text(encoding="utf-8")
        self.assertIn('"--progress-file"', src)
        self.assertIn("progress_path=getattr(args", src)


class UsageCacheTest(unittest.TestCase):
    """结果缓存：打开弹窗先出缓存，避免每次都重扫上千个会话文件。"""

    def test_cache_helpers_exist(self):
        src = _src()
        for token in ("USAGE_CACHE_KEY", "loadUsageCache", "saveUsageCache",
                      "readUsageCache", "usageCacheFresh"):
            self.assertIn(token, src, f"缺少缓存件 {token}")

    def test_open_prefers_cache_then_refreshes_in_background(self):
        body = _fn("toggleUsagePanel")
        self.assertIn("readUsageCache", body, "打开弹窗必须先读缓存")
        self.assertIn("usageCacheFresh", body,
                      "缓存过期要在后台静默刷新，而不是又弹一次统计中")

    def test_scan_result_is_cached(self):
        body = _fn("runSkillUsage")
        self.assertIn("saveUsageCache", body, "扫描结果必须写回缓存")

    def test_cancel_keeps_cached_view(self):
        body = _fn("runSkillUsage")
        self.assertIn("cancelled", body,
                      "用户取消不是失败：不得把已有结果替换成报错")


if __name__ == "__main__":
    unittest.main()