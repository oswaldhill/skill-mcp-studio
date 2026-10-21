# 设计文档：Hook 命令变量插值（补 v0.29.0 缺口）+ 配置导入/导出（v0.30.0 #3 本地+iCloud）

- 日期：2026-10-21 ｜ 分支：develop ｜ 基线 `14f41e7`（v0.29.2 / build 125）
- 状态：已实施（2026-10-21，D1/D2/D3/E/F/H 七步全部落地；实施中新增两项计划外修复：
  auto_discover overlay 断链（§3.3 前置）与 _set_default_command_in_text 引号加固，
  详见 CHANGELOG [Unreleased]）
- 上游需求：路线图 §4c P0#1（插值半项）+ P0#3（导入/导出）；PRD §6.4

## 1. 背景与问题

### 1a. 变量插值未实现（v0.29.0 遗留缺口）

设计 `2026-10-16-hook-write-configurable-design.md` §4.1 承诺「变量插值：
`{event}`（snake_case 事件名）、`{agent}`（agent_slug）、`{server_url}`（活动
profile 的 URL）」，PRD §6.4 与路线图 P0#1 同口径。但实测
`core/hooks_fixer.py` 全文无任何 format/replace 逻辑：`fix_hooks_tool` 把
template 命令**原样**写入客户端配置。后果：用户应用「日志记录」预设
（`echo {event} triggered >> ~/.hook.log`）后，客户端执行的是字面 `{event}`
——`{event}` 不是任何客户端的 hook 变量语法，等于写入坏命令。

### 1b. 配置导入/导出未开始（v0.30.0 #3）

换机器 / 团队分享时，配置分散在三处：trunk `config.yaml`（版本受控）、
`data/local_overrides.yaml`（gitignored 个人拓扑 overlay）、
`data/discovered_tools.yaml`（自动发现客户端）。无打包迁移手段。

## 2. 需求结论（用户已确认）

1. 插值补齐：写入前对命令模板做 `{event}` / `{agent}` / `{server_url}` 替换。
2. 导入/导出：本地文件 + iCloud 路径先行；**WebDAV 留下个版本**（本机无
   服务器可验证，不交付未验证代码）。
3. GUI：设置页新增「配置导入/导出」卡片；CLI 同步提供两条命令。
4. #2 打包完善本轮**只做文档收尾**（targets 已在平台 conf 声明；CI
   `--bundles`、Windows 签名、AppImage 瘦身本地无法验证，不动 CI）。

## 3. 方案

### 3.1 Hook 变量插值（D1 轨：改 `core/hooks_fixer.py`）

**插入点**：`fix_hooks_tool` 的 template 构建循环（L141-149）——该处同时持有
canonical 事件名与 client_name，是唯一能做 `{event}` 插值的位置：

```python
template[client_name] = _interpolate(
    cmd, canonical=canonical, agent_slug=..., server_url=...)
```

**变量来源**：

| 变量 | 来源 | 缺省行为 |
|---|---|---|
| `{event}` | 该事件 canonical snake_case 名（如 `session_start`） | 必有（写入时已知） |
| `{agent}` | `hooks.clients[].agent_slug`（config.yaml 声明） | 未声明 → 客户端名 slug 化（`WorkBuddy` → `workbuddy`） |
| `{server_url}` | 活动 profile 的 `url`（`config["profiles"][config["active_profile"]]`） | 取不到（无活动 profile / 无 url）→ **保留 `{server_url}` 原样**，dry-run 提示 |

**边界**：
- 未识别的 `{xxx}` 一律保留原样（不吞、不报错）——用户可能写 shell 的
  `${VAR}` 或字面 `{}`，不能误伤。
- 无占位符的命令插值为 no-op：**已写入的旧命令零影响**。
- 不做转义语法（YAGNI；需要字面 `{event}` 的场景文档说明用 `''` 包裹或
  避开预设）。
- 插值只发生在**写入时**（fixer 侧）；`--set-hook-template` 存的是原始模板
  （含占位符），每次写入重新插值——改 agent_slug / 活动端点后重写即生效。
- dry-run 输出插值后命令预览（`[dry-run] 将写入 N 个事件` 消息里附第一条
  插值样例，避免刷屏）。

**新函数**（模块级，便于测试）：

