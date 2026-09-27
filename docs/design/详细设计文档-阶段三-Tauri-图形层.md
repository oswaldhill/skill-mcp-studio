# skill-mcp-studio 详细设计文档 — 阶段三（Tauri 图形层）

## 版本

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.1 | 2026-09-01 | 阶段三首版：Tauri 只读审计看板；数据契约定案 + 架构 + 看板规范 + 一致性验证 + 打包方案 |
| v1.0 | 2026-09-01 | 定稿：Tauri 壳 `cargo tauri build` 全绿产出 `.app`；一致性 gate 修复 `set -e` 退出码容忍缺陷（仅 exit 2 阻断）并归档达 DoD；P1–P4 全绿，测试 134 项全绿 |

## 1. 概述

阶段三把「多客户端 × 多状态」的审计结论给一个一眼可读的**只读看板**——客户端矩阵 × 状态字段，红黄绿三态。**写入操作仍仅 CLI**（硬边界，阶段三不做任何写入按钮）。

文档的读者是实施工程师与评审人，回答「怎么做」：数据契约定案、模块划分、看板规范、红黄绿判定、一致性验证、打包分发。

- **范围**：CLI→GUI 数据契约落地、只读看板渲染、一致性验证、Tauri 打包分发（macOS 首发）。
- **不覆盖**：阶段四按需加载与启停（立项另定）；阶段三遗留延期项中项目级模板目录、stdio Windows 兼容仍不实际落地（仅确认排期，见 §13）。

### 1.1 承继与现状

- 阶段一 §12 预留「GUI 数据契约 = `check_agents` 返回结构」；
- 阶段二 §12 预留「GUI 消费汇总报告 = `--all-profiles --format json` 的 `results`」；
- 阶段二已交付可独立安装的 CLI（`skill-mcp-studio`），且 `--all-profiles --format json` 已产出完整、机读的审计快照。阶段三的核心是**把这个快照渲染成看板**，并严格保证「GUI 与 CLI 结论一致」。

### 1.2 DoD（阶段三退出标准）

> GUI 与 CLI 对**同一环境**产出**完全一致**的审计结论；写操作仍仅 CLI（阶段三不做任何写入型按钮）。

> **达成状态（v1.0）**：一致性 gate `scripts/verify_gui_consistency.sh` 修复 `set -e` 缺陷后通过（默认 Python 与 3.11 双版本复算 0 违规）；Tauri 壳 `cargo tauri build` 全绿产出 `.app`；测试套件 134 项全绿。P1–P4 全部 ✅，详见 §12。

## 2. 数据契约定案（唯一事实源）

GUI 不做二次解析、不重算任何结论，只**消费**引擎输出的 JSON。契约以 `core/combined_checker.py::check_agents` 与 `core/multi_profile_reporter.py::report_all_profiles` 的**代码实际返回为准**。

### 2.1 单 profile 审计结构（`check_agents` 返回，JSON 序列化）

```json
{
  "endpoint": "https://example.internal/mcp",
  "probe": {
    "initialize_ok": true,
    "tools_list_ok": true,
    "tool_names": ["memory_search", "memory_add"],
    "error": ""
  },
  "records": [ { "客户端记录，见 2.2" } ],
  "unmanaged": [ { "name": "...", "skills_compliant": true, "paths": ["..."] } ],
  "summary": {
    "installed": 6,
    "skills_compliant": 5,
    "mcp_configured": 4,
    "mcp_connected": 3,
    "full_capabilities": 2,
    "hooks_configured": 1,
    "legacy_channels": 1,
    "unmanaged_mcp": 1
  },
  "capability_groups": ["memory", "tdai"]
}
```

### 2.2 record 结构（每客户端一条，只增不改名不删除）

```json
{
  "name": "Codex",
  "installed": true,
  "install_evidence": ["cli", "config"],
  "skills_compliant": true,
  "mcp_configured": true,
  "configured_url": "https://example.internal/mcp",
  "mcp_initialize_ok": true,
  "mcp_tools_list_ok": true,
  "capabilities": { "memory": true, "tdai": false },
  "hooks_configured": true,
  "hook_events": ["on_session_end"],
  "legacy_channels": ["hermes-nas"]
}
```

### 2.3 汇总报告结构（`--all-profiles --format json`）

