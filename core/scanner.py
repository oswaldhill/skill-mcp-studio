"""

Skills 目录扫描器
- 读取 config.yaml 中的工具清单
- 调用 checker 检查每个工具
- 自动发现新工具并持久化保存
"""

import os
import yaml
import glob
from typing import Dict, Any, List


from checker import check_all, check_path
from tool_registry import normalized_name


# 工具类型推断映射表（3 类：AI IDE / IDE Plugin / AI Agent）
TYPE_KEYWORDS = {
    # AI IDE（独立 AI 编辑器）
    "AI IDE": ["cursor", "trae", "windsurf", "vscode", "vs code", "visual studio", "zed", "idea", "pycharm", "webstorm", "clawdbot"],
    # IDE Plugin（寄生在宿主 IDE 中的 AI 扩展）
    "IDE Plugin": [
        "cline", "roo", "copilot", "tabnine", "cody", "continue", "augment",
        "codeium", "lingma", "qoder", "comate", "codearts", "amazonq", "q-developer",
    ],
    # AI Agent（终端编码代理 + 独立助手/客户端）
    "AI Agent": [
        "claude", "codex", "aider", "opencode", "codebuddy", "reasonix",
        "gemini", "goose", "hermes", "dsh", "harness", "devin", "openclaw",
        "kimi", "moonshot", "qwen", "doubao", "deepseek", "workbuddy",
        # 注意：`cc-switch`（CC Switch）**故意不在此表**。它是供应商切换器/配置工具，
        # 既不是 IDE 也不是 Agent（见 config.yaml 中它的 non_agent 声明）。此前它列在
        # 这里，自动发现时就近被推断成「AI Agent」，与 config.yaml 里「非 AI Agent」
        # 的注释自相矛盾。
        "cherry", "ghcp-appmod",
    ],
}


DISCOVERED_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "data", "discovered_tools.yaml"
)


def infer_tool_type(tool_name: str) -> str:
    """
    根据工具名称自动推断类型
    """
    name = tool_name.lower()

    # 遍历关键词映射表
    for type_name, keywords in TYPE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in name:
                return type_name

    # 根据路径关键词推断
    if any(kw in name for kw in ["ide", "editor"]):
        return "AI IDE"
    elif any(kw in name for kw in ["plugin", "extension"]):
        return "IDE Plugin"

    return "AI Agent"  # 默认类型


def load_config(config_path: str = None) -> Dict[str, Any]:
    """
    加载配置文件
    """
    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "config.yaml"
        )

    config_path = os.path.normpath(config_path)

    if not os.path.exists(config_path):
        return {
            "unified_skills_dir": "~/.skills",
            "auto_discover": {"enabled": False, "scan_paths": []},
            "tools": [],
        }

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    config = config or {}

    # profile_sources 本地覆盖：真实端点等个人拓扑放仓库外，主干保持零个人拓扑。
    from profile_loader import apply_profile_sources

    return apply_profile_sources(config)


