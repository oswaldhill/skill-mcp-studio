# 交接文档：v0.31.0 技能版本管理 + 市场源 + 升级链路

> 创建时间：2026-10-23
> 用途：在其他设备上继续开发 v0.31.x
> 前序交接：`HANDOFF-v0.29.0.md`（v0.29.x 的 Hook 与 ai-memory 细节仍在其内）

## 1. 当前状态

### 1a. 版本与代码

| 项 | 值 |
|---|---|
| 当前版本 | **v0.31.0 (build 127)**，已发布（tag `v0.31.0` 推送至 codeup + github） |
| 分支 | develop（与 origin 同步，工作区干净） |
| HEAD | `e121cd8` feat: 升级前备份与技能回滚 |
| 已安装 app | /Applications/skill-mcp-studio.app (0.31.0) |
| CI | Test / Build macOS / Build Windows / Build Linux 全绿 |
| 测试 | **1295 tests OK**（CI_ALLOW_SKIP_DRIFT=1） |

### 1b. 环境要求

```bash
# 仓库内自带工具链（不需要全局安装 Rust）
export RUSTUP_HOME="$PWD/.rustup-home"
export CARGO_HOME="$PWD/.cargo-home"
export PATH="$CARGO_HOME/bin:/opt/homebrew/bin:$PATH"

# 门禁（含干净环境自检，见 §2g）
CI_ALLOW_SKIP_DRIFT=1 bash scripts/ci_parity.sh

# 构建
cd src-tauri && cargo tauri build
```

### 1c. 远端

| 远端 | 用途 |
|---|---|
| codeup `codeup-oswaldhill:oswaldhill/skill-mcp-studio.git` | 主开发 |
| github `github.com:oswaldhill/skill-mcp-studio.git` | CI + Release |

同一 origin 双 push URL，`git push origin develop` 同步两边。

---

## 2. v0.31.0 交付内容

### 2a. 技能版本管理（路线图 P0 #4 前半）

| 能力 | 实现位置 | 要点 |
|---|---|---|
| SKILL.md version 解析 | `core/skill_state.py` `parse_frontmatter_text` | 本地与远端**共用同一解析**（含 name/title/`metadata.short-description` 兜底；数值型 YAML 归一为字符串） |
| 安装/升级版本记录 | `core/skill_market_ops.py` `_record_versions` | 写 `data/skill_versions.json` |
| 更新检查 | `core/skill_market.py` `check_updates` | 三态（outdated/current/unknown）+ 1h 缓存；**限流结果不写缓存** |
| 远端版本读取 | `_remote_skill_version` | 拉 `raw.githubusercontent.com/<o>/<r>/HEAD/<skillPath>` 解析 frontmatter version |
| 时间比对回退 | `_remote_commit_time` + `_iso_lt` | 本地无 version 时按 skillPath 过滤 commit 时间 |
| 升级前备份 | `backup_skill` / `list_skill_backups` / `restore_skill_backup` | `data/skill_backups/<name>/<时间戳>/`；回滚前另存 `.before-restore-<时间戳>` |

**比对链（重要，v0.31.0 修复的核心）**：

```
远端该技能 SKILL.md 的 version   ← 首选（同源比对）
  ↓ 无 version 字段
repo release/tag                 ← 回退（单技能仓库靠 tag 标版本）
  ↓ 都没有
该路径 commit 时间               ← 最后回退（本地无 version 时）
```

曾因**拿 repo tag 比技能版本**导致 larksuite/cli 的 27 个技能永久误报
「有更新」（tag v1.0.98 是 lark-cli 工具版本，技能包版本长期 1.0.0）。
修复后 outdated 22 → 1。

### 2b. 市场源可配置（P0 #4 前半）

`core/market_sources.py`：`skills-sh` / `github-repo` 两类，默认回落 `[skills-sh]`，
可增删改（`data/market_sources.yaml`，写前备份）。CLI：
`--list-market-sources` / `--set-market-source` / `--remove-market-source`。
**按用户定案：QwenWork 与企业 MCP 不视为市场源。**

### 2c. GitHub Token 配置通道

- 存储：`data/github_token`（gitignored）
- 双通道：`GITHUB_TOKEN` 环境变量优先 → 文件回落
  （解决 GUI 从 launchd 启动读不到 shell env 的问题）
- CLI：`--set-github-token`（空串=清除）/ `--get-github-token`（脱敏）
- GUI：设置页 Skill tab `#github-token-card`（状态行 + password 输入）
- 效果：配额 60 → 5000 次/小时

### 2d. 升级链路（含多处迭代）

- **入口**：更新列可点击 tag / kebab「升级到最新版」/ 工具栏「一键升级」
- **单一弹框三阶段**：确认（批量=版本对比表格+分页；单个=版本对比条）→ 进度（进度条+逐行状态）→ 完成（版本变迁+失败原因）
- **假成功检测**：`_parse_upgrade_failure` 识破 `npx` 的 exit 0 但「cannot be checked」
- **自动重装回退**：上游迁移时按 npx 建议的 `add` 命令重装（用户定案：重装也算升级）
- **升级前备份**：见 2a

### 2e. 概览页全量检查

与托盘后台巡检同源（`--snapshot` + `--endpoint-status`），4 维度配置审计
与端点连通性分组呈现，两列分组网格 + 状态点行。

### 2f. 评审修复（v0.31.0 收尾）

完整评审清单见 `docs/REVIEW-v0.31.0.md`（含 60 项逐项结论）。
本次修复 10 项：4 项发布管理（版本号/CHANGELOG/推送/tag）+ 6 项 UI
（列名语义化、空态文案、表格密度、reduced-motion、aria-hidden、--modal-w 变量）。

