# 交接文档：v0.29.0 Hook 写入可配置 + ai-memory 剥离

> 创建时间：2026-10-16
> 用途：在其他设备上继续开发 v0.29.0

## 1. 当前状态

### 1a. 版本与代码

| 项 | 值 |
|---|---|
| 当前版本 | v0.28.0 (build 122)，已发布（tag v0.28.0 推送至 codeup + github） |
| 分支 | develop（与 origin 同步，工作区干净） |
| HEAD | `48bcfcd` docs: 设计文档 v3 |
| 已安装 app | /Applications/skill-mcp-studio.app (0.28.0) |
| CI | 四 workflow 全绿（Test / Build macOS / Build Windows / Build Linux） |
| 测试 | 1200 tests OK（CI_ALLOW_SKIP_DRIFT=1） |

### 1b. 环境要求

```bash
# 仓库内自带工具链（不需要全局安装 Rust）
export RUSTUP_HOME="$PWD/.rustup-home"
export CARGO_HOME="$PWD/.cargo-home"
export PATH="$CARGO_HOME/bin:/opt/homebrew/bin:$PATH"

# 门禁
CI_ALLOW_SKIP_DRIFT=1 bash scripts/ci_parity.sh

# 构建
cd src-tauri && cargo tauri build
```

### 1c. 远端

| 远端 | URL | 用途 |
|---|---|---|
| codeup | `codeup-oswaldhill:oswaldhill/skill-mcp-studio.git` | 主开发 |
| github | `github.com:oswaldhill/skill-mcp-studio.git` | CI + Release |

两者配置为同一 origin 的双 push URL，一次 `git push origin develop` 同步两边。

## 2. 待做的工作：v0.29.0

### 2a. 设计文档（已完成，已评审）

文档路径：`docs/superpowers/specs/2026-10-16-hook-write-configurable-design.md`（428 行）

已通过四维评审（安全/架构/产品/测试），修复了 5 个阻断项 + 6 个改进建议。关键设计决策：

1. **三函数提取到 config_codec.py**（不是内联到 hooks_inventory）：hooks_fixer.py:22 也依赖 `_find_in_dict`，原设计遗漏
2. **能力组不改名**：`ai_memory` 能力组保留（它是记忆能力组，改名有语义错位），改为解耦——profile 显式 `hooks_required: true`
3. **fix_supported 动态化**：`declared and (has_agent_slug or has_template)`，否则 template 清空后"显示支持但实际零写入"
4. **用户配置迁移**：保留旧值 + warn 标记 + 命令可执行性校验 + 引导 banner
5. **移除 Hook 全删**：确认框文案改为"清除全部 hook 条目（含第三方）"
6. **模板预设扩到 5 种**：empty / logging / webhook / local-script / custom
7. **用例数**：删 28（非 ~10），预期 1172（非 1190）
8. **grep 零命中**：拆为强（core/config/gui）/ 弱（scan.py 豁免别名）/ tests（排除 legacy 示例名）

### 2b. 实施步骤（按执行顺序）

**第一步：B 轨（必须先于 A 轨）**

1. 把 `_load_toml_file` / `_find_in_dict` / `_extract_hook_commands` 从 `ai_memory_checker.py` 提取到 `core/config_codec.py`
2. `hooks_inventory.py` 改为 `from config_codec import ...`
3. `hooks_fixer.py` 改为 `from config_codec import _find_in_dict`
4. 跑测试确认绿

**第二步：D 轨**

5. `hooks_inventory.py`：移除 `is_ai_memory` 字段改为 `is_configured`，移除 `_is_ai_memory_hook_cmd`
6. `hooks_fixer.py`：`_default_hook_command` 返回空字符串，L183 删除 `e.is_ai_memory` 过滤，`_filter_ai_memory_from_event` 改为 `_filter_all_hooks` 全删，`remove_hooks_tool` 改为全删
7. `hooks_inventory.py`：补 `fix_supported` 运行时重算（`declared and (has_agent_slug or has_template)`）
8. docstring/注释里的 "ai-memory" 改为中性措辞

**第三步：C 轨**

9. `config.yaml`：template 清空、新增 `default_command` 和 `agent_slug`、profiles 段新增 `hooks_required: true`

**第四步：E 轨**

10. `combined_checker.py`：`hooks_required` 改为 `required.get("hooks_required", False)`（解耦），保留 `ai_memory_available` 字段
11. `legacy_checker.py`：删除 `AI_MEMORY_DETECTION` 常量和 `DEFAULT_DETECTIONS` 里的引用
12. `scan.py`：输出文案里的 "ai-memory" 改为 "Hook 命令"，`--ai-memory`/`--fix-ai-memory` 保留为别名
13. `cli_modes.py`：文案改写
14. `hooks_checker.py`：`"ai-memory" in command` 改为 `bool(command.strip())`

**第五步：A 轨（删文件）**

15. 删除 `core/ai_memory_checker.py`
16. 删除 `scripts/unified_mcp_server.py`
17. 删除 `tests/test_ai_memory_section_guard.py`
18. 删除 `tests/test_unified_mcp_server.py`

**第六步：F 轨（GUI）**

19. `gui/dashboard.html`：Hook 页文案改写（所有面向用户的 "ai-memory" 改为中性措辞）
20. 移除 Hook 确认框文案改为"清除全部 hook 条目（含第三方）"
21. 新增"写入命令模板"卡片（结构见设计文档 §3.7b）

**第七步：G 轨（测试）**

