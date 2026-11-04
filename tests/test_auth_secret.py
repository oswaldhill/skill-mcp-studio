"""端点凭据来源（auth_mode）核心逻辑的回归测试（v0.31.4 之后）。

覆盖 ``core/auth_secret.py`` 的四条判据：

1. ``resolve_auth`` 对四种模式各走对的来源，失败时报**可读原因**而不是空 token；
2. 引用型**绝不**把明文写进返回值（只在探活路径按需取真值）；
3. ``describe_auth`` 默认不读内容（读钥匙串会弹系统授权 → 在 GUI/CI 里会把
   「看状态」变成 10 秒卡顿），且**任何路径都不返回完整明文**；
4. 钥匙串读写走的是 ``security`` / ``secret-tool`` 命令行 —— 用假的可执行文件
   替身验证参数装配与错误传播，不在测试里碰真钥匙串。
"""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import auth_secret  # noqa: E402


class NormalizeAuthModeTest(unittest.TestCase):
    def test_default_is_plaintext_token(self):
        # 历史配置没有 auth_mode —— 必须原样按明文 token 处理，否则存量用户
        # 的客户端配置会在升级后突然丢掉 Authorization 头。
        self.assertEqual(auth_secret.normalize_auth_mode({}), "token")
        self.assertEqual(auth_secret.normalize_auth_mode({"auth_mode": None}), "token")

    def test_known_modes_are_case_insensitive(self):
        for raw in ("keychain", "KEYCHAIN", " File ", "env"):
            with self.subTest(raw=raw):
                self.assertEqual(
                    auth_secret.normalize_auth_mode({"auth_mode": raw}),
                    raw.strip().lower(),
                )

    def test_unknown_mode_falls_back_to_token(self):
        # 未知取值不抛错：auth_mode 是新增字段，手写错了也不能让整份配置不可用。
        self.assertEqual(auth_secret.normalize_auth_mode({"auth_mode": "vault"}), "token")


class MaskTokenTest(unittest.TestCase):
    def test_mask_never_returns_full_secret(self):
        secret = "sk-live-0123456789abcdef"
        masked = auth_secret.mask_token(secret)
        self.assertNotEqual(masked, secret)
        self.assertNotIn("0123456789", masked)
        self.assertTrue(masked.startswith("sk-l"))
        self.assertTrue(masked.endswith("cdef"))

    def test_short_tokens_are_fully_masked(self):
        self.assertEqual(auth_secret.mask_token("abc"), "****")
        self.assertEqual(auth_secret.mask_token("12345678"), "****")
        self.assertEqual(auth_secret.mask_token(""), "")


class RedactProfileTest(unittest.TestCase):
    def test_plaintext_token_is_replaced(self):
        out = auth_secret.redact_profile({"name": "hermes", "auth_token": "SECRET"})
        self.assertEqual(out["auth_token"], auth_secret.REDACTED)
        self.assertEqual(out["name"], "hermes")

    def test_reference_modes_have_nothing_to_redact(self):
        profile = {"auth_mode": "keychain", "auth_keychain": "hermes-unified-mcp"}
        self.assertEqual(auth_secret.redact_profile(profile), profile)

    def test_original_profile_is_not_mutated(self):
        profile = {"auth_token": "SECRET"}
        auth_secret.redact_profile(profile)
        self.assertEqual(profile["auth_token"], "SECRET")


class AuthConfiguredTest(unittest.TestCase):
    def test_each_mode_checks_its_own_field(self):
        self.assertTrue(auth_secret.auth_configured({"auth_token": "x"}))
        self.assertTrue(auth_secret.auth_configured({"auth_mode": "env", "auth_token_env": "V"}))
        self.assertTrue(auth_secret.auth_configured({"auth_mode": "keychain", "auth_keychain": "S"}))
        self.assertTrue(auth_secret.auth_configured({"auth_mode": "file", "auth_file": "/p"}))
        # 模式选对了但来源没填 = 未配置（不能因为「选了模式」就当配置好了）
        self.assertFalse(auth_secret.auth_configured({"auth_mode": "keychain"}))
        self.assertFalse(auth_secret.auth_configured({"auth_mode": "env"}))


