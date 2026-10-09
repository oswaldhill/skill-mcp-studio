# Skill MCP Studio 新功能方案

> 托盘常驻 · 后台巡检 · 变更通知 · Hook 管理

## 一、现状摸底

| 维度 | 现状 | 缺口 |
|---|---|---|
| **Tauri 桌面壳** | 单窗口；已有"关窗隐藏不退出"（`EXITING` + `CloseRequested` 只 hide + Dock Reopen）；CLI 子进程调度成熟（`spawn`/`spawn_cancellable`，白名单安全边界） | 无 tray-icon、无 notification、无 autostart、无后台定时器 |
| **变更检测** | `change_tracker` 已有 `compute_changes`/`save_current_state`，存 `data/state.yaml` | 维度极窄（只比 skills 工具增减/status）；`management_snapshot` 的丰富快照**不持久化、不对比**；无定时/后台/轮询；`save_current_state` 仅 `--fix-skills`/`--clean` 时才存 |
| **Hook** | `hooks_config_path` 已在 `config.yaml` 声明（5 处）；`combined_checker` 已读它做合规检测；`hooks_checker.py` + `ai_memory_checker.py` 已能检测 | 管理台**不透传** hooks 字段；CLI 无编辑/修复参数；GUI 无 hook 入口——**管理/修复层面完全未消费** |
| **UI 范式** | `runCli(["--management",...])` → `SNAP` → `renderXxx()`；操作流 `data-action` → `confirmModal` → `runTaskModal(runCli)` → `refreshBlocks` | 配置面板只覆盖 MCP 字段，无 hooks 编辑入口 |

**核心架构原则（必须延续）**：CLI 是唯一数据源（ADR: one engine, one data contract），Rust 壳只 spawn `skill-mcp-studio` 子进程，不在 Rust 里重写业务逻辑；所有写操作走 CLI 的 backup → atomic-write → validate → rollback 安全链。

---

## 二、总体架构

```
┌─────────────────────────────────────────────────────────┐
│  macOS 状态栏（Tray Icon）  ← 新增 tray-icon feature      │
│  菜单：显示/隐藏 · 立即巡检 · 暂停/恢复 · 间隔 · 退出      │
│  图标态：空闲🟢 / 巡检中🔄 / 发现变更🔴(badge)            │
└───────────┬─────────────────────────────────────────────┘
            │ 唤起 / 状态显示
┌───────────▼─────────────────────────────────────────────┐
│  Tauri 壳（src-tauri/src/lib.rs）                         │
│  ├─ 后台巡检循环（tokio::time::interval）  ← 新增         │
│  │   └─ 定时 spawn CLI 只读审计 → 对比快照 → 发通知       │
│  ├─ 通知推送（tauri-plugin-notification）← 新增           │
│  ├─ 现有：run_audit / run_cli / cancel_cli / open_url    │
│  └─ 新增命令：start_daemon / stop_daemon / daemon_status │
└───────────┬─────────────────────────────────────────────┘
            │ Command::new("skill-mcp-studio")
┌───────────▼─────────────────────────────────────────────┐
│  Python 引擎（scan.py + core/）                           │
│  ├─ 现有：scan / --management / --fix-mcp / --fix-skills │
│  ├─ 新增：--snapshot（轻量只读快照，供后台巡检）           │
│  ├─ 新增：snapshot_diff（对比持久化快照，产出变更清单）    │
│  └─ 新增：Hook 管理域（--list-hooks/--fix-hooks/...）     │
└─────────────────────────────────────────────────────────┘
```

---

## 三、功能 1：状态栏显示（macOS Menu Bar / Tray）

### 3.1 依赖新增
- `Cargo.toml`：`tauri = { version = "2", features = ["tray-icon"] }`
- `tauri.conf.json`：新增 `app.trayIcon` 配置（图标 + 菜单）
- 图标复用现有 `icons/`（32x32.png + icon.icns），另做一版单色模板图（macOS `template` 图标，随深浅色自适应）

