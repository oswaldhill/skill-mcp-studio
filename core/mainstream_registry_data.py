"""主流工具数据表 —— 由 mainstream_registry.py 拆分（P2-16）。"""
import sys
from typing import Any, Dict, List


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
        # 桌面 app 现名 /Applications/DeepSeek Harness.app（bundle id
        # com.deepseek.harness.local）；旧名 DeepSeek AI Assistant.app 保留作兜底。
        # commands 除裸名外补 Homebrew 绝对路径：GUI 壳从 Finder 启动时继承 launchd
        # 最小 PATH（没有 /opt/homebrew/bin），只写裸名会让在用客户端被误判成
        # config_only（「仅配置」，并给出会删配置的清理入口）。
        app_bundles=[
            "/Applications/DeepSeek Harness.app",
            "/Applications/DeepSeek AI Assistant.app",
        ],
        commands=["dsh", "/opt/homebrew/bin/dsh"],
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
                "commands": ["dsh", "/usr/local/bin/dsh"],
                "config_paths": ["~/.dsh/settings.yaml", "~/.dsh/mcp.json"],
                "skills_path": "~/.dsh/skills",
                "mcp_config_path": "~/.dsh/mcp.json",
            },
        },
    ),
]
