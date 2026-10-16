# Hook 写入可配置 + 全面剥离 ai-memory

> v0.29.0 核心改动。本文是设计文档，不是产品方案。

## 1. 背景

Skill MCP Studio 从 `skills-mcp-unifier` 演化而来，`ai-memory` 是早期绑定的一个**外部 MCP 服务**。它的命令被硬编码进了 `config.yaml` 的 `hooks.clients[].template` 段，成了"默认 Hook 写入内容"。同时 `ai_memory_checker.py` 和 `unified_mcp_server.py` 作为 ai-memory 的专属检查器和 HTTP 网关代理住在了主干代码库里。

用户明确要求：**ai-memory 是外部 MCP 的功能，不是本产品的组成部分，全部剥离。** Hook 写入命令应完全由用户自定义。

## 2. 改动总览

| 轨 | 内容 | 文件数 |
|---|---|---|
| A | 删除 ai-memory 专属模块 | 4 |
| B | 提取公共解析原语 | 1 新 + 1 改 |
| C | config.yaml template 改为空模板 | 1 |
| D | hooks_fixer / hooks_inventory 改写 | 2 |
| E | scan.py / cli_modes / combined_checker / legacy_checker 改写 | 4 |
| F | GUI 文案改写 | 1 |
| G | 测试改写 | ~15 |
| H | 文档改写 | ~8 |

## 3. 详细设计

### 3.1 删除的文件（A 轨）

| 文件 | 理由 |
|---|---|
| `core/ai_memory_checker.py` | ai-memory MCP 条目检查器，专属外部服务 |
| `scripts/unified_mcp_server.py` | ai-memory HTTP 网关代理，专属外部服务 |
| `tests/test_ai_memory_section_guard.py` | 上述模块测试 |
| `tests/test_unified_mcp_server.py` | 上述模块测试 |

### 3.2 提取公共解析原语（B 轨）

`hooks_inventory.py` 从 `ai_memory_checker` 导入了三个函数：

- `_load_toml_file(filepath)` — 加载 TOML 文件
- `_find_in_dict(data, key_path)` — 在嵌套字典里按键路径取值
- `_extract_hook_commands(hook_section)` — 从 hook 段提取命令列表

这三个是**通用 JSON/TOML 解析原语**，与 ai-memory 无关。将它们内联到 `hooks_inventory.py` 自身（该模块已有 `_load_json_file`，补一个 `_load_toml_file` 即可；`_find_in_dict` 和 `_extract_hook_commands` 内联为模块内私有函数）。不新建文件，避免增加模块数。

### 3.3 config.yaml template 改为空模板（C 轨）

**改前**（6 个客户端，每个 template 段硬编码 `ai-memory hook --event ...`）：

```yaml
hooks:
  clients:
    - name: Claude Code
      template:
        SessionStart: ai-memory hook --event session_start
        # ...
```

**改后**（template 段全部清空，用户在 GUI 自行填写）：

```yaml
hooks:
  default_command: ""        # 全局默认命令模板（空 = 不写入兜底）
  clients:
    - name: Claude Code
      agent_slug: claude-code  # 新增：ai-memory 的 agent slug（如有）
      fix_supported: true      # 改为：有 agent_slug 且 template 非空时才 true
      template: {}             # 空：用户自行配置
```

`agent_slug` 字段：保留但不绑定 ai-memory。它的语义是"该客户端在 MCP 端点的 agent 标识"，可用于命令模板的 `{agent}` 变量插值。值来自 config.yaml 声明，与 ai-memory 无关。

WorkBuddy / TRAE：不填 `agent_slug`，`fix_supported: false`（已有此机制，保持不变）。

### 3.4 hooks_fixer.py 改写（D 轨）

