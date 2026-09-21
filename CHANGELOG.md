# 变更日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 约定，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

> 注：项目早期历史未按版本逐次发布，以下按可识别的版本里程碑汇总。

## [Unreleased]

### 修复

- **新增「被外部工具改写」识别与一键回流（DATA-8）**：`~/.codex/config.toml` 这类
  文件是**多写者竞争**的。实测：CC Switch 每次切换通道都用它自己的两个片段
  （当前 provider 的 `config` + `codex` 通用配置）重新生成整份文件，而这两个片段里
  **不含任何 `[mcp_servers]`**；把活文件去掉 `mcp_servers` 后与二者合并结果比对，
  12 个键与值完全一致。因此凡是不被它登记的端点（如 `K8s-uat`、`hermes`）都会被
  静默抹掉，而它自己登记的（`hermes-nas`：活文件里的块与它数据库里的配置逐字节一致）
  与客户端自带的（`node_repl`、`computer-use`）则存活。现场复现：16:03:15 修复写入
  成功，**34 秒后**即被写回旧状态。
  快照新增 `drift`（`suspected` / `lost` / `backup_count` / `last_backup` /
  `last_backup_at`），判据只用一个客观事实：`<config>.bak-*` 兄弟备份是**本工具写入
  前**留下的，故「有备份 + 期望端点不见」= 写入成功过、之后被别人改掉（疑似外部
  改写）；「无备份 + 端点不见」只是「尚未应用」。面板据此在客户端标签位说明**原因**
  并就地给出 `回流` 按钮（复用既有 `fix-mcp` 动作，写入前自动备份），图例汇总
  「N 个疑似被外部改写」；`缺失` 仍表达端点状态，原因与状态分开表述。

- **「不支持 MCP」被误报成「缺失」**：注册表未声明 `mcp_config_path` 的客户端
  （实况 `ima.copilot`，已安装但没有 MCP 配置文件）根本没有 MCP 能力，
  却仍被按默认「全部端点」套上期望，于是判成「声明要挂却没挂」的异常，
  在异常计数里多出一个虚假故障。快照新增 `supports_mcp`，不支持时期望与缺失
  均为空（`core/management_snapshot.py`），能力缺失不再计入异常。
  界面上「不支持」与「缺失」双维度区分：缺失 = 橙色空心环 + 左侧 2px 警示条
  （真异常）；不支持 = 灰色横杠 + 整行去强调（不适用，非故障），端点列显示
  「不适用」、挂载列显示「不支持」，且不计入异常数。首页 MCP 列的「无配置」
  一并统一为「不支持」，与面板共用一套词汇。

### 变更

- **MCP 面板改为单表覆盖矩阵**：P2 修复之后，「端点挂载状态」列（端点键 + 状态 +
  来源长文案）与下方「端点 × 客户端 覆盖矩阵」表达的是同一份数据，界面出现两张等价表，
  且单元格里重复端点名，既冗余又难纵向扫读。现合并为一张表
  （客户端 / 各端点状态列 / 挂载 / MCP 条目），端点名只在表头出现一次，
  端点库之外但实际观测到的端点仍会补出列，不会静默丢状态。
- **状态改为形态 + 色彩双编码**：实心点 = 配置里已有；空心环 = 声明要挂却缺失；
  浅灰环 = 未纳入期望；灰色横杠 = 不支持 MCP。异常行用左侧 2px 警示条标注，
  不再用与客户端名争权重的 `⚠ N` 角标；端点表头保留大小写（此前被 `thead` 的
  `text-transform: uppercase` 改写成 `K8S-UAT`）；「来源」由每行长文案改为
  `手动` / `自动` 微标签 + tooltip，语义在页面提示与图例里解释一次。
- 图例复用 Skills 面板的 `.skill-legend` 形态，右侧汇总「N 客户端 · M 端点 ·
  K 个不支持 MCP · K 个存在缺失」；新增空端点库、零客户端、显式声明、
  库外端点等边界处理。

