# Hook 写入可配置 + 全面剥离 ai-memory

> v0.29.0 核心改动。本文是设计文档，不是产品方案。
> 修订 v2（2026-10-16）：按四维评审（安全/架构/产品/测试）补齐 5 个阻断项 + 6 个改进建议。
> 修订 v3（2026-10-16）：补齐 §0 功能能力基线（Hook 与 MCP 的完整能力清单 + 耦合点 + 剥离后边界）。

## 0. 功能能力基线

### 0a. Hook 功能的完整能力

**产品定位**：Hook 是生命周期事件配置管理，管理"客户端在什么时机执行什么命令"。Skill MCP Studio 负责：检查哪些客户端配了哪些事件、写入/移除配置、展示各客户端的能力集与配置状态。

| 层 | 能力 | 现状 |
|---|---|---|
| 规范词表 | 47 个规范事件，按 9 个 group 分组（会话生命周期 / 提示词 / 工具调用 / shell·MCP·文件 / 子代理·任务 / 上下文压缩·模型 / 观察·通知 / 指令·配置·目录 / MCP 交互） | 完整 |
| 客户端能力集 | 6 个客户端声明各自支持的事件全集：Claude Code 33 / Cursor 21 / WorkBuddy 29 / Codex 12 / TRAE 6 / OpenCode 11 | 完整 |
| 分层作用域 | 每个客户端声明多档作用域（用户级 / 项目级 / 本地级 / 托管级），Claude Code 4 档 / WorkBuddy 4 档 / Codex 3 档 / OpenCode 3 档 / Cursor 2 档 / TRAE 2 档 | 完整 |
| 事件命名转换 | canonicalToClient：规范 PascalCase 转各客户端格式（Cursor camelCase / TRAE PascalCase / OpenCode lowercase_dotted 等） | 完整 |
| 配置检查（hooks_checker） | 扫描各客户端配置文件，列出已配置的事件和命令 | 完整 |
| 配置清单（hooks_inventory） | 按客户端 x 事件粒度，产出结构化清单：支持事件数 / 已配置事件数 / 缺失事件 / 配置路径 / 作用域 | 完整 |
| 写入（hooks_fixer） | --fix-hooks：按用户选中的事件 + 能力集过滤，写入各客户端配置（含备份 + 原子写 + 回滚） | broken：写入的命令是 ai-memory hook --event ...（硬编码外部工具命令，且该命令本身缺参数） |
| 移除（hooks_fixer） | --remove-hooks：移除已写入的 hook 条目（含备份） | 只移除 ai-memory 签名的条目 |
| GUI 展示 | IDE/Agent 列表 Hook 列（N/M 胶囊 + 档数注记）、Hook 业务页（47 事件分组表）、设置页 Hook tab（事件勾选） | 完整 |
| CLI 命令 | --list-hooks / --fix-hooks / --remove-hooks（均在 Rust 白名单） | 完整 |
| 事件选择 | 设置页 GUI 勾选后写 settings.hook_events（默认全选 47） | 完整 |

**Hook 功能不涉及** MCP 协议、不涉及端点连接、不涉及探活。Hook 管理的是"客户端配置文件里写了什么命令"，至于这个命令连到哪里、是不是 MCP，Hook 功能不管。

### 0b. MCP 功能的完整能力

**产品定位**：MCP 是端点连接与挂载管理，管理"客户端连到哪个 MCP 端点、端点是否可用、端点上挂了哪些工具"。Skill MCP Studio 负责：端点库 CRUD、活动 profile 切换、逐客户端挂载、探活、MCP 条目审计/清理。

