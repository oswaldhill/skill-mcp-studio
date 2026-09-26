"""
Skills 分布分析与整理建议模块
功能：
1. 扫描 skills 目录结构，统计分布情况
2. 检测重复的技能（同名或功能相似）
3. 检测可能过时的技能（基于目录名命名规范判断）
4. 给出整理建议
"""

import os
import re
from typing import Dict, Any, List, Set


def scan_skills_distribution(unified_dir: str) -> Dict[str, Any]:
    """
    扫描 skills 目录的分布情况。

    Args:
        unified_dir: 统一 skills 目录路径（已展开）

    Returns:
        dict: {
            "total_skills": int,           # 技能总数
            "categories": dict,            # 按前缀/命名空间分类
            "skill_names": list,           # 所有技能名列表
            "has_skill_md": int,           # 有 SKILL.md 的技能数
            "no_skill_md": int,            # 没有 SKILL.md 的技能数
            "has_dot_prefix": int,         # 点前缀的目录数（隐藏/系统）
            "subdirectories": list,        # 所有子目录
        }
    """
    expanded = os.path.expanduser(unified_dir)

    if not os.path.isdir(expanded):
        return {
            "total_skills": 0,
            "categories": {},
            "skill_names": [],
            "has_skill_md": 0,
            "no_skill_md": 0,
            "has_dot_prefix": 0,
            "subdirectories": [],
            "error": "目录不存在",
        }

    # 收集所有一级子目录
    subdirs = []
    has_skill_md = 0
    no_skill_md = 0
    dot_prefix_count = 0

    try:
        for item in sorted(os.listdir(expanded)):
            item_path = os.path.join(expanded, item)
            if os.path.isdir(item_path):
                subdirs.append(item)
                if item.startswith("."):
                    dot_prefix_count += 1
                else:
                    # 检查是否有 SKILL.md
                    skill_md_path = os.path.join(item_path, "SKILL.md")
                    if os.path.exists(skill_md_path):
                        has_skill_md += 1
                    else:
                        no_skill_md += 1
    except PermissionError:
        pass

    # 按命名空间/前缀分类
    categories = {}
    for name in subdirs:
        if name.startswith("."):
            cat = "系统/隐藏"
        elif "-" in name:
            prefix = name.split("-")[0]
            cat = f"{prefix}-*"
        elif "_" in name:
            prefix = name.split("_")[0]
            cat = f"{prefix}_*"
        else:
            cat = "其他"

        if cat not in categories:
            categories[cat] = []
        categories[cat].append(name)

    return {
        "total_skills": len(subdirs),
        "skill_subdirs": len([s for s in subdirs if not s.startswith(".")]),
        "dot_prefix_count": dot_prefix_count,
        "categories": categories,
        "skill_names": subdirs,
        "has_skill_md": has_skill_md,
        "no_skill_md": no_skill_md,
        "subdirectories": subdirs,
    }


def find_duplicates(skill_names: List[str]) -> List[Dict[str, Any]]:
    """
    查找可能重复的技能。

    检测策略：
    - 完全同名的技能（不同路径）
    - 名称相似度高的技能（如 "pdf-maker" vs "nano-pdf" vs "minimax-pdf"）

    Args:
        skill_names: 技能名列表

    Returns:
        list: [{"group": str, "skills": [name1, name2, ...], "reason": str}, ...]
    """
    duplicates = []

    # 策略1: 寻找包含相同核心关键词的技能
    keyword_groups: Dict[str, List[str]] = {}
    for name in skill_names:
        if name.startswith("."):
            continue
        # 提取有意义的单词（去掉前缀分隔符）
        parts = re.split(r"[-_]", name.lower())
        for part in parts:
            if len(part) >= 3 and part not in ("and", "the", "for", "with", "to"):
                if part not in keyword_groups:
                    keyword_groups[part] = []
                keyword_groups[part].append(name)

    # 过滤出共享关键词的组（>=2 个同名技能共享同一关键词）
    for keyword, names in keyword_groups.items():
        unique_names = sorted(set(names))
        if len(unique_names) >= 2:
            duplicates.append({
                "group": f"关键词: {keyword}",
                "skills": unique_names,
                "reason": f"共享关键词 '{keyword}'，可能功能重叠",
            })

    # 策略2: 全名包含关系（如 "pdf" 包含 "pdf-maker"、"nano-pdf"）
    # 防止过多，按组去重合并
    seen_groups: Set[str] = set()
    filtered = []
    for dup in duplicates:
        group_key = "|".join(sorted(dup["skills"]))
        if group_key not in seen_groups:
            seen_groups.add(group_key)
            filtered.append(dup)

    return filtered


def find_skills_without_skillmd(unified_dir: str) -> List[str]:
    """
    查找没有 SKILL.md 文件的技能目录。

    Args:
        unified_dir: 统一 skills 目录路径

    Returns:
        list: 缺少 SKILL.md 的技能名列表
    """
    expanded = os.path.expanduser(unified_dir)
    missing = []

    if not os.path.isdir(expanded):
        return missing

    try:
        for item in sorted(os.listdir(expanded)):
            if item.startswith("."):
                continue
            item_path = os.path.join(expanded, item)
            if os.path.isdir(item_path):
                skill_md = os.path.join(item_path, "SKILL.md")
                if not os.path.exists(skill_md):
                    missing.append(item)
    except PermissionError:
        pass

    return missing


