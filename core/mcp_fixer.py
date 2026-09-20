"""Safe, atomic repair for the canonical Hermes MCP client entry."""

import json
import os
import re
import shutil
import stat
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from mcp_checker import inspect_mcp_configuration, load_mcp_servers
from ops_log import ops_log
from tool_registry import detect_installation, effective_tools, normalized_name


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


try:
    import tomllib as _toml
except ImportError:  # Python < 3.11
    import tomli as _toml

import yaml


def _load_cordis_yaml(text: str) -> Any:
    """Parse a cordis patch YAML document tolerating ``!!js`` expressions.

    DSH cordis loader-patch uses the custom ``!!js`` tag for runtime JS
    expressions (e.g. env-var bearer headers). PyYAML cannot construct that tag,
    so we register it as an opaque scalar for validation only; the value is never
    used to make fixes decisions.
    """
    class CordisLoader(yaml.SafeLoader):
        pass

    CordisLoader.add_constructor(
        "tag:yaml.org,2002:js",
        lambda loader, node: loader.construct_scalar(node),
    )
    return yaml.load(text, Loader=CordisLoader)


def _result(tool: Dict[str, Any], status: str, message: str) -> Dict[str, str]:
    return {
        "name": tool.get("name", "Unknown"),
        "path": os.path.expanduser(tool.get("config_path", "")),
        "status": status,
        "message": message,
    }


def _nested_container(data: Dict[str, Any], key_path: List[str]) -> Dict[str, Any]:
    current = data
    for key in key_path:
        value = current.get(key)
        if value is None:
            value = {}
            current[key] = value
        if not isinstance(value, dict):
            raise ValueError("configured MCP key is not an object")
        current = value
    return current


def _bearer_headers(token: str) -> Dict[str, str]:
    """落库用鉴权头：`Authorization: Bearer <token>`，token 明文写入客户端配置。"""
    return {"Authorization": "Bearer " + token}


def _render_json(text: str, key_path: List[str], name: str, url: str, token: str = "") -> str:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    servers = _nested_container(data, key_path)
    entry = {"url": url}
    if token:
        entry["headers"] = _bearer_headers(token)
    servers[name] = entry
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _render_yaml(text: str, key_path: List[str], name: str, url: str, token: str = "") -> str:
    """Write a unified MCP server entry into a generic YAML config file.

    Generic YAML clients (e.g. Hermes Agent ``~/.hermes/config.yaml``) expect
    the ``mcp_servers`` mapping inside the YAML document.  Empty or absent
    content starts from an empty mapping; comments are preserved where safe.
    """
    data = yaml.safe_load(text) if text.strip() else {}
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("YAML root must be an object")
    servers = _nested_container(data, key_path)
    entry = {"url": url}
    if token:
        entry["headers"] = _bearer_headers(token)
    servers[name] = entry
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _render_reasonix(text: str, key_path: List[str], name: str, url: str, token: str = "") -> str:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Reasonix root must be an object")
    if len(key_path) != 1:
        raise ValueError("unsupported Reasonix MCP key path")
    items = data.get(key_path[0])
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise ValueError("Reasonix MCP configuration must be a string array")

    replacement = f"{name}={url}"
    updated = []
    inserted = False
    for item in items:
        item_name, separator, _ = item.partition("=")
        if separator and item_name.strip() == name:
            if not inserted:
                updated.append(replacement)
                inserted = True
            continue
        updated.append(item)
    if not inserted:
        updated.append(replacement)
    data[key_path[0]] = updated
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _toml_section_ranges(text: str, section_name: str) -> List[Tuple[int, int]]:
    header = re.compile(
        r"(?m)^\s*\[" + re.escape(section_name) + r"\]\s*(?:#.*)?$"
    )
    any_header = re.compile(r"(?m)^\s*\[[^\]]+\]\s*(?:#.*)?$")
    ranges = []
    for match in header.finditer(text):
        following = any_header.search(text, match.end())
        ranges.append((match.start(), following.start() if following else len(text)))
    return ranges