### 测试

- 新增 `tests/test_dashboard_mcp_ui.py` 20 例：源码结构护栏（单表、端点名仅在表头、
  表头大小写、形态/色彩双编码、不支持与缺失的形状区分、警示条只给异常、
  语义只解释一次、首页与面板词汇一致）与 node 渲染快照（对齐后的表头/行内容、
  仅异常客户端被标注、不支持行读作不适用、两类计数分离、旧快照回退、
  输出无 `⚠`/`✓` 图形字符、空库/库外端点/零客户端/手动来源）。
- `tests/test_management_snapshot.py` 新增 DATA-7 用例，锁定「不支持 MCP 不得报成
  缺失异常」，并与「声明要挂却没挂仍判缺失」的对照组一并断言；新增 `DriftDetectionTest`
  5 例锁定漂移判据（有备份+缺失=外部改写、无备份=尚未应用、无缺失不报、文件不存在不抛）。
- `tests/test_dashboard_mcp_ui.py` 13 → 26 例。
- 全量 **570 passed, 28 subtests**。

> 以下为合入 `master` 前累积的未发布记录。

## [v0.21.1] - 2026-09

当前发布版本（build 107）。

### 修复

- **P0（数据损失）TOML 嵌套子表被当成独立 MCP 条目**：`parse_toml_mcp_servers` 只特判了
  `.env` 子表，其余子表一律落成新 server。Codex 用
  `[mcp_servers.<name>.tools.<tool>]` 记录 `approval_mode` 审批设置，于是真实 4 个 server
  被解析成 **11 条**，多出的 7 条被归类为「未纳管」并出现在「清理未纳管」清单里——点击即
  删掉这些审批设置。现按 TOML 语义只取**第一个点分段**为 server 名，更深子表归属该 server
  且不贡献字段（`env` 仍折叠进 `env`）；只有子表、没有父表时不再凭空造出 server。
  顺带修正两处泄漏：段头可带 `# 注释`（此前导致该段字段写入**上一个** server）、非
  `mcp_servers` 段结束当前上下文（此前跨段字段会混入上一个 server）。
- **P1（假阳性）「已配置 MCP 端点」把期望当事实**：端点列原本直接渲染 `mcp_attach`，而未
  显式声明时 `resolve_client_attach` 返回**端点库全集**，因此一个 `config_path` 为空、
  inventory 为 0 的客户端也显示为「已配置两个端点」。快照新增
  `has_explicit_attach` / `observed_attach` / `missing_attach` / `undeclared_attach`
  （`mcp_inventory.attachment_consistency`），把「期望」与「实际观测」分开，使
  **声明要挂却没挂**可被判为异常。实况：`ima.copilot` 由「已配置 K8s-uat, hermes-home」
  修正为 **⚠ 2 个端点未挂载**。
- **P2（冗余与误标）界面两列语义重叠**：第二列改为**端点视角的挂载状态**（已挂载 ✓ /
  未挂载 ⚠ / 未配置），并标注期望来源（手动指定 vs 自动默认全部端点）；第三列保留
  「配置文件里的真实条目」并在 tooltip 里给出 `端点：<key>` 映射，消除两列命名错位
  （端点键 `hermes-home` vs 配置键 `hermes`）。覆盖矩阵同步改为按**实际观测**着色，修掉
  同一假阳性，并修正把 `attached`（已挂载但未声明）显示成「未纳管」的误标。

### 测试

- `tests/test_config_codec.py` 9 → 20 例（嵌套子表、跨段字段泄漏、真实 Codex 形状回归、
  两条解析链路一致性）；新增 `tests/test_mcp_attachment_consistency.py` 12 例
  （观测端点、期望/缺失/未声明、快照字段护栏）。全量 **538 passed, 28 subtests**。

## [v0.21.0] - 2026-09

