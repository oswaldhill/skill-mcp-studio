"""Shared IDE/Agent registry helpers for Skills and MCP checks."""

import os
import plistlib
import re
import shutil
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple

from names import normalized_name  # noqa: F401  (re-export; leaf module, A-5)
from config_store import load_discovered


def expand_path(path: str, environ: Dict[str, str] = None) -> str:
    """Expand a registry path portably across platforms.

    Handles, in order:

    - Windows ``%VAR%`` references (``%APPDATA%``, ``%USERPROFILE%``,
      ``%LOCALAPPDATA%``) via ``os.path.expandvars``, whose ``ntpath``
      implementation understands ``%name%`` on Windows and leaves it intact
      elsewhere — so we fall back to a literal ``%…%`` expander for non-Windows
      hosts that still receive Windows-style paths (e.g. tests);
    - POSIX ``~`` (and ``~user``) via ``os.path.expanduser``.

    A path that references an unset variable keeps the literal ``%NAME%`` token
    (matches ``os.path.expandvars`` semantics upstream), so detection simply
    yields "not found" rather than crashing.
    """
    if not path:
        return path
    environ = dict(os.environ if environ is None else environ)
    expanded = path

    # os.path.expandvars: on nt it expands %NAME%; on posix it only expands
    # ${NAME}/$NAME, leaving %NAME% untouched. Complement with a literal %NAME%
    # pass so Windows-style registry paths also expand on non-Windows hosts.
    expanded = os.path.expandvars(expanded)
    if "%" in expanded:
        def _repl(match: re.Match) -> str:
            name = match.group(1)
            return environ.get(name, match.group(0))
        expanded = re.sub(r"%([^%]+)%", _repl, expanded)

    return os.path.expanduser(expanded)


def _abbreviate_home(path: str, home: str) -> str:
    """把 ``home`` 前缀缩写回 ``~``，得到跨设备通用的展示地址。

    ``home`` 是 ``expanduser("~")`` 的结果；仅当 ``path`` 严格以
    ``home + os.sep`` 开头时才缩写（``home`` 为空或仍是字面 ``~``——注入的
    ``expanduser`` 未展开时——则原样返回），避免把 ``/Users/x`` 误缩成
    ``/Users/xyz``。非 home 前缀的绝对路径（如 ``/Applications``、
    ``/opt/homebrew/bin``）保持不变，因为它们本就是设备无关的真实诊断信息。
    """
    if home and home != "~" and path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


#: GUI 壳（Finder / Dock / Explorer 启动的应用）继承的是最小 PATH——macOS 上是
#: launchd 默认的 ``/usr/bin:/bin:/usr/sbin:/sbin``——而 Homebrew / npm / pipx /
#: cargo 装的 CLI 都落在用户级 bin 目录里。裸名 ``which`` 因此在 GUI 里必然查不到，
#: 在用客户端会被误判成 ``config_only``（「仅配置」，并给出会删配置的清理入口）。
#: 这里补一份常见安装位置作为兜底搜索路径；PATH 仍然优先，尊重用户的 shim 与版本
#: 管理器（nvm / volta / asdf 等改 PATH 的写法照旧生效）。
_EXTRA_BIN_DIRS_POSIX: Tuple[str, ...] = (
    "/opt/homebrew/bin",   # macOS Apple Silicon Homebrew
    "/opt/homebrew/sbin",
    "/usr/local/bin",      # Intel Homebrew / 手工安装
    "/usr/local/sbin",
    "/opt/local/bin",      # MacPorts
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
    "~/.local/bin",        # pipx / pip --user
    "~/.npm-global/bin",
    "~/Library/pnpm",
    "~/.bun/bin",
    "~/.volta/bin",
    "~/.deno/bin",
    "~/.cargo/bin",
)

_EXTRA_BIN_DIRS_WINDOWS: Tuple[str, ...] = (
    "%APPDATA%\\npm",
    "%LOCALAPPDATA%\\Programs\\Python\\Scripts",
    "%USERPROFILE%\\.local\\bin",
    "%USERPROFILE%\\.cargo\\bin",
    "%LOCALAPPDATA%\\Microsoft\\WindowsApps",
)


