"""
符号链接状态检查器
检查单个路径的状态：
- ✅ correct: 符号链接且指向统一 skills 目录
- ❌ real_dir: 真实目录（需要转换为符号链接）
- ❌ missing: 路径不存在
- ⚠️ wrong_link: 符号链接但指向错误位置
- ⏭️ skipped: 真实目录但已被排除（工具自有目录，不修复）
"""

import os
import shutil
from typing import Dict, Any, List, Optional


# 已知的工具自有技能目录特征
# 这些目录是工具管理的自有 skills，不应被替换为 symlink
KNOWN_OWN_SKILLS = [
    ".claude-plugin",       # Claude Code 插件目录
]

# 需要同时存在的标记组合（更严格的 npm 项目检测）
NPM_PROJECT_MARKERS = {"package.json"}  # package.json 存在时还需检查其他条件


def is_known_own_skills_dir(path: str) -> bool:
    """
    智能检测路径是否为工具自有的技能目录（不应被 symlink 替换）。
    """
    parent = os.path.dirname(path)
    if not parent or not os.path.isdir(parent):
        return False

    for marker in KNOWN_OWN_SKILLS:
        marker_path = os.path.join(parent, marker)
        if os.path.exists(marker_path):
            return True

    # npm 项目需要同时有 package.json 和 node_modules
    pkg = os.path.join(parent, "package.json")
    nm = os.path.join(parent, "node_modules")
    if os.path.exists(pkg) and os.path.isdir(nm):
        return True

    # 父目录本身也是 symlink → 可能是外部项目
    if os.path.islink(parent):
        return True

    return False


def _per_skill_link_states(path: str, unified: str) -> Dict[str, bool]:
    """Map each entry of a real skills dir to "is a valid unified symlink".

    Stage-4 addition (design §5): where ``_all_entries_point_to_unified`` is
    all-or-nothing, this returns the per-entry state so the toggle writer can
    re-read link states after a write (design §6.1 step 5). An entry is valid
    only when it is a symlink whose ``realpath`` resolves to the **matching**
    repo skill directory — the entry's own name under the unified repo — the
    same rule as ``skill_state.classify_skill_state`` (ADR-17: enabled = the
    link points at the matching repo skill). A link that points elsewhere
    inside the repo (another skill, or the repo root) is NOT that entry's
    enable link and counts as invalid.
    """
    try:
        entries = os.listdir(path)
    except OSError:
        return {}
    if not entries:
        return {}
    # realpath (not normpath) so symlinked path prefixes (macOS /var ->
    # /private/var) compare equal to the realpath'd link targets below.
    norm_unified = os.path.realpath(unified)
    states: Dict[str, bool] = {}
    for name in entries:
        # Dot rule: hidden entries are client runtime state (e.g. Codex
        # .system/), outside the skill inventory — not managed, not invalid.
        if name.startswith("."):
            continue
        entry = os.path.join(path, name)
        if not os.path.islink(entry):
            states[name] = False
            continue
        try:
            real = os.path.realpath(entry)
        except OSError:
            states[name] = False
            continue
        try:
            skill_dir = os.path.realpath(os.path.join(norm_unified, name))
            states[name] = real == skill_dir
        except OSError:
            states[name] = False
    return states


def _all_entries_point_to_unified(path: str, unified: str) -> bool:
    """True if every entry in a real skills dir is a symlink resolving under unified.

    Some agents (e.g. DSH) keep a real skills directory but symlink every entry
    to the unified repository. That is functionally equivalent to a directory
    symlink and must count as compliant (and must NOT be "fixed").
    """
    states = _per_skill_link_states(path, unified)
    return bool(states) and all(states.values())