```json
{
  "schema_version": 1,
  "generated_at": "2026-09-01T11:43:38.803552+00:00",
  "active_profile": "hermes-home",
  "profiles": ["hermes-home", "local-notes"],
  "results": [
    { "profile": "hermes-home", "ok": true, "endpoint": "...", "probe": {}, "records": [], "unmanaged": [], "summary": {}, "capability_groups": [] },
    { "profile": "local-notes", "ok": false, "endpoint": "...", "probe": {}, "records": [], "unmanaged": [], "summary": {}, "capability_groups": [] }
  ]
}
```

### 2.4 契约漂移修正（本节同时修复阶段一 §12 / §4.2 的两处旧文案）

| 位置 | 旧文案 | 实际实现（以代码为准） | 定案 |
|------|--------|------------------------|------|
| 阶段一 §12 顶层契约 | 声明 `profile` 字段（"阶段一新增字段"） | 顶层无 `profile`，而是 `capability_groups`；`profile` 由**汇总层**在 `results[i]` 注入 | 顶层契约去掉 `profile`，补 `capability_groups`；`profile` 仅在 `results[i]` |
| 阶段一 §4.2 能力组字段名 | 扁平 `capability_<组名>` | 嵌套 `capabilities: { "<组名>": bool }` | 统一为嵌套 `capabilities` 字典 |

约束延续：**records 字段只增不改名不删除**；能力组以 `capabilities` 字典呈现，GUI 矩阵列按字典键（或 `capability_groups`）动态生成。

## 3. 架构：CLI → GUI 通道

### 3.1 通道选型（ADR-13）

GUI 通过**子进程调用 CLI**获取审计快照，不在 Rust/前端重写引擎：

```
Tauri 应用（前端 webview + Rust 侧边进程）
  └─ Rust 侧调用子进程: skill-mcp-studio --all-profiles --format json
       └─ 读 stdout → 解析 JSON → 注入前端渲染
```

理由：

1. `skill-mcp-studio` 已可独立安装（pipx），同一份引擎、同一份 config、同一环境 →「结论一致」从机制上成立，无需重写；
2. Rust 侧只要负责「起进程 + 传 JSON + 退出码」，不需要理解审计语义；
3. 若未来要替换为共享引擎（进程内嵌入 Python），契约 JSON 不变，可平滑迁移（§14）。

子进程契约：

- 命令：`skill-mcp-studio --all-profiles --format json`（跨 profile）或 `skill-mcp-studio --profile X --skills --mcp --hooks --probe-mcp --format json`（单 profile，见 §14 开放项）；
- 读 `stdout` 的 JSON（`--format json` 保证纯 JSON 到 stdout）；
- 退出码沿用：0 全绿、1 存在不合规、2 运行/配置错误（GUI 把 2 显示为「工具运行失败」横幅，不当作审计结论）。

### 3.2 单 profile 快照来源

现状 `--format json` 只服务于 `--all-profiles`（`report_all_profiles` 的 JSON 分支）。单 profile 审计要拿到同构快照，需新增一个**单 profile JSON 出口**（阶段三 CLI 增量，§14 开放项 B），否则 GUI 单 profile 视图只能靠 `--all-profiles` 遍历一遍再取 `results[0]`（可行但浪费）。首版捷径：单 profile 视图也走 `--all-profiles`（因为只有 active 一个 profile 时结果同构）；多 profile 时才真正逐 profile 抓取。

## 4. 看板规范

### 4.1 布局

- 顶栏：当前 profile / 全部 profile 切换、`generated_at`、退出码横幅（仅 2 时显示「工具运行失败」）；
- 主体：**矩阵视图**——一行一个客户端，列为状态字段；
- 每客户端行首格 = 客户端名；末格可选 hover 展示 `install_evidence` / `configured_url` / `hook_events` 明细。

### 4.2 列定义

固定列（7）：`installed · skills_compliant · mcp_configured · mcp_initialize_ok · mcp_tools_list_ok · hooks_configured · legacy_channels`；
能力组列（N）：按 `capability_groups`（或 records 里 `capabilities` 键并集）动态追加。

### 4.3 红黄绿三态判定（ADR-14）

判定以**单个已安装客户端**为单元，逐 record 分类，与 `result_ok`（CLI 退出码判定）共用同一组字段，保证一致。先区分探测状态：`probe.error == "not probed"` 为「未探测」，`probe.error == ""` 为「探测完成」，其余非空为「探测失败」。

