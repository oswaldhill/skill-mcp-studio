"""Combine installation, Skills, MCP, hooks, and live capability results."""

from typing import Any, Dict, List, Optional

from hooks_checker import check_hooks
from mcp_checker import inspect_mcp_configuration, load_mcp_servers, summarize_records
from mcp_fixer import _merged_legacy_names
from mcp_probe import probe_mcp
from skill_state import read_skill_states, skill_link_form
from skill_state_auditor import audit_skill_states
from native_disable import read_native_disabled
from tool_registry import detect_installation, effective_tools, normalized_name
from endpoint_library import clients_attached_to, has_explicit_attach


def _skills_compliant(name: str, scan_result: Dict[str, Any]) -> bool:
    wanted = normalized_name(name)
    rows = [
        row for row in scan_result.get("results", [])
        if normalized_name(row.get("tool_name", "")) == wanted
    ]
    return bool(rows) and all(row.get("status") == "correct" for row in rows)


def _has_group(tool_names: List[str], required: List[str]) -> bool:
    available = set(tool_names)
    return bool(required) and all(name in available for name in required)


CAPABILITY_DISPLAY_NAMES = {
    "hermes_memory": "Hermes memory",
    "ai_memory": "AI memory",
    "tdai": "TDAI",
    "hermes": "Hermes",
}


def _unmanaged_installed_clients(
    registry: List[Dict[str, Any]],
    scan_result: Dict[str, Any],
    *,
    tools_registry: List[Dict[str, Any]] = (),
    exempt: List[str] = (),
) -> List[Dict[str, Any]]:
    """Installed-but-unmanaged clients, minus managed and exempted names.

    Managed means registered in either registry: ``mcp_tools`` (MCP-capable
    clients) or ``tools`` (skills-only clients such as GitHub Copilot — L2
    manages their links even though there is no MCP surface). ``exempt``
    (config ``unmanaged_exempt``) silences known non-skill consumers whose
    links exist anyway (e.g. cc-switch, a config switcher).
    """
    managed_names = set()
    for tool in list(registry) + list(tools_registry):
        for candidate in [tool.get("name", "")] + list(tool.get("aliases", []) or []):
            managed_names.add(normalized_name(candidate))
    exempt_names = {normalized_name(name) for name in exempt}

    unmanaged = {}
    for row in scan_result.get("results", []):
        name = row.get("tool_name", "")
        normalized = normalized_name(name)
        if not row.get("is_installed", False) or normalized in managed_names:
            continue
        if normalized in exempt_names:
            continue
        record = unmanaged.setdefault(
            normalized,
            {"name": name, "skills_compliant": True, "paths": []},
        )
        record["skills_compliant"] = (
            record["skills_compliant"] and row.get("status") == "correct"
        )
        record["paths"].append(row.get("path", ""))
    return list(unmanaged.values())


