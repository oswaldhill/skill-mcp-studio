"""WebDAV 远程同步（v0.31.1，#3 后半）。

重点验证三条纪律：
1. **同步范围**：只同步个人配置层；凭据与技能包永不在清单内
2. **凭据安全**：0600 权限、脱敏输出、格式校验
3. **覆盖留档**：推送前保远端旧值、拉取前保本地旧值（不自动合并）
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import webdav_sync as wd  # noqa: E402


class _Base(unittest.TestCase):
    """把 data 目录移到临时目录，避免碰到真实 data/。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "data"
        self.data.mkdir()
        self._p1 = mock.patch.object(wd, "_data_dir", return_value=self.data)
        self._p1.start()

    def tearDown(self):
        self._p1.stop()
        self.tmp.cleanup()


class ScopeTest(_Base):
    def test_credential_never_in_sync_list(self):
        """凭据文件永不同步——同步出去等于把密码发到远端。"""
        self.assertNotIn(wd.CRED_NAME, wd.SYNC_FILES)
        self.assertNotIn("webdav_config.yaml", wd.SYNC_FILES)
        self.assertNotIn("github_token", wd.SYNC_FILES)

    def test_skill_backups_not_synced(self):
        self.assertFalse(any("skill_backups" in f for f in wd.SYNC_FILES))

    def test_sync_list_is_personal_config_only(self):
        self.assertEqual(set(wd.SYNC_FILES), {
            "local_overrides.yaml", "market_sources.yaml",
            "discovered_tools.yaml", "skill_versions.json",
        })


class CredentialTest(_Base):
    def test_rejects_malformed(self):
        self.assertFalse(wd.set_credential("nopass")["ok"])
        self.assertFalse(wd.set_credential(":onlypass")["ok"])

    def test_saves_with_0600(self):
        res = wd.set_credential("alice:s3cret")
        self.assertTrue(res["ok"])
        mode = oct(wd.credential_path().stat().st_mode & 0o777)
        self.assertEqual(mode, "0o600", "凭据文件应仅属主可读写")

    def test_masked_never_leaks_full_secret(self):
        res = wd.set_credential("alice:s3cretpassword")
        self.assertNotIn("s3cretpassword", str(res))
        self.assertIn("alice", res["masked"])
        self.assertIn("***", res["masked"])

    def test_clear_removes_file(self):
        wd.set_credential("alice:s3cret")
        self.assertTrue(wd.credential_path().exists())
        res = wd.set_credential("")
        self.assertTrue(res.get("cleared"))
        self.assertFalse(wd.credential_path().exists())

    def test_status_does_not_leak(self):
        wd.set_url("https://dav.example.com/x")
        wd.set_credential("alice:topsecret")
        st = wd.status()
        self.assertTrue(st["configured"])
        self.assertNotIn("topsecret", repr(st))


class UrlTest(_Base):
    def test_rejects_non_http_scheme(self):
        self.assertFalse(wd.set_url("ftp://x")["ok"])
        self.assertFalse(wd.set_url("/local/path")["ok"])

    def test_strips_trailing_slash(self):
        res = wd.set_url("https://dav.example.com/files/")
        self.assertEqual(res["url"], "https://dav.example.com/files")

    def test_http_warns_about_plaintext(self):
        res = wd.set_url("http://nas.local/dav")
        self.assertTrue(res["ok"])
        self.assertIn("https", res["note"])

    def test_clear_removes_file(self):
        wd.set_url("https://dav.example.com/x")
        self.assertTrue(wd.config_path().exists())
        wd.set_url("")
        self.assertFalse(wd.config_path().exists())


class RemoteGuardTest(_Base):
    def test_push_requires_url(self):
        res = wd.push()
        self.assertFalse(res["ok"])
        self.assertIn("URL", res["reason"])

    def test_push_requires_credential(self):
        wd.set_url("https://dav.example.com/x")
        res = wd.push()
        self.assertFalse(res["ok"])
        self.assertIn("凭据", res["reason"])

    def test_check_remote_reports_auth_failure(self):
        wd.set_url("https://dav.example.com/x")
        wd.set_credential("alice:pw")
        with mock.patch.object(wd, "_http_status", return_value=401):
            res = wd.check_remote()
        self.assertFalse(res["ok"])
        self.assertIn("认证失败", res["reason"])

    def test_check_remote_ok(self):
        wd.set_url("https://dav.example.com/x")
        wd.set_credential("alice:pw")
        with mock.patch.object(wd, "_http_status", return_value=207):
            res = wd.check_remote()
        self.assertTrue(res["ok"])

    def test_check_remote_unreachable(self):
        wd.set_url("https://dav.example.com/x")
        wd.set_credential("alice:pw")
        with mock.patch.object(wd, "_http_status", return_value=0):
            res = wd.check_remote()
        self.assertFalse(res["ok"])
        self.assertIn("无法连接", res["reason"])


