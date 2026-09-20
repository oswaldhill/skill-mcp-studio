# MCP 条目删除与清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让管理台能删除 / 清理任意客户端的 MCP 条目（含「未纳管」），对「疑似客户端自带」条目做强化确认，并提供基于配置备份的一键回滚。

**Architecture:** 复用既有「备份 → 原子写 → 校验」安全链。把 `core/mcp_fixer.py` 里本质通用的 `_render_without_legacy` 泛化为 `_render_without_entries`（legacy 成为薄包装，输出逐字不变）。新增两个纯函数模块：`mcp_entry_risk`（高风险判定）与 `config_backups`（备份列出 / 还原）。新增编排模块 `mcp_entry_removal` 负责「分类 → 挑 key → 高风险门 → attached 声明同步 → 空声明拒绝 → 落盘」。CLI 暴露 4 个参数并支持 `--format json`；GUI 复用现有弹窗形态接入。

**Tech Stack:** Python 3（stdlib + PyYAML + 与 mcp_fixer 相同的 TOML 解析器）、unittest、Tauri 静态前端 `gui/dashboard.html`（原生 JS，无构建步骤）。

**设计依据:** `docs/design/详细设计文档-阶段五增量-MCP条目删除与清理.md`（下称「设计文档」）。

---

## Scope Check

本计划只覆盖设计文档 §9「明确不做」之外的单一子系统：MCP 条目的删除 / 清理 / 回滚。
不做条目的新增与修改，不做覆盖矩阵勾选挂载，不做跨客户端批量。故无需拆分为多个计划。

## 前置约定

- **测试文件头部固定写法**（仓库 34/35 个测试文件如此，勿改）：

  ```python
  import sys
  import unittest
  from pathlib import Path

  ROOT = Path(__file__).resolve().parents[1]
  sys.path.insert(0, str(ROOT / "core"))

  from <module> import <name>  # noqa: E402
  ```

  即：先把 `core/` 插进 `sys.path`，再**扁平导入**（如 `from mcp_entry_risk import
  is_high_risk_entry`），而非 `from core.X import ...`——后者依赖 pytest 注入仓库根到
  `sys.path`，单文件直接 `python3 tests/test_x.py` 跑会失败。
- `core/` 内部模块之间同样用扁平导入（如 `from tool_registry import expand_path`）。
- 测试运行：`python3 -m pytest tests/<file> -q`。**必须用 `python3`（`/usr/local/bin/python3`）**，`/usr/bin/python3` 缺 PyYAML。
- 提交信息沿用仓库风格：Conventional Commits + 中文描述。
- 六种配置格式的既有 fixture 在 `tests/test_mcp_fixer.py`（含 `tool(path)` / `EXPECTED` / `URL` 助手），本计划的任务 2、3、4 直接复用其形状，不要另创格式。

## File Structure

**Create：**

| 文件 | 职责 |
| --- | --- |
| `core/mcp_entry_risk.py` | 高风险判定 R1/R2/R3，纯函数、无 I/O |
| `core/config_backups.py` | 配置备份的列出与还原（含归属校验与解析校验） |
| `core/mcp_entry_removal.py` | 删除编排：分类挑 key、高风险门、attach 声明同步、空声明拒绝 |
| `tests/test_mcp_entry_risk.py` | 任务 1 测试 |
| `tests/test_config_backups.py` | 任务 3 测试 |
| `tests/test_mcp_entry_removal.py` | 任务 2 / 4 测试 |

**Modify：**

| 文件 | 改动 |
| --- | --- |
| `core/mcp_fixer.py` | `_render_without_legacy` → `_render_without_entries` + 薄包装；`remove_mcp_entries_tool` 通用原语；`remove_legacy_mcp_tool` 改薄包装；新增 `validate_config_text` |
| `core/management_snapshot.py:280-289` | inventory 每条补 `high_risk` / `risk_reason` |
| `scan.py` | 4 个新参数 + 路由（`--remove-legacy-mcp` 路由在 L1489）+ 4 个 `_run_*` 处理函数 |
| `gui/dashboard.html` | 第三列可点击、`showMcpClass` 增删除 / 批量 / 回滚、`showAgentDetail` 条目删除、`confirmTypedKeyModal`、分发器增 4 个 action |
| `README.md` | 命令速查补 4 个参数 |
| `docs/design/详细设计文档-阶段五增量-MCP条目删除与清理.md` | 状态由「设计已评审（待实施）」改为「已实施」 |

---

## Task 1: 高风险判定模块

**Files:**
- Create: `core/mcp_entry_risk.py`
- Test: `tests/test_mcp_entry_risk.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_mcp_entry_risk.py`：

```python
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from mcp_entry_risk import is_high_risk_entry  # noqa: E402


class HighRiskEntryTest(unittest.TestCase):
    """R1/R2/R3 各一例 + 真实反例（本机 2026-09-20 实测条目）。"""

    def setUp(self):
        # 注册表真实形状（config.yaml:106-118）
        self.codex = {
            "name": "Codex",
            "aliases": ["codex"],
            "app_bundles": ["/Applications/Codex.app", "/Applications/ChatGPT.app"],
        }

    def test_r1_absolute_command_inside_app_bundle(self):
        entry = {
            "key": "node_repl",
            "command": "/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node_repl",
            "args": [],
        }
        high, reason = is_high_risk_entry(entry, self.codex)
        self.assertTrue(high)
        self.assertIn("/Applications/ChatGPT.app", reason)

    def test_r1_absolute_path_in_args_inside_app_bundle(self):
        entry = {
            "key": "helper",
            "command": "node",
            "args": ["/Applications/ChatGPT.app/Contents/Resources/tool.js"],
        }
        high, reason = is_high_risk_entry(entry, self.codex)
        self.assertTrue(high)
        self.assertIn("/Applications/ChatGPT.app", reason)

    def test_r2_relative_path_into_app_contents(self):
        entry = {
            "key": "computer-use",
            "command": "./Codex Computer Use.app/Contents/SharedSupport/SkyComputerUseClient",
            "args": [],
        }
        high, reason = is_high_risk_entry(entry, self.codex)
        self.assertTrue(high)
        self.assertIn("应用包", reason)

    def test_r3_key_equals_client_name(self):
        high, reason = is_high_risk_entry({"key": "Codex", "command": "", "args": []}, self.codex)
        self.assertTrue(high)
        self.assertIn("同名", reason)

    def test_r3_key_equals_client_alias(self):
        high, _ = is_high_risk_entry({"key": "codex", "command": "", "args": []}, self.codex)
        self.assertTrue(high)

    def test_user_entry_is_not_high_risk(self):
        dsh = {
            "name": "DeepSeek Harness",
            "app_bundles": ["/Applications/DeepSeek Harness.app"],
        }
        entry = {
            "key": "image-vision",
            "command": "/usr/local/bin/python3",
            "args": ["/opt/vision/server.py"],
        }
        high, reason = is_high_risk_entry(entry, dsh)
        self.assertFalse(high)
        self.assertEqual(reason, "")

    def test_bare_command_name_is_not_high_risk(self):
        wb = {"name": "WorkBuddy", "app_bundles": ["/Applications/WorkBuddy.app"]}
        high, _ = is_high_risk_entry({"key": "context7", "command": "npx", "args": []}, wb)
        self.assertFalse(high)

    def test_near_miss_path_prefix_does_not_match(self):
        """前缀必须是目录边界，'/Applications/ChatGPT.app-evil' 不算。"""
        entry = {
            "key": "sneaky",
            "command": "/Applications/ChatGPT.app-evil/bin/x",
            "args": [],
        }
        high, _ = is_high_risk_entry(entry, self.codex)
        self.assertFalse(high)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_mcp_entry_risk.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.mcp_entry_risk'`

- [ ] **Step 3: 写最小实现**

创建 `core/mcp_entry_risk.py`：

```python
"""高风险 MCP 条目判定：识别「疑似客户端自带」的条目。

客户端自带条目（如 Codex 内嵌在 ChatGPT.app 里的 node_repl / computer-use）
删掉会破坏该客户端能力；而用户自建条目（如 image-vision、context7）恰恰是最想
清理的对象。二者都落在 ``unmanaged`` 分类里，只能靠启发式区分。

规则：
- R1 条目的 command / args 中绝对路径落在该客户端 ``app_bundles`` 任一前缀下；
- R2 路径含 ``.app/Contents/``（覆盖 ``./Codex Computer Use.app/...`` 这类相对路径）；
- R3 条目 key 归一化后等于客户端名或其 alias 之一。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

from tool_registry import expand_path, normalized_name

_APP_CONTENTS = ".app/contents/"


def _bundle_prefixes(tool: Dict[str, Any]) -> List[str]:
    """客户端 app bundle 路径前缀（归一化、去尾斜杠）。"""
    prefixes: List[str] = []
    for raw in tool.get("app_bundles") or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        prefix = os.path.normpath(expand_path(raw.strip())).replace("\\", "/")
        prefixes.append(prefix.rstrip("/"))
    return prefixes


def _entry_paths(entry: Dict[str, Any]) -> List[str]:
    """条目里可能承载可执行/脚本路径的字符串。"""
    paths: List[str] = []
    command = entry.get("command")
    if isinstance(command, str) and command.strip():
        paths.append(command.strip())
    for arg in entry.get("args") or []:
        if isinstance(arg, str) and arg.strip():
            paths.append(arg.strip())
    return paths


def _matching_bundle(path: str, prefixes: List[str]) -> str:
    """命中的 bundle 前缀；未命中返回空串。仅对绝对路径生效。"""
    if not os.path.isabs(path):
        return ""
    norm = os.path.normpath(path).replace("\\", "/")
    for prefix in prefixes:
        if norm == prefix or norm.startswith(prefix + "/"):
            return prefix
    return ""


def is_high_risk_entry(entry: Dict[str, Any], tool: Dict[str, Any]) -> Tuple[bool, str]:
    """返回 ``(high_risk, reason)``。

    非高风险时 ``reason`` 为空串；高风险时给出可直接展示给用户的中文原因。
    """
    raw_key = entry.get("key")
    key = raw_key if isinstance(raw_key, str) else ""
    norm_key = normalized_name(key)

    if norm_key:
        candidates: List[Any] = [tool.get("name") or ""]
        candidates.extend(tool.get("aliases") or [])
        for candidate in candidates:
            if not isinstance(candidate, str) or not candidate:
                continue
            if normalized_name(candidate) == norm_key:
                return True, f"条目名与客户端同名（{key}）"

    prefixes = _bundle_prefixes(tool)
    for path in _entry_paths(entry):
        matched = _matching_bundle(path, prefixes)
        if matched:
            return True, f"命令位于 {matched} 内（客户端自带）"
        if _APP_CONTENTS in path.replace("\\", "/").lower():
            return True, f"命令位于应用包内（{path}）"

    return False, ""
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python3 -m pytest tests/test_mcp_entry_risk.py -q`
Expected: PASS（8 passed）