| 层 | 能力 | 现状 |
|---|---|---|
| 端点 profile 抽象 | config.yaml 的 profiles 段，每 profile 声明 name / url / transport / required_capabilities / legacy_names | 完整 |
| 活动 profile 切换 | --set-active-profile：写 overlay，切换所有客户端共享的统一端点 | v0.28.0 新增 |
| 端点库 CRUD | --add-endpoint / --remove-endpoint / --update-endpoint | 完整 |
| 端点挂载 | --attach-endpoints：每客户端声明挂载哪些端点 | 完整 |
| 探活 | --probe-mcp / --endpoint-status：MCP initialize + tools/list + 能力组验证 | 完整 |
| MCP 配置审计（mcp_checker） | 扫描各客户端 MCP 配置文件，检查是否接入了统一端点 | 完整 |
| MCP 条目清单（mcp_inventory） | 列出每个客户端配置文件里的所有 MCP server 条目 | 完整 |
| MCP 配置修复（mcp_fixer） | --fix-mcp：写入统一端点配置到各客户端（含备份 + 回滚） | 完整 |
| MCP 条目清理 | --remove-mcp-entry / --remove-mcp-class / --remove-legacy-mcp（含风险门） | 完整 |
| legacy 通道检测（legacy_checker） | 检测旧的 Hermes / ai-memory legacy 通道条目 | 含 ai-memory 检测块（待移入 profile） |
| 能力组验证 | combined_checker 检查端点是否声明了 required_capabilities 里的能力组 | 完整（ai_memory 是其中一个能力组） |
| GUI 展示 | MCP 页（客户端 x 端点 覆盖矩阵）、概览页端点状态区、设置页 MCP tab | 完整 |
| profile 分发 | profile_sources：个人端点隔离在 ~/.skills-manager/profiles.local.yaml（仓库外） | 完整 |

**profiles-hermes-home/config.yaml 的能力组**（profile 专属，不清理）：

| 能力组 | 成员工具 | 语义 |
|---|---|---|
| hermes_memory | memory_search, memory_add | Hermes 记忆服务 |
| ai_memory | ai_memory_query, ai_memory_handoff_begin, ai_memory_call | AI 记忆查询/交接 |
| tdai | tdai_memory_search, tdai_conversation_search, tdai_knowledge | TDAI 记忆服务 |
| hermes | hermes_health, hermes_chat | Hermes 健康检查与聊天 |

**MCP 功能不涉及** Hook 写入命令。MCP 管的是"端点连没连上"，Hook 管的是"配置文件里写了什么命令"。

### 0c. 两者的关系与耦合点

Hook 与 MCP 是两个独立功能域，仅在 combined_checker 有一个耦合点：

```
combined_checker: hooks_required = "ai_memory" in required
```

这行代码的语义是"端点声明了 ai_memory 能力组时，才要求客户端配 hook"。这是一个隐式耦合：hook 是否 required 寄生在某个能力组的键名上。

本设计文档的解耦方案：改为 profile 显式声明 `hooks_required: true`（布尔字段），不再依赖任何能力组键名。解耦后两个功能域完全独立。

### 0d. ai-memory 耦合点完整清单

| 耦合点 | 所在功能域 | 处理方式 |
|---|---|---|
| config.yaml template 段命令值 | Hook | 清空（C 轨） |
| _default_hook_command() 兜底命令 | Hook | 改为返回空字符串（D 轨） |
| _is_ai_memory_hook_cmd() / HookEntry.is_ai_memory | Hook | 删除，改为 is_configured（D 轨） |
| _filter_ai_memory_from_event() / remove_hooks_tool | Hook | 改为全删（D 轨） |
| ai_memory_checker.py 整个模块 | MCP（ai-memory 专属检查器） | 删除（A 轨） |
| unified_mcp_server.py 整个模块 | MCP（ai-memory HTTP 网关代理） | 删除（A 轨） |
| legacy_checker.py 的 AI_MEMORY_DETECTION | MCP（legacy 检测） | 移入 profiles-hermes-home/（E 轨） |
| combined_checker.py 的 hooks_required = "ai_memory" in required | 交叉耦合点 | 解耦为 hooks_required: true（E 轨） |
| profiles-hermes-home/config.yaml 的 required_capabilities.ai_memory | MCP（profile 专属能力组） | 保留（profile 专属，不清理） |