| 函数 | 改前 | 改后 |
|---|---|---|
| `_default_hook_command` | 返回 `ai-memory hook --event <snake>` | 返回空字符串 `""`（空 = 不写入兜底，该事件跳过） |
| `_build_hook_entry` | 不变 | 不变（结构正确，与 ai-memory 无关） |
| `_filter_ai_memory_from_event` | 只过滤 ai-memory 签名的 hook 条目 | 改名为 `_filter_managed_hooks`，过滤"由本工具写入的"条目（标记机制见下） |
| `remove_hooks_tool` | 只移除 ai-memory hook | 改为移除**全部 hook 条目**（用户明确操作"移除 Hook"就是全删，不是只删某工具的） |

**标记机制**：不再用命令签名识别"哪些是我们写的"。改为：移除时**全删**该事件的 hook 条目。如果用户有第三方 hook 不想被删，不应该用"移除 Hook"按钮——那个按钮的语义是"清除该事件的所有 hook 配置"。

docstring 和注释里所有 "ai-memory" 字样改为中性措辞（"Hook 命令模板"、"由用户配置的命令"）。

### 3.5 hooks_inventory.py 改写（D 轨）

| 改动 | 说明 |
|---|---|
| 移除 `from ai_memory_checker import ...` | 改为内联的 `_load_toml_file` / `_find_in_dict` / `_extract_hook_commands` |
| 移除 `_is_ai_memory_hook_cmd` | 不再需要识别"是否 ai-memory" |
| 移除 `HookEntry.is_ai_memory` 字段 | 改为 `HookEntry.is_configured`（只要命令非空即为 True） |
| 移除 `is_ai_memory` 的所有引用 | 改为 `is_configured` |
| docstring / 注释里的 "ai-memory" | 改为 "Hook 命令" |

### 3.6 scan.py / cli_modes / combined_checker / legacy_checker 改写（E 轨）

| 文件 | 改动 |
|---|---|
| `scan.py` | `--ai-memory` 和 `--fix-ai-memory` 参数保留为**纯别名**（向后兼容），但 help 文本改为"已废弃，改用 --mcp / --fix-hooks"。输出文案里的 "ai-memory" 改为 "Hook 命令" |
| `cli_modes.py` | `--ai-memory` 路由保留（别名），文案改写 |
| `combined_checker.py` | `ai_memory` 能力组改为 `hook_lifecycle`（中性命名）。`hooks_required = "ai_memory" in required` 改为 `hooks_required = "hook_lifecycle" in required` |
| `legacy_checker.py` | `AI_MEMORY_DETECTION` 检测块移入 `profiles-hermes-home/`（profile 专属），主干删除 |
| `hooks_checker.py` | `"ai-memory" in command` 改为通用判定（命令非空即算已配置，已有此口径） |

### 3.7 GUI 文案改写（F 轨）

`gui/dashboard.html` 里所有面向用户的 "ai-memory" 字样改为中性措辞：

| 位置 | 改前 | 改后 |
|---|---|---|
| Hook 页 hint | "ai-memory 自动交接依赖 hooks" | "生命周期 hook 配置状态与修复" |
| 写入 Hook 确认框 | "写入标准 ai-memory 生命周期 hook 模板" | "写入 Hook 命令模板" |
| 移除 Hook 确认框 | "移除 ai-memory 生命周期 hook" | "移除 Hook 配置" |
| 一键写入确认框 | "写入标准 ai-memory 生命周期 hook 模板" | "写入 Hook 命令模板" |
| 正则分类标签 | `"ai-memory"` 归入 "AI 记忆" | 移除该分类（ai-memory 不是技能分类） |

### 3.8 测试改写（G 轨）

约 15 个测试文件引用了 ai-memory。分类处理：

