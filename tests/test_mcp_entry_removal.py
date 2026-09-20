import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

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


if __name__ == "__main__":
    unittest.main()