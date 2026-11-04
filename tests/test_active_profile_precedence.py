"""活动端点（active_profile）写入必须落到「真正生效」的那一层。

## 实测缺陷（2026-11-04）

`--set-active-profile hermes-home` 报告 `✅ active_profile = hermes-home`，
但 `load_config()` 读回的仍是空串 —— 命令成功、配置没变。

根因是两个函数的**方向相反**：

- ``profile_loader.apply_profile_sources`` 按 ``profile_sources`` 顺序合并，
  **后面的文件覆盖前面的**（docs 里写的是「later sources win」）；
- ``config_store._overlay_target`` 却返回**第一个**存在的覆盖层。

于是写入落到优先级最低的文件，被后面的文件盖掉。本机实测：写进
``~/.skills-manager/profiles.local.yaml``，而 ``data/local_overrides.yaml``
里的 `active_profile: ''` 优先级更高，把空值又盖了回去。

## 判据

1. 目标必须是 ``profile_sources`` 里**最后一个存在的**文件（优先级最高）；
2. 写入后 ``load_config`` 必须真的读到新值（端到端，不只是「函数返回 ok」）；
3. 已有值仍保留在其它层时，必须清掉那层的 ``active_profile``，否则下一层
   的文件改动会静默复活旧值。
"""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from config_store import _overlay_target, set_active_profile  # noqa: E402
from scanner import load_config  # noqa: E402


class OverlayTargetPrecedenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.low = self.dir / "low.yaml"      # 先列 → 优先级低
        self.high = self.dir / "high.yaml"    # 后列 → 优先级高
        self.low.write_text(yaml.safe_dump({"active_profile": ""}), encoding="utf-8")
        self.high.write_text(yaml.safe_dump({"marker": 1}), encoding="utf-8")
        self.trunk = self.dir / "config.yaml"
        self.trunk.write_text(
            "schema_version: 2\n"
            "active_profile: trunk-endpoint\n"
            "profile_sources:\n"
            f"  - {self.low}\n"
            f"  - {self.high}\n"
            "profiles:\n"
            "  trunk-endpoint: {name: trunk, url: 'https://t/mcp'}\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_target_is_the_highest_priority_source(self):
        self.assertEqual(
            _overlay_target(str(self.trunk)), str(self.high),
            "写入目标必须是 profile_sources 里最后一个存在的文件（合并时后写者胜）",
        )

    def test_single_source_still_works(self):
        only = self.dir / "only.yaml"
        only.write_text("{}\n", encoding="utf-8")
        trunk = self.dir / "single.yaml"
        trunk.write_text(
            f"profile_sources:\n  - {only}\nprofiles: {{}}\n", encoding="utf-8"
        )
        self.assertEqual(_overlay_target(str(trunk)), str(only))

    def test_falls_back_to_local_overrides_when_no_source_exists(self):
        trunk = self.dir / "none.yaml"
        trunk.write_text(
            f"profile_sources:\n  - {self.dir}/missing.yaml\nprofiles: {{}}\n",
            encoding="utf-8",
        )
        self.assertIn("local_overrides", _overlay_target(str(trunk)))


class SetActiveProfileTakesEffectTest(unittest.TestCase):
    """端到端：写完必须能被 load_config 读到（本缺陷正是「写成功但读不到」）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.low = self.dir / "low.yaml"
        self.high = self.dir / "high.yaml"
        self.low.write_text(yaml.safe_dump({"active_profile": ""}), encoding="utf-8")
        self.high.write_text("{}\n", encoding="utf-8")
        self.trunk = self.dir / "config.yaml"
        self.trunk.write_text(
            "schema_version: 2\n"
            "active_profile: generic-http\n"
            "profile_sources:\n"
            f"  - {self.low}\n"
            f"  - {self.high}\n"
            "profiles:\n"
            "  hermes-home: {name: hermes, url: 'https://h/mcp'}\n"
            "  generic-http: {name: my-mcp, url: 'https://example.internal/mcp'}\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_written_value_is_what_config_loads(self):
        result = set_active_profile(str(self.trunk), "hermes-home")
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(
            load_config(str(self.trunk)).get("active_profile"), "hermes-home",
            "命令报告成功但 load_config 读回的不是新值 —— 写到了被覆盖的层",
        )

    def test_shadowing_value_in_lower_layer_is_cleared(self):
        # 低优先级层留着 active_profile: ''，写完必须顺手清掉，
        # 否则那个文件一变（哪怕只改 auto_discover），旧空值就会复活。
        set_active_profile(str(self.trunk), "hermes-home")
        low = yaml.safe_load(self.low.read_text(encoding="utf-8"))
        self.assertNotIn(
            "active_profile", low,
            "低优先级层仍留有 active_profile，会遮蔽新写入的值",
        )

    def test_endpoint_declared_in_overlay_is_accepted(self):
        # 端点库条目几乎都住在覆盖层里：只查主干会把真实可用的端点判成「不存在」。
        self.high.write_text(
            yaml.safe_dump({"profiles": {"overlay-endpoint": {"name": "o", "url": "https://o/mcp"}}}),
            encoding="utf-8",
        )
        result = set_active_profile(str(self.trunk), "overlay-endpoint")
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(load_config(str(self.trunk)).get("active_profile"), "overlay-endpoint")

    def test_soft_deleted_endpoint_is_rejected(self):
        # null 是软删除标记，不能当成可选端点。
        self.high.write_text(
            yaml.safe_dump({"profiles": {"gone": None}}), encoding="utf-8"
        )
        result = set_active_profile(str(self.trunk), "gone")
        self.assertEqual(result["status"], "error")

    def test_unknown_key_is_rejected_without_writing(self):
        before = self.high.read_text(encoding="utf-8")
        result = set_active_profile(str(self.trunk), "no-such-endpoint")
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.high.read_text(encoding="utf-8"), before)

    def test_clearing_writes_empty_to_the_effective_layer(self):
        set_active_profile(str(self.trunk), "hermes-home")
        set_active_profile(str(self.trunk), "")
        self.assertEqual(load_config(str(self.trunk)).get("active_profile"), "")


if __name__ == "__main__":
    unittest.main()
