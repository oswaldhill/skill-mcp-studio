"""
Skill 全网版本检查模块
功能：
1. 从 SKILL.md frontmatter 解析 version / homepage / source_url 等元数据
2. 多源检查最新版本：
   a. WorkBuddy Marketplace（本地 marketplace 目录）
   b. GitHub API（有 GitHub homepage/repo 的 skill）
   c. skills-lock.json hash 对比（well-known source）
3. 输出当前版本 vs 最新版本，支持交互式更新
"""

import os
import re
import json
import subprocess
import hashlib
from typing import Dict, Any, Optional, Tuple


# ============================================================
# SKILL.md frontmatter 解析
# ============================================================

def parse_frontmatter(skill_dir: str) -> Dict[str, Any]:
    """
    解析 SKILL.md 的 YAML frontmatter，提取 version / homepage / source_url 等。
    不依赖 PyYAML，用简单正则解析顶层字段。
    """
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(skill_md):
        return {}

    # 单个 SKILL.md 读不了（权限 / 非 UTF-8 编码）不应中断整轮版本检查：
    # 此前这里无任何保护，一个 GBK 编码的 SKILL.md 会让 check_all_versions
    # 的整个循环抛 UnicodeDecodeError 中断，其余技能一个都查不到。
    try:
        with open(skill_md, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return {}

    # 提取 frontmatter 块
    m = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not m:
        return {}

    fm_text = m.group(1)
    result = {}

    # 提取简单 key: value 字段
    for key in ["name", "version", "homepage", "source_url", "repository", "author", "license"]:
        km = re.search(rf'^{key}:\s*(.+)$', fm_text, re.MULTILINE)
        if km:
            val = km.group(1).strip().strip('"').strip("'")
            result[key] = val

    # 提取 metadata.hermes.homepage
    hm = re.search(r'homepage:\s*(https?://\S+)', fm_text)
    if hm and "homepage" not in result:
        result["homepage"] = hm.group(1)

    return result


# ============================================================
# 来源检测：确定每个 skill 的来源类型
# ============================================================

def detect_source(skill_name: str, skill_dir: str, lock_data: Dict, marketplace_dir: str) -> Dict[str, Any]:
    """
    检测 skill 的来源类型和标识。

    Returns:
        dict: {
            "source_type": "marketplace" | "github" | "well-known" | "unknown",
            "source_id": str,  # marketplace name / github repo / well-known source
            "local_version": str,
            "homepage": str,
        }
    """
    fm = parse_frontmatter(skill_dir)
    local_version = fm.get("version", "")
    homepage = fm.get("homepage", "")

    # 1) 检查是否在 marketplace 中
    marketplace_path = os.path.join(marketplace_dir, skill_name)
    if os.path.isdir(marketplace_path):
        return {
            "source_type": "marketplace",
            "source_id": marketplace_path,
            "local_version": local_version,
            "homepage": homepage,
        }

    # 2) 检查是否在 skills-lock.json 中
    if skill_name in lock_data.get("skills", {}):
        lock_entry = lock_data["skills"][skill_name]
        return {
            "source_type": "well-known",
            "source_id": lock_entry.get("source", ""),
            "local_version": local_version,
            "homepage": homepage,
            "lock_hash": lock_entry.get("computedHash", ""),
        }

    # 3) 检查是否有 GitHub homepage
    github_pattern = re.compile(r'github\.com/([^/]+/[^/#]+)')
    if homepage:
        gm = github_pattern.search(homepage)
        if gm:
            return {
                "source_type": "github",
                "source_id": gm.group(1).rstrip(".git"),
                "local_version": local_version,
                "homepage": homepage,
            }

    # 4) 检查 metadata 中的 repository 字段
    repo = fm.get("repository", "") or fm.get("source_url", "")
    if repo:
        gm = github_pattern.search(repo)
        if gm:
            return {
                "source_type": "github",
                "source_id": gm.group(1).rstrip(".git"),
                "local_version": local_version,
                "homepage": repo,
            }

    return {
        "source_type": "unknown",
        "source_id": "",
        "local_version": local_version,
        "homepage": homepage,
    }


# ============================================================
# 版本检查：各来源的最新版本
# ============================================================

def get_marketplace_version(marketplace_path: str) -> str:
    """从 marketplace 的 SKILL.md 读取版本号"""
    fm = parse_frontmatter(marketplace_path)
    return fm.get("version", "")


def get_github_latest_version(repo: str) -> Optional[str]:
    """
    通过 GitHub API 获取仓库的最新 release 或 tag。
    返回版本号字符串，失败返回 None。
    """
    repo = repo.rstrip("/")
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"

    try:
        result = subprocess.run(
            ["curl", "-s", "-m", "10", "-H", "Accept: application/vnd.github.v3+json", api_url],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            tag = data.get("tag_name", "")
            if tag:
                # 去掉 v 前缀
                return tag.lstrip("v")
    except (subprocess.SubprocessError, FileNotFoundError, ValueError):
        # D-9: 网络/binary/json 失败均按「未知最新版本」降级，不再裸吞任意异常。
        pass

    # fallback: 尝试 tags
    try:
        tags_url = f"https://api.github.com/repos/{repo}/tags?per_page=1"
        result = subprocess.run(
            ["curl", "-s", "-m", "10", "-H", "Accept: application/vnd.github.v3+json", tags_url],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, list) and len(data) > 0:
                tag = data[0].get("name", "")
                return tag.lstrip("v") if tag else None
    except (subprocess.SubprocessError, FileNotFoundError, ValueError):
        pass

    return None


def compute_skill_hash(skill_dir: str) -> str:
    """
    计算 skill 目录内容的 SHA256 hash（与 skills-lock.json 的 computedHash 对比）。
    只 hash SKILL.md 和 references/ 目录下的文件。
    """
    hasher = hashlib.sha256()
    files_to_hash = []

    # SKILL.md
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if os.path.exists(skill_md):
        files_to_hash.append(skill_md)

    # references/ 目录
    refs_dir = os.path.join(skill_dir, "references")
    if os.path.isdir(refs_dir):
        for root, dirs, files in os.walk(refs_dir):
            for f in sorted(files):
                files_to_hash.append(os.path.join(root, f))

    for fpath in sorted(files_to_hash):
        try:
            with open(fpath, "rb") as f:
                hasher.update(f.read())
        except Exception:
            pass

    return hasher.hexdigest()


def check_well_known_version(skill_name: str, skill_dir: str, lock_entry: Dict) -> Dict[str, str]:
    """
    对 well-known source 的 skill，对比本地 hash 和 lock 中记录的 hash。
    如果 hash 不同，说明本地有修改（可能是更新也可能是自定义修改）。
    """
    local_hash = compute_skill_hash(skill_dir)
    lock_hash = lock_entry.get("computedHash", "")

    return {
        "local_hash": local_hash[:12],
        "lock_hash": lock_hash[:12],
        "hash_match": local_hash == lock_hash,
    }


# ============================================================
# 版本号比较
# ============================================================

def parse_version(v: str) -> Tuple:
    """将版本号字符串解析为可比较的 tuple"""
    if not v:
        return (0,)
    # 去掉 v 前缀
    v = v.lstrip("v")
    parts = []
    for p in re.split(r'[.\-]', v):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def is_newer(remote: str, local: str) -> bool:
    """判断 remote 版本是否比 local 更新"""
    if not remote:
        return False
    if not local:
        return True  # 本地无版本号，视为有更新
    return parse_version(remote) > parse_version(local)


# ============================================================
# 主检查流程
# ============================================================

def check_all_versions(unified_dir: str) -> Dict[str, Any]:
    """
    检查所有 skill 的全网最新版本。

    Returns:
        dict: {
            "total": int,
            "checked": int,
            "updatable": int,
            "up_to_date": int,
            "unknown_source": int,
            "skills": [
                {
                    "name": str,
                    "source_type": str,
                    "local_version": str,
                    "latest_version": str,
                    "has_update": bool,
                    "detail": str,
                }
            ]
        }
    """
    expanded = os.path.expanduser(unified_dir)
    marketplace_dir = os.path.expanduser("~/.workbuddy/skills-marketplace/skills")

    # 加载 skills-lock.json
    lock_path = os.path.join(expanded, "skills-lock.json")
    lock_data = {}
    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r", encoding="utf-8") as f:
                lock_data = json.load(f)
        except Exception:
            pass

    # 遍历所有 skill
    skills = []
    updatable = 0
    git_updatable = 0  # 可通过 git pull 自动更新的 skill 数
    up_to_date = 0
    unknown_source = 0
    checked = 0

    try:
        entries = sorted(os.listdir(expanded))
    except PermissionError:
        return {"total": 0, "checked": 0, "updatable": 0, "git_updatable": 0, "up_to_date": 0, "unknown_source": 0, "skills": []}

    for name in entries:
        if name.startswith("."):
            continue
        skill_dir = os.path.join(expanded, name)
        if not os.path.isdir(skill_dir):
            continue

        source_info = detect_source(name, skill_dir, lock_data, marketplace_dir)
        source_type = source_info["source_type"]
        local_ver = source_info["local_version"]
        latest_ver = ""
        has_update = False
        detail = ""

        if source_type == "marketplace":
            checked += 1
            latest_ver = get_marketplace_version(source_info["source_id"])
            if is_newer(latest_ver, local_ver):
                has_update = True
                updatable += 1
                detail = f"Marketplace 有更新: {local_ver or '无'} → {latest_ver}"
            elif local_ver and latest_ver and local_ver != latest_ver:
                # 本地版本比 marketplace 新（可能是自定义修改）
                detail = f"本地版本更新: {local_ver} (marketplace: {latest_ver})"
                up_to_date += 1
            else:
                detail = f"已是最新 ({local_ver or '无版本号'})"
                up_to_date += 1

        elif source_type == "github":
            checked += 1
            github_ver = get_github_latest_version(source_info["source_id"])
            if github_ver:
                latest_ver = github_ver
                if is_newer(latest_ver, local_ver):
                    has_update = True
                    updatable += 1
                    detail = f"GitHub 有更新: {local_ver or '无'} → {latest_ver}"
                else:
                    detail = f"已是最新 ({local_ver or latest_ver})"
                    up_to_date += 1
            else:
                detail = f"GitHub 无 release/tag ({source_info['source_id']})"
                unknown_source += 1

        elif source_type == "well-known":
            checked += 1
            hash_info = check_well_known_version(name, skill_dir, lock_data["skills"][name])
            if hash_info["hash_match"]:
                detail = f"hash 一致 ({hash_info['local_hash']})"
                up_to_date += 1
            else:
                detail = f"hash 不匹配 (本地: {hash_info['local_hash']}, 记录: {hash_info['lock_hash']})"
                has_update = True
                updatable += 1
            latest_ver = "hash-check"

        else:
            unknown_source += 1
            detail = "未知来源，无法检查"

        # 判断是否可通过 git pull 自动更新
        # well-known (hash) 来源的 skill 在 git 仓库中，可以自动更新
        # marketplace / github 来源需要手动操作
        can_auto_update = (has_update and source_type == "well-known")
        if can_auto_update:
            git_updatable += 1

        skills.append({
            "name": name,
            "source_type": source_type,
            "local_version": local_ver,
            "latest_version": latest_ver,
            "has_update": has_update,
            "detail": detail,
            "source_id": source_info.get("source_id", ""),
            "can_auto_update": can_auto_update,
        })

    return {
        "total": len(skills),
        "checked": checked,
        "updatable": updatable,
        "git_updatable": git_updatable,
        "up_to_date": up_to_date,
        "unknown_source": unknown_source,
        "skills": skills,
    }


# ============================================================
# 报告格式化
# ============================================================

def format_version_report(result: Dict[str, Any]) -> str:
    """格式化版本检查报告"""
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("  Skill 全网版本检查报告")
    lines.append("=" * 80)
    lines.append("")

    total = result["total"]
    checked = result["checked"]
    updatable = result["updatable"]
    git_updatable = result.get("git_updatable", 0)
    up_to_date = result["up_to_date"]
    unknown = result["unknown_source"]

    lines.append(f"  📊 总计 {total} 个 skill:")
    lines.append(f"     ├─ 🔍 已检查: {checked}")
    lines.append(f"     ├─ ✅ 已是最新: {up_to_date}")
    lines.append(f"     ├─ 🔄 可更新:   {updatable}（其中 {git_updatable} 个可自动更新）")
    lines.append(f"     └─ ❓ 未知来源: {unknown}")
    lines.append("")

    # 可更新的 skill
    updatable_skills = [s for s in result["skills"] if s["has_update"]]
    if updatable_skills:
        lines.append("  🔄 以下 skill 有可用更新:")
        lines.append("")
        lines.append(f"  {'Skill':<35} {'本地版本':<14} {'最新版本':<14} {'来源':<14} {'方式':<8} {'详情'}")
        lines.append("  " + "-" * 100)
        for s in updatable_skills:
            lv = s["local_version"] or "(无)"
            rv = s["latest_version"] or "(无)"
            st = s["source_type"]
            auto = "🔄自动" if s.get("can_auto_update") else "🖐️手动"
            detail = s["detail"]
            if len(detail) > 28:
                detail = detail[:25] + "..."
            lines.append(f"  {s['name']:<35} {lv:<14} {rv:<14} {st:<14} {auto:<8} {detail}")
        lines.append("")

    # 未知来源的 skill（仅列出前 10 个）
    unknown_skills = [s for s in result["skills"] if s["source_type"] == "unknown"]
    if unknown_skills:
        lines.append(f"  ❓ {len(unknown_skills)} 个 skill 来源未知，无法检查更新:")
        names = [s["name"] for s in unknown_skills]
        for i in range(0, min(len(names), 15), 8):
            lines.append(f"     {', '.join(names[i:i+8])}")
        if len(names) > 15:
            lines.append(f"     ... 还有 {len(names) - 15} 个")
        lines.append("")

    # 操作建议
    if updatable > 0:
        lines.append("  💡 操作建议:")
        if git_updatable > 0:
            lines.append(f"     {git_updatable} 个 skill 可通过 git pull 自动更新")
        manual_count = updatable - git_updatable
        if manual_count > 0:
            lines.append(f"     {manual_count} 个 skill 需手动更新（marketplace/GitHub 来源）")
        lines.append("")
    elif updatable == 0 and checked > 0:
        lines.append("  ✅ 所有已检查的 skill 均已是最新版本！")
        lines.append("")

    lines.append("=" * 80)
    return "\n".join(lines)


def format_version_report_markdown(result: Dict[str, Any]) -> str:
    """Markdown 格式的版本检查报告"""
    lines = []
    lines.append("## 🔄 Skill 全网版本检查\n")

    lines.append(f"- 总计: **{result['total']}** 个 skill")
    lines.append(f"- 已检查: **{result['checked']}**")
    lines.append(f"- 已是最新: **{result['up_to_date']}**")
    lines.append(f"- 可更新: **{result['updatable']}**")
    lines.append(f"- 未知来源: **{result['unknown_source']}**\n")

    updatable_skills = [s for s in result["skills"] if s["has_update"]]
    if updatable_skills:
        lines.append("### 可更新的 Skill\n")
        lines.append("| Skill | 本地版本 | 最新版本 | 来源 | 详情 |")
        lines.append("|-------|---------|---------|------|------|")
        for s in updatable_skills:
            lv = s["local_version"] or "(无)"
            rv = s["latest_version"] or "(无)"
            lines.append(f"| {s['name']} | {lv} | {rv} | {s['source_type']} | {s['detail']} |")
        lines.append("")

    return "\n".join(lines)