## 1. 背景

Skill MCP Studio 从 `skills-mcp-unifier` 演化而来，`ai-memory` 是早期绑定的一个**外部 MCP 服务**。它的命令被硬编码进了 `config.yaml` 的 `hooks.clients[].template` 段，成了"默认 Hook 写入内容"。同时 `ai_memory_checker.py` 和 `unified_mcp_server.py` 作为 ai-memory 的专属检查器和 HTTP 网关代理住在了主干代码库里。

用户明确要求：**ai-memory 是外部 MCP 的功能，不是本产品的组成部分，全部剥离。** Hook 写入命令应完全由用户自定义。

## 2. 改动总览

| 轨 | 内容 | 文件数 |
|---|---|---|
| A | 删除 ai-memory 专属模块 | 4 删 |
| B | 提取公共解析原语到 config_codec.py | 1 改（config_codec）+ 2 改（hooks_inventory / hooks_fixer 改 import） |
| C | config.yaml template 改为空模板 + 用户配置迁移 | 1 |
| D | hooks_fixer / hooks_inventory 改写（含 fix_supported 动态化） | 2 |
| E | scan.py / cli_modes / combined_checker / legacy_checker 改写 | 4 |
| F | GUI 文案改写 + 新增"命令模板编辑"卡片 | 1 |
| G | 测试改写 | 17（含新增反向断言） |
| H | 文档改写 | 10（含 SECURITY.md） |

### 执行顺序约束

B 轨（提取函数到 config_codec + 改 import）**必须先于** A 轨（删 ai_memory_checker.py）。若先删文件后改 import，hooks_fixer.py:22 和 hooks_inventory.py:20 的 import 会断裂，全量门禁必挂。建议分两个 commit：先 B（改 import + 内联函数），再 A（删文件 + 删测试）。

## 3. 详细设计

### 3.1 删除的文件（A 轨）

| 文件 | 理由 |
|---|---|
| `core/ai_memory_checker.py` | ai-memory MCP 条目检查器，专属外部服务 |
| `scripts/unified_mcp_server.py` | ai-memory HTTP 网关代理，专属外部服务 |
| `tests/test_ai_memory_section_guard.py` | 上述模块测试（5 用例） |
| `tests/test_unified_mcp_server.py` | 上述模块测试（23 用例） |

删除前需确认：`pgrep -f unified_mcp_server` 无在运行进程；无 launchd/crontab 条目引用该文件。删除后该文件的 `_redact()` 凭据脱敏机制一并消失，SECURITY.md 中对该机制的引用必须同步清理（见 H 轨）。

### 3.2 提取公共解析原语到 config_codec.py（B 轨，修订）

`hooks_inventory.py:20-24` 从 `ai_memory_checker` 导入了三个函数，**hooks_fixer.py:22 也导入了 `_find_in_dict`**（原设计文档遗漏此依赖）：

- `_load_toml_file(filepath)` — 加载 TOML 文件（14 行）
- `_find_in_dict(data, key_path)` — 在嵌套字典里按键路径取值（9 行）
- `_extract_hook_commands(hook_section)` — 从 hook 段提取命令列表（22 行）

这三个是**通用 JSON/TOML 解析原语**，与 ai-memory 无关。项目已有 `core/config_codec.py` 模块（`legacy_checker.py:30` 已从它导入），语义上属于配置编解码层。

**方案（修订）**：将三个函数提取到 `core/config_codec.py`（已存在，不新建文件）。`hooks_inventory.py` 和 `hooks_fixer.py` 统一改为 `from config_codec import _load_toml_file, _find_in_dict, _extract_hook_commands`。一处定义、两处复用、零重复、关注点归位。

### 3.3 config.yaml template 改为空模板 + 用户配置迁移（C 轨，修订）

