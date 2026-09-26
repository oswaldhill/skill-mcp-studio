import json
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from transport import StdioProbeError, expand_env, probe_stdio  # noqa: E402

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
        respond(msg["id"], {"tools": [{"name": "fake_ping"}, {"name": "fake_read"}]})
    elif msg.get("method") == "notifications/initialized":
        pass  # no response
"""

# P0-5 回归用：向 stderr 写 200 KiB 且**不含换行**的噪音，然后正常握手。
# 200 KiB 超过管道缓冲（POSIX 通常 64 KiB）—— 不排空就会把子进程卡在
# stderr.write 上，它从此不读 stdin，外部只看到「stdio handshake timed out」。
# 判据有效性已反向验证：把排空整个去掉，本用例稳定失败（5.0s 超时）；
# 恢复排空后 0.1s 内通过。
NOISY_STDERR_SERVER = r"""
import json
import sys

sys.stderr.write("x" * 200000)
sys.stderr.flush()

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
        respond(msg["id"], {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "noisy"}})
    elif msg.get("method") == "tools/list":
        respond(msg["id"], {"tools": [{"name": "noisy_ping"}]})
"""

# 只在 stderr 留下一句诊断就退出、完全不回应握手。
STDERR_ONLY_SERVER = r"""
import sys
sys.stderr.write("BOOM: simulated startup failure\n")
sys.stderr.flush()
"""


class ExpandEnvTest(unittest.TestCase):
    def test_expands_reference(self):
        self.assertEqual(expand_env("x${FOO}y", {"FOO": "1"}), "x1y")

    def test_missing_reference_fails(self):
        with self.assertRaises(StdioProbeError):
            expand_env("${MISSING}", {})


class StdioProbeTest(unittest.TestCase):
    def test_handshake_and_tool_names(self):
        result = probe_stdio(
            sys.executable, args=["-c", FAKE_SERVER], timeout=5.0
        )
        self.assertTrue(result["initialize_ok"], result["error"])
        self.assertTrue(result["tools_list_ok"], result["error"])
        self.assertEqual(result["tool_names"], ["fake_ping", "fake_read"])

    def test_missing_command_fails(self):
        result = probe_stdio("definitely-not-a-real-cmd-xyz", timeout=3.0)
        self.assertFalse(result["initialize_ok"])
        self.assertIn("failed to start", result["error"])

    def test_env_expansion_injects_token(self):
        # The fake server doesn't read env, but expansion must succeed.
        os.environ["FAKE_TOKEN_FOR_TEST"] = "secret"
        try:
            result = probe_stdio(
                sys.executable,
                args=["-c", FAKE_SERVER],
                env={"T": "${FAKE_TOKEN_FOR_TEST}"},
                timeout=5.0,
            )
        finally:
            os.environ.pop("FAKE_TOKEN_FOR_TEST", None)
        self.assertTrue(result["initialize_ok"], result["error"])

    def test_noisy_stderr_does_not_block_handshake(self):
        # P0-5 回归：stderr 管道不排空时，子进程会卡在「管道写满」上而不再回应
        # 握手 —— 外部只看到偶发的「stdio handshake timed out」。
        # 判据有效性已反向验证：把排空整个去掉，本用例稳定失败（5.0s 超时）。
        result = probe_stdio(
            sys.executable, args=["-c", NOISY_STDERR_SERVER], timeout=5.0
        )
        self.assertTrue(result["initialize_ok"], result["error"])
        self.assertTrue(result["tools_list_ok"], result["error"])
        self.assertEqual(result["tool_names"], ["noisy_ping"])

    def test_stderr_tail_reported_when_handshake_fails(self):
        # P0-5 的另一半诉求：失败必须**可归因**。子进程明明说了话，
        # 就不该只回一句裸的「stdio handshake timed out」。
        result = probe_stdio(
            sys.executable, args=["-c", STDERR_ONLY_SERVER], timeout=1.5
        )
        self.assertFalse(result["initialize_ok"])
        self.assertIn("stdio handshake timed out", result["error"])
        self.assertIn("BOOM: simulated startup failure", result["error"])


if __name__ == "__main__":
    unittest.main()
