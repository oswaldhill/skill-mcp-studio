# skill-mcp-studio 产品需求文档（PRD）

| 版本 | 日期 | 说明 |
|------|------|------|
| v1.0 | 2026-09-07 | 基于当时版本（v0.7.0 build 79）重写；纠正既有定位/设计文档中「只读看板」「三栏」等已过时表述，作为产品层面的单一权威 PRD |
| v1.1 | 2026-09-07 | 新增 §1「应用范围」：跨平台（Windows / macOS / Linux）三环境支持，三类路径三平台化（决策 A）；配套调研见《跨平台路径矩阵-Windows-Linux.md》 |
| v1.2 | 2026-09-18 | 版本时点字段改「另见 CHANGELOG」，不再散落快照号（`version.json` 单源真相）；§8 缺口看板标注关闭版本 |

> **版本口径**：本文**不再内嵌「当前版本 = vX.Y.Z」快照**——版本号以仓库 `version.json`（及 `CHANGELOG.md`）为单一真相，本文只描述产品能力而不随版本号漂移。

> **本文档角色**：回答「产品是什么、给谁用、核心能力与边界」。
> 它与既有文档的关系见 §10。凡与本文不一致的旧表述（《产品定位与路线图规划》《产品形态与开发计划》中的「只读审计看板」「刻意不做写入型 GUI」「三栏管理台」等），**一律以本文为准**。

---

## 1. 应用范围（跨平台）

### 1.1 目标环境

skill-mcp-studio 是**跨平台**的本地桌面工具，同一份代码在三类环境运行：

| 环境 | 口径 | 路径规范 | 交付形态 |
|------|------|----------|----------|
| **Windows** | 支持 | `%USERPROFILE%`（家目录）、`%APPDATA%`（Roaming）、`%LOCALAPPDATA%`（Local） | **MSI 安装器** |
| **macOS** | 支持（当前已实现） | `~`、`/Applications`、`~/Library`、`~/.config` | `.app` / `.dmg` |
| **Linux** | 支持「主流」口径 = Ubuntu / Debian / Fedora(RPM) + XDG + portable(AppImage) | `~`、`~/.config`（XDG 优先）、`~/.local`、`/usr/share/applications`、`/opt` | `.deb` `.rpm` `.AppImage` |

> 架构结论：必须摒弃「macOS 中心」的路径硬编码，采用**跨平台分派**（决策 A，见 §1.3）。当前代码（`core/mainstream_registry.py`、`config.yaml`）仅含 macOS 路径，且全项目无 `sys.platform` 分派逻辑，Windows/Linux 支持为空白。

### 1.2 三类扫描路径

自动扫描覆盖三类路径，各平台默认值见《跨平台路径矩阵-Windows-Linux.md》：

| 类别 | 对应字段 | 说明 |
|------|----------|------|
| **Skill 路径** | `skills_paths` + `unified_skills_dir` + `auto_discover.scan_paths` | 每个客户端的技能目录位置、共享技能仓库、自动发现的技能扫描根 |
| **IDE 路径** | 客户端 `app_bundles`（GUI 应用）+ 部分 `config_paths` | 桌面 IDE 的安装位置与配置目录 |
| **Agent 路径** | 客户端 `commands`（PATH 可执行）+ `config_paths` + Agent 型条目的 `type` | AI Agent / CLI 助手的可执行命令与配置目录 |

> IDE 与 Agent 在实现上共用同一份客户端注册表（`mcp_tools` + `tools`），用 `type` 字段区分（AI IDE / AI Coding Assistant / AI Agent / AI Coding Plugin / AI Desktop Client）。「IDE 路径」「Agent 路径」落到实现是**同一注册表路径字段的三平台化**。

### 1.3 路径建模（决策 A：已定）

