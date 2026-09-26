"""MCP 配置修复与去重（写安全链 + 编排）。

纯渲染已拆到 mcp_fixer_render.py（评审清单 P2-16）；本模块保留 validate/写安全链/编排，
并逐名再导出渲染函数，使 `mcp_fixer.<name>` 与拆分前一致。
"""
import json
import os
import shutil
import stat
from typing import Any, Dict, List, Optional, Tuple
from config_codec import parse_cordis_yaml as _parse_cordis_yaml
from file_atomic import atomic_write as _atomic_write, backup_path as _backup_path
from jsonc_text import mask_jsonc_comments
from mcp_checker import inspect_mcp_configuration, load_mcp_servers
from ops_log import ops_log
from profile_loader import list_profiles, load_profile
from tool_registry import detect_installation, effective_tools, normalized_name
try:
    import tomllib as _toml
except ImportError:  # Python < 3.11
    import tomli as _toml
import yaml


# 再导出：外部多处经 `mcp_fixer` 访问这些名字，路径必须不变。
# `as` 同名字写法同时避免被 ruff F401 当未使用导入删除（见清单 P1-11）。
from mcp_fixer_render import _load_cordis_yaml as _load_cordis_yaml
from mcp_fixer_render import _result as _result
from mcp_fixer_render import _nested_container as _nested_container
from mcp_fixer_render import _bearer_headers as _bearer_headers
from mcp_fixer_render import _toml_string as _toml_string
from mcp_fixer_render import _render_json as _render_json
from mcp_fixer_render import _render_yaml as _render_yaml
from mcp_fixer_render import _render_reasonix as _render_reasonix
from mcp_fixer_render import _toml_section_ranges as _toml_section_ranges
from mcp_fixer_render import _toml_section_tree_ranges as _toml_section_tree_ranges
from mcp_fixer_render import _render_toml as _render_toml
from mcp_fixer_render import _toml_header_end as _toml_header_end
from mcp_fixer_render import _set_toml_field as _set_toml_field
from mcp_fixer_render import _remove_toml_field as _remove_toml_field
from mcp_fixer_render import _set_toml_http_headers as _set_toml_http_headers
from mcp_fixer_render import _remove_toml_http_headers as _remove_toml_http_headers
from mcp_fixer_render import _reasonix_plugin_ranges as _reasonix_plugin_ranges
from mcp_fixer_render import _toml_string_field as _toml_string_field
from mcp_fixer_render import _replace_or_insert_toml_field as _replace_or_insert_toml_field
from mcp_fixer_render import _render_reasonix_toml as _render_reasonix_toml
from mcp_fixer_render import _set_reasonix_headers as _set_reasonix_headers
from mcp_fixer_render import _remove_reasonix_headers as _remove_reasonix_headers
from mcp_fixer_render import _cordis_entry_block as _cordis_entry_block
from mcp_fixer_render import _render_cordis_yaml as _render_cordis_yaml
from mcp_fixer_render import _render as _render
from mcp_fixer_render import _render_without_entries as _render_without_entries
from mcp_fixer_render import _render_without_legacy as _render_without_legacy
from mcp_fixer_render import _render_cordis_without_entries as _render_cordis_without_entries
from mcp_fixer_render import _reasonix_servers as _reasonix_servers


_GENERIC_REMOVAL_MESSAGES = {
    "unchanged": "没有匹配到要移除的条目",
    "dry-run": "将移除匹配到的条目",
    "updated": "条目已移除并校验通过",
}


_LEGACY_REMOVAL_MESSAGES = {
    "unchanged": "没有残留的旧通道条目",
    "dry-run": "将移除旧通道条目",
    "updated": "旧通道条目已移除并校验通过",
}


