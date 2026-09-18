"""内置主流 IDE / Agent 默认清单（skill-mcp-studio 整改）。

每个条目自带安装检测信息（app_bundles / commands / config_paths）、Skills 目录、
以及 MCP 配置文件定位（config_path / format / mcp_key_path），使「默认添加」后
能立即参与三态安装判定与 MCP 检查，与手工配置的 registry 条目完全一致。

install.commands 的探测用 shutil.which（PATH 上的可执行文件），app_bundles /
config_paths 用 os.path.exists（expanduser + %VAR% 展开后）。用户机器上未命中的
条目会按三态语义落为 config_only（仅配置，显示待确认）或 none（隐藏），不会误报。

跨平台（决策 A：``paths_by_os`` + ``sys.platform`` 分派）：每个条目以 macOS
路径为“默认基准”，可借 ``by_os`` 声明 Windows / Linux 覆盖。模块 import 时
按当前 ``sys.platform``（darwin / win32 / linux）把对应平台的路径合并进
``install`` 与 ``skills_paths``/``config_path``，因此 ``detect_installation``
无需感知平台。Windows 路径用 ``%APPDATA%``/``%USERPROFILE%``/``%LOCALAPPDATA%``
形式书写，运行时由 ``tool_registry.expand_path`` 展开。
"""

import sys
from typing import Any, Dict, List

# 平台键：sys.platform -> 内部键（win32 覆盖 cygwin 等别名）。
_PLATFORM_KEY = {"darwin": "darwin", "win32": "windows", "linux": "linux"}


def _current_os() -> str:
    return _PLATFORM_KEY.get(sys.platform, sys.platform)


def _pick(values_by_os: Dict[str, Any], current_os: str, default: Any) -> Any:
    """Return the current-OS override if declared, else the macOS default."""
    override = (values_by_os or {}).get(current_os)
    if override is not None:
        return override
    return default


