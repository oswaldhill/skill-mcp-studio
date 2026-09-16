"""App version / build-number source of truth (stage-5 设置页「关于」).

版本两种格式，单源真相存于仓库根 ``version.json``:

- ``version`` — ``X.Y.Z`` 语义化版本，每次发布按常规软件升级规则升级
  （patch=修复 / minor=功能 / major=不兼容变更），由 ``scripts/bump_version.py`` 维护；
- ``build`` — 数字格式构建号，**每次构建必增**（monotonic），同样由 bump 脚本维护。

其它模块只读本模块；绝不在此反写 version.json（避免多源真相漂移）。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_VERSION_PATH = os.path.join(_REPO_ROOT, "version.json")

_FALLBACK_VERSION = "0.0.0"


def _git_commit_count() -> int:
    """数字格式的兜底（version.json 缺失时）：git 提交计数，monotonic。"""
    try:
        import subprocess

        out = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=_REPO_ROOT, capture_output=True, text=True, timeout=5,
        )
        return int(out.stdout.strip())
    except Exception:
        return 0


def read_app_info() -> Dict[str, Any]:
    """读取当前版本信息。永不抛异常；缺失时给兜底值。"""
    data: Dict[str, Any] = {}
    try:
        with open(_VERSION_PATH, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:
        data = {}

    version = str(data.get("version", _FALLBACK_VERSION))
    try:
        build = int(data.get("build", 0))
    except (TypeError, ValueError):
        build = 0
    if build <= 0:
        build = _git_commit_count()

    # 校验 X.Y.Z 三段的合法性，非法则回落并保留原始文本供诊断
    parts = version.split(".")
    semver_ok = len(parts) == 3 and all(p.isdigit() for p in parts)
    return {
        "version": version,
        "semver_ok": semver_ok,
        "build": build,
        "build_number": build,
        "full": f"v{version} (build {build})" if semver_ok else f"{version} (build {build})",
    }


if __name__ == "__main__":  # pragma: no cover - ad-hoc 诊断
    import sys

    print(json.dumps(read_app_info(), ensure_ascii=False, indent=2))
    sys.exit(0)