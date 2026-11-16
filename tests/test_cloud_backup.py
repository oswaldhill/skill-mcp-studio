"""iCloud 完整备份契约（2026-11-16，macOS 专属）。

## 隔离纪律（与 test_config_porter 同源教训，必须遵守）

``cloud_backup._repo_root`` 与 ``cloud_backup.backup_root`` 都必须 patch 到
临时目录：

- 不 patch ``_repo_root``：``create_backup`` 会读仓库真实 ``config.yaml``，
  而 ``restore_backup`` 会**覆盖**真实配置文件；
- 不 patch ``backup_root``：备份会真的写进用户的 iCloud Drive。

两者都不是「测试副作用」而是「污染用户数据」，所以每个用例都经
``_Env`` 上下文统一接管。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import cloud_backup  # noqa: E402
from cloud_backup import (  # noqa: E402
    BACKUP_KIND,
    BACKUP_SCHEMA_VERSION,
    backup_root,
    backup_status,
    create_backup,
    list_backups,
    prune_backups,
    restore_backup,
)

TRUNK = """\
schema_version: 1
active_profile: generic-http
profiles:
  generic-http:
    name: my-mcp
    url: https://example.test/mcp
    auth_token: token-in-test
"""

OVERLAY = "disabled_tools:\n- Cursor\n"
DISCOVERED = "- name: Cursor\n  config_path: ~/.cursor/mcp.json\n"


class _Env:
    """临时仓库根 + 临时 iCloud 根，接管两个路径函数。"""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.repo = base / "repo"
        self.cloud = base / "cloud"
        (self.repo / "data").mkdir(parents=True)
        (self.repo / "config.yaml").write_text(TRUNK, encoding="utf-8")
        (self.repo / "data" / "local_overrides.yaml").write_text(OVERLAY, encoding="utf-8")
        (self.repo / "data" / "discovered_tools.yaml").write_text(DISCOVERED, encoding="utf-8")
        (self.repo / "data" / "git_sources.yaml").write_text("sources: []\n", encoding="utf-8")
        (self.repo / "data" / "github_token").write_text("ghp_secret\n", encoding="utf-8")
        self._patches = [
            mock.patch.object(cloud_backup, "_repo_root", lambda: str(self.repo)),
            mock.patch.object(cloud_backup, "backup_root", lambda: str(self.cloud)),
        ]
        for p in self._patches:
            p.start()

    def __enter__(self) -> "_Env":
        return self

    def __exit__(self, *exc) -> None:
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()


class PlatformGateTest(unittest.TestCase):
    def test_non_macos_rejects_explicitly(self):
        """非 macOS 必须显式报错，而不是静默写到错误位置。"""
        with mock.patch.object(cloud_backup.sys, "platform", "linux"):
            with self.assertRaises(ValueError) as ctx:
                backup_root()
        self.assertIn("仅在 macOS 可用", str(ctx.exception))


class CreateBackupTest(unittest.TestCase):
    def test_writes_json_with_plaintext_secrets(self):
        """备份含明文密钥 —— 与导出（脱敏）刻意相反，这是灾难恢复的前提。"""
        with _Env() as env:
            result = create_backup()
            self.assertEqual("ok", result["status"])
            path = Path(result["path"])
            self.assertTrue(path.is_file())
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(BACKUP_KIND, payload["kind"])
            self.assertEqual(BACKUP_SCHEMA_VERSION, payload["schema_version"])
            self.assertIn("token-in-test", payload["files"]["config.yaml"])
            self.assertIn("ghp_secret", payload["files"]["data/github_token"])

    def test_backup_file_is_owner_only(self):
        """备份含密钥，落盘权限必须是 0600。"""
        with _Env() as env:
            result = create_backup()
            mode = os.stat(result["path"]).st_mode & 0o777
            self.assertEqual(0o600, mode)

    def test_skips_missing_optional_files(self):
        """market_sources.yaml 属可选：不存在时不报错。"""
        with _Env():
            result = create_backup()
            self.assertEqual("ok", result["status"])
            payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
            self.assertNotIn("data/market_sources.yaml", payload["files"])

    def test_missing_core_file_raises(self):
        """config.yaml 缺失属硬错误（不能产出半份备份）。"""
        with _Env() as env:
            (env.repo / "config.yaml").unlink()
            with self.assertRaises(ValueError) as ctx:
                create_backup()
            self.assertIn("config.yaml", str(ctx.exception))

    def test_excludes_skill_content(self):
        """范围约束：备份只含配置与数据，不含技能目录。"""
        with _Env() as env:
            skills = env.repo / "data" / "skills"
            skills.mkdir()
            (skills / "some-skill.md").write_text("# skill\n", encoding="utf-8")
            result = create_backup()
            payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
            self.assertFalse(any("skills/" in key for key in payload["files"]))

    def test_dry_run_writes_nothing(self):
        with _Env() as env:
            result = create_backup(dry_run=True)
            self.assertEqual("dry-run", result["status"])
            self.assertFalse(env.cloud.exists())


class ListBackupsTest(unittest.TestCase):
    def test_newest_first_by_timestamp(self):
        """按文件名时间戳排序（不依赖 mtime，避免秒级分辨率抹平顺序）。"""
        with _Env():
            with mock.patch.object(cloud_backup, "_now_stamp", lambda: "20260101-000000"):
                create_backup()
            with mock.patch.object(cloud_backup, "_now_stamp", lambda: "20260102-000000"):
                create_backup()
            items = list_backups()
            self.assertEqual(2, len(items))
            self.assertEqual("backup-20260102-000000.json", items[0]["id"])

    def test_ignores_unrelated_files(self):
        with _Env() as env:
            create_backup()
            env.cloud.mkdir(parents=True, exist_ok=True)
            (env.cloud / "notes.txt").write_text("x", encoding="utf-8")
            (env.cloud / "backup-bad-name.json").write_text("{}", encoding="utf-8")
            self.assertEqual(1, len(list_backups()))


class RestoreBackupTest(unittest.TestCase):
    def test_roundtrip_restores_content(self):
        with _Env() as env:
            result = create_backup()
            trunk = env.repo / "config.yaml"
            trunk.write_text(TRUNK.replace("token-in-test", "changed"), encoding="utf-8")
            restored = restore_backup(Path(result["path"]).name)
            self.assertEqual("ok", restored["status"])
            self.assertIn("token-in-test", trunk.read_text(encoding="utf-8"))

    def test_safety_backup_before_overwrite(self):
        """恢复前必须真的复制出 .bak- 文件（不是只生成路径名）。"""
        with _Env() as env:
            result = create_backup()
            trunk = env.repo / "config.yaml"
            trunk.write_text("changed: true\n", encoding="utf-8")
            restored = restore_backup(Path(result["path"]).name)
            self.assertTrue(restored["backups"])
            for bak in restored["backups"]:
                self.assertTrue(os.path.isfile(bak), f"备份文件不存在: {bak}")
            baks = list(env.repo.glob("config.yaml.bak-*"))
            self.assertTrue(baks, "应生成 config.yaml.bak-<ts>")
            self.assertIn("changed: true", baks[0].read_text(encoding="utf-8"))

    def test_restores_secret_file_as_0600(self):
        with _Env() as env:
            result = create_backup()
            token = env.repo / "data" / "github_token"
            token.write_text("rotated\n", encoding="utf-8")
            restore_backup(Path(result["path"]).name)
            self.assertEqual(0o600, os.stat(token).st_mode & 0o777)

    def test_rejects_non_whitelisted_path(self):
        """备份里塞白名单外路径 → 拒绝（路径穿越防线）。"""
        with _Env() as env:
            env.cloud.mkdir(parents=True, exist_ok=True)
            evil = env.cloud / "backup-20260101-000000.json"
            evil.write_text(json.dumps({
                "kind": BACKUP_KIND,
                "schema_version": BACKUP_SCHEMA_VERSION,
                "files": {"../../etc/passwd": "x"},
            }), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                restore_backup(evil.name)
            self.assertIn("白名单之外", str(ctx.exception))

    def test_rejects_wrong_kind(self):
        with _Env() as env:
            env.cloud.mkdir(parents=True, exist_ok=True)
            bad = env.cloud / "backup-20260101-000000.json"
            bad.write_text(json.dumps({"kind": "other", "schema_version": 1,
                                       "files": {"config.yaml": "x"}}), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                restore_backup(bad.name)
            self.assertIn("kind 不符", str(ctx.exception))

    def test_rejects_wrong_schema_version(self):
        with _Env() as env:
            env.cloud.mkdir(parents=True, exist_ok=True)
            bad = env.cloud / "backup-20260101-000000.json"
            bad.write_text(json.dumps({"kind": BACKUP_KIND, "schema_version": 99,
                                       "files": {"config.yaml": "x"}}), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                restore_backup(bad.name)
            self.assertIn("schema_version", str(ctx.exception))

    def test_dry_run_does_not_touch_files(self):
        with _Env() as env:
            result = create_backup()
            trunk = env.repo / "config.yaml"
            trunk.write_text("changed: true\n", encoding="utf-8")
            restored = restore_backup(Path(result["path"]).name, dry_run=True)
            self.assertEqual("dry-run", restored["status"])
            self.assertEqual("changed: true\n", trunk.read_text(encoding="utf-8"))


class PruneBackupsTest(unittest.TestCase):
    def _seed(self, stamps):
        for stamp in stamps:
            with mock.patch.object(cloud_backup, "_now_stamp", lambda s=stamp: s):
                create_backup()

    def test_keeps_most_recent_n(self):
        with _Env():
            self._seed(["20260101-000000", "20260102-000000", "20260103-000000",
                        "20260104-000000", "20260105-000000"])
            result = prune_backups(keep=2)
            self.assertEqual(3, result["removed"])
            remaining = [item["id"] for item in list_backups()]
            self.assertEqual(["backup-20260105-000000.json",
                              "backup-20260104-000000.json"], remaining)

    def test_keep_below_one_rejected(self):
        with _Env():
            with self.assertRaises(ValueError):
                prune_backups(keep=0)

    def test_dry_run_reports_without_deleting(self):
        with _Env():
            self._seed(["20260101-000000", "20260102-000000", "20260103-000000"])
            result = prune_backups(keep=1, dry_run=True)
            self.assertEqual(2, result["removed"])
            self.assertEqual(3, len(list_backups()))


class StatusTest(unittest.TestCase):
    def test_shape_when_available(self):
        with _Env():
            create_backup()
            status = backup_status()
            self.assertTrue(status["available"])
            self.assertEqual(1, status["count"])
            self.assertGreater(status["bytes"], 0)
            self.assertEqual("backup-" + status["latest"]["stamp"] + ".json",
                             status["latest"]["id"])

    def test_shape_when_platform_unsupported(self):
        with mock.patch.object(cloud_backup.sys, "platform", "linux"):
            status = backup_status()
        self.assertFalse(status["available"])
        self.assertIn("仅在 macOS 可用", status["reason"])
        self.assertEqual(0, status["count"])


if __name__ == "__main__":
    unittest.main()