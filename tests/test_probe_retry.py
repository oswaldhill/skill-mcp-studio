"""端点探活重试护栏。

背景：总览「MCP 探活正常」卡把「端点探活」等同于「审计结论」，且后端对
单次 socket 超时不做任何重试——远程网关偶发抖动一次，卡片就从 N/N 翻成 0/N，
用户看到「MCP 不正常」而实际端点可用（k8s.carobo.cn 正常约 0.4s 但会偶发超时）。

本护栏锁定两件事：
* ``probe_mcp`` 对 initialize 与 tools/list 两阶段的瞬时网络错误重试 ``retries`` 次；
* 一旦拿到业务响应就停止重试，成功路径的调用次数与不重试时完全一致，
  因此审计结论（result_ok）语义不受影响，只是少报一次「假故障」。
"""

import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

import mcp_probe  # noqa: E402

URL = "https://example.test/mcp"


def _probe(**kw):
    return mcp_probe.probe_mcp(URL, **kw)


class _FakePost:
    """按 JSON-RPC method 分派的假 ``_post``，可注入前 N 次瞬时失败。"""

    def __init__(self, fail_times=0, always_fail=False, tools=("a", "b")):
        self.fail_times = fail_times
        self.always_fail = always_fail
        self.tools = list(tools)
        self.initialize_calls = 0
        self.methods = []

    def __call__(self, url, payload, *, session_id="", token="", timeout=8.0):
        method = payload.get("method")
        self.methods.append(method)
        if method == "initialize":
            self.initialize_calls += 1
            if self.always_fail or self.initialize_calls <= self.fail_times:
                raise urllib.error.URLError("timed out")
            return {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-03-26"}}, ""
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": t} for t in self.tools]}}, ""
        return {}, ""  # notifications/initialized


class ProbeRetryTest(unittest.TestCase):
    def _run(self, fake, **kw):
        with mock.patch.object(mcp_probe, "_post", fake):
            return _probe(token="tk", **kw)

    def test_transient_timeout_recovers_with_one_retry(self):
        fake = _FakePost(fail_times=1)
        out = self._run(fake, retries=1)
        self.assertEqual(fake.initialize_calls, 2, "应恰好重试 1 次")
        self.assertTrue(out["initialize_ok"])
        self.assertTrue(out["tools_list_ok"])
        self.assertEqual(out["error"], "", "重试成功后不应残留错误")
        self.assertEqual(out["tool_names"], ["a", "b"])

    def test_default_retries_is_zero_so_other_callers_are_unchanged(self):
        fake = _FakePost(fail_times=1)
        out = self._run(fake)  # 不传 retries
        self.assertEqual(fake.initialize_calls, 1, "默认不重试，保持向后兼容")
        self.assertFalse(out["initialize_ok"])
        self.assertIn("timed out", out["error"])

    def test_exhausted_retries_still_report_the_real_error(self):
        fake = _FakePost(always_fail=True)
        out = self._run(fake, retries=1)
        self.assertEqual(fake.initialize_calls, 2, "重试次数用尽即停止")
        self.assertFalse(out["initialize_ok"])
        self.assertFalse(out["tools_list_ok"])
        self.assertIn("timed out", out["error"], "真实故障不得被重试掩盖")

    def test_success_path_calls_are_identical_with_and_without_retry(self):
        plain = _FakePost()
        out0 = self._run(plain, retries=0)
        retried = _FakePost()
        out1 = self._run(retried, retries=2)
        self.assertEqual(plain.initialize_calls, 1)
        self.assertEqual(retried.initialize_calls, 1, "成功一次即停，不做多余请求")
        self.assertEqual(plain.methods, retried.methods)
        self.assertEqual(out0, out1, "成功路径结果与重试设置无关")

    def test_business_error_is_not_retried(self):
        """initialize 返回业务错误（非网络异常）时应立即上报，不消耗重试。"""
        calls = []

        def fake(url, payload, *, session_id="", token="", timeout=8.0):
            if payload.get("method") == "initialize":
                calls.append(1)
                return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "bad request"}}, ""
            return {}, ""

        out = self._run(fake, retries=3)
        self.assertEqual(len(calls), 1, "业务错误不重试")
        self.assertFalse(out["initialize_ok"])
        self.assertIn("bad request", out["error"])


    def test_tools_list_transient_timeout_recovers_with_retry(self):
        """tools/list 阶段的瞬时网络错误同样重试，成功后 error 仍为空。"""
        tools_calls = {"n": 0}

        def fake(url, payload, *, session_id="", token="", timeout=8.0):
            method = payload.get("method")
            if method == "initialize":
                return {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-03-26"}}, ""
            if method == "tools/list":
                tools_calls["n"] += 1
                if tools_calls["n"] == 1:
                    raise urllib.error.URLError("timed out")
                return {"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "a"}, {"name": "b"}]}}, ""
            return {}, ""

        out = self._run(fake, retries=1)
        self.assertEqual(tools_calls["n"], 2, "tools/list 应恰好重试 1 次")
        self.assertTrue(out["initialize_ok"])
        self.assertTrue(out["tools_list_ok"])
        self.assertEqual(out["error"], "", "重试成功后不应残留错误")
        self.assertEqual(out["tool_names"], ["a", "b"])

    def test_tools_list_exhausted_retries_still_report_real_error(self):
        """tools/list 持续瞬时失败且重试耗尽时，应上报真实错误而非掩盖。"""

        def fake(url, payload, *, session_id="", token="", timeout=8.0):
            if payload.get("method") == "initialize":
                return {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-03-26"}}, ""
            if payload.get("method") == "tools/list":
                raise urllib.error.URLError("timed out")
            return {}, ""

        out = self._run(fake, retries=1)
        self.assertTrue(out["initialize_ok"])
        self.assertFalse(out["tools_list_ok"])
        self.assertIn("timed out", out["error"], "tools/list 真实故障不得被重试掩盖")


if __name__ == "__main__":
    unittest.main()