### 2g. 关键教训：本地过、CI 挂

**现象**：3 个 `execute_plan` 测试本地全绿、CI 失败。

**根因**：`execute_plan` 内部调 `verify_installed` 读**真实文件系统**。
测试只 mock 了 npx runner，没 mock 文件系统 → 本机有技能目录所以过，
CI 干净环境没有 → verify 失败提前返回 → 走不到被测逻辑。

**修法**：用例里 mock `skill_market_ops.verify_installed`。

**防复发（重要）**：新增 `scripts/ci_clean_env_check.sh` —— 用**临时 HOME**
跑全量单测，但显式保留 site-packages 搜索路径（否则 PyYAML/certifi
会因 HOME 变化 import 失败，测出的失败与产品无关）。已接入
`ci_parity.sh` 门禁 1h。**任何新增测试都应先在空 HOME 下跑一遍。**

---

## 3. 待做的工作（v0.31.x / v0.32+）

### 3a. 弹框类名归并（技术债，P2）

现状有五套：`cfm-card`（确认类）/ `modal-form`（表单类）/ `task-card`
（任务进度）/ `ad-modal`（Agent 详情）/ `upg-modal`（升级三阶段）。
样式有重叠，长期维护面大。

建议归并为两套：
- **确认类**：`cfm-card` 家族（含 upg-modal 的变体，用修饰类区分）
- **表单/详情类**：`modal-form` 家族（含 ad-modal）

**风险**：涉及大量 UI 选择器，必须先补契约断言再改，逐套迁移。
DESIGN.md 有多处引用这些类名，需同步。

### 3b. WebDAV 远程同步（路线图 #3 后半）

目标：配置/技能元数据在多设备间同步。设计要点（未定稿）：

- **同步什么**：`data/local_overrides.yaml`、`data/market_sources.yaml`、
  `data/skill_versions.json`（**不含** `github_token`、不含技能包本体）
- **不碰 trunk**：`config.yaml` 只读纪律不变，同步走 overlay 层
- **冲突策略**：待定（时间戳优先 / 手动合并 / 分文件策略）
- **凭据**：WebDAV 用户名密码同样需要文件通道（参考 `data/github_token` 模式）
- **CLI 形状建议**：`--sync-webdav-push` / `--sync-webdav-pull` /
  `--set-webdav-credential`，GUI 放设置页「通用」tab
- 参考已有 `core/config_porter.py` 的脱敏与分流逻辑

### 3c. 其他

- `--skill-rollback` 的 GUI 入口（当前仅 CLI）：技能 kebab 菜单加「回滚到升级前」
- `docs/DESIGN.html` 镜像与 DESIGN.md 的同步核对
- HANDOFF 后续版本继续沿用本文件结构

---

## 4. 关键文件索引（v0.31.0 新增/改动）

| 文件 | 作用 |
|---|---|
| `core/skill_market.py` | 更新检查（三态判定/缓存/远端版本/时间比对） |
| `core/skill_market_ops.py` | 写操作（安装/升级/备份/回滚/版本记录） |
| `core/market_sources.py` | 市场源模型（增删改 + 备份） |
| `core/skill_state.py` | `parse_frontmatter_text`（本地/远端共用解析） |
| `core/config_porter.py` | 配置导入导出（脱敏/分流/备份） |
| `core/config_text.py` | config.yaml 文本级改写（保注释） |
| `gui/dashboard.html` | 单文件 GUI（升级模态三阶段、Token 卡片、市场源卡片） |
| `tests/test_skill_market.py` | 更新检查/远端版本/时间比对/失败检测（66 例） |
| `tests/test_skill_market_ops.py` | 备份/回滚/执行计划（23 例） |
| `tests/test_market_sources.py` | 市场源模型（14 例） |
| `scripts/ci_clean_env_check.sh` | **干净环境自检**（抓本地过 CI 挂） |
| `docs/REVIEW-v0.31.0.md` | v0.31.0 完整评审清单（60 项） |

---

## 5. 在新设备上开始

```bash
# 1. 克隆
git clone git@github.com:oswaldhill/skill-mcp-studio.git
cd skill-mcp-studio && git checkout develop

# 2. 工具链（仓库内自带）
export RUSTUP_HOME="$PWD/.rustup-home"
export CARGO_HOME="$PWD/.cargo-home"
export PATH="$CARGO_HOME/bin:/opt/homebrew/bin:$PATH"

# 3. 跑门禁（含干净环境自检）
CI_ALLOW_SKIP_DRIFT=1 bash scripts/ci_parity.sh

# 4. 阅读
#    - 本文件 §2（v0.31.0 交付与教训）
#    - docs/REVIEW-v0.31.0.md（评审结论与遗留项）
#    - docs/DESIGN.md（UI 规范，改 UI 必须同步 + 补断言）

# 5. 按 §3 选一项开始（建议顺序：3a 技术债 → 3c GUI 入口 → 3b WebDAV）
```

---

## 6. 真机验证纪律（沿用并补充）

- 改 UI 后**必须**重建 `.app` 并截图确认（`cargo tauri build` → 替换
  `/Applications` → 重开 → `screencapture -l <window_id>`）
- 打真实私人端点前先用 tmp fixture
- 改用户文件先手动 `cp` 备份
- 升级/回滚类写操作，先在**非关键技能**上验证（如 playwright-cli），
  用 shasum 比对内容指纹确认真的恢复
- AX 自动化有边界（设置页 tab 点不到、动态按钮时序），必要时人工确认