- [ ] **Step 5: 提交**

```bash
git add core/mcp_entry_risk.py tests/test_mcp_entry_risk.py
git commit -m "feat(mcp): 新增高风险 MCP 条目判定（疑似客户端自带）"
```

---

## Task 2: 泛化 mcp_fixer 删除原语

**Files:**
- Modify: `core/mcp_fixer.py`（`_render_without_legacy` 在 L431-504；`remove_legacy_mcp_tool` 在 L748-798）
- Test: `tests/test_mcp_entry_removal.py`

**关键约束：** `--remove-legacy-mcp` 的输出被 GUI 用字符串匹配消费（`gui/dashboard.html:4406` 等），legacy 三个消息必须**逐字不变**。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_mcp_entry_removal.py`：

```python
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from mcp_fixer import remove_legacy_mcp_tool, remove_mcp_entries_tool  # noqa: E402

URL = "https://hermes.example/mcp"


def tool(path, **over):
    data = {
        "name": "WorkBuddy",
        "config_path": str(path),
        "format": "json",
        "mcp_key_path": ["mcpServers"],
        "fix_supported": True,
    }
    data.update(over)
    return data


class RemoveArbitraryEntriesTest(unittest.TestCase):
    def test_removes_named_entry_and_keeps_rest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text(
                json.dumps(
                    {
                        "theme": "dark",
                        "mcpServers": {
                            "hermes": {"url": URL},
                            "my-mcp": {"url": "https://example.internal/mcp"},
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            result = remove_mcp_entries_tool(tool(path), ["my-mcp"])

            self.assertEqual(result["status"], "updated")
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("my-mcp", updated["mcpServers"])
            self.assertIn("hermes", updated["mcpServers"])
            self.assertEqual(updated["theme"], "dark")

    def test_backup_contains_original_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            original = '{"mcpServers":{"my-mcp":{"url":"https://x.example/mcp"}}}\n'
            path.write_text(original, encoding="utf-8")

            result = remove_mcp_entries_tool(tool(path), ["my-mcp"])

            self.assertEqual(result["status"], "updated")
            self.assertTrue(result["backup"])
            self.assertEqual(Path(result["backup"]).read_text(encoding="utf-8"), original)

    def test_unknown_key_reports_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            original = '{"mcpServers":{"hermes":{"url":"https://h.example/mcp"}}}\n'
            path.write_text(original, encoding="utf-8")

            result = remove_mcp_entries_tool(tool(path), ["nope"])

            self.assertEqual(result["status"], "unchanged")
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_parse_failure_leaves_file_untouched(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            original = "{ not json"
            path.write_text(original, encoding="utf-8")

            result = remove_mcp_entries_tool(tool(path), ["my-mcp"])

            self.assertEqual(result["status"], "error")
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_missing_file_and_unsupported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "absent.json"
            self.assertEqual(remove_mcp_entries_tool(tool(path), ["x"])["status"], "missing")

            real = Path(temp_dir) / "mcp.json"
            real.write_text('{"mcpServers":{}}\n', encoding="utf-8")
            unsupported = tool(real, fix_supported=False)
            self.assertEqual(remove_mcp_entries_tool(unsupported, ["x"])["status"], "unsupported")

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            original = '{"mcpServers":{"my-mcp":{}}}\n'
            path.write_text(original, encoding="utf-8")

            result = remove_mcp_entries_tool(tool(path), ["my-mcp"], dry_run=True)

            self.assertEqual(result["status"], "dry-run")
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_toml_section_removal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            path.write_text(
                f'[mcp_servers.hermes]\nurl = "{URL}"\n\n'
                '[mcp_servers.my-mcp]\nurl = "https://example.internal/mcp"\n',
                encoding="utf-8",
            )
            cfg = tool(path, name="Codex", format="toml", mcp_key_path=["mcp_servers"])

            result = remove_mcp_entries_tool(cfg, ["my-mcp"])

            self.assertEqual(result["status"], "updated")
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("[mcp_servers.my-mcp]", text)
            self.assertIn("[mcp_servers.hermes]", text)


class LegacyCompatibilityTest(unittest.TestCase):
    """legacy 包装必须与新原语共用一条实现，且消息逐字不变。"""

    def test_legacy_updated_message_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text(
                '{"mcpServers":{"hermes":{"url":"https://h.example/mcp"},'
                '"ai-memory":{"command":"legacy"}}}\n',
                encoding="utf-8",
            )
            expected = {"legacy_names": ["ai-memory"]}

            result = remove_legacy_mcp_tool(tool(path), expected)

            self.assertEqual(result["status"], "updated")
            self.assertEqual(result["message"], "旧通道条目已移除并校验通过")

    def test_legacy_unchanged_message_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text('{"mcpServers":{"hermes":{}}}\n', encoding="utf-8")

            result = remove_legacy_mcp_tool(tool(path), {"legacy_names": ["ai-memory"]})

            self.assertEqual(result["status"], "unchanged")
            self.assertEqual(result["message"], "没有残留的旧通道条目")

    def test_legacy_dry_run_message_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text('{"mcpServers":{"ai-memory":{}}}\n', encoding="utf-8")

            result = remove_legacy_mcp_tool(
                tool(path), {"legacy_names": ["ai-memory"]}, dry_run=True
            )

            self.assertEqual(result["status"], "dry-run")
            self.assertEqual(result["message"], "将移除旧通道条目")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_mcp_entry_removal.py -q`
Expected: FAIL — `ImportError: cannot import name 'remove_mcp_entries_tool'`

- [ ] **Step 3: 把 `_render_without_legacy` 泛化**

在 `core/mcp_fixer.py` 中，把 L431 的函数**改名**为 `_render_without_entries`，并把函数体内两处 `legacy` 集合改名（语义不变）：

```python
def _render_without_entries(
    tool: Dict[str, Any], text: str, keys: List[str]
) -> str:
    """Remove exactly the named MCP entries from a client config.

    原 ``_render_without_legacy``：删除逻辑与「legacy」无关，只是一组待删 key，
    故泛化命名以复用同一条实现（六种格式共用）。
    """
    targets = set(keys)
    config_format = tool.get("format", "json")
    key_path = tool.get("mcp_key_path", ["mcpServers"])

    if config_format == "cordis_yaml":
        return _render_cordis_without_entries(text, keys)
    ...
```

其余分支里的 `for name in legacy:` / `if ... in legacy` / `not in legacy` 一律改为 `targets`。函数体其余部分**逐字保留**。

同时把 `_render_cordis_without_legacy`（L507）改名为 `_render_cordis_without_entries`，其形参 `legacy_names` 改名为 `keys`，内部 `legacy = set(legacy_names)` 改为 `targets = set(keys)`。

**紧接其后**保留旧名薄包装，兼容既有调用点与既有测试：

```python
def _render_without_legacy(
    tool: Dict[str, Any], text: str, legacy_names: List[str]
) -> str:
    """向后兼容别名（旧调用点与 tests/test_mcp_fixer.py 沿用此名）。"""
    return _render_without_entries(tool, text, legacy_names)
```

- [ ] **Step 4: 新增通用删除原语与 legacy 消息覆盖表**

在 `remove_legacy_mcp_tool` 之前插入：

```python
_GENERIC_REMOVAL_MESSAGES = {
    "unchanged": "没有匹配到要移除的条目",
    "dry-run": "将移除匹配到的条目",
    "updated": "条目已移除并校验通过",
}

# 旧 CLI 输出被 GUI 字符串匹配消费（gui/dashboard.html:4406），必须逐字不变。
_LEGACY_REMOVAL_MESSAGES = {
    "unchanged": "没有残留的旧通道条目",
    "dry-run": "将移除旧通道条目",
    "updated": "旧通道条目已移除并校验通过",
}


def remove_mcp_entries_tool(
    tool: Dict[str, Any],
    keys: List[str],
    *,
    dry_run: bool = False,
    messages: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """移除指定 key 的 MCP 条目（通用原语）。

    安全链与旧 ``remove_legacy_mcp_tool`` 完全一致：解析 → 备份 → 重新序列化 →
    再次解析校验 → 原子写。``messages`` 允许调用方覆盖 updated/unchanged/dry-run
    三个结果文案（legacy 包装用旧文案保持向后兼容）。
    """
    labels = messages or _GENERIC_REMOVAL_MESSAGES
    path = os.path.expanduser(tool.get("config_path", ""))
    if not path or not os.path.isfile(path):
        return _result(tool, "missing", "配置文件缺失，未做改动")
    if not tool.get("fix_supported", True):
        reason = tool.get("fix_unsupported_reason", "该客户端不支持此项修复")
        return _result(tool, "unsupported", reason)

    targets = [k for k in keys if isinstance(k, str) and k]
    if not targets:
        return _result(tool, "unchanged", labels["unchanged"])

    try:
        with open(path, "r", encoding="utf-8") as handle:
            original = handle.read()
        rendered = _render_without_entries(tool, original, targets)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return _result(tool, "error", "配置读取或解析失败，未做改动")

    if rendered == original:
        return _result(tool, "unchanged", labels["unchanged"])
    if dry_run:
        return _result(tool, "dry-run", labels["dry-run"])

    mode = stat.S_IMODE(os.stat(path).st_mode)
    backup_path = _backup_path(path)
    try:
        shutil.copy2(path, backup_path)
    except OSError:
        return _result(tool, "error", "无法创建备份，未做改动")

    try:
        _atomic_write(path, rendered, mode)
    except OSError:
        return _result(tool, "error", "原子写入失败，原配置未变")

    result = _result(tool, "updated", labels["updated"])
    result["backup"] = backup_path
    return result
```

- [ ] **Step 5: 把 `remove_legacy_mcp_tool` 改为薄包装**

将原 L748 `remove_legacy_mcp_tool` 的整个函数体替换为：

```python
def remove_legacy_mcp_tool(
    tool: Dict[str, Any],
    expected: Dict[str, Any],
    *,
    dry_run: bool = False,
) -> Dict[str, str]:
    """纯粹移除旧通道（legacy）条目，不校验正典端点是否已配置。

    删除旧通道不应以「正典端点已接入」为前提——正典端点缺失/待接入时，旧
    通道可能是客户端当前唯一连接，但用户仍有权选择先删旧通道、之后再用
    --fix-mcp 重新接入。实现已泛化为 ``remove_mcp_entries_tool``；此处只负责
    解析出 legacy 名单并沿用旧的输出文案（GUI 依赖字符串匹配）。
    """
    legacy_names = _merged_legacy_names(expected, tool)
    return remove_mcp_entries_tool(
        tool, legacy_names, dry_run=dry_run, messages=_LEGACY_REMOVAL_MESSAGES
    )
```

- [ ] **Step 6: 跑新测试与既有回归**

Run: `python3 -m pytest tests/test_mcp_entry_removal.py tests/test_mcp_fixer.py -q`
Expected: 全部 PASS（新文件 10 passed；`test_mcp_fixer.py` 无失败）

- [ ] **Step 7: 提交**

```bash
git add core/mcp_fixer.py tests/test_mcp_entry_removal.py
git commit -m "refactor(mcp): 删除原语泛化为按任意 key 移除，legacy 输出保持逐字兼容"
```

---

## Task 3: 配置备份的列出与还原

**Files:**
- Modify: `core/mcp_fixer.py`（新增 `validate_config_text`）
- Create: `core/config_backups.py`
- Test: `tests/test_config_backups.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_config_backups.py`：

```python
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from config_backups import list_config_backups, restore_config_backup  # noqa: E402


def tool(path, **over):
    data = {
        "name": "WorkBuddy",
        "config_path": str(path),
        "format": "json",
        "mcp_key_path": ["mcpServers"],
        "fix_supported": True,
    }
    data.update(over)
    return data


class ListBackupsTest(unittest.TestCase):
    def test_lists_only_own_backups_newest_first(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text('{"mcpServers":{}}\n', encoding="utf-8")
            older = Path(str(path) + ".bak-20260920-100000-000000")
            newer = Path(str(path) + ".bak-20260920-110000-000000")
            older.write_text('{"mcpServers":{"a":{}}}\n', encoding="utf-8")
            newer.write_text('{"mcpServers":{"b":{}}}\n', encoding="utf-8")
            # 干扰项：不是本配置的备份
            (Path(temp_dir) / "other.json.bak-20260920-120000-000000").write_text(
                "{}\n", encoding="utf-8"
            )

            backups = list_config_backups(str(path))

            self.assertEqual([b["path"] for b in backups], [str(newer), str(older)])
            self.assertEqual(backups[0]["size"], newer.stat().st_size)
            self.assertTrue(backups[0]["mtime_text"])


class RestoreBackupTest(unittest.TestCase):
    def _fixture(self, temp_dir, current, backup):
        path = Path(temp_dir) / "mcp.json"
        path.write_text(current, encoding="utf-8")
        backup_path = Path(str(path) + ".bak-20260920-100000-000000")
        backup_path.write_text(backup, encoding="utf-8")
        return path, backup_path

    def test_restore_overwrites_and_backs_up_current_first(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            current = '{"mcpServers":{"a":{}}}\n'
            backup = '{"mcpServers":{"a":{},"b":{}}}\n'
            path, backup_path = self._fixture(temp_dir, current, backup)

            result = restore_config_backup(tool(path), str(backup_path))

            self.assertEqual(result["status"], "updated")
            self.assertEqual(path.read_text(encoding="utf-8"), backup)
            self.assertTrue(result["backup"])
            self.assertEqual(Path(result["backup"]).read_text(encoding="utf-8"), current)

    def test_refuses_backup_of_another_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp.json"
            path.write_text('{"mcpServers":{}}\n', encoding="utf-8")
            foreign = Path(temp_dir) / "other.json.bak-20260920-100000-000000"
            foreign.write_text("{}\n", encoding="utf-8")

            result = restore_config_backup(tool(path), str(foreign))

            self.assertEqual(result["status"], "refused")
            self.assertIn("不是该客户端配置的备份", result["message"])

    def test_refuses_unparsable_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            current = '{"mcpServers":{"a":{}}}\n'
            path, backup_path = self._fixture(temp_dir, current, "{ broken")
            before = path.read_text(encoding="utf-8")

            result = restore_config_backup(tool(path), str(backup_path))

            self.assertEqual(result["status"], "refused")
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            current = '{"mcpServers":{"a":{}}}\n'
            backup = '{"mcpServers":{"b":{}}}\n'
            path, backup_path = self._fixture(temp_dir, current, backup)

            result = restore_config_backup(tool(path), str(backup_path), dry_run=True)

            self.assertEqual(result["status"], "dry-run")
            self.assertEqual(path.read_text(encoding="utf-8"), current)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_config_backups.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.config_backups'`

- [ ] **Step 3: 在 `core/mcp_fixer.py` 新增解析校验入口**

紧接 `_render_without_entries` 之后插入（供还原路径复用同一批解析器，避免格式分叉）：

```python
def validate_config_text(tool: Dict[str, Any], text: str) -> None:
    """按客户端声明的格式做解析校验；非法时抛异常。

    与 ``_render_without_entries`` 使用完全相同的解析器，供「还原备份」等
    不经过渲染的路径复用，避免出现第二套格式判定。
    """
    config_format = tool.get("format", "json")
    if config_format == "cordis_yaml":
        _load_cordis_yaml(text)
    elif config_format == "yaml":
        yaml.safe_load(text)
    elif config_format in ("json", "jsonc"):
        json.loads(text)
    elif config_format == "reasonix":
        json.loads(text)
    else:
        _toml.loads(text)
```

- [ ] **Step 4: 实现 `core/config_backups.py`**

```python
"""客户端配置文件的备份管理：列出与还原。

备份沿用 ``core/mcp_fixer.py`` 的命名约定 ``<config_path>.bak-<时间戳>``。

**还原是整文件覆盖**——备份是配置文件的完整副本，还原会连带回退该文件的全部
后续改动（不只是 MCP 段落）。因此调用方（GUI）必须在强确认文案里讲清这一点；
本模块只负责安全落地：归属校验 → 解析校验 → 先备份当前 → 原子写 → 复校。
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from datetime import datetime
from typing import Any, Dict, List

from mcp_fixer import _atomic_write, _backup_path, validate_config_text

BACKUP_MARKER = ".bak-"


def list_config_backups(config_path: str) -> List[Dict[str, Any]]:
    """返回指定配置文件的全部备份，按时间倒序（新的在前）。"""
    path = os.path.expanduser(config_path or "")
    if not path:
        return []
    directory = os.path.dirname(path) or "."
    prefix = os.path.basename(path) + BACKUP_MARKER
    if not os.path.isdir(directory):
        return []

    found: List[Dict[str, Any]] = []
    for name in os.listdir(directory):
        if not name.startswith(prefix):
            continue
        full = os.path.join(directory, name)
        if not os.path.isfile(full):
            continue
        info = os.stat(full)
        found.append(
            {
                "path": full,
                "size": info.st_size,
                "mtime": info.st_mtime,
                "mtime_text": datetime.fromtimestamp(info.st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "suffix": name[len(prefix):],
            }
        )
    found.sort(key=lambda item: item["mtime"], reverse=True)
    return found


def restore_config_backup(
    tool: Dict[str, Any],
    backup_path: str,
    *,
    dry_run: bool = False,
) -> Dict[str, str]:
    """把指定备份还原到客户端的配置文件。"""
    config_path = os.path.expanduser(tool.get("config_path", "") or "")
    target = os.path.expanduser(backup_path or "")
    result: Dict[str, str] = {
        "status": "error",
        "message": "",
        "path": config_path,
        "backup": "",
    }

    if not config_path or not os.path.isfile(config_path):
        result["status"] = "missing"
        result["message"] = "配置文件缺失，未做改动"
        return result

    expected_prefix = config_path + BACKUP_MARKER
    if not target.startswith(expected_prefix) or not os.path.isfile(target):
        result["status"] = "refused"
        result["message"] = "不是该客户端配置的备份，已拒绝"
        return result

    try:
        with open(target, "r", encoding="utf-8") as handle:
            content = handle.read()
        validate_config_text(tool, content)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        result["status"] = "refused"
        result["message"] = "备份内容解析失败，已拒绝（原配置未变）"
        return result

    if dry_run:
        result["status"] = "dry-run"
        result["message"] = "将用该备份覆盖当前配置"
        return result

    mode = stat.S_IMODE(os.stat(config_path).st_mode)
    safety_backup = _backup_path(config_path)
    try:
        shutil.copy2(config_path, safety_backup)
    except OSError:
        result["status"] = "error"
        result["message"] = "无法备份当前配置，未做改动"
        return result

    try:
        _atomic_write(config_path, content, mode)
    except OSError:
        result["status"] = "error"
        result["message"] = "原子写入失败，原配置未变"
        return result

    result["status"] = "updated"
    result["message"] = "已从备份还原（还原前的当前配置也已备份）"
    result["backup"] = safety_backup
    return result
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `python3 -m pytest tests/test_config_backups.py -q`
Expected: PASS（5 passed）

- [ ] **Step 6: 提交**

```bash
git add core/config_backups.py core/mcp_fixer.py tests/test_config_backups.py
git commit -m "feat(mcp): 新增配置备份列出与整文件还原能力"
```

---

## Task 4: 删除编排模块

**Files:**
- Create: `core/mcp_entry_removal.py`
- Test: `tests/test_mcp_entry_removal.py`（追加一个测试类）

**两个已定案的决策（设计文档 §3.1、§3.4）：**

1. **写入顺序：先删配置条目，后改挂载声明。** 若声明更新失败，条目已删而声明仍挂着，下次「修复 MCP」会把它装回来 —— 失败自愈。反序则留下「条目在、声明没了」的困惑状态。
2. **空声明必须在写盘之前拒绝。** `resolve_client_attach` 用 `if attach:` 判定，空列表 == 未声明 == 挂载全部端点，所以把声明清空会让它回弹成「挂载全部」。

- [ ] **Step 1: 追加失败测试**

在 `tests/test_mcp_entry_removal.py` 末尾追加（放在 `if __name__ == "__main__":` 之前）：

```python
class RemovalOrchestrationTest(unittest.TestCase):
    """编排层：分类挑 key、高风险门、attach 声明同步、空声明拒绝。"""

    def _config(self, path, *, attach=None, app_bundles=None):
        tool_entry = {
            "name": "Codex",
            "aliases": ["codex"],
            "config_path": str(path),
            "format": "toml",
            "mcp_key_path": ["mcp_servers"],
            "fix_supported": True,
            "mcp_attach": attach if attach is not None else ["K8s-uat", "hermes-home"],
        }
        if app_bundles:
            tool_entry["app_bundles"] = app_bundles
        return {
            "mcp_tools": [tool_entry],
            "profiles": {
                "K8s-uat": {"name": "K8s-uat", "url": "https://k8s.example/mcp"},
                "hermes-home": {"name": "hermes", "url": "https://hermes.example/mcp"},
            },
        }

    def _write(self, temp_dir):
        path = Path(temp_dir) / "config.toml"
        path.write_text(
            f'[mcp_servers.hermes]\nurl = "{URL}"\n\n'
            '[mcp_servers.K8s-uat]\nurl = "https://k8s.example/mcp"\n\n'
            '[mcp_servers.my-mcp]\nurl = "https://example.internal/mcp"\n',
            encoding="utf-8",
        )
        return path

    def test_unmanaged_removal_touches_no_declaration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write(temp_dir)
            config = self._config(path)

            result = remove_entries(config, "Codex", ["my-mcp"])

            self.assertEqual(result["status"], "updated")
            self.assertNotIn("[mcp_servers.my-mcp]", path.read_text(encoding="utf-8"))
            self.assertEqual(result["attach_updated"], [])
            self.assertEqual(
                config["mcp_tools"][0]["mcp_attach"], ["K8s-uat", "hermes-home"]
            )

    def test_attached_removal_drops_endpoint_key_not_config_key(self):
        """配置 key 是 'hermes'，声明 key 是 'hermes-home'，必须经 endpoint_key 回映。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write(temp_dir)
            config = self._config(path)

            result = remove_entries(config, "Codex", ["hermes"])

            self.assertEqual(result["status"], "updated")
            self.assertEqual(result["attach_updated"], ["hermes-home"])
            self.assertNotIn("[mcp_servers.hermes]", path.read_text(encoding="utf-8"))

    def test_high_risk_entry_is_refused_without_force(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            original = (
                '[mcp_servers.node_repl]\n'
                'command = "/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node_repl"\n'
            )
            path.write_text(original, encoding="utf-8")
            config = self._config(path, app_bundles=["/Applications/ChatGPT.app"])

            result = remove_entries(config, "Codex", ["node_repl"])

            self.assertEqual(result["status"], "refused")
            self.assertIn("node_repl", result["high_risk"][0]["key"])
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_empty_declaration_is_refused_before_any_write(self):
        """删掉最后一个 attached 条目会让声明变空 → 必须整体拒绝且不落盘。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            original = f'[mcp_servers.hermes]\nurl = "{URL}"\n'
            path.write_text(original, encoding="utf-8")
            config = self._config(path, attach=["hermes-home"])

            result = remove_entries(config, "Codex", ["hermes"])

            self.assertEqual(result["status"], "refused")
            self.assertIn("空", result["message"])
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(config["mcp_tools"][0]["mcp_attach"], ["hermes-home"])

    def test_remove_class_unmanaged_skips_high_risk_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            path.write_text(
                '[mcp_servers.my-mcp]\nurl = "https://example.internal/mcp"\n\n'
                '[mcp_servers.bundled]\n'
                'command = "/Applications/ChatGPT.app/Contents/Resources/x"\n',
                encoding="utf-8",
            )
            config = self._config(path, app_bundles=["/Applications/ChatGPT.app"])

            result = remove_class(config, "Codex", "unmanaged")

            self.assertEqual(result["status"], "updated")
            self.assertIn("my-mcp", result["removed"])
            self.assertEqual([h["key"] for h in result["skipped_high_risk"]], ["bundled"])
            self.assertIn("[mcp_servers.bundled]", path.read_text(encoding="utf-8"))
```

并在该文件顶部导入行补充（沿用该文件已有的路径头，扁平导入）：

```python
from mcp_entry_removal import remove_class, remove_entries  # noqa: E402
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_mcp_entry_removal.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.mcp_entry_removal'`

- [ ] **Step 3: 实现 `core/mcp_entry_removal.py`**

```python
"""MCP 条目删除编排：分类挑 key、高风险门、attach 声明同步、空声明拒绝。

落盘逻辑 100% 复用既有安全链——条目删除走
``mcp_fixer.remove_mcp_entries_tool``，挂载声明走
``endpoint_store.set_client_attach``（写 ``client_mcp_attach`` overlay）。本模块
只做编排与门禁，不新增任何写盘路径。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from endpoint_library import resolve_client_attach
from endpoint_store import set_client_attach
from mcp_entry_risk import is_high_risk_entry
from mcp_fixer import remove_mcp_entries_tool
from mcp_inventory import inventory_client
from tool_registry import effective_tools, normalized_name

CLASSES = ("attached", "legacy", "unmanaged")


def _find_tool(config: Dict[str, Any], client_name: str) -> Optional[Dict[str, Any]]:
    wanted = normalized_name(client_name)
    for tool in effective_tools(config):
        if not isinstance(tool, dict):
            continue
        if normalized_name(tool.get("name", "")) == wanted:
            return tool
    return None


def _endpoint_entries(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    from endpoint_library import list_endpoints  # 局部导入避免循环

    profiles = config.get("profiles") or {}
    entries: List[Dict[str, Any]] = []
    for key in list_endpoints(config):
        profile = profiles.get(key) or {}
        entry = {"key": key, "name": profile.get("name", key)}
        for legacy in profile.get("legacy_names", []) or []:
            entry.setdefault("legacy_names", []).append(legacy)
        entries.append(entry)
    return entries


def _legacy_names(config: Dict[str, Any], tool: Dict[str, Any]) -> List[str]:
    names = set(tool.get("legacy_names", []) or [])
    for entry in _endpoint_entries(config):
        names.update(entry.get("legacy_names", []) or [])
    return sorted(names)


def client_entries(config: Dict[str, Any], tool: Dict[str, Any]) -> List[Any]:
    """该客户端当前全部 MCP 条目（已分类）。"""
    return inventory_client(
        tool,
        endpoint_entries=_endpoint_entries(config),
        legacy_names=_legacy_names(config, tool),
    )


def _annotate(entry: Any, tool: Dict[str, Any]) -> Dict[str, Any]:
    high, reason = is_high_risk_entry(
        {"key": entry.key, "command": entry.command, "args": list(entry.args)}, tool
    )
    return {
        "key": entry.key,
        "classification": entry.classification,
        "endpoint_key": entry.endpoint_key,
        "high_risk": high,
        "risk_reason": reason,
    }


def _plan(
    config: Dict[str, Any],
    tool: Dict[str, Any],
    keys: List[str],
    *,
    force_high_risk: bool,
) -> Dict[str, Any]:
    """把待删 key 解析为「可删 / 高危 / 不存在 / 声明变更 / 拒绝」。"""
    entries = {entry.key: entry for entry in client_entries(config, tool)}
    annotated = {entry.key: _annotate(entry, tool) for entry in entries.values()}

    existing = [k for k in keys if k in entries]
    missing = [k for k in keys if k not in entries]
    blocked = [annotated[k] for k in existing if annotated[k]["high_risk"]]
    if blocked and not force_high_risk:
        return {"refused": True, "high_risk": blocked, "existing": existing, "missing": missing}

    attach_keys: List[str] = []
    for key in existing:
        entry = entries[key]
        if entry.classification == "attached" and entry.endpoint_key:
            attach_keys.append(entry.endpoint_key)

    declaration = list(resolve_client_attach(tool, config))
    remaining = [k for k in declaration if k not in attach_keys]
    if attach_keys and not remaining:
        return {
            "refused": True,
            "empty_declaration": True,
            "existing": existing,
            "missing": missing,
            "high_risk": [],
        }

    return {
        "refused": False,
        "existing": existing,
        "missing": missing,
        "high_risk": [],
        "attach_keys": attach_keys,
        "remaining": remaining,
        "explicit_attach": bool(tool.get("mcp_attach")),
    }


def remove_entries(
    config: Dict[str, Any],
    client_name: str,
    keys: List[str],
    *,
    force_high_risk: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """删除指定 key 的 MCP 条目（含 attached 声明同步）。"""
    tool = _find_tool(config, client_name)
    if tool is None:
        return {"status": "error", "message": f"未找到客户端 {client_name}", "removed": []}

    plan = _plan(config, tool, keys, force_high_risk=force_high_risk)
    base = {
        "removed": [],
        "skipped_high_risk": [],
        "attach_updated": [],
        "path": tool.get("config_path", ""),
        "backup": "",
    }
    if plan.get("empty_declaration"):
        base["status"] = "refused"
        base["message"] = (
            "拒绝：删除后该客户端的挂载声明将变为空，而本项目语义中"
            "「空声明」等同于「挂载全部端点」，会回弹成挂载全部。"
            "如需彻底断开，请改用端点库 / 客户端管理。"
        )
        return base
    if plan.get("refused"):
        base["status"] = "refused"
        base["high_risk"] = plan["high_risk"]
        base["message"] = "拒绝：以下条目疑似客户端自带，需显式确认后才能删除：" + "、".join(
            h["key"] for h in plan["high_risk"]
        )
        return base
    if not plan["existing"]:
        base["status"] = "unchanged"
        base["message"] = "没有匹配到要移除的条目"
        return base

    if dry_run:
        base["status"] = "dry-run"
        base["message"] = "将移除：" + "、".join(plan["existing"])
        return base

    # 先删配置条目：若随后的声明更新失败，下一次「修复 MCP」会把条目装回来（自愈）。
    outcome = remove_mcp_entries_tool(tool, plan["existing"])
    base["status"] = outcome.get("status", "error")
    base["message"] = outcome.get("message", "")
    base["backup"] = outcome.get("backup", "")
    if outcome.get("status") != "updated":
        return base

    base["removed"] = list(plan["existing"])
    if not plan["attach_keys"]:
        return base

    store_result = set_client_attach(config, tool.get("name", client_name), plan["remaining"])
    if store_result.get("status") not in ("ok", "dry-run"):
        base["status"] = "error"
        base["message"] = (
            "配置条目已移除，但挂载声明更新失败（"
            + str(store_result.get("message", ""))
            + "）。下次「修复 MCP」可能重新写入该条目；可用「从备份恢复」回滚。"
        )
        return base

    base["attach_updated"] = list(plan["attach_keys"])
    return base


def remove_class(
    config: Dict[str, Any],
    client_name: str,
    klass: str,
    *,
    include_high_risk: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """按分类批量清理一个客户端的 MCP 条目。"""
    if klass not in CLASSES:
        return {
            "status": "error",
            "message": f"未知分类 {klass}；可选：{'、'.join(CLASSES)}",
            "removed": [],
        }
    tool = _find_tool(config, client_name)
    if tool is None:
        return {"status": "error", "message": f"未找到客户端 {client_name}", "removed": []}

    annotated = [_annotate(entry, tool) for entry in client_entries(config, tool)]
    targets = [item["key"] for item in annotated if item["classification"] == klass]
    skipped = [item for item in annotated if item["classification"] == klass and item["high_risk"]]
    if not include_high_risk:
        targets = [key for key in targets if key not in {s["key"] for s in skipped}]

    result = remove_entries(
        config, client_name, targets, force_high_risk=include_high_risk, dry_run=dry_run
    )
    result.setdefault("skipped_high_risk", [])
    if not include_high_risk:
        result["skipped_high_risk"] = [
            {"key": item["key"], "reason": item["risk_reason"]} for item in skipped
        ]
    return result
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python3 -m pytest tests/test_mcp_entry_removal.py tests/test_endpoint_store.py -q`
Expected: PASS（`test_endpoint_store.py` 无失败——确认 `set_client_attach` 调用方式正确）

- [ ] **Step 5: 提交**

```bash
git add core/mcp_entry_removal.py tests/test_mcp_entry_removal.py
git commit -m "feat(mcp): 新增 MCP 条目删除编排（高风险门 + 挂载声明同步 + 空声明拒绝）"
```

---

## Task 5: 快照补 `high_risk` / `risk_reason`

**Files:**
- Modify: `core/management_snapshot.py:280-289`

- [ ] **Step 1: 改动 inventory 构造**

在 `core/management_snapshot.py` 顶部导入区加入：

```python
from mcp_entry_risk import is_high_risk_entry
```

把 L280-289 的列表推导替换为显式循环（避免同一判定调用两次）：

```python
            "inventory": _mcp_inventory_payload(entries, tool),
```

并在同文件的 `_effective_tools` 附近新增：

```python
def _mcp_inventory_payload(entries: List[Any], tool: Dict[str, Any]) -> List[Dict[str, Any]]:
    """inventory 条目载荷；每条附带高风险判定，供 GUI 分级确认。"""
    payload: List[Dict[str, Any]] = []
    for entry in entries:
        high, reason = is_high_risk_entry(
            {"key": entry.key, "command": entry.command, "args": list(entry.args)}, tool
        )
        payload.append(
            {
                "key": entry.key,
                "url": entry.url,
                "command": entry.command,
                "classification": entry.classification,
                "endpoint_key": entry.endpoint_key,
                "high_risk": high,
                "risk_reason": reason,
            }
        )
    return payload
```

- [ ] **Step 2: 跑既有测试**

Run: `python3 -m pytest tests/test_management_snapshot.py tests/test_gui_consistency.py -q`
Expected: PASS（两文件无失败）

- [ ] **Step 3: 真机验证字段**

Run:

```bash
python3 scan.py --management --format json | python3 -c "
import json,sys
d=json.load(sys.stdin)
for c in (d.get('mcp') or {}).get('clients',[]):
    for e in c.get('inventory') or []:
        if e.get('high_risk'):
            print('HIGH', c['name'], e['key'], '|', e['risk_reason'])
"
```

Expected: 恰好两行，均为 `Codex node_repl` 与 `Codex computer-use`（本机 2026-09-20 实测形状）

- [ ] **Step 4: 提交**

```bash
git add core/management_snapshot.py
git commit -m "feat(mcp): 管理快照 inventory 补高风险判定字段"
```

---

## Task 6: CLI 参数与路由

**Files:**
- Modify: `scan.py`（argparse 定义在 L1131-1139 一带；路由 `--remove-legacy-mcp` 在 L1489；`_print_store_result` 在 L513）

- [ ] **Step 1: 加 argparse 参数**

在 `scan.py` 的 `--attach-endpoints` 定义（L1132-1135）之后插入：

```python
    parser.add_argument(
        "--remove-mcp-entry", type=str, default=None, metavar="KEY[,KEY...]",
        help="移除指定 MCP 条目（配合 --client；高风险条目需 --force-high-risk；支持 --dry-run）",
    )
    parser.add_argument(
        "--remove-mcp-class", type=str, default=None,
        choices=["attached", "legacy", "unmanaged"],
        help="按分类批量清理 MCP 条目（配合 --client；默认跳过高风险，需 --include-high-risk）",
    )
    parser.add_argument(
        "--force-high-risk", action="store_true",
        help="配合 --remove-mcp-entry：允许删除疑似客户端自带的条目",
    )
    parser.add_argument(
        "--include-high-risk", action="store_true",
        help="配合 --remove-mcp-class：批量清理时纳入疑似客户端自带的条目",
    )
    parser.add_argument(
        "--list-config-backups", action="store_true",
        help="只读列出该客户端配置的历史备份（配合 --client）",
    )
    parser.add_argument(
        "--restore-config-backup", type=str, default=None, metavar="PATH",
        help="从备份还原该客户端配置（配合 --client；整文件覆盖；支持 --dry-run）",
    )
```

- [ ] **Step 2: 加输出助手与 4 个处理函数**

在 `_print_store_result`（L513）附近新增：

```python
def _print_mcp_result(result, as_json: bool) -> None:
    """MCP 条目删除 / 清理 / 还原的统一输出。

    ``--format json`` 时输出结构化对象，前端据此判定结果，不再对 stdout 做
    字符串匹配（旧 ``--remove-legacy-mcp`` 保持原有字符串输出不变）。
    """
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    mark = "✅" if result.get("status") in ("updated", "unchanged") else "❌"
    print(f"  {mark} {result.get('message', '')}")
    if result.get("path"):
        print(f"    配置: {result['path']}")
    if result.get("backup"):
        print(f"    备份: {result['backup']}")
    if result.get("attach_updated"):
        print(f"    已同步摘除挂载声明: {', '.join(result['attach_updated'])}")
    for item in result.get("skipped_high_risk") or []:
        print(f"    ⏭️ 跳过高风险: {item['key']}（{item['reason']}）")


def _run_remove_mcp_entry(args, config, config_path) -> int:
    client = getattr(args, "client", None)
    if not client:
        print("  ❌ --remove-mcp-entry 需要配合 --client <客户端名>")
        return 2
    keys = [part.strip() for part in (args.remove_mcp_entry or "").split(",") if part.strip()]
    if not keys:
        print("  ❌ --remove-mcp-entry 需要至少一个条目 key")
        return 2
    result = remove_entries(
        config, client, keys,
        force_high_risk=bool(args.force_high_risk), dry_run=bool(args.dry_run),
    )
    _print_mcp_result(result, getattr(args, "format", None) == "json")
    return 0 if result.get("status") in ("updated", "unchanged", "dry-run") else 2


def _run_remove_mcp_class(args, config, config_path) -> int:
    client = getattr(args, "client", None)
    if not client:
        print("  ❌ --remove-mcp-class 需要配合 --client <客户端名>")
        return 2
    result = remove_class(
        config, client, args.remove_mcp_class,
        include_high_risk=bool(args.include_high_risk), dry_run=bool(args.dry_run),
    )
    _print_mcp_result(result, getattr(args, "format", None) == "json")
    return 0 if result.get("status") in ("updated", "unchanged", "dry-run") else 2


def _run_list_config_backups(args, config, config_path) -> int:
    client = getattr(args, "client", None)
    if not client:
        print("  ❌ --list-config-backups 需要配合 --client <客户端名>")
        return 2
    tool = _find_client_tool(config, client)
    if tool is None:
        print(f"  ❌ 未找到客户端 {client}")
        return 2
    backups = list_config_backups(tool.get("config_path", ""))
    if getattr(args, "format", None) == "json":
        print(json.dumps(
            {"status": "ok", "client": client, "config_path": tool.get("config_path", ""),
             "backups": backups}, ensure_ascii=False, indent=2))
        return 0
    print(f"  {client} 的配置备份（{len(backups)} 个）:")
    for item in backups:
        print(f"    {item['mtime_text']}  {item['size']:>8} B  {item['path']}")
    return 0


def _run_restore_config_backup(args, config, config_path) -> int:
    client = getattr(args, "client", None)
    if not client:
        print("  ❌ --restore-config-backup 需要配合 --client <客户端名>")
        return 2
    tool = _find_client_tool(config, client)
    if tool is None:
        print(f"  ❌ 未找到客户端 {client}")
        return 2
    result = restore_config_backup(tool, args.restore_config_backup, dry_run=bool(args.dry_run))
    _print_mcp_result(result, getattr(args, "format", None) == "json")
    return 0 if result.get("status") in ("updated", "dry-run") else 2
```

同时新增客户端查找助手（`_run_list_config_backups` 与 `_run_restore_config_backup` 共用）：

```python
def _find_client_tool(config, client_name):
    """按归一化名在有效客户端里查注册表条目。"""
    wanted = normalized_name(client_name)
    for tool in effective_tools(config):
        if isinstance(tool, dict) and normalized_name(tool.get("name", "")) == wanted:
            return tool
    return None
```

- [ ] **Step 3: 加导入**

在 `scan.py` 顶部导入区（`from mcp_fixer import ...` 在 L75）补充：

```python
from config_backups import list_config_backups, restore_config_backup
from mcp_entry_removal import remove_class, remove_entries
from tool_registry import effective_tools, normalized_name
```

（若 `effective_tools` / `normalized_name` 已从 `tool_registry` 导入，则只补缺失的名字，不要重复导入。）

- [ ] **Step 4: 加路由**

在 `--remove-legacy-mcp` 路由分支（L1489）**之前**插入：

```python
    if args.remove_mcp_entry:
        return _run_remove_mcp_entry(args, config, config_path)
    if args.remove_mcp_class:
        return _run_remove_mcp_class(args, config, config_path)
    if args.list_config_backups:
        return _run_list_config_backups(args, config, config_path)
    if args.restore_config_backup:
        return _run_restore_config_backup(args, config, config_path)
```

- [ ] **Step 5: 验证 CLI 行为（只读 + dry-run）**

Run:

```bash
python3 scan.py --list-config-backups --client Codex
python3 scan.py --remove-mcp-entry my-mcp --client WorkBuddy --dry-run --format json
python3 scan.py --remove-mcp-class unmanaged --client WorkBuddy --dry-run --format json
python3 scan.py --remove-mcp-entry node_repl --client Codex --format json; echo "exit=$?"
```

Expected:
- 第一条：列出 `~/.codex/config.toml.bak-*`（可能为 0 个）
- 第二、三条：JSON，`status` 为 `dry-run`
- 第四条：`status` 为 `refused`，`exit=2`（高风险未加 `--force-high-risk`）

- [ ] **Step 6: 回归旧参数**

Run: `python3 scan.py --remove-legacy-mcp --client WorkBuddy --dry-run`
Expected: 输出与改动前一致（`将移除旧通道条目` / `没有残留的旧通道条目`）

- [ ] **Step 7: 提交**

```bash
git add scan.py
git commit -m "feat(cli): 新增 MCP 条目删除/清理与配置备份还原命令"
```

---

## Task 7: GUI 接入

**Files:**
- Modify: `gui/dashboard.html`（分发器 L4239-4258；`showMcpClass` L3332；`showAgentDetail` 条目区 L3283-3313；`renderMcpClients` L2623-2656；`confirmModal` L1373）

**说明：** 本前端为单文件静态页，改完刷新即生效（无需重建）；但若通过 Tauri 桌面壳使用，需按 `src-tauri/BUILD.md` 重新 `cargo tauri build` 才能进 `.app`。

- [ ] **Step 1: 新增强确认弹窗**

在 `confirmModal`（L1373-1390）之后插入：

```javascript
/**
 * 高风险条目强确认：必须手输 key 名才解锁删除按钮。
 * 复用 confirmModal 的样式类，不新造视觉。
 */
function confirmTypedKeyModal(title, message, keyName) {
  return new Promise((resolve) => {
    $("modal-root").innerHTML = `<div class="modal-backdrop"><div class="modal cfm-card">
      <div class="cfm-icon">!</div>
      <div class="cfm-title">${escapeHtml(title)}</div>
      <div class="cfm-msg">${escapeHtml(message)}</div>
      <div class="cfm-typed"><input id="cfm-typed-input" type="text" autocomplete="off"
        placeholder="输入 ${escapeHtml(keyName)} 以确认" aria-label="输入条目名以确认" /></div>
      <div class="actions">
        <button class="cfm-btn-cancel" id="cfm-no">取消</button>
        <button class="cfm-btn-danger" id="cfm-yes" disabled>确认删除</button>
      </div>
    </div></div>`;
    const input = $("cfm-typed-input");
    const yes = $("cfm-yes");
    input.oninput = () => { yes.disabled = input.value.trim() !== keyName; };
    input.focus();
    $("cfm-no").onclick = () => { closeModal(); resolve(false); };
    yes.onclick = () => { closeModal(); resolve(true); };
  });
}
```

- [ ] **Step 2: MCP 页第三列改为可点击**

在 `renderMcpClients`（L2623）中，把 inventory 标签的渲染（约 L2633-2637）由 `<span>` 改为按钮，打开既有分类详情弹窗：

```javascript
      const inv = (c.inventory || []).map((e) => {
        const cls = e.classification || "unmanaged";
        const label = CLASS_TRANSLATE[cls] || cls;
        const color = CLASS_COLOR[cls] || "";
        const risk = e.high_risk ? " ⚠" : "";
        const tip = e.high_risk ? (e.risk_reason || "疑似客户端自带") : (e.url || e.command || "");
        return `<button type="button" class="tag tag-btn ${color}" data-action="show-mcp-class" data-name="${escapeHtml(c.name)}" data-class="${escapeHtml(cls)}" title="${escapeHtml(tip)}">${escapeHtml(e.key)} · ${escapeHtml(label)}${risk}</button>`;
      }).join(" ") || '<span class="ok-na">无</span>';
```

- [ ] **Step 3: `showMcpClass` 增加删除 / 批量 / 回滚**

把 `showMcpClass`（L3332-3380 一带）整体替换为：

```javascript
function showMcpClass(name, cls) {
  const mcpCl = (SNAP && SNAP.mcp && SNAP.mcp.clients || []).find((c) => c.name === name);
  const inv = (mcpCl && mcpCl.inventory) || [];
  const items = inv.filter((e) => (e.classification || "unmanaged") === cls);
  const titleMap = { legacy: "旧通道（已失效）", unmanaged: "未纳管条目", attached: "已挂载端点" };
  const title = titleMap[cls] || "MCP 条目";
  const a = (SNAP && SNAP.agents || []).find((x) => x.name === name);
  const fixable = !!(a && a.fix_supported);
  const highCount = items.filter((e) => e.high_risk).length;

  const rows = items.map((e) => {
    const locType = e.url ? "URL" : (e.command ? "命令" : "");
    const locDetail = e.url ? escapeHtml(e.url) : (e.command ? escapeHtml(e.command) : "");
    const risk = e.high_risk
      ? `<span class="tag warn" title="${escapeHtml(e.risk_reason || "")}">疑似客户端自带</span>` : "";
    const del = fixable
      ? `<button class="ad-clean" type="button" data-action="remove-mcp-entry"
           data-name="${escapeHtml(name)}" data-key="${escapeHtml(e.key)}"
           data-high="${e.high_risk ? "1" : "0"}"
           data-reason="${escapeHtml(e.risk_reason || "")}">删除</button>`
      : "";
    return `<div class="ad-entry mcp-entry">
      <span class="ad-e-key">${escapeHtml(e.key)}</span>
      <span class="tag ${cls === "legacy" ? "warn" : ""}">${escapeHtml(title)}</span>
      ${risk}
      <span class="ad-e-loc" title="${locDetail}">${locType ? `<span class="mcp-loc-type">${locType}</span> ${locDetail}` : `<span class="ad-none">无地址</span>`}</span>
      ${del}
    </div>`;
  }).join("");

  const bulk = (fixable && items.length)
    ? `<div class="ad-cleanbar">
         <span class="ad-clean-note">共 ${items.length} 条${highCount ? `，其中 ${highCount} 条疑似客户端自带` : ""}</span>
         <label class="note" style="display:inline-flex;align-items:center;gap:4px">
           <input type="checkbox" id="mcpcls-include-high" ${highCount ? "" : "disabled"} />
           包含疑似客户端自带（${highCount}）
         </label>
         <button class="ad-clean-btn" type="button" data-action="remove-mcp-class"
           data-name="${escapeHtml(name)}" data-class="${escapeHtml(cls)}">清理全部${escapeHtml(title)}</button>
       </div>`
    : "";

  const footNote = fixable
    ? "删除前会自动备份到 <配置文件名>.bak-<时间戳>；需要时可用「从备份恢复」还原（还原为整文件覆盖）。"
    : "该客户端不支持配置写入（fix_supported=false），因此不提供删除。";

  mountModal(`<div class="modal-backdrop"><div class="modal ad-modal">
    <div class="ad-head">
      <div class="ad-head-top"><span class="ad-type">${escapeHtml(name)}</span><span class="tag ${cls === "legacy" ? "warn" : ""}">${escapeHtml(title)}</span></div>
      <div class="ad-name">${escapeHtml(title)}</div>
    </div>
    <div class="ad-body">
      <div class="ad-section">
        <div class="ad-entries">${rows || '<div class="ad-none">无条目</div>'}</div>
        ${bulk}
      </div>
    </div>
    <div class="ad-foot">
      <button class="btn-soft" type="button" data-action="show-config-backups" data-name="${escapeHtml(name)}">从备份恢复</button>
      <button class="btn-cancel close-push" id="mcpcls-close">关闭</button>
    </div>
    <div class="ad-foot-note">${escapeHtml(footNote)}</div>
  </div></div>`);
  $("mcpcls-close").onclick = closeModal;
}
```

- [ ] **Step 4: 新增执行函数**

在 `cleanLegacyMcp`（L4399）之后插入：

```javascript
async function removeMcpEntry(name, key, high, reason) {
  const msg = high
    ? `「${key}」疑似客户端自带${reason ? `（${reason}）` : ""}，删除可能破坏该客户端的功能。\n原配置会先备份。确认继续？`
    : `将从 ${name} 的 MCP 配置中移除条目「${key}」。\n原配置会先备份，可用「从备份恢复」还原。继续？`;
  const ok = high
    ? await confirmTypedKeyModal("删除疑似客户端自带条目", msg, key)
    : await confirmModal("删除 MCP 条目", msg, true);
  if (!ok) return;
  await runTaskModal(`删除 ${name} 的 ${key}`, async () => {
    const args = ["--remove-mcp-entry", key, "--client", name, "--format", "json"];
    if (high) args.push("--force-high-risk");
    const res = await runCli(args);
    if (!res) return { ok: false, message: "工具未能执行", detail: "run_cli 无返回" };
    return mcpResultToTask(res, `已删除 ${key}`);
  }, undefined, ["读取 MCP 配置", "备份原配置", "移除条目", "校验回写"]);
}

async function removeMcpClassEntries(name, cls) {
  const box = $("mcpcls-include-high");
  const include = !!(box && box.checked && !box.disabled);
  const label = { legacy: "旧通道", unmanaged: "未纳管", attached: "已挂载" }[cls] || cls;
  const ok = await confirmModal(
    `清理全部${label}`,
    `将移除 ${name} 的全部「${label}」MCP 条目${include ? "（含疑似客户端自带）" : "（默认跳过疑似客户端自带的条目）"}。\n原配置会先备份。继续？`,
    true,
  );
  if (!ok) return;
  await runTaskModal(`清理 ${name} 的${label}`, async () => {
    const args = ["--remove-mcp-class", cls, "--client", name, "--format", "json"];
    if (include) args.push("--include-high-risk");
    const res = await runCli(args);
    if (!res) return { ok: false, message: "工具未能执行", detail: "run_cli 无返回" };
    return mcpResultToTask(res, `${label}已清理`);
  }, undefined, ["读取 MCP 配置", "备份原配置", "移除条目", "校验回写"]);
}

/** 把 --format json 的 MCP 结果转成 runTaskModal 契约（不再字符串匹配）。 */
function mcpResultToTask(res, okMessage) {
  let payload = null;
  try { payload = JSON.parse(stripAnsi(res.stdout || "")); } catch (e) { payload = null; }
  if (!payload) {
    return { ok: false, message: "未识别到结构化结果", detail: cliFailLines(res) || cliErrDetail(res) };
  }
  if (payload.status === "updated") {
    const extra = (payload.attach_updated || []).length
      ? `（已同步摘除挂载声明：${payload.attach_updated.join("、")}）` : "";
    return { ok: true, message: okMessage + extra };
  }
  if (payload.status === "unchanged") return { ok: true, message: "没有匹配到要移除的条目" };
  if (payload.status === "refused") return { ok: false, message: "已拒绝", detail: payload.message };
  if (payload.status === "missing") return { ok: false, message: "配置文件缺失", detail: payload.message };
  return { ok: false, message: "操作未完成", detail: payload.message || cliErrDetail(res) };
}

async function showConfigBackups(name) {
  const res = await runCli(["--list-config-backups", "--client", name, "--format", "json"]);
  let payload = null;
  try { payload = JSON.parse(stripAnsi(res && res.stdout || "")); } catch (e) { payload = null; }
  const backups = (payload && payload.backups) || [];
  const rows = backups.map((b) => `<div class="ad-entry">
      <span class="ad-e-key">${escapeHtml(b.mtime_text)}</span>
      <span class="ad-e-loc">${b.size} B</span>
      <button class="ad-clean" type="button" data-action="restore-config-backup"
        data-name="${escapeHtml(name)}" data-path="${escapeHtml(b.path)}">还原到此版本</button>
    </div>`).join("");
  mountModal(`<div class="modal-backdrop"><div class="modal ad-modal">
    <div class="ad-head"><div class="ad-head-top"><span class="ad-type">${escapeHtml(name)}</span></div>
      <div class="ad-name">配置备份（${backups.length}）</div></div>
    <div class="ad-body"><div class="ad-section"><div class="ad-entries">${rows || '<div class="ad-none">暂无备份</div>'}</div></div></div>
    <div class="ad-foot"><button class="btn-cancel close-push" id="cfgbak-close">关闭</button></div>
    <div class="ad-foot-note">还原是整文件覆盖：该配置文件的全部后续改动都会被回退，不只是 MCP 段落。还原前会把当前文件另存为一份新备份。</div>
  </div></div>`);
  $("cfgbak-close").onclick = closeModal;
}

async function restoreConfigBackup(name, path) {
  const ok = await confirmModal(
    "从备份还原",
    `将用该备份覆盖 ${name} 的整个配置文件（不只是 MCP 段落，全部后续改动都会回退）。\n还原前会把当前文件另存为新备份。继续？`,
    true,
  );
  if (!ok) return;
  await runTaskModal(`还原 ${name} 的配置`, async () => {
    const res = await runCli(["--restore-config-backup", path, "--client", name, "--format", "json"]);
    if (!res) return { ok: false, message: "工具未能执行", detail: "run_cli 无返回" };
    return mcpResultToTask(res, `已还原 ${name} 的配置`);
  }, undefined, ["校验备份归属", "备份当前配置", "写回备份内容", "解析校验"]);
}
```

- [ ] **Step 5: 分发器加 4 个 action**

在 L4258（`show-mcp-class` 分支）之后插入：

```javascript
    else if (a === "remove-mcp-entry") removeMcpEntry(act.dataset.name, act.dataset.key, act.dataset.high === "1", act.dataset.reason);
    else if (a === "remove-mcp-class") removeMcpClassEntries(act.dataset.name, act.dataset.class);
    else if (a === "show-config-backups") showConfigBackups(act.dataset.name);
    else if (a === "restore-config-backup") restoreConfigBackup(act.dataset.name, act.dataset.path);
```

- [ ] **Step 6: 客户端详情弹窗条目行加删除**

在 `showAgentDetail` 的条目渲染（L3283-3286）中，把 `legBtn` 改为通用删除按钮：

```javascript
    const delBtn = a.fix_supported
      ? `<button class="ad-clean" type="button" data-action="remove-mcp-entry"
           data-name="${escapeHtml(name)}" data-key="${escapeHtml(e.key)}"
           data-high="${e.high_risk ? "1" : "0"}"
           data-reason="${escapeHtml(e.risk_reason || "")}">删除</button>`
      : "";
    return `<div class="ad-entry"><span class="ad-e-key">${escapeHtml(e.key)}</span><span class="tag ${color}">${escapeHtml(label)}</span>${e.high_risk ? '<span class="tag warn" title="' + escapeHtml(e.risk_reason || "") + '">客户端自带?</span>' : ""}<span class="ad-e-loc" title="${escapeHtml(loc)}">${escapeHtml(loc)}</span>${delBtn}</div>`;
```

并在该弹窗的 cleanbar（L3313）里，把「清理旧 MCP」按钮旁补一个未纳管清理入口：

```javascript
        ${legacyCount > 0 || unmanagedCount > 0 ? `<div class="ad-cleanbar"><span class="ad-clean-note">${legacyCount > 0 ? `${legacyCount} 个旧通道` : ""}${legacyCount > 0 && unmanagedCount > 0 ? "，" : ""}${unmanagedCount > 0 ? `${unmanagedCount} 个未纳管` : ""}</span>${a.fix_supported && legacyCount > 0 ? `<button class="ad-clean-btn" type="button" data-action="remove-mcp-class" data-name="${escapeHtml(name)}" data-class="legacy">清理旧通道</button>` : ""}${a.fix_supported && unmanagedCount > 0 ? `<button class="ad-clean-btn" type="button" data-action="remove-mcp-class" data-name="${escapeHtml(name)}" data-class="unmanaged">清理未纳管</button>` : ""}<button class="ad-clean-btn" type="button" data-action="show-config-backups" data-name="${escapeHtml(name)}">从备份恢复</button></div>` : ""}
```

- [ ] **Step 7: 语法自检**

Run:

```bash
node --input-type=module -e "
import fs from 'fs';
const html = fs.readFileSync('gui/dashboard.html','utf8');
const m = html.match(/<script>([\s\S]*)<\/script>/);
new Function(m[1]);
console.log('dashboard.html inline script parses OK');
"
```

Expected: `dashboard.html inline script parses OK`（若为一个以上 `<script>`，改为逐个抽取后分别 `new Function` 校验）

- [ ] **Step 8: 提交**

```bash
git add gui/dashboard.html
git commit -m "feat(gui): MCP 页支持删除/清理条目（含未纳管）与从备份恢复"
```

---

## Task 8: 文档与真机验收

**Files:**
- Modify: `README.md`、`docs/design/详细设计文档-阶段五增量-MCP条目删除与清理.md`

- [ ] **Step 1: README 命令速查补 4 个参数**

在 README 的 CLI 命令速查/表格中，比照 `--list-mcp-inventory` 那一行的写法补入：

```markdown
| `--remove-mcp-entry KEY[,KEY...] --client <名>` | 移除指定 MCP 条目（高风险需 `--force-high-risk`） |
| `--remove-mcp-class attached\|legacy\|unmanaged --client <名>` | 按分类批量清理（默认跳过高风险） |
| `--list-config-backups --client <名>` | 列出该客户端配置的历史备份 |
| `--restore-config-backup <备份路径> --client <名>` | 从备份还原配置（整文件覆盖） |
```

- [ ] **Step 2: 设计文档状态改为已实施**

把设计文档头部的 `- 状态：设计已评审（待实施）` 改为 `- 状态：已实施（v0.20.2 起）`。

- [ ] **Step 3: 跑全量测试**

Run: `python3 -m pytest tests/ -q`
Expected: 与改动前基线一致。改动前基线为 **384 passed, 1 failed**——那 1 个失败是既有的
`tests/test_config_store.py::OverlayRegistrationTest::test_overlay_target_reuses_first_existing_profiles_local`
（用例顺序污染，单跑通过、干净 HEAD 上同样失败），**不是本次引入**。新增测试应全部通过。

- [ ] **Step 4: 一致性 gate**

Run: `scripts/verify_gui_consistency.sh -c config.yaml`
Expected: 退出码 0，GUI 结论 == CLI 结论

- [ ] **Step 5: 真机验收（只动测试残留，不真删客户端自带条目）**

```bash
# 1) 备份基线
python3 scan.py --list-config-backups --client WorkBuddy --format json

# 2) 删除测试残留 my-mcp
python3 scan.py --remove-mcp-entry my-mcp --client WorkBuddy --format json

# 3) 确认条目已消失且出现了 my-mcp
python3 scan.py --list-mcp-inventory | grep -A 6 "\[WorkBuddy\]"

# 4) 确认 Codex 自带条目仍被拦（不应真的删除）
python3 scan.py --remove-mcp-entry node_repl --client Codex --format json; echo "exit=$?"

# 5) 从备份还原
python3 scan.py --list-config-backups --client WorkBuddy --format json
python3 scan.py --restore-config-backup <第 5 步列出的最新备份路径> --client WorkBuddy --format json
python3 scan.py --list-mcp-inventory | grep -A 6 "\[WorkBuddy\]"
```

Expected:
- 第 2 步 `status=updated`，返回 `backup` 路径
- 第 3 步 WorkBuddy 下不再出现 `my-mcp`（`hermes` / `K8s-uat` 仍在）
- 第 4 步 `status=refused`，`exit=2`，`~/.codex/config.toml` 未被改动
- 第 5 步还原后 `my-mcp` 重新出现

- [ ] **Step 6: 提交**

```bash
git add README.md docs/design/详细设计文档-阶段五增量-MCP条目删除与清理.md
git commit -m "docs: 补 MCP 条目删除/清理命令说明并将设计文档标记为已实施"
```

---

## Self-Review 记录

**1. Spec coverage（逐条对照设计文档）：**

| 设计文档要求 | 落地任务 |
| --- | --- |
| §3.1 三类条目语义 + attached 声明同步 + key/name 映射 | Task 4 |
| §3.1 缺省 attach 物化显式列表 | Task 4（`resolve_client_attach` 得全量后减去被删项） |
| §3.1 / §3.4 空声明拒绝且不落盘 | Task 4（`empty_declaration` 分支在写盘前） |
| §3.2 高风险 R1/R2/R3 + reason | Task 1 |
| §3.2 高危门（CLI `--force-high-risk`、批量 `--include-high-risk`） | Task 6 + Task 4 |
| §3.3 安全链（备份→原子写→校验） | Task 2（复用）+ Task 3 |
| §3.4 拒绝条件 missing/unsupported/unchanged | Task 2 测试覆盖 |
| §5 4 个 CLI 参数 + JSON 输出 | Task 6 |
| §6 备份列出 + 整文件还原 + 还原前再备份 | Task 3 |
| §7.1 快照补 high_risk / risk_reason | Task 5 |
| §7.2 UI 五处改动 | Task 7 |
| §8 测试与验收 | Task 1-5 测试 + Task 8 验收 |
| §9 明确不做 | 无对应任务（符合预期） |

无缺口。

**2. Placeholder scan：** 无 TBD/TODO/「类似任务 N」；每个代码步骤都给出完整代码。

**3. Type consistency：**
- `is_high_risk_entry(entry, tool) -> (bool, str)` 在 Task 1 定义，Task 4/5 均按此签名调用。
- `remove_mcp_entries_tool(tool, keys, *, dry_run, messages) -> Dict[str,str]` 在 Task 2 定义，Task 4 按此调用。
- `restore_config_backup(tool, backup_path, *, dry_run)` 在 Task 3 定义，Task 6 按此调用。
- `remove_entries(config, client_name, keys, *, force_high_risk, dry_run)` / `remove_class(config, client_name, klass, *, include_high_risk, dry_run)` 在 Task 4 定义，Task 6 按此调用。
- 结果字典 key 统一为 `status / message / path / backup / removed / skipped_high_risk / attach_updated`，Task 6 的 `_print_mcp_result` 与 Task 7 的 `mcpResultToTask` 均按此读取。
- 前端 action 名 `remove-mcp-entry` / `remove-mcp-class` / `show-config-backups` / `restore-config-backup` 在 Task 7 的 Step 3/4/5 三处一致。
- 新增 `validate_config_text(tool, text)` 在 Task 3 定义并由 `config_backups` 调用。

**已知偏差（需在实施时留意）：** Task 5 的 Step 3 与 Task 8 的验收以本机 2026-09-20 实测形状为准（Codex 两条自带条目、WorkBuddy `my-mcp` 为测试残留）。若届时机器状态已变，以实际输出为准判断，不强行套用期望值。
---

## 实施过程记录：计划执行中暴露的缺陷

本节由实施过程中回填；计划正文保留原样，便于对照「计划写的」与「实际做的」。

### Task 1 暴露

1. **测试导入约定写错**：计划原文写「测试一律用 `from core.<module> import ...`」，与仓库实际
   约定（34/35 个测试文件用「路径头 + 扁平导入」）不符；且 `from core.X` 依赖 pytest 把仓库根
   注入 `sys.path`，单文件直接 `python3 tests/test_x.py` 会失败。已把「前置约定」及 Task 1/2/3/4
   的测试片段统一为「路径头 + 扁平导入」，并把 `tests/test_mcp_entry_risk.py` 改为扁平导入
   （直跑与 pytest 均通过）。
2. **测试条数写错**：Task 1 原写「9 passed」，实际测试代码只有 8 个用例，已改为 8。

### Task 2 暴露

3. **实现代码与它自己的测试自相矛盾**：计划给的 `_render_without_entries`（沿用改动前的
   `_render_without_legacy`）在 JSON/JSONC/YAML/Reasonix 四个分支**无条件重新序列化**，因此当
   配置中没有任何待删 key 时 `rendered == original` 永远为假，会把「无操作」误报成 `updated`，
   并顺手改写用户配置、生成备份；而计划自己的 `test_unknown_key_reports_unchanged` 与
   `test_legacy_unchanged_message_is_byte_identical` 要求返回 `unchanged`——两者不可能同时成立
   （实测：这两个用例在改动前的 HEAD 上同样失败）。

   实施时按仓库取向「修实现、不改测试」处理：为这四个分支补上
   `if not any(name in current for name in targets): return text` 短路，使六种格式统一满足
   「无命中则原样返回」，与既有 cordis 分支的 `if len(filtered) == len(data): return text`
   不变式对齐。副作用：`--remove-legacy-mcp` 在「配置里已无旧通道条目」时，由原来的假 `updated`
   （改写配置 + 建备份）纠正为 `unchanged`；三条 legacy 结果文案逐字未变，GUI 的字符串匹配不受
   影响（`tests/test_mcp_fixer.py` 27 passed 全绿）。
   另：`updated` 结果现在多带 `backup` 字段（计划代码即如此），`scan.py` 只读 status/message/path，
   无影响。

### 流程缺陷（非计划内容）

4. **不要边提交边并发派发子代理，也不要把「写入」和「校验」放进同一个消息块**：同一消息块内的
   多个工具调用会并发执行，校验/提交会读到写入前的状态。Task 2 因此与我的计划修正提交竞争，
   导致那次提交丢失（改动留在工作区，已重新提交为 `d380331`）。此后一律：单次调用内顺序完成
   写入+提交，校验放在下一条消息。

### Task 3 暴露

5. **`validate_config_text` 对 `jsonc` 过严**：它（以及 `_render_without_entries` 的 jsonc 分支）
   用的是 `json.loads`，而 JSONC 语义允许注释。实测：带 `// 注释` 的 jsonc 备份在还原路径上会被
   判为「备份内容解析失败」而 `refused`；去掉注释的同样内容则 `updated`（对照组已证明差异只来自
   注释）。这是从 `_render_without_legacy` 继承的既有口径，不是 Task 3 新引入；本机现有
   `~/.config/opencode/*.jsonc.bak-*` 恰好无注释，故未触发。修法需新增一个能识别字符串字面量的
   jsonc 注释剥离函数（纯正则会把 `"https://…"` 截断），建议作为独立小任务。

### Task 4 暴露

6. **Task 4 的测试 fixture 缺 `profile_sources`**：计划 `_config()` 只造了 `mcp_tools` 与 `profiles`，
   但删除 attached 条目后要调 `endpoint_store.set_client_attach()` 落盘挂载声明，而该函数经
   `_write_target` → `_source_paths` 只读顶层 `profile_sources`；为空时直接返回
   `{"status": "error", "message": "no profile_sources configured"}`，导致
   `test_attached_removal_drops_endpoint_key_not_config_key` **必然断言失败（与实现无关）**。
   实施时在 fixture 内补齐：在用例的 `TemporaryDirectory()` 里造一个真实的 overlay 目标文件并在
   config 顶层加 `profile_sources: [<overlay>]`；调用点与断言强度均未改动，另加两条断言证明
   挂载声明确有真实落盘、且空声明被拒时 overlay 也未被改动。

### Task 6 暴露

7. **路由落点不可达（计划代码与计划自己的验收自相矛盾）**：计划 Step 4 要求把 4 条路由插在
   `--remove-legacy-mcp`（L1489）之前。但 `scan.py` L1332 已有一条更早的通用路由
   `if getattr(args, "format", None) in ("json", "csv", "md"): return _run_single_profile_snapshot(...)`，
   会把带 `--format json` 的新命令先截走；而计划 Step 5 的第 2/3/4 条验证、Task 7 GUI 的全部调用
   以及 Task 8 验收**都要靠 `--format json`**。按计划落点实现，这些命令永远到不了新分支，stdout
   还会混入阶段一二三的报告，使 Task 7 的 `JSON.parse(整个 stdout)` 必然失败。
   实施时改为放进与 `--attach-endpoints` / `--list-mcp-inventory` 同一组「阶段五早返回」分支
   （仍在 `--remove-legacy-mcp` 之前，且早于 `--format` 快照路由），实测 stdout 为纯 JSON。
8. **文档口径不一致**：File Structure 表与 §5 自检表写「4 个 CLI 参数」，实际是 6 个
   （`--force-high-risk` / `--include-high-risk` 未计入）；正文相应表述以本节为准。
9. **`--list-config-backups` 的匹配口径宽于归属校验（安全，但需在文档里讲清）**：它按
   `config_path + ".bak-"` 前缀匹配，会把非本模块生成的备份（如
   `config.toml.bak-memory-remediation-20260920-163013`）也列出来（本机 Codex 的 20 个备份里就有 1 个）。
   因为 `restore_config_backup` 用**同一前缀**做归属校验，凡列出的都能还原，故不是 bug；但
   「列出即可控」的暗示应在 Task 8 的文档里说明。

### Task 7 暴露

10. **【最关键】File Structure 表漏了 `src-tauri/src/lib.rs`，导致桌面版四个功能全部不可用**：桌上壳的
    `run_cli` 对 argv 首个 `--flag` 做白名单校验（`ALLOWED.contains(&bare)`，否则返回
    `Err("run_cli: 子命令 … 不在白名单内（安全边界）")`）。计划只列了 `scan.py` 与 `gui/dashboard.html`，
    新命令不在白名单里 → `runCli` 拿到 null → 四个按钮一律显示「工具未能执行」，即「渲染了按钮但
    没人能处理」的半成品。已补 4 个 flag（`lib.rs:188-191`）并用仓库内 Rust 工具链跑
    `cargo check --offline` 验证通过（exit 0）。**凡新增 CLI 参数，必须同时改这里**——这是既有
    铁律（写盘在 CLI、壳只透传 argv），计划应当显式列出，而不是等到实现时才发现。
11. **批量清理「全部被跳过高危」时不能报成功**：真实 CLI 在该情形返回 `status=unchanged` +
    `skipped_high_risk`。计划的分支会显示成 ✅「没有匹配到要移除的条目」，用户会以为已清干净。
    已改为失败态 + 逐条列出 reason。
12. **计划用了不存在/不生效的东西**：`.cfm-typed` CSS 类未定义；`.cfm-msg` 无 `white-space: pre-line`，
    而计划的确认文案都带 `\n`（多行会挤成一行）；计划还无条件渲染一个 disabled 的
    「包含疑似客户端自带（0）」勾选框。均已修正。另：计划里 `mountModal` / `stripAnsi` 等假设
    **确实存在**，行号则全部漂移（一律按函数名定位）。
13. **计划沿用了既有 footNote 里的假话**：旧文案称「清理前会先做统一端点活体探测」，但
    `remove_legacy_mcp_tool` 的 docstring 明确写了删除不以正典端点接入为前提，代码里也没有探测。
    该句已随本次改动删除。
14. **Task 7 无法在 Task 7 内完成实弹验证**：`tauri.conf.json` 的 `frontendDist: "../gui"` 意味着
    dashboard.html 是**构建期**拷进 bundle 的，加上本次改了 Rust 白名单，必须重建 .app 才能在桌面端
    点按钮。计划的 Step 7 只做语法自检，这一点应在 Task 8 的验收步骤里写明。

### Task 8 暴露

15. **【阻断项】工作区外不可写，真实客户端配置的往返验收无法完成**：沙箱对 `~/.workbuddy`、`~/.codex`
    一律 `Operation not permitted`（`os.access(dir, W_OK) → False`，`shutil.copy2 → PermissionError`），
    子代理权限不可放宽。**这不是产品缺陷**——产品在该环境下正确失败并保持文件零改动
    （`{"status":"error","message":"无法创建备份，未做改动"}`，前后 sha256 一致），且只读路径可达
    （真实文件 dry-run 返回 `将移除：my-mcp`）。替代方案已跑通：对真实文件的可写副本走同一产品路径，
    完成「删除 → 条目消失 → 备份内容 == 原文 → 还原 → sha256 回到基线」全往返。
    **遗留**：真实 `~/.workbuddy/mcp.json` 上的实弹往返仍需有写权限的会话补跑。
16. **D 段的验收方法本身有陷阱（计划未预料）**：「bundle 里有 dashboard.html」这个前提不成立——Tauri 2
    把 `frontendDist` 资源 **brotli 压缩后 `include_bytes!`** 进二进制，bundle 内没有该文件，且
    `strings` / `grep -a` 对**任何** HTML 文本（含既有字符串）都是假阴性。正确做法：解压
    `out/tauri-codegen-assets/*.html`，验证其 sha256 与 `gui/dashboard.html` 相同、且这些压缩字节
    逐字出现在 .app 二进制中（本次：273409 B 源文件 ≡ 解压结果，4 个新 action 名 ×2/×1 命中）。
17. **BUILD.md §3 的 PATH 写法在本环境失效**：`PATH="$CARGO_HOME/bin:$PATH"` 中 `$CARGO_HOME` 含 `..`
    会导致 `cargo: command not found`（直接绝对路径可用）。应改为归一化后的绝对路径。
18. **计划 Task 8 未包含「重建 .app + 验证前端与白名单已进产物」**：因 `frontendDist: "../gui"` 是构建期
    嵌入、且本次改了 Rust 白名单，不重建就无法在桌面端点按钮（Task 7 第 14 条）。Task 8 应显式包含
    构建与产物内验证。
19. **GUI 实弹点击仍未验证**：产物内验证只证明「前端已进 bundle、白名单已进二进制」，未点击过任何
    新按钮；`run_cli` 的真实 argv 透传、`mcpResultToTask` 的运行时 JSON 解析、强确认弹窗的手输解锁
    均未在运行时走通。这需要安装构建产物后人工或用 UI 自动化完成。

### Task 8 收尾（本次会话补跑）

以上第 15 条列为「阻断项」的真实往返验收，已在**有写权限**的会话中补跑完成，产品行为全链路正确：

| 步骤 | 实测结果 |
| --- | --- |
| 基线 | `~/.workbuddy/mcp.json` sha256 `0d3c7609…`，既有备份 4 个 |
| 真实删除 `my-mcp` | `status=updated`，exit 0，返回 `backup=…bak-20260920-183233-532370` |
| 条目消失 | `[WorkBuddy]` 仅剩 `context7`(unmanaged) / `hermes`(attached) / `K8s-uat`(attached) |
| 备份正确性 | 备份 sha256 == `0d3c7609…`（**等于删除前原文**）；删除后文件为 `06d5e310…` |
| 安全门 | Codex `node_repl` → `status=refused` + 真实 `risk_reason`，exit 2；`~/.codex/config.toml` sha256 保持 `574232dd…` **未被触碰** |
| 还原 | `status=updated`，且**还原前自动再备份**当前配置（`…bak-20260920-192435-839984`） |
| 回滚验证 | `my-mcp` 回到列表，sha256 **精确回到基线** `0d3c7609…` |

另：第 17 条（BUILD.md PATH）已修（提交 `5631c54`）——归一化写法实测可解析
（`cargo 1.98.1`），原始含 `..` 写法稳定复现 `command not found`。

**仍未验证**：GUI 实弹点击（需把新构建安装到 `/Applications`，属改动用户已装发行版，
留待用户决定）。