该版本构建号 build 106。

### 新增

- **MCP 条目删除与清理**：管理台可按条目或按分类（`attached` / `legacy` /
  `unmanaged`）清理任意客户端的 MCP 条目，**包含以往只能查看、不能删除的「未纳管」
  条目**。新增 CLI：`--remove-mcp-entry`、`--remove-mcp-class`、`--list-config-backups`、
  `--restore-config-backup`，以及高风险门 `--force-high-risk` / `--include-high-risk`
  （共 6 个参数，均支持 `--dry-run`，新命令支持 `--format json`）。
- **高风险分级确认**：识别「疑似客户端自带」的条目（命令落在该客户端 `app_bundles`
  内、路径含 `.app/Contents/`、或条目名与客户端同名/别名），默认拒绝删除；GUI 需
  **手输条目名**方可解锁。本机实测恰好命中 Codex 的 `node_repl` 与 `computer-use`。
- **配置备份回滚**：可列出某客户端配置的历史备份并从任意一份还原（整文件覆盖，
  还原前自动再备份当前文件）。

### 修复

- **JSONC 配置无法删除条目/还原备份**：`json.loads` 不接受 JSONC 注释，带注释的
  `opencode.jsonc` 在删除时报 `error`、还原报 `refused`。改为**按字节范围定点删除
  成员**（不使用「解析→改 dict→序列化」），注释、缩进、键序逐字保留；校验路径改为
  「注释屏蔽后再解析」。新增 `core/jsonc_text.py`（含 34 个用例）。
- **删除原语的假成功**：JSON/YAML/Reasonix 分支在**没有命中任何待删条目**时仍会
  重新序列化，把「无操作」误报成 `updated` 并顺手改写用户配置、生成备份。现统一
  满足「无命中则原样返回」不变式（与既有 cordis 分支对齐）。
- **测试跨用例状态污染**（长期存在的顺序依赖失败）：`SetUnifiedDirTest.setUp` 把
  `config_store._local_overrides_file` / `_overlay_target` 两个**模块级函数**替换为
  指向自身临时目录的 lambda，`tearDown` 却只清理目录、未还原函数。污染因此在同
  进程内持续存活，后续 `OverlayRegistrationTest` 拿到的「原函数」已是污染版本，
  其 `_overlay_target` 返回前一个用例已销毁的临时目录。表现为
  `test_overlay_target_reuses_first_existing_profiles_local` **单独运行通过、按文件
  或全量运行失败**。已在 `setUp` 记录原函数、`tearDown` 还原。全量测试
  `1 failed, 514 passed` → **`515 passed`**。

### 变更

- **六维度深度评审整改**：按 `docs/reviews/评审报告-v0.20.0-六维度深度评审.md`
  完成 54 项整改——CLI 契约单源（A-1）、探测三态退出码（A-2）、注册表收敛（A-3/A-4）、
  无环 import（A-5）、config_codec（A-6）、`main()` 拆分 `build_parser()` 与 Phase 7 编号
  补齐（A-7）、active_profile 只读定案（P-3）、后端 `state` 契约落到每条 record（U-2）；
  auth_token 0o600（D-3）、open_url 注入加固 + CSP 收紧（D-4）、除死代码与裸 except
  （D-2/D-9）、TOML 转义（D-8）、原子写（D-6）、退出码 2 分层（D-7）；GUI 键盘可达性 /
  CLI 未装透出 / 语义色 / 模态可及性（U-1/U-3/U-4/U-5）；CI 测试门禁（Python unittest +
  cargo test + node:test）+ 签名/公证验证 + SHA256SUMS + 平台 bundle.targets +
  concurrency（T-1/B-2/B-3/B-4/B-6）；Rust `#[cfg(test)]`（spawn 路径解析 + open_url
  注入）+ node:test 纯函数（T-3）；pytest/coverage 配置 + wheel 形态守护 + 跨平台路径 +
  flaky/文件句柄/环境耦合修正（T-4..T-10）；QwenWork/TraeWork 注册表（P-5/B-8）；arm64
  按需立项文档化（B-9）。测试 381 → 448（Python 440 + Rust `cargo test` 3 + node:test 5）。
