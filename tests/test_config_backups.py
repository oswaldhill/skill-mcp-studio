import json
import os
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
            # 关键：把两个备份的 mtime 压成同一个值。真实场景里这很常见（同一秒内
            # 连续写入，或文件系统分辨率粗），CI 上就复现了——此时若只按 mtime 排序，
            # 顺序会退化成 os.listdir 的任意顺序，"最上面"的未必是最新备份，
            # 用户据此还原就会选错版本。故顺序必须由文件名时间戳决定。
            same = 1_700_000_000
            os.utime(older, (same, same))
            os.utime(newer, (same, same))
            # 干扰项：不是本配置的备份
            (Path(temp_dir) / "other.json.bak-20260920-120000-000000").write_text(
                "{}\n", encoding="utf-8"
            )

            backups = list_config_backups(str(path))

            self.assertEqual([b["path"] for b in backups], [str(newer), str(older)])
            self.assertEqual(backups[0]["size"], newer.stat().st_size)
            self.assertTrue(backups[0]["mtime_text"])

    def test_order_survives_identical_mtime_and_inode_order(self):
        """mtime 全同 + 目录返回顺序与时间序相反时，仍必须按文件名时间戳倒序。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text('{"mcpServers":{}}\n', encoding="utf-8")
            # 故意先建"新"的、后建"旧"的，再统一 mtime，让任何依赖创建序/mtime 的
            # 实现都排序失败——只有读文件名时间戳的实现能通过。
            newest = Path(str(path) + ".bak-20260920-120000-000000")
            middle = Path(str(path) + ".bak-20260920-110000-000000")
            oldest = Path(str(path) + ".bak-20260920-100000-000000")
            for p in (newest, middle, oldest):
                p.write_text('{"mcpServers":{}}\n', encoding="utf-8")
                os.utime(p, (1_700_000_000, 1_700_000_000))

            backups = list_config_backups(str(path))

            self.assertEqual(
                [b["path"] for b in backups], [str(newest), str(middle), str(oldest)]
            )


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