def load_discovered_tools() -> List[Dict[str, Any]]:
    """
    加载已发现的工具列表（持久化文件）
    """
    discovered_file = os.path.normpath(DISCOVERED_FILE)

    if not os.path.exists(discovered_file):
        return []

    with open(discovered_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data if isinstance(data, list) else []


def save_discovered_tools(discovered: List[Dict[str, Any]]) -> None:
    """
    保存新发现的工具到持久化文件
    """
    discovered_file = os.path.normpath(DISCOVERED_FILE)
    data_dir = os.path.dirname(discovered_file)

    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    with open(discovered_file, "w", encoding="utf-8") as f:
        yaml.dump(discovered, f, allow_unicode=True, default_flow_style=False)


def scan_for_new_tools(
    config: Dict[str, Any],
    discovered: List[Dict[str, Any]]
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    扫描本机，发现新的工具

    Returns:
        tuple: (new_tools, all_discovered)
        - new_tools: 本次新发现的工具（需要标记 🆕）
        - all_discovered: 所有已发现的工具（已知的 + 新发现的）
    """
    auto_discover = config.get("auto_discover", {})
    if not auto_discover.get("enabled", False):
        return [], discovered

    scan_paths = auto_discover.get("scan_paths", [])
    exclude_paths = auto_discover.get("exclude_paths", [])
    known_paths = set()

    # 收集所有已知路径（config.yaml）
    for t in config.get("tools", []):
        for p in t.get("skills_paths", []):
            expanded = os.path.expanduser(p)
            known_paths.add(os.path.normpath(expanded))

    # 收集所有已发现路径（discovered_tools.yaml）
    for t in discovered:
        for p in t.get("skills_paths", []):
            expanded = os.path.expanduser(p)
            known_paths.add(os.path.normpath(expanded))

    # 排除统一技能目录本身
    unified_dir = config.get("unified_skills_dir", "~/.skills")
    unified_expanded = os.path.normpath(os.path.expanduser(unified_dir))
    known_paths.add(unified_expanded)

    # 处理用户配置的排除路径（支持 glob 模式）
    normalized_excludes = set()
    for ep in exclude_paths:
        expanded_ep = os.path.expanduser(ep)
        # Check if it contains glob patterns
        if glob.has_magic(expanded_ep):
            for matched in glob.glob(expanded_ep):
                normalized_excludes.add(os.path.normpath(matched))
        else:
            normalized_excludes.add(os.path.normpath(expanded_ep))

    new_tools = []

    for pattern in scan_paths:
        expanded = os.path.expanduser(pattern)
        for matched_path in glob.glob(expanded):
            if not os.path.isdir(matched_path):
                continue

            normalized_path = os.path.normpath(matched_path)

            # 跳过已知路径和排除路径
            if normalized_path in known_paths or normalized_path in normalized_excludes:
                continue

            tool_name = os.path.basename(os.path.dirname(matched_path))
            inferred_type = infer_tool_type(tool_name)

            new_tool = {
                "name": tool_name,
                "type": inferred_type,
                "skills_paths": [matched_path],
                "backup_suffix": ".bak",
                "auto_discovered": True,
            }

            new_tools.append(new_tool)
            known_paths.add(normalized_path)

    # 合并：已发现的 + 新发现的
    all_discovered = discovered + new_tools

    # 持久化保存
    if new_tools:
        save_discovered_tools(all_discovered)

    return new_tools, all_discovered


def run_scan(
    config_path: str = None,
    auto_discover: bool = None
) -> Dict[str, Any]:
    """
    执行完整扫描

    Returns:
        dict: {
            "unified_dir": 统一目录,
            "results": 检查结果列表,
            "summary": 统计摘要,
            "new_tools": 本次新发现的工具名称列表,
        }
    """
    config = load_config(config_path)
    unified_dir = config.get("unified_skills_dir", "~/.skills")

    # 加载已知工具
    tools = list(config.get("tools", []))

    # 加载已发现的工具
    discovered = load_discovered_tools()

    # 归一名去重：discovered 里与 config.tools 同名的条目（如 Claude Code/Codex 等
    # 两边都有 skills 定义）会重复扫描，导致 skills_paths/expanded_paths 出现两份
    # 相同路径。config.tools 优先，discovered 仅补齐 config 没有的客户端。
    config_names = {normalized_name(t.get("name", "")) for t in tools if t.get("name")}
    discovered = [
        t for t in discovered
        if not (t.get("name") and normalized_name(t["name"]) in config_names)
    ]

    # 自动发现新工具
    new_tools = []
    if auto_discover or (
        auto_discover is None and config.get("auto_discover", {}).get("enabled", False)
    ):
        new_tools, all_discovered = scan_for_new_tools(config, discovered)
        tools.extend(all_discovered)
    else:
        tools.extend(discovered)

    # 获取排除路径
    exclude_paths = config.get("auto_discover", {}).get("exclude_paths", [])

    # 本机停用过滤：overlay 标记的停用客户端不进入管理与审计（trunk 注册表保留，
    # 只是本机不再管理）。与 effective_tools 的兜底过滤保持一致。
    disabled = {normalized_name(n) for n in (config.get("disabled_tools") or []) if isinstance(n, str)}
    if disabled:
        tools = [t for t in tools if normalized_name(t.get("name", "")) not in disabled]

    # 执行检查（传入排除路径）
    results = check_all(tools, unified_dir, new_tools, exclude_paths)

    # 统计摘要
    summary = {
        "total": len(results),
        "correct": sum(1 for r in results if r["status"] == "correct"),
        "real_dir": sum(1 for r in results if r["status"] == "real_dir"),
        "missing": sum(1 for r in results if r["status"] == "missing"),
        "wrong_link": sum(1 for r in results if r["status"] == "wrong_link"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
    }

    return {
        "unified_dir": unified_dir,
        "results": results,
        "summary": summary,
        "tools_count": len(tools),
        "new_tools_count": len(new_tools),
        "new_tools": new_tools,
    }
