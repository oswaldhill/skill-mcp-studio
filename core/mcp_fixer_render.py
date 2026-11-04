"""MCP 配置文本渲染（由 mcp_fixer.py 拆分，评审清单 P2-16）。

本模块只做纯文本渲染/解析，不落盘、不校验；写安全链与编排留在 mcp_fixer.py。
"""
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
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
    """落库用鉴权头：`Authorization: Bearer <token>`，token 明文写入客户端配置。

    仅在端点 ``auth_mode=token``（或完全没有声明 ``auth_mode``）时使用；引用型
    模式改走 :func:`_header_placeholder`，见该函数里的取舍说明。
    """
    return {"Authorization": "Bearer " + token}


#: 引用型 auth_mode 在不能求值的位置（reasonix 的 ``name=url`` 数组）里写的占位符。
AUTH_PLACEHOLDER = "<redacted>"


def resolve_auth_fields(
    profile: Dict[str, Any], auth: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """把端点的凭据声明归一成渲染器需要的字段（不含明文，除非 ``auth_mode=token``）。

    返回 ``{mode, token, env_var, keychain_service, file_path}``：

    * ``mode=token``：``token`` 是明文（历史行为，逐字节不变）；
    * ``mode=env``：``env_var`` 是变量名，客户端配置里写 ``${env:VAR}``；
    * ``mode=keychain`` / ``file``：``token`` 固定为 ``AUTH_PLACEHOLDER``，
      需要求值的位置由调用方显式传入 ``auth.evaluated_token``。

    ``auth`` 缺省时从 ``profile`` 自行解析（``auth_mode`` 缺省 = ``token``）。
    """
    if auth is None:
        from auth_secret import resolve_auth_fields as _resolve

        return _resolve(profile)
    mode = str(auth.get("mode") or "token")
    fields = {
        "mode": mode,
        "token": "",
        "env_var": "",
        "keychain_service": "",
        "file_path": "",
    }
    if mode == "token":
        fields["token"] = str(profile.get("auth_token") or "")
    elif mode == "env":
        from auth_secret import DEFAULT_ENV_VAR

        fields["env_var"] = str(profile.get("auth_token_env") or DEFAULT_ENV_VAR)
    elif mode == "keychain":
        fields["token"] = AUTH_PLACEHOLDER
        fields["keychain_service"] = str(profile.get("auth_keychain") or "")
    elif mode == "file":
        fields["token"] = AUTH_PLACEHOLDER
        fields["file_path"] = str(profile.get("auth_file") or "")
    # 求值后的明文只来自显式传入（探活/校验路径），不从 profile 反推。
    fields["evaluated_token"] = str(auth.get("evaluated_token") or "")
    return fields


def _header_placeholder(auth: Dict[str, Any], format_title: str) -> str:
    """Return the value written into ``Authorization`` for a non-plaintext mode.

    为什么不是「直接写变量引用」：各客户端对 header 值里的占位符支持**不一致**，
    而写一个客户端不认识的占位符等于写一个错误 token —— 比报错更难发现。所以
    这里分两类处理：

    * ``auth_mode=env`` **所有格式**都写 ``Bearer ${env:VAR}``： Claude Code /
      Cursor / VS Code 文档化的 header 插值语法，是唯一有据可依的通用形。
    * ``auth_mode=keychain`` / ``file`` 在 JSON/YAML/Cordis 里无法求值（没有通用
      语法，Codex 的 ``bearer_token_env_var`` 也读不了钥匙串），因此同样写成
      ``Bearer ${env.<服务名>}`` 形态的**占位符**：客户端不认时是一条会被网关
      明确拒绝的无效值，而不是在不知情中发出明文；配套动作是
      ``--auth-secret-status`` 给出的 export 提示。TOML（Codex）改用它官方的
      ``bearer_token_env_var`` 字段，见 :func:`_render_toml`。

    调用方（``fix_mcp_tool``）在写盘后把「该格式不求值/求值」的事实写进返回消息，
    保证用户不会以为配置已经能直接连上；判定见 :func:`reference_is_evaluated`。

    ``format_title`` 只用于把「求值兜底」写进代码可读性（当前不参与判断）。
    """
    mode = str(auth.get("mode") or "token")
    if mode == "env":
        return "Bearer ${env:" + str(auth.get("env_var") or "") + "}"
    # keychain / file：用同一个合法变量名（见 env_var_for）
    return "Bearer ${env." + env_var_for(auth) + "}"


#: 客户端 registry 的 ``mcp_root_env_style`` 取值 → 配置根上 env 块的**真实键名**。
#: 取值即键名（不做二次映射：``process_env`` 与 ``process_envs`` 差一个字母，
#: 多一层映射只会制造两边不一致的机会）：
#: * ``env`` —— Claude Code / Cursor / VS Code / Windsurf / Gemini CLI / OpenCode；
#: * ``process_envs`` —— Goose 的根级进程环境块。
ROOT_ENV_STYLES = ("env", "process_envs")


def reference_is_evaluated(
    config_format: str,
    mode: str,
    root_env_style: str = "",
    auth: Optional[Dict[str, Any]] = None,
) -> bool:
    """Whether the client will resolve the reference we write for this credential.

    三条「能求值」的路径，其余一律视为**不能**（写的是占位符）：

    * ``token`` —— 写的就是明文，天然可用；
    * ``toml``（Codex）—— 引用 ``bearer_token_env_var`` 是官方字段，会被解析；
    * ``root_env_style`` 非空 —— 我们把真值写进客户端配置根上的 env 块
      （JSON / YAML 两种容器都支持），客户端启动后会把它注入自身进程环境，
      于是 ``${env:VAR}`` 插值和 ``headers`` 都能取到值。

    ``cordis_yaml``（DSH）没有可写 env 的容器位置，``reasonix*`` 没有插值能力，
    二者恒为 False —— 调用方据此不得对用户宣称「已接入」。
    """
    if mode == "token":
        return True
    if config_format == "toml":
        # Codex 的 bearer_token_env_var 只接受变量名；变量名不合法时写下去也读不到。
        return bool(_toml_env_var(auth))
    return bool(root_env_style)


def _env_var_name(auth: Optional[Dict[str, Any]]) -> str:
    """引用型凭据对应的环境变量名（与 ``_toml_env_var`` 同一取值规则）。"""
    return _toml_env_var(auth)


def _apply_root_env(data: Dict[str, Any], auth: Optional[Dict[str, Any]], style: str, value: str) -> None:
    """把真值写进配置根上的 env 块（原地）。

    只为引用型且「会用 env 块求值」的客户端调用。已有同名键就覆盖 —— 该键由本工具
    管理，覆盖是幂等的；其它键原样保留。``value`` 为空时不写（避免在客户端配置里
    留下一个空变量，让用户以为已配置）。
    """
    if not style or not value:
        return
    block = data.get(style)
    if not isinstance(block, dict):
        block = {}
        data[style] = block
    block[_env_var_name(auth)] = value


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


def _render_json(
    text: str,
    key_path: List[str],
    name: str,
    url: str,
    token: str = "",
    entry_type: str = "",
    auth: Optional[Dict[str, Any]] = None,
    root_env_style: str = "",
    auth_token_value: str = "",
) -> str:
    """写入一个 JSON/JSONC 客户端配置。

    ``entry_type`` 是客户端声明的连接类型（config.yaml 的 ``mcp_entry_type``）。
    为什么需要它：OpenCode 的 ``mcp`` 段是**判别联合** —— 官方 schema 里
    ``McpRemoteConfig`` 的 ``required`` 是 ``[type, url]``、``McpLocalConfig`` 是
    ``[type, command]``。缺 ``type`` 时 OpenCode 不是忽略该条目，而是把**整份配置**
    判为无效（实测 ``opencode debug config`` 报
    ``Expected { type: local } | { type: remote }, got {"url": ...}``），于是所有
    MCP 端点一起失效。而 ``mcpServers`` 型客户端（Claude Code / Cursor / WorkBuddy）
    的条目只需 ``url``，多写 ``type`` 是多余字段。故类型由调用方按客户端传入，
    默认空（= 不写），保持既有客户端的字节级行为不变。
    """
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    servers = _nested_container(data, key_path)
    # 目标 key 已被 stdio 条目占用时**不得静默覆盖**。
    #
    # 2026-10-11 实测：`{"command": ..., "args": [...]}` 会被整条替换成
    # `{"url": ...}` —— 用户的本地 stdio 桥（如 hermes 桥）就此消失，且返回
    # status=updated、毫无提示。这正是主干 config.yaml 注释里描述的
    # 「命中同名桥并把它改写成 HTTP 形态」，此前只是改用独立 key 绕开了它。
    existing_json = servers.get(name)
    if isinstance(existing_json, dict) and (
        "command" in existing_json or "args" in existing_json
    ):
        raise McpEntryConflict(
            f"`{name}` 已被一条 stdio 条目占用（command/args），"
            "覆盖它会删除用户的本地 stdio 桥；stdio 与 url 互斥，无法按统一端点写入。"
            "请先移除该条目（--remove-mcp-entry）或为该端点改用其它 key。"
        )
    entry: Dict[str, Any] = {}
    if entry_type:
        entry["type"] = entry_type
    entry["url"] = url
    headers = _auth_headers(auth, token)
    if headers:
        entry["headers"] = headers
    servers[name] = entry
    # 引用型 + 客户端支持根 env 块：把真值写进去，客户端启动后即可求值
    # （见 reference_is_evaluated 的三条路径）。
    if auth is not None and str(auth.get("mode") or "token") != "token":
        _apply_root_env(data, auth, root_env_style, auth_token_value)
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _render_yaml(
    text: str,
    key_path: List[str],
    name: str,
    url: str,
    token: str = "",
    auth: Optional[Dict[str, Any]] = None,
    root_env_style: str = "",
    auth_token_value: str = "",
) -> str:
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
    entry: Dict[str, Any] = {"url": url}
    headers = _auth_headers(auth, token)
    if headers:
        entry["headers"] = headers
    servers[name] = entry
    if auth is not None and str(auth.get("mode") or "token") != "token":
        _apply_root_env(data, auth, root_env_style, auth_token_value)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _auth_headers(auth: Optional[Dict[str, Any]], token: str) -> Dict[str, str]:
    """JSON/YAML 形态的鉴权头：明文 token → ``Bearer <token>``；引用型 → 占位符。

    ``auth`` 为 ``None`` 表示历史调用面（只有 ``token`` 一个输入）。两种来源都为空
    时返回空字典，调用方据此不写 ``headers``，保持「端点无凭据」的既有字节输出。
    """
    if auth is None:
        return _bearer_headers(token) if token else {}
    mode = str(auth.get("mode") or "token")
    if mode == "token":
        plain = str(auth.get("token") or "")
        return _bearer_headers(plain) if plain else {}
    return {"Authorization": _header_placeholder(auth, "json")}


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
        r"(?m)^[ \t]*\[" + re.escape(section_name) + r"\][ \t]*(?:#.*)?$"
    )
    any_header = re.compile(r"(?m)^[ \t]*\[[^\]]+\][ \t]*(?:#.*)?$")
    ranges = []
    for match in header.finditer(text):
        following = any_header.search(text, match.end())
        ranges.append((match.start(), following.start() if following else len(text)))
    return ranges