- 每个客户端声明 `paths_by_os: { "darwin": {...}, "windows": {...}, "linux": {...} }`，运行时按 `sys.platform` 取当前平台那份。
- 三平台通用字段仍在顶层兜底（`commands` 中跨平台一致的 CLI 名如 `claude` / `codex` 可只写一份）。
- **消费点收口**：新增统一分派层（建议落在 `core/tool_registry.py`），把「当前平台的 `install.app_bundles` / `install.commands` / `install.config_paths` / `skills_paths` / `config_path`」解析成一套平台无关视图，供 `detect_installation`、scanner、combined_checker、mcp_fixer、management_snapshot 等 10+ 处消费点调用，避免各处散写 `sys.platform`。
- **Windows 路径展开**：`expanduser` 需扩展为同时展开 `%USERPROFILE%` / `%APPDATA%` / `%LOCALAPPDATA%`（`os.path.expandvars` + 平台映射）；Linux/macOS 沿用 `~` 展开。

### 1.4 内置客户端清单（以主流注册表为唯一事实源）

内置默认清单分两类（国际 / 通用 + 国产）共 **22 个**（完整路径 + 确定度 + 来源 URL 见 [`跨平台路径矩阵-Windows-Linux.md`](../design/跨平台路径矩阵-Windows-Linux.md)）。**条目数量与路径以 `core/mainstream_registry.py`（`register_mainstream_tools()` 返回值）为唯一事实源**，本文的「22 个」只是 v0.7 时代的设计目标快照，后续新增（如 QwenWork、TraeWork、Trae CN）以注册表为准，不再回写本段落计数：

**国际 / 通用（15 个）**：Claude Code、Cursor、VS Code、Windsurf、Codex、Gemini CLI、OpenCode、Aider、Cline、Roo Code、JetBrains(IDEA/PyCharm/WebStorm)、Zed、TRAE、Goose、Cherry Studio。

**国产（7 个）**：CodeBuddy、WorkBuddy（腾讯）；Qoder、QwenWork 千问办公（阿里）；Trae、TraeWork、豆包 Doubao（字节）。

> **无 Linux 桌面版，Linux 扫描直接跳过**：QwenWork 千问办公（仅 macOS/Win/HarmonyOS）、TraeWork（桌面版仅 macOS/Win）、豆包（仅网页版）。
> **无本地 skills/MCP 语义，只判安装不参与 skills/MCP 检查**：豆包（通用对话助手，非编程 IDE）。

### 1.5 内置默认路径的确定度口径

内置默认路径按确定度标注，绝不虚构：

- **verified**：官方文档 / 源码核实（如 Claude Code、Codex、Gemini、OpenCode、VS Code、Zed、Goose、CodeBuddy、Qoder、QwenWork、Trae 的配置与技能路径）。
- **best-effort**：仅基于 VS Code fork / Electron 惯例或社区来源推断（如 TRAE、Cherry Studio、豆包、部分 `%APPDATA%` 映射）。
- 查无权威来源的字段**留空**并标注，扫描时不参与安装判定（如 Aider 的 skills、VS Code 的 skills 目录、JetBrains 的 MCP 文件、豆包的 skills/MCP）。

完整矩阵（22 客户端 × Windows/Linux × 5 字段 + 来源 URL）见 [`跨平台路径矩阵-Windows-Linux.md`](../design/跨平台路径矩阵-Windows-Linux.md)。

---

## 2. 产品概述

**一句话定位：本地多客户端的 Skill / MCP 通用管理台**——竞品负责「安装与同步」，skill-mcp-studio 负责「检查、管理与修复」。

skill-mcp-studio 是一台面向开发者的**管理型桌面应用**（Tauri 2 + 通用 CLI 引擎），用于：

1. **IDE / Agent**：检查本机所有 IDE / Agent 的安装状态与配置正确性（声明 + 自动发现 + 手动三来源）；
2. **Skills**：管理共享 Skills 仓库（统一目录 vs 单独目录判定、一键合并、逐技能启用状态）；
3. **MCP**：管理多个 MCP endpoint（端点库 + 每客户端多端点挂载 + 逐端点探活与能力验证）。

