#!/usr/bin/env python3
"""版本升级脚本 —— skill-mcp-studio 构建前必跑。

维护仓库根 ``version.json``（单源真相）的两种版本格式，并同步到打包产物：

- ``version``  — ``X.Y.Z`` 语义化版本：每次发布按常规软件升级规则升级
  （patch=修复 / minor=功能 / major=不兼容变更）。
- ``build``    — 数字格式构建号：**每次构建必增**（monotonic，永不回落）。

用法::

    scripts/bump_version.py                 # 按 git 提交类型自动推断 patch/minor/major
    scripts/bump_version.py --bump patch    # 显式指定
    scripts/bump_version.py --bump minor
    scripts/bump_version.py --bump major
    scripts/bump_version.py --dry-run       # 只预览，不落盘

同步目标:
    * version.json                    （单源真相）
    * src-tauri/tauri.conf.json       （Tauri 打包 version）
    * src-tauri/Cargo.toml            （Rust 侧 version）
    * src-tauri/Cargo.lock            （本应用自身 package 的 version）
    * pyproject.toml                  （pip 打包元数据 version）
    * README.md / SECURITY.md         （版本 badge 与「当前版本」表述）
    * gui/dashboard.html              （浏览器预览态的版本兜底）
    * skill-mcp-studio-architecture.svg（架构图版本标注）
    * .github/ISSUE_TEMPLATE/bug_report.md（版本示例）
    * CHANGELOG.md                    （链接块：Unreleased 比较基准 + 版本链接）

CHANGELOG 的**正文段落**（``## [vX.Y.Z]``）仍由人工撰写：脚本只在缺失时提醒，
不会自动生成变更内容。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATH = ROOT / "version.json"
TAURI_CONF = ROOT / "src-tauri" / "tauri.conf.json"
CARGO_TOML = ROOT / "src-tauri" / "Cargo.toml"
PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"


def load() -> dict:
    if VERSION_PATH.exists():
        try:
            data = json.loads(VERSION_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}
    version = data.get("version", "0.0.0")
    build = data.get("build", 0)
    return {"version": version, "build": int(build) if str(build).isdigit() else 0}


def infer_kind(version: str) -> str:
    """从上次 tag 之后的 conventional commit 类型推断升级幅度。

    规则（常规软件升级规范）:
    - 有 breaking change / ``!`` / ``BREAKING CHANGE`` → major
    - 有 feat → minor
    - 其余（fix/docs/chore/refactor/... 或无提交）→ patch
    """
    try:
        out = subprocess.run(
            ["git", "log", "--pretty=%s", "--no-merges"],
            cwd=ROOT, capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return "patch"
    lines = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    if any("breaking change" in ln.lower() or ln.rstrip().endswith("!") for ln in lines):
        return "major"
    if any(re.match(r"^(feat|feature)", ln, re.IGNORECASE) for ln in lines):
        return "minor"
    return "patch"


def bump_semver(version: str, kind: str) -> str:
    parts = re.split(r"[.\-]", version)
    try:
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError):
        major, minor, patch = 0, 0, 0
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def sync_tauri(version: str) -> None:
    if TAURI_CONF.exists():
        txt = TAURI_CONF.read_text(encoding="utf-8")
        txt = re.sub(r'"version"\s*:\s*"[^"]*"', f'"version": "{version}"', txt, count=1)
        TAURI_CONF.write_text(txt, encoding="utf-8")
    if CARGO_TOML.exists():
        txt = CARGO_TOML.read_text(encoding="utf-8")
        txt = re.sub(r'^version\s*=\s*"[^"]*"', f'version = "{version}"', txt, count=1, flags=re.MULTILINE)
        CARGO_TOML.write_text(txt, encoding="utf-8")
    # Cargo.lock 中本应用自身 package 的 version 同步（避免 locks 与 manifest 漂移）
    lock = ROOT / "src-tauri" / "Cargo.lock"
    if lock.exists():
        txt = lock.read_text(encoding="utf-8")
        # 只替换 [[package]] 块中 name == "skill-mcp-studio" 后的 version 行
        pattern = re.compile(r'(name\s*=\s*"skill-mcp-studio"\s*\nversion\s*=\s*")[^"]*(")')
        txt = pattern.sub(lambda m: m.group(1) + version + m.group(2), txt, count=1)
        lock.write_text(txt, encoding="utf-8")


def _sub_once(path: Path, pattern: str, repl, label: str) -> bool:
    """对单个文件做一次正则替换；未命中时告警但不中断（格式可能已演进）。

    ``repl`` 与 ``re.subn`` 一致：字符串或可调用对象。
    """
    rel = path.relative_to(ROOT)
    if not path.exists():
        print(f"  [跳过] {label}: 文件不存在（{rel}）")
        return False
    txt = path.read_text(encoding="utf-8")
    new_txt, hits = re.subn(pattern, repl, txt, count=1)
    if hits == 0:
        print(f"  [警告] {label}: 未匹配到版本引用，请检查 {rel} 的格式是否变化")
        return False
    path.write_text(new_txt, encoding="utf-8")
    return True


def sync_docs(version: str, build: int) -> None:
    """同步文档与控制台预览兜底里的版本引用。

    这些位置不在 ``version.json`` 的写入链上，历史上每次发版都会漏改（README
    badge、SECURITY「当前版本」、架构图、浏览器预览兜底、Issue 模板示例、
    CHANGELOG 链接块），导致文档版本与单源真相互相漂移，故一并纳入本脚本。

    CHANGELOG 只做机械的链接块同步，正文段落留给人工——脚本发现缺段落时提醒。
    """
    # 控制台浏览器预览的静态兜底（无桌面壳时页脚显示它）
    _sub_once(
        ROOT / "gui" / "dashboard.html",
        r'(app: \{ name: "Skill MCP Studio", version: ")[^"]*(",\s*build: )\d+'
        r'(,\s*build_number: )\d+(,\s*semver_ok: true, full: ")[^"]*(")',
        lambda m: (
            f"{m.group(1)}{version}{m.group(2)}{build}"
            f"{m.group(3)}{build}{m.group(4)}v{version} (build {build}){m.group(5)}"
        ),
        "控制台预览兜底",
    )
    _sub_once(
        ROOT / "README.md",
        r"(badge/version-v)\d+\.\d+\.\d+(-blue)",
        rf"\g<1>{version}\g<2>",
        "README 版本 badge",
    )
    _sub_once(
        ROOT / "README.md",
        r"(badge/build-)\d+(-lightgrey)",
        rf"\g<1>{build}\g<2>",
        "README 构建号 badge",
    )
    _sub_once(
        ROOT / "README.md",
        r"(如 `v)\d+\.\d+\.\d+(`)",
        rf"\g<1>{version}\g<2>",
        "README tag 示例",
    )
    _sub_once(
        ROOT / "SECURITY.md",
        r"(仅支持最新发布版本（当前 `v)\d+\.\d+\.\d+(`）)",
        rf"\g<1>{version}\g<2>",
        "SECURITY 当前版本",
    )
    _sub_once(
        ROOT / "skill-mcp-studio-architecture.svg",
        r"(>v)\d+\.\d+\.\d+( \(build )\d+(\))",
        rf"\g<1>{version}\g<2>{build}\g<3>",
        "架构图版本标注",
    )
    _sub_once(
        ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.md",
        r"(如 `v)\d+\.\d+\.\d+( build )\d+(`)",
        rf"\g<1>{version}\g<2>{build}\g<3>",
        "Issue 模板版本示例",
    )

    # CHANGELOG 链接块：Unreleased 比较基准前移 + 补新版本链接
    changelog = ROOT / "CHANGELOG.md"
    _sub_once(
        changelog,
        r"(\[Unreleased\]:\s*\S*?/compare/v)\d+\.\d+\.\d+(\.\.\.HEAD)",
        rf"\g<1>{version}\g<2>",
        "CHANGELOG Unreleased 比较基准",
    )
    if changelog.exists():
        txt = changelog.read_text(encoding="utf-8")
        if f"[v{version}]:" not in txt:
            txt, hits = re.subn(
                r"(\[Unreleased\]:[^\n]*\n)",
                lambda m: m.group(1)
                + f"[v{version}]: "
                + f"https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v{version}\n",
                txt,
                count=1,
            )
            if hits:
                changelog.write_text(txt, encoding="utf-8")
        if f"## [v{version}]" not in txt:
            print(f"  [提醒] CHANGELOG 缺少「## [v{version}]」正文段落，请人工补写")
def sync_pyproject(version: str) -> None:
    """pip 打包元数据 ``[project].version`` 同步（B-1/D-1 修复）。"""
    if not PYPROJECT.exists():
        return
    txt = PYPROJECT.read_text(encoding="utf-8")
    txt = re.sub(
        r'^version\s*=\s*"[^"]*"',
        f'version = "{version}"',
        txt, count=1, flags=re.MULTILINE,
    )
    PYPROJECT.write_text(txt, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="bump version (X.Y.Z) + build number")
    ap.add_argument("--bump", choices=["patch", "minor", "major"], default=None,
                    help="显式指定升级幅度；缺省按 git conventional commits 推断")
    ap.add_argument("--dry-run", action="store_true", help="只预览不落盘")
    args = ap.parse_args()

    cur = load()
    kind = args.bump or infer_kind(cur["version"])
    new_version = bump_semver(cur["version"], kind)
    new_build = cur["build"] + 1

    print(f"  版本升级: {cur['version']} -> {new_version}   ({kind})")
    print(f"  构建号:   {cur['build']} -> {new_build}   (每次构建必增)")

    if args.dry_run:
        print("  [dry-run] 未写入任何文件")
        return 0

    VERSION_PATH.write_text(
        json.dumps({"version": new_version, "build": new_build}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    sync_tauri(new_version)
    sync_docs(new_version, new_build)
    sync_pyproject(new_version)
    print(
        "  已写入: version.json, src-tauri/tauri.conf.json, src-tauri/Cargo.toml, "
        "src-tauri/Cargo.lock, pyproject.toml, 文档/预览层版本引用"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())