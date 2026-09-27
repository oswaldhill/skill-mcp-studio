"""`probe_timeout` / `probe_retries` 显式为 null 时必须回落到文档化默认值。

背景（Round 42 实测发现）：`dict.get(key, default)` **只在键不存在时**才用 default。
键存在但值为 null（YAML 里写 `probe_timeout:` 留空、或上游写入 None）会把 None 原样
传给 `mcp_probe.probe_mcp`，后果比报错更糟：

- ``timeout=None``  → urllib 视为「无超时」，探活会**永久挂死**；
- ``retries=None``  → mcp_probe 内 ``int(None)`` 抛 TypeError，被 management_snapshot
  的 per-endpoint ``except`` 吞成一个误导性错误，**真实探活结论丢失**。

因此 `combined_checker` 把「显式 null」与「未设置」一律当作未设置。
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import combined_checker  # noqa: E402


class NoneConfigFallbackTest(unittest.TestCase):
    """直接给 `check_agents` 传 profile，跳过 load_profile，只观察传给 probe 的实参。"""

    def _capture(self, profile: dict) -> dict:
        captured: dict = {}

        def fake_probe(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return {
                "initialize_ok": False,
                "tools_list_ok": False,
                "tool_names": [],
                "error": "stub",
            }

        with mock.patch.object(combined_checker, "probe_mcp", fake_probe):
            try:
                combined_checker.check_agents(
                    {},
                    {"unified_dir": "", "results": [], "summary": {}},
                    live_probe=True,
                    profile=profile,
                    endpoint_key="stub",
                )
            except Exception:
                # 探活之后的逻辑需要更完整的 config；本测试只关心传下去的实参，
                # 因此后面的失败不影响断言。
                pass
        return captured

    def test_explicit_null_falls_back_to_defaults(self):
        cap = self._capture({
            "name": "X",
            "url": "https://example.invalid/mcp",
            "probe_timeout": None,
            "probe_retries": None,
        })
        self.assertEqual(
            cap.get("timeout"), 8.0,
            "probe_timeout=None 必须回落 8.0；否则 urlopen(timeout=None) 会永不超时（挂死）",
        )
        self.assertEqual(
            cap.get("retries"), 1,
            "probe_retries=None 必须回落 1；否则 mcp_probe 的 int(None) 抛 TypeError",
        )

    def test_explicit_zero_retries_is_respected(self):
        """反向验证：显式 0（关闭重试）不能被 None 回落逻辑改写成 1。"""
        cap = self._capture({
            "name": "X",
            "url": "https://example.invalid/mcp",
            "probe_retries": 0,
        })
        self.assertEqual(cap.get("retries"), 0, "显式 probe_retries: 0 必须保留")

    def test_custom_values_pass_through_unchanged(self):
        """反向验证：正常数值不做任何改写。"""
        cap = self._capture({
            "name": "X",
            "url": "https://example.invalid/mcp",
            "probe_timeout": 3.0,
            "probe_retries": 2,
        })
        self.assertEqual(cap.get("timeout"), 3.0)
        self.assertEqual(cap.get("retries"), 2)


if __name__ == "__main__":
    unittest.main()