### 3.2 Tray 菜单结构
```
Skill MCP Studio
├─ 显示管理台          → window.show() + set_focus()
├─ ──────────────
├─ 立即巡检            → 触发一次后台巡检（不等间隔）
├─ 后台巡检：开/关     → 切换 daemon
├─ 巡检间隔：15min ▶   → 子菜单（5/15/30/60min）
├─ ──────────────
├─ 上次结果：无变更 🟢  → 只读显示（动态更新）
├─ ──────────────
└─ 退出                → EXITING=true + app.exit()
```

### 3.3 图标状态
| 状态 | 图标 | 触发 |
|---|---|---|
| 空闲 | 模板图（正常） | 无后台巡检或上次无变更 |
| 巡检中 | 模板图 + 旋转动画（或换 loading 图） | 巡检进行时 |
| 发现变更 | 模板图 + 红色 badge 数字 | 检测到变更且用户未处理 |

### 3.4 与现有"关窗隐藏"的衔接
现有 `CloseRequested` 只 hide 不退出——**保留**。Tray 提供唯一的"真正退出"入口（菜单"退出"）。Dock Reopen 也保留（点 Dock 图标唤起窗口）。

### 3.5 点击弹框（概览浮窗）
**点击 tray icon 不直接开主窗口，而是弹一个轻量概览浮窗**——让用户一眼看到状态，再决定是否进管理台。

- **触发**：tray icon 的 click 事件（macOS 单击；避免与菜单项冲突）
- **形态**：无边框小 webview 窗口，定位在 tray icon 正下方（Tauri 2 用 `TrayIcon::on_tray_icon_event` + 独立小窗口，或 macOS `NSPopover`）
- **内容（概览卡片）**：

| 项 | 示例 |
|---|---|
| 客户端总数 | 20 个 IDE/Agent |
| 技能总数 | 209 个 |
| MCP 端点 | 3 个（2 已挂载 / 1 缺失） |
| Hook 已配 | 4/5 客户端 |
| **变更状态** | 🟢 无变更 / 🔴 3 项变更（2 新增 · 1 修改） |
| 上次巡检 | 2 分钟前 |

- **底部按钮**：「打开管理台」→ 显示主窗口；「立即巡检」→ 触发一次巡检
- **数据来源**：复用 `--snapshot` 的缓存结果（后台巡检已产出，不重复扫描）；首次无缓存时显示"尚未巡检"
- **消失**：失焦自动关闭，或点 tray icon 再次切换

### 3.6 tray 菜单与弹框的分工
- **左键单击 tray icon** → 弹概览浮窗（3.5）
- **右键 / 菜单键** → 弹完整菜单（3.2：显示/隐藏·立即巡检·开关·间隔·退出）
- macOS 惯例：单击弹 popover，长按或右键弹菜单

---

## 四、功能 2：后台检测（长期后台巡检）

### 4.1 巡检循环（Rust 侧）
```rust
// lib.rs 新增
tokio::spawn(async move {
    let mut interval = tokio::time::interval(Duration::from_secs(interval_secs));
    loop {
        interval.tick().await;
        if !daemon_running.load() { continue; }
        // spawn CLI 只读快照
        let snap = spawn(&["--snapshot".into(), "--format".into(), "json".into()]);
        // 对比上次持久化快照
        let diff = compare_with_last(snap);
        if diff.has_changes {
            // 更新 tray badge + 发通知
            notify_changes(&diff);
        }
        save_last_snapshot(snap);
    }
});
```

### 4.2 巡检用什么命令
新增 CLI 出口 `--snapshot`（轻量只读，比 `--management` 更快）：
- 复用 `build_management_snapshot`，但 `live_probe=False`（不探活，只读配置）
- 产出持久化快照 `data/last_snapshot.yaml`（替代当前窄维度的 `state.yaml`）
- 支持 `--only` 局部刷新（后台巡检可只刷 agents+mcp，不刷 skills 全量）