def _load_tool_servers(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Load and merge MCP servers from the primary ``config_path`` and any
    declared ``config_candidates``.

    Some clients keep the unified Hermes endpoint in an alternate config file
    (e.g. DSH exposes it via ``~/.dsh/mcp.json`` while the registry's primary
    path is the cordis loader-patch). Merging every candidate lets the checker
    report the client as configured whenever the canonical endpoint is present
    in *any* of the expected locations, without changing which file ``--fix-mcp``
    writes to.
    """
    servers: Dict[str, Any] = {}
    primary = load_mcp_servers(
        tool.get("config_path", ""),
        tool.get("format", "json"),
        tool.get("mcp_key_path", ["mcpServers"]),
    )
    servers.update(primary)
    for candidate in tool.get("config_candidates", []) or []:
        if not isinstance(candidate, dict):
            continue
        candidate_servers = load_mcp_servers(
            candidate.get("path", ""),
            candidate.get("format", "json"),
            candidate.get("key_path", tool.get("mcp_key_path", ["mcpServers"])),
        )
        servers.update(candidate_servers)
    return servers


def _skill_state_fields(name: str, scan_result: Dict[str, Any], tool: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Stage-4 L5 fields for one record, derived from the skills scan rows.

    Clients without a registered skills dir (no matching scan row) get empty
    ``skill_states`` with ``skill_link_form="mixed"``: L5 is not applicable and
    the drift audit excludes them. ``records`` fields only grow (design §1.2).

    ``native_disable`` markers (read-only, client-owned; item 7) are applied as
    an overlay on link truth and surfaced via ``native_disabled_skills`` so the
    audit channels can exempt them from the symlink-residue check.
    """
    wanted = normalized_name(name)
    unified = scan_result.get("unified_dir", "")
    native = read_native_disabled(tool or {})
    paths = [
        row.get("expanded_path")
        for row in scan_result.get("results", [])
        if normalized_name(row.get("tool_name", "")) == wanted and row.get("expanded_path")
    ]
    if not unified or not paths:
        return {
            "skill_states": {},
            "skills_enabled_count": 0,
            "skills_total": 0,
            "skill_link_form": "mixed",
            "native_disabled_skills": [],
        }
    states: Dict[str, str] = {}
    forms = set()
    for path in paths:
        forms.add(skill_link_form(path, unified))
        for skill, state in read_skill_states(path, unified, native_disabled=frozenset(native)).items():
            if state == "enabled" or skill not in states:
                states[skill] = state
    return {
        "skill_states": states,
        "skills_enabled_count": sum(1 for value in states.values() if value == "enabled"),
        "skills_total": len(states),
        "skill_link_form": "mixed" if len(forms) > 1 else next(iter(forms)),
        "native_disabled_skills": sorted(native & set(states)),
    }


def check_agents(
    config: Dict[str, Any],
    scan_result: Dict[str, Any],
    *,
    live_probe: bool = False,
    profile: Optional[Dict[str, Any]] = None,
    endpoint_key: Optional[str] = None,
) -> Dict[str, Any]:
    expected = profile if profile is not None else config.get("unified_mcp", {})
    expected_name = expected.get("name", "hermes")
    expected_url = expected.get("url", "")
    legacy_names = expected.get("legacy_names", [])
    probe = probe_mcp(
        expected_url,
        transport=expected.get("transport", "streamable-http"),
        command=expected.get("command"),
        args=expected.get("args"),
        env=expected.get("env"),
        timeout=expected.get("probe_timeout", 8.0),
        token=expected.get("auth_token"),
        token_env=expected.get("auth_token_env"),
        url_policy=expected.get("url_policy", "strict"),
    ) if live_probe else {
        "initialize_ok": False, "tools_list_ok": False, "tool_names": [], "error": "not probed"
    }
    required = expected.get("required_capabilities", {}) or {}
    capability_groups = list(required.keys())
    # hooks（AI-memory lifecycle hooks）只在端点声明 ai_memory 能力时才适用。
    # 纯工具端点（如 K8s/Kuboard，required_capabilities={}）没有 hooks 概念，
    # 不应被「客户端未配 hermes hooks」拖累其合规判定。
    hooks_required = "ai_memory" in required
    registry = effective_tools(config)
    # Stage-5 P2: per-client attachment narrows which clients are expected to
    # mount THIS endpoint.  Only when at least one client declares ``mcp_attach``
    # do we filter; otherwise the library keeps the full-matrix behaviour and the
    # result is byte-for-byte identical to stage-2.
    attach_filter_applied = False
    if endpoint_key and has_explicit_attach(config):
        attach_filter_applied = True
        attached = clients_attached_to(config, endpoint_key)
        registry = [
            tool for tool in registry
            if normalized_name(tool.get("name", "")) in attached
        ]
    records = []
    for tool in registry:
        install = detect_installation(tool)
        servers = _load_tool_servers(tool)
        mcp = inspect_mcp_configuration(
            servers,
            expected_name=tool.get("unified_name") or expected_name,
            expected_url=expected_url,
            legacy_names=_merged_legacy_names(expected, tool),
        )
        hooks = check_hooks(tool.get("hooks_config_path", "")) if tool.get("hooks_config_path") else {
            "hooks_configured": False, "events": []
        }
        configured_and_probed = mcp["mcp_configured"] and live_probe
        tool_names = probe["tool_names"] if configured_and_probed else []
        capabilities = {
            group: _has_group(tool_names, names)
            for group, names in required.items()
        }
        records.append({
            "name": tool.get("name", "Unknown"),
            "installed": install["installed"],
            "install_state": install["install_state"],
            "install_evidence": install["evidence"],
            "app_paths": install["app_paths"],
            "cli_paths": install["cli_paths"],
            "config_paths": install["config_paths"],
            "skills_compliant": _skills_compliant(tool.get("name", ""), scan_result),
            "mcp_configured": mcp["mcp_configured"],
            "configured_url": mcp["configured_url"],
            "mcp_initialize_ok": configured_and_probed and probe["initialize_ok"],
            "mcp_tools_list_ok": configured_and_probed and probe["tools_list_ok"],
            "capabilities": capabilities,
            # 平铺四组能力布尔字段（规格 Status Model）。缺组的 profile 落 False。
            "hermes_memory_available": capabilities.get("hermes_memory", False),
            "ai_memory_available": capabilities.get("ai_memory", False),
            "tdai_available": capabilities.get("tdai", False),
            "hermes_available": capabilities.get("hermes", False),
            "hooks_configured": hooks["hooks_configured"],
            "hooks_required": hooks_required,
            "hook_events": hooks["events"],
            "legacy_channels": mcp["legacy_channels"],
            **_skill_state_fields(tool.get("name", ""), scan_result, tool),
        })
    unmanaged = _unmanaged_installed_clients(
        registry,
        scan_result,
        tools_registry=config.get("tools", []) or [],
        exempt=config.get("unmanaged_exempt", []) or [],
    )
    summary = summarize_records(records)
    summary["unmanaged_mcp"] = len(unmanaged)
    # ARCH-6: make the filtering semantics visible so consumers can tell whether
    # this per-endpoint result was narrowed by explicit client attach (vs the
    # default full-matrix).  False = full matrix / endpoint_key None / no
    # explicit attach declared anywhere.
    summary["attach_filter_applied"] = attach_filter_applied
    result = {
        "endpoint": expected_url,
        "probe": probe,
        "records": records,
        "unmanaged": unmanaged,
        "summary": summary,
        "capability_groups": capability_groups,
    }
    # Stage-4 L5: cross-client skill-state drift is computed once per result and
    # surfaced at the result level (design §4.3); records only grow fields.
    audit = audit_skill_states(result)
    result["skill_state_drift"] = audit["skill_state_drift"]
    summary["skill_state_consistent"] = audit["skill_state_consistent"]
    return result


def result_ok(result: Dict[str, Any], *, strict_skill_state: bool = False) -> bool:
    """Phase-2 exit-code judgment: is a ``check_agents`` result fully compliant?

    Non-compliant (``False``) when a live probe failed, any installed client
    fails a required field (skills / MCP configure / initialize / tools-list /
    hooks), any capability group is unmet, any legacy channel remains, or any
    unmanaged installed client is present.

    Stage-4 (design §4.4): by default the L5 skill state is NOT part of this
    judgment. ``strict_skill_state=True`` (CLI ``--strict-skill-state``)
    additionally requires cross-client skill-state consistency.
    """
    probe_error = (result.get("probe") or {}).get("error", "")
    if probe_error and probe_error != "not probed":
        return False
    for record in result.get("records", []) or []:
        if not record.get("installed"):
            continue
        if not (
            record.get("skills_compliant")
            and record.get("mcp_configured")
            and record.get("mcp_initialize_ok")
            and record.get("mcp_tools_list_ok")
            and (record.get("hooks_configured") or not record.get("hooks_required", True))
        ):
            return False
        if record.get("legacy_channels"):
            return False
        capabilities = record.get("capabilities", {}) or {}
        if not all(capabilities.values()):
            return False
    if result.get("unmanaged"):
        return False
    if strict_skill_state:
        summary = result.get("summary") or {}
        if "skill_state_consistent" in summary:
            if not summary["skill_state_consistent"]:
                return False
        elif not audit_skill_states(result)["skill_state_consistent"]:
            return False
    return True


def format_combined_report(result: Dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "",
        "=" * 88,
        "  IDE/Agent Skills + Unified MCP Report",
        "=" * 88,
        "  Endpoint: " + result["endpoint"],
        (
            "  Summary: installed={installed} skills={skills_compliant} configured={mcp_configured} "
            "connected={mcp_connected} full={full_capabilities} hooks={hooks_configured} "
            "legacy={legacy_channels} unmanaged={unmanaged_mcp}"
        ).format(**summary),
        "-" * 88,
    ]
    for record in result["records"]:
        if not record["installed"]:
            continue
        status = "OK" if record["mcp_tools_list_ok"] else ("CONFIG" if record["mcp_configured"] else "MISSING")
        legacy = ",".join(record["legacy_channels"]) or "none"
        lines.append(
            "  {name:<16} skills={skills!s:<5} mcp={status:<7} hooks={hooks!s:<5} legacy={legacy}".format(
                name=record["name"], skills=record["skills_compliant"], status=status,
                hooks=record["hooks_configured"], legacy=legacy,
            )
        )
    for record in result.get("unmanaged", []):
        lines.append(
            "  {name:<16} skills={skills!s:<5} mcp=UNMANAGED (no verified registry format)".format(
                name=record["name"], skills=record["skills_compliant"]
            )
        )
    if result["probe"].get("error") and result["probe"]["error"] != "not probed":
        lines.append("  Probe error: " + result["probe"]["error"])
    return "\n".join(lines)


def format_combined_markdown(result: Dict[str, Any]) -> str:
    """Render the same aggregate state as a durable Markdown report section."""
    summary = result["summary"]
    lines = [
        "## IDE / Agent Unified MCP",
        "",
        f"**Endpoint**: `{result['endpoint']}`",
        "",
        (
            "Installed: **{installed}** · Skills compliant: **{skills_compliant}** · "
            "MCP configured: **{mcp_configured}** · Connected: **{mcp_connected}** · "
            "Full capabilities: **{full_capabilities}** · Hooks: **{hooks_configured}** · "
            "Legacy channels: **{legacy_channels}**"
        ).format(**summary),
        f"Unmanaged installed clients: **{summary.get('unmanaged_mcp', 0)}**",
        "",
    ]

    groups = result.get("capability_groups", [])
    cap_headers = [
        CAPABILITY_DISPLAY_NAMES.get(group, group.replace("_", " ").title())
        for group in groups
    ]
    if groups == list(CAPABILITY_DISPLAY_NAMES):
        header = (
            "| Client | Installed | Skills | MCP configured | Initialize | Tools list | "
            "Hermes memory | AI memory | TDAI | Hermes | Hooks | Legacy channels |"
        )
        separator = "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"
    else:
        prefix = "| Client | Installed | Skills | MCP configured | Initialize | Tools list | "
        if cap_headers:
            header = prefix + " | ".join(cap_headers) + " | Hooks | Legacy channels |"
        else:
            header = prefix + "Hooks | Legacy channels |"
        separator = "|" + "---|" * (6 + len(groups) + 2)
    lines.extend([header, separator])

    for record in result["records"]:
        legacy = ", ".join(record["legacy_channels"]) or "none"
        capability_values = [
            record.get("capabilities", {}).get(group, False) for group in groups
        ]
        values = [
            record["name"], record["installed"], record["skills_compliant"],
            record["mcp_configured"], record["mcp_initialize_ok"],
            record["mcp_tools_list_ok"],
        ] + capability_values + [record["hooks_configured"], legacy]
        lines.append("| " + " | ".join(str(value) for value in values) + " |")
    if result.get("unmanaged"):
        lines.extend([
            "",
            "### Installed clients without verified MCP repair support",
            "",
        ])
        for record in result["unmanaged"]:
            lines.append(
                f"- `{record['name']}`: Skills compliant={record['skills_compliant']}; "
                "MCP configuration was not modified."
            )
    probe_error = result.get("probe", {}).get("error")
    if probe_error and probe_error != "not probed":
        lines.extend(["", f"Probe error: `{probe_error}`"])
    return "\n".join(lines)
