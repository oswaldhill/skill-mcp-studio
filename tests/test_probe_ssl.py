"""SSL context for the HTTP MCP probe.

macOS python.org framework builds ship without a linked system CA store, so
``ssl.create_default_context()`` cannot verify real HTTPS endpoints. ``certifi``
is already a dependency; when present we load its bundle explicitly so live
probes verify TLS against trusted roots on every platform.
"""

import os
import ssl
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import mcp_probe  # noqa: E402
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


def _empty_verifying_context(*args, **kwargs):
    """模拟 macOS python.org 构建：上下文合法，但**一个根证书都没有**。"""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


_real_import = __import__


def _no_certifi(name, *args, **kwargs):
    """模拟 certifi 未安装。"""
    if name == "certifi":
        raise ImportError("simulated: certifi not installed")
    return _real_import(name, *args, **kwargs)


class SystemCaFallbackTest(unittest.TestCase):
    """certifi 缺失时必须有兜底，不能静默返回空上下文。

    2026-11-04 实测事故：本机三个解释器都没有 certifi，
    ``ssl.create_default_context()`` 加载到的根证书数为 0，于是**所有** HTTPS
    端点探活都以 ``CERTIFICATE_VERIFY_FAILED`` 失败 —— 管理台里看起来像
    「端点全挂」，而报错信息又指向网络，极具误导性。

    旧实现在 ``ImportError`` 时只 warn 一句就返回空上下文，没有测试守着，
    因为原用例只在装了 certifi 的机器上通过。
    """

    def test_uses_system_bundle_when_certifi_is_missing(self):
        with mock.patch("builtins.__import__", _no_certifi), \
             mock.patch.object(mcp_probe.ssl, "create_default_context", _empty_verifying_context):
            ctx = mcp_probe._ssl_context()
        self.assertGreater(len(ctx.get_ca_certs()), 0, "certifi 缺失时必须从系统 CA 兜底")
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)

    def test_present_certifi_still_takes_priority(self):
        # 装了 certifi 就走 certifi（跨平台最一致），不被系统包覆盖。
        ctx = mcp_probe._ssl_context()
        self.assertGreater(len(ctx.get_ca_certs()), 0)

    def test_never_downgrades_verification(self):
        ctx = _ssl_context()
        self.assertTrue(ctx.check_hostname, "不得关闭主机名校验")
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)

    def test_raises_when_no_trust_store_available(self):
        # 一条信任库都找不到时，宁可明确报错，也不能静默构造必然失败的上下文。
        with mock.patch("builtins.__import__", _no_certifi), \
             mock.patch.object(mcp_probe.ssl, "create_default_context", _empty_verifying_context), \
             mock.patch.object(mcp_probe, "SYSTEM_CA_BUNDLES", ("/nonexistent/ca.pem",)):
            with self.assertRaises(RuntimeError) as caught:
                mcp_probe._ssl_context()
        self.assertIn("CA 信任库", str(caught.exception))

    def test_shipped_bundle_path_exists_on_this_platform(self):
        # 至少有一个候选路径在「没装 certifi」的 macOS 上真实存在，否则兜底是空谈。
        if sys.platform == "darwin":
            self.assertTrue(
                any(os.path.isfile(p) for p in mcp_probe.SYSTEM_CA_BUNDLES),
                "macOS 上找不到任何系统 CA 包，certifi 缺失时必然失败",
            )


if __name__ == "__main__":
    unittest.main()
