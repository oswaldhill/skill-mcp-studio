"""探活的凭据来源：keychain / file 引用型必须按引用取到真值（v0.31.4 之后）。

为什么单独守这条：客户端配置里写的是引用，探活如果还用旧逻辑（只认
``auth_token`` / 环境变量），就会出现「客户端能用、审计说 401」或反过来的
分裂结论 —— 而审计工具的价值恰恰在于它的结论可信。

另一半同样重要：**取不到时不能静默回落**到环境变量。回落会把「凭据来源配错」
伪装成「端点故障」，用户会去查网络。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import mcp_probe  # noqa: E402

URL = "https://hermes.example.com/mcp"


def _capture_token():
    """替身 _post：记录第一次调用收到的 token，返回一个最小可用的 initialize 结果。"""
    calls = []

    def fake_post(url, payload, *, session_id="", token="", timeout=8.0):
        calls.append(token)
        if payload.get("method") == "initialize":
            return {"result": {"protocolVersion": "2025-03-26"}}, "sess-1"
        if payload.get("method") == "tools/list":
            return {"result": {"tools": [{"name": "ping"}]}}, "sess-1"
        return {}, "sess-1"

    return calls, fake_post


class KeychainSourceTest(unittest.TestCase):
    def test_keychain_reference_is_resolved_before_probing(self):
        calls, fake_post = _capture_token()
        with patch.object(mcp_probe, "_post", side_effect=fake_post), \
             patch("auth_secret.keychain_read", return_value="from-keychain") as reader:
            result = mcp_probe.probe_mcp(URL, auth_keychain="hermes-unified-mcp")
        self.assertTrue(result["initialize_ok"])
        self.assertEqual(calls[0], "from-keychain")
        reader.assert_called_once()

    def test_unreadable_keychain_fails_loudly_instead_of_falling_back_to_env(self):
        calls, fake_post = _capture_token()
        with patch.object(mcp_probe, "_post", side_effect=fake_post), \
             patch("auth_secret.keychain_read", side_effect=RuntimeError("钥匙串条目 'x' 不可读：denied")), \
             patch.dict(os.environ, {"HERMES_MCP_AUTH_TOKEN": "env-fallback"}, clear=False):
            result = mcp_probe.probe_mcp(URL, auth_keychain="x")
        self.assertFalse(result["initialize_ok"])
        self.assertIn("凭据不可用", result["error"])
        self.assertIn("denied", result["error"])
        # 关键：没有发起任何请求 —— 否则就要用一个错误 token 去撞鉴权
        self.assertEqual(calls, [])


class FileSourceTest(unittest.TestCase):
    def test_file_reference_is_resolved_before_probing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "token")
            Path(path).write_text("from-file\n", encoding="utf-8")
            calls, fake_post = _capture_token()
            with patch.object(mcp_probe, "_post", side_effect=fake_post):
                result = mcp_probe.probe_mcp(URL, auth_file=path)
        self.assertTrue(result["initialize_ok"])
        self.assertEqual(calls[0], "from-file")

    def test_missing_file_is_reported_with_path(self):
        calls, fake_post = _capture_token()
        with patch.object(mcp_probe, "_post", side_effect=fake_post):
            result = mcp_probe.probe_mcp(URL, auth_file="/nonexistent/studio-token")
        self.assertFalse(result["initialize_ok"])
        self.assertIn("凭据文件不可读", result["error"])
        self.assertEqual(calls, [])


class LegacyBehaviourTest(unittest.TestCase):
    def test_env_var_still_used_when_no_reference_mode(self):
        calls, fake_post = _capture_token()
        with patch.object(mcp_probe, "_post", side_effect=fake_post), \
             patch.dict(os.environ, {"HERMES_MCP_AUTH_TOKEN": "env-token"}, clear=False):
            mcp_probe.probe_mcp(URL)
        self.assertEqual(calls[0], "env-token")

    def test_explicit_token_still_wins_over_env(self):
        calls, fake_post = _capture_token()
        with patch.object(mcp_probe, "_post", side_effect=fake_post), \
             patch.dict(os.environ, {"HERMES_MCP_AUTH_TOKEN": "env-token"}, clear=False):
            mcp_probe.probe_mcp(URL, token="explicit")
        self.assertEqual(calls[0], "explicit")


class CheckerPlumbingTest(unittest.TestCase):
    """组合检查器 / 端点状态必须把 auth_keychain / auth_file 传下去。"""

    def _probe_args(self, module_name):
        import importlib

        module = importlib.import_module(module_name)
        captured = {}

        def fake_probe(url, **kwargs):
            captured.update(kwargs)
            return {"initialize_ok": True, "tools_list_ok": True, "tool_names": ["x"], "error": ""}

        return module, captured, fake_probe

    def test_endpoint_status_forwards_reference_fields(self):
        module, captured, fake_probe = self._probe_args("mcp_endpoint_status")
        with patch.object(module, "probe_mcp", side_effect=fake_probe):
            module._probe_with_profile_timing({
                "url": URL,
                "auth_mode": "keychain",
                "auth_keychain": "svc",
            })
        self.assertEqual(captured.get("auth_keychain"), "svc")
        self.assertIsNone(captured.get("auth_file"))

    def test_combined_checker_forwards_reference_fields(self):
        # 审计路径（combined_checker）不与端点状态共用代码，必须同样传参，
        # 否则会出现「审计说 401、端点状态说连通」的分裂结论。
        module, captured, fake_probe = self._probe_args("combined_checker")
        import inspect

        source = inspect.getsource(module)
        for field in ("auth_keychain", "auth_file"):
            self.assertIn(
                f'{field}=expected.get("{field}")', source,
                f"combined_checker 未把 {field} 传给 probe_mcp",
            )


if __name__ == "__main__":
    unittest.main()