22. 改写 17 个测试文件（分类见设计文档 §3.8）
23. 注意 `test_mcp_fixer.py` / `test_mcp_entry_removal.py` 的 "ai-memory" 是 legacy 示例名，**不改**
24. 新增反向断言（主干源码零 ai-memory 命令字符串）

**第八步：新增 CLI 命令**

25. `scan.py` 新增 `--list-hook-templates` / `--set-hook-template` / `--apply-hook-preset`
26. Rust 白名单加这三条

**第九步：H 轨（文档）**

27. PRD §6.4 新增需求、§8 新增边界、§10 新增已关闭项
28. DESIGN.md §2.10 新增"命令模板编辑"卡片规范
29. SECURITY.md 删除对 `unified_mcp_server.py` 的引用
30. CHANGELOG 记录
31. README / SKILL.md 移除 ai-memory 引用

**第十步：验证**

32. 跑全量门禁（预期 1172+ tests OK）
33. grep 零命中验证（强/弱/tests 三级，见设计文档 §6b）
34. 反向断言验证
35. 构建 + 安装 + 确认

### 2c. 注意事项

- **bash 通道在本设备上不稳定**：经常出现 `FileNotFoundError`（文件存在但读不到），用 harness 的 `read`/`edit`/`grep` 工具替代 bash 读写
- **build_gui.py 会拆分 HTML**：`gui/dashboard.html` 的 `<script>` 在构建时被拆到 `gui/dist/app.js`，注释里的花括号会被括号平衡门禁计数（不要在注释里写裸 `}`）
- **_fn 提取器**：测试用 `"\n}\n"` 定位函数结尾，不要在函数体内写顶格 `}`（会被误判为函数结束）
- **NoLiteralSpacingTest**：CSS 里不能写字面 px 值（必须用 token）
- **ruff F401**：删除文件后检查是否有未清理的 import

## 3. 后续版本规划（v0.30+）

| 版本 | 范围 | 设计文档 |
|---|---|---|
| v0.30.0 | Windows/Linux 打包完善 + 配置导入/导出（iCloud + WebDAV） | 待写 |
| v0.31.0 | 技能版本管理 + 市场更新检查 + 技能依赖关系图 | 待写 |
| v0.32.0 | MCP 端点健康看板 + 变更通知渠道扩展 | 待写 |
| v0.33.0 | 多环境 Profile 预设 + 技能仓库 Git 同步 + 技能搜索增强 | 待写 |

路线图完整清单见 `docs/product/产品定位与路线图规划.md` §4c/§4d。

## 4. 关键文件索引

### 设计文档

| 文件 | 内容 |
|---|---|
| `docs/superpowers/specs/2026-10-16-hook-write-configurable-design.md` | v0.29.0 设计文档（428 行，已评审） |
| `docs/superpowers/specs/2026-10-15-auto-discover-active-profile-gui-design.md` | v0.28.0 自动发现设计（已完成） |

### 产品文档

| 文件 | 内容 |
|---|---|
| `docs/product/PRD-产品需求文档.md` | 产品需求权威（§10 待实现项已全部关闭） |
| `docs/product/产品定位与路线图规划.md` | 路线图（§4c 功能增强清单 + §4d 版本路线图 + §6b 产品治理评估） |
| `docs/decisions/决策记录-待决问题定案.md` | ADR D1-D13 |

### 界面规范

| 文件 | 内容 |
|---|---|
| `docs/DESIGN.md` | 832 行 31 章节（Token / 组件 / 状态 / 检查清单 / 双轨机制） |

### 代码结构

| 目录 | 内容 |
|---|---|
| `core/` | 61 个 Python 模块（16808 行） |
| `src-tauri/src/` | Rust 后端（1221 行） |
| `gui/dashboard.html` | 单文件 GUI（7578 行） |
| `scripts/` | 8 个脚本（build_gui / ci_parity / release / bump_version 等） |
| `tests/` | 95 个测试文件（19606 行，1200 用例） |

### 核心代码（v0.29.0 改动涉及的）

| 文件 | 当前行数 | 改动内容 |
|---|---|---|
| `core/ai_memory_checker.py` | ~300 | 删除 |
| `scripts/unified_mcp_server.py` | ~750 | 删除 |
| `core/hooks_fixer.py` | ~378 | 改写（D 轨） |
| `core/hooks_inventory.py` | ~290 | 改写（D 轨） |
| `core/combined_checker.py` | ~450 | 解耦 hooks_required（E 轨） |
| `core/legacy_checker.py` | ~180 | 删除 AI_MEMORY_DETECTION（E 轨） |
| `core/config_codec.py` | ~300 | 新增三函数（B 轨） |
| `scan.py` | ~3000 | 文案改写 + 新增 CLI 命令 |
| `gui/dashboard.html` | ~7578 | 文案改写 + 新增卡片 |
| `config.yaml` | ~600 | template 清空 + 新字段 |
| `src-tauri/src/lib.rs` | ~1221 | 白名单新增 |

## 5. 在新设备上开始

```bash
# 1. 克隆仓库
git clone <codeup 或 github URL>
cd skill-mcp-studio

# 2. 确认工具链
export RUSTUP_HOME="$PWD/.rustup-home"
export CARGO_HOME="$PWD/.cargo-home"
export PATH="$CARGO_HOME/bin:/opt/homebrew/bin:$PATH"

# 3. 确认在 develop 分支且与远端同步
git checkout develop
git pull origin develop

# 4. 跑门禁确认环境正常
CI_ALLOW_SKIP_DRIFT=1 bash scripts/ci_parity.sh

# 5. 阅读设计文档
cat docs/superpowers/specs/2026-10-16-hook-write-configurable-design.md

# 6. 按 §2b 的步骤开始实施
```
