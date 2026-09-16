import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from mcp_fixer import (  # noqa: E402
    fix_mcp_clients,
    fix_mcp_tool,
    remove_legacy_mcp_tool,
)
from mcp_checker import load_mcp_servers  # noqa: E402


URL = "https://mcp.example.com/mcp"
EXPECTED = {"name": "hermes", "url": URL}


def tool(path, config_format="json", **overrides):
    value = {
        "name": "Test Client",
        "config_path": str(path),
        "format": config_format,
        "mcp_key_path": ["mcpServers"],
        "fix_supported": True,
        "install": {"config_paths": [str(path)]},
    }
    value.update(overrides)
    return value


class McpFixerTest(unittest.TestCase):
    def test_remove_legacy_json_preserves_canonical_and_unrelated_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            original = {
                "theme": "dark",
                "mcpServers": {
                    "hermes": {"url": URL},
                    "hermes-memory": {"command": "legacy"},
                    "ai-memory": {"command": "legacy-ai"},
                    "other": {"url": "https://other.example/mcp"},
                },
            }
            path.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")
            expected = {**EXPECTED, "legacy_names": ["hermes-memory", "ai-memory"]}

            result = remove_legacy_mcp_tool(tool(path), expected)

            self.assertEqual(result["status"], "updated")
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(updated["mcpServers"]["hermes"], {"url": URL})
            self.assertEqual(updated["mcpServers"]["other"], original["mcpServers"]["other"])
            self.assertNotIn("hermes-memory", updated["mcpServers"])
            self.assertNotIn("ai-memory", updated["mcpServers"])
            self.assertEqual(len(list(path.parent.glob("mcp.json.bak-*"))), 1)

    def test_remove_legacy_merges_tool_level_legacy_names(self):
        # OpenCode shape: the canonical entry carries a per-tool unified_name
        # ("hermes-unified") while the legacy stdio bridge occupies the plain
        # "hermes" name. The profile declares no legacy_names; the tool entry
        # does. Removal must honor the tool-level list without touching the
        # canonical or unrelated entries.
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "opencode.json"
            original = {
                "$schema": "https://opencode.ai/config.json",
                "mcp": {
                    "hermes": {
                        "type": "local",
                        "command": ["python3", "/home/u/.local/bin/hermes-bridge.py"],
                        "env": {"NAS_GATEWAY_URL": "http://nas.example:8642"},
                    },
                    "hermes-unified": {"url": URL},
                    "other": {"url": "https://other.example/mcp"},
                },
            }
            path.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")
            client = tool(path, "jsonc", mcp_key_path=["mcp"], unified_name="hermes-unified")
            client["legacy_names"] = ["hermes"]

            result = remove_legacy_mcp_tool(client, EXPECTED)

            self.assertEqual(result["status"], "updated")
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("hermes", updated["mcp"])
            self.assertEqual(updated["mcp"]["hermes-unified"], {"url": URL})
            self.assertEqual(updated["mcp"]["other"], original["mcp"]["other"])

    def test_remove_legacy_toml_and_reasonix_plugins_preserves_other_blocks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            expected = {**EXPECTED, "legacy_names": ["hermes-memory", "hermes-gateway"]}
            codex_path = Path(temp_dir) / "codex.toml"
            codex_path.write_text(
                f'[mcp_servers.hermes]\nurl = "{URL}"\n\n'
                '[mcp_servers.hermes-memory]\ncommand = "legacy"\n\n'
                '[mcp_servers.hermes-memory.env]\nTOKEN = "legacy-secret"\n\n'
                '[mcp_servers.other]\ncommand = "keep"\n',
                encoding="utf-8",
            )
            reasonix_path = Path(temp_dir) / "reasonix.toml"
            reasonix_path.write_text(
                f'[[plugins]]\nname = "hermes"\ntype = "http"\nurl = "{URL}"\n\n'
                '[[plugins]]\nname = "hermes-gateway"\ncommand = "legacy"\n\n'
                '[[plugins]]\nname = "other"\ntype = "http"\nurl = "https://other.example/mcp"\n',
                encoding="utf-8",
            )

            codex_result = remove_legacy_mcp_tool(
                tool(codex_path, "toml", mcp_key_path=["mcp_servers"]), expected
            )
            reasonix_result = remove_legacy_mcp_tool(
                tool(reasonix_path, "reasonix_toml", mcp_key_path=["plugins"]), expected
            )

            self.assertEqual(codex_result["status"], "updated")
            self.assertNotIn("mcp_servers.hermes-memory", codex_path.read_text())
            self.assertNotIn("legacy-secret", codex_path.read_text())
            self.assertIn("mcp_servers.other", codex_path.read_text())
            self.assertEqual(reasonix_result["status"], "updated")
            self.assertNotIn('name = "hermes-gateway"', reasonix_path.read_text())
            self.assertIn('name = "other"', reasonix_path.read_text())

    def test_remove_legacy_ignores_canonical_validity(self):
        """纯删除：即使正典端点 url 无效，也照常删除旧通道，且不动正典条目。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            original = '{"mcpServers":{"hermes":{"url":"https://wrong.example/mcp"},"ai-memory":{}}}\n'
            path.write_text(original, encoding="utf-8")
            expected = {**EXPECTED, "legacy_names": ["ai-memory"]}

            result = remove_legacy_mcp_tool(tool(path), expected)

            self.assertEqual(result["status"], "updated")
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("ai-memory", updated["mcpServers"])
            # 正典条目（即使 url 错误）保持原样，纯删除不校验其有效性
            self.assertEqual(updated["mcpServers"]["hermes"], {"url": "https://wrong.example/mcp"})
            self.assertEqual(len(list(path.parent.glob("mcp.json.bak-*"))), 1)

    def test_json_update_preserves_legacy_and_other_content_and_makes_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            original = {
                "theme": "dark",
                "mcpServers": {
                    "hermes": {"url": "https://old.example/mcp", "headers": {"secret": "keep"}},
                    "hermes-memory": {"command": "python3", "args": ["bridge.py"]},
                    "other": {"command": "node", "env": {"TOKEN": "untouched"}},
                },
            }
            path.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")
            os.chmod(path, 0o640)

            result = fix_mcp_tool(tool(path), EXPECTED)

            self.assertEqual(result["status"], "updated")
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(updated["mcpServers"]["hermes"], {"url": URL})
            self.assertEqual(updated["mcpServers"]["hermes-memory"], original["mcpServers"]["hermes-memory"])
            self.assertEqual(updated["mcpServers"]["other"], original["mcpServers"]["other"])
            self.assertEqual(updated["theme"], "dark")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
            backups = list(path.parent.glob("mcp.json.bak-20*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), json.dumps(original, indent=2) + "\n")

    def test_toml_append_preserves_comments_legacy_sections_and_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            original = (
                "# user comment\n"
                "model = \"gpt-5\"\n\n"
                "[mcp_servers.hermes-memory]\n"
                "command = \"python3\" # preserve legacy\n\n"
                "[mcp_servers.other]\n"
                "command = \"node\"\n"
            )
            path.write_text(original, encoding="utf-8")
            os.chmod(path, 0o600)

            result = fix_mcp_tool(tool(path, "toml", mcp_key_path=["mcp_servers"]), EXPECTED)

            self.assertEqual(result["status"], "updated")
            updated = path.read_text(encoding="utf-8")
            self.assertIn(original, updated)
            self.assertEqual(updated.count("[mcp_servers.hermes]"), 1)
            self.assertIn(f'url = "{URL}"', updated)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_toml_update_changes_only_canonical_section_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            original = (
                "# header\n"
                "[mcp_servers.hermes]\n"
                "# endpoint comment\n"
                "url = \"https://old.example/mcp\" # inline\n"
                "enabled = true\n\n"
                "[mcp_servers.hermes-gateway]\n"
                "command = \"bridge\"\n"
            )
            path.write_text(original, encoding="utf-8")

            result = fix_mcp_tool(tool(path, "toml", mcp_key_path=["mcp_servers"]), EXPECTED)

            self.assertEqual(result["status"], "updated")
            updated = path.read_text(encoding="utf-8")
            self.assertIn("# endpoint comment", updated)
            self.assertIn(f'url = "{URL}" # inline', updated)
            self.assertIn("[mcp_servers.hermes-gateway]", updated)
            self.assertIn('command = "bridge"', updated)
            self.assertEqual(updated.count("[mcp_servers.hermes]"), 1)

    def test_reasonix_string_array_is_supported_when_explicitly_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({
                "mcp": ["other=node server.js", "hermes=https://old.example/mcp", "hermes-memory=python bridge.py"],
                "apiKey": "untouched",
            }), encoding="utf-8")

            result = fix_mcp_tool(
                tool(path, "reasonix", mcp_key_path=["mcp"]), EXPECTED
            )

            self.assertEqual(result["status"], "updated")
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(updated["mcp"].count(f"hermes={URL}"), 1)
            self.assertIn("other=node server.js", updated["mcp"])
            self.assertIn("hermes-memory=python bridge.py", updated["mcp"])
            self.assertEqual(updated["apiKey"], "untouched")

    def test_reasonix_toml_plugins_are_loaded_and_repaired_without_removing_legacy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            original = (
                "# Reasonix user settings\n"
                "config_version = 3\n\n"
                "[[plugins]]\n"
                "name = \"hermes-memory\"\n"
                "command = \"python3\" # legacy comment\n"
                "args = [\"bridge.py\"]\n\n"
                "[[plugins]]\n"
                "name = \"other\"\n"
                "type = \"http\"\n"
                "url = \"https://other.example/mcp\"\n"
            )
            path.write_text(original, encoding="utf-8")

            result = fix_mcp_tool(
                tool(path, "reasonix_toml", mcp_key_path=["plugins"]), EXPECTED
            )

            self.assertEqual(result["status"], "updated")
            updated_text = path.read_text(encoding="utf-8")
            self.assertIn(original, updated_text)
            self.assertIn("# legacy comment", updated_text)
            servers = load_mcp_servers(str(path), "reasonix_toml", ["plugins"])
            self.assertEqual(servers["hermes"], {"type": "http", "url": URL})
            self.assertEqual(servers["hermes-memory"]["command"], "python3")
            self.assertEqual(servers["other"]["url"], "https://other.example/mcp")
            self.assertEqual(updated_text.count('name = "hermes"'), 1)

    def test_reasonix_toml_updates_existing_canonical_plugin_in_place(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            path.write_text(
                "[[plugins]]\n"
                "name = \"hermes\"\n"
                "type = \"http\"\n"
                "url = \"https://old.example/mcp\" # endpoint\n"
                "enabled = true\n\n"
                "[[plugins]]\n"
                "name = \"hermes-gateway\"\n"
                "command = \"bridge\"\n",
                encoding="utf-8",
            )

            result = fix_mcp_tool(
                tool(path, "reasonix_toml", mcp_key_path=["plugins"]), EXPECTED
            )

            self.assertEqual(result["status"], "updated")
            updated = path.read_text(encoding="utf-8")
            self.assertIn(f'url = "{URL}" # endpoint', updated)
            self.assertIn("enabled = true", updated)
            self.assertIn('name = "hermes-gateway"', updated)
            self.assertEqual(updated.count('name = "hermes"'), 1)

    def test_dry_run_and_idempotency_do_not_write_or_create_extra_backups(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            original = json.dumps({"mcpServers": {"legacy": {"command": "x"}}}) + "\n"
            path.write_text(original, encoding="utf-8")

            dry = fix_mcp_tool(tool(path), EXPECTED, dry_run=True)
            self.assertEqual(dry["status"], "dry-run")
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(list(path.parent.glob("mcp.json.bak-*")), [])

            first = fix_mcp_tool(tool(path), EXPECTED)
            second = fix_mcp_tool(tool(path), EXPECTED)
            self.assertEqual(first["status"], "updated")
            self.assertEqual(second["status"], "unchanged")
            self.assertEqual(len(list(path.parent.glob("mcp.json.bak-*"))), 1)

    def test_unsupported_and_invalid_configs_are_reported_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reasonix = Path(temp_dir) / "reasonix.json"
            reasonix.write_text('{"mcp": []}', encoding="utf-8")
            unsupported_result = fix_mcp_tool(
                tool(reasonix, "reasonix", fix_supported=False, fix_unsupported_reason="remote URL syntax is unverified"),
                EXPECTED,
            )
            self.assertEqual(unsupported_result["status"], "unsupported")
            self.assertIn("unverified", unsupported_result["message"])
            self.assertEqual(reasonix.read_text(encoding="utf-8"), '{"mcp": []}')

            invalid = Path(temp_dir) / "invalid.json"
            invalid.write_text("{broken", encoding="utf-8")
            invalid_result = fix_mcp_tool(tool(invalid), EXPECTED)
            self.assertEqual(invalid_result["status"], "error")
            self.assertEqual(invalid.read_text(encoding="utf-8"), "{broken")
            self.assertEqual(list(invalid.parent.glob("invalid.json.bak-*")), [])

    def test_atomic_replace_failure_leaves_original_and_backup_intact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            original = '{"mcpServers": {}}\n'
            path.write_text(original, encoding="utf-8")

            with patch("mcp_fixer.os.replace", side_effect=OSError("replace failed")):
                result = fix_mcp_tool(tool(path), EXPECTED)

            self.assertEqual(result["status"], "error")
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            backups = list(path.parent.glob("mcp.json.bak-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), original)
            self.assertEqual(list(path.parent.glob(".mcp.json.*.tmp")), [])

    def test_post_write_validation_failure_rolls_back_original(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            original = '{"mcpServers": {"legacy": {"command": "x"}}}\n'
            path.write_text(original, encoding="utf-8")

            with patch("mcp_fixer._validate_written_config", side_effect=ValueError("validation failed")):
                result = fix_mcp_tool(tool(path), EXPECTED)

            self.assertEqual(result["status"], "error")
            self.assertIn("rolled back", result["message"])
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(len(list(path.parent.glob("mcp.json.bak-*"))), 1)

    def test_fix_clients_skips_uninstalled_and_returns_one_result_per_client(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            installed_path = Path(temp_dir) / "installed.json"
            installed_path.write_text('{"mcpServers": {}}', encoding="utf-8")
            absent_path = Path(temp_dir) / "absent.json"
            # 三态语义整改: 仅 config 不再算 installed；给「已安装」客户端加
            # 真实 app bundle 目录，Absent Client 保持 config-only → not-installed。
            app_dir = Path(temp_dir) / "TestClient.app"
            app_dir.mkdir()
            config = {
                "unified_mcp": EXPECTED,
                "mcp_tools": [
                    tool(installed_path, install={"app_bundles": [str(app_dir)], "config_paths": [str(installed_path)]}),
                    tool(absent_path, name="Absent Client"),
                ],
            }

            with patch("config_store.load_discovered", return_value=[]):
                results = fix_mcp_clients(config, dry_run=True)

            self.assertEqual([item["status"] for item in results], ["dry-run", "not-installed"])
            self.assertEqual([item["name"] for item in results], ["Test Client", "Absent Client"])

    def test_missing_supported_config_is_created_for_installed_client(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "new-client" / "mcp.json"

            result = fix_mcp_tool(tool(path), EXPECTED)

            self.assertEqual(result["status"], "created")
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["hermes"]["url"],
                URL,
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


    def test_cordis_yaml_inserts_canonical_entry_without_disturbing_others(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cordis.patch.yml"
            path.write_text(
                "# header comment preserved\n"
                "- id: mcp-github\n"
                "  name: '@deepseek-ai/dsh-mcp-client'\n"
                "  config:\n"
                "    serverName: github\n"
                "    transport: stdio\n"
                "    command: npx\n",
                encoding="utf-8",
            )
            result = fix_mcp_tool(
                tool(path, "cordis_yaml", mcp_key_path=["hermes"]), EXPECTED
            )
            self.assertEqual(result["status"], "updated")
            text = path.read_text(encoding="utf-8")
            self.assertIn("# header comment preserved", text)
            self.assertIn("mcp-github", text)
            self.assertIn("mcp-hermes", text)
            self.assertIn("serverName: hermes", text)
            self.assertIn(URL, text)
            self.assertIn("transport: streamable-http", text)

    def test_cordis_yaml_already_correct_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cordis.patch.yml"
            correct = (
                "- id: mcp-hermes\n"
                "  name: '@deepseek-ai/dsh-mcp-client'\n"
                "  config:\n"
                "    serverName: hermes\n"
                "    transport: streamable-http\n"
                f"    url: {URL}\n"
            )
            path.write_text(correct, encoding="utf-8")
            result = fix_mcp_tool(
                tool(path, "cordis_yaml", mcp_key_path=["hermes"]), EXPECTED
            )
            self.assertEqual(result["status"], "unchanged")

    def test_cordis_yaml_remove_legacy_is_noop_when_absent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cordis.patch.yml"
            path.write_text(
                "- id: mcp-hermes\n"
                "  config:\n"
                "    serverName: hermes\n"
                f"    url: {URL}\n",
                encoding="utf-8",
            )
            expected = {**EXPECTED, "legacy_names": ["hermes-nas", "hermes-memory"]}
            result = remove_legacy_mcp_tool(
                tool(path, "cordis_yaml", mcp_key_path=["hermes"]), expected
            )
            self.assertEqual(result["status"], "unchanged")
            self.assertIn("mcp-hermes", path.read_text(encoding="utf-8"))

    def test_json_with_auth_token_writes_bearer_plaintext_headers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text('{"mcpServers": {}}', encoding="utf-8")
            expected = {"name": "K8s", "url": URL, "auth_token": "SECRET.VALUE"}
            result = fix_mcp_tool(tool(path), expected)
            self.assertEqual(result["status"], "updated")
            data = json.loads(path.read_text(encoding="utf-8"))
            entry = data["mcpServers"]["K8s"]
            self.assertEqual(entry["url"], URL)
            self.assertEqual(
                entry["headers"],
                {"Authorization": "Bearer SECRET.VALUE"},
            )

    def test_json_without_auth_token_writes_url_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text('{"mcpServers": {}}', encoding="utf-8")
            result = fix_mcp_tool(tool(path), EXPECTED)
            self.assertEqual(result["status"], "updated")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["mcpServers"]["hermes"], {"url": URL})

    def test_toml_with_auth_token_writes_http_headers_plaintext(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            path.write_text("", encoding="utf-8")
            expected = {"name": "K8s", "url": URL, "auth_token": "SECRET"}
            result = fix_mcp_tool(
                tool(path, "toml", mcp_key_path=["mcp_servers"]), expected
            )
            self.assertEqual(result["status"], "updated")
            text = path.read_text(encoding="utf-8")
            self.assertIn(f'url = "{URL}"', text)
            self.assertIn('http_headers = { Authorization = "Bearer SECRET" }', text)
            self.assertNotIn("bearer_token_env_var", text)

    def test_toml_http_headers_inserted_in_correct_section_when_not_first(self):
        # 回归：目标 section 前有其它 section + 空行时，http_headers 必须落到
        # 目标 `[mcp_servers.K8s]` 段内，而不是误插到上一个段。
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            path.write_text(
                '[mcp_servers.hermes]\nurl = "https://hermes.example.com/mcp"\n\n'
                '[mcp_servers.K8s]\nurl = "https://k8s.example.com/mcp"\n',
                encoding="utf-8",
            )
            expected = {"name": "K8s", "url": "https://k8s.example.com/mcp", "auth_token": "SECRET"}
            result = fix_mcp_tool(
                tool(path, "toml", mcp_key_path=["mcp_servers"]), expected
            )
            self.assertEqual(result["status"], "updated")
            text = path.read_text(encoding="utf-8")
            self.assertIn('http_headers = { Authorization = "Bearer SECRET" }', text)
            servers = load_mcp_servers(str(path), "toml", ["mcp_servers"])
            # http_headers 落到 K8s 段内，hermes 段不受污染
            self.assertEqual(servers["K8s"]["url"], "https://k8s.example.com/mcp")
            self.assertIn("http_headers", servers["K8s"])
            self.assertNotIn("http_headers", servers["hermes"])
            self.assertEqual(servers["hermes"], {"url": "https://hermes.example.com/mcp"})

    def test_reasonix_toml_with_auth_token_writes_headers_plaintext(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            path.write_text("", encoding="utf-8")
            expected = {"name": "K8s", "url": URL, "auth_token": "SECRET"}
            result = fix_mcp_tool(
                tool(path, "reasonix_toml", mcp_key_path=["plugins"]), expected
            )
            self.assertEqual(result["status"], "updated")
            text = path.read_text(encoding="utf-8")
            self.assertIn(f'url = "{URL}"', text)
            self.assertIn('headers = { Authorization = "Bearer SECRET" }', text)

    def test_fix_mcp_clients_writes_every_endpoint_for_each_client(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            installed_path = Path(temp_dir) / "mcp.json"
            installed_path.write_text('{"mcpServers": {}}', encoding="utf-8")
            app_dir = Path(temp_dir) / "TestClient.app"
            app_dir.mkdir()
            config = {
                "profiles": {
                    "hermes": {"name": "hermes", "url": "https://hermes.example.com/mcp"},
                    "k8s": {
                        "name": "K8s",
                        "url": "https://k8s.example.com/mcp",
                        "auth_token": "SECRET",
                        "auth_token_env": "K8S_MCP_AUTH_TOKEN",
                    },
                },
                "active_profile": "hermes",
                "mcp_tools": [
                    tool(installed_path, install={"app_bundles": [str(app_dir)], "config_paths": [str(installed_path)]}),
                ],
            }
            with patch("config_store.load_discovered", return_value=[]):
                results = fix_mcp_clients(config, dry_run=True)
            # 一个客户端 × 两个端点 = 两条结果
            self.assertEqual(len(results), 2)
            self.assertEqual(
                sorted(item["message"] for item in results),
                ["endpoint 'K8s' would be updated", "endpoint 'hermes' would be updated"],
            )

    def test_cordis_yaml_with_auth_token_writes_plaintext_header(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cordis.patch.yml"
            path.write_text("", encoding="utf-8")
            expected = {
                "name": "K8s",
                "url": URL,
                "auth_token": "SECRET",
            }
            result = fix_mcp_tool(
                tool(path, "cordis_yaml", mcp_key_path=["hermes"]), expected
            )
            self.assertEqual(result["status"], "updated")
            text = path.read_text(encoding="utf-8")
            self.assertIn("serverName: K8s", text)
            self.assertIn("mcp-K8s", text)
            self.assertIn('Authorization: "Bearer SECRET"', text)
            self.assertNotIn("!!js", text)

    def test_fix_mcp_clients_single_profile_mode_writes_only_that_endpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            installed_path = Path(temp_dir) / "mcp.json"
            installed_path.write_text('{"mcpServers": {}}', encoding="utf-8")
            app_dir = Path(temp_dir) / "TestClient.app"
            app_dir.mkdir()
            config = {
                "profiles": {
                    "hermes": {"name": "hermes", "url": "https://hermes.example.com/mcp"},
                    "k8s": {"name": "K8s", "url": "https://k8s.example.com/mcp"},
                },
                "active_profile": "hermes",
                "mcp_tools": [
                    tool(installed_path, install={"app_bundles": [str(app_dir)], "config_paths": [str(installed_path)]}),
                ],
            }
            with patch("config_store.load_discovered", return_value=[]):
                results = fix_mcp_clients(
                    config, dry_run=True, profile={"name": "hermes", "url": "https://hermes.example.com/mcp"}
                )
            self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