def _toml_section_tree_ranges(text: str, section_name: str) -> List[Tuple[int, int]]:
    """Return the parent TOML table and every dotted child table range."""
    header = re.compile(
        r"(?m)^[ \t]*\[" + re.escape(section_name) + r"(?:\.[^\]]+)?\][ \t]*(?:#.*)?$"
    )
    any_header = re.compile(r"(?m)^[ \t]*\[[^\]]+\][ \t]*(?:#.*)?$")
    ranges = []
    for match in header.finditer(text):
        following = any_header.search(text, match.end())
        ranges.append((match.start(), following.start() if following else len(text)))
    return ranges


def _render_toml(
    text: str, name: str, url: str, token: str = "", auth: Optional[Dict[str, Any]] = None
) -> str:
    """写入 Codex 的 ``[mcp_servers.<name>]`` 表。

    ``auth``（非 ``None`` 即引用型或显式明文声明）改变鉴权写法：

    * ``auth_mode=env`` / ``keychain`` / ``file`` → 写 Codex 官方字段
      ``bearer_token_env_var = "<变量名>"``。这是 TOML 侧唯一「不发明文、客户端
      又真能求值」的形态：Token 由客户端在发起请求时从**自己的环境**读取。
      钥匙串身份（``auth_keychain``）因此被用作变量名，用户需要把这个变量注入
      客户端的启动环境（macOS 可在客户端配置里设 ``env``，或在 shell profile 中
      ``export``）；文件模式同理。
    * ``auth_mode=token`` → 既有的 ``http_headers = { Authorization = "Bearer ..." }``。
    """
    _toml.loads(text)
    section_name = f"mcp_servers.{name}"
    # 正典段唯一性只看父表本身：``_toml_section_ranges`` 不匹配 ``[X.http_headers]``，
    # 因此「父表出现两次」才是真错误（子表出现不算，见下方 tree_ranges 的合并）。
    canonical = _toml_section_ranges(text, section_name)
    if len(canonical) > 1:
        raise ValueError("duplicate canonical MCP sections")
    if not canonical:
        separator = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        block = f'[{section_name}]\nurl = {_toml_string(url)}\n'
        if _toml_uses_env_ref(auth):
            # 引用型：清掉可能的明文头，改写 bearer_token_env_var（见函数 docstring）。
            block += f'bearer_token_env_var = {_toml_string(_toml_env_var(auth))}\n'
            rendered = text + separator + block
            rendered = _set_toml_subtable_field(
                rendered, f"{section_name}.http_headers", "Authorization", None
            )
            _toml.loads(rendered)
            return rendered
        # 文件别处可能已存在 ``[<section>.http_headers]`` 子表（父表尚未声明）。
        # 这种情形下鉴权头必须写进那个子表 —— 再写一行内联 http_headers 就是重复声明。
        has_subtable = _toml_subtable_range(text, f"{section_name}.http_headers") is not None
        if token and not has_subtable:
            block += f'http_headers = {{ Authorization = {_toml_string("Bearer " + token)} }}\n'
        rendered = text + separator + block
        if has_subtable:
            rendered = _set_toml_subtable_field(
                rendered,
                f"{section_name}.http_headers",
                "Authorization",
                ("Bearer " + token) if token else None,
            )
        _toml.loads(rendered)
        return rendered

    # 父表与其点分子表（``[<section>.http_headers]`` 等）属于同一个逻辑段落，必须
    # 一起切片：只改父表会把子表留在原处，随后写入的内联 http_headers 与它重复声明，
    # 生成非法 TOML 并让整个修复失败。
    tree = _toml_section_tree_ranges(text, section_name)
    start, end = tree[0][0], tree[-1][1]
    section = text[start:end]
    url_line = re.compile(
        r'(?m)^(\s*url\s*=\s*)(["\'])(.*?)(\2)(\s*(?:#.*)?)$'
    )
    matches = list(url_line.finditer(section))
    if len(matches) > 1:
        raise ValueError("duplicate canonical MCP URL keys")
    # stdio 与 url 互斥：先判类型，再决定「更新 url」还是「保持 stdio」。
    #
    # 2026-10-11 实测事故（两次，同源）：
    #   ① 该表是 stdio 桥、无 url 行 → 修复器无条件**补写** url，Codex 拒绝：
    #      `url is not supported for stdio in \`mcp_servers.<name>\``
    #   ② 该表是 stdio、但残留了一个历史 url 行（形态曾从 URL 型翻转过来，
    #      见 ~/.codex/config.toml.bak-20261010-234804 里该表只有 ['url']）
    #      → 修复器走「更新 url」分支，**保留了 command/args**，产出的仍是混用形态。
    # 两次都因为「没先判类型」。所以类型判别必须放在这两个分支**之前**。
    if _toml_section_is_stdio(section):
        # 目标 key 被 stdio 条目占用 → 显式报冲突，不改动用户配置。
        #
        # 此前这里是「清除残留 url 后原样保留」，并让调用方报
        # 『endpoint X is already configured』—— 那是**谎报**：该条目的接入方式与
        # 期望的统一端点（url 型）不同，审计仍会判「未配置」，于是 GUI 永远显示
        # 「修复 MCP」而点了没反应。改为如实报冲突并给出处置指引。
        has_url = bool(url_line.search(section))
        raise McpEntryConflict(
            f"`{section_name}` 已被一条 stdio 条目占用（command/args）"
            + ("，且残留了 url 字段（该配置无法被客户端加载）" if has_url else "")
            + "；stdio 与 url 互斥，无法按统一端点写入。"
            "请先移除该条目（--remove-mcp-entry）或为该端点改用其它 key。"
        )
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
    if _toml_uses_env_ref(auth):
        # 引用型：两个声明位置都收敛到 bearer_token_env_var，且清掉明文头
        # （子表与内联两种形式都清，避免残留旧 token）。
        section = _set_toml_field(section, "bearer_token_env_var", _toml_env_var(auth))
        section = _remove_toml_http_headers(section)
        section = _set_toml_subtable_field(
            section, f"{section_name}.http_headers", "Authorization", None
        )
        if _toml_subtable_is_empty(section, f"{section_name}.http_headers"):
            section = _drop_toml_subtable(section, f"{section_name}.http_headers")
        rendered = text[:start] + section + text[end:]
        _toml.loads(rendered)
        return rendered
    # 鉴权：Codex 官方字段 ``http_headers`` 静态表承载明文 ``Authorization`` 头；
    # 同时清理旧的环境变量引用写法（bearer_token_env_var）。
    section = _remove_toml_field(section, "bearer_token_env_var")
    section = _apply_toml_headers(section, section_name, token)
    rendered = text[:start] + section + text[end:]
    _toml.loads(rendered)
    return rendered