| 态 | 颜色 | 触发条件（对 `installed=True` 的 record） |
|----|------|------------------------------------------|
| 通过 | 绿 | `skills_compliant ∧ mcp_configured ∧ mcp_initialize_ok ∧ mcp_tools_list_ok ∧ hooks_configured ∧ all(capabilities) ∧ legacy_channels==[]`（即在**探测完成**态下满足全部字段） |
| 失败 | 红 | `¬skills_compliant` ∨ `¬mcp_configured` ∨ 探测失败（`probe.error` 非空且 ≠`"not probed"`）∨ （探测完成态下 `¬mcp_initialize_ok ∨ ¬mcp_tools_list_ok`）∨ （探测完成态下 `∃g: ¬capabilities[g]`） |
| 部分缺失 | 黄 | `installed` ∧ 非绿 ∧ 非红——即「未探测」（`mcp_configured=True` 但 `probe.error=="not probed"`，L4 字段 False 属未探测而非失败）、`legacy_channels` 非空（遗留通道待迁移）、或 `hooks_configured=False`（hooks 未配置，可补齐） |

补充表：

| record 状态 | 呈现 |
|-------------|------|
| `installed=False` | 灰（未安装，不参与三态审计，列出但不打分） |
| 未纳管客户端（`unmanaged[]`） | 单独分区「未纳管但已安装」，不写入、不计入三态，标注「无验证过的 MCP 注册表格式」 |

**一致性不变量（DoD 关键）**：`result_ok(result) == True` 当且仅当「所有已安装 record 均为绿，且 `unmanaged` 为空」。黄与红都对应 `result_ok=False`，GUI 用黄/红进一步区分「未探测/可迁移缺失」与「硬失败」；三态不复造第二套规则。

## 5. 一致性验证（DoD 硬要求）

GUI 与 CLI 对同一环境分别跑审计并逐项 diff，结论必须完全一致。

- **验证脚本** `scripts/verify_gui_consistency.sh`：调 CLI `--all-profiles --format json` 产出快照，用引擎侧 `gui_consistency.verify_snapshot` 复算每个 record 的 `state`/`ok` 与快照逐字段（profile、record 每个布尔字段、capabilities、summary、ok）比对，违规数非零即退出 1；
- 一致性根因：GUI 快照**来自** CLI 子进程 stdout，不经二次加工（除解析 JSON），故「结论一致」是结构性保证，复算脚本只做回归护栏；
- **退出码容忍（v1.0 修复）**：scan.py 按退出码约定对「存在不合规项」返回 **exit 1**（合法快照，非错误）。gate 早期在 `set -e` 下被 exit 1 直接终止、从未执行复算——v1.0 改为 `set +e` 捕获退出码，**仅 exit 2**（运行/配置错误）阻断，exit 0/1 放行进入复算，与 §3.1 GUI 把 exit 2 显示为「工具运行失败」横幅的语义对齐。

## 6. 安全设计（只读硬边界）

1. GUI 无任何写入入口：不提供 `--fix-*` / `--remove-legacy-mcp` / setup 按钮；所有修复仍在 CLI 显式触发（延续阶段一/二 §8 与产品 §8.1 硬边界）；
2. GUI 不缓存 token：`probe.error` 与报告均不含凭据；`env` 令牌只进子进程环境，不进前端 state；
3. 子进程继承 CLI 的只读承诺：`--all-profiles` / 单 profile `--format` 只做扫描 + 探测（`initialize/tools/list` 三类只读），**无任何写盘副作用**——`run_scan` 只读，唯一写 `state.yaml` 的 `save_current_state` 仅在阶段 9 的 `(--fix-skills 且非 --dry-run) 或 --clean` 写入场景触发，GUI 路径 early return 不经过阶段 9（见 §14.B，已核实）。

## 7. Tauri 打包分发（macOS 首发）

- 前端 = 自包含 Web（HTML + 原生 JS，无构建步骤），既可作为 Tauri `webview` 内容，也可浏览器直开做第一时间验证；
- Rust 侧 = 最小 `tauri` 壳：`invoke("run_audit")` → `Command::new("skill-mcp-studio").args(["--all-profiles","--format","json"])` → 解析 JSON → 返给前端；「选择 profile」由前端在聚合快照上切片（§14.C：一次 `--all-profiles` 覆盖全部 profile，无需逐 profile 子进程），「刷新审计」重跑子进程。原 `run_audit_profile` 桥接因前端从未接线，已于 2026-09-05 评审整改中删除（CLI 单 profile 出口 `--profile X --format json` 仍保留，供 CI/脚本使用）；
- 依赖校验：宿主需已装 `skill-mcp-studio`（GUI 首次启动检测 `which skill-mcp-studio`，缺则引导 `pipx install skill-mcp-studio`）；
- Tauri 壳**已构建验证**（`cargo tauri build` 全绿，产出 `src-tauri/target/release/bundle/macos/skill-mcp-studio.app`）：脚手架 `src-tauri/`（`Cargo.toml` / `tauri.conf.json` / `build.rs` / `src/main.rs` / `src/lib.rs` + `icons/` + `BUILD.md`）；Rust 1.92 已存于 `~/.rustup/toolchains/stable-aarch64-apple-darwin/`，仅 `~/.cargo/bin` shim 缺失（用绝对路径或加 PATH 即可），`CARGO_HOME` 重定向到仓库内 `.cargo-home/` 避免触碰系统路径；`targets: ["app"]` 出可运行 `.app`（`.dmg` 因本机 `hdiutil` 磁盘映像权限限制暂不含，见 `src-tauri/BUILD.md` §3）；数据契约、看板 HTML、一致性脚本三者在 Python/Web 侧均已交付并验证（§12 交付顺序）。