def _toml_section_tree_ranges(text: str, section_name: str) -> List[Tuple[int, int]]:
    """Return the parent TOML table and every dotted child table range."""
    header = re.compile(
        r"(?m)^\s*\[" + re.escape(section_name) + r"(?:\.[^\]]+)?\]\s*(?:#.*)?$"
    )
    any_header = re.compile(r"(?m)^\s*\[[^\]]+\]\s*(?:#.*)?$")
    ranges = []
    for match in header.finditer(text):
        following = any_header.search(text, match.end())
        ranges.append((match.start(), following.start() if following else len(text)))
    return ranges


def _render_toml(text: str, name: str, url: str, token: str = "") -> str:
    _toml.loads(text)
    section_name = f"mcp_servers.{name}"
    ranges = _toml_section_ranges(text, section_name)
    if len(ranges) > 1:
        raise ValueError("duplicate canonical MCP sections")
    if not ranges:
        separator = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        block = f'[{section_name}]\nurl = "{url}"\n'
        if token:
            block += f'http_headers = {{ Authorization = "Bearer {token}" }}\n'
        return text + separator + block

    start, end = ranges[0]
    section = text[start:end]
    url_line = re.compile(
        r'(?m)^(\s*url\s*=\s*)(["\'])(.*?)(\2)(\s*(?:#.*)?)$'
    )
    matches = list(url_line.finditer(section))
    if len(matches) > 1:
        raise ValueError("duplicate canonical MCP URL keys")
    if matches:
        match = matches[0]
        replacement = match.group(1) + match.group(2) + url + match.group(4) + match.group(5)
        section = section[:match.start()] + replacement + section[match.end():]
    else:
        header_end = section.find("\n")
        if header_end < 0:
            section += f'\nurl = "{url}"\n'
        else:
            section = section[:header_end + 1] + f'url = "{url}"\n' + section[header_end + 1:]
    # 鉴权：Codex 官方字段 ``http_headers`` 静态表承载明文 ``Authorization`` 头；
    # 同时清理旧的环境变量引用写法（bearer_token_env_var）。
    section = _remove_toml_field(section, "bearer_token_env_var")
    if token:
        section = _set_toml_http_headers(section, token)
    else:
        section = _remove_toml_http_headers(section)
    rendered = text[:start] + section + text[end:]
    _toml.loads(rendered)
    return rendered


def _toml_header_end(block: str) -> int:
    """Return the offset just past the ``[section]`` header line, or ``len(block)``.

    The section block given by :func:`_toml_section_ranges` may begin with a
    leading separator newline, so a naive ``block.find("\\n")`` would anchor on
    the wrong line. Anchor on the first ``[...]`` header instead.
    """
    header = re.compile(r"(?m)^\s*\[[^\]]+\]")
    match = header.search(block)
    if not match:
        return len(block)
    newline = block.find("\n", match.end())
    return newline + 1 if newline >= 0 else len(block)


def _set_toml_field(block: str, field: str, value: str) -> str:
    """Replace or insert a ``field = "value"`` line inside a TOML section block.

    Insert point is right after the section header line; replacement is in place
    when the field already exists. Unlike :func:`_replace_or_insert_toml_field`
    (reasonix plugin blocks keyed by a ``name`` line), this works on any section.
    """
    field_line = re.compile(
        r"(?m)^(\s*" + re.escape(field) + r'\s*=\s*)(["\'])(.*?)(\2)(\s*(?:#.*)?)$'
    )
    matches = list(field_line.finditer(block))
    if len(matches) > 1:
        raise ValueError(f"duplicate canonical section field {field!r}")
    if matches:
        match = matches[0]
        replacement = match.group(1) + match.group(2) + value + match.group(4) + match.group(5)
        return block[:match.start()] + replacement + block[match.end():]
    header_end = _toml_header_end(block)
    return block[:header_end] + f'{field} = "{value}"\n' + block[header_end:]


def _remove_toml_field(block: str, field: str) -> str:
    """Drop a ``field = "..."`` line from a TOML section block (idempotent)."""
    field_line = re.compile(
        r"(?m)^[ \t]*" + re.escape(field) + r'\s*=\s*(["\'])(.*?)\1[ \t]*(?:#.*)?\n'
    )
    return field_line.sub("", block)