def _toml_uses_env_ref(auth: Optional[Dict[str, Any]]) -> bool:
    """Whether this render should use Codex's ``bearer_token_env_var`` field."""
    return auth is not None and str(auth.get("mode") or "token") != "token"


#: POSIX 环境变量名的合法形态（shell 与大多数客户端都按这条校验）。
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def env_var_for(auth: Dict[str, Any], fallback: str = "") -> str:
    """引用型凭据对应的**合法**环境变量名。

    ``env`` 模式直接用端点声明名；``keychain`` / ``file`` 没有原生等价物，先用它们
    的身份名（服务名 / 路径）—— 服务名通常合法（``hermes-unified-mcp`` 含连字符，
    不合法会走到下面的兜底）；路径几乎必然不合法，此时用调用方给的确定性名字
    （端点 key 派生，见 ``fix_mcp_tool``），而不是把 ``/tmp/tok`` 硬塞进变量名 ——
    那样写出来的配置在客户端里根本不是「一个变量」，只是碰巧像。
    """
    if not auth:
        return ""
    mode = str(auth.get("mode") or "token")
    if mode == "env":
        name = str(auth.get("env_var") or "")
        return name if _ENV_NAME_RE.match(name) else fallback
    # 端点级派生名优先：它保证同一端点在所有客户端里同名（见 mcp_fixer 的
    # _derived_env_name），不会出现「VS Code 用服务名、Codex 用另一个名字」。
    candidate = str(auth.get("template_var") or "")
    if candidate and _ENV_NAME_RE.match(candidate):
        return candidate
    # 未派生时退回服务名（仍须合法）；路径永不作为变量名。
    candidate = str(auth.get("keychain_service") or "")
    if candidate and _ENV_NAME_RE.match(candidate):
        return candidate
    return fallback