## 8. 模块划分

| 模块 | 职责 | 新增/改 |
|------|------|---------|
| `core/dashboard_states.py` | 绿/黄/红/灰 `classify_record`，与 `result_ok` 共用字段；`all_installed_green` 不变量 | 新增 |
| `core/gui_consistency.py` | `verify_snapshot`：复算 state/ok/契约字段，GUI/CLI 一致性护栏 | 新增 |
| `core/multi_profile_reporter.py` | JSON 快照为每 record 注入 `state`（只增字段）；前端纯渲染 | 改（阶段三增量） |
| `scan.py::_run_single_profile_snapshot` | `--format json/csv/md` 单 profile 快照出口（同构单元素 results） | 改（P2） |
| `gui/dashboard.html` | 自包含看板：解析 JSON、动态能力组列、三态着色；内联 CSS/JS，无构建步骤 | 新增 |
| `scripts/verify_gui_consistency.sh` | CLI→引擎复算一致性 gate（DoD 护栏） | 新增 |
| `src-tauri/`（Rust 壳脚手架） | `Cargo.toml`/`tauri.conf.json`/`build.rs`/`src/main.rs`/`src/lib.rs`/`BUILD.md`：起 CLI 子进程 + webview 装载 | 新增（需 Rust 环境构建） |
| `core/combined_checker.py` | 已产出 `check_agents`/`result_ok`（阶段一/二） | 不变，GUI 消费 |

## 9. 测试设计

- 三态判定单测：给定 record 集合，断言绿/黄/红/灰/unmanaged 分类与 `result_ok` 语义一致（含「未探测 → 黄」与「探测失败 → 红」边界）；
- 数据契约 schema 测试：`check_agents` / `report_all_profiles` 返回 JSON 反序列化后字段精确匹配 §2 契约（防字段漂移回归）；
- 看板渲染测试：固定 + 动态能力组列、三态 CSS 类、空能力组 profile 无能力组列；
- 一致性脚本测试：同环境两路快照逐项 diff 为空（fixture 驱动）；
- 全量回归：阶段一/二测试全绿；`--all-profiles --format json` 输出不变。

## 10. 目标目录结构

```
skill-mcp-studio/
├── scan.py                               # CLI 入口（P2 加单 profile 快照出口）
├── core/
│   ├── dashboard_states.py               # 三态判定（绿/黄/红/灰）
│   ├── gui_consistency.py                # GUI/CLI 一致性校验
│   └── multi_profile_reporter.py         # 汇总 JSON + state 注入
├── gui/
│   └── dashboard.html                    # 自包含看板（webview 内容 / 浏览器直开）
├── scripts/
│   └── verify_gui_consistency.sh         # 一致性 gate
├── src-tauri/                            # Rust 壳脚手架（有 Rust 环境时构建）
│   ├── Cargo.toml
│   ├── build.rs
│   ├── tauri.conf.json
│   ├── BUILD.md                          # 构建/验证步骤 + 只读边界表
│   └── src/{main.rs, lib.rs}             # run_audit（只读）
└── tests/
    ├── test_dashboard_states.py          # 三态判定 + result_ok 不变量
    ├── test_gui_consistency.py           # 一致性校验
    ├── test_multi_profile_reporter.py    # JSON state 注入
    └── test_exit_codes.py                # 单 profile 快照退出码
```

## 11. 关键流程