- **Tauri 白名单**：`run_cli` 的允许参数新增上述 4 个命令（壳只透传 argv、写盘仍在
  CLI 的安全链内）。
- **构建文档**：修正 `src-tauri/BUILD.md` 中仓库本地工具链的 `PATH` 写法——原写法
  `$CARGO_HOME` 含 `..`，会导致 `cargo: command not found`。

## [v0.20.1] - 2026-09

build 105。

### 修复

- **安装探测**：GUI 壳（Finder / Dock 启动）继承 launchd 的最小 PATH，使经
  Homebrew / npm / pipx 安装的 CLI 探测落空，在用客户端被误判为 `config_only`
  「仅配置」——该状态会开放「删除客户端」清理入口（备份后删除其配置文件）。新增
  `tool_registry.which_with_fallback`：PATH 优先，未命中再兜底常见 bin 目录
  （Windows 按 `PATHEXT` 补后缀），成为 `detect_installation` 的默认实现；调用方
  注入 `command_exists` 时仍完全接管该逻辑，测试契约不变。
- **注册表**：`DeepSeek Harness` 的 app bundle 更正为 `/Applications/DeepSeek
  Harness.app`（旧名 `DeepSeek AI Assistant.app` 保留兜底），`commands` 补
  Homebrew 绝对路径，并修正过期的 bundle id 注释；主流默认注册表条目同步补
  `app_bundles`，三平台一致。附带效果：`Claude Code` 等仅声明裸名 CLI 的客户端
  也从漏判中恢复。

### 工程化

- `scripts/bump_version.py` 同步范围扩展：新增 README 版本 badge、`SECURITY.md`
  「当前版本」、架构图版本标注、控制台浏览器预览兜底、Issue 模板版本示例与
  CHANGELOG 链接块，消除文档版本与 `version.json` 的漂移。
- 新增 `CliFallbackTest` 回归用例：裸名兜底命中、路径形态不扫描、默认走兜底、
  注入语义不变。

## [v0.20.0] - 2026-09

build 104。

### 变更

- **跨平台**：新增 Windows / Linux 构建支持——`mainstream_registry` 引入 `by_os`
  + `sys.platform` 路径分派，`tool_registry` 新增 `expand_path` 统一展开 `%VAR%`
  与 `~`，Rust 壳 `cli_candidates` 三平台适配；新增 `build-windows.yml`
  （NSIS + MSI）与 `build-linux.yml`（deb + rpm + AppImage）。

### 修复

- 修复 Windows / Linux 跨平台构建失败。

### 工程化

- tag（`v*`）触发时把 `.exe` / `.msi` 与 `.deb` / `.rpm` / `.AppImage` 追加到同一
  GitHub Release；非 tag 触发仍只上传 artifact（与 `build-macos.yml` 对齐）。
- 新增 GitHub 推送门禁 `pre-push` hook 模板：推送到 GitHub 需显式放行
  （`GITHUB_PUSH_ALLOW=1`）。

## [v0.19.0] - 2026-09

build 103。
### 变更

- **隐私加固**：主干中硬编码的真实端点域名与 IP 全部改用占位符；`ai-memory` 默认服务
  地址改用 `127.0.0.1` 占位。
- **UI**：浏览器预览示例改为「未配置」初始态（不预置端点）；合并预览口径统一；端点
  测试；设置子页持久化。
- **MCP**：鉴权改为明文 `Bearer` 头落库；修复覆盖所有纳管端点并支持鉴权落库。
- **Skills**：新增 `SKILL.md` frontmatter 契约审计。
- **修复**：一键修复失败详情改用 `cliFailLines` 提取关键行；修复「失败被误报为成功」的
  退出码与错误提示缺位；端点 overlay 复用与注册双重缺陷。