class ResolveAuthTest(unittest.TestCase):
    def test_env_mode_reads_named_variable(self):
        with patch.dict(os.environ, {"STUDIO_TEST_TOKEN": "env-secret"}, clear=False):
            resolved = auth_secret.resolve_auth(
                {"auth_mode": "env", "auth_token_env": "STUDIO_TEST_TOKEN"}
            )
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["token"], "env-secret")
        self.assertEqual(resolved["source"], "STUDIO_TEST_TOKEN")

    def test_env_mode_reports_missing_variable_by_name(self):
        with patch.dict(os.environ, {}, clear=True):
            resolved = auth_secret.resolve_auth(
                {"auth_mode": "env", "auth_token_env": "NO_SUCH_VAR_XYZ"}
            )
        self.assertFalse(resolved["ok"])
        self.assertEqual(resolved["token"], "")
        self.assertIn("NO_SUCH_VAR_XYZ", resolved["error"])

    def test_env_mode_without_name_uses_legacy_default(self):
        with patch.dict(os.environ, {"HERMES_MCP_AUTH_TOKEN": "legacy"}, clear=False):
            resolved = auth_secret.resolve_auth({"auth_mode": "env"})
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["source"], auth_secret.DEFAULT_ENV_VAR)

    def test_file_mode_reads_and_strips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "token")
            Path(path).write_text("  file-secret\n", encoding="utf-8")
            resolved = auth_secret.resolve_auth({"auth_mode": "file", "auth_file": path})
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["token"], "file-secret")
        self.assertEqual(resolved["source"], path)

    def test_file_mode_missing_file_is_a_readable_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolved = auth_secret.resolve_auth(
                {"auth_mode": "file", "auth_file": os.path.join(tmp, "nope")}
            )
        self.assertFalse(resolved["ok"])
        self.assertIn("凭据文件不可读", resolved["error"])

    def test_keychain_mode_failure_is_reported_not_raised(self):
        with patch.object(auth_secret, "keychain_read", side_effect=RuntimeError("钥匙串条目 'x' 不可读")):
            resolved = auth_secret.resolve_auth(
                {"auth_mode": "keychain", "auth_keychain": "x"}
            )
        self.assertFalse(resolved["ok"])
        self.assertIn("钥匙串", resolved["error"])
        self.assertEqual(resolved["token"], "")

    def test_plaintext_mode_returns_token(self):
        resolved = auth_secret.resolve_auth({"auth_token": "plain"})
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["token"], "plain")


class ResolveForFixTest(unittest.TestCase):
    def test_reference_modes_never_read_the_secret(self):
        # 渲染客户端配置只需要「引用怎么写」；若这里去读钥匙串，--fix-mcp 就会
        # 因为授权弹窗未点而失败。用会抛错的替身证明它根本没被调用。
        with patch.object(auth_secret, "keychain_read", side_effect=AssertionError("不该被调用")):
            resolved = auth_secret.resolve_for_fix(
                {"auth_mode": "keychain", "auth_keychain": "svc"}
            )
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["mode"], "keychain")

    def test_reference_mode_without_source_is_not_ok(self):
        resolved = auth_secret.resolve_for_fix({"auth_mode": "keychain"})
        self.assertFalse(resolved["ok"])
        self.assertIn("未声明", resolved["error"])

    def test_plaintext_mode_still_resolves_token(self):
        resolved = auth_secret.resolve_for_fix({"auth_token": "plain"})
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["token"], "plain")


class DescribeAuthTest(unittest.TestCase):
    def test_default_does_not_read_the_secret(self):
        with patch.object(auth_secret, "keychain_read", side_effect=AssertionError("默认不应读取")):
            with patch.object(auth_secret, "keychain_entry_exists", return_value=True):
                status = auth_secret.describe_auth(
                    {"auth_mode": "keychain", "auth_keychain": "svc"}
                )
        self.assertTrue(status["available"])
        self.assertFalse(status["checked"])
        self.assertEqual(status["masked"], "")

    def test_check_mode_reads_but_only_returns_masked_value(self):
        with patch.object(auth_secret, "keychain_read", return_value="abcdefgh12345678"):
            status = auth_secret.describe_auth(
                {"auth_mode": "keychain", "auth_keychain": "svc"}, check=True
            )
        self.assertTrue(status["checked"])
        self.assertTrue(status["available"])
        self.assertNotIn("abcdefgh12345678", str(status))

    def test_unconfigured_token_mode_reports_not_configured(self):
        status = auth_secret.describe_auth({})
        self.assertEqual(status["mode"], "token")
        self.assertFalse(status["configured"])
        self.assertIsNone(status["available"])

    def test_env_mode_without_process_value_is_unavailable(self):
        with patch.dict(os.environ, {}, clear=True):
            status = auth_secret.describe_auth(
                {"auth_mode": "env", "auth_token_env": "NO_SUCH_VAR_XYZ"}
            )
        self.assertTrue(status["configured"])
        self.assertFalse(status["available"])

    def test_file_mode_availability_comes_from_file_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t")
            Path(path).write_text("", encoding="utf-8")
            status = auth_secret.describe_auth({"auth_mode": "file", "auth_file": path})
            self.assertFalse(status["available"])
            Path(path).write_text("live\n", encoding="utf-8")
            status = auth_secret.describe_auth({"auth_mode": "file", "auth_file": path})
            self.assertTrue(status["available"])


def _fake_bin_dir(tmp: str, script_body: str, name: str = "security") -> str:
    """在临时目录里造一个假的可执行文件，并把它放到 PATH 最前面。"""
    path = os.path.join(tmp, name)
    Path(path).write_text("#!/bin/sh\n" + script_body + "\n", encoding="utf-8")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