def _set_toml_http_headers(block: str, token: str) -> str:
    """Replace or insert a ``http_headers = { Authorization = "Bearer <token>" }`` line.

    Insert point is right after the section header line, matching the sibling
    :func:`_set_toml_field` convention.
    """
    value = '{ Authorization = "Bearer ' + token + '" }'
    line = re.compile(r"(?m)^[ \t]*http_headers\s*=.*(?:\n|$)")
    if line.search(block):
        return line.sub(f"http_headers = {value}\n", block, count=1)
    header_end = _toml_header_end(block)
    return block[:header_end] + f"http_headers = {value}\n" + block[header_end:]


def _remove_toml_http_headers(block: str) -> str:
    """Drop an ``http_headers = ...`` inline-table line from a TOML section block."""
    line = re.compile(r"(?m)^[ \t]*http_headers\s*=.*(?:\n|$)")
    return line.sub("", block)


def _reasonix_plugin_ranges(text: str) -> List[Tuple[int, int]]:
    plugin_header = re.compile(r"(?m)^\s*\[\[plugins\]\]\s*(?:#.*)?$")
    any_header = re.compile(r"(?m)^\s*\[{1,2}[^\]]+\]{1,2}\s*(?:#.*)?$")
    ranges = []
    for match in plugin_header.finditer(text):
        following = any_header.search(text, match.end())
        ranges.append((match.start(), following.start() if following else len(text)))
    return ranges


def _toml_string_field(block: str, field: str) -> str:
    match = re.search(
        r"(?m)^\s*" + re.escape(field) + r'\s*=\s*(["\'])(.*?)\1\s*(?:#.*)?$',
        block,
    )
    return match.group(2) if match else ""


def _replace_or_insert_toml_field(block: str, field: str, value: str) -> str:
    field_line = re.compile(
        r"(?m)^(\s*" + re.escape(field) + r'\s*=\s*)(["\'])(.*?)(\2)(\s*(?:#.*)?)$'
    )
    matches = list(field_line.finditer(block))
    if len(matches) > 1:
        raise ValueError("duplicate canonical plugin fields")
    if matches:
        match = matches[0]
        replacement = match.group(1) + match.group(2) + value + match.group(4) + match.group(5)
        return block[:match.start()] + replacement + block[match.end():]

    name_line = re.search(r"(?m)^\s*name\s*=.*$", block)
    if not name_line:
        raise ValueError("canonical plugin has no name field")
    insert_at = name_line.end()
    return block[:insert_at] + f'\n{field} = "{value}"' + block[insert_at:]


def _render_reasonix_toml(text: str, name: str, url: str, token: str = "") -> str:
    _toml.loads(text)
    matching = []
    for start, end in _reasonix_plugin_ranges(text):
        if _toml_string_field(text[start:end], "name") == name:
            matching.append((start, end))
    if len(matching) > 1:
        raise ValueError("duplicate canonical Reasonix plugins")
    if not matching:
        separator = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        lines = ['[[plugins]]', f'name = "{name}"', 'type = "http"', f'url = "{url}"']
        if token:
            lines.append(f'headers = {{ Authorization = "Bearer {token}" }}')
        rendered = text + separator + "\n".join(lines) + "\n"
    else:
        start, end = matching[0]
        block = text[start:end]
        block = _replace_or_insert_toml_field(block, "type", "http")
        block = _replace_or_insert_toml_field(block, "url", url)
        if token:
            block = _set_reasonix_headers(block, token)
        else:
            block = _remove_reasonix_headers(block)
        rendered = text[:start] + block + text[end:]
    _toml.loads(rendered)
    return rendered


def _set_reasonix_headers(block: str, token: str) -> str:
    """Set the reasonix http plugin ``headers`` inline table to a plaintext bearer token."""
    value = f'{{ Authorization = "Bearer {token}" }}'
    line = re.compile(r"(?m)^[ \t]*headers\s*=.*(?:\n|$)")
    if line.search(block):
        return line.sub(f'headers = {value}\n', block, count=1)
    name_line = re.search(r"(?m)^\s*name\s*=.*$", block)
    if not name_line:
        return block + f'headers = {value}\n'
    insert_at = name_line.end()
    return block[:insert_at] + f'\nheaders = {value}' + block[insert_at:]


