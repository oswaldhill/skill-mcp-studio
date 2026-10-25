"""PRD 综合整理与评审结果的门禁断言（v1.5，2026-10-25）。

评审的产出不是「改了几行字」，而是**把过时表述钉死**：本次发现 9 处「文档说 A、
代码是 B」，其中 6 处的成因都是「实现先行、PRD 未回写」。这类漂移下次评审还会
重犯，所以把关键结论写成断言——谁把「三态」改回去、谁把「不做技能市场」原样
搬回来，门禁立刻报红。

断言分三类：
1. 已勘正的事实不再回退（跨平台、38 条、五态、WebDAV）；
2. 边界表述必须是「拆分过」的版本，不能退回粗表述；
3. 评审记录本身要留档（方法、问题表、未改项及原因），否则等于没评审。
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRD = ROOT / "docs" / "product" / "PRD-产品需求文档.md"


class CorrectedFactsTest(unittest.TestCase):
    """已勘正的事实：这些句子被改回去就说明回写白做了。"""

    def setUp(self):
        self.body = PRD.read_text(encoding="utf-8")

    def test_cross_platform_is_no_longer_claimed_blank(self):
        # 这句话只允许出现在「勘正上下文」里（即紧跟在「该表述已不成立」之后），
        # 不允许作为结论句独立出现。
        self.assertIn("该表述已不成立", self.body)
        self.assertIn("by_os", self.body)
        self.assertIn("build-windows.yml", self.body)
        # 不能再有「结论式」的空白断言：不以勘正口吻出现的相同句子
        self.assertNotIn("> 架构结论：必须摒弃「macOS 中心」的路径硬编码，采用**跨平台分派**（决策 A，见 §1.3）。当前代码", self.body)

    def test_registry_count_is_38_not_22(self):
        self.assertIn("实测 38 条", self.body)
        self.assertNotIn("共 **22 个**", self.body)
        # 两个口径必须都讲清楚，避免又混成一个数
        self.assertIn("注册表条数」≠「本机受管客户端数", self.body)

    def test_update_check_is_five_states(self):
        self.assertIn("**五态**", self.body)
        for state in ("outdated", "current", "unknown", "missing", "repo_outdated"):
            self.assertIn(state, self.body, f"五态里缺 {state}")
        self.assertNotIn("三态：有更新 / 最新 / 未知", self.body)

    def test_webdav_no_longer_deferred(self):
        self.assertNotIn("WebDAV 远程同步留后续版本", self.body)
        self.assertIn("--sync-webdav-push", self.body)
        self.assertIn("不同步** `github_token`", self.body)


class BoundarySplitTest(unittest.TestCase):
    """边界表述必须是拆分后的版本，不能退回「一句不做」的粗表述。"""

    def setUp(self):
        self.body = PRD.read_text(encoding="utf-8")

    def test_market_boundary_is_split_into_consumer_vs_distributor(self):
        self.assertIn("不做**技能市场 / 商店**平台**", self.body)
        self.assertIn("成为分发方", self.body)
        self.assertIn("消费方", self.body)
        # 原来的粗表述不能再出现
        self.assertNotIn("- **不做**技能市场 / 商店（agentregistry、gh skill 领域）。", self.body)

    def test_cloud_sync_boundary_explains_webdav(self):
        self.assertIn("不自建云", self.body)
        self.assertIn("搬运的是用户自己的存储", self.body)

    def test_on_demand_loading_marked_landed(self):
        self.assertIn("按需加载 / 逐技能启停已落地", self.body)
        self.assertIn("运行时按会话加载", self.body)


class ReviewRecordTest(unittest.TestCase):
    """评审记录本身要留档。"""

    def setUp(self):
        self.body = PRD.read_text(encoding="utf-8")

    def test_review_section_exists_with_method(self):
        self.assertIn("## 12. 评审记录", self.body)
        self.assertIn("评审方法", self.body)

    def test_problem_table_lists_the_nine_findings(self):
        # §12.2 的问题表必须有 9 行（用「| 数字 | §」形态计数）
        rows = re.findall(r"\n\| \d+ \| §", self.body)
        self.assertGreaterEqual(len(rows), 9, f"评审问题表只有 {len(rows)} 行，应为 9 行")

    def test_untouched_parts_recorded_with_reason(self):
        self.assertIn("本轮**没有**改的部分及原因", self.body)
        self.assertIn("七页", self.body)
        self.assertIn("退出码", self.body)

    def test_product_level_issues_escalated(self):
        # 评审要能区分「文档问题」与「产品问题」，后者要排期
        self.assertIn("产品层", self.body)
        self.assertIn("查不成 ≠ 没问题", self.body)

    def test_version_row_added(self):
        self.assertIn("| v1.5 | 2026-10-25 |", self.body)


class ClaimsMatchCodeTest(unittest.TestCase):
    """PRD 声称的能力，CLI 里必须真的有——防止「文档写了但没实现」。"""

    FLAGS = (
        "--skill-insight",
        "--skill-rollback",
        "--list-skill-backups",
        "--sync-webdav-push",
        "--set-github-token",
        "--list-skill-states",
        "--audit-skill-states",
        "--migrate-skill-links",
        "--market-install",
        "--market-upgrade",
    )

    def test_all_claimed_flags_exist_in_cli(self):
        scan = (ROOT / "scan.py").read_text(encoding="utf-8")
        missing = [f for f in self.FLAGS if f not in scan]
        self.assertEqual([], missing, f"PRD 声称但 CLI 未实现: {missing}")

    def test_pages_claim_matches_dashboard(self):
        # v1.7 起为八页（新增 DSH 插件页）。这条断言的作用就是：页面集合一变就
        # 必须回来改这里与 PRD §5.3，防止文档与实现各说各话。
        gui = (ROOT / "gui" / "dashboard.html").read_text(encoding="utf-8")
        pages = set(re.findall(r'data-page="([a-z-]+)"', gui))
        self.assertEqual(
            {"overview", "agents", "skills", "mcp", "hooks", "changes", "dsh", "settings"},
            pages,
            "PRD §5.3 说八页，dashboard 的 data-page 集合变了就要同步改文档",
        )

    def test_registry_count_claim_is_true(self):
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0,'core');"
             "import mainstream_registry as m;"
             "print(len(m.register_mainstream_tools()))"],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(0, out.returncode, out.stderr)
        self.assertEqual("38", out.stdout.strip(),
                         "注册表条数变了：PRD §1.4 的「38 条」需同步更新")


if __name__ == "__main__":
    unittest.main()
