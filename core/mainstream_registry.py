"""内置主流 IDE / Agent 默认清单（skill-mcp-studio 整改）。

每个条目自带安装检测信息（app_bundles / commands / config_paths）、Skills 目录、
以及 MCP 配置文件定位（config_path / format / mcp_key_path），使「默认添加」后
能立即参与三态安装判定与 MCP 检查，与手工配置的 registry 条目完全一致。

install.commands 的探测用 shutil.which（PATH 上的可执行文件），app_bundles /
config_paths 用 os.path.exists（expanduser 后）。用户机器上未命中的条目会按
三态语义落为 config_only（仅配置，显示待确认）或 none（隐藏），不会误报已安装。
"""

from typing import Any, Dict, List


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
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "name": name,
        "type": type_,
        "install": {
            "app_bundles": app_bundles or [],
            "commands": commands or [],
            "config_paths": config_paths or [],
        },
    }
    if skills_path:
        entry["skills_paths"] = [skills_path]
    if mcp_config_path:
        entry["config_path"] = mcp_config_path
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
    ),
    _entry(
        "VS Code", type_="AI IDE",
        app_bundles=["/Applications/Visual Studio Code.app"],
        commands=["code"],
        config_paths=["~/.vscode/mcp.json", "~/.config/Code/User/mcp.json"],
        skills_path="~/.vscode/skills",
        mcp_config_path="~/.vscode/mcp.json",
        aliases=["vscode", "visual-studio-code"],
    ),
    _entry(
        "Windsurf", type_="AI IDE",
        app_bundles=["/Applications/Windsurf.app"],
        commands=["windsurf"],
        config_paths=["~/.codeium/windsurf/mcp_config.json"],
        skills_path="~/.windsurf/skills",
        mcp_config_path="~/.codeium/windsurf/mcp_config.json",
        aliases=["windsurf"],
    ),
    _entry(
        "TRAE", type_="AI IDE",
        app_bundles=["/Applications/Trae.app"],
        commands=["trae"],
        config_paths=["~/Library/Application Support/Trae/User/mcp.json"],
        skills_path="~/.trae/skills",
        mcp_config_path="~/Library/Application Support/Trae/User/mcp.json",
        aliases=["trae", "trae-cn"],
    ),
    _entry(
        "Zed", type_="AI IDE",
        app_bundles=["/Applications/Zed.app"],
        commands=["zed"],
        config_paths=["~/.config/zed/settings.json"],
        skills_path="~/.config/zed/skills",
        mcp_config_path="~/.config/zed/settings.json", mcp_format="json", mcp_key_path="context_servers",
        aliases=["zed"],
    ),
    _entry(
        "JetBrains IntelliJ IDEA", type_="AI IDE",
        app_bundles=["/Applications/IntelliJ IDEA.app"],
        commands=["idea"],
        config_paths=["~/.config/JetBrains/mcp.json"],
        aliases=["intellij", "idea"],
    ),
    _entry(
        "JetBrains PyCharm", type_="AI IDE",
        app_bundles=["/Applications/PyCharm.app"],
        commands=["pycharm"],
        config_paths=["~/.config/JetBrains/mcp.json"],
        aliases=["pycharm"],
    ),
    _entry(
        "JetBrains WebStorm", type_="AI IDE",
        app_bundles=["/Applications/WebStorm.app"],
        commands=["webstorm"],
        config_paths=["~/.config/JetBrains/mcp.json"],
        aliases=["webstorm"],
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
    ),
    _entry(
        "Gemini CLI", type_="AI Agent",
        commands=["gemini"],
        config_paths=["~/.gemini/settings.json", "~/.config/gemini/mcp.json"],
        skills_path="~/.gemini/skills",
        mcp_config_path="~/.config/gemini/mcp.json",
        aliases=["gemini", "gemini-cli"],
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
    ),
    _entry(
        "Aider", type_="AI Agent",
        commands=["aider"],
        config_paths=["~/.aider/mcp.json", "~/.config/aider/mcp.json"],
        skills_path="~/.aider/skills",
        aliases=["aider"],
    ),
    _entry(
        "OpenCode", type_="AI Agent",
        commands=["opencode"],
        config_paths=["~/.config/opencode/opencode.jsonc"],
        skills_path="~/.config/opencode/skills",
        mcp_config_path="~/.config/opencode/opencode.jsonc", mcp_format="jsonc", mcp_key_path="mcp",
        aliases=["opencode"],
    ),
    _entry(
        "Goose", type_="AI Agent",
        commands=["goose"],
        config_paths=["~/.config/goose/settings.json", "~/.config/goose/config.yaml"],
        skills_path="~/.config/goose/skills",
        mcp_config_path="~/.config/goose/config.yaml", mcp_format="yaml", mcp_key_path="extensions",
        aliases=["goose"],
    ),
    _entry(
        "WorkBuddy", type_="AI Agent",
        app_bundles=["/Applications/WorkBuddy.app"],
        commands=["workbuddy"],
        config_paths=["~/.workbuddy/mcp.json"],
        skills_path="~/.workbuddy/skills",
        mcp_config_path="~/.workbuddy/mcp.json",
        aliases=["workbuddy"],
    ),
    _entry(
        "Cherry Studio", type_="AI Agent",
        app_bundles=["/Applications/Cherry Studio.app", "/Applications/CherryStudio.app"],
        commands=["cherry-studio"],
        config_paths=["~/.config/CherryStudio/mcp.json"],
        aliases=["cherry", "cherry-studio"],
    ),
    # ---- 当前 AI 本体（原 DSH）----
    _entry(
        "DeepSeek Harness", type_="AI Agent",
        commands=["dsh"],
        config_paths=["~/.dsh/settings.yaml", "~/.dsh/mcp.json"],
        skills_path="~/.dsh/skills",
        mcp_config_path="~/.dsh/mcp.json",
        aliases=["dsh", "ds-harness", "deepseek-harness"],
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
               aliases=["lingma", "tongyi-lingma", "qoder"]),
        _entry("百度 Comate", type_="IDE Plugin",
               app_bundles=["/Applications/Comate.app"], commands=["comate"],
               config_paths=["~/.comate/mcp.json"],
               aliases=["comate", "baidu-comate"]),
        _entry("CodeBuddy", type_="AI Agent",
               app_bundles=["/Applications/CodeBuddy.app"], commands=["codebuddy"],
               config_paths=["~/.codebuddy/mcp.json"], skills_path="~/.codebuddy/skills",
               mcp_config_path="~/.codebuddy/mcp.json",
               aliases=["codebuddy", "tencent-codebuddy"]),
        _entry("Kimi", type_="AI Agent",
               app_bundles=["/Applications/Kimi.app"], commands=["kimi"],
               config_paths=["~/.kimi/mcp.json"], skills_path="~/.kimi/skills",
               aliases=["kimi", "moonshot"]),
        _entry("Qwen", type_="AI Agent",
               app_bundles=["/Applications/Qwen.app"], commands=["qwen"],
               config_paths=["~/.qwen/mcp.json"], skills_path="~/.qwen/skills",
               aliases=["qwen", "tongyi-qianwen"]),
        _entry("豆包", type_="AI Agent",
               app_bundles=["/Applications/Doubao.app"], commands=["doubao"],
               config_paths=["~/.doubao/mcp.json"],
               aliases=["doubao", "bytedance-doubao"]),
        _entry("Huawei CodeArts", type_="IDE Plugin",
               commands=["codearts"], config_paths=["~/.codearts/mcp.json"],
               aliases=["codearts", "huawei-codearts"]),
        _entry("DeepSeek", type_="AI Agent",
               app_bundles=["/Applications/DeepSeek.app"], commands=["deepseek"],
               config_paths=["~/.deepseek/mcp.json"], skills_path="~/.deepseek/skills",
               aliases=["deepseek", "deepseek-app"]),
        # ==== 国际常用 ====
        _entry("GitHub Copilot", type_="IDE Plugin",
               app_bundles=["/Applications/GitHub Copilot.app"], commands=["copilot"],
               config_paths=["~/.copilot/mcp.json", "~/.config/github-copilot/mcp.json"],
               skills_path="~/.copilot/skills", mcp_config_path="~/.copilot/mcp.json",
               aliases=["copilot", "github-copilot"]),
        _entry("Amazon Q", type_="IDE Plugin",
               commands=["q"], config_paths=["~/.aws/amazonq/mcp.json"],
               aliases=["amazon-q", "q-developer"]),
        _entry("Tabnine", type_="IDE Plugin",
               commands=["tabnine"], config_paths=["~/.tabnine/mcp.json"],
               aliases=["tabnine"]),
        _entry("Cody", type_="IDE Plugin",
               commands=["cody"], config_paths=["~/.sourcegraph/cody/mcp.json"],
               skills_path="~/.sourcegraph/cody/skills",
               aliases=["cody", "sourcegraph-cody"]),
        _entry("Continue", type_="IDE Plugin",
               commands=["continue"], config_paths=["~/.continue/config.json"],
               skills_path="~/.continue/skills",
               aliases=["continue", "continue-dev"]),
        _entry("Augment Code", type_="IDE Plugin",
               commands=["augment"], config_paths=["~/.augment/mcp.json"],
               skills_path="~/.augment/skills",
               aliases=["augment", "augment-code"]),
        _entry("Codeium", type_="IDE Plugin",
               app_bundles=["/Applications/Codeium.app"], commands=["codeium"],
               config_paths=["~/.codeium/mcp.json"],
               aliases=["codeium"]),
        _entry("Reasonix", type_="AI Agent",
               app_bundles=["/Applications/Reasonix.app"], commands=["reasonix"],
               config_paths=["~/.reasonix/config.toml"], skills_path="~/.reasonix/skills",
               mcp_config_path="~/.reasonix/config.toml", mcp_format="reasonix_toml",
               mcp_key_path="plugins",
               aliases=["reasonix"]),
        _entry("Hermes Agent", type_="AI Agent",
               commands=["hermes"], config_paths=["~/.hermes/config.yaml"],
               skills_path="~/.agents/skills",
               mcp_config_path="~/.hermes/config.yaml", mcp_format="yaml",
               mcp_key_path="mcp_servers",
               aliases=["hermes", "hermes-agent"]),
    ]
    return MAINSTREAM_TOOLS + extra
