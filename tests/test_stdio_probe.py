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


if __name__ == "__main__":
    unittest.main()