def _remove_reasonix_headers(block: str) -> str:
    line = re.compile(r"(?m)^[ \t]*headers\s*=.*(?:\n|$)")
    return line.sub("", block)


def _cordis_entry_block(url: str, name: str = "hermes", token: str = "") -> str:
    block = (
        f"- id: mcp-{name}\n"
        "  name: '@deepseek-ai/dsh-mcp-client'\n"
        "  config:\n"
        f"    serverName: {name}\n"
        "    transport: streamable-http\n"
        f"    url: {url}\n"
    )
    if token:
        block += (
            "    headers:\n"
            f'      Authorization: "Bearer {token}"\n'
        )
    return block


def _render_cordis_yaml(text: str, name: str, url: str, token: str = "") -> str:
    """Insert or replace the canonical cordis patch entry for serverName ``name``.

    The canonical channel for DSH uses serverName `hermes`; additional managed
    endpoints become their own ``mcp-<name>`` entry block. Other top-level entries
    and file-level comments are preserved; only the matching block is rewritten.
    """
    lines = text.splitlines(keepends=True)
    entry_id = f"mcp-{name}"
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^- id:\s*" + re.escape(entry_id) + r"\s*$", line):
            start = i
            break
    if start is not None:
        block_end = len(lines)
        for j in range(start + 1, len(lines)):
            if re.match(r"^- id:\s", lines[j]):
                block_end = j
                break
        rendered = "".join(lines[:start]) + _cordis_entry_block(url, name, token) + "".join(lines[block_end:])
    else:
        separator = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        rendered = text + separator + _cordis_entry_block(url, name, token)
    _load_cordis_yaml(rendered)  # validate the rewritten document
    return rendered


def _render(tool: Dict[str, Any], text: str, name: str, url: str, token: str = "") -> str:
    config_format = tool.get("format", "json")
    key_path = tool.get("mcp_key_path", ["mcpServers"])
    if config_format in ("json", "jsonc"):
        return _render_json(text, key_path, name, url, token)
    if config_format == "toml":
        return _render_toml(text, name, url, token)
    if config_format == "reasonix_toml":
        return _render_reasonix_toml(text, name, url, token)
    if config_format == "reasonix":
        return _render_reasonix(text, key_path, name, url, token)
    if config_format == "cordis_yaml":
        return _render_cordis_yaml(text, name, url, token)
    if config_format == "yaml":
        return _render_yaml(text, key_path, name, url, token)
    raise ValueError("unsupported MCP configuration format")