def _toml_env_var(auth: Optional[Dict[str, Any]]) -> str:
    """The env var name written into ``bearer_token_env_var`` for a reference mode."""
    return env_var_for(auth or {})


def _toml_subtable_is_empty(block: str, header_name: str) -> bool:
    """True when the ``[header_name]`` subtable holds no ``key = value`` lines."""
    span = _toml_subtable_range(block, header_name)
    if not span:
        return False
    start, end = span
    body = block[start:end].splitlines()[1:]
    return not any(re.match(r"^[ \t]*[A-Za-z0-9_.-]+[ \t]*=", line) for line in body)


def _drop_toml_subtable(block: str, header_name: str) -> str:
    """Remove a ``[header_name]`` subtable block (used once its last key is gone)."""
    span = _toml_subtable_range(block, header_name)
    if not span:
        return block
    start, end = span
    return block[:start] + block[end:]


def _toml_target_is_stdio(text: str, section_name: str) -> bool:
    """Return True when ``[section_name]`` exists and is a **stdio** server.

    Used by the fixer's post-write validation: a stdio entry carries no ``url``
    (its endpoint lives inside ``command``/``args``), so the URL-based validator
    can never confirm it —— 删除残留 url 后校验会误判为失败并回滚。
    """
    tree = _toml_section_tree_ranges(text, section_name)
    if not tree:
        return False
    start, end = tree[0][0], tree[-1][1]
    return _toml_section_is_stdio(text[start:end])


