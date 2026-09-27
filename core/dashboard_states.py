"""Read-only dashboard tri-state classification.

职责边界（v0.24.0 复审后修正，用户明确要求）
-------------------------------------------
本模块只回答一个问题：**这台机器上的客户端配置是否正确**。

判定只用「配置派生」字段，**绝不**看探活（连通性）结果：

- 配置派生：``installed`` / ``skills_compliant`` / ``mcp_configured`` /
  ``hooks_configured`` / ``hooks_required`` / ``legacy_channels``
- 探活派生：``mcp_initialize_ok`` / ``mcp_tools_list_ok`` / ``capabilities`` /
  ``probe`` —— 这些**不参与颜色**，只在「端点状态」视图里用

理由：端点是否可达是**运行时状态**，不是配置正确性。一个配置完全合法的端点
（例如内网 ``k8s.carobo.cn`` 在本机不可达）不应让配置审计变色；反过来，探活
成功也不能把配置写错的客户端判成绿色。

    GREEN  == 配置完全合规
    YELLOW == 配置无硬性错误，但存在需人工处理项（遗留通道 / 缺必需 hooks）
    RED    == 配置存在硬性错误（skills 不合规 / MCP 未按预期配置）
    GRAY   == 未安装

「端点连通性」是**另一个**视图，入口在 MCP 模块，由独立命令手动触发；
其展示态由 ``classify_endpoint_probe`` 给出，与上面的颜色互不影响。
"""

from __future__ import annotations

from typing import Any, Dict

STATE_GREEN = "green"
STATE_YELLOW = "yellow"
STATE_RED = "red"
STATE_GRAY = "gray"

# 端点连通性的三态（只服务于「端点状态」视图，与配置审计无关）。
PROBE_STATE_OK = "probed_ok"
PROBE_STATE_FAILED = "probed_failed"
PROBE_STATE_NOT_PROBED = "not_probed"

# 「端点状态」视图的展示态。
ENDPOINT_OK = "ok"
ENDPOINT_FAILED = "failed"
ENDPOINT_NOT_RUN = "not_run"


def probe_state(probe: Dict[str, Any]) -> str:
    """把一次端点探活归入三态。

    ``probe`` 是探活结果的 dict，其 ``error`` 字段承载全部信号：

    - **没有 probe 段、或没有 ``error`` 键** → 从未探活（无信号可依），
      判 ``NOT_PROBED``。**不能**当作成功 —— 把「没测过」显示成「正常」会误导人。
    - ``error == "not probed"`` → 探活没跑（纯配置运行），
    - 其它非空 error → 探活跑了但失败，
    - 空串 → 探活跑了且成功。
    """
    if not probe or "error" not in probe:
        return PROBE_STATE_NOT_PROBED
    error = probe.get("error", "")
    if error == "not probed":
        return PROBE_STATE_NOT_PROBED
    return PROBE_STATE_FAILED if error else PROBE_STATE_OK


def classify_endpoint_probe(probe: Dict[str, Any]) -> str:
    """端点连通性的展示态：ok / failed / not_run。

    这是「端点状态」视图专用的判定，**不参与** ``classify_record`` 的颜色，
    因此「端口不通」永远不会让配置审计变红。
    """
    state = probe_state(probe)
    if state == PROBE_STATE_OK:
        return ENDPOINT_OK
    if state == PROBE_STATE_FAILED:
        return ENDPOINT_FAILED
    return ENDPOINT_NOT_RUN


def classify_record(record: Dict[str, Any]) -> str:
    """按**配置**给出 green/yellow/red/gray（不看探活）。

    ``record`` 需包含 ``installed``、``skills_compliant``、``mcp_configured``、
    ``hooks_configured``、``hooks_required``、``legacy_channels``。

    注意：``mcp_initialize_ok`` / ``mcp_tools_list_ok`` / ``capabilities`` 是
    探活派生字段，**故意不参与判定**。
    """
    if not record.get("installed"):
        return STATE_GRAY

    # 硬性配置错误 -> RED。
    if not record.get("skills_compliant"):
        return STATE_RED
    if not record.get("mcp_configured"):
        return STATE_RED

    # 配置完全合规 -> GREEN。hooks 只在端点适用时才是硬性要求
    # （纯工具端点 record.hooks_required=False，未配 hooks 不阻断 green）。
    if (
        record.get("skills_compliant")
        and record.get("mcp_configured")
        and (record.get("hooks_configured") or not record.get("hooks_required", True))
        and not record.get("legacy_channels")
    ):
        return STATE_GREEN

    # 其余：遗留通道待迁移 / 缺必需 hooks -> YELLOW。
    return STATE_YELLOW


def classify_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """对 ``check_agents`` 结果里的每条 record 分类，并附 unmanaged 名单。"""
    records: Dict[str, str] = {}
    for record in result.get("records", []) or []:
        records[record.get("name", "")] = classify_record(record)
    unmanaged = [item.get("name", "") for item in result.get("unmanaged", []) or []]
    return {
        "records": records,
        "unmanaged": unmanaged,
    }


def all_installed_compliant(result: Dict[str, Any]) -> bool:
    """从 GUI 三态独立重推 ``result_ok``（配置口径）。

    配置审计里只有 GREEN 算合规：YELLOW 在本口径下必然意味着「有遗留通道」
    或「缺必需 hooks」，两者都是失败，不再存在「因未探活而黄」的情形
    （探活已完全移出审计）。

    这是 ``combined_checker.result_ok`` 的 GUI 侧孪生实现，两者在
    ``test_dashboard_states`` 中比对，以防漂移。
    """
    if result.get("unmanaged"):
        return False
    for record in result.get("records", []) or []:
        if not record.get("installed"):
            continue
        if classify_record(record) != STATE_GREEN:
            return False
    return True
