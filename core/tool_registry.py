"""Shared IDE/Agent registry helpers for Skills and MCP checks."""

import os
import plistlib
import re
import shutil
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple


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


def detect_installation(
    tool: Dict[str, Any],
    *,
    path_exists: Callable[[str], bool] = os.path.exists,
    command_exists: Callable[[str], Any] = which_with_fallback,
    expanduser: Callable[[str], str] = os.path.expanduser,
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
    # command_exists 默认是 which_with_fallback：返回解析后的命令路径（或 None）；
    # 只保留命中项。
    cli_paths = _dedupe([
        _abbreviate_home(resolved, home)
        for resolved in (command_exists(cmd) for cmd in install.get("commands", []))
        if resolved
    ])
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
    if config_paths:
        evidence.append("config")

    install_state = "installed" if has_app_or_cli else ("config_only" if has_config_only else "none")

    return {
        "installed": has_app_or_cli,
        "evidence": evidence,
        "install_state": install_state,
        "app_paths": app_paths,
        "cli_paths": cli_paths,
        "config_paths": config_paths,
    }


def normalized_name(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def effective_tools(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """mcp_tools ∪ tools ∪ discovered(持久化) 按归一名去重合并。

    此前 agents/mcp_clients/skills 矩阵只读 config.yaml 内置注册表，写进
    ``data/discovered_tools.yaml`` 的客户端（如手动添加的 VS Code）从不出现
    在管理/修复/清理链路里。此函数统一三源合并，供 snapshot、fixer、checker
    复用，保证「修复 MCP / 清理旧通道 / 刷新判定」覆盖发现型客户端。

    惰性 import ``load_discovered`` 以避免与 config_store（→ mcp_fixer）的
    模块加载期循环依赖。
    """
    from config_store import load_discovered

    tools: List[Dict[str, Any]] = []
    seen: set = set()
    for src in (config.get("mcp_tools", []), config.get("tools", []), load_discovered()):
        for tool in src or []:
            if not isinstance(tool, dict) or not tool.get("name"):
                continue
            key = normalized_name(tool["name"])
            if key in seen:
                continue
            seen.add(key)
            tools.append(tool)
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