## [v0.18.0] - 2026-09

build 101。

### 变更

- **管理台**：统一三面板客户端口径，修复幽灵客户端与 MCP/skills 误报；彻底删除客户端
  （注册条目 + 残留配置 + skills 链接）；补全修复/清理能力。
- **Skills**：嵌套子技能展示描述 + 技能级操作（备份/导出/重命名/删除）。
- **MCP**：旧通道清理改为纯删除，统一列表与卡片页口径。
- **配置**：客户端删除改本机停用，恢复主干注册表三客户端；移除未安装客户端注册条目。

## [v0.16.1] - 2026-09

build 96。

### 变更

- **GUI**：设置页分区重构、IDE/Agent 双视图与 MCP 端点功能；主页 IDE/Agent 面板重构。
- **MCP**：端点测试连接、认证 Token 与 stdio 本地命令支持。
- **注册表**：分类重构为 AI IDE / IDE Plugin / AI Agent 三类并补齐 MCP 写入。
- **路径**：修正 Trae / Windsurf / DeepSeek Harness 默认路径为标准路径。

## 早期里程碑（v0.x 之前）

以下为阶段一至阶段五过程中的关键能力落地：

> **命名迁移（P-10）**：项目自历史名 `skills-mcp-unifier` 更名并迁移为
> `skill-mcp-studio`（仓库 `github.com/oswaldhill/skill-mcp-studio`）。代码内 CLI
> `--help`、MCP `clientInfo.name`、报告头均使用新名；旧名仅作为符号链接别名目录
> （`skills-unifier`/`skills-mcp-unifier`）与历史文档中的演进记录保留。

### 阶段五 · 通用管理台重塑

- 五页信息架构（概览 · IDE/Agent · Skills · MCP · 设置）与视觉重构。
- rebuild `.app`（Tauri P4/P5）、客户端添加与统一目录写命令（P7）、端点库 CRUD 与 MCP
  清单命令（P3）、按客户端挂载过滤端点（P2）、管理快照重建。
- 阶段五管理台完整评审 + 整改报告。

### 阶段一~四 · 核心能力

- **endpoint profile 抽象**：端点库 CRUD、每客户端多挂载、逐端点活体探活。
- **CLI 通用化**：`--all-profiles` 跨 profile 汇总、退出码约定、能力组模板库。
- **Tauri 图形层**：macOS 桌面 `.app` 壳，`run_audit` / `run_cli` 双命令桥接。
- **按需加载与启停（L5）**：每「客户端 × 技能」三态启停矩阵、漂移审计、回滚幂等。
- **打包**：pipx/pip 可安装发行、产品 README。

### 仍未发布：合入 `master` 前的累积记录

### 变更

- **分支合并（2026-09-21）**：`master` 原为 `develop` 的**祖先**（两条线并非分叉），
  `develop` 比它多 4 个提交（`8dc646e` 注册表 / `517ed72` 六维度整改 / `137006e` 文档
  同步 / `d7795f7` 测试污染修复）。以 `--no-ff` 将 `develop` 合入 `master`
  （`807b80d`），合并后两分支 **tree 哈希一致**（`4d0ac637`），全量测试 `515 passed`。
- **本机构建与安装**：合并后重新 `cargo tauri build`（`0.21.0` build 106，28.7s，
  `BUILD_EXIT=0`），安装到 `/Applications/skill-mcp-studio.app`，产物与安装后二进制
  sha256 一致（`e253763e…`）；旧版备份至
  `~/.skill-mcp-studio-backups/skill-mcp-studio-0.21.0-premerge.app`。步骤与权限、
  TCC 授权失效须知见 `src-tauri/BUILD.md` §3.2；**DSH 本体更新**（ad-hoc 签名、
  无 TeamIdentifier，cdhash 变更即失效）导致授权丢失的完整判据与根治手段见 §3.3。