def check_path(
    path: str,
    unified_dir: str,
    tool_type: str = "Unknown",
    is_new: bool = False,
    exclude_paths: Optional[List[str]] = None,
    tool_name: str = ""
) -> Dict[str, Any]:
    """
    检查单个路径的状态

    Args:
        path: 要检查的路径
        unified_dir: 统一 skills 目录路径（会展开 ~）
        tool_type: 工具类型（IDE/AI Agent 等）
        is_new: 是否是本次新发现的工具
        exclude_paths: 要排除的路径列表（展开后的绝对路径）

    Returns:
        dict: 检查结果
    """
    # 展开用户目录
    expanded_path = os.path.expanduser(path)
    expanded_unified = os.path.expanduser(unified_dir)

    # 规范化排除路径
    normalized_excludes = set()
    if exclude_paths:
        for ep in exclude_paths:
            expanded_ep = os.path.expanduser(ep)
            normalized_excludes.add(os.path.normpath(expanded_ep))

    result = {
        "path": path,
        "expanded_path": expanded_path,
        "unified_dir": unified_dir,
        "exists": False,
        "is_symlink": False,
        "target": None,
        "status": "missing",
        "tool_type": tool_type,
        "is_installed": False,
        "is_new": is_new,
        "note": "",
    }

    # 工具是否真实安装：以实际 CLI(在 PATH/常见 bin 目录) 或 App(/Applications) 为准，
    # 不以配置文件 / skills 软链目录的存在为准（后者会把仅创建了软链的工具误判为已安装）。
    if tool_name:
        result["is_installed"] = is_tool_installed(tool_name)
    else:
        parent_dir = os.path.dirname(expanded_path)
        result["is_installed"] = os.path.exists(parent_dir)

    # 检查路径是否存在（lexists 对 broken symlink 也返回 True）
    if not os.path.lexists(expanded_path):
        result["status"] = "missing"
        return result

    result["exists"] = True

    # 检查是否是 broken symlink
    if os.path.islink(expanded_path) and not os.path.exists(expanded_path):
        result["is_symlink"] = True
        result["target"] = os.readlink(expanded_path)
        result["status"] = "broken_link"
        result["note"] = "符号链接存在但目标不存在（broken symlink）"
        return result

    # 检查是否是符号链接
    if os.path.islink(expanded_path):
        result["is_symlink"] = True
        target = os.readlink(expanded_path)
        result["target"] = target

        # 用 realpath 解析完整符号链接链
        real_path = os.path.realpath(expanded_path)

        # 检查解析后的真实路径是否等于统一目录
        if os.path.normpath(real_path) == os.path.normpath(expanded_unified):
            result["status"] = "correct"
        else:
            result["status"] = "wrong_link"
    else:
        # 是真实目录
        result["status"] = "real_dir"

        # ⭐ 智能判定：检查是否应跳过修复
        normalized_path = os.path.normpath(expanded_path)
        if normalized_path in normalized_excludes:
            result["status"] = "skipped"
            result["note"] = "已在排除列表中，跳过修复"
        elif is_known_own_skills_dir(expanded_path):
            result["status"] = "skipped"
            marker = _find_own_marker(expanded_path)
            result["note"] = f"工具自有技能目录（检测到 {marker}），跳过修复"
        elif _all_entries_point_to_unified(expanded_path, expanded_unified):
            result["status"] = "correct"
            result["note"] = "真实目录，但内部条目全部为指向统一仓库的符号链接（等效统一）"

    return result


def _find_own_marker(path: str) -> str:
    """找到触发自有技能判定的标记文件/目录名"""
    parent = os.path.dirname(path)
    if not parent:
        return ""
    for marker in KNOWN_OWN_SKILLS:
        marker_path = os.path.join(parent, marker)
        if os.path.exists(marker_path):
            return marker
    # Check npm project
    pkg = os.path.join(parent, "package.json")
    nm = os.path.join(parent, "node_modules")
    if os.path.exists(pkg) and os.path.isdir(nm):
        return "package.json+node_modules"
    return ""


# ============================================================
# 真实安装检测：以实际 CLI(在 PATH/常见 bin 目录) 或 App(/Applications) 为准
# ============================================================

# CLI 搜索目录（不依赖继承的 PATH，确保稳健）
_BIN_DIRS = [
    "/usr/local/bin", "/opt/homebrew/bin", "/usr/bin", "/bin",
    os.path.expanduser("~/bin"), os.path.expanduser("~/.local/bin"),
]

# App 搜索目录
_APP_DIRS = [
    "/Applications", os.path.expanduser("~/Applications"),
]


def _norm_name(name: str) -> str:
    """规范化工具名：小写、去前导点、去空格与连字符。"""
    return name.strip().lower().lstrip(".").replace(" ", "").replace("-", "")


def _cli_exists(cmd: str) -> bool:
    """CLI 是否存在：shutil.which 或常见 bin 目录中存在可执行文件。"""
    if not cmd:
        return False
    if shutil.which(cmd):
        return True
    for d in _BIN_DIRS:
        p = os.path.join(d, cmd)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return True
    return False


def _app_exists(app: str) -> bool:
    """App 是否安装：/Applications 或 ~/Applications 下存在 .app 目录。"""
    if not app:
        return False
    for d in _APP_DIRS:
        if os.path.isdir(os.path.join(d, app)):
            return True
    return False


