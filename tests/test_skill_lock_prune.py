"""登记残留清理（``--prune-skill-lock``）的门禁断言。

背景：检查更新弹框曾写「可在技能行删除」，但这条路对登记残留根本走不通——
``--delete-skill`` 要求技能目录存在（``soft_delete_skill`` 第一句就是
``os.path.isdir``），而技能列表又是按磁盘目录渲染的，残留行压根不会出现。
于是新增 ``--prune-skill-lock`` 作为唯一出口：只删「登记表有、统一库无目录」
的条目，改前备份整份登记表。

这批断言守 7 类事实：

1. ``dry-run`` 一个字节都不改，也不生成备份；
2. 只删磁盘上确实没有的登记，仍在磁盘的登记保留；
3. ``dismissed`` / ``lastSelectedAgents`` 等非 ``skills`` 字段原样保留；
4. 改前备份整份登记表，备份内容等于改前原文；
5. 无残留时返回 ``nothing-to-prune``，不制造空备份；
6. 登记表缺失 / JSON 损坏时如实报错，不静默当成「没有残留」；
7. CLI 端到端：``--format json`` 的字段、``--dry-run`` 不落盘、退出码。

GUI 契约（按钮 / 事件名 / CLI 参数 / Rust 白名单）另见文件末的
``TestPruneSkillLockGuiContract`` —— 它守的是「这个能力在界面上真的可达」，
删掉按钮或漏登记白名单都会让它失败。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import skill_market as sm  # noqa: E402

_TS = "20260101-000000"


def _write_lock(path: Path, skills: dict, **extra) -> None:
    payload = {"version": 1, "skills": skills, **extra}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class _Fixture:
    """一个临时 HOME：``.agents/.skill-lock.json`` + ``.skills-manager/skills/``。"""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.lock = self.root / ".agents" / ".skill-lock.json"
        self.skills = self.root / ".skills-manager" / "skills"
        self.skills.mkdir(parents=True, exist_ok=True)

    def on_disk(self, *names: str) -> None:
        for name in names:
            (self.skills / name).mkdir(parents=True, exist_ok=True)

    def cleanup(self) -> None:
        self._tmp.cleanup()


class TestMissingRegistrations(unittest.TestCase):
    """只读探测：口径必须与 check_updates 的 missing 同源。"""

    def setUp(self) -> None:
        self.fx = _Fixture()
        self.addCleanup(self.fx.cleanup)

    def test_lists_only_registered_but_absent(self):
        _write_lock(self.fx.lock, {
            "alpha": {"sourceType": "github"},
            "ghost-a": {"sourceType": "github"},
            "ghost-b": {"sourceType": "github"},
        })
        self.fx.on_disk("alpha")

        info = sm.missing_registrations(self.fx.lock, self.fx.skills)

        self.assertEqual(info["names"], ["ghost-a", "ghost-b"])
        self.assertEqual(info["registered"], 3)
        self.assertEqual(info["lock_path"], str(self.fx.lock))

    def test_unregistered_disk_skill_is_not_a_ghost(self):
        # 磁盘有目录、lock 无登记 = 「未登记」，不属于残留（不能被删）。
        _write_lock(self.fx.lock, {})
        self.fx.on_disk("only-on-disk")

        info = sm.missing_registrations(self.fx.lock, self.fx.skills)

        self.assertEqual(info["names"], [])
        self.assertEqual(info["registered"], 0)

    def test_probe_does_not_touch_file(self):
        _write_lock(self.fx.lock, {"ghost": {"sourceType": "github"}})
        before = self.fx.lock.read_bytes()

        sm.missing_registrations(self.fx.lock, self.fx.skills)

        self.assertEqual(self.fx.lock.read_bytes(), before)


class TestPruneMissingRegistrations(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Fixture()
        self.addCleanup(self.fx.cleanup)

    def test_dry_run_changes_nothing(self):
        _write_lock(self.fx.lock, {
            "keep": {"sourceType": "github"},
            "ghost": {"sourceType": "github"},
        })
        self.fx.on_disk("keep")
        before = self.fx.lock.read_bytes()

        res = sm.prune_missing_registrations(self.fx.lock, self.fx.skills, dry_run=True)

        self.assertEqual(res["status"], "dry-run")
        self.assertEqual(res["removed"], 1)
        self.assertEqual(res["kept"], 1)
        self.assertEqual(res["names"], ["ghost"])
        self.assertEqual(self.fx.lock.read_bytes(), before)
        # dry-run 不落备份：不能留下一个「备份了但没改」的误导性文件。
        self.assertEqual(list(self.fx.lock.parent.glob("*.bak-*")), [])

    def test_prune_removes_only_ghosts(self):
        _write_lock(self.fx.lock, {
            "keep-a": {"sourceType": "github"},
            "keep-b": {"sourceType": "skills.sh"},
            "ghost-a": {"sourceType": "github"},
            "ghost-b": {"sourceType": "github"},
        })
        self.fx.on_disk("keep-a", "keep-b")

        res = sm.prune_missing_registrations(self.fx.lock, self.fx.skills)

        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["removed"], 2)
        self.assertEqual(res["kept"], 2)
        remaining = _read_json(self.fx.lock)["skills"]
        self.assertEqual(sorted(remaining), ["keep-a", "keep-b"])
        # 保留项的内容不能被「顺手归一化」掉。
        self.assertEqual(remaining["keep-b"]["sourceType"], "skills.sh")

    def test_other_top_level_fields_survive(self):
        _write_lock(
            self.fx.lock,
            {"ghost": {"sourceType": "github"}},
            dismissed={"some-skill": {"at": "2026-01-01"}},
            lastSelectedAgents=["claude-code", "cursor"],
        )

        sm.prune_missing_registrations(self.fx.lock, self.fx.skills)

        after = _read_json(self.fx.lock)
        self.assertEqual(after["skills"], {})
        self.assertEqual(after["dismissed"], {"some-skill": {"at": "2026-01-01"}})
        self.assertEqual(after["lastSelectedAgents"], ["claude-code", "cursor"])
        self.assertEqual(after["version"], 1)

    def test_backup_matches_pre_prune_content(self):
        _write_lock(self.fx.lock, {"ghost": {"sourceType": "github"}})
        before = self.fx.lock.read_bytes()

        res = sm.prune_missing_registrations(self.fx.lock, self.fx.skills)

        backup = Path(res["backup"])
        self.assertTrue(backup.is_file(), "必须留下备份")
        self.assertEqual(backup.read_bytes(), before, "备份必须是改前原文")
        self.assertIn(".bak-", backup.name)

    def test_nothing_to_prune_makes_no_backup(self):
        _write_lock(self.fx.lock, {"keep": {"sourceType": "github"}})
        self.fx.on_disk("keep")

        res = sm.prune_missing_registrations(self.fx.lock, self.fx.skills)

        self.assertEqual(res["status"], "nothing-to-prune")
        self.assertEqual(res["removed"], 0)
        self.assertEqual(res["backup"], "")
        self.assertEqual(list(self.fx.lock.parent.glob("*.bak-*")), [])

    def test_missing_lock_reports_error(self):
        res = sm.prune_missing_registrations(self.fx.lock, self.fx.skills)

        self.assertEqual(res["status"], "error")
        self.assertIn("未找到来源登记", res["message"])
        self.assertFalse(self.fx.lock.exists(), "报错时不得创建登记表")

    def test_corrupt_lock_reports_error_and_is_left_alone(self):
        self.fx.lock.parent.mkdir(parents=True, exist_ok=True)
        self.fx.lock.write_text("{ not json", encoding="utf-8")
        before = self.fx.lock.read_bytes()

        res = sm.prune_missing_registrations(self.fx.lock, self.fx.skills)

        self.assertEqual(res["status"], "error")
        self.assertEqual(self.fx.lock.read_bytes(), before,
                         "解析失败时不能覆盖或删除用户文件")


class TestPruneSkillLockCli(unittest.TestCase):
    """端到端：GUI 就是直接 JSON.parse 这条命令的 stdout。"""

    def setUp(self) -> None:
        self.fx = _Fixture()
        self.addCleanup(self.fx.cleanup)
        self.env = dict(os.environ)
        self.env["SKILL_MCP_STUDIO_HOME"] = str(self.fx.root)
        # 隔离掉真实 config.yaml，避免用例受本机配置影响。
        self.env["PYTHONPATH"] = str(ROOT / "core")

    def _run(self, *args: str):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scan.py"), *args],
            cwd=str(ROOT), env=self.env, capture_output=True, text=True, timeout=120,
        )
        return proc

    def test_json_dry_run_then_apply(self):
        _write_lock(self.fx.lock, {
            "keep": {"sourceType": "github"},
            "ghost-a": {"sourceType": "github"},
            "ghost-b": {"sourceType": "github"},
        })
        self.fx.on_disk("keep")
        before = self.fx.lock.read_bytes()

        dry = self._run("--prune-skill-lock", "--dry-run", "--format", "json")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        payload = json.loads(dry.stdout)
        self.assertEqual(payload["status"], "dry-run")
        self.assertEqual(payload["removed"], 2)
        self.assertEqual(sorted(payload["names"]), ["ghost-a", "ghost-b"])
        self.assertEqual(self.fx.lock.read_bytes(), before, "dry-run 不得落盘")

        applied = self._run("--prune-skill-lock", "--format", "json")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        done = json.loads(applied.stdout)
        self.assertEqual(done["status"], "ok")
        self.assertEqual(done["removed"], 2)
        self.assertTrue(Path(done["backup"]).is_file())
        self.assertEqual(sorted(_read_json(self.fx.lock)["skills"]), ["keep"])

    def test_json_nothing_to_prune_exit_zero(self):
        _write_lock(self.fx.lock, {"keep": {"sourceType": "github"}})
        self.fx.on_disk("keep")

        proc = self._run("--prune-skill-lock", "--format", "json")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["status"], "nothing-to-prune")


class TestPruneSkillLockGuiContract(unittest.TestCase):
    """界面可达性：按钮、事件分发、CLI 参数、Rust 白名单必须同时在。

    这条断言是**反向验证过的**：删掉 dashboard.html 里的按钮（或 lib.rs 的
    白名单项）后本用例立刻失败——只保留其中一侧，用户点了按钮也只会收到
    「子命令不在白名单内」。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.dashboard = (ROOT / "gui" / "dashboard.html").read_text(encoding="utf-8")
        cls.scan = (ROOT / "scan.py").read_text(encoding="utf-8")
        cls.lib_rs = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
        cls.design = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")

    def test_button_exists_in_market_sources_card(self):
        card_start = self.dashboard.index('id="market-sources-card"')
        card = self.dashboard[card_start:card_start + 2000]
        self.assertIn('data-action="prune-skill-lock"', card,
                      "「清理登记残留」按钮必须落在市场源卡片内")

    def test_handler_is_wired(self):
        self.assertIn('a === "prune-skill-lock"', self.dashboard,
                      "事件分发里必须接上 prune-skill-lock")
        self.assertIn("function openPruneSkillLockModal", self.dashboard,
                      "缺少 openPruneSkillLockModal 实现")
        # 先 dry-run 再确认：直接执行会把「删了多少」变成事后才知道。
        self.assertIn('"--prune-skill-lock", "--dry-run", "--format", "json"',
                      self.dashboard,
                      "点击后必须先用 dry-run 拿清单，不能直接落盘")

    def test_cli_flag_and_rust_whitelist(self):
        self.assertIn('"--prune-skill-lock"', self.scan, "scan.py 缺少参数定义")
        self.assertIn('"--prune-skill-lock"', self.lib_rs,
                      "Rust run_cli 白名单缺少 --prune-skill-lock（GUI 调用会被拒）")

    def test_design_spec_registers_the_control(self):
        # 规范轨：DESIGN.md 必须登记这个控件，否则下一个人不知道它存在。
        self.assertIn("prune-skill-lock", self.design,
                      "docs/DESIGN.md 未登记「清理登记残留」控件")


if __name__ == "__main__":
    unittest.main()