核心方法论是「**四层独立验证**」，把「配置对了」和「真的能用」分开，逐项独立报告、不做短路合并。所有写操作复用统一的「备份 → 原子写 → 校验 → 回滚」安全链。

| 属性 | 值 |
|------|-----|
| 产品形态 | 桌面 App（Tauri 2），webview 装载单文件 `gui/dashboard.html` |
| 引擎层 | Python CLI（`scan.py`，≥ 3.11），core/ 审计引擎 |
| 当前版本 | 见 `version.json` / `CHANGELOG.md`（单一真相，不在文档内快照） |
| 交付物 | `.app`（macOS）+ `skill-mcp-studio` 控制台命令 |
| 数据源 | `config.yaml`（客户端注册表 + endpoint 库）+ 仓库外 `profile_sources` 覆盖 |

---

## 3. 背景与问题

同时使用多个 AI 编码助手（Claude Code、Cursor、Codex、Windsurf、OpenCode、DSH 等）的开发者，面临三类治理痛点：

1. **变更后体检**：升级、换机、改配置后，不知道哪些客户端掉线、哪些能力缺失。
2. **一致性治理**：多客户端接入同一套 Skill / MCP 时，路径是否都指向统一仓库、端点是否都配置正确，缺乏对齐核查手段。
3. **安全修复**：统一端点迁移时，批量改写各客户端配置需要「可回滚」的安全保障，避免越改越坏。

现有同类工具集中在「安装分发 / 一键启停 / 目录治理」，**「审计验证 + 可回滚修复」是空白带**。skill-mcp-studio 填补这一空白，并从「验证器」演进为「管理器」。

---

## 4. 目标用户与使用场景

| 维度 | 描述 |
|------|------|
| 目标用户 | 同时使用多个 AI 编码助手的开发者与团队；集中托管 Skill / MCP、要求多客户端一致接入的「重度用户」与托管基础设施维护者 |
| 非目标用户 | 只用单一客户端、无集中托管诉求的个人开发者（价值密度过低） |
| 核心场景 | ① 变更后体检；② 多机 / 多客户端一致性核查；③ 统一端点迁移的批量安全改写 |
| 使用方式 | 桌面 GUI（日常操作）+ CLI（脚本 / 集成 / 机读报告）双入口 |

---

## 5. 产品形态

### 5.1 形态模型

```
┌───────────────────────────────────────────────────────────────┐
│  L2  桌面 GUI（Tauri 2 · 五页管理台 · 浅/深双主题）              │
│       webview 装载 gui/dashboard.html，注入 run_audit / run_cli │
├───────────────────────────────────────────────────────────────┤
│  L1  通用 CLI（scan.py）                                        │
│       只读审计 + 显式写操作 + --dry-run + 多格式机读报告          │
├───────────────────────────────────────────────────────────────┤
│  L0  审计/修复引擎（core/）                                      │
│       四层验证 · 多格式配置解析 · 备份-原子写-回滚 · 报告          │
├───────────────────────────────────────────────────────────────┤
│  配置层  config.yaml + profile_sources（源代码事实）              │
│       客户端注册表（mcp_tools/tools/auto_discover）+ endpoint 库 │
└───────────────────────────────────────────────────────────────┘
```

### 5.2 三条贯穿式硬约束

1. **审计与修复分离**：写操作永远需要显式触发（CLI `--fix-*` / GUI 点按钮），只读审计绝不隐含写入。
2. **单一 source of truth**：客户端注册表 + endpoint 库是唯一事实源，CLI 与 GUI 共享同一引擎产出，结论一致（`scripts/verify_gui_consistency.sh` 作为回归 gate）。
3. **形态向上兼容**：每个形态复用下一层引擎与数据契约，不做推翻式二次实现。

### 5.3 页面结构（五页）

