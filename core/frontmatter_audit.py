"""SKILL.md frontmatter 契约审计（只读）。

对统一 Skills 仓库做 frontmatter 契约检查：每个技能目录的 ``SKILL.md`` 必须
携带 YAML frontmatter，且包含必填字段 ``name`` 与 ``description``。frontmatter
驱动的消费者（远程仓库列表、技能市场、解析 ``name``/``description`` 的注册表）
会静默丢弃使用非标准字段的技能，症状是本地与远程计数不一致。本审计只读，绝不
改写 frontmatter；符号链接别名目录（如 ``skills-unifier`` -> ``skills-mcp-unifier``）
跳过。
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is a declared dependency
    yaml = None

# frontmatter 块只出现在 SKILL.md 顶部。
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
# 超长描述仅作警告：超过该字符数的 description 大概率会在市场/注册表被截断。
DESCRIPTION_MAX_LEN = 200


def audit_skill_frontmatter(unified_dir: str) -> Dict[str, Any]:
    """只读审计每个技能目录的 ``SKILL.md`` frontmatter 契约。

    审计范围：统一目录下一级、非 dot、非符号链接别名的子目录。检查项：

    - 缺 ``SKILL.md`` 文件
    - 缺 frontmatter 块（或块未闭合）
    - frontmatter YAML 解析失败 / 非映射
    - 缺 ``name`` / ``description``，或用 ``title``/``summary`` 非标准字段替代 ``name``
    - ``name`` 与目录名不符（警告）
    - ``description`` 超长（警告）

    Returns:
        结构化审计结果（详见各键）；``problems`` 与 ``warnings`` 为汇总计数。
    """
    expanded = os.path.expanduser(unified_dir)
    result: Dict[str, Any] = {
        "skills_dir": expanded,
        "total_skills": 0,
        "skipped_aliases": [],
        "missing_skillmd": [],
        "missing_frontmatter": [],
        "unparsable": [],
        "missing_name": [],
        "missing_description": [],
        "nonstandard_name_field": [],
        "name_mismatch": [],
        "overlong_description": [],
        "problems": 0,
        "warnings": 0,
    }
    if not os.path.isdir(expanded):
        return result

    for item in sorted(os.listdir(expanded)):
        item_path = os.path.join(expanded, item)
        if item.startswith(".") or not os.path.isdir(item_path):
            continue
        # 符号链接别名目录跳过（skills-unifier -> skills-mcp-unifier 之类）。
        if os.path.islink(item_path):
            result["skipped_aliases"].append(item)
            continue
        result["total_skills"] += 1
        _audit_one(result, item_path, item)

    result["problems"] = (
        len(result["missing_skillmd"])
        + len(result["missing_frontmatter"])
        + len(result["unparsable"])
        + len(result["missing_name"])
        + len(result["missing_description"])
        + len(result["nonstandard_name_field"])
    )
    result["warnings"] = len(result["name_mismatch"]) + len(result["overlong_description"])
    return result


def _audit_one(result: Dict[str, Any], item_path: str, dir_name: str) -> None:
    """审计单个技能目录的 SKILL.md frontmatter，就地追加到 ``result``。"""
    md_path = os.path.join(item_path, "SKILL.md")
    if not os.path.isfile(md_path):
        result["missing_skillmd"].append(dir_name)
        return

    try:
        with open(md_path, encoding="utf-8") as fh:
            head = fh.read(8192)
    except OSError:
        result["missing_skillmd"].append(dir_name)
        return

    m = FRONTMATTER_RE.match(head)
    if not m:
        # 无 frontmatter 块，或块未闭合（都归为「缺 frontmatter / 未闭合」）。
        result["missing_frontmatter"].append(dir_name)
        return

    data: Any = None
    if yaml is not None:
        try:
            data = yaml.safe_load(m.group(1))
        except Exception:
            data = None
    if data is None:
        result["unparsable"].append(dir_name)
        return
    if not isinstance(data, dict):
        result["unparsable"].append(dir_name)
        return

    name = _as_str(data.get("name"))
    description = _as_str(data.get("description"))

    if not name:
        # 有 title / summary 属于「用非标准字段替代 name」，否则「缺 name」。
        if data.get("title") is not None or data.get("summary") is not None:
            result["nonstandard_name_field"].append(dir_name)
        else:
            result["missing_name"].append(dir_name)
    else:
        if name != dir_name:
            result["name_mismatch"].append({"skill": dir_name, "declared": name})

    if not description:
        result["missing_description"].append(dir_name)
    elif len(description) > DESCRIPTION_MAX_LEN:
        result["overlong_description"].append({"skill": dir_name, "length": len(description)})


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        return ""
    return value.strip()


def format_frontmatter_report(audit: Dict[str, Any]) -> str:
    """把 frontmatter 审计结果格式化为控制台可读文本。"""
    total = audit.get("total_skills", 0)
    problems = audit.get("problems", 0)
    warnings = audit.get("warnings", 0)

    lines: List[str] = []
    lines.append("=" * 60)
    lines.append("  SKILL.md frontmatter 契约审计")
    lines.append("=" * 60)
    if total == 0:
        lines.append("  （无技能目录或目录不存在）")
        return "\n".join(lines)

    lines.append(f"  审计技能数: {total}")
    lines.append(f"  契约问题: {problems} · 警告: {warnings}")

    if audit.get("skipped_aliases"):
        lines.append(f"  跳过别名（symlink）: {', '.join(audit['skipped_aliases'])}")

    _append_list(lines, "❌ 缺 SKILL.md", audit.get("missing_skillmd"))
    _append_list(lines, "❌ 缺 frontmatter 块（或未闭合）", audit.get("missing_frontmatter"))
    _append_list(lines, "❌ frontmatter 解析失败", audit.get("unparsable"))
    _append_list(lines, "❌ 缺 name 字段", audit.get("missing_name"))
    _append_list(lines, "❌ 用 title/summary 替代 name", audit.get("nonstandard_name_field"))
    _append_list(lines, "❌ 缺 description 字段", audit.get("missing_description"))

    if audit.get("name_mismatch"):
        lines.append("  ⚠️  name 与目录名不符（警告）:")
        for row in audit["name_mismatch"]:
            lines.append(f"     - {row.get('skill')}: 声明为 {row.get('declared')!r}")
    if audit.get("overlong_description"):
        lines.append("  ⚠️  description 超长（警告）:")
        for row in audit["overlong_description"]:
            lines.append(f"     - {row.get('skill')}: {row.get('length')} 字符")

    return "\n".join(lines)


def format_frontmatter_markdown(audit: Dict[str, Any]) -> str:
    """把 frontmatter 审计结果格式化为 Markdown（嵌进 --report）。"""
    total = audit.get("total_skills", 0)
    problems = audit.get("problems", 0)
    warnings = audit.get("warnings", 0)

    lines: List[str] = []
    lines.append("## SKILL.md frontmatter 契约审计\n")
    if total == 0:
        lines.append("（无技能目录或目录不存在）\n")
        return "\n".join(lines)
    lines.append(f"- 审计技能数: **{total}** · 契约问题: **{problems}** · 警告: **{warnings}**\n")
    if audit.get("skipped_aliases"):
        lines.append(f"- 跳过别名（symlink）: {', '.join('`' + s + '`' for s in audit['skipped_aliases'])}\n")

    _append_list_md(lines, "- ❌ 缺 SKILL.md", audit.get("missing_skillmd"))
    _append_list_md(lines, "- ❌ 缺 frontmatter 块（或未闭合）", audit.get("missing_frontmatter"))
    _append_list_md(lines, "- ❌ frontmatter 解析失败", audit.get("unparsable"))
    _append_list_md(lines, "- ❌ 缺 name 字段", audit.get("missing_name"))
    _append_list_md(lines, "- ❌ 用 title/summary 替代 name", audit.get("nonstandard_name_field"))
    _append_list_md(lines, "- ❌ 缺 description 字段", audit.get("missing_description"))

    if audit.get("name_mismatch"):
        lines.append("- ⚠️ name 与目录名不符（警告）:")
        for row in audit["name_mismatch"]:
            lines.append(f"  - `{row.get('skill')}`: 声明为 `{row.get('declared')}`")
    if audit.get("overlong_description"):
        lines.append("- ⚠️ description 超长（警告）:")
        for row in audit["overlong_description"]:
            lines.append(f"  - `{row.get('skill')}`: {row.get('length')} 字符")
    return "\n".join(lines)


def _append_list(lines: List[str], title: str, items: List[Any]) -> None:
    if not items:
        return
    if len(items) <= 8:
        lines.append(f"  {title}: {', '.join(items)}")
    else:
        lines.append(f"  {title}: {len(items)} 个（{', '.join(items[:8])}...）")


def _append_list_md(lines: List[str], title: str, items: List[Any]) -> None:
    if not items:
        return
    names = ", ".join("`" + str(s) + "`" for s in items)
    lines.append(f"{title}: {names}")
