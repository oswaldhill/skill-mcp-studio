# 技能市场接入 + 版本更新检测 + 在线升级

- 日期：2026-09-23 ｜ 分支：develop
- 新增：`core/skill_market.py`、`tests/test_skill_market.py`、`tests/test_dashboard_market_ui.py`
- 改动：`scan.py`、`gui/dashboard.html`
- 前置事实：`~/.skills-manager/skills` 是统一技能库实体目录，四个客户端目录均为指向它的
  符号链接（`~/.agents/skills`、`~/.codex/skills`、`~/.dsh/skills`、`~/.hermes/skills`，
  实测 `ls -ldi` 确认）

## 问题

统一技能库 209 个技能全靠手工下载或 `npx skills` 命令行维护，本管理台看不见来源、
版本与更新状态。需要：①在 GUI 中搜索并安装市场技能；②检查已装技能是否有上游更新；
③在线升级到最新版。

## 市场源实测结论（2026-09-23 本机）

| 源 | 接入方式 | 实测 |
|---|---|---|
| A. QwenWork 官方市场 | `mcp__qw-builtin__qw_query`，key `qwenwork.settings.skills.market` | **不可用** —— `~/.dsh/mcp.json` 只有 `hermes`、`image-vision`，无 `qw-builtin`（QwenWork 客户端专属） |
| B. skills.sh 社区库 | `npx skills find/add/list/update` | **可用** —— 实测 `npx skills find react` 返回真实结果 |
| C. 企业技能市场 MCP | 动态探测 `searchSkills` | **未探测到** |

结论：**只实现源 B**。源 A/C 在界面上标注「未检测到」并说明原因，**不报错**。

## 关键事实（实测，构成实现约束）

1. `~/.skills-manager/skills` 是唯一实体；四个客户端目录是符号链接 ⇒
   `npx skills add -g` 装到 `~/.agents/skills` 即**已落在统一库**，
   **不需要额外的归一机制**，只需装后校验。
2. `.skill-lock.json`（`~/.agents/`，version 3）是来源登记：`source` /
   `sourceType` / `sourceUrl` / `skillPath` / `installedAt` / `updatedAt`。
   **`skillFolderHash` 为空字符串**，不可用于版本比较。
3. `npx skills` 支持 `--json` 的子命令：`list -g --json` 输出干净 JSON；
   `find` / `check` **不支持**（输出带 ANSI 转义与 `◐ Fetching…` 刷新行，必须清洗）。
4. 已装 209 项、58 项在 lock 中登记；来源含 `larksuite/cli`(27)、
   `firecrawl/*`(13)、`anthropics/skills`(2)、`trailofbits/skills`(2) 等。

## 硬约束：`npx skills check` 是破坏性命令，禁止调用

**实测事故记录**：该命令名为 `check`（且未出现在 `--help` 列表中），**实际执行升级**
——本机一次调用即更新 41 个技能。`npx skills update` 亦**无 `--dry-run`**。
因此「检查更新」**必须自行实现只读检测**，不得调用这两个命令。

事故核验结论（留存备查）：41 个受影响技能全部为市场来源，无 `local` 来源被改动；
与上游文件数逐一吻合（`lark-minutes` 1=1、`lark-base` 27=27、`lark-doc` 44=44、
`lark-vc` 1=1）；49 个文件删除均系上游自身移除。已在技能库 git 中留检查点提交。

## 方案

### 1. `core/skill_market.py`（新增，检测层只读）

- `detect_backend()` —— 探测 `npx` 与 `skills` 可用性、版本；缺失则整体降级为
  「未检测到后端」，界面给安装指引，不报错。
- `read_sources()` —— 三源可用性汇总（见上表）。
- `list_installed()` —— 读 `.skill-lock.json` + 统一库目录，输出
  `{name, source, sourceUrl, skillPath, updatedAt, installedAt, agents[]}`。
- `search(query, owner=None)` —— 包 `npx skills find`，剥离 ANSI 与进度行后结构化。
- `check_updates()` —— **只读**更新检测，见下节。

