# 设计文档：技能版本管理 + 市场源可配置（v0.31.0 #4 前半）

- 日期：2026-10-22 ｜ 分支：develop ｜ 基线 `98a7b01`
- 状态：已批准（用户 2026-10-22 确认）
- 上游需求：PRD v1.4 §6.2（技能版本展示 / 更新检查 / 市场源管理）；路线图 §4c P0#4 前半

## 1. 背景与定案

### 1a. 现状缺口

- 市场源**硬编码**三个（`_SOURCE_SPECS`：skills.sh / qwenwork / enterprise），不可配置；
  后两个依赖特定会话工具实际不可用——**概念错位**（它们是会话工具集成，不是市场）。
- `check_updates` 只对 lock 里带 GitHub `sourceUrl` 的技能查远端——实测本机 25 个已装
  技能 **0 个带 sourceUrl**（来源是飞书等），更新检查实际不可用。
- SKILL.md frontmatter 已有 `version:` 字段（实测 75 个技能有），但**未解析**进
  `skill_meta`，Skills tab 无版本展示。

### 1b. 用户定案（2026-10-22）

1. **QwenWork / 企业 MCP 不是市场源**——从源列表移除。
2. **skills.sh 作为默认源，可删改**；支持自定义远端源。
3. Skills tab 展示版本与更新状态。

## 2. 市场源模型

**存储**：`data/market_sources.yaml`（gitignored 个人配置，同 `discovered_tools`
模式）。文件不存在时回落内置默认 `[skills.sh]`。选独立文件而非 overlay 的理由：
结构化列表数据（yaml.safe_dump 整体读写），不碰 trunk/overlay 合并链，GUI 经
CLI 读写（同 discovered 的通道纪律）。

```yaml
- id: skills-sh
  label: skills.sh 社区技能库
  type: skills-sh          # 内置类型：走 npx skills CLI
  enabled: true
- id: my-hub               # 用户自定义（示例）
  label: 自定义 Hub
  type: github-repo        # GitHub 仓库源：API 查最新 tag/release
  url: https://github.com/owner/skills-repo
  enabled: true
```

- `type` 取值：`skills-sh`（内置）/ `github-repo`（远端仓库）。未知 type 拒绝。
- `id` 唯一键（upsert 语义）；`enabled: false` = 保留配置但检查/搜索时跳过。
- 删除默认源 skills.sh **允许**（用户明确要求可删；删后若无其他源，检查更新
  报「无可用市场源」而不是静默）。

## 3. 版本数据链（三层）

| 层 | 数据 | 来源 | 用途 |
|---|---|---|---|
| 本地版本 | `skill_meta[].version` | 解析 SKILL.md frontmatter `version:` | Skills tab 版本列 |
| 安装记录 | `data/skill_versions.json` | `--market-install` / `--market-upgrade` 写入 `{skill: {version, installed_at, source}}` | 回滚基准（后续版本） |
| 远端版本 | 按源类型查询 | skills.sh 走 CLI；github-repo 走 API | 更新比对 |

本地版本解析：`management_snapshot` 构建 skill_meta 时读各技能 SKILL.md 的
frontmatter `version` 字段（字符串原样透出；缺失为 `null`——**不虚构版本**）。

## 4. 更新检查（`--market-check` 重构）

- **输入**：市场源列表（enabled 的）+ 已装技能（本地 version）。
- **判定**：远端 version vs 本地 version → 三态：
  - `outdated`：远端版本号 ≠ 本地（语义化版本比较，非字符串不等——`1.0.0` vs
    `1.0.0-beta` 需正确排序；解析失败退化为字符串不等比对）；
  - `current`：相等；
  - `unknown`：无本地版本 / 无源可查 / 查询失败 / 限流跳过。
- **缓存**：`data/market_check_cache.json`（TTL 1 小时；`--market-check` 带
  `--force` 跳过缓存；缓存命中时输出 `cache_hit: true`）。