- **安装数变化**：`8dc646e` 使「空壳 CLI 启动器」不再被计为安装证据，管理台
  `IDE / Agent` 计数由 **7 → 6**（预期行为修正，非回归）。

### 跨平台支持（Windows / Linux）

- **CLI 路径矩阵**：`core/mainstream_registry.py` 引入 `by_os` + `sys.platform` 分派
  （决策 A），为全部内置 IDE/Agent 补充 Windows（`%APPDATA%`/`%USERPROFILE%`/
  `%LOCALAPPDATA%`）与 Linux（XDG `~/.config`）路径，依据
  `docs/design/跨平台路径矩阵-Windows-Linux.md`；
- **路径展开**：`core/tool_registry.py` 新增 `expand_path()`，统一展开 `%VAR%` 与
  `~`，`detect_installation` 兼容注入的 `expanduser`（既有测试契约不变）；
- **python3 解析**：`core/ai_memory_checker.py` 移除硬编码 `/usr/local/bin/python3`，
  改为 `sys.executable` → `shutil.which("python3")` → `"python3"` 的跨平台解析；
- **模板目录**：`capability_templates._default_user_dir()` 平台感知（Windows 走
  `%APPDATA%\skill-mcp-studio`，POSIX 走 `~/.config/skill-mcp-studio`）；
- **Rust 壳**：`lib.rs::cli_candidates()` 三平台适配（Windows 补 `.exe` 与
  `%USERPROFILE%\.local\bin`、`%APPDATA%\Python\Scripts`；Linux 补 `/usr/bin`）；
- **CI 构建**：新增 `.github/workflows/build-windows.yml`（NSIS + MSI）与
  `build-linux.yml`（deb + rpm + AppImage），产物以 workflow artifact 形式产出，
  暂不发布 GitHub Releases（遵循「仅 codeup」门禁）。

### 工程化 / 开源准备

- **CI/CD（GitHub Actions）**：新增 `.github/workflows/build-macos.yml`，macOS
  universal 二进制（`universal-apple-darwin`，Tauri 自动 `lipo` 合并 `x86_64` +
  `arm64`），单一 `.app`/`.dmg` 原生覆盖 Intel 与 Apple Silicon；
- **签名与公证（可选）**：配置 Apple 证书 secrets 时自动导入证书并启用正式签名 +
  公证，未配置时回退 ad-hoc 签名（构建不中断）；
- **自动发布**：push `v*` tag 时用 `softprops/action-gh-release` 自动创建 GitHub
  Release（自动生成 release notes），上传 `.dmg` 与 `.app.zip`；
- **双远端与分支保护**：`origin` 接管 codeup + github 双 pushurl（`git push origin
  master` 一次推两处）；github `master` 设 PR-only 保护（需审批、禁 force push）；
- **开源仓库**：公开仓库 `github.com/oswaldhill/skill-mcp-studio`，清理历史敏感信息
  （真实端点域名/IP/密钥在 HEAD 中全部占位符化）。

### 文档

- 根目录产品/设计/决策/评审文档归档至 `docs/` 分层目录；
- 新增 `CONTRIBUTING.md` / `SECURITY.md` / `CHANGELOG.md` 与 `.github/` Issue/PR 模板；
- README 增加 badges、仓库结构树、文档索引与管理台 UI 截图；
- README「开发」章节补充 CI/发布说明与 Apple 签名 secrets 配置表。

[Unreleased]: https://github.com/oswaldhill/skill-mcp-studio/compare/v0.21.1...HEAD
[v0.21.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.21.1
[v0.21.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.21.0
[v0.20.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.20.1
[v0.20.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.20.0
[v0.19.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.19.0
[v0.18.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.18.0
[v0.16.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.16.1