| 页面 | 职责 | 性质 |
|------|------|------|
| **概览** | KPI 汇总（受管客户端 / 安装 / 技能 / MCP 探活 / 主流纳入）+ 快捷操作 | 只读 + 快捷入口 |
| **IDE / Agent** | 客户端安装状态、Skills 路径合规、挂载端点 | 业务（纳入 / 移出客户端） |
| **Skills** | 技能清单、每客户端启停状态、客户端挂载矩阵 | 业务（一键合并、逐技能启停） |
| **MCP** | 每客户端 MCP 条目分类（已挂载 / 旧通道 / 未纳管）与覆盖矩阵 | 业务（挂载视图） |
| **设置** | 通用配置：统一技能目录、MCP 端点库、自动发现、关于 | 通用（集中管理） |

> **通用 / 业务分离原则**：通用配置（能跨所有客户端起作用的全局项：统一技能目录、MCP 端点库、自动发现、活动 endpoint）收敛进「设置」页；只涉及具体客户端 / 具体技能 / 具体挂载的业务动作放在对应管理页。

---

## 6. 核心功能需求

### 6.1 IDE / Agent

| 能力 | 类型 | 实现入口 |
|------|------|----------|
| 列出本机所有客户端（声明 + 自动发现 + 手动三来源归一去重） | 读 | `--management --format json` 快照 |
| 展示安装证据（app bundle / CLI 命令 / 配置路径） | 读 | 客户端卡片安装证据区 |
| 展示 Skills 路径合规 + 链接形态（per_skill / root / mixed） | 读 | 卡片 + 详情 Sheet |
| 展示 MCP 挂载端点（显式 / 自动全部） | 读 | 卡片 |
| 查看客户端完整详情（含配置解析出的 MCP 条目） | 读 | 详情 Sheet |
| 纳入 / 移出客户端（主流工具勾选 + 自定义添加） | 写 | `--add-client` / `--remove-client` / `--add-defaults` |
| 重新扫描（含自动发现） | 写（触发生成） | `--management --format json --discover` |

### 6.2 Skills

| 能力 | 类型 | 实现入口 |
|------|------|----------|
| 展示统一技能目录、技能总数 | 读 | 快照 `skills.unified_dir` / `skill_count` |
| 搜索 / 筛选技能清单（全部 / 已启用 / 部分 / 未启用） | 读 | 技能页分段筛选 + 搜索 |
| 网格 / 列表视图切换（记忆于 localStorage） | 读 | 视图切换 |
| 查看单技能详情（描述 + 每客户端启用状态） | 读 | 右侧 Sheet |
| 每客户端技能启停（ToggleSwitch） | 写 | `--enable-skill <s> --client <c>` / `--disable-skill ...`（见 §8 缺口） |
| 一键合并（dry-run 预览 → 确认实写） | 写 | `--fix-skills --dry-run` → `--fix-skills` |
| 设置统一技能目录 | 写（通用） | `--set-unified-dir`（设置页） |

### 6.3 MCP

| 能力 | 类型 | 实现入口 |
|------|------|----------|
| 端点库（key / name / url / transport / 探活 / 能力组） | 读 | 快照 `mcp.endpoints`（设置页表格） |
| 每客户端 MCP 条目分类（已挂载 / 旧通道 / 未纳管） | 读 | MCP 页 |
| 端点 × 客户端覆盖矩阵 | 读 | MCP 页 |
| 端点库增 / 删 / 改 | 写（通用） | `--add-endpoint` / `--remove-endpoint` / `--update-endpoint`（设置页） |
| 客户端挂载端点调整 | 写（业务） | `--attach-endpoints <key,...> --client <name>` |

### 6.4 设置（通用配置）

| 能力 | 类型 | 实现入口 |
|------|------|----------|
| 统一技能目录（可改） | 写 | `--set-unified-dir` |
| MCP 端点库（增删改） | 写 | 端点 CRUD 命令 |
| 自动发现开关 + 扫描 / 排除路径 | 读（当前只读） | 快照 `settings.auto_discover`；**编辑待后端命令** |
| 活动 endpoint（active_profile）切换 | 读（当前只读） | 快照 `settings.active_profile`；**编辑待后端命令** |
| 版本 / 构建号 | 读 | `--version` 快照 |