- **限流**：GitHub API 未鉴权 60 次/小时（保留现有保护：配额确认耗尽后本轮
  跳过并标注 reason；支持 `GITHUB_TOKEN` 提升配额）。
- **输出**：`{kind: "market-check", checked_at, cache_hit, skills: [{name, local, remote, state, reason}], summary: {outdated, current, unknown}}`。
- **只读承诺**：绝不调用 `npx skills check`（名为检查实为升级——实测一次调用
  即更新 41 个技能）；只发 HTTP GET，不写技能库。

## 5. CLI 命令（早返回模式）

```
--list-market-sources                                      # 读：源清单（含默认回落）
--set-market-source <id> label=<l> type=<t> [url=<u>] [enabled=<b>]   # 写：upsert
--remove-market-source <id>                                # 写：删除
--market-check [--force]                                   # 增强：新源模型 + 缓存 + 三态
```

- 写命令走 `data/market_sources.yaml`（读-改-写 + 备份）；早返回不跑审计。
- Rust `run_cli` 白名单加 `--list-market-sources` / `--set-market-source` /
  `--remove-market-source` / `--force`（`--market-check` 已在）。

## 6. GUI

### 6a. 设置页 Skill tab「市场源」卡片

- 源列表行：label / 类型 tag / enabled 开关（`.seg-btn`）+ 删除按钮（ghost sm）。
- 添加源表单：id / label / type 下拉（skills-sh / github-repo）/ url（github-repo
  时显示）+「添加」按钮。
- 读写一律经 CLI；行内控件 flex 布局（v0.29.1 裁剪教训）。

### 6b. Skills tab

- 技能清单加**版本列**（`skill_meta.version`，mono 字体；无版本显示 `-`）。
- 工具栏**「检查更新」按钮**（复用现有 `market-check` action 改造）→ 异步跑
  `--market-check` → 技能行更新状态列：**有更新（黄 tag）/ 最新（绿 tag）/
  未知（灰）**；结果缓存于前端变量（刷新页面后需重查）。
- 技能详情 Sheet 补「版本」「更新」两行。

## 7. 测试与验收

- `tests/test_market_sources.py`：CRUD（tmp 隔离）/ 默认回落 / 未知 type 拒绝 /
  id 唯一 upsert / 删默认源允许。
- `tests/test_skill_version.py`：frontmatter version 解析（有/无/格式异常）进
  skill_meta；安装记录写入。
- `tests/test_market_check.py`：三态判定（语义化版本比较 + 退化字符串）/
  缓存 TTL 与 force / 限流跳过 / 无源报错。
- GUI 契约断言：版本列 / 检查更新按钮 / 市场源卡片 / 三态 tag。
- 全量门禁全绿。

## 8. 明确不做（out of scope）

- **回滚**（`--skill-rollback` 留后续——`skill_versions.json` 已为此铺路）；
- **自动更新**（只检查不自动升级；升级仍走 `--market-upgrade` 手动确认）；
- QwenWork / 企业 MCP 集成（已移除；若未来需要按「会话工具集成」另立概念）。

## 9. 实施顺序

| 步 | 轨 | 内容 |
|---|---|---|
| 1 | D1 | `core/market_sources.py`（模型 + CRUD + 默认回落）+ 单测 |
| 2 | D2 | skill_meta 版本解析 + `skill_versions.json` 安装记录 + 单测 |
| 3 | D3 | `check_updates` 重构（新源模型 + 缓存 + 三态）+ 单测 |
| 4 | D4 | CLI 三命令 + `--market-check` 增强 + 单测 |
| 5 | E | Rust 白名单 + cargo test |
| 6 | F | GUI（市场源卡片 + Skills tab 版本/更新列 + 检查按钮）+ 契约 |
| 7 | H | README 命令速查 / CHANGELOG / DESIGN.md §2.10 归属细化 |
| 8 | 验证 | 全量门禁 + 真机端到端 |