def _render_without_entries(
    tool: Dict[str, Any], text: str, keys: List[str]
) -> str:
    """Remove exactly the named MCP entries from a client config.

    原 ``_render_without_legacy``：删除逻辑与「legacy」无关，只是一组待删 key，
    故泛化命名以复用同一条实现（六种格式共用）。

    不变式：**没有命中任何待删 key 时原样返回 ``text``**（六个格式一致）。调用方
    以 ``rendered == original`` 判定 unchanged；若某个格式在空删时仍重新序列化，
    就会把「无操作」误报成 updated 并顺手改写用户的配置文件（含备份）。TOML 与
    cordis 天然满足该不变式，JSON/YAML/Reasonix 需在 pop 之前显式短路。
    """
    targets = set(keys)
    config_format = tool.get("format", "json")
    key_path = tool.get("mcp_key_path", ["mcpServers"])

    if config_format == "cordis_yaml":
        return _render_cordis_without_entries(text, keys)

    if config_format == "yaml":
        data = yaml.safe_load(text) if text.strip() else {}
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ValueError("YAML root must be an object")
        current = data
        for key in key_path:
            current = current.get(key)
            if current is None:
                return text
            if not isinstance(current, dict):
                raise ValueError("configured MCP key is not an object")
        if not any(name in current for name in targets):
            return text  # nothing removed; keep original (preserves comments/format)
        for name in targets:
            current.pop(name, None)
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    if config_format in ("json", "jsonc"):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("JSON root must be an object")
        current = data
        for key in key_path:
            current = current.get(key)
            if current is None:
                return text
            if not isinstance(current, dict):
                raise ValueError("configured MCP key is not an object")
        if not any(name in current for name in targets):
            return text  # nothing removed; keep original (preserves comments/format)
        for name in targets:
            current.pop(name, None)
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    if config_format == "reasonix":
        data = json.loads(text)
        if not isinstance(data, dict) or len(key_path) != 1:
            raise ValueError("unsupported Reasonix MCP key path")
        items = data.get(key_path[0])
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise ValueError("Reasonix MCP configuration must be a string array")
        if not any(item.partition("=")[0].strip() in targets for item in items):
            return text  # nothing removed; keep original (preserves comments/format)
        data[key_path[0]] = [
            item for item in items if item.partition("=")[0].strip() not in targets
        ]
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    _toml.loads(text)
    if config_format == "toml":
        ranges = []
        for name in targets:
            ranges.extend(_toml_section_tree_ranges(text, f"mcp_servers.{name}"))
    elif config_format == "reasonix_toml":
        ranges = [
            (start, end)
            for start, end in _reasonix_plugin_ranges(text)
            if _toml_string_field(text[start:end], "name") in targets
        ]
    else:
        raise ValueError("unsupported MCP configuration format")

    rendered = text
    for start, end in sorted(ranges, reverse=True):
        rendered = rendered[:start] + rendered[end:]
    _toml.loads(rendered)
    return rendered


def _render_without_legacy(
    tool: Dict[str, Any], text: str, legacy_names: List[str]
) -> str:
    """向后兼容别名（旧调用点与 tests/test_mcp_fixer.py 沿用此名）。"""
    return _render_without_entries(tool, text, legacy_names)


def _render_cordis_without_entries(text: str, keys: List[str]) -> str:
    """Remove only the named legacy MCP entries from a cordis YAML array."""
    data = yaml.safe_load(text)
    if not isinstance(data, list):
        return text
    targets = set(keys)
    filtered = [
        entry for entry in data
        if not (
            isinstance(entry, dict)
            and isinstance(entry.get("config"), dict)
            and entry["config"].get("serverName") in targets
        )
    ]
    if len(filtered) == len(data):
        return text  # nothing removed; keep original (preserves comments/format)
    return yaml.safe_dump(filtered, sort_keys=False, allow_unicode=True)


def _reasonix_servers(path: str, key_path: List[str]) -> Dict[str, Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or len(key_path) != 1:
        return {}
    items = data.get(key_path[0], [])
    servers = {}
    if not isinstance(items, list):
        return servers
    for item in items:
        if not isinstance(item, str) or "=" not in item:
            continue
        name, value = item.split("=", 1)
        value = value.strip()
        if value.startswith("https://"):
            servers[name.strip()] = {"url": value}
    return servers


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


def _backup_path(path: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return f"{path}.bak-{timestamp}"


def _atomic_write(path: str, content: str, mode: int) -> None:
    directory = os.path.dirname(path) or "."
    descriptor, temp_path = tempfile.mkstemp(
        dir=directory, prefix=f".{os.path.basename(path)}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def _restore_backup(backup_path: str, path: str, mode: int) -> None:
    with open(backup_path, "r", encoding="utf-8") as handle:
        original = handle.read()
    _atomic_write(path, original, mode)


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
    each one by its own ``name``). Lazy import avoids a load-time cycle.
    """
    from profile_loader import list_profiles, load_profile

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


_GENERIC_REMOVAL_MESSAGES = {
    "unchanged": "没有匹配到要移除的条目",
    "dry-run": "将移除匹配到的条目",
    "updated": "条目已移除并校验通过",
}

# 旧 CLI 输出被 GUI 字符串匹配消费（gui/dashboard.html:4406），必须逐字不变。
_LEGACY_REMOVAL_MESSAGES = {
    "unchanged": "没有残留的旧通道条目",
    "dry-run": "将移除旧通道条目",
    "updated": "旧通道条目已移除并校验通过",
}


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
    expected = profile if profile is not None else config.get("unified_mcp", {})
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
