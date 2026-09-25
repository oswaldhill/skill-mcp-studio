"""使用统计自动刷新契约 + 市场弹窗的测试。

这些断言钉的是 2026-09 的交互决策：
- 统计是后台定时任务，打开弹窗不弹「正在计算」全屏框（用户明确要求）
- APP 开着就按可配间隔静默刷新
- 设置页可配间隔（关闭 / 5 / 15 / 30 / 60 分钟）
- 市场是独立弹窗，且只列可用市场源
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "gui" / "dashboard.html"


def _src() -> str:
    return HTML.read_text(encoding="utf-8")


def _script() -> str:
    s = _src()
    i = s.index("<script>")
    j = s.rindex("</script>")
    return s[i:j]


def _body(fn: str) -> str:
    """花括号平衡截取函数体。"""
    s = _script()
    m = re.search(r"function\s+" + re.escape(fn) + r"\s*\(", s)
    assert m, f"未找到函数 {fn}"
    i = s.index("{", m.end() - 1)
    depth, j = 0, i
    while j < len(s):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    return s[i:j + 1]


class AutoRefreshTest(unittest.TestCase):
    """统计必须由后台定时器驱动，而不是靠用户打开弹窗触发。"""

    def test_interval_key_and_options_declared_before_use(self):
        s = _script()
        # 声明必须出现在 renderSettings 之前，否则 renderSettings 一旦被提前调用
        # 就会踩 const 的 TDZ（引用点写在声明点之前是脆结构）。
        i_decl = s.index("const USAGE_AUTO_OPTS")
        i_use = s.index("usageAutoBtns")
        self.assertLess(i_decl, i_use, "USAGE_AUTO_OPTS 声明必须在设置卡片引用之前")
        for token in ("const USAGE_AUTO_KEY", "const USAGE_AUTO_DEFAULT", "const USAGE_AUTO_OPTS"):
            self.assertIn(token, s)
        # 档位：关闭 / 5 / 15 / 30 / 60
        m = re.search(r"USAGE_AUTO_OPTS\s*=\s*\[([^\]]*)\]", s)
        opts = [x.strip() for x in m.group(1).split(",")]
        self.assertEqual(opts, ["0", "5", "15", "30", "60"], f"档位变了: {opts}")

    def test_scheduler_registered_at_startup(self):
        s = _script()
        self.assertIn("function scheduleUsageAutoRefresh()", s)
        self.assertIn("setInterval(", _body("scheduleUsageAutoRefresh"))
        # 0 = 关闭时必须不注册定时器
        body = _body("scheduleUsageAutoRefresh")
        self.assertIn("if (!min) return", body, "关闭档位必须真的不注册定时器")
        # 启动时就挂上
        self.assertRegex(s, r"initNavGroups\(\);\s*\n\s*initSkillToolbar\(\);\s*\n\s*scheduleUsageAutoRefresh\(\);",
                         "启动流程必须注册自动统计定时器")

    def test_auto_refresh_is_silent_and_skips_when_busy(self):
        body = _body("scheduleUsageAutoRefresh")
        self.assertIn("silent: true", body, "定时刷新必须静默")
        self.assertIn("busy: false", body, "定时刷新绝不能弹进度框")
        # 有前台任务在跑时跳过这一轮，别和用户正等的操作抢 IO
        self.assertIn("busy-root", body, "定时刷新需检查进度框是否开着")
        self.assertRegex(body, r"return;", "忙时应跳过本轮")

    def test_startup_kickoff_is_delayed_and_silent(self):
        s = _script()
        m = re.search(r"setTimeout\(\(\) => \{(.{0,400}?)\},\s*(\d+)\);", s, re.S)
        self.assertIsNotNone(m, "缺少启动后补一次统计的 setTimeout")
        self.assertIn("silent: true", m.group(1))
        self.assertIn("busy: false", m.group(1))
        self.assertGreaterEqual(int(m.group(2)), 5000, "启动补统计应延迟，避开启动扫描的 IO 高峰")


class OpenPanelNoBusyTest(unittest.TestCase):
    """打开统计弹窗只呈现当前结果，不弹「正在计算」。"""

    def test_open_usage_passes_busy_false(self):
        body = _body("toggleInsightPanel")
        self.assertNotIn("runSkillInsight(null, true)", body,
                         "旧的 silent-only 调用会被误判为需要弹框")
        self.assertRegex(body, r"runSkillInsight\(null,\s*\{\s*silent:\s*(true|false),\s*busy:\s*false\s*\}\)",
                         "打开弹窗必须显式 busy:false")

    def test_window_switch_is_silent(self):
        s = _script()
        i = s.index('a === "insight-window"')
        seg = s[i:i + 900]
        self.assertIn("busy: false", seg, "切换窗口也不该弹进度框")

    def test_manual_refresh_still_shows_busy(self):
        # 用户确认：手动点「强制重新统计」仍要显示可取消的进度框。
        body = _body("runSkillInsight")
        self.assertRegex(body, r"withBusy\s*=", "runSkillInsight 需要区分弹框与静默")
        self.assertIn("o.busy === undefined ? (force && !silent)", body,
                      "默认行为：仅强制重算才弹框")
        self.assertIn("runCli(args, withBusy", body, "进度框文案必须按 withBusy 决定是否传")


class SettingsIntervalTest(unittest.TestCase):
    """设置页必须能配统计间隔，并持久化。"""

    def test_setting_row_present_in_general_panel(self):
        s = _script()
        self.assertIn("自动统计间隔", s)
        self.assertIn('id="usage-auto-seg"', s)
        self.assertIn("data-usage-auto=", s)
        # 落在「Skill」子页（data-panel="general"）
        m = re.search(r'data-panel="general">([^`]*)`', s)
        self.assertIsNotNone(m)
        self.assertIn("usageCard", m.group(1), "统计设置项应在 general 子页")

    def test_persists_and_reschedules(self):
        body = _body("setUsageAutoMinutes")
        self.assertIn("saveStore(USAGE_AUTO_KEY", body, "必须持久化")
        self.assertIn("scheduleUsageAutoRefresh()", body, "改间隔后必须重排定时器")

    def test_click_binding_wired(self):
        s = _script()
        self.assertRegex(s, r'querySelectorAll\("\[data-usage-auto\]"\)',
                         "设置项按钮未绑定点击")

    def test_seg_active_reads_usage_auto_attr(self):
        # setSegActive 默认读 data-win（统计窗口）；设置项用 data-usage-auto，
        # 必须显式传属性名，否则高亮永远不生效。
        self.assertIn('setSegActive($("usage-auto-seg"), usageAutoMinutes(), "usageAuto")', _script())
        self.assertIn("const key = attr || \"win\";", _body("setSegActive"))


class MarketDialogTest(unittest.TestCase):
    """市场必须是独立弹窗，且只列可用市场源。"""

    def test_market_panel_is_dialog(self):
        s = _src()
        self.assertIn('<dialog id="market-panel" class="insight-backdrop hidden"', s)
        self.assertIn('aria-label="技能市场"', s)
        # 关闭标签也要是 dialog
        i = s.index('<dialog id="market-panel"')
        seg = s[i:i + 2000]
        self.assertIn("</dialog>", seg)

    def test_market_toggle_uses_top_layer(self):
        body = _body("toggleMarketPanel")
        self.assertIn("openOverlay(el)", body)
        self.assertIn("closeOverlay(el)", body)
        self.assertNotIn("classList.toggle", body, "不应再用 class 切换显隐")

    def test_sources_reprobed_on_every_open(self):
        """打开面板必须重新探测源可用性。

        源可用性随环境变化（例如事后才装上 Node/npx）。若只在首次探测，
        后端已经修好、用户重开弹窗看到的仍是旧结论，除了重启 App 没有别的
        刷新途径——2026-09 实测踩到过，故钉住。
        """
        body = _body("toggleMarketPanel")
        self.assertIn("refreshMarketSources()", body, "打开面板未触发重新探测")
        self.assertNotIn("!MARKET_DATA.sources", body,
                         "又退回「只在首次加载」，环境变化后无法刷新")
        refresh = _body("refreshMarketSources")
        self.assertIn("loadMarketSources()", refresh, "刷新未真正发起探测")
        # 面板可被反复开关，探测进行中不得重复打 CLI
        self.assertIn("MARKET_DATA.loading", refresh, "刷新缺并发守卫")
        self.assertIn("MARKET_DATA.loading", _body("loadMarketSources"),
                      "探测本身缺并发守卫")

    def test_only_available_sources_rendered(self):
        body = _body("renderMarketSources")
        self.assertIn(".filter((s) => s.available)", body, "必须过滤出可用源")
        self.assertIn("未检测到可用的技能市场", body, "全不可用时要有兜底提示")
        # 判断依据来自后端字段，前端不做可用性推断
        self.assertNotIn("includes(", body)
        self.assertNotIn("test(", body)

    def test_no_unavailable_label_rendered(self):
        # 「未检测到」不再出现在源列表渲染里（用户要求去掉不可用项）
        body = _body("renderMarketSources")
        self.assertNotIn("未检测到\"", body)
        self.assertIn("：可用", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)