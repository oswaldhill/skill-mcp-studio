"""回归：``unified_name`` 的作用域只能是**统一端点**（2026-10-08 实测事故）。

背景
----
``unified_name`` 是「统一 Hermes 端点」在该客户端配置里的条目别名 —— config.yaml
里写得很清楚：「统一端点用独立 key 写入，避免覆盖本地桥」。它由**客户端级**字段
声明，但端点库里通常不止一个端点（本机：``K8s-uat`` 与 ``hermes-home``）。

事故
----
两处代码都把别名当成了「该客户端所有端点的条目名」：

1. ``combined_checker.check_agents``：``tool.get("unified_name") or expected_name``
   → 审计 ``K8s-uat`` 时也去查 ``hermes-unified``，读到的是 hermes 的 URL，
   URL 校验必然失败，把**已正确接入**的端点判成「未配置」。
2. ``mcp_fixer.fix_mcp_tool``：``tool.get("unified_name") or expected.get("name")``
   → ``--fix-mcp`` 遍历端点库时，每个端点都写进同一个 key、互相覆盖，最终只剩
   最后一个端点的 URL。

两者叠加的结果，就是界面上长期停在 ``1/2``（用户原话：「执行了修复，但仍 1/2」）。
另有一处同源缺陷：``mcp_inventory`` 的 ``canonical_name`` 分支只标 ``attached``、
漏设 ``endpoint_key``，而 ``observed_endpoint_keys`` 只读该字段，于是用别名写入的
条目对附件审计**不可见**，误报「声明要挂却没挂」（实测 OpenCode 的 hermes-home）。

本文件锁定三处修复。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from mcp_fixer import fix_mcp_clients  # noqa: E402
from mcp_inventory import attachment_consistency, inventory_client  # noqa: E402


def _client(path, unified="hermes-unified"):
    value = {
        "name": "Test Client",
        "config_path": str(path),
        "format": "json",
        "mcp_key_path": ["mcpServers"],
        "fix_supported": True,
        "install": {"app_bundles": ["/nonexistent"], "config_paths": [str(path)]},
    }
    if unified is not None:
        value["unified_name"] = unified
    return value


def _endpoints():
    """端点库：key 与正典名不同（hermes-home 的正典名是 hermes），贴近本机真实配置。"""
    return [
        {"key": "K8s-uat", "name": "K8s", "url": "https://k8s.example.com/mcp"},
        {"key": "hermes-home", "name": "hermes", "url": "https://hermes.example.com/mcp"},
    ]


def _config(path, active="hermes-home"):
    return {
        "schema_version": 2,
        "active_profile": active,
        "profiles": {
            "K8s-uat": {"name": "K8s", "url": "https://k8s.example.com/mcp"},
            "hermes-home": {"name": "hermes", "url": "https://hermes.example.com/mcp"},
        },
        "mcp_tools": [_client(path)],
    }


class FixWriteScopeTest(unittest.TestCase):
    """写入侧：每个端点必须写进**自己的** key，别名只留给统一端点。"""

    def test_each_endpoint_written_under_its_own_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text("{}", encoding="utf-8")
            config = _config(path)
            with patch("config_store.load_discovered", return_value=[]), \
                    patch("mcp_fixer.detect_installation", return_value={"installed": True}):
                results = fix_mcp_clients(config, client="Test Client")

            self.assertEqual(len(results), 2)
            data = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
            # 关键断言：K8s 端点绝不能被写进 hermes-unified（那正是互相覆盖的成因）
            self.assertIn("K8s", data)
            self.assertEqual(data["K8s"]["url"], "https://k8s.example.com/mcp")
            self.assertEqual(data["hermes-unified"]["url"], "https://hermes.example.com/mcp")

    def test_both_endpoints_coexist_instead_of_collapsing(self):
        """反证：旧实现下两个端点会塌缩成一个 key，这里锁定「两个都在」。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text("{}", encoding="utf-8")
            config = _config(path)
            with patch("config_store.load_discovered", return_value=[]), \
                    patch("mcp_fixer.detect_installation", return_value={"installed": True}):
                fix_mcp_clients(config, client="Test Client")
            data = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
            self.assertEqual(sorted(data.keys()), ["K8s", "hermes-unified"])

    def test_single_profile_path_keeps_alias_for_active_endpoint(self):
        """``--profile`` 指向统一端点时别名必须保留，否则会覆盖本地 hermes 桥。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text(
                '{"mcpServers": {"hermes": {"command": "/usr/bin/python3"}}}',
                encoding="utf-8",
            )
            profile = {"name": "hermes", "url": "https://hermes.example.com/mcp"}
            config = _config(path)
            config["profiles"] = {"hermes-home": profile}
            with patch("config_store.load_discovered", return_value=[]), \
                    patch("mcp_fixer.detect_installation", return_value={"installed": True}):
                results = fix_mcp_clients(
                    config, profile=profile, profile_key="hermes-home", client="Test Client"
                )
            self.assertEqual(results[0]["status"], "updated")
            data = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
            self.assertEqual(data["hermes-unified"]["url"], "https://hermes.example.com/mcp")
            # 本地 stdio 桥原样保留（unified_name 的设计初衷）
            self.assertEqual(data["hermes"]["command"], "/usr/bin/python3")

    def test_single_profile_path_for_non_active_endpoint_uses_own_name(self):
        """``--profile`` 指向**非**统一端点时不得套用别名。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text("{}", encoding="utf-8")
            profile = {"name": "K8s", "url": "https://k8s.example.com/mcp"}
            config = _config(path)
            config["profiles"] = {"K8s-uat": profile}
            with patch("config_store.load_discovered", return_value=[]), \
                    patch("mcp_fixer.detect_installation", return_value={"installed": True}):
                fix_mcp_clients(
                    config, profile=profile, profile_key="K8s-uat", client="Test Client"
                )
            data = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
            self.assertIn("K8s", data)
            self.assertNotIn("hermes-unified", data)


