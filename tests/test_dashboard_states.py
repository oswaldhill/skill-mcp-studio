"""Tri-state classification tests + the result_ok consistency invariant.

v0.24.0 复审后的契约（用户明确要求）
-----------------------------------
审计只判**配置**。探活（端点连通性）不参与颜色，也不参与 ``result_ok``。

因此原先「把 probe 传给 classify_record」的写法已全部移除；端点连通性改由
``classify_endpoint_probe`` + 独立的连通性检查入口负责（见 EndpointProbeTest）。

三条旧契约用例被**反转**（原名见各自 docstring）：它们曾断言「探活失败 /
能力缺失 / 未探活」会改变配置颜色 —— 那正是本次要废除的越界行为。
"""

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from combined_checker import result_ok  # noqa: E402
from dashboard_states import (  # noqa: E402
    ENDPOINT_FAILED,
    ENDPOINT_NOT_RUN,
    ENDPOINT_OK,
    STATE_GRAY,
    STATE_GREEN,
    STATE_RED,
    STATE_YELLOW,
    all_installed_compliant,
    classify_endpoint_probe,
    classify_record,
    probe_state,
)


def rec(**overrides):
    """一台配置完整的客户端。

    探活派生字段（``mcp_initialize_ok`` / ``mcp_tools_list_ok`` / ``capabilities``）
    在这里是中性值；新契约下它们**不参与**判定，改动它们不应改变颜色
    —— 见 ConfigOnlyTest 的反向用例。
    """
    base = {
        "name": "Codex",
        "installed": True,
        "skills_compliant": True,
        "mcp_configured": True,
        "mcp_initialize_ok": True,
        "mcp_tools_list_ok": True,
        "hooks_configured": True,
        "capabilities": {"memory": True},
        "legacy_channels": [],
    }
    base.update(overrides)
    return base


class TriStateTest(unittest.TestCase):
    """颜色只由配置决定。"""

    def test_green(self):
        self.assertEqual(classify_record(rec()), STATE_GREEN)

    def test_gray_when_not_installed(self):
        self.assertEqual(classify_record(rec(installed=False)), STATE_GRAY)

    def test_red_when_skills_non_compliant(self):
        self.assertEqual(classify_record(rec(skills_compliant=False)), STATE_RED)

    def test_red_when_mcp_not_configured(self):
        self.assertEqual(classify_record(rec(mcp_configured=False)), STATE_RED)

    def test_yellow_when_legacy_channels_present(self):
        self.assertEqual(classify_record(rec(legacy_channels=["hermes-nas"])), STATE_YELLOW)

    def test_yellow_when_hooks_missing(self):
        self.assertEqual(classify_record(rec(hooks_configured=False)), STATE_YELLOW)

    def test_green_when_hooks_not_required(self):
        # 纯工具端点 hooks_required=False：未配 hooks 不阻断 GREEN。
        r = rec(hooks_configured=False, hooks_required=False, capabilities={})
        self.assertEqual(classify_record(r), STATE_GREEN)


class ConfigOnlyTest(unittest.TestCase):
    """契约反转：探活派生字段**不得**影响配置颜色。

    这三条是 v0.24.0 复审的直接产物。在旧实现下它们会失败（旧实现把
    probe 失败 / 能力缺失 / 未探活分别判成 RED 或 YELLOW）。
    """

    def test_probe_failure_does_not_redden_config(self):
        """反转 ``test_red_when_probe_failed``：端点连不上不是配置错误。"""
        r = rec(
            mcp_initialize_ok=False,
            mcp_tools_list_ok=False,
            capabilities={"memory": False},
        )
        self.assertEqual(classify_record(r), STATE_GREEN)

    def test_unmet_capability_does_not_redden_config(self):
        """反转 ``test_red_when_capability_unmet``。

        能力位由 ``tools/list`` 得出（属探活），是运行时状态，配置审计不判它。
        """
        self.assertEqual(classify_record(rec(capabilities={"memory": False})), STATE_GREEN)

    def test_not_probed_is_not_yellow(self):
        """反转 ``test_yellow_when_not_probed``：不探活不再把合规客户端降级成黄。"""
        r = rec(mcp_initialize_ok=False, mcp_tools_list_ok=False, capabilities={})
        self.assertEqual(classify_record(r), STATE_GREEN)


class EndpointProbeTest(unittest.TestCase):
    """端点连通性的展示态 —— 独立于配置颜色。"""

    def test_ok(self):
        self.assertEqual(classify_endpoint_probe({"error": ""}), ENDPOINT_OK)

    def test_failed(self):
        self.assertEqual(classify_endpoint_probe({"error": "connect fail"}), ENDPOINT_FAILED)

    def test_not_run(self):
        self.assertEqual(classify_endpoint_probe({"error": "not probed"}), ENDPOINT_NOT_RUN)

    def test_missing_probe_treated_as_not_run(self):
        # 快照里没有 probe 段（纯配置运行）时按「未检查」呈现，而不是失败。
        self.assertEqual(classify_endpoint_probe({}), ENDPOINT_NOT_RUN)

    def test_probe_state_tri_state(self):
        self.assertEqual(probe_state({"error": ""}), "probed_ok")
        self.assertEqual(probe_state({"error": "x"}), "probed_failed")
        self.assertEqual(probe_state({"error": "not probed"}), "not_probed")


class ConsistencyInvariantTest(unittest.TestCase):
    def test_result_ok_equals_all_installed_compliant(self):
        """DoD 不变量：CLI 的 result_ok 必须与 GUI 三态判定一致。"""
        cases = [
            # (records, unmanaged)
            ([rec()], []),
            ([rec(skills_compliant=False)], []),
            ([rec(mcp_configured=False)], []),
            ([rec(installed=False)], []),  # 什么都没装 -> 空真
            ([rec(legacy_channels=["h"])], []),
            ([rec(hooks_configured=False)], []),
            ([rec()], [{"name": "Orphan"}]),  # unmanaged -> 不合规
        ]
        for records, unmanaged in cases:
            result = {"records": records, "unmanaged": unmanaged, "summary": {}}
            self.assertEqual(
                result_ok(result),
                all_installed_compliant(result),
                msg=f"invariant broken for records={records} unmanaged={unmanaged}",
            )

    def test_probe_failure_still_reaches_ok(self):
        """契约反转：探活失败不再让审计退出码变红。

        旧 ``result_ok`` 见到 ``probe.error`` 非空即直接 False。现在审计只看配置，
        端点故障由**独立的连通性检查**呈现，不影响审计结论。
        """
        result = {
            "probe": {"error": "connect fail"},
            "records": [
                rec(
                    mcp_initialize_ok=False,
                    mcp_tools_list_ok=False,
                    capabilities={},
                )
            ],
            "unmanaged": [],
            "summary": {},
        }
        self.assertTrue(result_ok(result))

    def test_config_only_reaches_ok(self):
        """A-2 回归：纯配置运行（未探活）且配置合规 -> 退出 0。"""
        result = {
            "probe": {"error": "not probed"},
            "records": [
                rec(
                    mcp_initialize_ok=False,
                    mcp_tools_list_ok=False,
                    capabilities={"memory": False},
                )
            ],
            "unmanaged": [],
            "summary": {},
        }
        self.assertTrue(result_ok(result))
        self.assertEqual(probe_state(result["probe"]), "not_probed")


if __name__ == "__main__":
    unittest.main()
