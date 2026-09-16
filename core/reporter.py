"""

报告生成器
- 控制台彩色表格输出
- Markdown 文件输出（~/.skills/skills-unifier/scan-report.md）
"""

import os
from typing import Dict, List, Any
from checker import status_label


# ANSI 颜色代码
class Color:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    END = "\033[0m"


def _color_for_status(status: str) -> str:
    """根据状态返回对应的 ANSI 颜色代码"""
    if status == "correct":
        return Color.GREEN
    elif status == "real_dir":
        return Color.RED
    elif status == "wrong_link":
        return Color.YELLOW
    elif status == "skipped":
        return Color.BLUE
    else:  # missing
        return Color.RED


def _tool_name_display(tool_name: str, is_new: bool) -> str:
    """返回带 🆕 标记的工具名称（如果需要）"""
    if is_new:
        return f"🆕 {tool_name}"
    return tool_name


def print_console_report(scan_result: Dict[str, Any]) -> None:
    """
    在控制台打印彩色表格报告
    """
    unified_dir = scan_result.get("unified_dir", "")
    results = scan_result.get("results", [])
    summary = scan_result.get("summary", {})
    new_tools_count = scan_result.get("new_tools_count", 0)

    print("")
    print("=" * 100)
    print(f"  Skills 统一化检查报告")
    print(f"  统一目录: {unified_dir}")
    if new_tools_count > 0:
        print(f"  🆕 新发现工具: {new_tools_count} 个")
    print("=" * 100)
    print("")

    # 表头
    header = f"  {'Tool':<22} {'类型':<20} {'安装':<8} {'Skills 路径':<40} {'状态':<15}"
    print(Color.BOLD + header + Color.END)
    print("-" * 100)

    # 表格内容
    for r in results:
        tool_name = r.get("tool_name", "Unknown")
        is_new = r.get("is_new", False)
        display_name = _tool_name_display(tool_name, is_new)

        tool_type = r.get("tool_type", "Unknown")
        is_installed = r.get("is_installed", False)
        path = r.get("path", "")
        status = r.get("status", "missing")
        label = status_label(status)

        install_str = "✅" if is_installed else "❌"
        color = _color_for_status(status)
        line = f"  {display_name:<22} {tool_type:<20} {install_str:<8} {path:<38} {color}{label}{Color.END}"
        print(line)

    print("")
    print("-" * 100)

    # 统计摘要
    total = summary.get("total", 0)
    correct = summary.get("correct", 0)
    real_dir = summary.get("real_dir", 0)
    missing = summary.get("missing", 0)
    wrong_link = summary.get("wrong_link", 0)
    skipped = summary.get("skipped", 0)

    print(f"  总计: {total} 个路径")
    print(f"  {Color.GREEN}✅ 正确（symlink）: {correct}{Color.END}")
    print(f"  {Color.RED}❌ 真实目录（需修复）: {real_dir}{Color.END}")
    print(f"  ⏭️ 跳过（工具自有）: {skipped}")
    print(f"  {Color.RED}❌ 缺失: {missing}{Color.END}")
    print(f"  {Color.YELLOW}⚠️  错误指向: {wrong_link}{Color.END}")
    print("")

    # 修复建议
    if real_dir > 0 or wrong_link > 0:
        print(f"  {Color.YELLOW}⚠️  建议执行: python3 scan.py --fix{Color.END}")
        print("")

    print("=" * 100)


def write_markdown_report(
    scan_result: Dict[str, Any],
    output_path: str = None,
    combined_result: Dict[str, Any] = None,
    frontmatter_audit: Dict[str, Any] = None,
) -> str:
    """
    生成 Markdown 格式报告文件

    Args:
        scan_result: run_scan() 的返回结果
        output_path: 输出文件路径，默认为 scan-report.md
        combined_result: unified MCP/hooks 检查结果（可选）
        frontmatter_audit: SKILL.md frontmatter 契约审计结果（可选）

    Returns:
        str: 实际写入的文件路径
    """
    if output_path is None:
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "scan-report.md"
        )
    output_path = os.path.normpath(output_path)

    unified_dir = scan_result.get("unified_dir", "")
    results = scan_result.get("results", [])
    summary = scan_result.get("summary", {})
    new_tools_count = scan_result.get("new_tools_count", 0)

    lines = []
    lines.append("# Skills 统一化检查报告\n")
    lines.append(f"**统一目录**: `{unified_dir}`\n")
    if new_tools_count > 0:
        lines.append(f"**🆕 新发现工具**: {new_tools_count} 个\n")
    lines.append("---\n")

    # 统计摘要
    total = summary.get("total", 0)
    correct = summary.get("correct", 0)
    real_dir = summary.get("real_dir", 0)
    missing = summary.get("missing", 0)
    wrong_link = summary.get("wrong_link", 0)
    skipped = summary.get("skipped", 0)

    lines.append("## 📊 统计摘要\n")
    lines.append(f"- 总计: **{total}** 个路径")
    lines.append(f"- ✅ 正确（symlink）: **{correct}**")
    lines.append(f"- ❌ 真实目录（需修复）: **{real_dir}**")
    lines.append(f"- ⏭️ 跳过（工具自有技能目录）: **{skipped}**")
    lines.append(f"- ❌ 缺失: **{missing}**")
    lines.append(f"- ⚠️ 错误指向: **{wrong_link}**\n")
    lines.append("---\n")

    # 详细信息表格
    lines.append("## 📋 详细信息\n")
    lines.append("| 工具名称 | 类型 | 已安装 | Skills 路径 | 状态 | 目标/说明 |")
    lines.append("|----------|------|--------|-------------|------|----------|")

    for r in results:
        tool_name = r.get("tool_name", "Unknown")
        is_new = r.get("is_new", False)
        display_name = _tool_name_display(tool_name, is_new)

        tool_type = r.get("tool_type", "Unknown")
        is_installed = r.get("is_installed", False)
        path = r.get("path", "")
        status = r.get("status", "missing")
        label = status_label(status)
        target = r.get("target", "-")

        install_str = "✅" if is_installed else "❌"

        if status == "correct":
            detail = f"→ `{target}`"
        elif status == "wrong_link":
            detail = f"错误指向: `{target}`"
        elif status == "real_dir":
            detail = "需要转换为 symlink"
        elif status == "skipped":
            note = r.get("note", "")
            detail = f"⏭️ 工具自有技能目录 {('(' + note + ')') if note else ''}"
        else:
            detail = "路径不存在"

        lines.append(f"| {display_name} | {tool_type} | {install_str} | `{path}` | {label} | {detail} |")

    lines.append("\n---\n")

    if frontmatter_audit is not None:
        from frontmatter_audit import format_frontmatter_markdown

        lines.append(format_frontmatter_markdown(frontmatter_audit))
        lines.append("\n---\n")

    if combined_result is not None:
        from combined_checker import format_combined_markdown

        lines.append(format_combined_markdown(combined_result))
        lines.append("\n---\n")

    # 修复命令
    if real_dir > 0 or wrong_link > 0:
        lines.append("## 🔧 修复命令\n")
        lines.append("```bash")
        lines.append("# 预览修复（不实际修改）")
        lines.append("python3 scan.py --fix --dry-run")
        lines.append("")
        lines.append("# 执行修复（备份 + 创建 symlink）")
        lines.append("python3 scan.py --fix")
        lines.append("```\n")

    lines.append("\n> 报告生成时间: 自动生成\n")

    content = "\n".join(lines)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    return output_path
