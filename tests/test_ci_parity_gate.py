"""守住 `scripts/ci_parity.sh` 的「失败不遮蔽」性质（2026-10-10 回归增设）。

## 为什么需要这个测试

`scripts/ci_parity.sh` 是本地复现 CI 结论的总闸，**但它自己此前没有回归保护**
（`grep -rln "ci_parity" tests/` 无命中，见 `docs/reviews/评审-v0.23.0-整改与优化清单.md`
的 P1-7）。于是它在 2026-10-10 的构建环境回归里暴露了一个盲区：

    每个「工具门禁」（PyYAML / 卫生自检 / 密钥扫描 / ruff / node / cargo）一旦失败
    就立刻 `exit 1`，导致**后面的 Python 单元测试根本不会跑**。

实测（漏装 ruff 时）：输出停在「✗ 未找到 ruff」，一条测试都没跑，`exit=1`。
这与「测试失败」在现象上难以区分，而处置完全不同 —— 前者是环境缺件，
后者是代码回归。**一次误导性的门禁输出，比没有门禁更危险。**

## 修法与本文档的断言

改为「失败累加器」：能跑的门禁全部跑完，`record_failure` 记录，最后
`print_summary_and_exit` 统一汇总并返回非零。只有「无论如何都跑不下去」的
前置条件（无解释器 / 解释器版本过低）才立即退出。

因此本文件断言四件事：

1. 累加器与汇总函数存在，且最终退出都经过汇总；
2. **ruff 段到 unittest 调用之间不许出现 `exit`** —— 这条直接锁住上述回归；
3. `exit 1` 只允许出现在汇总函数与两个硬前置条件里；
4. 脚本里的 CI 基线常量（`CI_PATTERN` / `CI_NODE_MAJOR`）与
   `.github/workflows/test.yml` 实际钉定的值一致 —— 基线与 CI 漂移会让
   「与 CI 等价」这句话失效（node 大版本一致性与 `node --test` 行为相关，见 Q1-1）。

刻意用**静态文本断言**而不是真跑一遍脚本：真跑会连带执行 1088 个用例
（约 30s）与 cargo test，让本测试自身成为套件里最慢的一项；而这里要守的是
脚本的**结构约束**（不许提前退出），静态断言恰好是最直接的判据。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_parity.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"

# 分段锚点：用脚本里稳定存在的 note 文案定位各段，避免依赖行号。
RUFF_SECTION = "ruff 静态检查（P1-11"
UNITTEST_SECTION = "== 运行（命令与"


class CiParityGateTest(unittest.TestCase):
    """`scripts/ci_parity.sh` 的结构约束。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SCRIPT.read_text(encoding="utf-8")

    # ── 1) 累加器与汇总函数 ──────────────────────────────────────────────
    def test_failure_accumulator_and_summary_exist(self) -> None:
        """必须存在失败累加器与统一汇总，否则「失败不遮蔽」无从谈起。"""
        self.assertIn("FAILED_GATES=(", self.text, "缺少失败累加器 FAILED_GATES")
        self.assertIn("record_failure()", self.text, "缺少 record_failure 记录函数")
        self.assertIn(
            "print_summary_and_exit()",
            self.text,
            "缺少 print_summary_and_exit 汇总函数 —— 各门禁会各自 exit，"
            "后面的门禁（尤其是单元测试）又会跑不到",
        )
        # 脚本末尾必须走汇总，而不是自己 exit。
        last_line = [ln for ln in self.text.rstrip().splitlines() if ln.strip()][-1].strip()
        self.assertEqual(
            "print_summary_and_exit",
            last_line,
            "脚本最后一行不是 print_summary_and_exit —— 说明某个分支会自己退出，"
            "汇总信息（含未通过门禁清单）将不再完整",
        )

    # ── 2) 核心回归：工具门禁不得提前退出 ───────────────────────────────
    def test_tool_gates_never_exit_before_unit_tests(self) -> None:
        """ruff 段到 unittest 调用之间，不许有**可执行行**提前退出。

        这正是 2026-10-10 回归的病灶：漏装 ruff 时脚本在 ruff 段 `exit 1`，
        于是「Ran N tests」那一行永远不会出现，输出被误读成测试失败。

        判据只看「去掉前导空白后以 exit/return 开头的行」—— 注释里出现
        `exit 1` 这类说明文字不算（本文件的注释就大量提到了它）。
        """
        start = self.text.find(RUFF_SECTION)
        end = self.text.find(UNITTEST_SECTION)
        self.assertNotEqual(start, -1, f"脚本里找不到 ruff 段锚点：{RUFF_SECTION!r}")
        self.assertNotEqual(end, -1, f"脚本里找不到 unittest 段锚点：{UNITTEST_SECTION!r}")
        self.assertLess(start, end, "ruff 段必须位于 unittest 段之前（否则本断言失去意义）")

        middle = self.text[start:end]
        offenders = [
            f"{idx}: {line.strip()}"
            for idx, line in enumerate(middle.splitlines(), start=1)
            if line.strip().startswith(("exit ", "return 1"))
        ]
        self.assertEqual(
            [],
            offenders,
            "ruff 段与单元测试之间仍有提前退出 —— 会让后面的门禁（含单元测试）"
            "完全不执行，输出被误读为『测试失败』。应改用 record_failure 记录并继续："
            + "; ".join(offenders),
        )
        # 这段里应当真的有「记录失败」的调用（否则可能整段被删了）。
        self.assertIn("record_failure", middle, "工具门禁段没有任何 record_failure 调用")

    def test_exits_are_confined_to_summary_and_hard_preconditions(self) -> None:
        """`exit 1` 只允许出现在汇总函数与两个硬前置条件里。

        硬前置条件 = 找不到解释器 / 解释器版本 < 3.11（这两种情况下什么也跑不了）。
        """
        ruff_start = self.text.find(RUFF_SECTION)
        assert ruff_start != -1

        offenders = []
        for lineno, line in enumerate(self.text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith("exit "):
                continue
            # 汇总函数内部允许（它在 ruff 段之前定义）。
            if lineno < ruff_start:
                continue
            offenders.append(f"{lineno}: {stripped}")
        self.assertEqual(
            [],
            offenders,
            "ruff 段之后仍存在提前退出（应改为 record_failure + 末尾汇总）："
            + "; ".join(offenders),
        )

    # ── 3) 基线常量与 CI 实际值一致 ─────────────────────────────────────
    def test_ci_pattern_matches_workflow_command(self) -> None:
        """`CI_PATTERN` 必须与 workflow 里 discover 用的 pattern 一致。"""
        wf = WORKFLOW.read_text(encoding="utf-8")
        m = re.search(r"unittest discover -s tests -p '([^']+)'", wf)
        self.assertIsNotNone(m, "workflow 里找不到 unittest discover 命令")
        wf_pattern = m.group(1)

        m2 = re.search(r"^CI_PATTERN='([^']+)'", self.text, re.MULTILINE)
        self.assertIsNotNone(m2, "脚本里找不到 CI_PATTERN")
        self.assertEqual(
            wf_pattern,
            m2.group(1),
            "CI_PATTERN 与 workflow 的 -p pattern 不一致 —— 本地跑的用例集合与 CI 不同",
        )

    def test_node_major_matches_ci_workflow(self) -> None:
        """`CI_NODE_MAJOR` 必须与 workflow 钉的 node 主版本一致（Q1-1）。

        脚本在 node 主版本与 CI 不一致时会告警（因为 `node --test` 的报告格式与
        部分 API 行为跨大版本有差异，而 T-3 是 GUI 纯函数的主要防线）。
        若 workflow 升级 node 而忘了改这里的常量，告警就会指向错误的目标版本。
        """
        wf = WORKFLOW.read_text(encoding="utf-8")
        m = re.search(r"node-version:\s*'(\d+)", wf)
        self.assertIsNotNone(m, "workflow 里找不到 node-version")
        wf_major = m.group(1)

        m2 = re.search(r"^CI_NODE_MAJOR=(\d+)", self.text, re.MULTILINE)
        self.assertIsNotNone(m2, "脚本里找不到 CI_NODE_MAJOR")
        self.assertEqual(
            wf_major,
            m2.group(1),
            "CI_NODE_MAJOR 与 workflow 的 node-version 主版本不一致 —— "
            "node 大版本不一致时的告警会指向错误版本",
        )

    # ── 4) unittest 命令与 CI 同形，且 skipped 基线仍受检 ────────────────
    def test_runs_same_unittest_command_and_checks_skip_baseline(self) -> None:
        """脚本必须用与 CI 相同的 discover 命令，并比对 skipped 基线。"""
        self.assertIn(
            '-m unittest discover -s tests -p "$CI_PATTERN"',
            self.text,
            "脚本没有用与 CI 相同的 unittest discover 命令",
        )
        self.assertIn(
            "CI_BASELINE_SKIPPED",
            self.text,
            "缺少 skipped 基线比对 —— 多出的 skip（依赖缺失导致静默跳过）将无人发现",
        )
        self.assertIn(
            "CI_ALLOW_SKIP_DRIFT",
            self.text,
            "缺少显式豁免开关 —— 基线漂移只能靠改脚本绕过，会诱发随手改基线",
        )


if __name__ == "__main__":
    unittest.main()
