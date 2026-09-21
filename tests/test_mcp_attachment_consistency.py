"""P1 回归：期望挂载 vs 实际观测的一致性判定（attachment_consistency）。

背景缺陷：界面把 ``mcp_attach``（显式声明，或未声明时的默认「全部端点」）直接
渲染成「已配置 MCP 端点」。由于没有任何客户端显式声明，且 ``resolve_client_attach``
在缺省时返回端点库全集，一个**完全没有 MCP 配置**的客户端（config_path 为空、
inventory 为空）也会显示为「已配置了两个端点」——纯假阳性。

``observed_endpoint_keys`` / ``attachment_consistency`` 把「期望」与「实际」分开，
使「声明要挂却没挂」可以被判定为异常。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from mcp_inventory import McpEntry, attachment_consistency, observed_endpoint_keys  # noqa: E402


def _attached(key: str, endpoint_key: str) -> McpEntry:
    return McpEntry(key=key, classification="attached", endpoint_key=endpoint_key)


def _other(key: str, classification: str = "unmanaged") -> McpEntry:
    return McpEntry(key=key, classification=classification)


class ObservedEndpointKeysTest(unittest.TestCase):
    def test_only_attached_entries_count(self):
        entries = [_attached("hermes", "hermes-home"), _other("context7"), _other("old", "legacy")]
        self.assertEqual(observed_endpoint_keys(entries), ["hermes-home"])

    def test_legacy_and_unmanaged_are_not_observed(self):
        entries = [_other("hermes-legacy", "legacy"), _other("context7")]
        self.assertEqual(observed_endpoint_keys(entries), [])

    def test_order_follows_inventory_and_dedupes(self):
        entries = [
            _attached("hermes", "hermes-home"),
            _attached("K8s-uat", "K8s-uat"),
            _attached("hermes2", "hermes-home"),
        ]
        self.assertEqual(observed_endpoint_keys(entries), ["hermes-home", "K8s-uat"])

    def test_empty_inventory(self):
        self.assertEqual(observed_endpoint_keys([]), [])


class AttachmentConsistencyTest(unittest.TestCase):
    def test_all_expected_are_mounted(self):
        entries = [_attached("hermes", "hermes-home"), _attached("K8s-uat", "K8s-uat")]
        result = attachment_consistency(entries, ["K8s-uat", "hermes-home"])
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["undeclared"], [])
        self.assertEqual(sorted(result["observed"]), ["K8s-uat", "hermes-home"])

    def test_declared_but_nothing_mounted_is_an_anomaly(self):
        """ima.copilot 实况：期望两个端点，配置文件里一个都没有。"""
        result = attachment_consistency([], ["K8s-uat", "hermes-home"])
        self.assertEqual(result["observed"], [])
        self.assertEqual(result["missing"], ["K8s-uat", "hermes-home"])
        self.assertEqual(result["undeclared"], [])

    def test_partially_mounted_reports_only_the_gap(self):
        entries = [_attached("hermes", "hermes-home")]
        result = attachment_consistency(entries, ["K8s-uat", "hermes-home"])
        self.assertEqual(result["missing"], ["K8s-uat"])
        self.assertEqual(result["observed"], ["hermes-home"])

    def test_mounted_but_not_expected_is_undeclared(self):
        entries = [_attached("K8s-uat", "K8s-uat")]
        result = attachment_consistency(entries, ["hermes-home"])
        self.assertEqual(result["undeclared"], ["K8s-uat"])
        self.assertEqual(result["missing"], ["hermes-home"])

    def test_expected_is_echoed_deduped_and_ordered(self):
        result = attachment_consistency([], ["b", "a", "b", ""])
        self.assertEqual(result["expected"], ["b", "a"])

    def test_expected_none_is_tolerated(self):
        result = attachment_consistency([], None)
        self.assertEqual(result["expected"], [])
        self.assertEqual(result["missing"], [])

    def test_missing_preserves_expected_order(self):
        result = attachment_consistency([], ["zeta", "alpha"])
        self.assertEqual(result["missing"], ["zeta", "alpha"])


class SnapshotPayloadTest(unittest.TestCase):
    """快照必须把期望/实际/异常四组字段一并交给 UI（防止回退到只发 mcp_attach）。"""

    def test_snapshot_client_payload_exposes_consistency_fields(self):
        import inspect

        import management_snapshot

        src = inspect.getsource(management_snapshot)
        for field in (
            "has_explicit_attach",
            "observed_attach",
            "missing_attach",
            "undeclared_attach",
        ):
            self.assertIn(field, src, f"快照载荷缺少 {field}")
        self.assertIn("attachment_consistency", src)


if __name__ == "__main__":
    unittest.main()