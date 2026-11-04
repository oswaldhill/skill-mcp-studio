"""端点凭据来源的 CLI 契约：``--endpoint-auth-*`` / ``--auth-secret-status`` / ``--set-auth-secret``。

为什么在 CLI 层再测一遍（引擎层已有单测）：GUI 只通过 ``run_cli`` 与引擎交互，
参数名、退出码、JSON 结构与「不许回显明文」这几条契约一旦漂移，界面会静默坏掉，
而引擎单测全绿。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CORE = str(ROOT / "core")


def _run_cli(args, cwd, extra_env=None):
    env = {**os.environ, "PYTHONPATH": CORE}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(ROOT / "scan.py")] + args,
        capture_output=True, text=True, cwd=cwd, timeout=120, env=env,
    )


class AuthSecretCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.overlay = Path(self.tmp) / "overlay.yaml"
        self.config = Path(self.tmp) / "config.yaml"
        self.config.write_text(
            "schema_version: 2\n"
            "active_profile: hermes\n"
            "profile_sources:\n"
            f"  - {self.overlay}\n"
            "profiles:\n"
            "  hermes:\n"
            "    name: hermes\n"
            "    url: https://hermes.example.com/mcp\n"
            "    transport: streamable-http\n"
            "mcp_tools: []\n",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cli(self, *args, extra_env=None):
        return _run_cli(["--config", str(self.config), *args], self.tmp, extra_env)

    def overlay_data(self):
        return yaml.safe_load(self.overlay.read_text(encoding="utf-8"))

    # ── 写声明 ────────────────────────────────────────────────────
    def test_update_endpoint_binds_keychain_source(self):
        r = self.cli("--update-endpoint", "hermes",
                     "--endpoint-auth-mode", "keychain",
                     "--endpoint-auth-keychain", "hermes-unified-mcp")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        profile = self.overlay_data()["profiles"]["hermes"]
        self.assertEqual(profile["auth_mode"], "keychain")
        self.assertEqual(profile["auth_keychain"], "hermes-unified-mcp")
        # 引用型不在端点库里存明文
        self.assertNotIn("auth_token", profile)

    def test_reference_mode_requires_a_source(self):
        r = self.cli("--update-endpoint", "hermes", "--endpoint-auth-mode", "env")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--endpoint-auth-env", r.stdout)

    def test_reference_mode_rejects_plaintext_token_argument(self):
        r = self.cli("--update-endpoint", "hermes",
                     "--endpoint-auth-mode", "keychain",
                     "--endpoint-auth-keychain", "svc",
                     "--endpoint-auth-token", "SECRET")
        self.assertEqual(r.returncode, 2)
        self.assertIn("互斥", r.stdout)

    def test_switching_back_to_plaintext_requires_token(self):
        r = self.cli("--update-endpoint", "hermes", "--endpoint-auth-mode", "token")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--endpoint-auth-token", r.stdout)

    def test_add_endpoint_with_env_source(self):
        r = self.cli("--add-endpoint", "ep2", "--endpoint-name", "ep2",
                     "--endpoint-url", "https://ep2.example.com/mcp",
                     "--endpoint-auth-mode", "env",
                     "--endpoint-auth-env", "EP2_TOKEN")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        profile = self.overlay_data()["profiles"]["ep2"]
        self.assertEqual(profile["auth_mode"], "env")
        self.assertEqual(profile["auth_token_env"], "EP2_TOKEN")

    # ── 状态查询 ──────────────────────────────────────────────────
    def test_status_json_is_masked_and_reports_env_presence(self):
        self.cli("--update-endpoint", "hermes", "--endpoint-auth-mode", "env",
                 "--endpoint-auth-env", "STUDIO_STATUS_TOKEN")
        r = self.cli("--auth-secret-status", "hermes", "--format", "json",
                     extra_env={"STUDIO_STATUS_TOKEN": "super-secret-value"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["mode"], "env")
        self.assertTrue(payload["configured"])
        self.assertTrue(payload["available"])
        self.assertTrue(payload["process_env_set"])
        # 明文绝不出现在输出里
        self.assertNotIn("super-secret-value", r.stdout)

    def test_status_reports_missing_env_variable(self):
        self.cli("--update-endpoint", "hermes", "--endpoint-auth-mode", "env",
                 "--endpoint-auth-env", "NO_SUCH_STUDIO_VAR")
        r = self.cli("--auth-secret-status", "hermes", "--format", "json")
        # --format json 是显式查询：状态在 JSON 里表达，退出码保持 0（与
        # --set-github-token 的 JSON 出口一致）；只有文本模式下不可用才退 1。
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        payload = json.loads(r.stdout)
        self.assertFalse(payload["available"])
        # 默认不读内容 → error 为空，但变量名要在 source 里可见，GUI 才能告诉
        # 用户「是哪个变量没设」。加 --check-credential 才给出具体原因。
        self.assertEqual(payload["source"], "NO_SUCH_STUDIO_VAR")
        checked = json.loads(
            self.cli("--auth-secret-status", "hermes", "--check-credential", "--format", "json").stdout
        )
        self.assertIn("NO_SUCH_STUDIO_VAR", checked["error"])

    def test_status_all_lists_every_endpoint(self):
        r = self.cli("--auth-secret-status", "all", "--format", "json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["kind"], "auth-secret-status")
        self.assertEqual([e["endpoint_key"] for e in payload["endpoints"]], ["hermes"])

    def test_status_unknown_endpoint_exits_2(self):
        r = self.cli("--auth-secret-status", "nope")
        self.assertEqual(r.returncode, 2)

    def test_status_check_flag_reports_checked(self):
        r = self.cli("--auth-secret-status", "hermes", "--check-credential", "--format", "json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(json.loads(r.stdout)["checked"])

    # ── 写入来源 ──────────────────────────────────────────────────
    def test_set_auth_secret_writes_file_with_owner_only_mode(self):
        path = Path(self.tmp) / "creds" / "token"
        self.cli("--update-endpoint", "hermes", "--endpoint-auth-mode", "file",
                 "--endpoint-auth-file", str(path))
        r = self.cli("--set-auth-secret", "hermes", "--endpoint-auth-mode", "file",
                     "--endpoint-auth-token", "file-secret-value")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(path.read_text(encoding="utf-8").strip(), "file-secret-value")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        # 端点库应保持「只有引用」：文件模式不得回写明文
        self.assertNotIn("auth_token", self.overlay_data()["profiles"]["hermes"])

    def test_set_auth_secret_can_clear_the_source(self):
        path = Path(self.tmp) / "token"
        path.write_text("x\n", encoding="utf-8")
        self.cli("--update-endpoint", "hermes", "--endpoint-auth-mode", "file",
                 "--endpoint-auth-file", str(path))
        r = self.cli("--set-auth-secret", "hermes", "--endpoint-auth-mode", "file",
                     "--endpoint-auth-token", "")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(path.exists())

    def test_set_auth_secret_refuses_env_mode(self):
        # env 的凭据由用户的 shell / 客户端环境管理，代写 shell profile 属于越权。
        self.cli("--update-endpoint", "hermes", "--endpoint-auth-mode", "env",
                 "--endpoint-auth-env", "SOME_VAR")
        r = self.cli("--set-auth-secret", "hermes", "--endpoint-auth-mode", "env",
                     "--endpoint-auth-token", "abc")
        self.assertEqual(r.returncode, 2)
        self.assertIn("不代写", r.stdout)

    def test_list_endpoints_shows_auth_summary_without_secret(self):
        self.cli("--update-endpoint", "hermes", "--endpoint-auth-mode", "keychain",
                 "--endpoint-auth-keychain", "hermes-unified-mcp")
        r = self.cli("--list-endpoints")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("keychain:hermes-unified-mcp", r.stdout)

    def test_test_endpoint_reports_credential_error_without_network(self):
        r = self.cli("--update-endpoint", "hermes", "--endpoint-auth-mode", "env",
                     "--endpoint-auth-env", "NO_SUCH_STUDIO_VAR")
        self.assertEqual(r.returncode, 0)
        r = self.cli("--test-endpoint", "hermes", "--format", "json")
        payload = json.loads(r.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("凭据不可用", payload["error"])
        self.assertEqual(payload["auth_mode"], "env")


if __name__ == "__main__":
    unittest.main()
