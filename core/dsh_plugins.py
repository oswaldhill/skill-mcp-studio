"""DSH（DeepSeek Harness）插件清单：只读扫描。

**为什么单独成模块**：DSH 的插件不是本工具自己那套「技能 + MCP」模型，而是
cordis 载入器的 bundle 体系。它的真相分散在三个地方，只看一个都会得出错误结论：

| 位置 | 提供什么 | 只看它的后果 |
|---|---|---|
| `<profile>/package.json` 的 `dependencies` | 装了什么（含 `link:` 本地路径） | 会以为「装了 = 在用」 |
| 同一文件的 `dsh.profile.bundles` | **启用清单**（有序，决定载入顺序） | 会漏掉「装了但没启用」 |
| `<profile>/cordis.patch.yml` | 补丁层（id 定向覆盖 / 禁用 / 插入） | 会漏掉「启用了但被 patch 禁掉」 |

因此本模块把三者合起来判一个插件的真实状态：**已启用 / 已装未启用 / 来源失效**。

## 安全纪律（重要）

`cordis.patch.yml` 的 `config` 段里**会有明文 apiKey**（本机实测：vision 插件的
`apiKey: sk-...` 就写在里面）。因此本模块：

- **只读**：不改任何 DSH 文件，不执行 `pnpm install`、不碰 lock 文件；
- **绝不回显 config 值**：只统计「有几个 patch 条目 / 其中几个是 disable」，
  键名与参数值一概不出现。`secrets_redacted=True` 是给调用方的显式承诺，
  由 `tests/test_dsh_plugins.py` 守着（构造含 apiKey 的样本，断言输出里没有它）。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

# DSH 的 profile 根目录（可用环境变量覆盖，便于测试与跨平台）
DSH_HOME_ENV = "DSH_HOME"
DEFAULT_DSH_HOME = "~/.dsh"

# ``profiles/`` 下与 profile 同级、但不是 profile 的目录。``node_modules`` 是
# pnpm 的工作区依赖树，**不是** profile —— 把它当 profile 扫会产出一个 0 插件的
# 假条目，让「共 N 个 profile」这个数字虚高（实测踩过）。
NON_PROFILE_DIRS = frozenset({"node_modules", "__pycache__"})

# cordis 内置 bundle 的包名前缀：这些随 DSH 本体分发，不是用户插件
BUILTIN_SCOPE = "@deepseek-ai/"


def dsh_home() -> str:
    """DSH 配置根目录（默认 ``~/.dsh``）。"""
    raw = os.environ.get(DSH_HOME_ENV) or DEFAULT_DSH_HOME
    return os.path.expanduser(raw)


def profiles_dir() -> str:
    return os.path.join(dsh_home(), "profiles")


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _patch_stats(path: str) -> Dict[str, Any]:
    """只统计 patch 层结构，**不读取也不回显任何 config 值**。

    不解析 YAML 语义，只做行级结构识别：够用（判断有没有 disable / insert），
    且天然不会把 config 内容带进内存再漏出去。
    """
    stats = {"exists": False, "entries": 0, "disables": 0, "inserts": 0}
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return stats
    stats["exists"] = True
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # 顶层数组项：顶格以 "- " 开头。**不能只认带 id: 的行**——`- insert:`
        # 同样是 patch 条目（只是内容是一个插入列表），漏掉它会让「条目数」
        # 少算，用户据此判断「补丁层有几个改动」就会错。
        if line.startswith("- "):
            stats["entries"] += 1
        if "disabled: true" in stripped or "disable: true" in stripped:
            stats["disables"] += 1
        if stripped.startswith("insert:") or stripped == "- insert:":
            stats["inserts"] += 1
    return stats


def _installed_version(profile_dir: str, name: str) -> Optional[str]:
    """从 profile 的 node_modules 读插件实际版本（不存在则 None）。"""
    pkg = os.path.join(profile_dir, "node_modules", name, "package.json")
    meta = _read_json(pkg)
    if meta is None:
        return None
    version = meta.get("version")
    return str(version) if version else None


def _linked_path(profile_dir: str, spec: str) -> Optional[str]:
    """``link:/abs/path`` 依赖 → 绝对路径（相对路径按 profile 目录解析）。"""
    if not spec.startswith("link:"):
        return None
    raw = spec[len("link:"):].strip()
    if not raw:
        return None
    if not os.path.isabs(raw):
        raw = os.path.join(profile_dir, raw)
    return os.path.normpath(raw)


def classify_plugin(
    name: str,
    *,
    spec: Optional[str],
    enabled: bool,
    version: Optional[str],
) -> Dict[str, Any]:
    """把一个插件判成 (kind, state)。

    kind：
    - ``builtin``：``@deepseek-ai/*``，随 DSH 本体分发；
    - ``local``：``link:`` 依赖，指向本地源码目录（开发者自己写的插件）；
    - ``registry``：来自 npm 的第三方插件。

    state：
    - ``enabled``：在 ``dsh.profile.bundles`` 里；
    - ``installed``：装了但没启用（真实但常被忽略的状态）；
    - ``broken``：``node_modules`` 里没有该包（且非 ``builtin``），即声明了却没落地，
      DSH 载入会失败。另有一条补充判据在 :func:`scan_profile`：``link:`` 依赖的目标
      目录不存在时也置 ``broken``（源码删了但 node_modules 还留着旧副本，此时 version
      读得到，必须单独判）。两条并存才是「载入会失败」的完整判据。
    """
    if name.startswith(BUILTIN_SCOPE):
        kind = "builtin"
    elif spec and spec.startswith("link:"):
        kind = "local"
    else:
        kind = "registry"
    if version is None and kind != "builtin":
        # 连 node_modules 里都没有 → 装了却没落地（pnpm install 没跑过 / 目标失效）
        state = "broken"
    elif enabled:
        state = "enabled"
    else:
        state = "installed"
    return {"kind": kind, "state": state}


def scan_profile(profile_dir: str) -> Dict[str, Any]:
    """扫一个 profile，返回其中的插件清单与 patch 层结构。"""
    name = os.path.basename(profile_dir)
    manifest = _read_json(os.path.join(profile_dir, "package.json")) or {}
    deps = manifest.get("dependencies") or {}
    if not isinstance(deps, dict):
        deps = {}
    dsh_section = manifest.get("dsh") or {}
    profile_section = (dsh_section or {}).get("profile") or {}
    bundles = profile_section.get("bundles") or []
    if not isinstance(bundles, list):
        bundles = []
    bundles = [str(b) for b in bundles]

    patch = _patch_stats(os.path.join(profile_dir, "cordis.patch.yml"))

    plugins: List[Dict[str, Any]] = []
    seen = set()
    # 先列 bundles（启用清单的顺序就是载入顺序，必须保住），再补「装了没启用」的
    ordered = bundles + [d for d in deps if d not in bundles]
    for pkg_name in ordered:
        if pkg_name in seen:
            continue
        seen.add(pkg_name)
        spec = deps.get(pkg_name)
        enabled = pkg_name in bundles
        linked = _linked_path(profile_dir, spec) if isinstance(spec, str) else None
        target_missing = bool(linked and not os.path.isdir(linked))
        version = _installed_version(profile_dir, pkg_name)
        info = classify_plugin(pkg_name, spec=spec, enabled=enabled, version=version)
        if target_missing:
            info["state"] = "broken"
        plugins.append({
            "name": pkg_name,
            "kind": info["kind"],
            "state": info["state"],
            "enabled": enabled,
            "version": version,
            "spec": spec if isinstance(spec, str) else None,
            "source_path": linked,
            "patch_file": os.path.join(profile_dir, "cordis.patch.yml"),
        })

    return {
        "name": name,
        "path": profile_dir,
        "plugin_count": len(plugins),
        "enabled_count": sum(1 for p in plugins if p["state"] == "enabled"),
        "broken_count": sum(1 for p in plugins if p["state"] == "broken"),
        "installed_only_count": sum(1 for p in plugins if p["state"] == "installed"),
        "patch": patch,
        "plugins": plugins,
    }


def scan(dsh_home_dir: Optional[str] = None) -> Dict[str, Any]:
    """扫全部 profile，产出「DSH 插件」页所需的完整数据（只读）。"""
    root = os.path.expanduser(dsh_home_dir) if dsh_home_dir else profiles_dir()
    result: Dict[str, Any] = {
        "kind": "dsh-plugins",
        "dsh_home": os.path.dirname(root) if root.endswith("profiles") else root,
        "profiles_dir": root,
        "secrets_redacted": True,   # 显式承诺：patch 层的 config 值永不回显
        "profiles": [],
        "summary": {"profiles": 0, "plugins": 0, "enabled": 0,
                    "broken": 0, "installed_only": 0},
        "reason": "",
    }
    if not os.path.isdir(root):
        result["reason"] = f"未找到 DSH profile 目录：{root}（未安装 DSH 或路径不同）"
        return result

    names = sorted(
        n for n in os.listdir(root)
        if os.path.isdir(os.path.join(root, n))
        and not n.startswith(".")
        and n not in NON_PROFILE_DIRS
    )
    profiles = [scan_profile(os.path.join(root, n)) for n in names]
    result["profiles"] = profiles
    result["summary"] = {
        "profiles": len(profiles),
        "plugins": sum(p["plugin_count"] for p in profiles),
        "enabled": sum(p["enabled_count"] for p in profiles),
        "broken": sum(p["broken_count"] for p in profiles),
        "installed_only": sum(p["installed_only_count"] for p in profiles),
    }
    if not profiles:
        result["reason"] = f"{root} 下没有 profile 目录"
    return result
