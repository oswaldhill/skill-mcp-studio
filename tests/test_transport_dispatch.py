"""Transport abstraction tests (评审 CLI-5 整改回归).

覆盖：
- §5.2 接口形态：ProbeSpec / Transport 协议 / TRANSPORTS 注册表 / dispatch_probe；
- CLI-5a：单一 deadline 预算——超时不再按每步独立计时（≤ 2× 预算内必返回）；
- stdio 分支经由统一分派（probe_mcp → dispatch_probe → StdioTransport）。
"""

import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from transport import (  # noqa: E402
    HttpTransport,
    ProbeSpec,
    StdioProbeError,
    StdioTransport,
    TRANSPORTS,
    Transport,
    dispatch_probe,
    get_transport,
    probe_stdio,
)
from mcp_probe import probe_mcp  # noqa: E402

SLOW_SERVER = r"""
import time
time.sleep(30)  # 永不响应：用于验证超时预算
"""

FAKE_SERVER = r"""
import json
import sys

def respond(request_id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue
    if msg.get("method") == "initialize":
        respond(msg["id"], {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "fake"}})
    elif msg.get("method") == "tools/list":
        respond(msg["id"], {"tools": [{"name": "dispatch_ping"}]})
"""


class RegistryTest(unittest.TestCase):
    def test_registry_covers_whitelist(self):
        self.assertEqual(set(TRANSPORTS), {"streamable-http", "stdio"})

    def test_registered_transports_satisfy_protocol(self):
        for name, transport in TRANSPORTS.items():
            self.assertIsInstance(transport, Transport)
            self.assertTrue(hasattr(transport, "probe"))
            self.assertEqual(transport.name, name)

    def test_get_transport_resolves_and_rejects_unknown(self):
        self.assertIsInstance(get_transport("stdio"), StdioTransport)
        self.assertIsInstance(get_transport("streamable-http"), HttpTransport)
        with self.assertRaises(StdioProbeError) as ctx:
            get_transport("websocket")
        self.assertIn("websocket", str(ctx.exception))

    def test_probe_spec_defaults(self):
        spec = ProbeSpec()
        self.assertEqual(spec.transport, "streamable-http")
        self.assertEqual(spec.args, ())
        self.assertEqual(spec.env, {})
        self.assertEqual(spec.url_policy, "strict")

    def test_probe_spec_is_frozen(self):
        spec = ProbeSpec()
        with self.assertRaises(Exception):
            spec.url = "https://x/mcp"  # type: ignore[misc]

    def test_stdio_transport_requires_command(self):
        with self.assertRaises(StdioProbeError):
            StdioTransport().probe(ProbeSpec(transport="stdio"), timeout=1.0)


class DispatchStdioTest(unittest.TestCase):
    def test_dispatch_stdio_handshake(self):
        spec = ProbeSpec(transport="stdio", command=sys.executable, args=("-c", FAKE_SERVER))
        result = dispatch_probe(spec, timeout=5.0)
        self.assertTrue(result["initialize_ok"], result["error"])
        self.assertTrue(result["tools_list_ok"], result["error"])
        self.assertEqual(result["tool_names"], ["dispatch_ping"])

    def test_dispatch_unknown_transport_fails(self):
        with self.assertRaises(StdioProbeError):
            dispatch_probe(ProbeSpec(transport="carrier-pigeon"), timeout=1.0)

    def test_probe_mcp_stdio_goes_through_dispatch(self):
        # probe_mcp 的 stdio 分支现在经由统一分派，行为不变。
        result = probe_mcp(
            "", transport="stdio", command=sys.executable,
            args=["-c", FAKE_SERVER], timeout=5.0,
        )
        self.assertTrue(result["initialize_ok"], result["error"])
        self.assertEqual(result["tool_names"], ["dispatch_ping"])


class DeadlineBudgetTest(unittest.TestCase):
    """CLI-5a：timeout 是覆盖启动 + 两次握手的单一预算。"""

    def test_silent_server_respects_single_budget(self):
        timeout = 1.5
        start = time.monotonic()
        result = probe_stdio(sys.executable, args=["-c", SLOW_SERVER], timeout=timeout)
        elapsed = time.monotonic() - start
        self.assertFalse(result["initialize_ok"])
        self.assertIn("timed out", result["error"])
        # 旧实现每步独立计时 → 最多 ~2×timeout；单一预算下应 ≤ timeout + 收尾余量。
        self.assertLess(elapsed, timeout * 1.6, f"elapsed={elapsed:.2f}s 超出单一预算语义")

    def test_dispatch_inherits_budget_semantics(self):
        timeout = 1.5
        start = time.monotonic()
        result = dispatch_probe(
            ProbeSpec(transport="stdio", command=sys.executable, args=("-c", SLOW_SERVER)),
            timeout=timeout,
        )
        elapsed = time.monotonic() - start
        self.assertFalse(result["initialize_ok"])
        self.assertLess(elapsed, timeout * 1.6)


if __name__ == "__main__":
    unittest.main()