> **P-3 定案**：`auto_discover` 与 `active_profile` 两项在当前版本**保持只读展示**（不出编辑项）。未来的写命令命名为 `--set-auto-discover` / `--set-active-profile`（编辑 config 对应键），与 Rust `DENIED_FLAGS` 拒绝的**重定向参数** `--active-profile`／`--profile`／`--config`（把引擎指向任意配置文件、属提权面）是两组不同的 flag，**互不冲突**。切「默认端点」的受控写形态留待后续版本立项。

### 6.5 交互与视觉（当前实现）

- **主题**：浅色 / 深色 / 跟随系统（`data-theme` + `prefers-color-scheme`）。
- **⌘K 命令面板**：分组（页面 / 操作 / 技能 / 主题）+ 过滤 + ↑↓/Enter 导航 + Esc 关闭。
- **右侧详情 Sheet**：技能详情、客户端详情以抽屉呈现（原为居中弹窗）。
- **ToggleSwitch**：逐客户端技能启停，loading 态旋钮转 spinner。
- **Toast 栈**：进度 → 成功 / 失败，接入异步写流。
- **溢出菜单（kebab）**：客户端 查看详情 / 重新扫描 / 移出管理。
- **全局 Esc 逐级关闭**：面板 → 溢出菜单 → 抽屉 / 弹窗。
- **可访问性**：内联 SVG 图标（无 emoji）；可点击元素 `cursor:pointer`；accent focus ring；`prefers-reduced-motion` 覆盖动画。
- **品牌色自觉**：强调色为 Brand Blue（浅 `#2563EB` / 深 `#60A5FA`），语义三色（绿 ok / 黄 warn / 红 err）仅用于审计结论。

---

## 7. 非功能需求（质量属性）

| 属性 | 要求 |
|------|------|
| **安全修复** | 所有写操作走「备份 → 原子写 → 写后校验 → 失败回滚」；symlink 用 `os.symlink(tmp)+os.replace` 原子替换，无删除窗口 |
| **dry-run** | 有破坏性的写命令一律支持 `--dry-run` 预览 |
| **安全边界** | GUI 的写命令经 Rust `run_cli` 白名单收口，禁止重定向类参数（`--config` / `--profile` / `--active-profile` 等升级面） |
| **GUI / CLI 一致性** | `scripts/verify_gui_consistency.sh` gate 绿，GUI 审计结论 == CLI 审计结论 |
| **只读默认** | 无参数 CLI 运行是只读；`--full` 绝不隐含 git/cleanup/fix |
| **离线可用** | 字体自托管（IBM Plex Mono），无外部 CDN 依赖；中文字体用原生 PingFang SC |
| **回归零破坏** | 单端点缺省路径输出与阶段一~四保持一致；`scripts/ci_parity.sh`（等价于 CI 的 `python3 -m unittest discover -s tests -p 'test_*.py'`）全绿 |
| **可访问性** | 对比度 ≥ 4.5:1（正文）、focus ring、reduced-motion、图标带语义 |

### 退出码语义

| 码 | 含义 |
|----|------|
| 0 | 全绿 |
| 1 | 存在不合规项（或写后校验失败，已回滚） |
| 2 | 配置 / profile / 模板加载错误；或技能不在仓库 / 形态不支持 / 回滚失败 |

---

## 8. 产品边界（刻意不做）

- **不做**技能市场 / 商店（agentregistry、gh skill 领域）。
- **不做**多用户权限体系与云端同步（企业级平台，部署成本不符）。
- **不做**云端托管与跨设备实时同步（本地工具）。
- 按需加载（阶段四 L5）作为增值层，立项时独立决策。

### 当前已知缺口（缺口看板，逐项标注关闭版本）