### 4.3 巡检间隔与资源
| 项 | 默认 | 说明 |
|---|---|---|
| 间隔 | 15 分钟 | tray 菜单可调（5/15/30/60） |
| 单次开销 | ~1.4s（已优化，209 技能 × 20 客户端） | 不探活，纯配置读取 |
| 进程模型 | 每次 spawn CLI 子进程，结束即退 | 不常驻 Python，不占内存 |
| 暂停 | tray 菜单"后台巡检：关" | `daemon_running` 标志位 |

### 4.4 安全边界
- 后台巡检**只读**，绝不自动修复（用户需求："让用户决定"）
- 复用 `run_cli` 的白名单：`--snapshot` 加入 ALLOWED，`--config`/`--prof` 仍被拒
- 巡检不写任何客户端配置，只写 `data/last_snapshot.yaml`

### 4.5 设置面板配置（开关 + 间隔）
**后台巡检的"是否启动"和"定时间隔"都要进设置面板**，不只靠 tray 菜单——tray 菜单是快捷入口，设置面板是权威配置。

- **持久化位置**：`config.yaml` 新增 `daemon` 段（与 `auto_discover`/`profiles` 同级）：
  ```yaml
  daemon:
    enabled: true              # 是否启动后台巡检
    interval_minutes: 15       # 巡检间隔（5/15/30/60）
    notify_on_change: true     # 检测到变更是否推送通知（功能 3 配套）
  ```
  机器本地覆盖走 `~/.skills-manager/profiles.local.yaml` 的 `daemon` 段（与现有 profile_sources 机制一致）。
- **设置面板入口**（`renderSettings`，`dashboard.html:3628`）新增：
  - 「后台巡检」开关 → 写 `daemon.enabled`
  - 「巡检间隔」下拉（5/15/30/60 分钟）→ 写 `daemon.interval_minutes`
  - 「变更通知」开关 → 写 `daemon.notify_on_change`
- **CLI 出口**：新增 `--set-daemon-config`（接受 `--enabled/--interval/--notify`），或并入现有 `--update-settings`；写入走 config_store 的 backup→atomic-write 安全链
- **双向同步**：设置面板改了 → 即时通知 Rust 侧 daemon 调整间隔/启停（通过新命令 `daemon_apply_config`）；tray 菜单改了 → 同步写回 config.yaml，设置面板下次刷新一致
- **首次启动**：无 `daemon` 段时默认 `enabled=true, interval=15`（与 tray 默认一致）

### 4.6 tray 菜单与设置面板的分工
- **tray 菜单**：快捷开关/调间隔（临时调整，同步写回 config）
- **设置面板**：完整配置（开关 + 间隔 + 通知开关），权威来源
- 两者操作同一份 `daemon` 段，任一处修改都即时生效并同步另一处

---

## 五、功能 3：变更通知

### 5.1 通知触发
后台巡检检测到变更 → `tauri-plugin-notification` 推送系统通知：
```
标题：Skill MCP Studio 检测到变更
正文：2 个客户端配置变化（Cursor 的 MCP、Claude Code 的 hooks）
操作：点击查看详情
```

### 5.2 通知点击交互
- 点击通知 → 唤起主窗口 + 跳到"变更详情"面板
- 变更详情面板列出每条变更：维度（IDE/MCP/Skill/Hook）/ 客户端 / 变化内容 / 旧值→新值
- 每条变更两个按钮：**修复** / **保持（忽略）**

### 5.3 变更检测维度（核心扩展）
当前 `change_tracker` 只比 skills 工具增减——**必须扩展**。新增 `core/snapshot_diff.py`，对比 `management_snapshot` 的四个维度：

| 维度 | 检测什么 | 来源字段 |
|---|---|---|
| **IDE/Agent** | 安装状态翻转、新增/消失客户端 | `agents[].installed`、`agents[].name` |
| **MCP** | 端点挂载变化、inventory 条目增减、drift 漂移 | `mcp.clients[].inventory`、`mcp.clients[].observed_attach` |
| **Skill** | 链接形式变化、启用数量变化、新增/删除技能 | `skills.skills[]`、`skills.clients_states[]` |
| **Hook** | hooks_configured 翻转、hook_events 变化 | `agents[].hooks_configured`、`agents[].hook_events`（需先透传，见功能 4） |

