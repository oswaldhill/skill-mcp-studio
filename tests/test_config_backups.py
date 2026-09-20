import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from config_backups import list_config_backups, restore_config_backup  # noqa: E402


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


class ListBackupsTest(unittest.TestCase):
    def test_lists_only_own_backups_newest_first(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text('{"mcpServers":{}}\n', encoding="utf-8")
            older = Path(str(path) + ".bak-20260920-100000-000000")
            newer = Path(str(path) + ".bak-20260920-110000-000000")
            older.write_text('{"mcpServers":{"a":{}}}\n', encoding="utf-8")
            newer.write_text('{"mcpServers":{"b":{}}}\n', encoding="utf-8")
            # 干扰项：不是本配置的备份
            (Path(temp_dir) / "other.json.bak-20260920-120000-000000").write_text(
                "{}\n", encoding="utf-8"
            )

            backups = list_config_backups(str(path))

            self.assertEqual([b["path"] for b in backups], [str(newer), str(older)])
            self.assertEqual(backups[0]["size"], newer.stat().st_size)
            self.assertTrue(backups[0]["mtime_text"])


class RestoreBackupTest(unittest.TestCase):
    def _fixture(self, temp_dir, current, backup):
        path = Path(temp_dir) / "mcp.json"
        path.write_text(current, encoding="utf-8")
        backup_path = Path(str(path) + ".bak-20260920-100000-000000")
        backup_path.write_text(backup, encoding="utf-8")
        return path, backup_path

    def test_restore_overwrites_and_backs_up_current_first(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            current = '{"mcpServers":{"a":{}}}\n'
            backup = '{"mcpServers":{"a":{},"b":{}}}\n'
            path, backup_path = self._fixture(temp_dir, current, backup)

            result = restore_config_backup(tool(path), str(backup_path))

            self.assertEqual(result["status"], "updated")
            self.assertEqual(path.read_text(encoding="utf-8"), backup)
            self.assertTrue(result["backup"])
            self.assertEqual(Path(result["backup"]).read_text(encoding="utf-8"), current)

    def test_refuses_backup_of_another_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text('{"mcpServers":{}}\n', encoding="utf-8")
            foreign = Path(temp_dir) / "other.json.bak-20260920-100000-000000"
            foreign.write_text("{}\n", encoding="utf-8")

            result = restore_config_backup(tool(path), str(foreign))

            self.assertEqual(result["status"], "refused")
            self.assertIn("不是该客户端配置的备份", result["message"])

    def test_refuses_unparsable_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            current = '{"mcpServers":{"a":{}}}\n'
            path, backup_path = self._fixture(temp_dir, current, "{ broken")
            before = path.read_text(encoding="utf-8")

            result = restore_config_backup(tool(path), str(backup_path))

            self.assertEqual(result["status"], "refused")
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            current = '{"mcpServers":{"a":{}}}\n'
            backup = '{"mcpServers":{"b":{}}}\n'
            path, backup_path = self._fixture(temp_dir, current, backup)

            result = restore_config_backup(tool(path), str(backup_path), dry_run=True)

            self.assertEqual(result["status"], "dry-run")
            self.assertEqual(path.read_text(encoding="utf-8"), current)


if __name__ == "__main__":
    unittest.main()