#### 3.3a 主干 config.yaml

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
  default_command: ""        # 全局默认命令模板（空 = 不写入兜底，跳过该事件）
  clients:
    - name: Claude Code
      agent_slug: claude-code  # 该客户端在 MCP 端点的 agent 标识（用于 {agent} 变量插值）
      fix_supported: true      # 声明值；运行时由 hooks_inventory 重算（见 D 轨）
      template: {}             # 空：用户自行配置
```

`agent_slug` 字段：语义是"该客户端在 MCP 端点的 agent 标识"，用于命令模板的 `{agent}` 变量插值。值来自 config.yaml 声明，与 ai-memory 无关。注意：agent_slug 仅填公开标识，勿填 token/密钥/内部 agent ID。

WorkBuddy / TRAE：不填 `agent_slug`，`fix_supported: false`（已有此机制，保持不变）。

#### 3.3b 用户配置迁移策略（新增，评审阻断项 #4）

现有用户升级到 v0.29.0 后，已落盘的 config.yaml 里 template 仍含 `ai-memory hook --event ...` 命令，但 ai-memory 模块已删除，这些命令执行会 `command not found`。

**迁移方案（推荐 A：保留旧值 + 显性降级标记）**：

1. 升级**不动**用户已落盘 config.yaml 的 template 值（不丢用户数据）。
2. 加载时检测：若某事件 template 命令以 `ai-memory ` 开头，GUI 该行 input 旁打 `.tag.warn`（"该命令指向已移除的工具"）。
3. CLI 写入前校验命令可执行性（`which` 或 `command -v` 取命令首词），不可执行则跳过并回报 `skipped`（复用 hooks_fixer 现有 skipped 机制）。
4. 升级首次启动在 Hook tab 顶部弹引导 banner：`检测到 N 条旧 ai-memory 命令，该工具已移除，建议改填新命令（见预设）`，提供"一键清空旧命令"按钮（经确认）。

### 3.4 hooks_fixer.py 改写（D 轨，修订）

| 函数/位置 | 改前 | 改后 |
|---|---|---|
| L22 `from ai_memory_checker import _find_in_dict` | 导入 | 改为 `from config_codec import _find_in_dict`（B 轨） |
| `_default_hook_command` | 返回 `ai-memory hook --event <snake>` | 返回空字符串 `""`（空 = 不写入兜底，该事件跳过） |
| `_build_hook_entry` | 不变 | 不变（结构正确） |
| L183 `existing_ai_events = {e.event for e in existing_entries if e.is_ai_memory}` | 过滤 ai-memory 条目 | **删除该行**（原设计文档遗漏此依赖）。全删语义下不再需要识别"哪些是我们写的"，移除即全删该事件的 hook 条目。 |
| `_filter_ai_memory_from_event` → `_filter_all_hooks` | 只过滤 ai-memory 签名的条目 | 改为**移除全部 hook 条目**（不再区分来源） |
| `remove_hooks_tool` | 只移除 ai-memory hook | 改为移除**全部 hook 条目**。语义变更："移除 Hook" = 清除该事件下所有 hook 配置（含第三方）。 |
| docstring/注释里的 "ai-memory" | — | 改为中性措辞（"Hook 命令模板"、"由用户配置的命令"） |

**移除 Hook 的产品语义与确认框**（评审阻断项 #5）：

当前 GUI 确认框文案（dashboard.html:7280）承诺"保留非 ai-memory hooks"。改为全删后该承诺被打破。确认框文案**必须**改为：

> 将清除 ${name} 该事件下**全部** hook 条目（包括非本工具写入的第三方 hook）。
> 原配置会先备份。继续？

并保留 `dangerConfirm=true`（红色确认按钮），确认框内列出"将删除 N 条 hook 条目"（数字来自 inventory）。

### 3.5 hooks_inventory.py 改写（D 轨，修订）

| 改动 | 说明 |
|---|---|
| `from ai_memory_checker import ...` | 改为 `from config_codec import _load_toml_file, _find_in_dict, _extract_hook_commands`（B 轨） |
| `_is_ai_memory_hook_cmd` | 删除（不再需要识别"是否 ai-memory"） |
| `HookEntry.is_ai_memory` 字段 | 改为 `HookEntry.is_configured`（只要命令非空即为 True） |
| L192 `is_ai_memory=True`（TS plugin 分支） | 改为 `is_configured=True` |
| L223 `is_ai_memory=_is_ai_memory_hook_cmd(cmd)` | 改为 `is_configured=bool(cmd.strip())` |
| L274 序列化 `{"is_ai_memory": ...}` | 改为 `{"is_configured": ...}` |
| **`fix_supported` 运行时重算**（评审阻断项 #2） | 见下方专项 |

#### fix_supported 动态化（评审阻断项 #2，新增）

设计文档原把"有 agent_slug 且 template 非空时才 true"的意图写在了 config 注释里，未落到代码。template 清空后 GUI 显示"支持修复"但实际零写入。

在 `hooks_inventory.py` 的 `hooks_client_config` / 读取处，增加运行时重算：

```python
declared_fix_supported = hc.get("fix_supported", False)
has_agent_slug = bool(hc.get("agent_slug", "").strip())
has_template = bool(hc.get("template"))  # {} 即 False
# 声明 true 时，还需 agent_slug 或 template 至少一个非空才真支持
effective_fix_supported = declared_fix_supported and (has_agent_slug or has_template)
```

用 `effective_fix_supported` 替代直接读 `hc.get("fix_supported")`。inventory 的 `hooks_fix_supported` 字段透传 `effective_fix_supported`，hooks_fixer 同理。

补测试断言："template 为空且无 agent_slug 时，hooks_fix_supported 必须为 False"。

### 3.6 scan.py / cli_modes / combined_checker / legacy_checker 改写（E 轨，修订）

| 文件 | 改动 |
|---|---|
| `scan.py` | `--ai-memory` / `--fix-ai-memory` 保留为**纯别名**（向后兼容）。help 文本已标"已废弃"。输出文案里的 "ai-memory" 改为 "Hook 命令"。注意：`--ai-memory` 实际等价于 `--mcp --hooks`（不只 `--mcp`）；`--fix-ai-memory` 实际转发到 `--fix-mcp`（不是 `--fix-hooks`）。help 文本与转发目标要对齐：`--fix-ai-memory` 的 help 保持"改用 --fix-mcp"（与代码一致）。 |
| `cli_modes.py` | `args.ai_memory` 保留在 `explicit` 列表（line 10），`if args.ai_memory` 分支（line 45-47）保持开 `mcp + hooks`。文案改写。 |
| `combined_checker.py` | **不改名能力组**（评审改进 #6：改名有语义错位，`ai_memory` 组成员是记忆查询工具，改名 `hook_lifecycle` 后名实不符）。改为**解耦**：`hooks_required` 不再寄生在能力组键名上，改为 profile 显式声明 `hooks_required: true`（布尔字段）。`combined_checker.py:223` 改为 `hooks_required = required.get("hooks_required", False)`（取布尔而非查能力组键名）。`CAPABILITY_DISPLAY_NAMES` 的 `ai_memory` 键保留（它确实是记忆能力组），但 `hooks_required` 不再依赖它。`record["ai_memory_available"]` 保留（它描述的是端点是否有记忆能力，与 hook 无关）。 |
| `legacy_checker.py` | `AI_MEMORY_DETECTION` 常量删除。`DEFAULT_DETECTIONS`（line 120）中的引用同步删除（原设计文档遗漏此行），改为只含 hermes 块。profile 自带 ai-memory legacy_detection，生产链路不受影响。无 profile 时的兜底检测退化为只检 hermes，符合 generic-http 端点定位。 |
| `hooks_checker.py` | `"ai-memory" in command` 改为通用判定 `bool(command.strip())`（命令非空即算已配置，已有此口径）。 |

### 3.7 GUI 文案改写 + 新增卡片（F 轨，修订）

#### 3.7a 文案改写

`gui/dashboard.html` 里所有面向用户的 "ai-memory" 字样改为中性措辞：

| 位置 | 改前 | 改后 |
|---|---|---|
| Hook 页 hint | "ai-memory 自动交接依赖 hooks" | "生命周期 hook 配置状态与修复" |
| 写入 Hook 确认框 | "写入标准 ai-memory 生命周期 hook 模板" | "写入 Hook 命令模板" |
| **移除 Hook 确认框** | "移除 ai-memory 生命周期 hook（保留非 ai-memory hooks）" | **"清除该事件下全部 hook 条目（含第三方）。原配置会先备份。继续？"**（评审阻断项 #5） |
| 一键写入确认框 | "写入标准 ai-memory 生命周期 hook 模板" | "写入 Hook 命令模板" |
| 正则分类标签 | `"ai-memory"` 归入 "AI 记忆" | 移除该分类 |
| 移除 Hook stages | "移除 ai-memory hook" | "移除 Hook 条目" |

#### 3.7b 新增"写入命令模板"卡片（评审改进 #1：补组件规范）

设置页 Hook tab 新增"写入命令模板"卡片，排在"事件勾选"卡片之后。DESIGN.md §2.10 需补以下规范：

**卡片结构**：

```
┌─ 写入命令模板 ─────────────────────────────────────┐
│ 预设  [ 选择预设...          ▼ ]  [应用预设]        │
│                                                     │
│ ┌─ 会话边界 ──────────────────────────────────────┐ │
│ │ SessionStart  [________________________]        │ │
│ │ SessionEnd    [________________________]        │ │
│ │ Stop          [________________________]        │ │
│ └────────────────────────────────────────────────┘ │
│ ┌─ 工具调用 ──────────────────────────────────────┐ │
│ │ PreToolUse    [________________________]        │ │
│ │ ...                                            │ │
│ └────────────────────────────────────────────────┘ │
│                                                     │
│ 默认命令  [______________________________________]  │
│ 可用变量: {event} {agent} {server_url}              │
│ [保存]                                               │
└─────────────────────────────────────────────────────┘
```

**组件规范**：
- 47 个事件按 `group` 分组渲染（复用现有 `.hook-group-row` 表头），与"事件勾选"卡同构
- 每行一个 `<input type="text" class="modal-form input">`，值为 `hooks.clients[].template[EventName]`
- 预设下拉 `<select>` + "应用预设"按钮（应用 = 批量覆写 template，**必须弹确认框**）
- "默认命令"输入框对应 `hooks.default_command`
- 可用变量提示用 `.ad-pill` 胶囊展示 `{event}` / `{agent}` / `{server_url}`
- 旧 ai-memory 命令行旁打 `.tag.warn`（"该命令指向已移除的工具"）
- 状态覆盖：空 template / 部分填写 / 全填写 / 预设应用中 / 保存中 / 保存失败回滚 各态
- 读写一律经 CLI（`--list-hook-templates` / `--set-hook-template` / `--apply-hook-preset`），GUI 不直接改 config.yaml

### 3.8 测试改写（G 轨，修订）

17 个测试文件引用了 ai-memory（原设计文档写"约 15"不准确）。分类处理：

| 处理方式 | 文件 | 用例数 | 说明 |
|---|---|---|---|
| **删除** | `test_ai_memory_section_guard.py` | 5 | 模块已删 |
| **删除** | `test_unified_mcp_server.py` | 23 | 模块已删 |
| **改写引用** | `test_hook_events_config.py` / `test_hook_capability_data.py` / `test_set_setting_early_return.py` | ~7 | `ai-memory` 命令改为空模板或自定义命令 |
| **改写断言（能力组）** | `test_legacy_checker.py` / `test_mcp_checker.py` / `test_reporter.py` / `test_multi_profile_reporter.py` | ~12 | `ai_memory` 能力组相关断言。注意：采用解耦方案后**不改名能力组**，只需删除 `hooks_required` 依赖 `ai_memory` 键的断言 |
| **误判排除** | `test_mcp_fixer.py` / `test_mcp_entry_removal.py` | ~11 | 原设计文档误归入"改写断言"。实际这两个文件的 `"ai-memory"` 是 **legacy 条目名示例**（`legacy_names=["ai-memory"]`），与能力组无关，**不应改动**（改了会破坏通用 legacy 移除测试的真实性） |
| **改写文案** | `test_cli.py` / `test_highrisk_modules.py` / `test_end_to_end_template_audit.py` / `test_config_codec.py` | ~8 | help/文案断言里的 "ai-memory" 改为中性措辞 |
| **保留反向守护** | `test_design_spec_contract.py` | — | 已有 `assertNotIn("is_ai_memory", body)` 断言，改名后仍成立，保留 |
| **新增反向断言** | `test_design_spec_contract.py` | +1 | 新增"主干源码零 ai-memory 命令字符串"断言（见下方验证标准） |

**删除用例总数**：28（5 + 23）。**预期删后总数**：1172（原设计文档写 1190，严重低估）。

### 3.9 文档改写（H 轨，修订）

| 文档 | 改动 |
|---|---|
| `config.yaml` | template 清空、default_command 新增、agent_slug 新增、注释改写 |
| `config.yaml` profiles 段 | 新增 `hooks_required: true` 布尔字段（解耦方案） |
| `profiles-hermes-home/config.yaml` | 保留 ai-memory 引用（profile 专属，不清理） |
| `CHANGELOG.md` | 记录本次剥离 |
| `README.md` | 移除 ai-memory 引用 |
| `SECURITY.md` | 删除对 `unified_mcp_server.py` `_redact` 机制 的引用（评审改进 #11） |
| `docs/DESIGN.md` | §2.3c Hook 列文案改写、§2.10 Hook tab 新增"命令模板编辑"卡片规范（见 §3.7b） |
| `docs/product/PRD-产品需求文档.md` | §6.4 新增 Hook 命令模板编辑需求 + §8 新增边界"不内置任何特定工具的 Hook 命令" + §10 新增已关闭项 |
| `docs/product/产品定位与路线图规划.md` | §4d v0.29.0 范围更新；标注"unified_mcp_server.py 已删除，后续 MCP 远程配置需从零重建" |
| `SKILL.md` | 移除 ai-memory 引用 |

#### PRD §8 修订草案（评审改进 #5）

新增边界条目：
> **不内置任何特定工具的 Hook 命令**：Hook 写入命令完全由用户在 config.yaml / GUI 自行配置，产品不预设 ai-memory 或任何第三方工具的命令。

新增边界条目：
> **不内置 MCP server 远程入口**：v0.29.0 不提供 MCP server 远程配置入口（`unified_mcp_server.py` 已删除），远程配置留待 v0.30+ 专项立项。

缺口看板新增：
> | 4 | Hook 命令模板可配置 + 剥离 ai-memory | ✅ 已关闭 | v0.29.0 |

## 4. 新增功能：Hook 命令模板可配置

剥离 ai-memory 后，Hook 写入命令变成**完全用户自定义**：

### 4.1 配置格式

```yaml
hooks:
  default_command: ""  # 全局默认命令（空 = 不写兜底，跳过该事件）
  clients:
    - name: Claude Code
      agent_slug: claude-code
      fix_supported: true  # 运行时重算
      template:
        SessionStart: ""  # 用户自行填写
