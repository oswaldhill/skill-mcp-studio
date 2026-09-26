import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from mcp_entry_removal import remove_class, remove_entries  # noqa: E402
from mcp_fixer import remove_legacy_mcp_tool, remove_mcp_entries_tool  # noqa: E402

URL = "https://hermes.example/mcp"


def tool(path, **over):
    data = {
        "name": "WorkBuddy",
        "config_path": str(path),
        "format": "json",
        "mcp_key_path": ["mcpServers"],
        "fix_supported": True,
    }
    data.update(over)
    return data


class RemoveArbitraryEntriesTest(unittest.TestCase):
    def test_removes_named_entry_and_keeps_rest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text(
                json.dumps(
                    {
                        "theme": "dark",
                        "mcpServers": {
                            "hermes": {"url": URL},
                            "my-mcp": {"url": "https://example.internal/mcp"},
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            result = remove_mcp_entries_tool(tool(path), ["my-mcp"])

            self.assertEqual(result["status"], "updated")
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("my-mcp", updated["mcpServers"])
            self.assertIn("hermes", updated["mcpServers"])
            self.assertEqual(updated["theme"], "dark")

    def test_backup_contains_original_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            original = '{"mcpServers":{"my-mcp":{"url":"https://x.example/mcp"}}}\n'
            path.write_text(original, encoding="utf-8")

            result = remove_mcp_entries_tool(tool(path), ["my-mcp"])

            self.assertEqual(result["status"], "updated")
            self.assertTrue(result["backup"])
            self.assertEqual(Path(result["backup"]).read_text(encoding="utf-8"), original)

    def test_unknown_key_reports_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            original = '{"mcpServers":{"hermes":{"url":"https://h.example/mcp"}}}\n'
            path.write_text(original, encoding="utf-8")

            result = remove_mcp_entries_tool(tool(path), ["nope"])

            self.assertEqual(result["status"], "unchanged")
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_parse_failure_leaves_file_untouched(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            original = "{ not json"
            path.write_text(original, encoding="utf-8")

            result = remove_mcp_entries_tool(tool(path), ["my-mcp"])

            self.assertEqual(result["status"], "error")
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_missing_file_and_unsupported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "absent.json"
            self.assertEqual(remove_mcp_entries_tool(tool(path), ["x"])["status"], "missing")

            real = Path(temp_dir) / "mcp.json"
            real.write_text('{"mcpServers":{}}\n', encoding="utf-8")
            unsupported = tool(real, fix_supported=False)
            self.assertEqual(remove_mcp_entries_tool(unsupported, ["x"])["status"], "unsupported")

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            original = '{"mcpServers":{"my-mcp":{}}}\n'
            path.write_text(original, encoding="utf-8")

            result = remove_mcp_entries_tool(tool(path), ["my-mcp"], dry_run=True)

            self.assertEqual(result["status"], "dry-run")
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_toml_section_removal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            path.write_text(
                f'[mcp_servers.hermes]\nurl = "{URL}"\n\n'
                '[mcp_servers.my-mcp]\nurl = "https://example.internal/mcp"\n',
                encoding="utf-8",
            )
            cfg = tool(path, name="Codex", format="toml", mcp_key_path=["mcp_servers"])

            result = remove_mcp_entries_tool(cfg, ["my-mcp"])

            self.assertEqual(result["status"], "updated")
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("[mcp_servers.my-mcp]", text)
            self.assertIn("[mcp_servers.hermes]", text)


class LegacyCompatibilityTest(unittest.TestCase):
    """legacy 包装必须与新原语共用一条实现，且消息逐字不变。"""

    def test_legacy_updated_message_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text(
                '{"mcpServers":{"hermes":{"url":"https://h.example/mcp"},'
                '"ai-memory":{"command":"legacy"}}}\n',
                encoding="utf-8",
            )
            expected = {"legacy_names": ["ai-memory"]}

            result = remove_legacy_mcp_tool(tool(path), expected)

            self.assertEqual(result["status"], "updated")
            self.assertEqual(result["message"], "旧通道条目已移除并校验通过")

    def test_legacy_unchanged_message_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text('{"mcpServers":{"hermes":{}}}\n', encoding="utf-8")

            result = remove_legacy_mcp_tool(tool(path), {"legacy_names": ["ai-memory"]})

            self.assertEqual(result["status"], "unchanged")
            self.assertEqual(result["message"], "没有残留的旧通道条目")

    def test_legacy_dry_run_message_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text('{"mcpServers":{"ai-memory":{}}}\n', encoding="utf-8")

            result = remove_legacy_mcp_tool(
                tool(path), {"legacy_names": ["ai-memory"]}, dry_run=True
            )

            self.assertEqual(result["status"], "dry-run")
            self.assertEqual(result["message"], "将移除旧通道条目")


class RemovalOrchestrationTest(unittest.TestCase):
    """编排层：分类挑 key、高风险门、attach 声明同步、空声明拒绝。

    **fixture 说明（对计划的一处补齐，不是放宽断言）：** 计划原文的 ``_config``
    只造 ``mcp_tools`` + ``profiles``，没有 ``profile_sources``。而 attached 删除
    路径要把 ``client_mcp_attach`` 落盘到 overlay，走的是
    ``endpoint_store.set_client_attach`` → ``_write_target``；没有
    ``profile_sources`` 时它直接返回 ``{"status": "error", "message": "no
    profile_sources configured"}``，``remove_entries`` 会以 ``status == "error"``
    结束、``attach_updated`` 恒为空——``test_attached_removal_*`` 永远不可能通过。
    故这里在用例的临时目录里造一个真实的 overlay 目标文件并声明为
    ``profile_sources``：写入目标真实存在，断言强度与计划完全一致。
    """

    def _config(self, path, *, attach=None, app_bundles=None):
        overlay = Path(path).parent / "local-overlay.yaml"
        if not overlay.exists():
            overlay.write_text("{}\n", encoding="utf-8")
        tool_entry = {
            "name": "Codex",
            "aliases": ["codex"],
            "config_path": str(path),
            "format": "toml",
            "mcp_key_path": ["mcp_servers"],
            "fix_supported": True,
            "mcp_attach": attach if attach is not None else ["K8s-uat", "hermes-home"],
        }
        if app_bundles:
            tool_entry["app_bundles"] = app_bundles
        return {
            "mcp_tools": [tool_entry],
            "profiles": {
                "K8s-uat": {"name": "K8s-uat", "url": "https://k8s.example/mcp"},
                "hermes-home": {"name": "hermes", "url": "https://hermes.example/mcp"},
            },
            "profile_sources": [str(overlay)],
        }

    def _write(self, temp_dir):
        path = Path(temp_dir) / "config.toml"
        path.write_text(
            f'[mcp_servers.hermes]\nurl = "{URL}"\n\n'
            '[mcp_servers.K8s-uat]\nurl = "https://k8s.example/mcp"\n\n'
            '[mcp_servers.my-mcp]\nurl = "https://example.internal/mcp"\n',
            encoding="utf-8",
        )
        return path

    def test_unmanaged_removal_touches_no_declaration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write(temp_dir)
            config = self._config(path)

            result = remove_entries(config, "Codex", ["my-mcp"])

            self.assertEqual(result["status"], "updated")
            self.assertNotIn("[mcp_servers.my-mcp]", path.read_text(encoding="utf-8"))
            self.assertEqual(result["attach_updated"], [])
            self.assertEqual(
                config["mcp_tools"][0]["mcp_attach"], ["K8s-uat", "hermes-home"]
            )

    def test_attached_removal_drops_endpoint_key_not_config_key(self):
        """配置 key 是 'hermes'，声明 key 是 'hermes-home'，必须经 endpoint_key 回映。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write(temp_dir)
            config = self._config(path)

            result = remove_entries(config, "Codex", ["hermes"])

            self.assertEqual(result["status"], "updated")
            self.assertEqual(result["attach_updated"], ["hermes-home"])
            self.assertNotIn("[mcp_servers.hermes]", path.read_text(encoding="utf-8"))
            # 声明同步必须真的落到 overlay（证明 fixture 的写入目标有效，而非空转）。
            stored = yaml.safe_load(
                (Path(temp_dir) / "local-overlay.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(stored["client_mcp_attach"]["Codex"], ["K8s-uat"])

    def test_high_risk_entry_is_refused_without_force(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            original = (
                '[mcp_servers.node_repl]\n'
                'command = "/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node_repl"\n'
            )
            path.write_text(original, encoding="utf-8")
            config = self._config(path, app_bundles=["/Applications/ChatGPT.app"])

            result = remove_entries(config, "Codex", ["node_repl"])

            self.assertEqual(result["status"], "refused")
            self.assertIn("node_repl", result["high_risk"][0]["key"])
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_empty_declaration_is_refused_before_any_write(self):
        """删掉最后一个 attached 条目会让声明变空 → 必须整体拒绝且不落盘。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            original = f'[mcp_servers.hermes]\nurl = "{URL}"\n'
            path.write_text(original, encoding="utf-8")
            config = self._config(path, attach=["hermes-home"])

            result = remove_entries(config, "Codex", ["hermes"])

            self.assertEqual(result["status"], "refused")
            self.assertIn("空", result["message"])
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(config["mcp_tools"][0]["mcp_attach"], ["hermes-home"])
            # 「写盘之前拒绝」也包括 overlay：声明文件必须一个字节都没动。
            self.assertEqual(
                (Path(temp_dir) / "local-overlay.yaml").read_text(encoding="utf-8"),
                "{}\n",
            )

    def test_remove_class_unmanaged_skips_high_risk_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            path.write_text(
                '[mcp_servers.my-mcp]\nurl = "https://example.internal/mcp"\n\n'
                '[mcp_servers.bundled]\n'
                'command = "/Applications/ChatGPT.app/Contents/Resources/x"\n',
                encoding="utf-8",
            )
            config = self._config(path, app_bundles=["/Applications/ChatGPT.app"])

            result = remove_class(config, "Codex", "unmanaged")

            self.assertEqual(result["status"], "updated")
            self.assertIn("my-mcp", result["removed"])
            self.assertEqual([h["key"] for h in result["skipped_high_risk"]], ["bundled"])
            self.assertIn("[mcp_servers.bundled]", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
