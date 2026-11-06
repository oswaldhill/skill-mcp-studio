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


class TrunkHasNoPhantomEndpointTest(unittest.TestCase):
    """主干 config.yaml 不得残留「已被软删除、却仍能复活」的占位端点。

    2026-11-05 实测隐患：``generic-http``（https://example.internal/mcp）在端点库里
    早已是 null（软删除标记），合并后根本不出现 —— 但主干 ``profiles`` 里那份还在。
    一旦 ``data/local_overrides.yaml`` 被清空（换机、重装、清理个人数据），
    它会**重新成为活动端点**，把所有客户端的 MCP 配置指向一个不存在的地址。

    两条判据：
    1. 主干 profiles 必须是**合法的空映射**（`{}`）或只含真实端点 —— 留空会解析成
       null，而 profile_loader 要求非空映射；写成空映射是唯一能表达
       「端点全部由覆盖层提供」又不炸加载的形态。
    2. 主干里不得出现指向占位域名的端点（example.* / .internal / .local 等）。
    """

    TRUNK = ROOT / "config.yaml"
    PHANTOM_HOSTS = ("example.internal", "example.com", "localhost", "127.0.0.1")

    def setUp(self):
        self.config = yaml.safe_load(self.TRUNK.read_text(encoding="utf-8"))
        self.profiles = self.config.get("profiles")

    def test_profiles_is_a_mapping_not_null(self):
        # 留空（只有注释）会解析成 None，加载期必炸；必须是 {} 或真实映射。
        self.assertIsInstance(
            self.profiles, dict,
            "主干 profiles 必须是映射：留空会解析成 null，profile_loader 会抛"
            "「'profiles:' must be a non-empty mapping」",
        )

    def test_no_placeholder_endpoint_in_trunk(self):
        offenders = []
        for key, profile in (self.profiles or {}).items():
            url = str((profile or {}).get("url") or "")
            if any(host in url for host in self.PHANTOM_HOSTS):
                offenders.append(f"{key} -> {url}")
        self.assertEqual(
            offenders, [],
            "主干仍有占位端点：覆盖层一旦被清空，它会重新成为活动端点"
            "并把客户端指向不存在的地址：%r" % offenders,
        )

    def test_merged_config_still_has_endpoints(self):
        """删掉占位端点后，真实环境（覆盖层存在）仍必须解析出端点。"""
        from profile_loader import list_profiles
        from scanner import load_config

        # Trunk intentionally has no personal topology. Supply a declared fixture
        # overlay instead of depending on the developer's ~/.skills-manager data.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = dict(self.config)
            config["profile_sources"] = ["fixture-profiles.yaml"]
            (root / "config.yaml").write_text(yaml.safe_dump(config))
            (root / "fixture-profiles.yaml").write_text(yaml.safe_dump({
                "active_profile": "fixture-native",
                "profiles": {"fixture-native": {"name": "fixture-native",
                    "url": "https://mcp.example.test/mcp", "transport": "streamable-http"}}}))
            merged = list_profiles(load_config(str(root / "config.yaml")))
        self.assertTrue(merged, "声明的覆盖层未被合并")


if __name__ == "__main__":
    unittest.main()