class McpEntryConflict(ValueError):
    """目标 key 已被一条 **stdio** 条目占用，无法按 url 型写入。

    stdio（``command``/``args``）与 url 是**互斥**的连接方式：

    * 写入 url 会让 Codex 拒绝整份配置（``url is not supported for stdio``）；
    * 直接覆盖又会**静默删掉**用户的本地 stdio 桥（2026-10-11 实测：JSON 型
      客户端上 ``command``/``args`` 直接消失，还不报错）。

    因此这里不猜、也不动用户配置，而是显式报冲突，交由调用方给出可执行的处置
    指引（移除该条目，或让统一端点改用其它 key）。
    """


def _toml_section_is_stdio(block: str) -> bool:
    """Return True when a TOML MCP section declares a **stdio** server.

    Stdio servers are identified by ``command`` / ``args`` (they are launched as a
    subprocess); HTTP servers use ``url``. Codex rejects mixing the two:

        invalid configuration: url is not supported for stdio in `mcp_servers.<name>`

    所以写 url 之前必须先判别类型 —— 见 :func:`_render_toml` 的 2026-10-11 事故注记。
    只认顶层 `key =` 行，避免把 ``args = ["--url", "..."]`` 里的内容误判成声明。
    """
    body = block
    header = re.compile(r"(?m)^[ \t]*\[[^\]]+\]")
    match = header.search(body)
    if match:
        newline = body.find("\n", match.end())
        body = body[newline + 1:] if newline >= 0 else ""
    # 只取本表自身的行（遇到下一个表头即停）。
    following = header.search(body)
    if following:
        body = body[:following.start()]
    for field in ("command", "args"):
        if re.search(r"(?m)^[ \t]*" + field + r"[ \t]*=", body):
            return True
    return False


