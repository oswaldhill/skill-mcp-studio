"""端点连通性检查 —— 与配置审计**完全独立**的一条路径。

为什么单独一个模块
------------------
用户明确要求：审计只判配置是否正确，**不判定对应端口是否正常**；端口是否正常应在
单独的状态里、或在 MCP 里检查，而不是塞进 IDE 页面的审计结论。

因此这里做的事只有一件：**对已配置的 MCP 端点发起一次真探活**，把结果整理成
「端点状态」视图。它：

- **不参与** ``classify_record`` 的颜色，**不参与** ``result_ok`` 的退出码；
- **只被显式调用**（CLI ``--endpoint-status`` / GUI「端点状态」区的手动按钮）；
- 复用既有的 ``probe_mcp``（不重写探活）与 ``classify_endpoint_probe``（展示态判定），
  避免两套探活逻辑各自漂移。

代价（需向用户明示）
--------------------
端点故障从此**不会**出现在审计里。配置合规的客户端即使端点全挂，审计仍是绿的；
要看端点是否活着，必须打开「端点状态」。
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dashboard_states import (
    ENDPOINT_FAILED,
    ENDPOINT_NOT_RUN,
    ENDPOINT_OK,
    classify_endpoint_probe,
)
from mcp_probe import probe_mcp


# 审计路径从不调用本模块；这里给出「未检查」的占位结果，供快照在**未手动触发**时
# 呈现「尚未检查」，而不是伪造一个 ok。
NOT_RUN: Dict[str, Any] = {
    "initialize_ok": False,
    "tools_list_ok": False,
    "tool_names": [],
    "error": "not probed",
}


def _probe_with_profile_timing(expected: Dict[str, Any]) -> Dict[str, Any]:
    """按 profile 的探活参数调一次 ``probe_mcp``，并附上耗时。

    参数取值规则与 ``combined_checker.check_agents`` **保持一致**，否则同一端点会在
    审计与端点状态两处得到不同结论：

    - ``probe_timeout`` / ``probe_retries`` 显式为 ``null`` 视同未设置（YAML 里
      ``probe_timeout:`` 留空会得到 None；透传下去会让 urllib **无超时永久挂死**）。
    - 默认重试 1 次，避免远程网关偶发抖动被误判成端点故障。
    """
    raw_timeout = expected.get("probe_timeout")
    raw_retries = expected.get("probe_retries")
    started = time.monotonic()
    probe = probe_mcp(
        expected.get("url", ""),
        transport=expected.get("transport", "streamable-http"),
        command=expected.get("command"),
        args=expected.get("args"),
        env=expected.get("env"),
        timeout=8.0 if raw_timeout is None else raw_timeout,
        token=expected.get("auth_token"),
        token_env=expected.get("auth_token_env"),
        url_policy=expected.get("url_policy", "strict"),
        retries=1 if raw_retries is None else raw_retries,
    )
    probe = dict(probe)
    probe["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return probe


def build_endpoint_status(
    config: Dict[str, Any],
    *,
    endpoint_key: Optional[str] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """对一个端点做一次真探活，返回「端点状态」视图的数据。

    返回结构::

        {
          "checked_at": "2026-01-01T00:00:00+00:00",   # 手动触发的时刻
          "endpoint": {"name": ..., "url": ..., "transport": ...},
          "state": "ok" | "failed" | "not_run",         # classify_endpoint_probe
          "initialize_ok": bool,
          "tools_list_ok": bool,
          "tool_count": int,
          "tool_names": [...],
          "elapsed_ms": int,
          "error": "...",
        }

    端点配置**必须**经 ``load_profile`` 规范化解析（含 legacy 包装 + 默认值），
    与审计用同一来源 —— 否则「审计看的端点」与「这里探的端点」可能不是同一个。
    """
    if profile is not None:
        expected = profile
    else:
        from profile_loader import load_profile

        expected = load_profile(config, endpoint_key)["profile"]

    probe = _probe_with_profile_timing(expected)
    state = classify_endpoint_probe(probe)
    tool_names = list(probe.get("tool_names") or [])
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": {
            "name": expected.get("name", "hermes"),
            "url": expected.get("url", ""),
            "transport": expected.get("transport", "streamable-http"),
        },
        "state": state,
        "initialize_ok": bool(probe.get("initialize_ok")),
        "tools_list_ok": bool(probe.get("tools_list_ok")),
        "tool_count": len(tool_names),
        "tool_names": tool_names,
        "elapsed_ms": probe.get("elapsed_ms", 0),
        "error": probe.get("error", ""),
    }


def not_run_endpoint_status(
    config: Dict[str, Any],
    *,
    endpoint_key: Optional[str] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """**不探活**，只把端点的配置信息整理出来，状态标为 ``not_run``。

    用于快照在用户尚未手动触发时的呈现：显示「端点是谁」但明确标注「尚未检查」。
    **绝不能**在这里假装成功 —— 把「没测过」显示成「正常」会误导人。
    """
    if profile is not None:
        expected = profile
    else:
        from profile_loader import load_profile

        expected = load_profile(config, endpoint_key)["profile"]

    probe = dict(NOT_RUN)
    return {
        "checked_at": "",
        "endpoint": {
            "name": expected.get("name", "hermes"),
            "url": expected.get("url", ""),
            "transport": expected.get("transport", "streamable-http"),
        },
        "state": classify_endpoint_probe(probe),
        "initialize_ok": False,
        "tools_list_ok": False,
        "tool_count": 0,
        "tool_names": [],
        "elapsed_ms": 0,
        "error": probe["error"],
    }


def endpoint_exit_code(status: Dict[str, Any]) -> int:
    """端点状态对应的进程退出码。

    **与审计退出码完全无关** —— 审计退出码只看配置（见 ``combined_checker.result_ok``）。
    这里只服务独立的连通性命令：

    - ``ok`` → 0（含 ``not_run``：没检查不算失败），
    - ``failed`` → 1（用户主动来查连通性，不通就是不通）。

    注意 ``not_run`` 判 0：``not_run`` 只在「未手动触发」时出现，而独立命令一定会
    真的探活，所以走到这里意味着探活被跳过而非失败，不该报错。
    """
    if status.get("state") == ENDPOINT_FAILED:
        return 1
    if status.get("state") == ENDPOINT_NOT_RUN:
        return 0
    return 0 if status.get("state") == ENDPOINT_OK else 0


def status_summary(status: Dict[str, Any]) -> str:
    """一行中文摘要，供 CLI / GUI 直接显示。"""
    state = status.get("state")
    endpoint = status.get("endpoint", {})
    name = endpoint.get("name", "hermes")
    url = endpoint.get("url", "")
    if state == ENDPOINT_OK:
        return f"端点 {name} 连通正常（{url}，{status.get('tool_count', 0)} 个工具，{status.get('elapsed_ms', 0)}ms）"
    if state == ENDPOINT_FAILED:
        return f"端点 {name} 不通（{url}）：{status.get('error', '')}"
    return f"端点 {name} 尚未检查（{url}）"


def status_lines(status: Dict[str, Any]) -> List[str]:
    """端点状态的多行文本视图（CLI 用）。"""
    endpoint = status.get("endpoint", {})
    lines = [
        "端点状态（独立于配置审计）",
        f"  名称: {endpoint.get('name', 'hermes')}",
        f"  地址: {endpoint.get('url', '')}",
        f"  传输: {endpoint.get('transport', 'streamable-http')}",
        f"  结论: {status.get('state')}",
    ]
    if status.get("checked_at"):
        lines.append(f"  检查时间: {status['checked_at']}")
    if status.get("state") != ENDPOINT_NOT_RUN:
        lines.append(f"  initialize: {'成功' if status.get('initialize_ok') else '失败'}")
        lines.append(f"  tools/list: {'成功' if status.get('tools_list_ok') else '失败'}")
        lines.append(f"  工具数: {status.get('tool_count', 0)}")
        lines.append(f"  耗时: {status.get('elapsed_ms', 0)}ms")
    if status.get("error"):
        lines.append(f"  错误: {status['error']}")
    lines.append("")
    lines.append("说明：这里只反映端点连通性；配置是否正确请看审计结论，两者互不影响。")
    return lines
