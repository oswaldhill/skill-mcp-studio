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
    print(f"  已写入: {VERSION_PATH.name}, src-tauri/tauri.conf.json, src-tauri/Cargo.toml")
    return 0


if __name__ == "__main__":
    sys.exit(main())