class KeychainCliTest(unittest.TestCase):
    """钥匙串读写走命令行：验证参数装配、回读校验与错误传播。"""

    def test_macos_read_uses_find_generic_password_without_leaking_to_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = os.path.join(tmp, "bin")
            os.makedirs(bin_dir)
            _fake_bin_dir(bin_dir, 'echo "  secret-from-keychain  "')
            with patch.object(auth_secret.sys, "platform", "darwin"), \
                 patch.dict(os.environ, {"PATH": bin_dir + os.pathsep + os.environ["PATH"]}):
                token = auth_secret._macos_keychain_read("svc", "acct")
        self.assertEqual(token, "secret-from-keychain")

    def test_macos_read_failure_surfaces_the_tool_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = os.path.join(tmp, "bin")
            os.makedirs(bin_dir)
            _fake_bin_dir(bin_dir, 'echo "security: SecKeychainSearchCopyNext: not found" >&2; exit 44')
            with patch.object(auth_secret.sys, "platform", "darwin"), \
                 patch.dict(os.environ, {"PATH": bin_dir + os.pathsep + os.environ["PATH"]}):
                with self.assertRaises(RuntimeError) as ctx:
                    auth_secret._macos_keychain_read("svc", "acct")
        self.assertIn("not found", str(ctx.exception))
        self.assertIn("svc", str(ctx.exception))

    def test_denied_exit_code_explains_what_to_do(self):
        # 实测 exit 161 = 条目存在但访问被拒；只说「不可读」帮不上忙。
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = os.path.join(tmp, "bin")
            os.makedirs(bin_dir)
            _fake_bin_dir(bin_dir, "exit 161")
            with patch.object(auth_secret.sys, "platform", "darwin"), \
                 patch.dict(os.environ, {"PATH": bin_dir + os.pathsep + os.environ["PATH"]}):
                with self.assertRaises(RuntimeError) as ctx:
                    auth_secret._macos_keychain_read("svc", "acct")
        message = str(ctx.exception)
        self.assertIn("总是允许", message)
        self.assertIn("--endpoint-auth-mode file", message)

    def test_timeout_explains_the_dialog_instead_of_a_bare_exception(self):
        import subprocess as _sp

        with patch.object(auth_secret.subprocess, "run",
                          side_effect=_sp.TimeoutExpired(cmd="security", timeout=10)):
            with self.assertRaises(RuntimeError) as ctx:
                auth_secret._macos_keychain_read("svc", "acct")
        self.assertIn("授权对话框", str(ctx.exception))
        self.assertIn("svc", str(ctx.exception))

    def test_write_denied_by_sandbox_mentions_alternatives(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = os.path.join(tmp, "bin")
            os.makedirs(bin_dir)
            _fake_bin_dir(bin_dir, 'echo "UNIX[Operation not permitted]" >&2; exit 1')
            with patch.object(auth_secret.sys, "platform", "darwin"), \
                 patch.dict(os.environ, {"PATH": bin_dir + os.pathsep + os.environ["PATH"], "USER": "u"}):
                with self.assertRaises(RuntimeError) as ctx:
                    auth_secret.keychain_write("svc", "tok", "u")
        self.assertIn("Operation not permitted", str(ctx.exception))
        self.assertIn("--endpoint-auth-mode file", str(ctx.exception))

    def test_macos_write_reads_back_to_prove_it_landed(self):
        # `security add-generic-password -U` 在某些钥匙串状态下会「成功但不更新」，
        # 只有回读才能确认真存进去了 —— 这里用「写成功、读失败」的替身验证。
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = os.path.join(tmp, "bin")
            os.makedirs(bin_dir)
            _fake_bin_dir(
                bin_dir,
                'case "$1" in add-generic-password) exit 0 ;; '
                'find-generic-password) echo "readback-failed" >&2; exit 1 ;; esac',
            )
            with patch.object(auth_secret.sys, "platform", "darwin"), \
                 patch.dict(os.environ, {"PATH": bin_dir + os.pathsep + os.environ["PATH"], "USER": "u"}):
                with self.assertRaises(RuntimeError):
                    auth_secret.keychain_write("svc", "tok", "u")

    def test_entry_exists_does_not_pass_the_w_flag(self):
        # 带 -w 会触发内容授权（弹窗）；存在性检查必须只读元数据。
        captured = os.path.join(tempfile.mkdtemp(), "args.txt")
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = os.path.join(tmp, "bin")
            os.makedirs(bin_dir)
            _fake_bin_dir(bin_dir, f'echo "$@" > {captured}; exit 0')
            with patch.object(auth_secret.sys, "platform", "darwin"), \
                 patch.dict(os.environ, {"PATH": bin_dir + os.pathsep + os.environ["PATH"]}):
                self.assertTrue(auth_secret.keychain_entry_exists("svc", "acct"))
        args = Path(captured).read_text(encoding="utf-8")
        self.assertNotIn(" -w", args)
        self.assertIn("find-generic-password", args)

    def test_keychain_write_rejects_empty_secret(self):
        with self.assertRaises(ValueError):
            auth_secret.keychain_write("svc", "   ")


if __name__ == "__main__":
    unittest.main()