def _toml_header_end(block: str) -> int:
    """Return the offset just past the ``[section]`` header line, or ``len(block)``.

    The section block given by :func:`_toml_section_ranges` may begin with a
    leading separator newline, so a naive ``block.find("\\n")`` would anchor on
    the wrong line. Anchor on the first ``[...]`` header instead.
    """
    header = re.compile(r"(?m)^[ \t]*\[[^\]]+\]")
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


def _toml_subtable_range(block: str, header_name: str) -> Optional[Tuple[int, int]]:
    """Return the ``[header_name]`` table block range, or ``None`` when absent.

    The range starts at the ``[header_name]`` header line and ends just before the
    next table header (or the end of ``block``), i.e. exactly the region that
    :func:`_set_toml_field` / :func:`_remove_toml_field` may edit in place without
    bleeding into neighbouring tables.
    """
    header = re.compile(r"(?m)^[ \t]*\[" + re.escape(header_name) + r"\][ \t]*(?:#.*)?$")
    any_header = re.compile(r"(?m)^[ \t]*\[[^\]]+\][ \t]*(?:#.*)?$")
    match = header.search(block)
    if not match:
        return None
    following = any_header.search(block, match.end())
    return (match.start(), following.start() if following else len(block))


def _set_toml_subtable_field(
    block: str, header_name: str, field: str, value: Optional[str]
) -> str:
    """Set ``field`` inside the dotted subtable ``[header_name]``.

    ``value=None`` deletes the field instead. Returns ``block`` unchanged when the
    subtable is absent.
    """
    span = _toml_subtable_range(block, header_name)
    if not span:
        return block
    start, end = span
    subtable = block[start:end]
    subtable = (
        _set_toml_field(subtable, field, value)
        if value is not None
        else _remove_toml_field(subtable, field)
    )
    return block[:start] + subtable + block[end:]


def _apply_toml_headers(section: str, section_name: str, token: str) -> str:
    """Maintain the auth header in ``section`` using exactly one declaration form.

    TOML forbids declaring the same table twice, so an inline
    ``http_headers = { ... }`` line and a ``[<section>.http_headers]`` child table
    cannot coexist. Writing the inline form into a file that already used the child
    table produced ``Cannot declare ('mcp_servers', '<name>', 'http_headers') twice``,
    which aborted the whole fix (Windows agents commonly ship the child-table form).
    The form already present in the file is preserved; only the other one is cleared.
    """
    if _toml_subtable_range(section, f"{section_name}.http_headers"):
        section = _remove_toml_http_headers(section)
        return _set_toml_subtable_field(
            section,
            f"{section_name}.http_headers",
            "Authorization",
            ("Bearer " + token) if token else None,
        )
    if token:
        return _set_toml_http_headers(section, token)
    return _remove_toml_http_headers(section)


def _reasonix_plugin_ranges(text: str) -> List[Tuple[int, int]]:
    plugin_header = re.compile(r"(?m)^[ \t]*\[\[plugins\]\][ \t]*(?:#.*)?$")
    any_header = re.compile(r"(?m)^[ \t]*\[{1,2}[^\]]+\]{1,2}[ \t]*(?:#.*)?$")
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


