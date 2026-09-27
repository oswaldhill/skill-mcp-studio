"""「操作后只刷新该操作产生的内容」的护栏。

用户要求：任何操作与「重新刷新整份审计」没有必然联系；操作结束之后，只需刷新
**该操作所产生的那一块**。本文件锁定这条契约，防止有人把写操作又改回全量刷新。

两个方向都锁：
  * 后端 ``--management --only``：粒度、同构性、免扫描、报错行为；
  * 前端：写操作不得裸调 ``loadInternal()``，且合并必须是深合并。
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

DASHBOARD = ROOT / "gui" / "dashboard.html"


def _src() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


class BackendOnlyBlocksTest(unittest.TestCase):
    """``--only`` 的块名校验与依赖划分。"""

    def test_parse_only_accepts_known_blocks(self):
        from management_snapshot import parse_only

        self.assertEqual(parse_only("endpoints"), frozenset({"endpoints"}))
        self.assertEqual(parse_only("mcp,endpoints"), frozenset({"mcp", "endpoints"}))
        self.assertEqual(parse_only(["agents", " skills "]), frozenset({"agents", "skills"}))

    def test_parse_only_none_means_full(self):
        from management_snapshot import parse_only

        for raw in (None, "", "  ", []):
            self.assertIsNone(parse_only(raw), f"{raw!r} 应表示全量")

    def test_parse_only_rejects_unknown_block(self):
        """块名拼错必须显式报错，否则调用方会以为「刷新过了」。"""
        from management_snapshot import parse_only

        with self.assertRaises(ValueError) as ctx:
            parse_only("endpoints,nosuch")
        self.assertIn("nosuch", str(ctx.exception))

    def test_only_endpoints_is_the_scan_free_block(self):
        """只有 endpoints 能跳过技能扫描——这是 30 倍加速的来源，必须写在常量里。"""
        from management_snapshot import _ONLY_NO_SCAN

        self.assertEqual(frozenset(_ONLY_NO_SCAN), frozenset({"endpoints"}))

    def test_scan_runs_only_when_a_scan_dependent_block_is_requested(self):
        """免扫描路径不得调用 run_scan——否则「快」只是偶然。"""
        import management_snapshot as ms

        calls = []
        real = ms.run_scan
        ms.run_scan = lambda **kw: (calls.append(kw), {"unified_dir": "~/.skills", "results": [], "summary": {}})[1]
        try:
            ms.build_management_snapshot({"unified_dir": "~/.skills"}, only="endpoints")
            self.assertEqual(calls, [], "只取 endpoints 时不应触发技能扫描")
            ms.build_management_snapshot({"unified_dir": "~/.skills"}, only="agents")
            self.assertEqual(len(calls), 1, "取 agents 时必须扫描（它依赖扫描结果）")
        finally:
            ms.run_scan = real


class FrontendWritePathTest(unittest.TestCase):
    """前端：写操作走局部刷新，不重跑整份审计。"""

    def setUp(self):
        self.src = _src()

    def test_partial_refresh_helpers_exist(self):
        self.assertIn("async function refreshBlocks(", self.src)
        self.assertIn("function mergePatch(", self.src)
        self.assertIn("const BLOCK_RENDERERS = {", self.src)

    def test_writes_use_partial_refresh(self):
        """端点增删改只需要端点库——这是用户点名的场景。"""
        for msg in ("端点已添加", "端点已更新", "端点已删除"):
            self.assertIn(
                f'"{msg}"); refreshBlocks(["endpoints"]);', self.src,
                f"{msg} 之后应只刷新端点库，而不是重跑整份审计",
            )

    def test_no_write_action_calls_load_internal(self):
        """写操作后不得出现裸的 loadInternal() 全量刷新。

        保留全量的正当场景只有三处：启动加载、命令面板「刷新快照」、
        「重新扫描」按钮——它们走的是 loadManagement()/loadInternal(true)。
        """
        self.assertNotIn('showToast("ok", "端点已添加"); loadInternal();', self.src)
        self.assertNotIn('showBanner("ok", "统一目录已更新"); loadInternal();', self.src)
        # 写操作上下文里不应再有裸 loadInternal()。
        bad = re.findall(r"show(?:Toast|Banner)\(\"ok\"[^\n]*loadInternal\(\)", self.src)
        self.assertEqual(bad, [], f"写操作后仍是全量刷新：{bad}")

    def test_merge_is_deep_so_sibling_keys_survive(self):
        """--only endpoints 只回 mcp.endpoints；整块替换会抹掉 endpoint_status。"""
        self.assertIn("Object.assign(cur, v);", self.src)
        self.assertIn("else if (SNAP) SNAP[k] = v;", self.src)

    def test_partial_refresh_uses_only_flag(self):
        self.assertIn('runCli(["--management", "--only", want.join(","), "--format", "json"])', self.src)


if __name__ == "__main__":
    unittest.main()
