"""SSL context for the HTTP MCP probe.

macOS python.org framework builds ship without a linked system CA store, so
``ssl.create_default_context()`` cannot verify real HTTPS endpoints. ``certifi``
is already a dependency; when present we load its bundle explicitly so live
probes verify TLS against trusted roots on every platform.
"""

import ssl
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from mcp_probe import _ssl_context  # noqa: E402


class SslContextTest(unittest.TestCase):
    def test_returns_ssl_context(self):
        ctx = _ssl_context()
        self.assertIsInstance(ctx, ssl.SSLContext)

    def test_context_verifies_certificates(self):
        ctx = _ssl_context()
        # Must enforce verification (never CERT_NONE) for a security tool.
        self.assertNotEqual(ctx.verify_mode, ssl.CERT_NONE)
        self.assertTrue(ctx.check_hostname)

    def test_context_has_loaded_ca_certs(self):
        ctx = _ssl_context()
        # get_ca_certs() returns the loaded trust store; empty means the
        # platform has no roots and certifi was not applied.
        self.assertGreater(len(ctx.get_ca_certs()), 0)


if __name__ == "__main__":
    unittest.main()
