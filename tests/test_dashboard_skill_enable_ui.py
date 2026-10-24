"""技能「启用 / 未启用」的界面口径门禁（v0.31.2 补规范时新增）。

背景：这套 UI 从 v0.29 起就有「已启用 / 部分启用 / 未启用」三段筛选与 `N / M`
徽标，但**规范里一直没有它的定义**（`DESIGN.md` 里「启用」只作为表头列名出现过
一次），也没有任何断言守着判定口径。于是长期存在两个认知风险：

1. 有人以为「启用」是技能自带的开关。实际上游 `SKILL.md` 没有 `enabled` 字段，
   共享库里没有启停开关——启用 = 客户端 skills 目录里那条符号链接。
2. 三段筛选与 `N / M` 徽标如果各算各的，就会出现「徽标说 3/5、筛选却说已启用」
   这类自相矛盾（与 v0.31.1「列表 2 个 / 弹框 4 个」同族的病）。

本文件把这两件事钉住：口径必须同源，且规范必须记录。
"""

import re
import unittest
from pathlib import Path

from tests._gui_source import page_source

ROOT = Path(__file__).resolve().parents[1]


def _src() -> str:
    return page_source()


def _fn(name: str) -> str:
    m = re.search(r"function " + name + r"\(.*?\n\}", _src(), re.S)
    if not m:
        raise AssertionError(f"未找到函数 {name}")
    return m.group(0)


class EnableSegmentsTest(unittest.TestCase):
    """三段筛选必须存在，且判据只依赖「挂了几个客户端」。"""

    def test_three_segments_exist(self):
        src = _src()
        for seg, label in (("on", "已启用"), ("partial", "部分启用"), ("off", "未启用")):
            with self.subTest(seg=seg):
                self.assertRegex(
                    src,
                    r'data-seg="%s"[^>]*>%s<' % (seg, label),
                    f"缺少分段 data-seg=\"{seg}\"（{label}）")

    def test_state_predicate_reads_client_states(self):
        """`skillStateFor` 必须从 clients_states 的 states 里数 enabled。"""
        body = _fn("skillStateFor")
        self.assertIn("states", body)
        self.assertIn("enabled", body)

    def test_segment_thresholds_are_consistent_with_badge(self):
        """三段判据必须与 N/M 徽标同源：全挂 / 部分 / 零。"""
        body = _fn("renderSkillList")
        # on: 全部挂载且客户端数非零
        self.assertRegex(
            body, r'seg === "on"\s*\)\s*return\s+enabled === total && total > 0',
            "「已启用」判据必须是 enabled === total && total > 0")
        # partial: 挂了但不全
        self.assertRegex(
            body, r'seg === "partial"\s*\)\s*return\s+enabled > 0 && enabled < total',
            "「部分启用」判据必须是 0 < enabled < total")
        # off: 一个都没挂
        self.assertRegex(
            body, r'seg === "off"\s*\)\s*return\s+enabled === 0',
            "「未启用」判据必须是 enabled === 0")

    def test_badge_colour_follows_same_three_states(self):
        """徽标三色必须由同一组数字推导（否则徽标与筛选会打架）。"""
        body = _fn("renderSkillList")
        self.assertRegex(
            body,
            r'countCls\s*=\s*enabled === total && total \? "ok" :'
            r' \(enabled > 0 \? "warn" : "err"\)',
            "N/M 徽标三色必须由 enabled/total 推导，且档位与三段筛选一致")


class EnableLegendTest(unittest.TestCase):
    """`N / M` 图例必须把两个字母的含义写全。"""

    def test_legend_explains_both_letters(self):
        src = _src()
        self.assertIn("已挂载该技能的客户端数", src,
                      "图例必须说明 N 是「已挂载该技能的客户端数」")
        self.assertIn("客户端总数", src,
                      "图例必须说明 M 是「客户端总数」，否则会被当成技能总数")


class EnableStateSemanticsTest(unittest.TestCase):
    """行为断言：三态判定与「not_in_repo 不进矩阵」是真的，不靠注释。"""

    def test_not_in_repo_excluded_from_matrix_and_states(self):
        import os
        import tempfile
        import sys
        sys.path.insert(0, str(ROOT / "core"))
        import skill_state

        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            client = os.path.join(tmp, "client")
            os.makedirs(os.path.join(repo, "alpha"))
            os.makedirs(os.path.join(repo, "beta"))
            os.makedirs(client)

            # 只给 alpha 建启用链接
            os.symlink(os.path.join(repo, "alpha"), os.path.join(client, "alpha"))

            self.assertEqual(
                skill_state.classify_skill_state(client, repo, "alpha"), "enabled")
            self.assertEqual(
                skill_state.classify_skill_state(client, repo, "beta"), "disabled")
            self.assertEqual(
                skill_state.classify_skill_state(client, repo, "ghost"), "not_in_repo")

            states = skill_state.read_skill_states(client, repo)
            self.assertEqual(states, {"alpha": "enabled", "beta": "disabled"},
                             "not_in_repo 的技能必须完全不进 states（否则会被算成未启用）")

    def test_root_form_client_marks_every_repo_skill_enabled(self):
        """root 形态（整目录一条链接）下，仓库内全部技能都算启用。"""
        import os
        import tempfile
        import sys
        sys.path.insert(0, str(ROOT / "core"))
        import skill_state

        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            os.makedirs(os.path.join(repo, "alpha"))
            os.makedirs(os.path.join(repo, "beta"))
            root_client = os.path.join(tmp, "root-client")
            os.symlink(repo, root_client)

            states = skill_state.read_skill_states(root_client, repo)
            self.assertEqual(states, {"alpha": "enabled", "beta": "enabled"},
                             "root 形态客户端应整仓库启用")
            self.assertEqual(skill_state.skill_link_form(root_client, repo), "root")


class EnableSpecTest(unittest.TestCase):
    """双轨：这套口径必须在规范（MD 与 HTML）里都有定义。"""

    REQUIRED = ("enabled", "disabled", "not_in_repo",
                "已启用", "部分启用", "未启用", "已挂载该技能的客户端数")

    def test_spec_documents_three_states_and_segments(self):
        docs = {
            "DESIGN.md": (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8"),
            "DESIGN.html": (ROOT / "docs" / "DESIGN.html").read_text(encoding="utf-8"),
        }
        for name, text in docs.items():
            with self.subTest(doc=name):
                for token in self.REQUIRED:
                    self.assertIn(token, text, f"{name} 缺少关于 {token!r} 的定义")

    def test_spec_distinguishes_disabled_from_missing(self):
        """最容易混淆的一对：disabled（正常配置状态）vs missing（数据残缺）。"""
        text = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
        self.assertIn("不可混为一谈", text,
                      "规范必须明确区分「未启用」与「登记失效」")
        self.assertIn("不是界面 bug", text,
                      "规范必须解释「本机三段里两段为空」是客户端形态决定的，不是缺陷")


if __name__ == "__main__":
    unittest.main()
