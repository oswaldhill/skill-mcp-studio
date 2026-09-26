"""技能合并执行（FEAT-12）：真实落盘行为与安全护栏。"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import skill_merge_exec  # noqa: E402


def _make_skill(root: Path, name: str, desc: str = "") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n\n内容 {name}\n",
        encoding="utf-8")
    return d


def _advice(*groups) -> dict:
    """构造一份判据结果，形状与 scan_advice 输出一致。"""
    return {"actionable": [
        {"id": f"grp-{i:02d}", "rule": "T1", "keep": k, "fold": list(f),
         "members": [k] + list(f), "evidence": "测试构造", "rules_hit": ["T1"], "detail": []}
        for i, (k, f) in enumerate(groups, 1)
    ]}


class MergeExecTest(unittest.TestCase):
    """在临时库里实跑，不碰真实技能库。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="merge-exec-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        _make_skill(self.tmp, "grafana-dashboard", "管理 Grafana 仪表盘。" * 3)
        _make_skill(self.tmp, "grafana-dashboards", "管理 Grafana 仪表盘。" * 3)
        _make_skill(self.tmp, "unrelated-skill", "完全无关的技能。" * 3)
        self.adv = _advice(("grafana-dashboard", ["grafana-dashboards"]))

    def _merge(self, keep, fold, **kw):
        kw.setdefault("advice", self.adv)
        return skill_merge_exec.merge_group(keep, fold, skills_dir=str(self.tmp), **kw)

    # ---- 正常路径 ------------------------------------------------------
    def test_fold_dir_moved_to_trash_and_backed_up(self):
        res = self._merge("grafana-dashboard", ["grafana-dashboards"])
        self.assertEqual(res["status"], "ok", res["message"])
        self.assertFalse((self.tmp / "grafana-dashboards").exists(), "归并方原目录应已移走")
        trash = list((self.tmp / "_trash").glob("grafana-dashboards-*"))
        self.assertEqual(len(trash), 1, "应有一条回收记录")
        self.assertTrue((trash[0] / "SKILL.md").exists(), "回收目录里应保留内容")
        backup = list((self.tmp / "_backup").glob("grafana-dashboards-*"))
        self.assertEqual(len(backup), 1, "应有一份备份")
        self.assertTrue((backup[0] / "SKILL.md").exists(), "备份里应保留内容")

    def test_keep_dir_untouched(self):
        keep = self.tmp / "grafana-dashboard"
        before = (keep / "SKILL.md").read_bytes()
        self._merge("grafana-dashboard", ["grafana-dashboards"])
        self.assertTrue(keep.exists(), "保留方必须还在")
        self.assertEqual((keep / "SKILL.md").read_bytes(), before, "保留方内容被改动")

    def test_unrelated_skill_untouched(self):
        other = self.tmp / "unrelated-skill"
        before = (other / "SKILL.md").read_bytes()
        self._merge("grafana-dashboard", ["grafana-dashboards"])
        self.assertTrue(other.exists(), "组外技能被删了")
        self.assertEqual((other / "SKILL.md").read_bytes(), before)

    # ---- 安全护栏 ------------------------------------------------------
    def test_stale_advice_is_rejected_and_nothing_changes(self):
        """组不在判据里（建议过期/伪造）必须拒绝，且不动盘。"""
        before = sorted(p.name for p in self.tmp.iterdir())
        bad = _advice(("other-keep", ["other-fold"]))
        res = skill_merge_exec.merge_group(
            "grafana-dashboard", ["grafana-dashboards"],
            skills_dir=str(self.tmp), advice=bad)
        self.assertEqual(res["status"], "error", "不成立的组必须拒绝")
        self.assertIn("不成立", res["message"])
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), before,
                         "拒绝执行时不得产生任何改动")
        self.assertFalse((self.tmp / "_trash").exists(), "拒绝执行不该建 _trash")

    def test_missing_dir_is_rejected(self):
        adv = _advice(("grafana-dashboard", ["no-such-skill"]))
        res = skill_merge_exec.merge_group(
            "grafana-dashboard", ["no-such-skill"],
            skills_dir=str(self.tmp), advice=adv)
        self.assertEqual(res["status"], "error")
        self.assertIn("未找到", res["message"])
        self.assertTrue((self.tmp / "grafana-dashboard").exists())

    def test_keep_cannot_be_in_fold(self):
        res = self._merge("grafana-dashboard", ["grafana-dashboard"])
        self.assertEqual(res["status"], "error")
        self.assertIn("不能同时", res["message"])

    def test_empty_inputs_rejected(self):
        self.assertEqual(self._merge("", ["a"])["status"], "error")
        self.assertEqual(self._merge("keep", [])["status"], "error")

    def test_over_limit_rejected(self):
        res = self._merge("grafana-dashboard", [f"s{i}" for i in range(50)])
        self.assertEqual(res["status"], "error")
        self.assertIn("最多", res["message"])

    # ---- dry-run ------------------------------------------------------
    def test_dry_run_changes_nothing(self):
        before = sorted(p.name for p in self.tmp.iterdir())
        res = self._merge("grafana-dashboard", ["grafana-dashboards"], dry_run=True)
        self.assertEqual(res["status"], "dry-run")
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), before)
        self.assertFalse((self.tmp / "_trash").exists(), "dry-run 不该建 _trash")
        self.assertFalse((self.tmp / "_backup").exists(), "dry-run 不该建 _backup")

    # ---- 全部合并 ------------------------------------------------------
    def test_merge_all_folds_every_group(self):
        adv = _advice(("grafana-dashboard", ["grafana-dashboards"]))
        res = skill_merge_exec.merge_all(skills_dir=str(self.tmp), advice=adv)
        self.assertEqual(res["status"], "ok", res["message"])
        self.assertIn("grafana-dashboards", res["folded"])
        self.assertFalse((self.tmp / "grafana-dashboards").exists())
        self.assertTrue((self.tmp / "grafana-dashboard").exists())

    def test_merge_all_with_no_groups_is_ok(self):
        res = skill_merge_exec.merge_all(skills_dir=str(self.tmp), advice={"actionable": []})
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["folded"], [])

    def test_partial_failure_is_reported_honestly(self):
        """一组失败、一组成功时必须如实报告，不假装整体成功。"""
        _make_skill(self.tmp, "beta")
        _make_skill(self.tmp, "beta-2")
        adv = _advice(("grafana-dashboard", ["grafana-dashboards"]),
                      ("beta", ["beta-2", "no-such-skill"]))
        res = skill_merge_exec.merge_all(skills_dir=str(self.tmp), advice=adv)
        self.assertEqual(res["status"], "error", "部分失败不应报 ok")
        self.assertTrue(res["folded"], "已成功的部分要报告")
        self.assertTrue(res["failed"], "失败的部分要报告")


class MergeExecRealAdviceTest(unittest.TestCase):
    """真跑一次判据（慢，默认跳过）。

    其余用例注入判据是为了速度；这条确认"不注入时确实会自己重算"，
    也就是生产路径那道防误删护栏真的接上了。
    """

    @unittest.skipUnless(os.environ.get("SMS_SLOW_TESTS"), "设 SMS_SLOW_TESTS=1 才跑")
    def test_real_scan_rejects_bogus_group(self):
        tmp = Path(tempfile.mkdtemp(prefix="merge-real-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        _make_skill(tmp, "grafana-dashboard", "管理 Grafana 仪表盘。" * 3)
        res = skill_merge_exec.merge_group(
            "grafana-dashboard", ["no-such-skill"], skills_dir=str(tmp))
        self.assertEqual(res["status"], "error",
                         "不注入时必须自己重算判据并拒绝不成立的组")


if __name__ == "__main__":
    unittest.main()