```python
def _interpolate(command, *, canonical, agent_slug, server_url) -> str
def _client_agent_slug(hc, client_name) -> str   # agent_slug 或名字 slug 化
def _active_server_url(config) -> str            # 活动 profile url，取不到返回 ""
```

### 3.2 配置导出（D2 轨：新模块 `core/config_porter.py`）

```python
def export_config(dest: str, *, config_path=None, include_discovered=True,
                  dry_run=False) -> Dict[str, Any]
```

- `dest` 为输出路径；特殊值 `icloud` 解析为
  `~/Library/Mobile Documents/com~apple~CloudDocs/skill-mcp-studio/config-export.json`
  （非 macOS 报错说明不支持；目录不存在则创建）。
- 导出内容（单 JSON，UTF-8，带换行）：

```json
{
  "kind": "skill-mcp-studio-config-export",
  "schema_version": 1,
  "exported_at": "2026-10-21T13:00:00+08:00",
  "app_version": "0.30.0",
  "config": {            // 生效视图（trunk + overlay 合并后的这些顶层键）
    "active_profile": ..., "auto_discover": ..., "unified_skills_dir": ...,
    "settings": ..., "hooks": ..., "disabled_tools": ...
  },
  "profiles": { ... },   // 端点定义（auth_token 脱敏）
  "discovered_tools": [ ... ]   // --skip-discovered 时省略
}
```

- **脱敏**：`profiles.*.auth_token` 非空时替换为 `"<redacted>"`（导出文件
  可能进 iCloud / 被分享，密钥不落盘）。其余字段原样（hooks 模板是用户
  命令，属迁移对象，不脱敏）。
- 生效视图取法：复用 `profile_loader.apply_profile_sources` 合并后的 config
  （与审计同源，保证「导出的就是当前生效的」）。
- `dry_run`：只返回将写的内容与目标路径，不落盘。

### 3.3 配置导入（同模块）

```python
def import_config(src: str, *, config_path=None, dry_run=False) -> Dict[str, Any]
```

- `src` 为 JSON 文件路径或 `icloud`（同上解析）。
- **合并语义（写 overlay，不动 trunk）**：
  - `config` 段各键 → 写入 `_overlay_target`（与 `set_unified_dir` 同通道：
    第一个已存在 overlay 或 `data/local_overrides.yaml`，首次写自动注册
    profile_source）。逐键覆盖（导入值优先），**不删除**本地已有键。
  - `profiles` 段 → 逐端点合并进 overlay 的 `profiles` 键（overlay 的
    profiles 会经 `apply_profile_sources` 合并覆盖 trunk 同名端点）。
    遇 `auth_token: "<redacted>"` **跳过该字段**（保留本地值；本地也无则
    留空），并在结果里提示「N 个端点的 auth_token 需手动补」。
  - `discovered_tools` → 按 `name` 去重合并进 `data/discovered_tools.yaml`
    （导入条目覆盖同名，其余保留）。
- **导入前自动备份**：overlay 与 discovered 各生成一份 `.bak-<ts>`（复用
  `file_atomic.backup_path` 约定，可被 `--list-config-backups` 列出）。
- 校验：`kind` 不符 / `schema_version` 不识别 → 报错退出（exit 2 语义），
  不做部分导入。
- 结果 dict：`status` / `message` / 写入键清单 / 跳过的 redacted 字段数 /
  备份路径。

### 3.4 CLI 命令（D3 轨：`scan.py`）

```
--export-config <path|icloud> [--skip-discovered] [--dry-run]
--import-config <path|icloud> [--dry-run]
```

- `--skip-discovered`：store_true，默认导出含 `discovered_tools`，加此参
  则省略（换机重建场景：目标机自己重新发现）。

- 早返回模式（与 `--set-hook-template` 同款）：加载 config → 调
  config_porter → 打印结果 → return，不跑审计。
- `--dry-run`：导出打印将写的 JSON（脱敏后）；导入打印将合并的键与备份
  计划。

### 3.5 GUI 卡片（F 轨：`gui/dashboard.html` 设置页）

- 位置：设置页 appearance tab 之后（「关于」卡片之前），新卡片
  「配置导入/导出」。