| 处理方式 | 文件 | 说明 |
|---|---|---|
| **删除** | `test_ai_memory_section_guard.py` / `test_unified_mcp_server.py` | 测试的模块已删 |
| **改写引用** | `test_hook_events_config.py` / `test_hook_capability_data.py` / `test_set_setting_early_return.py` | 把 `ai-memory` 命令改为空模板或自定义命令 |
| **改写断言** | `test_legacy_checker.py` / `test_mcp_checker.py` / `test_mcp_fixer.py` / `test_mcp_entry_removal.py` / `test_combined_checker.py` / `test_reporter.py` / `test_multi_profile_reporter.py` | 把 `ai_memory` 能力组改为 `hook_lifecycle` |
| **改写文案** | `test_cli.py` / `test_highrisk_modules.py` / `test_end_to_end_template_audit.py` / `test_config_codec.py` | 帮助文本 / 文案断言里的 "ai-memory" 改为中性措辞 |
| **DESIGN.md 断言** | `test_design_spec_contract.py` | 检查代码里不再出现 `ai-memory` 命令字符串的断言（如有） |

### 3.9 文档改写（H 轨）

| 文档 | 改动 |
|---|---|
| `config.yaml` | template 清空、default_command 新增、注释改写 |
| `CHANGELOG.md` | 记录本次剥离 |
| `README.md` | 移除 ai-memory 引用 |
| `docs/DESIGN.md` | §2.3c Hook 列文案改写、§2.10 Hook tab 新增"命令模板编辑"卡片 |
| `docs/product/PRD-产品需求文档.md` | §6.4 新增 Hook 命令模板编辑需求、§8 修订边界、§10 #1 关闭 |
| `docs/product/产品定位与路线图规划.md` | §4d v0.29.0 范围更新 |
| `SKILL.md` | 移除 ai-memory 引用 |
| `docs/research/*.json` | 改写注释里的 ai-memory 引用 |

## 4. 新增功能：Hook 命令模板可配置

剥离 ai-memory 后，Hook 写入命令变成**完全用户自定义**：

### 4.1 配置格式

```yaml
hooks:
  default_command: ""  # 全局默认命令（空 = 不写兜底，跳过该事件）
  clients:
    - name: Claude Code
      agent_slug: claude-code
      fix_supported: true
      template:
        SessionStart: ""  # 用户自行填写，如 "my-script.sh {event}"
        SessionEnd: ""
```

变量插值：`{event}`（snake_case 事件名）、`{agent}`（agent_slug）、`{server_url}`（活动 profile 的 URL）。

### 4.2 模板预设

| 预设 | 说明 |
|---|---|
| 空模板 | 所有事件命令为空，用户自行填写 |
| 通用 shell 命令 | 示范格式：`echo {event} triggered >> ~/.hook.log` |
| 自定义 | 保留现有 template 不变 |

**不预设任何特定工具的命令。**

### 4.3 CLI 命令

| 命令 | 功能 |
|---|---|
| `--list-hook-templates` | 列出当前所有事件的命令模板（JSON） |
| `--set-hook-template <event>=<command>` | 设置单个事件的命令模板 |
| `--apply-hook-preset <name>` | 应用预设（`empty` / `shell-example` / `custom`） |

### 4.4 GUI

设置页 Hook tab 新增"写入命令模板"卡片（排在"事件勾选"卡片之后）：
- 每个事件一行 `<input type="text">`，值为 template 中的命令
- 预设下拉 + "应用"按钮
- "默认命令"输入框对应 `hooks.default_command`
- 可用变量提示

## 5. 不做的

- **不新建 MCP server**：MCP 远程配置是后续版本的事，本次只做剥离 + 可配置
- **不修改 Rust 白名单的 DENIED_FLAG_PREFIXES**：`--ai-memory` 保留为别名，不删参数（向后兼容）

## 6. 验证

- 全量门禁通过（预期 ~1190 tests，删除 2 个测试文件后减少 ~10 用例）
- `grep -ri 'ai.memory' core/ scan.py gui/dashboard.html config.yaml` 零命中（主干代码）
- `profiles-hermes-home/` 保留 ai-memory 引用（profile 专属，不清理）
- CHANGELOG 记录