def _cordis_entry_block(
    url: str, name: str = "hermes", token: str = "", auth: Optional[Dict[str, Any]] = None
) -> str:
    """DSH cordis patch 条目。``auth`` 为引用型时写占位符而非明文。

    实测约束（2026-11-04）：``!!js`` 表达式的值里只要含反引号/花括号，PyYAML
    的 plain scalar 就会解析失败（``found character '`' that cannot start any
    token``），而本项目的校验链正是用 PyYAML 读回这份文件 —— 写下去就是一份
    「自己校验不过」的配置。因此这里与 JSON/YAML 采用**同一种形态**
    （``_header_placeholder``），保证六个格式对外表述一致：

    * ``env`` → ``Bearer ${env:VAR}``
    * ``keychain`` / ``file`` → ``Bearer ${env.<服务名>}``

    代价是 DSH 客户端暂时同样不求值（与其它客户端同一处境，见
    ``_header_placeholder`` 的取舍说明）；把 ``!!js`` 真正写通是下一步的事，
    前提是先让 config_codec 的解析器接受它。
    """
    block = (
        f"- id: mcp-{name}\n"
        "  name: '@deepseek-ai/dsh-mcp-client'\n"
        "  config:\n"
        f"    serverName: {name}\n"
        "    transport: streamable-http\n"
        f"    url: {url}\n"
    )
    if auth is not None and str(auth.get("mode") or "token") != "token":
        block += (
            "    headers:\n"
            f'      Authorization: "{_header_placeholder(auth, "cordis_yaml")}"\n'
        )
        return block
    if token:
        block += (
            "    headers:\n"
            f'      Authorization: "Bearer {token}"\n'
        )
    return block


def _render_cordis_yaml(
    text: str, name: str, url: str, token: str = "", auth: Optional[Dict[str, Any]] = None
) -> str:
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
        rendered = "".join(lines[:start]) + _cordis_entry_block(url, name, token, auth) + "".join(lines[block_end:])
    else:
        separator = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        rendered = text + separator + _cordis_entry_block(url, name, token, auth)
    _load_cordis_yaml(rendered)  # validate the rewritten document
    return rendered


def _render(
    tool: Dict[str, Any],
    text: str,
    name: str,
    url: str,
    token: str = "",
    auth: Optional[Dict[str, Any]] = None,
) -> str:
    """按客户端格式渲染统一端点条目。

    ``auth`` 由 :func:`resolve_auth_fields` 产出（``None`` = 只有 ``token`` 的
    历史调用面，行为逐字节不变）。引用型 ``auth`` 的分支写在六个格式各自的
    渲染器里，因为它们「能不能求值」的能力不同：

    ============  ==================================================
    格式           引用型 ``auth`` 的写法
    ============  ==================================================
    json / jsonc  ``Authorization: "Bearer ${env:VAR}"``
    yaml          同上
    toml          ``bearer_token_env_var = "VAR"``（Codex 官方字段）
    cordis_yaml   同上（``!!js`` 写法会被 PyYAML 拒绝，见 _cordis_entry_block）
    reasonix*     ``Bearer <redacted>`` 占位（该格式无求值能力）
    ============  ==================================================
    """
    config_format = tool.get("format", "json")
    key_path = tool.get("mcp_key_path", ["mcpServers"])
    root_env_style = str(tool.get("mcp_root_env_style") or "")
    if root_env_style not in ROOT_ENV_STYLES:
        root_env_style = ""
    auth_value = str((auth or {}).get("evaluated_token") or "")
    if config_format in ("json", "jsonc"):
        return _render_json(
            text, key_path, name, url, token,
            entry_type=str(tool.get("mcp_entry_type") or ""),
            auth=auth,
            root_env_style=root_env_style,
            auth_token_value=auth_value,
        )
    if config_format == "toml":
        return _render_toml(text, name, url, token, auth=auth)
    if config_format == "reasonix_toml":
        return _render_reasonix_toml(text, name, url, token)
    if config_format == "reasonix":
        return _render_reasonix(text, key_path, name, url, token)
    if config_format == "cordis_yaml":
        return _render_cordis_yaml(text, name, url, token, auth=auth)
    if config_format == "yaml":
        return _render_yaml(
            text, key_path, name, url, token, auth=auth,
            root_env_style=root_env_style, auth_token_value=auth_value,
        )
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