class PushPullTest(_Base):
    def _ready(self):
        wd.set_url("https://dav.example.com/x")
        wd.set_credential("alice:pw")
        (self.data / "local_overrides.yaml").write_text("a: 1\n", encoding="utf-8")

    def test_push_skips_missing_files(self):
        self._ready()
        with mock.patch.object(wd, "check_remote", return_value={"ok": True}), \
             mock.patch.object(wd, "_http_status", return_value=404), \
             mock.patch.object(wd, "_curl", return_value=(b"", 0, "")):
            res = wd.push()
        self.assertTrue(res["ok"])
        actions = {r["file"]: r["action"] for r in res["results"]}
        self.assertEqual(actions["local_overrides.yaml"], "uploaded")
        self.assertEqual(actions["market_sources.yaml"], "skipped")

    def test_push_backs_up_remote_before_overwrite(self):
        """推送前必须留下远端旧值，否则覆盖后无法比对/回退。"""
        self._ready()
        with mock.patch.object(wd, "check_remote", return_value={"ok": True}), \
             mock.patch.object(wd, "_http_status", return_value=200), \
             mock.patch.object(wd, "_curl", return_value=(b"remote-old", 0, "")):
            wd.push()
        backups = list(self.data.glob("local_overrides.yaml.remote-*"))
        self.assertEqual(len(backups), 1, "应留下远端旧值备份")
        self.assertEqual(backups[0].read_bytes(), b"remote-old")

    def test_push_dry_run_writes_nothing(self):
        self._ready()
        with mock.patch.object(wd, "check_remote", return_value={"ok": True}), \
             mock.patch.object(wd, "_http_status", return_value=404), \
             mock.patch.object(wd, "_curl", return_value=(b"", 0, "")) as curl:
            res = wd.push(dry_run=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["results"][0]["action"], "would-upload")
        self.assertFalse(curl.called, "dry-run 不应发起上传")

    def test_pull_backs_up_local_before_overwrite(self):
        self._ready()
        with mock.patch.object(wd, "check_remote", return_value={"ok": True}), \
             mock.patch.object(wd, "_http_status", return_value=200), \
             mock.patch.object(wd, "_curl", return_value=(b"remote-new", 0, "")):
            res = wd.pull()
        self.assertTrue(res["ok"])
        self.assertEqual((self.data / "local_overrides.yaml").read_bytes(), b"remote-new")
        backups = list(self.data.glob("local_overrides.yaml.bak-*"))
        self.assertEqual(len(backups), 1, "覆盖前应备份本地旧值")
        self.assertEqual(backups[0].read_bytes(), b"a: 1\n")

    def test_pull_skips_remote_missing(self):
        self._ready()
        with mock.patch.object(wd, "check_remote", return_value={"ok": True}), \
             mock.patch.object(wd, "_http_status", return_value=404):
            res = wd.pull()
        self.assertTrue(res["ok"])
        self.assertEqual(res["results"][0]["action"], "skipped")

    def test_pull_fails_on_remote_error(self):
        self._ready()
        with mock.patch.object(wd, "check_remote", return_value={"ok": True}), \
             mock.patch.object(wd, "_http_status", return_value=500):
            res = wd.pull()
        self.assertFalse(res["ok"])

    def test_upload_failure_is_reported_not_swallowed(self):
        self._ready()
        with mock.patch.object(wd, "check_remote", return_value={"ok": True}), \
             mock.patch.object(wd, "_http_status", return_value=404), \
             mock.patch.object(wd, "_curl", return_value=(None, 22, "HTTP 500")):
            res = wd.push()
        self.assertFalse(res["ok"])
        self.assertEqual(res["results"][0]["action"], "failed")
        self.assertIn("500", res["results"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