def _effective_tools(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """合并 mcp_tools + tools + discovered，供修复/清理遍历（见 tool_registry.effective_tools）。

    让 discovered_tools.yaml 里持久化的客户端（如 VS Code）也能被 MCP 修复/清理，
    而不是只处理 config.yaml 内置的 ``mcp_tools`` 注册表。
    """
    return effective_tools(config)


def _merged_legacy_names(expected: Dict[str, Any], tool: Dict[str, Any]) -> List[str]:
    """Profile-level legacy names plus per-tool additions (order preserved).

    A client can carry legacy entries whose names collide with other clients'
    canonical names (OpenCode's stdio bridge is named ``hermes`` while its
    canonical entry is ``hermes-unified``); those can only be declared on the
    tool entry, never profile-wide.
    """
    merged = list(expected.get("legacy_names", []) or [])
    for name in tool.get("legacy_names", []) or []:
        if name not in merged:
            merged.append(name)
    return merged


def validate_config_text(tool: Dict[str, Any], text: str) -> None:
    """按客户端声明的格式做解析校验；非法时抛异常。

    与 ``_render_without_entries`` 使用完全相同的解析器，供「还原备份」等
    不经过渲染的路径复用，避免出现第二套格式判定。
    """
    config_format = tool.get("format", "json")
    if config_format == "cordis_yaml":
        _load_cordis_yaml(text)
    elif config_format == "yaml":
        yaml.safe_load(text)
    elif config_format == "json":
        json.loads(text)
    elif config_format == "jsonc":
        # jsonc 允许注释：先按长度一一对应地把注释掩成空格，再按 JSON 解析校验。
        json.loads(mask_jsonc_comments(text))
    elif config_format == "reasonix":
        json.loads(text)
    else:
        _toml.loads(text)


def _validate_written_config(
    tool: Dict[str, Any], name: str, url: str, legacy_names: List[str] = None
) -> None:
    config_format = tool.get("format", "json")
    path = os.path.expanduser(tool.get("config_path", ""))
    key_path = tool.get("mcp_key_path", ["mcpServers"])
    if config_format == "reasonix":
        servers = _reasonix_servers(path, key_path)
    elif config_format in {"toml", "reasonix_toml"}:
        with open(path, "rb") as handle:
            data = _toml.load(handle)
        if config_format == "toml":
            servers = data.get("mcp_servers", {}) if isinstance(data, dict) else {}
        else:
            plugins = data.get("plugins", []) if isinstance(data, dict) else []
            servers = {
                item["name"]: {key: value for key, value in item.items() if key != "name"}
                for item in plugins
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            }
    else:
        servers = load_mcp_servers(path, config_format, key_path)
    inspected = inspect_mcp_configuration(
        servers,
        expected_name=name,
        expected_url=url,
        legacy_names=legacy_names or [],
    )
    if not inspected["mcp_configured"]:
        raise ValueError("written MCP configuration did not validate")
    if inspected["legacy_channels"]:
        raise ValueError("legacy MCP entries remain after cleanup")


def _restore_backup(backup_path: str, path: str, mode: int) -> None:
    from file_atomic import restore_backup

    restore_backup(backup_path, path, mode)


def fix_mcp_tool(
    tool: Dict[str, Any],
    expected: Dict[str, Any],
    *,
    dry_run: bool = False,
) -> Dict[str, str]:
    """Add or update one canonical MCP entry without removing legacy entries."""
    path = os.path.expanduser(tool.get("config_path", ""))
    if not path:
        return _result(tool, "missing", "configuration path is not configured; no changes made")
    if not tool.get("fix_supported", True):
        reason = tool.get("fix_unsupported_reason", "repair is not supported for this client")
        return _result(tool, "unsupported", reason)

    name = tool.get("unified_name") or expected.get("name", "hermes")
    url = expected.get("url", "")
    # 鉴权：端点带 auth_token 时以明文 Bearer 头写入客户端配置（本机单用户场景，
    # token 已在本地 profiles 明文存储，环境变量引用在 GUI 应用里时灵时不灵）。
    token = expected.get("auth_token") or ""
    existed = os.path.isfile(path)
    config_format = tool.get("format", "json")
    initial = "{}\n" if config_format == "json" else ""
    if config_format == "reasonix":
        key_path = tool.get("mcp_key_path", ["mcpServers"])
        initial = json.dumps({key_path[0]: []}, indent=2) + "\n"
    try:
        if existed:
            with open(path, "r", encoding="utf-8") as handle:
                original = handle.read()
        else:
            original = initial
        rendered = _render(tool, original, name, url, token)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return _result(tool, "error", "configuration could not be parsed safely; no changes made")

    if rendered == original:
        return _result(tool, "unchanged", f"endpoint {name!r} is already configured")
    if dry_run:
        return _result(tool, "dry-run", f"endpoint {name!r} would be updated")

    mode = stat.S_IMODE(os.stat(path).st_mode) if existed else 0o600
    backup_path = _backup_path(path) if existed else ""
    if existed:
        try:
            shutil.copy2(path, backup_path)
        except OSError:
            return _result(tool, "error", "backup could not be created; no changes made")

    try:
        parent = os.path.dirname(path) or "."
        if os.path.islink(parent) and not os.path.exists(parent):
            raise OSError(
                f"父目录 {parent} 是失效符号链接（目标磁盘可能未挂载），无法写入"
            )
        os.makedirs(parent, exist_ok=True)
        _atomic_write(path, rendered, mode)
    except OSError as exc:
        reason = str(exc) if "失效符号链接" in str(exc) else "atomic write failed; original configuration is unchanged"
        return _result(tool, "error", reason)

    try:
        _validate_written_config(tool, name, url)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        try:
            if existed:
                _restore_backup(backup_path, path, mode)
            elif os.path.exists(path):
                os.unlink(path)
        except OSError:
            return _result(tool, "error", "validation failed and automatic rollback failed")
        return _result(tool, "error", "validation failed; original configuration was rolled back")

    action = "updated" if existed else "created"
    return _result(tool, action, f"endpoint {name!r} updated and verified")


def _endpoint_profiles(config: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """Resolve the endpoint library to ``[(key, profile_dict), ...]``.

    Returns every managed endpoint in display order (stage-5 P2: a client with
    no explicit ``mcp_attach`` mounts every endpoint, so ``--fix-mcp`` must write
    each one by its own ``name``).
    """
    out: List[Tuple[str, Dict[str, Any]]] = []
    for key in list_profiles(config):
        out.append((key, load_profile(config, key, config_path=None)["profile"]))
    return out


def fix_mcp_clients(
    config: Dict[str, Any],
    *,
    dry_run: bool = False,
    profile: Optional[Dict[str, Any]] = None,
    client: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Repair installed registry clients against every managed MCP endpoint.

    When ``profile`` is given, only that single endpoint is written (the
    ``--profile`` path); otherwise every endpoint in the library is written so
    each MCP-capable client ends up configured for all managed endpoints.

    ``client`` narrows the repair to a single registry entry by name
    (normalized comparison); when omitted every installed client is repaired.
    """
    if profile is not None:
        endpoint_pairs = [(profile.get("name", "hermes"), profile)]
    else:
        endpoint_pairs = _endpoint_profiles(config)
    wanted = normalized_name(client) if client else None
    results = []
    for tool in _effective_tools(config):
        tool_key = normalized_name(tool.get("name", ""))
        if wanted is not None and tool_key != wanted:
            ops_log("fix_mcp_skip", wanted=wanted, name=tool.get("name"), normalized=tool_key)
            continue
        # 无 MCP 配置路径的客户端（纯 skills / unmanaged）不参与 MCP 修复，
        # 而不是每个端点都报一条「missing」噪音。
        if not tool.get("config_path"):
            continue
        if not detect_installation(tool)["installed"]:
            results.append(_result(tool, "not-installed", "客户端未安装，跳过"))
            continue
        for _ep_key, expected in endpoint_pairs:
            result = fix_mcp_tool(tool, expected, dry_run=dry_run)
            results.append(result)
            ops_log(
                "fix_mcp_result",
                name=tool.get("name"),
                normalized=tool_key,
                endpoint=expected.get("name", _ep_key),
                status=result.get("status"),
                path=result.get("path"),
                message=result.get("message"),
            )
    ops_log("fix_mcp_end", wanted=wanted, total=len(results))
    return results


def remove_mcp_entries_tool(
    tool: Dict[str, Any],
    keys: List[str],
    *,
    dry_run: bool = False,
    messages: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """移除指定 key 的 MCP 条目（通用原语）。

    安全链与旧 ``remove_legacy_mcp_tool`` 完全一致：解析 → 备份 → 重新序列化 →
    再次解析校验 → 原子写。``messages`` 允许调用方覆盖 updated/unchanged/dry-run
    三个结果文案（legacy 包装用旧文案保持向后兼容）。
    """
    labels = messages or _GENERIC_REMOVAL_MESSAGES
    path = os.path.expanduser(tool.get("config_path", ""))
    if not path or not os.path.isfile(path):
        return _result(tool, "missing", "配置文件缺失，未做改动")
    if not tool.get("fix_supported", True):
        reason = tool.get("fix_unsupported_reason", "该客户端不支持此项修复")
        return _result(tool, "unsupported", reason)

    targets = [k for k in keys if isinstance(k, str) and k]
    if not targets:
        return _result(tool, "unchanged", labels["unchanged"])

    try:
        with open(path, "r", encoding="utf-8") as handle:
            original = handle.read()
        rendered = _render_without_entries(tool, original, targets)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return _result(tool, "error", "配置读取或解析失败，未做改动")

    if rendered == original:
        return _result(tool, "unchanged", labels["unchanged"])
    if dry_run:
        return _result(tool, "dry-run", labels["dry-run"])

    mode = stat.S_IMODE(os.stat(path).st_mode)
    backup_path = _backup_path(path)
    try:
        shutil.copy2(path, backup_path)
    except OSError:
        return _result(tool, "error", "无法创建备份，未做改动")

    try:
        _atomic_write(path, rendered, mode)
    except OSError:
        return _result(tool, "error", "原子写入失败，原配置未变")

    result = _result(tool, "updated", labels["updated"])
    result["backup"] = backup_path
    return result


def remove_legacy_mcp_tool(
    tool: Dict[str, Any],
    expected: Dict[str, Any],
    *,
    dry_run: bool = False,
) -> Dict[str, str]:
    """纯粹移除旧通道（legacy）条目，不校验正典端点是否已配置。

    删除旧通道不应以「正典端点已接入」为前提——正典端点缺失/待接入时，旧
    通道可能是客户端当前唯一连接，但用户仍有权选择先删旧通道、之后再用
    --fix-mcp 重新接入。实现已泛化为 ``remove_mcp_entries_tool``；此处只负责
    解析出 legacy 名单并沿用旧的输出文案（GUI 依赖字符串匹配）。
    """
    legacy_names = _merged_legacy_names(expected, tool)
    return remove_mcp_entries_tool(
        tool, legacy_names, dry_run=dry_run, messages=_LEGACY_REMOVAL_MESSAGES
    )


def remove_legacy_mcp_clients(
    config: Dict[str, Any],
    *,
    dry_run: bool = False,
    profile: Optional[Dict[str, Any]] = None,
    client: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Remove legacy entries from installed, supported clients.

    ``client`` narrows the removal to a single registry entry by name
    (normalized comparison); when omitted every installed client is processed.
    """
    if profile is not None:
        expected = profile
    else:
        # A-8: 走 profile_loader 规范化解析（含 legacy unified_mcp 包装），避免 raw
        # ``config["unified_mcp"]`` 的静默 no-op 分支。
        expected = load_profile(config)["profile"]
    wanted = normalized_name(client) if client else None
    results = []
    for tool in _effective_tools(config):
        if wanted is not None and normalized_name(tool.get("name", "")) != wanted:
            continue
        if not detect_installation(tool)["installed"]:
            results.append(_result(tool, "not-installed", "客户端未安装，跳过"))
            continue
        results.append(remove_legacy_mcp_tool(tool, expected, dry_run=dry_run))
    return results