# 工具名(规范化) -> {cli: [候选命令], apps: [候选 .app 包名]}
# 候选来自本机实测：claude/codex/cursor/opencode/hermes/reasonix/trae CLI 在 PATH，
# CC Switch/Cursor/QoderWork/Reasonix/WorkBuddy.app 在 /Applications。
TOOL_INSTALL_SIGNS = {
    "claudecode":   {"cli": ["claude"], "apps": ["Claude.app"]},
    "codebuddy":    {"cli": ["codebuddy"], "apps": ["CodeBuddy.app"]},
    "cursor":       {"cli": ["cursor"], "apps": ["Cursor.app"]},
    "hermesagent":  {"cli": ["hermes"], "apps": ["Hermes.app"]},
    "opencode":     {"cli": ["opencode"], "apps": ["OpenCode.app"]},
    "workbuddy":    {"cli": ["workbuddy"], "apps": ["WorkBuddy.app"]},
    "ccswitch":     {"cli": ["cc-switch"], "apps": ["CC Switch.app"]},
    "codex":        {"cli": ["codex"], "apps": ["ChatGPT.app", "Codex.app", "CodeIsland.app"]},
    "reasonix":     {"cli": ["reasonix"], "apps": ["Reasonix.app"]},
    "qoderwork":    {"cli": ["qoderwork"], "apps": ["QoderWork.app"]},
    "qoder":        {"cli": ["qoder"], "apps": ["Qoder.app"]},
    "trae":         {"cli": ["trae"], "apps": ["Trae.app"]},
    "traecn":       {"cli": ["trae"], "apps": ["Trae CN.app"]},
    "cherrystudio": {"cli": [], "apps": ["Cherry Studio.app"]},
    "cline":        {"cli": ["cline"], "apps": ["Cline.app"]},
    "continue":     {"cli": ["continue"], "apps": ["Continue.app"]},
    "copilot":      {"cli": ["copilot", "github-copilot"],
                     "apps": ["GitHub Copilot.app", "Copilot.app", "ima.copilot.app"]},
    "gemini":       {"cli": ["gemini"], "apps": ["Gemini.app"]},
    "ghcpappmod":   {"cli": ["ghcp-appmod", "ghcp"], "apps": ["Ghcp Appmod.app"]},
    "kiro":         {"cli": ["kiro"], "apps": ["Kiro.app"]},
    "lingma":       {"cli": ["lingma"], "apps": ["Lingma.app"]},
    "windsurf":     {"cli": ["windsurf"], "apps": ["Windsurf.app"]},
    "claude":       {"cli": ["claude"], "apps": ["Claude.app"]},
    "dsh":          {"cli": ["dsh"], "apps": [], "config": ["~/.dsh/profiles/web/cordis.patch.yml"]},
    "vscode":       {"cli": ["code"], "apps": ["Visual Studio Code.app", "VS Code.app"]},
}


def is_tool_installed(name: str) -> bool:
    """
    判断工具是否真实安装：实际 CLI 或 App 任一存在即视为已安装。
    未命中签名表时回退为启发式（规范化名作 CLI、首字母大写+.app 作 App）。
    """
    if not name:
        return False
    key = _norm_name(name)
    sig = TOOL_INSTALL_SIGNS.get(key)
    if sig is None:
        # 启发式回退
        cli = [key] if key else []
        base = name.strip().lstrip(".")
        titled = " ".join(w.capitalize() for w in base.replace("-", " ").split())
        sig = {"cli": cli, "apps": [titled + ".app"]}

    for c in sig.get("cli", []):
        if _cli_exists(c):
            return True
    for a in sig.get("apps", []):
        if _app_exists(a):
            return True
    for cfg in sig.get("config", []):
        if os.path.exists(os.path.expanduser(cfg)):
            return True
    return False


def check_all(
    tools_config: List[Dict[str, Any]],
    unified_dir: str,
    new_tools: List[Dict[str, Any]] = None,
    exclude_paths: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    检查所有工具的 skills 路径

    Args:
        tools_config: config.yaml 中的 tools 列表
        unified_dir: 统一 skills 目录
        new_tools: 本次新发现的工具列表（用于标记 is_new）
        exclude_paths: 要排除的路径列表（原始格式，含 ~）

    Returns:
        list: 每个工具每个路径的检查结果列表
    """
    results = []
    new_tool_names = {t.get("name", "") for t in (new_tools or [])}

    for tool in tools_config:
        tool_name = tool.get("name", "Unknown")
        tool_type = tool.get("type", "Unknown")
        skills_paths = tool.get("skills_paths", [])

        # 判断是否是新发现的工具
        is_new = tool_name in new_tool_names

        for path in skills_paths:
            result = check_path(path, unified_dir, tool_type, is_new, exclude_paths, tool_name)
            result["tool_name"] = tool_name
            results.append(result)

    return results


def status_label(status: str) -> str:
    """
    返回状态的中文标签和 emoji
    """
    labels = {
        "correct": "✅ 正确",
        "real_dir": "❌ 真实目录",
        "missing": "❌ 缺失",
        "wrong_link": "⚠️ 错误指向",
        "broken_link": "⚠️ 断链",
        "skipped": "⏭️ 跳过",
    }
    return labels.get(status, "❓ 未知")
