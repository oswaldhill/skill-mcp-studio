"""MCP 配置文本渲染（由 mcp_fixer.py 拆分，评审清单 P2-16）。

本模块只做纯文本渲染/解析，不落盘、不校验；写安全链与编排留在 mcp_fixer.py。
"""
import json
import os
import re
from typing import Any, Dict, List, Tuple
from config_codec import parse_cordis_yaml as _parse_cordis_yaml
from jsonc_text import remove_object_members
try:
    import tomllib as _toml
except ImportError:  # Python < 3.11
    import tomli as _toml
import yaml


def _load_cordis_yaml(text: str) -> Any:
    """Parse a cordis patch YAML document tolerating ``!!js`` expressions.

    Delegates to the canonical ``config_codec.parse_cordis_yaml`` (A-6); the value
    is used for validation only, never to make fix decisions.
    """
    return _parse_cordis_yaml(text)


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


def _toml_string(value: str) -> str:
    """Escape a string for embedding inside a TOML basic (double-quoted) string.

    D-8：token/url 直接 f-string 拼进 TOML 时，若含 ``"``、``\\`` 或控制字符会产生
    非法 TOML。此 helper 按 TOML 基本字符串转义规则处理后才返回带引号的字面量。
    """
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    # 其余控制字符（0x00-0x1f）用 \uXXXX 转义，保证始终为合法 TOML basic string。
    return '"' + "".join(
        ch if ord(ch) >= 0x20 or ch == "\t" else f"\\u{ord(ch):04x}"
        for ch in escaped
    ) + '"'


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
        block = f'[{section_name}]\nurl = {_toml_string(url)}\n'
        if token:
            block += f'http_headers = {{ Authorization = {_toml_string("Bearer " + token)} }}\n'
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
        replacement = match.group(1) + _toml_string(url) + match.group(5)
        section = section[:match.start()] + replacement + section[match.end():]
    else:
        header_end = section.find("\n")
        if header_end < 0:
            section += f'\nurl = {_toml_string(url)}\n'
        else:
            section = section[:header_end + 1] + f'url = {_toml_string(url)}\n' + section[header_end + 1:]
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
    return block[:header_end] + f'{field} = {_toml_string(value)}\n' + block[header_end:]


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
    value = '{ Authorization = ' + _toml_string("Bearer " + token) + ' }'
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
    return block[:insert_at] + f'\n{field} = {_toml_string(value)}' + block[insert_at:]


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
        lines = ['[[plugins]]', f'name = {_toml_string(name)}', 'type = "http"', f'url = {_toml_string(url)}']
        if token:
            lines.append(f'headers = {{ Authorization = {_toml_string("Bearer " + token)} }}')
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
    value = f'{{ Authorization = {_toml_string("Bearer " + token)} }}'
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

    if config_format == "jsonc":
        # JSONC 语义允许 // 与 /* */ 注释，json.loads 会直接判解析失败。这里改走
        # 按字节范围定点删除：只删目标成员与一个分隔逗号，注释/缩进/键序全保留。
        return remove_object_members(text, key_path, list(targets))

    if config_format == "json":
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