| # | 缺口 | 状态 | 关闭版本 |
|---|------|------|---------|
| 1 | **自动发现、活动 endpoint 的 GUI 编辑**：设置页仅有只读展示，缺少 `--set-auto-discover` / `--set-active-profile` 后端写命令，UI 标注「即将支持」 | 🟡 待实现 | — |
| 2 | **逐技能启停的 GUI 运行时边界**：GUI 的 ToggleSwitch 已绑定 `--enable-skill` / `--disable-skill` | ✅ 已关闭（已加入 Rust `run_cli` 白名单） | v0.20.0 |
| 3 | **端点 transport 选择、能力组编辑**：端点详情编辑最初仅支持 name / url | ✅ 已关闭（`--endpoint-url` / `--endpoint-command` / `--endpoint-required-yaml` 补全 transport 与 required_capabilities 编辑） | v0.20.0 |

---

## 9. 关键术语

| 术语 | 定义 |
|------|------|
| 四层独立验证 | L1 安装证据 → L2 路径合规 → L3 配置正确 → L4 端点活体 + 能力组，逐层独立判结论 |
| 端点库（endpoint library） | 一组 MCP endpoint 的声明集合（`profiles` 的语义重述） |
| 挂载（attach） | 客户端与端点间的多对多关系（`mcp_attach`） |
| 能力组 | 一组必须同时存在的工具名，用于判定端点能力覆盖 |
| legacy 条目 | 客户端配置中指向旧端点 / 旧通道的 MCP 条目 |
| 活体探测 | initialize + notifications/initialized + tools/list 三步 JSON-RPC 调用 |
| source of truth | `config.yaml` 的客户端注册表 + endpoint 库 |
| 统一 / 单独目录 | 客户端 Skills 目录是否指向统一仓库（符号链接解析比对） |

---

## 10. 与既有文档的关系（偏差勘正）

本节是本次 PRD 重写的核心目的：纠正产品演进后残留的过时表述。

| 旧文档 / 表述 | 过时点 | 本文裁定（以本节为准） |
|--------------|--------|----------------------|
| 《产品定位与路线图规划》§4 路线图「L2 桌面 GUI（只读看板）」 | 产品已是可写管理台 | 形态更新为五页管理台（本文 §5.3）；「只读看板」表述废弃 |
| 《产品形态与开发计划》§6「阶段三之前不做任何写入型 GUI 按钮」 | 阶段五起已推翻 | GUI 直接写操作（含备份回滚），此项删除 |
| 两份文档 §4 阶梯表「L2 三栏（IDE/Skills/MCP）」 | 实际是五页 + 设置页 | 五页：概览 / IDE·Agent / Skills / MCP / 设置（本文 §5.3） |
| README §180「三栏管理台」 | 同上 | 同为五页，README 可后续同步 |
| 「一句话定位 = 审计与修复工具」 | 已转向管理型 | 定位更新为「通用管理台」（本文 §2） |
| 缺少「通用 / 业务设置分离」 | 设置页为新结构 | 加入 §5.3 通用/业务分离原则 |
| 缺少主题 / 命令面板 / 抽屉 / 开关等交互描述 | GUI 二轮演进补充 | 加入 §6.5 |

**文档层级**（建议）：README（入口）→ **PRD（本文，产品层权威）** → 产品定位与路线图 / 产品形态与开发计划（战略与计划，需按本文勘正）→ 详细设计文档-阶段一~五（实现层，阶段五为准）→ docs/ 评审与数据（过程记录）。

---

## 11. 验收标准（DoD）

1. 五页管理台各自独立展示检查结果，且通用配置集中在设置页、业务操作在对应管理页。
2. 多 MCP 真实生效：端点库 ≥2 端点时可挂载任意子集，逐端点探活 / 能力独立呈现。
3. 三种来源（声明 + 自动发现 + 手动）归一去重、不重复报 UNMANAGED。
4. 所有写操作走备份 - 原子写 - 回滚，dry-run 可预览。
5. 阶段一~四全部测试通过；`verify_gui_consistency.sh` gate 绿。
6. §8「当前已知缺口」在后续版本逐一关闭。

---