def _extra_bin_dirs() -> Tuple[str, ...]:
    """当前平台的兜底 bin 目录（``%VAR%`` 在 :func:`expand_path` 里展开）。"""
    return _EXTRA_BIN_DIRS_WINDOWS if os.name == "nt" else _EXTRA_BIN_DIRS_POSIX


def _command_filenames(command: str) -> List[str]:
    """Windows 下按 ``PATHEXT`` 补后缀：文件查找不会自动补扩展名。"""
    if os.name != "nt" or os.path.splitext(command)[1]:
        return [command]
    exts = (os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD").split(os.pathsep)
    return [command + ext.lower() for ext in exts if ext]


def which_with_fallback(command: str) -> Optional[str]:
    """``shutil.which`` 优先，未命中再扫常见安装目录。

    这是 :func:`detect_installation` 的默认 CLI 探测实现。路径形态的命令
    （含 ``os.sep``/``os.altsep``）直接交给 ``shutil.which`` 并原样返回其结果
    ——它自己会校验可执行位；裸名在 PATH 未命中时，按 :func:`_extra_bin_dirs`
    的顺序返回第一个真实存在的可执行文件。这样从 Finder 启动的 GUI 壳（PATH
    受限）与终端（PATH 完整）会得到同一份判定，不再出现「终端说已安装、控制台
    说仅配置」的分裂。
    """
    found = shutil.which(command)
    if found or os.sep in command or (os.altsep and os.altsep in command):
        return found
    names = _command_filenames(command)
    for directory in _extra_bin_dirs():
        base = expand_path(directory)
        for name in names:
            candidate = os.path.join(base, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


#: 转发型启动器（launcher shim）在真身缺失时仍留在磁盘上，仅凭「同名文件存在 +
#: 可执行位」判定 CLI 会把它误报成「已安装」，并进一步让修复链路把 MCP 端点写进
#: 一个已经不存在的客户端。这里改用**只读**静态判定：读脚本头部，不 fork 进程、
#: 不产生任何副作用。
_SCRIPT_HEAD_BYTES = 65536

#: 启动器脚本引用产品 bundle 的写法（VS Code 的 code shim 会引用
#: ``/Applications/Visual Studio Code.app/Contents/...``）。
_APP_BUNDLE_RE = re.compile(r'(/[^\s"\'`()]*?\.app)(?=[/\s"\'`)]|$)')


def _script_head(path: str, limit: int = _SCRIPT_HEAD_BYTES) -> Optional[str]:
    """读取脚本头部文本；原生二进制或读取失败返回 ``None``。

    头部含 NUL 字节即判为二进制（ELF / Mach-O / PE 都有），那说明命中的是产品
    真身而不是启动器，直接放行；非 UTF-8 文本同样无法静态分析，也放行。
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read(limit)
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _self_searches_path(script: str, command: str) -> bool:
    """脚本是否在 PATH / 系统查找里重新寻找**同名**命令。

    这是「通用转发器」的标志：shim 自身不实现功能，只在别处找一个同名的自己并
    ``exec`` 过去。只认这种写法，避免把普通包装脚本（例如 pip 生成的 console
    script：shebang 指向解释器、正文是 Python 代码）误判成启动器。
    """
    name = re.escape(os.path.basename(command))
    patterns = (
        rf'command\s+-v\s+["\']?{name}["\']?(?=\s|$|[;)])',
        rf'\bwhich\s+(?:-a\s+)?["\']?{name}["\']?(?=\s|$|[;)])',
        rf'\$dir/{name}(?=[\s"\'`;)]|$)',
        rf'\$\{{?dir\}}?/{name}(?=[\s"\'`;)]|$)',
        rf'\bexec\s+["\']?{name}["\']?(?=\s|$)',
    )
    return any(re.search(pattern, script) for pattern in patterns)


def _other_command_paths(command: str, exclude: str) -> List[str]:
    """PATH + 兜底目录里，除 ``exclude`` 之外的**同名**可执行文件。

    模拟启动器自己的查找动作：它排除自身后找不到第二个同名命令，就会走
    「未安装」分支（Cursor 的 shim 会打印 ``No Cursor IDE installation found``
    并以非零码退出）。
    """
    exclude_real = os.path.realpath(exclude)
    found: List[str] = []
    directories = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    directories += [expand_path(d) for d in _extra_bin_dirs()]
    for directory in directories:
        for name in _command_filenames(os.path.basename(command)):
            candidate = os.path.join(directory, name)
            if not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
                continue
            if os.path.realpath(candidate) == exclude_real:
                continue
            if candidate not in found:
                found.append(candidate)
    return found


def is_stub_launcher(
    path: str,
    command: str,
    *,
    path_exists: Callable[[str], bool] = os.path.exists,
) -> bool:
    """判定 ``path`` 是否为「真身已不在」的转发型启动器（空壳 CLI）。

    回归背景：Cursor 卸载后 ``~/.local/bin/cursor`` 这个 shim 仍留在磁盘上且带
    可执行位，旧逻辑据此判定 ``installed`` —— 于是扫描结果误报「已安装」，修复
    链路还把 MCP 端点写进了一个已经不存在的客户端。该 shim 本身不含任何产品
    代码，真正运行只会输出 ``No Cursor IDE installation found`` 后非零退出。

    判定只读且保守，两条规则任一命中才算空壳：

    1. 脚本引用了产品 bundle（``…/X.app``），且这些 bundle 全都不存在 —— 覆盖
       VS Code 那类「引用 .app 的 Electron 启动器」；
    2. 脚本在 PATH 里重新寻找同名命令，且排除自身后找不到第二个 —— 覆盖 Cursor
       那类「通用转发器」。

    判不出来时一律返回 ``False``：宁可漏报残留，也不把真实 CLI 误判成未安装
    （后者会让在用客户端被当成 config_only，并给出会删配置的清理入口）。
    """
    script = _script_head(path)
    if script is None:
        return False

    bundles = set(_APP_BUNDLE_RE.findall(script))
    if bundles and not any(path_exists(bundle) for bundle in bundles):
        return True

    if _self_searches_path(script, command):
        return not _other_command_paths(command, path)

    return False


def detect_installation(
    tool: Dict[str, Any],
    *,
    path_exists: Callable[[str], bool] = os.path.exists,
    command_exists: Callable[[str], Any] = which_with_fallback,
    expanduser: Callable[[str], str] = os.path.expanduser,
    stub_launcher: Callable[[str, str], bool] = is_stub_launcher,
) -> Dict[str, Any]:
    """Return three-state installation evidence without treating a Skills link as proof.

    Three-state semantics (skill-mcp-studio 整改):
    - ``installed``      — a real install exists: an app bundle OR a CLI command.
    - ``config_only``    — only config files exist (no app/cli): likely an
                           uninstalled client whose config survived; surfaces in
                           the UI so the user can confirm it's a missing install.
    - ``none``           — no app, no cli, no config: effectively not installed,
                           hidden from the UI.

    ``app``/``cli``/``config`` evidence lists use a portable ``~`` display form:
    every home-prefixed path (app bundles and config files via expanduser, CLI via
    :func:`which_with_fallback`) is abbreviated back to ``~/...``, matching the
    registry/config source which declares ``~`` — the address reads the same on
    every device.

    CLI 探测默认走 :func:`which_with_fallback`：PATH 优先、再兜底常见安装目录，
    因此 GUI 壳（PATH 受限）与终端得到同一份判定。调用方注入 ``command_exists``
    时（测试）完全接管该逻辑，不做任何额外文件系统探测。

    CLI 命中项再由 :func:`is_stub_launcher` 过一道只读的「空壳启动器」判定：卸载
    残留的转发型 shim 不作为安装证据，单独降级进 ``cli_stubs``（evidence 记
    ``cli_stub``），``install_state`` 相应回落到 ``config_only`` / ``none``。
    """
    install = tool.get("install", {}) or {}
    home = expanduser("~")

    # 去重（保持首次出现顺序）：commands 里同时声明别名与绝对路径（如 Codex 的
    # "codex" 和 "/Applications/.../codex"）会 resolve 到同一二进制，导致 cli_paths
    # 出现两份相同值；app/config 列表同理防止配置里的重复项。
    def _dedupe(items: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for it in items:
            if it not in seen:
                seen.add(it)
                out.append(it)
        return out

    def _expand(path: str) -> str:
        """Resolve a registry path, honoring the injected ``expanduser`` for ``~``
        while still expanding Windows ``%VAR%`` tokens via :func:`expand_path`.

        - paths *without* ``%`` keep the legacy contract: they go through the
          injected ``expanduser`` (identity in tests, ``os.path.expanduser`` in
          production), so existing ``expanduser=...`` tests stay valid;
        - paths *with* ``%VAR%`` (Windows registry entries) route through
          ``expand_path`` for a full ``%VAR%`` + ``~`` expansion.
        """
        if "%" in path:
            return expand_path(path)
        return expanduser(path)

    app_paths = _dedupe([
        _abbreviate_home(_expand(path), home) for path in install.get("app_bundles", [])
        if path_exists(_expand(path))
    ])
    # command_exists 默认是 which_with_fallback：返回解析后的命令路径（或 None）。
    # 命中项还要过一道 stub_launcher：卸载后残留的转发型启动器（Cursor 的
    # ~/.local/bin/cursor 那类空壳）会把「同名文件存在」冒充成「CLI 已安装」，
    # 既误导界面，又让修复链路往幽灵客户端写配置。
    cli_paths: List[str] = []
    cli_stubs: List[str] = []
    for command in install.get("commands", []):
        resolved = command_exists(command)
        if not resolved:
            continue
        shown = _abbreviate_home(resolved, home)
        if shown in cli_paths or shown in cli_stubs:
            continue
        if stub_launcher(resolved, command):
            cli_stubs.append(shown)
            continue
        cli_paths.append(shown)
    config_paths = _dedupe([
        _abbreviate_home(_expand(path), home) for path in install.get("config_paths", [])
        if path_exists(_expand(path))
    ])

    has_app_or_cli = bool(app_paths or cli_paths)
    has_config_only = bool(config_paths) and not has_app_or_cli

    evidence: List[str] = []
    if app_paths:
        evidence.append("app")
    if cli_paths:
        evidence.append("cli")
    if cli_stubs:
        evidence.append("cli_stub")
    if config_paths:
        evidence.append("config")

    install_state = "installed" if has_app_or_cli else ("config_only" if has_config_only else "none")

    return {
        "installed": has_app_or_cli,
        "evidence": evidence,
        "install_state": install_state,
        "app_paths": app_paths,
        "cli_paths": cli_paths,
        "cli_stubs": cli_stubs,
        "config_paths": config_paths,
    }


def _field_union(target: Dict[str, Any], incoming: Dict[str, Any]) -> None:
    """A-3: 客户端多源字段级 union（mcp_tools / tools / discovered 三源）。

    第一源（mcp_tools）优先，但缺失/为空的字段由后续源补齐；列表字段去重合并、
    字典字段（如 ``install``）递归 union。这样同一客户端在 ``mcp_tools`` 段只有
    MCP 字段、在 ``tools`` 段只有 ``skills_paths`` 时，合并产物同时携带两者，
    下游不再需要反查 scan rows 补洞。
    """

    def _empty(value: Any) -> bool:
        return value is None or value == "" or value == [] or value == {}

    for key, value in incoming.items():
        if _empty(value):
            continue
        current = target.get(key)
        if key not in target or _empty(current):
            # 深拷贝容器，避免各源之间共享可变引用。
            if isinstance(value, dict):
                target[key] = dict(value)
            elif isinstance(value, list):
                target[key] = list(value)
            else:
                target[key] = value
        elif isinstance(value, dict) and isinstance(current, dict):
            _field_union(current, value)
        elif isinstance(value, list) and isinstance(current, list):
            for item in value:
                if item not in current:
                    current.append(item)


def effective_tools(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """mcp_tools ∪ tools ∪ discovered(持久化) 按归一名去重合并。

    此前 agents/mcp_clients/skills 矩阵只读 config.yaml 内置注册表，写进
    ``data/discovered_tools.yaml`` 的客户端（如手动添加的 VS Code）从不出现
    在管理/修复/清理链路里。此函数统一三源合并，供 snapshot、fixer、checker
    复用，保证「修复 MCP / 清理旧通道 / 刷新判定」覆盖发现型客户端。

    A-3: 合并改为**字段级 union**（非首源整条覆盖）——同一客户端在 mcp_tools 段
    （只有 config_path/format/mcp_key_path）与 tools 段（只有 skills_paths/type）
    的字段被逐字段合并，去重后不再丢失 skills_paths 等字段。

    ``load_discovered`` 保持惰性 import：config_store 在 ``update_discovered_client``/
    ``remove_managed_client`` 链路上仍需要 tool_registry 的 ``detect_installation``/
    ``effective_tools``（函数级互依赖），顶层互 import 会成环；此处的调用期 import
    同时保证测试对 ``config_store.load_discovered`` 的 mock 生效。
    """
    from config_store import load_discovered  # noqa: F811  （刻意惰性导入，见上方 docstring）

    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for src in (config.get("mcp_tools", []), config.get("tools", []), load_discovered()):
        for tool in src or []:
            if not isinstance(tool, dict) or not tool.get("name"):
                continue
            key = normalized_name(tool["name"])
            if key not in merged:
                merged[key] = {}
                order.append(key)
            _field_union(merged[key], tool)

    tools = [merged[key] for key in order]
    # 本机停用过滤：config["disabled_tools"]（来自 profile_sources overlay）里的
    # 客户端即使仍存在于 trunk 注册表或被 auto_discover 重新扫回，也一律从有效
    # 视图剔除——「本机没装/停用」只影响本机管理对象，不改 trunk 共享注册表。
    disabled = {normalized_name(n) for n in (config.get("disabled_tools") or []) if isinstance(n, str)}
    if disabled:
        tools = [t for t in tools if normalized_name(t.get("name", "")) not in disabled]
    return tools


def find_tool(registry: List[Dict[str, Any]], name: str) -> Dict[str, Any]:
    wanted = normalized_name(name)
    for tool in registry:
        candidates = [tool.get("name", "")] + list(tool.get("aliases", []))
        if wanted in {normalized_name(candidate) for candidate in candidates}:
            return tool
    return {}


def read_app_versions(
    app_paths: List[str],
    *,
    expanduser: Callable[[str], str] = os.path.expanduser,
) -> List[str]:
    """读取每个 ``.app`` bundle 的显示版本（``CFBundleShortVersionString``）。

    与 ``detect_installation`` 返回的 ``app_paths`` 一一对应（长度一致，index
    对齐）；读取失败或非 app bundle 时对应项为空字符串，前端据此隐藏版本徽章。
    纯本地 plist 读取，无子进程。
    """
    versions: List[str] = []
    for path in app_paths:
        plist = os.path.join(expanduser(path), "Contents", "Info.plist")
        version = ""
        try:
            with open(plist, "rb") as fh:
                data = plistlib.load(fh)
            version = str(data.get("CFBundleShortVersionString") or "").strip()
        except Exception:
            version = ""
        versions.append(version)
    return versions


def read_cli_versions(
    cli_paths: List[str],
    *,
    expanduser: Callable[[str], str] = os.path.expanduser,
    timeout: float = 2.0,
) -> List[str]:
    """探测每个 CLI 命令的版本（依次尝试 ``--version`` / ``-V`` / ``version``）。

    与 ``detect_installation`` 返回的 ``cli_paths`` 一一对应（长度一致，index
    对齐）；失败给空字符串。每个子进程限时 ``timeout`` 秒、失败静默降级，
    不会让版本探测拖慢主快照链路。命中 CLI 数量小（本机通常 1~3 个），串行
    探测即可；若未来规模扩大再并发。
    """
    versions: List[str] = []
    for path in cli_paths:
        real = expanduser(path)
        version = ""
        for flag in ("--version", "-V", "version"):
            try:
                proc = subprocess.run(
                    [real, flag], capture_output=True, text=True, timeout=timeout
                )
                line = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
                if line and line[0].strip():
                    version = line[0].strip()
                    break
            except Exception:
                continue
        versions.append(version)
    return versions