- 结构（复用 `.card` + `.row` 形态，控件一律 `flex:1 1 auto`，**禁止 inline
  `width:100%`**——v0.29.1 裁剪缺陷教训）：
  - 导出行：路径输入（默认空，placeholder 提示绝对路径或 `icloud`）+
    「导出」按钮（ghost sm）+ 说明 note（含脱敏提示）。
  - 导入行：路径输入 + 「导入」按钮 + 确认弹窗（复用现有 confirm 模态，
  文案说明「合并写入 overlay，不动主配置；导入前自动备份」）。
  - 结果 toast（成功 / 失败 + redacted 提示）。
- 异步走 `runCli(["--export-config", path])` / `--import-config`，完成后
  `refreshBlocks(["settings"])`。
- DESIGN.md §2.10 增补该卡片规范（结构 / 取值 / 为什么）。

### 3.6 Rust 白名单（E 轨：`src-tauri/src/lib.rs`）

`ALLOWED` 列表加 `--export-config` / `--import-config`（只读参数
`--include-discovered` 随命令放行；`--dry-run` 已在白名单机制内）。

## 4. 测试与验收

新增 `tests/test_hook_interpolation.py`：
- 三变量齐插（logging 预设 → `echo session_start triggered`）；
- agent_slug 缺省回退（WorkBuddy → `workbuddy`）；
- server_url 取不到 → `{server_url}` 原样保留；
- 未识别 `{xxx}` / `${VAR}` / 无占位符 → no-op 原样；
- dry-run 消息含插值样例；
- 既有用例零改动（插值对无占位符命令是 no-op）。

新增 `tests/test_config_porter.py`：
- 导出：kind/schema 字段、auth_token 脱敏、`icloud` 路径解析（macOS）与
  非 macOS 报错、dry-run 不落盘；
- 导入：合并写 overlay（trunk 不动）、redacted 跳过、discovered 去重、
  备份生成、kind 不符报错、导入后 `apply_profile_sources` 能取到导入值；
- 隔离：全部用 tmp 目录 + 指向 tmp 的 profile_sources（吸取
  test_config_overlay_writes 的教训：**不让 overlay 落到仓库真实
  data/local_overrides.yaml**）。

GUI 契约（`tests/test_design_spec_contract.py` 增断言）：
- 卡片存在 + 控件无 inline `width:100%`（守住 v0.29.1 根因）；
- DESIGN.md §2.10 与 dashboard.html 镜像（卡片标题字面一致）。

门禁：`CI_ALLOW_SKIP_DRIFT=1 bash scripts/ci_parity.sh` 全绿（含 ruff /
node / cargo / 文本卫生）。

## 5. 明确不做（out of scope）

- WebDAV 远程同步（`--sync-config webdav://`）——留下个版本，本机无服务器
  可验证；
- 插值转义语法；
- CI `--bundles` / Windows 代码签名 / AppImage 瘦身（本地无法验证，只做
  路线图状态回写）；
- 导出的加密压缩（密钥已脱敏，明文 JSON 足够）；
- GUI 导入的拖拽 / 文件选择器（路径输入先行，Tauri dialog 插件可后续加）。

## 6. 实施顺序

| 步 | 轨 | 内容 |
|---|---|---|
| 1 | D1 | hooks_fixer 插值三函数 + 循环接入 + 单测 |
| 2 | D2 | config_porter 导出/导入 + 单测（tmp 隔离） |
| 3 | D3 | scan.py 两条命令 + 早返回 + 单测 |
| 4 | E | lib.rs 白名单 + cargo test |
| 5 | F | GUI 卡片 + DESIGN.md §2.10 + 契约断言（含反向验证） |
| 6 | H | PRD §6.4/§8、路线图 §4c/§4d、README 命令速查、CHANGELOG |
| 7 | 验证 | 全量门禁 + `--export-config`/`--import-config` 真机端到端（tmp 副本） |

## 7. 风险与对策

- **插值误伤既有命令**：无占位符 no-op + 既有 17 个 hooks 测试零改动作
  回归护栏；
- **导入写坏 overlay**：导入前双备份 + dry-run 预览 + kind 校验拒绝部分导入；
- **iCloud 路径因设备而异**：`icloud` 别名只在 macOS 生效，其余平台显式
  报错（不静默写错地方）。