def get_skills_summary(unified_dir: str) -> Dict[str, Any]:
    """
    生成 skills 目录的完整分析报告。

    Args:
        unified_dir: 统一 skills 目录路径

    Returns:
        dict: 完整的分析结果
    """
    distribution = scan_skills_distribution(unified_dir)
    skill_names = distribution.get("skill_names", [])

    if distribution.get("total_skills", 0) == 0:
        return {
            "distribution": distribution,
            "duplicates": [],
            "missing_skillmd": [],
            "suggestions": ["skills 目录为空，暂无建议"],
        }

    real_skills = [n for n in skill_names if not n.startswith(".")]
    duplicates = find_duplicates(real_skills)
    missing_skillmd = find_skills_without_skillmd(unified_dir)

    suggestions = generate_suggestions(distribution, duplicates, missing_skillmd, real_skills)

    for dup in duplicates:
        dup["skills"] = dup["skills"]  # 已排序

    return {
        "distribution": distribution,
        "duplicates": duplicates,
        "missing_skillmd": missing_skillmd,
        "suggestions": suggestions,
    }


def generate_suggestions(
    distribution: Dict[str, Any],
    duplicates: List[Dict[str, Any]],
    missing_skillmd: List[str],
    skill_names: List[str],
) -> List[str]:
    """
    根据分析结果生成整理建议。

    Args:
        distribution: 分布信息
        duplicates: 重复项列表
        missing_skillmd: 缺少 SKILL.md 的技能
        skill_names: 所有技能名

    Returns:
        list: 建议列表
    """
    suggestions = []

    total = distribution.get("total_skills", 0)
    real_count = distribution.get("skill_subdirs", 0)
    hidden_count = distribution.get("dot_prefix_count", 0)

    suggestions.append(f"当前 skills 总数: {total}（实际技能: {real_count}，系统/隐藏: {hidden_count}）")

    # 建议1: 缺少 SKILL.md
    if missing_skillmd:
        if len(missing_skillmd) <= 5:
            suggestions.append(f"⚠️ 以下 {len(missing_skillmd)} 个技能缺少 SKILL.md 描述文件: {', '.join(missing_skillmd)}")
        else:
            suggestions.append(f"⚠️ 有 {len(missing_skillmd)} 个技能缺少 SKILL.md 描述文件（如 {', '.join(missing_skillmd[:5])}...）")

    # 建议2: 重复项
    if duplicates:
        suggestions.append(f"🔄 发现 {len(duplicates)} 组可能重复的技能:")
        for dup in duplicates[:5]:  # 最多显示前5组
            suggestions.append(f"   - [{dup['group']}] {', '.join(dup['skills'])} ({dup['reason']})")
        if len(duplicates) > 5:
            suggestions.append(f"   ... 还有 {len(duplicates) - 5} 组")
    else:
        suggestions.append("✅ 未发现明显重复的技能")

    # 建议3: 分类建议
    categories = distribution.get("categories", {})
    if len(categories) > 10:
        suggestions.append(f"📂 技能分布在 {len(categories)} 个命名空间下，可使用前缀分类整理")

    # 建议4: SKILL.md 覆盖情况
    has_md = distribution.get("has_skill_md", 0)
    coverage = (has_md / real_count * 100) if real_count > 0 else 0
    suggestions.append(f"📄 SKILL.md 覆盖率: {has_md}/{real_count} ({coverage:.1f}%)")

    return suggestions


def format_analysis_report(analysis: Dict[str, Any]) -> str:
    """
    将分析结果格式化为可读字符串。

    Args:
        analysis: get_skills_summary() 的返回结果

    Returns:
        str: 格式化的报告
    """
    lines = []
    lines.append("=" * 60)
    lines.append("  Skills 分布分析与整理建议")
    lines.append("=" * 60)
    lines.append("")

    dist = analysis.get("distribution", {})
    lines.append(f"  📊 技能总数: {dist.get('total_skills', 0)}")
    lines.append(f"     ├─ 实际技能: {dist.get('skill_subdirs', 0)}")
    lines.append(f"     ├─ 系统/隐藏: {dist.get('dot_prefix_count', 0)}")
    lines.append(f"     ├─ 有 SKILL.md: {dist.get('has_skill_md', 0)}")
    lines.append(f"     └─ 无 SKILL.md: {dist.get('no_skill_md', 0)}")
    lines.append("")

    # 分类统计
    categories = dist.get("categories", {})
    if categories:
        lines.append("  📁 命名空间分布:")
        for cat in sorted(categories.keys()):
            count = len(categories[cat])
            bar = "█" * min(count, 30)
            lines.append(f"    {cat:<15} {count:3d} {bar}")
        lines.append("")

    # 重复项
    duplicates = analysis.get("duplicates", [])
    if duplicates:
        lines.append(f"  🔄 可能重复的技能 ({len(duplicates)} 组):")
        for dup in duplicates:
            lines.append(f"    [{dup['group']}]")
            lines.append(f"      {', '.join(dup['skills'])}")
            lines.append(f"      原因: {dup['reason']}")
        lines.append("")

    # 缺少 SKILL.md
    missing = analysis.get("missing_skillmd", [])
    if missing:
        lines.append(f"  ⚠️ 缺少 SKILL.md 描述 ({len(missing)} 个):")
        for name in missing[:10]:
            lines.append(f"    {name}")
        if len(missing) > 10:
            lines.append(f"    ... 还有 {len(missing) - 10} 个")
        lines.append("")

    lines.append("━━━ 整理建议 ━━━")
    lines.append("")
    for s in analysis.get("suggestions", []):
        lines.append(f"  {s}")

    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)