class InventoryCanonicalScopeTest(unittest.TestCase):
    """清单侧：用别名写入的条目必须关联回统一端点，否则会被误报「未挂载」。"""

    def _write(self, temp_dir, servers):
        path = Path(temp_dir) / "mcp.json"
        path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
        return path

    def test_canonical_entry_gets_endpoint_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write(temp_dir, {
                "K8s": {"url": "https://k8s.example.com/mcp"},
                "hermes-unified": {"url": "https://hermes.example.com/mcp"},
            })
            entries = inventory_client(
                _client(path),
                endpoint_entries=_endpoints(),
                legacy_names=[],
                canonical_endpoint_key="hermes-home",
            )
            entry = next(e for e in entries if e.key == "hermes-unified")
            self.assertEqual(entry.classification, "attached")
            self.assertEqual(entry.endpoint_key, "hermes-home")
            # 两个端点都应被审计认作「已挂载」——这就是界面上的 2/2
            consistency = attachment_consistency(entries, ["K8s-uat", "hermes-home"])
            self.assertEqual(consistency["observed"], ["K8s-uat", "hermes-home"])
            self.assertEqual(consistency["missing"], [])

    def test_local_bridge_still_classified_by_endpoint_name(self):
        """本地 hermes 桥（无 url，走 stdio）仍按正典名 hermes 归到 hermes-home。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write(temp_dir, {"hermes": {"command": "/usr/bin/python3"}})
            entries = inventory_client(
                _client(path),
                endpoint_entries=_endpoints(),
                legacy_names=[],
                canonical_endpoint_key="hermes-home",
            )
            entry = next(e for e in entries if e.key == "hermes")
            self.assertEqual(entry.classification, "attached")
            self.assertEqual(entry.endpoint_key, "hermes-home")

    def test_without_canonical_key_entry_has_no_endpoint_key(self):
        """未提供统一端点 key 时不得凭空关联（保持既有语义）。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write(temp_dir, {
                "hermes-unified": {"url": "https://hermes.example.com/mcp"},
            })
            entries = inventory_client(
                _client(path),
                endpoint_entries=_endpoints(),
                legacy_names=[],
            )
            entry = next(e for e in entries if e.key == "hermes-unified")
            self.assertEqual(entry.classification, "attached")
            self.assertFalse(entry.endpoint_key)


class CurrentConfigUniformKeyTest(unittest.TestCase):
    """现行配置的约定：**全平台用端点自身的 name 作为 key**（2026-11-05 决定）。

    背景：Codex 与 OpenCode 曾声明 ``unified_name: hermes-unified``，起因是它们
    当时各有一条同名本地 stdio 桥。复核发现两处都已无该桥（Codex 的 hermes 段
    早已不在、OpenCode 从未接入），保留 renamed key 只会让同一端点在配置里
    出现两个名字。去掉后全平台统一为 ``hermes``。

    这条断言守的是「别再悄悄加回 unified_name」：一个人加了、另一个人没加，
    就会出现 Codex 叫 hermes-unified、VS Code 叫 hermes 的分裂。
    若将来确实需要（某客户端又要接本地桥），请同时更新本用例与 config.yaml 注释。
    """

    def setUp(self):
        from scanner import load_config

        self.config = load_config(str(ROOT / "config.yaml"))

    def test_no_client_declares_unified_name(self):
        offenders = [
            t.get("name")
            for t in self.config.get("mcp_tools") or []
            if t.get("unified_name")
        ]
        self.assertEqual(
            offenders,
            [],
            f"这些客户端又声明了 unified_name，会导致同一端点在配置里出现两个名字：{offenders}",
        )

    def test_no_client_declares_profile_level_legacy_names(self):
        # unified_name 的伴生物：本地桥以端点 name 存在时的 legacy 声明。
        offenders = [
            (t.get("name"), t.get("legacy_names"))
            for t in self.config.get("mcp_tools") or []
            if t.get("legacy_names")
        ]
        self.assertEqual(offenders, [], f"仍有客户端声明 legacy_names：{offenders}")

    def test_active_endpoint_writes_the_endpoint_name_everywhere(self):
        """统一端点写入每个客户端时都用端点 name，与是否设置了 active_profile 无关。

        这是「去掉 unified_name」的直接行为验证：把 active_profile 设成统一端点
        （原本会触发别名分支），写出的 key 仍必须是端点 name —— 否则不同客户端
        会因 active_profile 的状态得到不同 key。
        """
        import json
        import tempfile

        from mcp_fixer import fix_mcp_tool

        profile = {"name": "hermes", "url": "https://h.example.com/mcp"}
        with tempfile.TemporaryDirectory() as tmp:
            for fmt, key_path, initial in (
                ("json", ["mcpServers"], '{"mcpServers": {}}'),
                ("toml", ["mcp_servers"], ""),
            ):
                with self.subTest(fmt=fmt):
                    path = Path(tmp) / f"cfg.{fmt}"
                    path.write_text(initial, encoding="utf-8")
                    tool = {
                        "name": "X",
                        "config_path": str(path),
                        "format": fmt,
                        "mcp_key_path": key_path,
                    }
                    result = fix_mcp_tool(tool, profile, use_unified_name=True)
                    self.assertEqual(result["status"], "updated", result)
                    body = path.read_text(encoding="utf-8")
                    self.assertIn("hermes", body)
                    self.assertNotIn("hermes-unified", body)
                    if fmt == "json":
                        self.assertIn("hermes", json.loads(body)["mcpServers"])


if __name__ == "__main__":
    unittest.main()