### 2. 更新检测（只读，双通道）

判定「有更新」需比较本地与上游该 `skillPath` 的最新提交：

1. **主通道**：GitHub API
   `GET /repos/{owner}/{repo}/commits?path={skillPath}&per_page=1` 取最新提交时间，
   与 lock 的 `updatedAt` 比较。支持可选 `GITHUB_TOKEN` 提升配额
   （**实测未鉴权会触发 `API rate limit exceeded`**）。
2. **降级通道**（主通道限流或失败时）：`git clone --depth 1 --filter=blob:none
   --sparse` 到临时目录比对（实测可用、无速率限制），用完即删。
3. **三态输出**：`有更新` / `已最新` / `无法检测`。「无法检测」对应私有库或已删除
   仓库（实测 12 个属此类，`npx skills` 自身也报 `Private or deleted repo`），
   界面给出官方建议命令而非静默失败。
4. 结果**带缓存**（记录检测时间），避免每次进页面都全量探测。

### 3. 在线升级（写操作，必须确认）

- 单技能：`npx skills add <sourceUrl> -g -y`（官方对「无法自动检测」条目给出的同一路径）。
- 批量：`npx skills update -g`。
- **执行前**：展示将受影响的技能清单与来源，二次确认。
- **执行后**：核对 `git status` 与文件数，输出「成功 N / 失败 M」。
- 升级前在技能库 git 中留检查点提交，保证可回退。

### 4. CLI

```
--market sources              列出源可用性（只读）
--market search <query>       搜索（只读）
--market list                 已装 + 来源 + 更新状态（只读）
--market check                检查更新（只读，不调用 npx skills check）
--market upgrade [name...]    升级（写，需 --yes）
```

### 5. GUI（Skills 页新增「市场」入口）

**进度展示按逐技能显示**（用户明确要求）：

- **搜索**：loading 态 + 骨架屏
- **检查更新**：逐技能进度行 `正在检查 larksuite/cli … 3/46`，可取消
- **安装 / 升级**：流式逐技能输出 `Updating firecrawl-build-scrape… ✓`，
  每行即时追加，不批量刷新
- **收尾汇总**：`成功 41 / 失败 0 / 无法检测 12`，失败项列出原因与建议命令
- 复用现有 `runTaskModal(title, run, refresh, stages)`（`dashboard.html:1516`，
  已支持分阶段与流式），不新造进度组件

### 6. 安全边界

- ❌ 不调用 `npx skills check`（破坏性，见硬约束）
- ❌ 不自动更新、不静默安装、不批量安装（安装/升级一律二次确认）
- ❌ 不重写 `.skill-lock.json`（保持 `npx skills` 为单一事实源）
- ✅ 安装/升级前展示来源仓库，供判断供应链风险（本机已有 `skill-vetter` 技能）

## 刻意不动

- 不改技能审计链（`combined_checker` → `run_scan`）与 `clients_states` 口径
- 不改 `--fix-skills` / `--migrate-skill-links` 既有语义（归一已由符号链接天然达成）
- 不改 `config.yaml` 的 `unified_dir` 约定
- 本子项目**不含**技能合并 / 归一 / 优化 / 清理的内容层能力（那些是后续子项目）

## 验证

`tests/test_skill_market.py`：

- 源可用性探测：后端缺失时降级不报错
- lock 解析：来源/时间字段正确，`skillFolderHash` 为空时不误用
- **`check_updates` 全程只读**：断言代码中不出现 `skills check` / `skills update`
  调用（护栏，防止回退到破坏性实现）
- 输出清洗：ANSI 与 `◐ Fetching…` 进度行被剥离
- 三态判定：有更新 / 已最新 / 无法检测

GUI 护栏（`tests/test_dashboard_market_ui.py`）：市场入口存在、按钮已接线、
进度区逐技能渲染、安装前有确认步骤。

另需全量 `pytest` 与 CI 三平台通过。