### 5.4 通知频率控制（防骚扰）
- 同一变更只通知一次（用户"保持"后不再重复通知）
- 聚合窗口：巡检后 5 秒内多条变更合并成一条通知
- "保持"的变更记入 `data/ignored_changes.yaml`，直到该变更消失或用户主动清除

---

## 六、功能 4：Hook 管理（参照 MCP/skill 范式）

### 6.1 配置层（config.yaml）
当前 `hooks_config_path` 依附于 `mcp_tools`——**提升为独立管理域**，参照 `mcp_tools` 结构新增 `hooks` 段：

```yaml
# 新增：Hook 管理域（参照 mcp_tools / tools 范式）
hooks:
  # hook 事件签名定义（各客户端的事件名、命令格式）
  events:
    - name: SessionStart
      description: 会话开始
    - name: SessionEnd
      description: 会话结束
    - name: Stop
      description: 停止
  # 各客户端的 hook 配置位置与写入规范
  clients:
    - name: Claude Code
      config_path: ~/.claude/settings.json      # 复用现有 hooks_config_path
      format: json
      hook_key_path: [hooks]                     # 配置中 hooks 段的定位路径
      event_format: pascal_case                  # SessionStart（Claude 风格）
      fix_supported: true
      # 标准注入模板（--fix-hooks 写入的内容）
      template:
        SessionStart:
          - matcher: "*"
            hooks:
              - type: command
                command: "ai-memory hook --event session_start"
    - name: Cursor
      config_path: ~/.cursor/hooks.json
      format: json
      hook_key_path: [hooks]
      event_format: camel_case                   # sessionStart（Cursor 风格）
      fix_supported: true
      template: { ... }
    # ... WorkBuddy / Codex / OpenCode
```

**与现有 `mcp_tools[].hooks_config_path` 的关系**：保留 `hooks_config_path` 作为兼容字段，`hooks.clients[]` 是权威配置。`management_snapshot` 优先读 `hooks.clients[]`，回退到 `mcp_tools[].hooks_config_path`。

### 6.2 引擎层（core/ + scan.py）
| 新增 | 作用 | 参照 |
|---|---|---|
| `core/hooks_inventory.py` | 读取各客户端 hook 配置，产出 inventory（已配事件、命令、是否 ai-memory） | `core/mcp_inventory.py` |
| `core/hooks_fixer.py` | 一键写入标准 hook 模板（backup → atomic-write → validate → rollback） | `core/mcp_fixer.py` |
| `core/hooks_snapshot.py` | hook 状态纳入 management_snapshot | `management_snapshot._agent_entry` 透传 |
| scan.py `--list-hooks` | 只读列出各客户端 hook 状态 | `--list-mcp-inventory` |
| scan.py `--fix-hooks` | 写入标准 hook 模板（支持 `--client`/`--dry-run`） | `--fix-mcp` |
| scan.py `--remove-hooks` | 移除 hook 配置（备份后清除） | `--remove-mcp-entry` |
| scan.py `--add-client`/`--update-client` 增 `--hooks-config-path` | 配置编辑入口 | `--mcp-config-path` |

### 6.3 management_snapshot 透传
`_agent_entry`（`management_snapshot.py:166-189`）新增字段：
```python
{
  ...,
  "hooks_config_path": tool.get("hooks_config_path", ""),
  "hooks_configured": ...,      # 从 combined_checker 已有
  "hook_events": ...,           # 已有
  "hooks_inventory": [...],     # 新增：详细事件×命令清单
  "hooks_fix_supported": ...,
}
```

### 6.4 UI 层（gui/dashboard.html）
| 新增 | 位置 | 参照 |
|---|---|---|
| **Hook 管理面板** | 新增一个 tab（与 MCP/Skill 并列） | MCP 面板（`renderMcp`） |
| 面板内容 | 客户端 × 事件 覆盖矩阵（已配/缺失/不支持） | MCP 的"客户端×端点"矩阵 |
| 一键修复 | `data-action="fix-hooks"` → `runCli(["--fix-hooks","--client",name])` | `fix-mcp` |
| 配置编辑 | "添加 IDE"/"客户端设置"面板增加 hooks 配置文件输入框 | 现有 MCP 配置文件输入框 |
| 变更详情 | 变更通知点击后的面板里，Hook 维度单独一栏 | 新增 |