1. 用户启动 GUI（或浏览器直开 `dashboard.html`）；
2. 前端请求 → Rust 侧（或纯前端直接 fetch 本地脚本出口）调 `skill-mcp-studio --all-profiles --format json`；
3. 解析 JSON → 注入渲染层 → 矩阵着色；
4. 切换 profile = 前端对聚合快照切片重渲染（§14.C；不再起单 profile 子进程）；刷新审计 = 重跑子进程；
5. 退出码 2 → 顶部「工具运行失败」横幅，不渲染为审计结论。

## 12. 交付顺序（受环境约束的分步，已推进到 P3 脚手架）

| 步 | 内容 | 状态 |
|----|------|------|
| P1 | 数据契约 + 看板 Web（`dashboard_states.py` / `gui_consistency.py` / `gui/dashboard.html` / `verify_gui_consistency.sh` + 三态/契约/一致性测试）；浏览器直开 + 一致性 gate 验证 | ✅ 完成（134 tests passed + gate exit 0） |
| P2 | 单 profile 机读快照出口（`_run_single_profile_snapshot`） | ✅ 完成 |
| P3 | Tauri 壳：`src-tauri/` 脚手架 + `BUILD.md` 已就位 | ✅ 完成（`cargo tauri build` 全绿，产出 `.app`） |
| P4 | 一致性 gate 归档 | ✅ 完成（gate `set -e` 退出码容忍缺陷修复后归档达 DoD，见 §5） |

## 13. 阶段三遗留延期项收口

| 遗留项 | 出处 | 阶段三动作 |
|--------|------|-----------|
| 项目级模板目录（`.skill-mcp-studio/templates/`） | 阶段二 §14.1 | **仍延期**：与本阶段 GUI 无耦合，维持阶段三后评估（不阻塞看板） |
| stdio Windows 兼容 | 阶段二 §14.5 | **仍延期**：macOS 首发已定，Windows 属后续兼容项（不阻塞看板） |

## 14. 开放项（阶段三内已全部收口）

- **A. 单 profile 快照来源** → **已实现（P2）**：新增 `--format json|csv|md` 单 profile 快照出口（`_run_single_profile_snapshot`），产出与 `--all-profiles` 同构的单元素 `results`，GUI 单 profile 视图与 CI 单 profile 断言直接消费；`--format table` 仍走 11 阶段人类报告；
- **B. `state.yaml` 快照副作用** → **已核实（无副作用）**：`run_scan`（`core/scanner.py`）只读；唯一写 `state.yaml` 的是 `save_current_state`（`core/change_tracker.py`），仅在阶段 9 的 `(--fix-skills 且非 --dry-run) 或 --clean` 写入场景触发。GUI 走 `--all-profiles --format json` / 单 profile `--format` 均 early return，不经过阶段 9，故 **read-only 边界结构性成立**，无需额外处理。
- **C. 多 profile 逐条抓取的性能** → **维持现状**：GUI 一次 `--all-profiles` 覆盖全部 profile，无需逐 profile 子进程；单 profile 视图用新增的 `--format` 单 profile 快照，也无逐条开销。
- **D. 一致性 gate 的退出码容忍** → **v1.0 修复**：gate 早期 `set -e` 把 scan.py 的合法 exit 1（存在不合规项）当作失败终止、从未执行复算；v1.0 改为 `set +e` 捕获退出码、仅 exit 2 阻断（见 §5），gate 真正完成复算并归档达 DoD。

## 15. 设计决策记录（ADR，续阶段二）

**ADR-13：GUI 数据通道采用「子进程调用 CLI」，不在 Rust/前端重写引擎。**
理由：CLI 已可独立安装且单命令产出机读快照；子进程 + 同环境 + 同 config 让「结论一致」成为结构性保证，Rust 侧只需搬运 JSON，不承担审计语义，避免双实现带来的结论漂移。

**ADR-14：红黄绿三态由「已安装客户端」逐 record 判定，字段语义对齐 `result_ok`。**
理由：GUI 与 CLI 必须同结论，故三态不复造规则，直接把 `result_ok` 的字段布尔组合映射为绿/红，把「未探测」单独归为黄（区分「探到失败」与「没探」）。

**ADR-15：GUI 只读是硬边界，任何写入按钮直接 reject。**
理由：审计/修复分离是产品级安全承诺，写入仍由 CLI 显式触发（延续产品 §8.1 与阶段一/二 §8）。

**ADR-16：看板前端用自包含 Web（HTML/JS），先浏览器直开验证，再装入 Tauri webview。**
理由：数据契约与渲染可脱离 Rust 独立验证，缩短反馈环；同一前台内容直接作为 Tauri webview 资产，macOS 首发用系统 WebKit。