def _entry(
    name: str,
    *,
    type_: str,
    app_bundles: List[str] = None,
    commands: List[str] = None,
    config_paths: List[str] = None,
    skills_path: str = "",
    mcp_config_path: str = "",
    mcp_format: str = "json",
    mcp_key_path: str = "mcpServers",
    aliases: List[str] = None,
    by_os: Dict[str, Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build one registry entry, resolving per-OS path overrides.

    ``by_os`` maps platform key (``windows``/``linux``/``darwin``) to a dict
    overriding any of the positional fields for that platform:
    ``app_bundles``, ``commands``, ``config_paths``, ``skills_path``,
    ``mcp_config_path``.  macOS callers use the positional defaults directly
    (``darwin`` entries seldom need ``by_os``).
    """
    os_key = _current_os()
    overrides = (by_os or {}).get(os_key, {})

    def _field(macos_default, key):
        if overrides and key in overrides:
            return overrides[key]
        return macos_default

    resolved_app_bundles = _field(app_bundles or [], "app_bundles") or []
    resolved_commands = _field(commands or [], "commands") or []
    resolved_config_paths = _field(config_paths or [], "config_paths") or []
    resolved_skills_path = _field(skills_path, "skills_path") or ""
    resolved_mcp_config = _field(mcp_config_path, "mcp_config_path") or ""

    entry: Dict[str, Any] = {
        "name": name,
        "type": type_,
        "install": {
            "app_bundles": list(resolved_app_bundles),
            "commands": list(resolved_commands),
            "config_paths": list(resolved_config_paths),
        },
    }
    if resolved_skills_path:
        entry["skills_paths"] = [resolved_skills_path]
    if resolved_mcp_config:
        entry["config_path"] = resolved_mcp_config
        entry["format"] = mcp_format
        entry["mcp_key_path"] = mcp_key_path.split(".") if mcp_key_path else ["mcpServers"]
    if aliases:
        entry["aliases"] = list(aliases)
    return entry


MAINSTREAM_TOOLS: List[Dict[str, Any]] = [
    # ---- AI IDE ----
    _entry(
        "Cursor", type_="AI IDE",
        app_bundles=["/Applications/Cursor.app"],
        commands=["cursor"],
        config_paths=["~/.cursor/mcp.json"],
        skills_path="~/.cursor/skills",
        mcp_config_path="~/.cursor/mcp.json",
        aliases=["cursor"],
        by_os={
            "windows": {
                "app_bundles": ["%LOCALAPPDATA%\\Programs\\Cursor\\Cursor.exe"],
                "commands": ["cursor", "agent"],
                "config_paths": ["%APPDATA%\\Cursor\\User\\settings.json", "%USERPROFILE%\\.cursor\\mcp.json"],
                "skills_path": "%USERPROFILE%\\.cursor\\skills",
                "mcp_config_path": "%USERPROFILE%\\.cursor\\mcp.json",
            },
            "linux": {
                "app_bundles": [],
                "commands": ["cursor", "agent"],
                "config_paths": ["~/.config/Cursor/User/settings.json", "~/.cursor/mcp.json"],
                "skills_path": "~/.cursor/skills",
                "mcp_config_path": "~/.cursor/mcp.json",
            },
        },
    ),
    _entry(
        "VS Code", type_="AI IDE",
        app_bundles=["/Applications/Visual Studio Code.app"],
        commands=["code"],
        config_paths=["~/.vscode/mcp.json", "~/.config/Code/User/mcp.json"],
        skills_path="~/.vscode/skills",
        mcp_config_path="~/.vscode/mcp.json",
        aliases=["vscode", "visual-studio-code"],
        by_os={
            "windows": {
                "app_bundles": ["%LOCALAPPDATA%\\Programs\\Microsoft VS Code\\Code.exe", "C:\\Program Files\\Microsoft VS Code\\Code.exe"],
                "commands": ["code"],
                "config_paths": ["%APPDATA%\\Code\\User\\settings.json", "%APPDATA%\\Code\\User\\mcp.json"],
                "skills_path": "",
                "mcp_config_path": "%APPDATA%\\Code\\User\\mcp.json",
            },
            "linux": {
                "app_bundles": [],
                "commands": ["code"],
                "config_paths": ["~/.config/Code/User/settings.json", "~/.config/Code/User/mcp.json"],
                "skills_path": "",
                "mcp_config_path": "~/.config/Code/User/mcp.json",
            },
        },
    ),
    _entry(
        "Windsurf", type_="AI IDE",
        app_bundles=["/Applications/Windsurf.app"],
        commands=["windsurf"],
        config_paths=["~/.codeium/windsurf/mcp_config.json"],
        skills_path="~/.windsurf/skills",
        mcp_config_path="~/.codeium/windsurf/mcp_config.json",
        aliases=["windsurf"],
        by_os={
            "windows": {
                "app_bundles": ["%LOCALAPPDATA%\\Programs\\Windsurf\\Windsurf.exe"],
                "commands": ["windsurf"],
                "config_paths": ["%APPDATA%\\Windsurf\\User\\settings.json", "%USERPROFILE%\\.codeium\\windsurf\\mcp_config.json"],
                "skills_path": "",
                "mcp_config_path": "%USERPROFILE%\\.codeium\\windsurf\\mcp_config.json",
            },
            "linux": {
                "app_bundles": [],
                "commands": ["windsurf"],
                "config_paths": ["~/.config/Windsurf/User/settings.json", "~/.codeium/windsurf/mcp_config.json"],
                "skills_path": "",
                "mcp_config_path": "~/.codeium/windsurf/mcp_config.json",
            },
        },
    ),
    _entry(
        "TRAE", type_="AI IDE",
        app_bundles=["/Applications/Trae.app"],
        commands=["trae"],
        config_paths=["~/Library/Application Support/Trae/User/mcp.json"],
        skills_path="~/.trae/skills",
        mcp_config_path="~/Library/Application Support/Trae/User/mcp.json",
        aliases=["trae", "trae-cn"],
        by_os={
            "windows": {
                "app_bundles": ["%LOCALAPPDATA%\\Programs\\Trae\\Trae.exe"],
                "commands": ["trae"],
                "config_paths": ["%APPDATA%\\Trae\\User\\settings.json", "%APPDATA%\\Trae\\User\\mcp.json"],
                "skills_path": "%APPDATA%\\Trae\\skills",
                "mcp_config_path": "%APPDATA%\\Trae\\User\\mcp.json",
            },
            "linux": {
                "app_bundles": [],
                "commands": ["trae"],
                "config_paths": ["~/.config/Trae/User/settings.json", "~/.config/Trae/User/mcp.json"],
                "skills_path": "~/.trae/skills",
                "mcp_config_path": "~/.config/Trae/User/mcp.json",
            },
        },
    ),
    _entry(
        "Zed", type_="AI IDE",
        app_bundles=["/Applications/Zed.app"],
        commands=["zed"],
        config_paths=["~/.config/zed/settings.json"],
        skills_path="~/.config/zed/skills",
        mcp_config_path="~/.config/zed/settings.json", mcp_format="json", mcp_key_path="context_servers",
        aliases=["zed"],
        by_os={
            "windows": {
                "app_bundles": ["%LOCALAPPDATA%\\Programs\\Zed\\zed.exe"],
                "commands": ["zed"],
                "config_paths": ["%APPDATA%\\Zed\\settings.json"],
                "skills_path": "%USERPROFILE%\\.agents\\skills",
                "mcp_config_path": "%APPDATA%\\Zed\\settings.json",
            },
            "linux": {
                "app_bundles": ["~/.local/zed.app/bin/zed"],
                "commands": ["zed"],
                "config_paths": ["~/.config/zed/settings.json"],
                "skills_path": "~/.agents/skills",
                "mcp_config_path": "~/.config/zed/settings.json",
            },
        },
    ),
    _entry(
        "JetBrains IntelliJ IDEA", type_="AI IDE",
        app_bundles=["/Applications/IntelliJ IDEA.app"],
        commands=["idea"],
        config_paths=["~/.config/JetBrains/mcp.json"],
        aliases=["intellij", "idea"],
        by_os={
            "windows": {
                "app_bundles": ["%LOCALAPPDATA%\\JetBrains\\Toolbox\\apps"],
                "commands": [],
                "config_paths": ["%APPDATA%\\JetBrains"],
            },
            "linux": {
                "app_bundles": ["~/.local/share/JetBrains/Toolbox/apps"],
                "commands": ["idea"],
                "config_paths": ["~/.config/JetBrains"],
            },
        },
    ),
    _entry(
        "JetBrains PyCharm", type_="AI IDE",
        app_bundles=["/Applications/PyCharm.app"],
        commands=["pycharm"],
        config_paths=["~/.config/JetBrains/mcp.json"],
        aliases=["pycharm"],
        by_os={
            "windows": {
                "app_bundles": ["%LOCALAPPDATA%\\JetBrains\\Toolbox\\apps"],
                "commands": [],
                "config_paths": ["%APPDATA%\\JetBrains"],
            },
            "linux": {
                "app_bundles": ["~/.local/share/JetBrains/Toolbox/apps"],
                "commands": ["pycharm"],
                "config_paths": ["~/.config/JetBrains"],
            },
        },
    ),
    _entry(
        "JetBrains WebStorm", type_="AI IDE",
        app_bundles=["/Applications/WebStorm.app"],
        commands=["webstorm"],
        config_paths=["~/.config/JetBrains/mcp.json"],
        aliases=["webstorm"],
        by_os={
            "windows": {
                "app_bundles": ["%LOCALAPPDATA%\\JetBrains\\Toolbox\\apps"],
                "commands": [],
                "config_paths": ["%APPDATA%\\JetBrains"],
            },
            "linux": {
                "app_bundles": ["~/.local/share/JetBrains/Toolbox/apps"],
                "commands": ["webstorm"],
                "config_paths": ["~/.config/JetBrains"],
            },
        },
    ),
    # ---- AI Agent / Coding Assistant ----
    _entry(
        "Claude Code", type_="AI Agent",
        app_bundles=["/Applications/Claude.app"],
        commands=["claude"],
        config_paths=["~/.claude.json", "~/.claude/settings.json"],
        skills_path="~/.claude/skills",
        mcp_config_path="~/.claude.json", mcp_key_path="mcpServers",
        aliases=["claude", "claude-code"],
        by_os={
            "windows": {
                "app_bundles": ["%USERPROFILE%\\.local\\bin\\claude.exe"],
                "commands": ["claude"],
                "config_paths": ["%USERPROFILE%\\.claude\\settings.json", "%USERPROFILE%\\.claude.json"],
                "skills_path": "%USERPROFILE%\\.claude\\skills",
                "mcp_config_path": "%USERPROFILE%\\.claude.json",
            },
            "linux": {
                "app_bundles": ["~/.local/bin/claude"],
                "commands": ["claude"],
                "config_paths": ["~/.claude/settings.json", "~/.claude.json"],
                "skills_path": "~/.claude/skills",
                "mcp_config_path": "~/.claude.json",
            },
        },
    ),
    _entry(
        "Codex", type_="AI Agent",
        # 新版 Codex 已并入 OpenAI ChatGPT 桌面应用：无独立 Codex.app，CLI 内嵌于
        # ChatGPT.app/Contents/Resources/codex；同时保留旧独立安装形态的探测。
        app_bundles=["/Applications/Codex.app", "/Applications/ChatGPT.app"],
        commands=["codex", "/Applications/ChatGPT.app/Contents/Resources/codex"],
        config_paths=["~/.codex/config.toml"],
        skills_path="~/.codex/skills",
        mcp_config_path="~/.codex/config.toml", mcp_format="toml", mcp_key_path="mcp_servers",
        aliases=["codex", "openai-codex"],
        by_os={
            "windows": {
                "app_bundles": [],
                "commands": ["codex"],
                "config_paths": ["%USERPROFILE%\\.codex\\config.toml", "%USERPROFILE%\\.codex\\auth.json"],
                "skills_path": "%USERPROFILE%\\.agents\\skills",
                "mcp_config_path": "%USERPROFILE%\\.codex\\config.toml",
            },
            "linux": {
                "app_bundles": [],
                "commands": ["codex"],
                "config_paths": ["~/.codex/config.toml", "~/.codex/auth.json"],
                "skills_path": "~/.agents/skills",
                "mcp_config_path": "~/.codex/config.toml",
            },
        },
    ),
    _entry(
        "Gemini CLI", type_="AI Agent",
        commands=["gemini"],
        config_paths=["~/.gemini/settings.json", "~/.config/gemini/mcp.json"],
        skills_path="~/.gemini/skills",
        mcp_config_path="~/.config/gemini/mcp.json",
        aliases=["gemini", "gemini-cli"],
        by_os={
            "windows": {
                "app_bundles": [],
                "commands": ["gemini"],
                "config_paths": ["%USERPROFILE%\\.gemini\\settings.json", "%USERPROFILE%\\.gemini\\.env"],
                "skills_path": "%USERPROFILE%\\.gemini\\skills",
                "mcp_config_path": "%USERPROFILE%\\.gemini\\settings.json",
            },
            "linux": {
                "app_bundles": [],
                "commands": ["gemini"],
                "config_paths": ["~/.gemini/settings.json", "~/.gemini/.env"],
                "skills_path": "~/.gemini/skills",
                "mcp_config_path": "~/.gemini/settings.json",
            },
        },
    ),
    _entry(
        "Cline", type_="IDE Plugin",
        commands=["cline"],
        config_paths=["~/.cline/mcp_settings.json",
                      "~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json"],
        skills_path="~/.cline/skills",
        mcp_config_path="~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
        mcp_format="json", mcp_key_path="mcpServers",
        aliases=["cline"],
        by_os={
            "windows": {
                "app_bundles": [],
                "commands": [],
                "config_paths": ["%APPDATA%\\Code\\User\\globalStorage\\saoudrizwan.claude-dev\\settings\\cline_mcp_settings.json"],
                "skills_path": "%USERPROFILE%\\.cline\\skills",
                "mcp_config_path": "%APPDATA%\\Code\\User\\globalStorage\\saoudrizwan.claude-dev\\settings\\cline_mcp_settings.json",
            },
            "linux": {
                "app_bundles": [],
                "commands": [],
                "config_paths": ["~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json"],
                "skills_path": "~/.cline/skills",
                "mcp_config_path": "~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
            },
        },
    ),
    _entry(
        "Roo Code", type_="IDE Plugin",
        commands=["roo-code"],
        config_paths=["~/.roo-code/mcp_settings.json",
                      "~/Library/Application Support/Code/User/globalStorage/RooVeterinaryInc.roo-cline/settings/mcp_settings.json"],
        skills_path="~/.roo-code/skills",
        mcp_config_path="~/Library/Application Support/Code/User/globalStorage/RooVeterinaryInc.roo-cline/settings/mcp_settings.json",
        mcp_format="json", mcp_key_path="mcpServers",
        aliases=["roo", "roo-code", "roocode"],
        by_os={
            "windows": {
                "app_bundles": [],
                "commands": [],
                "config_paths": ["%APPDATA%\\Code\\User\\globalStorage\\RooVeterinaryInc.roo-cline\\settings\\mcp_settings.json"],
                "skills_path": "%USERPROFILE%\\.roo\\skills",
                "mcp_config_path": "%APPDATA%\\Code\\User\\globalStorage\\RooVeterinaryInc.roo-cline\\settings\\mcp_settings.json",
            },
            "linux": {
                "app_bundles": [],
                "commands": [],
                "config_paths": ["~/.config/Code/User/globalStorage/RooVeterinaryInc.roo-cline/settings/mcp_settings.json"],
                "skills_path": "~/.roo/skills",
                "mcp_config_path": "~/.config/Code/User/globalStorage/RooVeterinaryInc.roo-cline/settings/mcp_settings.json",
            },
        },
    ),
    _entry(
        "Aider", type_="AI Agent",
        commands=["aider"],
        config_paths=["~/.aider/mcp.json", "~/.config/aider/mcp.json"],
        skills_path="~/.aider/skills",
        aliases=["aider"],
        by_os={
            "windows": {
                "app_bundles": [],
                "commands": ["aider"],
                "config_paths": ["%USERPROFILE%\\.aider.conf.yml", "%USERPROFILE%\\.env"],
                "skills_path": "",
            },
            "linux": {
                "app_bundles": [],
                "commands": ["aider"],
                "config_paths": ["~/.aider.conf.yml", "~/.env"],
                "skills_path": "",
            },
        },
    ),
    _entry(
        "OpenCode", type_="AI Agent",
        commands=["opencode"],
        config_paths=["~/.config/opencode/opencode.jsonc"],
        skills_path="~/.config/opencode/skills",
        mcp_config_path="~/.config/opencode/opencode.jsonc", mcp_format="jsonc", mcp_key_path="mcp",
        aliases=["opencode"],
        by_os={
            "windows": {
                "app_bundles": [],
                "commands": ["opencode"],
                "config_paths": ["%USERPROFILE%\\.config\\opencode\\opencode.json"],
                "skills_path": "%USERPROFILE%\\.config\\opencode\\skills",
                "mcp_config_path": "%USERPROFILE%\\.config\\opencode\\opencode.json",
            },
            "linux": {
                "app_bundles": [],
                "commands": ["opencode"],
                "config_paths": ["~/.config/opencode/opencode.json", "~/.config/opencode/tui.json"],
                "skills_path": "~/.config/opencode/skills",
                "mcp_config_path": "~/.config/opencode/opencode.json",
            },
        },
    ),
    _entry(
        "Goose", type_="AI Agent",
        commands=["goose"],
        config_paths=["~/.config/goose/settings.json", "~/.config/goose/config.yaml"],
        skills_path="~/.config/goose/skills",
        mcp_config_path="~/.config/goose/config.yaml", mcp_format="yaml", mcp_key_path="extensions",
        aliases=["goose"],
        by_os={
            "windows": {
                "app_bundles": [],
                "commands": ["goose"],
                "config_paths": ["%APPDATA%\\Block\\goose\\config\\config.yaml"],
                "skills_path": "%USERPROFILE%\\.agents\\skills",
                "mcp_config_path": "%APPDATA%\\Block\\goose\\config\\config.yaml",
            },
            "linux": {
                "app_bundles": [],
                "commands": ["goose"],
                "config_paths": ["~/.config/goose/config.yaml"],
                "skills_path": "~/.agents/skills",
                "mcp_config_path": "~/.config/goose/config.yaml",
            },
        },
    ),
    _entry(
        "WorkBuddy", type_="AI Agent",
        app_bundles=["/Applications/WorkBuddy.app"],
        commands=["workbuddy"],
        config_paths=["~/.workbuddy/mcp.json"],
        skills_path="~/.workbuddy/skills",
        mcp_config_path="~/.workbuddy/mcp.json",
        aliases=["workbuddy"],
        by_os={
            "windows": {
                "app_bundles": ["%LOCALAPPDATA%\\Programs\\WorkBuddy"],
                "commands": [],
                "config_paths": ["%USERPROFILE%\\.workbuddy\\settings.json", "%USERPROFILE%\\.workbuddy\\models.json"],
                "skills_path": "%USERPROFILE%\\.workbuddy\\skills",
                "mcp_config_path": "%USERPROFILE%\\.workbuddy\\mcp.json",
            },
            "linux": {
                "app_bundles": [],
                "commands": ["workbuddy"],
                "config_paths": ["~/.workbuddy/settings.json", "~/.workbuddy/models.json"],
                "skills_path": "~/.workbuddy/skills",
                "mcp_config_path": "~/.workbuddy/mcp.json",
            },
        },
    ),
    _entry(
        "Cherry Studio", type_="AI Agent",
        app_bundles=["/Applications/Cherry Studio.app", "/Applications/CherryStudio.app"],
        commands=["cherry-studio"],
        config_paths=["~/.config/CherryStudio/mcp.json"],
        aliases=["cherry", "cherry-studio"],
        by_os={
            "windows": {
                "app_bundles": ["%LOCALAPPDATA%\\Programs\\Cherry Studio\\Cherry Studio.exe"],
                "commands": [],
                "config_paths": ["%APPDATA%\\CherryStudio"],
            },
            "linux": {
                "app_bundles": [],
                "commands": [],
                "config_paths": ["~/.config/CherryStudio"],
            },
        },
    ),
    # ---- 当前 AI 本体（原 DSH）----
    _entry(
        "DeepSeek Harness", type_="AI Agent",
        commands=["dsh"],
        config_paths=["~/.dsh/settings.yaml", "~/.dsh/mcp.json"],
        skills_path="~/.dsh/skills",
        mcp_config_path="~/.dsh/mcp.json",
        aliases=["dsh", "ds-harness", "deepseek-harness"],
        by_os={
            "windows": {
                "app_bundles": [],
                "commands": ["dsh"],
                "config_paths": ["%USERPROFILE%\\.dsh\\settings.yaml", "%USERPROFILE%\\.dsh\\mcp.json"],
                "skills_path": "%USERPROFILE%\\.dsh\\skills",
                "mcp_config_path": "%USERPROFILE%\\.dsh\\mcp.json",
            },
            "linux": {
                "app_bundles": [],
                "commands": ["dsh"],
                "config_paths": ["~/.dsh/settings.yaml", "~/.dsh/mcp.json"],
                "skills_path": "~/.dsh/skills",
                "mcp_config_path": "~/.dsh/mcp.json",
            },
        },
    ),
]

# 名称类写法便于 CLI / GUI 摘要展示
MAINSTREAM_NAMES = [t["name"] for t in MAINSTREAM_TOOLS]

def register_mainstream_tools():
    """返回扩展后的主流工具清单（含国内外常用）。"""
    extra = [
        # ==== 国内常用 ====
        _entry("通义灵码", type_="IDE Plugin",
               app_bundles=["/Applications/Tongyi Lingma.app"], commands=["lingma"],
               config_paths=["~/.lingma/mcp.json", "~/.qoder/settings.json"],
               skills_path="~/.lingma/skills",
               mcp_config_path="~/.qoder/settings.json", mcp_format="json", mcp_key_path="mcpServers",
               aliases=["lingma", "tongyi-lingma", "qoder"],
               by_os={
                   "windows": {
                       "app_bundles": ["%LOCALAPPDATA%\\Programs\\Qoder"],
                       "commands": ["qoder", "lingma"],
                       "config_paths": ["%USERPROFILE%\\.qoder\\settings.json"],
                       "skills_path": "%USERPROFILE%\\.qoder\\skills",
                       "mcp_config_path": "%USERPROFILE%\\.qoder\\settings.json",
                   },
                   "linux": {
                       "app_bundles": [],
                       "commands": ["qoder", "lingma"],
                       "config_paths": ["~/.qoder/settings.json"],
                       "skills_path": "~/.qoder/skills",
                       "mcp_config_path": "~/.qoder/settings.json",
                   },
               }),
        _entry("百度 Comate", type_="IDE Plugin",
               app_bundles=["/Applications/Comate.app"], commands=["comate"],
               config_paths=["~/.comate/mcp.json"],
               aliases=["comate", "baidu-comate"],
               by_os={
                   "windows": {"app_bundles": [], "commands": ["comate"], "config_paths": ["%USERPROFILE%\\.comate\\mcp.json"]},
                   "linux": {"app_bundles": [], "commands": ["comate"], "config_paths": ["~/.comate/mcp.json"]},
               }),
        _entry("CodeBuddy", type_="AI Agent",
               app_bundles=["/Applications/CodeBuddy.app"], commands=["codebuddy"],
               config_paths=["~/.codebuddy/mcp.json"], skills_path="~/.codebuddy/skills",
               mcp_config_path="~/.codebuddy/mcp.json",
               aliases=["codebuddy", "tencent-codebuddy"],
               by_os={
                   "windows": {
                       "app_bundles": ["%LOCALAPPDATA%\\Programs\\CodeBuddy"],
                       "commands": ["codebuddy", "buddycn"],
                       "config_paths": ["%USERPROFILE%\\.codebuddy\\settings.json", "%USERPROFILE%\\.codebuddy\\models.json"],
                       "skills_path": "%USERPROFILE%\\.codebuddy\\skills",
                       "mcp_config_path": "%USERPROFILE%\\.codebuddy\\mcp.json",
                   },
                   "linux": {
                       "app_bundles": [],
                       "commands": ["codebuddy", "buddycn"],
                       "config_paths": ["~/.codebuddy/settings.json", "~/.codebuddy/models.json"],
                       "skills_path": "~/.codebuddy/skills",
                       "mcp_config_path": "~/.codebuddy/mcp.json",
                   },
               }),
        _entry("Kimi", type_="AI Agent",
               app_bundles=["/Applications/Kimi.app"], commands=["kimi"],
               config_paths=["~/.kimi/mcp.json"], skills_path="~/.kimi/skills",
               aliases=["kimi", "moonshot"],
               by_os={
                   "windows": {"app_bundles": ["%LOCALAPPDATA%\\Programs\\Kimi"], "commands": ["kimi"],
                               "config_paths": ["%USERPROFILE%\\.kimi\\mcp.json"], "skills_path": "%USERPROFILE%\\.kimi\\skills"},
                   "linux": {"app_bundles": [], "commands": ["kimi"],
                             "config_paths": ["~/.kimi/mcp.json"], "skills_path": "~/.kimi/skills"},
               }),
        _entry("Qwen", type_="AI Agent",
               app_bundles=["/Applications/Qwen.app"], commands=["qwen"],
               config_paths=["~/.qwen/mcp.json"], skills_path="~/.qwen/skills",
               aliases=["qwen", "tongyi-qianwen"],
               by_os={
                   "windows": {"app_bundles": ["%LOCALAPPDATA%\\Programs\\Qwen"], "commands": ["qwen"],
                               "config_paths": ["%USERPROFILE%\\.qwen\\mcp.json"], "skills_path": "%USERPROFILE%\\.qwen\\skills"},
                   "linux": {"app_bundles": [], "commands": ["qwen"],
                             "config_paths": ["~/.qwen/mcp.json"], "skills_path": "~/.qwen/skills"},
               }),
        _entry("豆包", type_="AI Agent",
               app_bundles=["/Applications/Doubao.app"], commands=["doubao"],
               config_paths=["~/.doubao/mcp.json"],
               aliases=["doubao", "bytedance-doubao"],
               by_os={
                   "windows": {"app_bundles": ["%LOCALAPPDATA%\\Doubao"], "commands": [],
                               "config_paths": ["%LOCALAPPDATA%\\Doubao"]},
                   "linux": {"app_bundles": [], "commands": [], "config_paths": []},
               }),
        _entry("Huawei CodeArts", type_="IDE Plugin",
               commands=["codearts"], config_paths=["~/.codearts/mcp.json"],
               aliases=["codearts", "huawei-codearts"],
               by_os={
                   "windows": {"app_bundles": [], "commands": ["codearts"], "config_paths": ["%USERPROFILE%\\.codearts\\mcp.json"]},
                   "linux": {"app_bundles": [], "commands": ["codearts"], "config_paths": ["~/.codearts/mcp.json"]},
               }),
        _entry("DeepSeek", type_="AI Agent",
               app_bundles=["/Applications/DeepSeek.app"], commands=["deepseek"],
               config_paths=["~/.deepseek/mcp.json"], skills_path="~/.deepseek/skills",
               aliases=["deepseek", "deepseek-app"],
               by_os={
                   "windows": {"app_bundles": ["%LOCALAPPDATA%\\Programs\\DeepSeek"], "commands": ["deepseek"],
                               "config_paths": ["%USERPROFILE%\\.deepseek\\mcp.json"], "skills_path": "%USERPROFILE%\\.deepseek\\skills"},
                   "linux": {"app_bundles": [], "commands": ["deepseek"],
                             "config_paths": ["~/.deepseek/mcp.json"], "skills_path": "~/.deepseek/skills"},
               }),
        # ==== 国际常用 ====
        _entry("GitHub Copilot", type_="IDE Plugin",
               app_bundles=["/Applications/GitHub Copilot.app"], commands=["copilot"],
               config_paths=["~/.copilot/mcp.json", "~/.config/github-copilot/mcp.json"],
               skills_path="~/.copilot/skills", mcp_config_path="~/.copilot/mcp.json",
               aliases=["copilot", "github-copilot"],
               by_os={
                   "windows": {"app_bundles": [], "commands": ["copilot"],
                               "config_paths": ["%USERPROFILE%\\.copilot\\mcp.json"], "skills_path": "%USERPROFILE%\\.copilot\\skills"},
                   "linux": {"app_bundles": [], "commands": ["copilot"],
                             "config_paths": ["~/.copilot/mcp.json"], "skills_path": "~/.copilot/skills"},
               }),
        _entry("Amazon Q", type_="IDE Plugin",
               commands=["q"], config_paths=["~/.aws/amazonq/mcp.json"],
               aliases=["amazon-q", "q-developer"],
               by_os={
                   "windows": {"app_bundles": [], "commands": ["q"], "config_paths": ["%USERPROFILE%\\.aws\\amazonq\\mcp.json"]},
                   "linux": {"app_bundles": [], "commands": ["q"], "config_paths": ["~/.aws/amazonq/mcp.json"]},
               }),
        _entry("Tabnine", type_="IDE Plugin",
               commands=["tabnine"], config_paths=["~/.tabnine/mcp.json"],
               aliases=["tabnine"],
               by_os={
                   "windows": {"app_bundles": [], "commands": ["tabnine"], "config_paths": ["%USERPROFILE%\\.tabnine\\mcp.json"]},
                   "linux": {"app_bundles": [], "commands": ["tabnine"], "config_paths": ["~/.tabnine/mcp.json"]},
               }),
        _entry("Cody", type_="IDE Plugin",
               commands=["cody"], config_paths=["~/.sourcegraph/cody/mcp.json"],
               skills_path="~/.sourcegraph/cody/skills",
               aliases=["cody", "sourcegraph-cody"],
               by_os={
                   "windows": {"app_bundles": [], "commands": ["cody"],
                               "config_paths": ["%USERPROFILE%\\.sourcegraph\\cody\\mcp.json"], "skills_path": "%USERPROFILE%\\.sourcegraph\\cody\\skills"},
                   "linux": {"app_bundles": [], "commands": ["cody"],
                             "config_paths": ["~/.sourcegraph/cody/mcp.json"], "skills_path": "~/.sourcegraph/cody/skills"},
               }),
        _entry("Continue", type_="IDE Plugin",
               commands=["continue"], config_paths=["~/.continue/config.json"],
               skills_path="~/.continue/skills",
               aliases=["continue", "continue-dev"],
               by_os={
                   "windows": {"app_bundles": [], "commands": ["continue"],
                               "config_paths": ["%USERPROFILE%\\.continue\\config.json"], "skills_path": "%USERPROFILE%\\.continue\\skills"},
                   "linux": {"app_bundles": [], "commands": ["continue"],
                             "config_paths": ["~/.continue/config.json"], "skills_path": "~/.continue/skills"},
               }),
        _entry("Augment Code", type_="IDE Plugin",
               commands=["augment"], config_paths=["~/.augment/mcp.json"],
               skills_path="~/.augment/skills",
               aliases=["augment", "augment-code"],
               by_os={
                   "windows": {"app_bundles": [], "commands": ["augment"],
                               "config_paths": ["%USERPROFILE%\\.augment\\mcp.json"], "skills_path": "%USERPROFILE%\\.augment\\skills"},
                   "linux": {"app_bundles": [], "commands": ["augment"],
                             "config_paths": ["~/.augment/mcp.json"], "skills_path": "~/.augment/skills"},
               }),
        _entry("Codeium", type_="IDE Plugin",
               app_bundles=["/Applications/Codeium.app"], commands=["codeium"],
               config_paths=["~/.codeium/mcp.json"],
               aliases=["codeium"],
               by_os={
                   "windows": {"app_bundles": ["%LOCALAPPDATA%\\Programs\\Codeium"], "commands": ["codeium"],
                               "config_paths": ["%USERPROFILE%\\.codeium\\mcp.json"]},
                   "linux": {"app_bundles": [], "commands": ["codeium"],
                             "config_paths": ["~/.codeium/mcp.json"]},
               }),
        _entry("Reasonix", type_="AI Agent",
               app_bundles=["/Applications/Reasonix.app"], commands=["reasonix"],
               config_paths=["~/.reasonix/config.toml"], skills_path="~/.reasonix/skills",
               mcp_config_path="~/.reasonix/config.toml", mcp_format="reasonix_toml",
               mcp_key_path="plugins",
               aliases=["reasonix"],
               by_os={
                   "windows": {"app_bundles": [], "commands": ["reasonix"],
                               "config_paths": ["%USERPROFILE%\\.reasonix\\config.toml"], "skills_path": "%USERPROFILE%\\.reasonix\\skills",
                               "mcp_config_path": "%USERPROFILE%\\.reasonix\\config.toml"},
                   "linux": {"app_bundles": [], "commands": ["reasonix"],
                             "config_paths": ["~/.reasonix/config.toml"], "skills_path": "~/.reasonix/skills",
                             "mcp_config_path": "~/.reasonix/config.toml"},
               }),
        _entry("Hermes Agent", type_="AI Agent",
               commands=["hermes"], config_paths=["~/.hermes/config.yaml"],
               skills_path="~/.agents/skills",
               mcp_config_path="~/.hermes/config.yaml", mcp_format="yaml",
               mcp_key_path="mcp_servers",
               aliases=["hermes", "hermes-agent"],
               by_os={
                   "windows": {"app_bundles": [], "commands": ["hermes"],
                               "config_paths": ["%USERPROFILE%\\.hermes\\config.yaml"], "skills_path": "%USERPROFILE%\\.agents\\skills",
                               "mcp_config_path": "%USERPROFILE%\\.hermes\\config.yaml"},
                   "linux": {"app_bundles": [], "commands": ["hermes"],
                             "config_paths": ["~/.hermes/config.yaml"], "skills_path": "~/.agents/skills",
                             "mcp_config_path": "~/.hermes/config.yaml"},
               }),
    ]
    return MAINSTREAM_TOOLS + extra