---

## 七、实现路径（分 5 阶段，每阶段独立可交付）

| 阶段 | 内容 | 涉及层 | 是否需重建 APP |
|---|---|---|---|
| **A. Hook 管理** | config.yaml `hooks` 段 + `hooks_inventory`/`hooks_fixer` + `--list-hooks`/`--fix-hooks` + management_snapshot 透传 + GUI Hook 面板 + 配置编辑入口 | 引擎 + 前端 | **是**（前端改了） |
| **B. 变更检测扩展** | `core/snapshot_diff.py` + `--snapshot` 出口 + `data/last_snapshot.yaml` 持久化 + 四维度 diff | 引擎 | 否（引擎即时生效） |
| **C. 托盘常驻** | tray-icon feature + tray 菜单 + 图标状态 + 退出入口 | Tauri | **是** |
| **D. 后台巡检** | tokio 定时循环 + `start_daemon`/`stop_daemon` 命令 + tray 开关 | Tauri + 引擎 | **是** |
| **E. 变更通知** | tauri-plugin-notification + 通知点击交互 + 变更详情面板 + 忽略清单 | Tauri + 前端 | **是** |

**依赖关系**：A 和 B 独立可并行；C 独立；D 依赖 B（需要 snapshot 出口）；E 依赖 B + D。

**建议顺序**：A → B → C → D → E（先补齐管理域和检测基础，再做常驻和通知）。

---

## 八、风险与边界

| 风险 | 应对 |
|---|---|
| 后台巡检 spawn CLI 的开销 | 默认 15 分钟、不探活、~1.4s/次；tray 可暂停 |
| 通知骚扰 | 同变更只通知一次；聚合窗口；"保持"后不再通知 |
| macOS 通知权限 | 首次发通知时系统会弹权限请求；tray 菜单加"开启通知"引导 |
| 后台巡检误判（如客户端自己改了配置） | 变更详情展示旧值→新值，用户可"保持"忽略 |
| tray 跨平台 | 本期只做 macOS（项目当前只打 macOS app）；Windows/Linux 的 tray-icon API 在 Tauri 2 已统一，后续可平滑支持 |
| Hook 写入破坏客户端配置 | 复用 MCP 的 backup → atomic-write → validate → rollback 安全链；`--fix-hooks` 支持 `--dry-run` 预览 |
| `ai_memory_checker.py` 的硬编码与新增 `hooks` 段重复 | 新增 `hooks` 段为权威；`ai_memory_checker` 的 `AI_MEMORY_HOOKS_PATHS` 改为从 config.yaml 读取，消除硬编码 |

---

## 九、需要确认的决策点

1. **巡检默认间隔**（已纳入设置面板，见 4.5）：默认 15 分钟合适？还是更短/更长？
2. **Hook 管理面板**：独立一个 tab，还是并入 MCP 面板作为子区？（建议独立 tab，因为维度不同）
3. **`--snapshot` 出口**：新建轻量出口，还是直接复用 `--management`？（建议新建，后台巡检不需要 skills 全量）
4. **通知的"修复"按钮**：点击后直接执行 `--fix-hooks`/`--fix-mcp`，还是只跳到详情面板让用户再点一次确认？（建议后者，符合现有 `confirmModal` 二次确认范式）
5. **阶段顺序**：A→B→C→D→E 可以？还是先做托盘常驻（C）看效果？
6. **是否要 `tauri-plugin-autostart`**（开机自启）？用户需求是"长期后台"，开机自启是配套，但会改系统登录项。
7. **概览浮窗形态**（新增需求 1）：用 Tauri 独立小 webview 窗口（跨平台、内容灵活），还是 macOS 原生 `NSPopover`（更轻、更贴合系统，但仅 macOS）？（建议独立小 webview，与项目"跨平台可扩展"一致，且能复用前端渲染）