```

变量插值：`{event}`（snake_case 事件名）、`{agent}`（agent_slug）、`{server_url}`（活动 profile 的 URL）。

### 4.2 模板预设（修订：扩到 5 种）

| 预设名 | CLI 标识 | 说明 |
|---|---|---|
| 空模板 | `empty` | 所有事件命令为空，用户自行填写 |
| 日志记录 | `logging` | `echo {event} triggered >> ~/.hook.log`（语法示范） |
| 回调通知 | `webhook` | `curl -s -X POST <your-endpoint>/hook -d '{"event":"{event}","agent":"{agent}"}'` |
| 本地脚本 | `local-script` | `~/.local/bin/on-hook.sh {event} {agent}` |
| 自定义 | `custom` | 保留现有 template 不变 |

**不预设任何特定工具的命令。** GUI 卡片头部加迁移引导 `.note`：`v0.29.0 起不再内置 ai-memory 命令，请在此填写你的 Hook 命令；如需类似能力可参考"回调通知"预设。`

### 4.3 CLI 命令

| 命令 | 功能 |
|---|---|
| `--list-hook-templates` | 列出当前所有事件的命令模板（JSON） |
| `--set-hook-template <event>=<command>` | 设置单个事件的命令模板 |
| `--apply-hook-preset <name>` | 应用预设（`empty` / `logging` / `webhook` / `local-script` / `custom`） |

三条命令走 overlay 路径（与 `--set-setting` 同模式），加入 Rust 白名单。

### 4.4 GUI

见 §3.7b。

## 5. 不做的

- **不新建 MCP server**：MCP 远程配置是 v0.30+ 的事，本次只做剥离 + 可配置。`unified_mcp_server.py` 删除后，后续 MCP 远程配置需从零重建基座。
- **不修改 Rust 白名单的 DENIED_FLAG_PREFIXES**：`--ai-memory` 保留为别名，不删参数（向后兼容）。
- **不改名能力组**：`ai_memory` 能力组保留语义不变（它是记忆能力组，不是 hook 能力组）。hook 触发条件改为 profile 显式声明 `hooks_required: true`，不再寄生在能力组键名上。

## 6. 验证（修订）

### 6a. 用例数

删除 2 个测试文件（28 用例），预期删后总数 **1172**（原设计文档写 1190，严重低估）。`pytest --co -q tests/ | tail -1` 期望输出 `1172 tests collected`。

### 6b. grep 零命中标准（修订：拆为强/弱两级）

原设计文档的"零命中"与"保留 --ai-memory 别名"自相矛盾（别名本身含 `ai-memory`）。修订为：

**强零命中**（无豁免，必须为空）：
```bash
grep -rnE 'ai[._-]memory' core/hooks_fixer.py core/hooks_inventory.py core/combined_checker.py core/hooks_checker.py core/legacy_checker.py config.yaml gui/dashboard.html
# 期望：零输出
```

**弱零命中**（豁免别名声明）：
```bash
grep -nE 'ai[._-]memory' scan.py | grep -vE '"--(fix-)?ai-memory"|help.*已废弃|args\.(fix_)?ai_memory'
# 期望：零输出（只剩别名参数声明和 help 文本）
```

**tests/ 零命中**（排除 legacy 示例名正当用途）：
```bash
grep -rnE 'ai[._-]memory' tests/ | grep -vE 'legacy_names|legacy_detection|"ai-memory":\s*\{'
# 期望：零输出（test_mcp_fixer / test_mcp_entry_removal 的 legacy 示例名保留）
```

**profiles-hermes-home/ 不检查**（profile 专属，保留 ai-memory 引用）。

### 6c. 反向断言（新增）

在 `test_design_spec_contract.py` 新增一条断言，将 grep 从人工验证升级为 CI 门禁：

```python
def test_no_ai_memory_in_trunk_sources(self):
    """主干源码不得出现 ai-memory 命令字符串（v0.29.0 剥离后）。"""
    import pathlib
    trunk = pathlib.Path("core/hooks_fixer.py")
    src = trunk.read_text(encoding="utf-8")
    self.assertNotIn("ai-memory hook", src, "hooks_fixer 不得含 ai-memory 命令")
    self.assertNotIn("is_ai_memory", src, "hooks_fixer 不得含 is_ai_memory 字段")
```

### 6d. 全量门禁

`CI_ALLOW_SKIP_DRIFT=1 bash scripts/ci_parity.sh` 全绿（预期 1172+ tests OK）。
