"""Cross-profile summary report (phase 2 matrix)."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from dashboard_states import classify_record


# Fixed (non-capability) data columns, in rendering order after ``profile``/``client``.
FIXED_COLUMNS = [
    "installed",
    "skills_compliant",
    "mcp_configured",
    "mcp_initialize_ok",
    "mcp_tools_list_ok",
    "hooks_configured",
    "legacy_channels",
]


def _group_columns(results: List[Dict[str, Any]]) -> List[str]:
    """Union of every profile's capability-group names, first-seen order."""
    columns: List[str] = []
    seen = set()
    for result in results:
        for group in result.get("capability_groups", []) or []:
            if group not in seen:
                seen.add(group)
                columns.append(group)
    # A profile may request zero groups but records could still carry a group
    # (defensive); also collect from record capabilities.
    for result in results:
        for record in result.get("records", []) or []:
            for group in (record.get("capabilities") or {}):
                if group not in seen:
                    seen.add(group)
                    columns.append(group)
    return columns


def _legacy_cell(record: Dict[str, Any]) -> str:
    legacy = record.get("legacy_channels", []) or []
    return ";".join(legacy) if legacy else ""


def _record_rows(
    result: Dict[str, Any],
    group_columns: List[str],
    groups_in_result: List[str],
) -> List[List[Any]]:
    rows = []
    for record in result.get("records", []) or []:
        capabilities = record.get("capabilities", {}) or {}
        row = [
            result.get("profile", ""),
            record.get("name", ""),
            record.get("installed", False),
            record.get("skills_compliant", False),
            record.get("mcp_configured", False),
            record.get("mcp_initialize_ok", False),
            record.get("mcp_tools_list_ok", False),
        ]
        for group in group_columns:
            if group in groups_in_result:
                row.append(capabilities.get(group, False))
            else:
                row.append("")  # not required by this profile -> empty, not False
        row.extend([
            record.get("hooks_configured", False),
            _legacy_cell(record),
        ])
        rows.append(row)
    return rows


def _header(group_columns: List[str]) -> List[str]:
    return (
        ["profile", "client"]
        + FIXED_COLUMNS[:5]
        + group_columns
        + FIXED_COLUMNS[5:]
    )


def _as_csv(results: List[Dict[str, Any]], group_columns: List[str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_header(group_columns))
    for result in results:
        groups_in_result = list(result.get("capability_groups", []) or [])
        for row in _record_rows(result, group_columns, groups_in_result):
            writer.writerow(row)
    return buffer.getvalue().rstrip("\r\n")


def _as_table(results: List[Dict[str, Any]], group_columns: List[str]) -> str:
    from combined_checker import CAPABILITY_DISPLAY_NAMES

    lines = [
        "=" * 100,
        "  跨 profile 汇总报告",
        "=" * 100,
        "",
    ]
    display = [
        CAPABILITY_DISPLAY_NAMES.get(group, group.replace("_", " ").title())
        for group in group_columns
    ]
    header = ["profile", "client"] + FIXED_COLUMNS[:5] + display + FIXED_COLUMNS[5:]
    lines.append("  " + " | ".join(header))
    lines.append("  " + "-" * 98)
    for result in results:
        groups_in_result = list(result.get("capability_groups", []) or [])
        for row in _record_rows(result, group_columns, groups_in_result):
            lines.append("  " + " | ".join(str(v) for v in row))
    for result in results:
        if not result.get("ok", True):
            error = result.get("probe", {}).get("error", "")
            suffix = f" (probe: {error})" if error else ""
            lines.append(f"  ⚠️ profile {result.get('profile', '')} 不合规{suffix}")
    lines.append("")
    return "\n".join(lines)


def _as_markdown(results: List[Dict[str, Any]], group_columns: List[str]) -> str:
    from combined_checker import CAPABILITY_DISPLAY_NAMES

    display = [
        CAPABILITY_DISPLAY_NAMES.get(group, group.replace("_", " ").title())
        for group in group_columns
    ]
    header = ["Profile", "Client"] + FIXED_COLUMNS[:5] + display + FIXED_COLUMNS[5:]
    lines = ["## 跨 profile 汇总", ""]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    for result in results:
        groups_in_result = list(result.get("capability_groups", []) or [])
        for row in _record_rows(result, group_columns, groups_in_result):
            lines.append("| " + " | ".join(str(v) for v in row) + " |")
    lines.append("")
    return "\n".join(lines)


def _annotate_states(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a copy of ``results`` with each record annotated with its tri-state.

    Stage-3 GUI consumes ``record.state`` (green/yellow/red/gray) computed by the
    single Python rule set (``dashboard_states``), so the webview never re-derives
    the classification. The field is additive: ``records`` fields only grow.
    """
    annotated: List[Dict[str, Any]] = []
    for result in results:
        probe = result.get("probe", {})
        copy = dict(result)
        records = []
        for record in result.get("records", []) or []:
            annotated_record = dict(record)
            annotated_record["state"] = classify_record(record, probe)
            records.append(annotated_record)
        copy["records"] = records
        annotated.append(copy)
    return annotated


def report_all_profiles(
    results: List[Dict[str, Any]],
    fmt: str = "table",
    active_profile: str = "",
) -> str:
    """Render a cross-profile summary.

    ``results`` is a list of ``{profile, ok, ...check_agents 返回结构}``.

    ``fmt`` is one of ``table`` (terminal), ``csv``, ``json``, ``md``.
    """
    if fmt == "json":
        payload = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "active_profile": active_profile,
            "profiles": [result.get("profile", "") for result in results],
            "results": _annotate_states(results),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    group_columns = _group_columns(results)
    if fmt == "csv":
        return _as_csv(results, group_columns)
    if fmt == "md":
        return _as_markdown(results, group_columns)
    return _as_table(results, group_columns)