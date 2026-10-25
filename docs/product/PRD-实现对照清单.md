# PRD ↔ 实现 对照清单

> 生成口径：本清单由 `docs/product/prd_impl_matrix.json` 派生，**每条「证据」都由
> `tests/test_prd_impl_matrix.py` 自动核对**——CLI 参数必须在 `scan.py` 里真实存在、
> 代码符号必须在指定文件里出现、GUI 选择器必须在 `dashboard.html` 里出现。
> 因此这份清单不会因为「文档写了但代码没有」而失真，也不会因为代码改名而悄悄过期
> （门禁会红）。
>
> 对照的 PRD 版本：**v1.6**（2026-10-25）。PRD 本身见
> [`PRD-产品需求文档.md`](./PRD-产品需求文档.md)。

## 1. 总览

| 项 | 数量 |
|---|---|
| 对照条目 | **73** |
| ✅ 已实现 | **60** |
| 🟡 部分实现 | **1** |
| ⬜ 未实现（已立需求） | **8** |
| 🚫 刻意不做 | **4** |

结论先讲：**主干能力全部落地**。缺口集中在两处——
① **§6.2.1「技能关闭」整条需求未实现**（8 条子需求，占全部未实现项 100%）；
② **跨平台只做到「能构建」，没做到「真机可用」**（缺口 #6）。
另有 1 项部分实现：Win/Linux 冒烟。4 项刻意不做是产品边界，不是欠债。

## 2. 状态口径

| 标记 | 含义 | 判定标准 |
|---|---|---|
| ✅ 已实现 | 能力可用，有非文档证据 | 证据（CLI flag / 代码符号 / GUI 选择器）全部核验通过 |
| 🟡 部分实现 | 主体可用，但有明确未闭合面 | 在 note 里写明**具体缺什么**，不得只写「部分」 |
| ⬜ 未实现（已立需求） | 尚未开发，但需求已进 PRD | 必须有对应的 PRD 章节与 §8 缺口看板条目 |
| 🚫 刻意不做 | 产品边界 | 依据 PRD §8，附判据 |

> **纪律**：本表不允许出现「看起来做了但其实没做」。每条 ✅ 的证据都是可机器
> 核验的；只有文档口径、无代码可验的条目（如边界条款）必须标 `doc` 证据并在
> note 说明原因。

## 3. 逐条对照

| ID | PRD | 能力 | 类型 | 状态 | 证据 | 备注 |
|---|---|---|---|---|---|---|
| 6.1-01 | §6.1 | 列出本机所有客户端（声明 + 自动发现 + 手动三来源归一去重） | 读 | ✅ 已实现 | `--management`；`core/management_snapshot.py` → `def build` | 本机实测发现 23 个客户端 |
| 6.1-02 | §6.1 | 展示安装证据（app bundle / CLI 命令 / 配置路径） | 读 | ✅ 已实现 | `core/tool_registry.py` → `def detect_installation`；GUI `ad-pill` | — |
| 6.1-03 | §6.1 | 展示 Skills 路径合规 + 链接形态（per_skill / root / mixed / n/a） | 读 | ✅ 已实现 | `core/skill_state.py` → `def skill_link_form`；`gui/dashboard.html` → `linkFormText` | 四态；n/a 表示该客户端无 skills 语义 |
| 6.1-04 | §6.1 | 展示 MCP 挂载端点（显式 / 自动全部） | 读 | ✅ 已实现 | `core/management_snapshot.py` → `mcp_attach` | — |
| 6.1-05 | §6.1 | 查看客户端完整详情（含配置解析出的 MCP 条目） | 读 | ✅ 已实现 | GUI `showAgentDetail` | 右侧 Sheet |
| 6.1-06 | §6.1 | 纳入 / 移出客户端（主流工具勾选 + 自定义添加） | 写 | ✅ 已实现 | `--add-client`；`--remove-client`；`--add-defaults` | — |
| 6.1-07 | §6.1 | 重新扫描（含自动发现） | 写（触发生成） | ✅ 已实现 | `--discover` | — |
| 6.2-01 | §6.2 | 展示统一技能目录、技能总数 | 读 | ✅ 已实现 | `core/management_snapshot.py` → `unified_dir` | 本机实测 192 个技能 |
| 6.2-02 | §6.2 | 搜索 / 筛选技能清单（全部 / 已启用 / 部分 / 未启用 / 可升级） | 读 | ✅ 已实现 | GUI `data-seg="partial"`；GUI `data-seg="updatable"` | 五段筛选 |
| 6.2-03 | §6.2 | 网格 / 列表视图切换（记忆于 localStorage） | 读 | ✅ 已实现 | GUI `localStorage` | — |
| 6.2-04 | §6.2 | 查看单技能详情（描述 + 每客户端启用状态） | 读 | ✅ 已实现 | GUI `showSkillDetail` | — |
| 6.2-05 | §6.2 | 每客户端技能启停（ToggleSwitch） | 写 | ✅ 已实现 | `--enable-skill`；`--disable-skill` | 仅 per_skill 形态可用；root 形态返回 skip（缺口 #7） |
| 6.2-06 | §6.2 | 一键合并（dry-run 预览 → 确认实写） | 写 | ✅ 已实现 | `--fix-skills` | — |
| 6.2-07 | §6.2 | 技能清单展示版本（本地 SKILL.md frontmatter version） | 读 | ✅ 已实现 | `core/skill_state.py` → `def read_skill_meta` | 无版本时回落最后更新时间 |
| 6.2-08 | §6.2 | 更新检查（五态：有更新 / 最新 / 未知 / 登记失效 / 仓库待同步） | 读 | ✅ 已实现 | `--market`；`core/skill_market.py` → `repo_outdated` | 本机实测 total=192（skill 39 + repo 153） |
| 6.2-09 | §6.2 | 市场源管理（默认 skills.sh，可删改，支持自定义远端源） | 写（通用） | ✅ 已实现 | `--set-market-source`；`--remove-market-source`；`--list-market-sources` | — |
| 6.2-10 | §6.2 | 设置统一技能目录 | 写（通用） | ✅ 已实现 | `--set-unified-dir` | — |
| 6.2-11 | §6.2 | 市场搜索 / 安装 / 升级已装技能 | 写（业务） | ✅ 已实现 | `--market-install`；`--market-upgrade`；`--market-query` | 安装/升级来自第三方仓库，必须 --yes 显式确认 |
| 6.2-12 | §6.2 | 技能使用统计（使用画像：load/browse/edit/last_used/never_used） | 读 | ✅ 已实现 | `--skill-insight`；`core/skill_usage.py` → `never_used` | 本机实测已装 193 / 用过 22 / never_used 171；依赖会话日志完整性（缺口 #8） |
| 6.2-13 | §6.2 | 备份与回滚（升级前自动备份） | 写（业务） | ✅ 已实现 | `--list-skill-backups`；`--skill-rollback` | data/skill_backups/<name>/<时间戳>/；回滚前另存 .before-restore-<时间戳> |
| 6.2-14 | §6.2 | 启停矩阵与形态迁移（list / audit / migrate） | 读 + 写 | ✅ 已实现 | `--list-skill-states`；`--audit-skill-states`；`--migrate-skill-links` | 本机 6 客户端 × 192 技能；root → per_skill 迁移为原子替换 + 校验 + 失败还原 |
| 6.2-15 | §6.2 | 跨设备配置同步（WebDAV） | 写（通用） | ✅ 已实现 | `--sync-webdav-push`；`--sync-webdav-pull`；`--webdav-status` | 只同步 3 个个人配置文件，不同步 token 与技能本体；冲突不自动合并，先留档 |
| 6.2-16 | §6.2 | GitHub token 通道（提升检查配额 60 → 5000 次/小时） | 写（通用） | ✅ 已实现 | `--set-github-token`；`--get-github-token` | 环境变量优先、文件回落；文件 gitignored |
| 6.2.1-R1 | §6.2.1 | 长期未使用检测（从未使用 / N 天未使用分开呈现） | 读 | ⬜ 未实现（已立需求） | 复用 --skill-insight 的 never_used 与 last_used | 数据已具备，缺「按阈值筛选并分开报数」的界面 |
| 6.2.1-R2 | §6.2.1 | 阈值可配（7/14/30/90 天 + 仅从未使用），阈值必须显示在文案里 | 读 | ⬜ 未实现（已立需求） | 默认 14 天 | 取值 7/14/30/90 天 + 仅从未使用；需与 R1 同批落地，否则阈值无意义 |
| 6.2.1-R3 | §6.2.1 | 候选清单 + 勾选（默认全选、可逐项取消、显示最后使用与 N/M） | 读 | ⬜ 未实现（已立需求） | 复用技能页分段筛选 + N/M 徽标 | 默认全选、允许逐项取消；每行显示最后使用日期与 N/M 徽标 |
| 6.2.1-R4 | §6.2.1 | 批量关闭（逐技能逐客户端执行、部分成功如实回报） | 写（业务） | ⬜ 未实现（已立需求） | 复用 --disable-skill；不新增写路径 | 受缺口 #7（root 形态）阻塞 |
| 6.2.1-R5 | §6.2.1 | 关闭前预览与代价说明（关闭≠删除，技能本体保留） | 读 | ⬜ 未实现（已立需求） | 关闭只移除符号链接 | 文案必须含「关闭≠删除、技能本体保留」，避免用户以为是删除 |
| 6.2.1-R6 | §6.2.1 | 提醒节流（不再提醒，状态落 overlay 不写 config.yaml） | 写（本地） | ⬜ 未实现（已立需求） | data/local_overrides.yaml 同层 | 不改 config.yaml；与现有 overlay 写层同模式，重启后保持 |
| 6.2.1-R7 | §6.2.1 | 入口与触发时机（技能页入口；启动不弹窗打断） | 读 | ⬜ 未实现（已立需求） | 仅技能页提示条 | 启动不弹窗打断，只在技能页给可关闭的提示条 |
| 6.2.1-R8 | §6.2.1 | 与 MCP 的边界（不得合并成一个数字） | 边界 | ⬜ 未实现（已立需求） | MCP 清理走 MCP 页既有分类 | 由门禁断言守住：技能与 MCP 各自计数，不得合并成一个数字 |
| 6.3-01 | §6.3 | 端点库（key / name / url / transport / 探活 / 能力组） | 读 | ✅ 已实现 | `core/management_snapshot.py` → `endpoints` | — |
| 6.3-02 | §6.3 | 每客户端 MCP 条目分类（已挂载 / 旧通道 / 未纳管） | 读 | ✅ 已实现 | GUI `CLASS_TRANSLATE` | — |
| 6.3-03 | §6.3 | 端点 × 客户端覆盖矩阵 | 读 | ✅ 已实现 | GUI `data-page="mcp"` | — |
| 6.3-04 | §6.3 | 端点库增 / 删 / 改 | 写（通用） | ✅ 已实现 | `--add-endpoint`；`--remove-endpoint`；`--update-endpoint` | — |
| 6.3-05 | §6.3 | 客户端挂载端点调整 | 写（业务） | ✅ 已实现 | `--attach-endpoints` | — |
| 6.3-06 | §6.3（补） | 端点活体探测（initialize + tools/list，HTTP 与 stdio） | 读 | ✅ 已实现 | `--endpoint-status`；`core/transport.py` → `def probe_stdio` | PRD §6.3 原表未列，本次补入 |
| 6.4-01 | §6.4 | 统一技能目录（可改） | 写 | ✅ 已实现 | `--set-unified-dir` | — |
| 6.4-02 | §6.4 | Hook 命令模板（按事件编辑 + 预设） | 写 | ✅ 已实现 | `--set-hook-template`；`--apply-hook-preset`；`--list-hook-templates` | — |
| 6.4-03 | §6.4 | 自动发现开关（写 overlay） | 写 | ✅ 已实现 | `--set-auto-discover` | 与 §6.4 的 P-3 定案一致；重定向参数 --profile/--config 仍被 Rust 拒 |
| 6.4-04 | §6.4 | 活动 endpoint（active_profile）切换 | 写 | ✅ 已实现 | `--set-active-profile` | 注意 --active-profile（无 set-）是被 Rust 拒绝的重定向参数，两者不同 |
| 6.4-05 | §6.4 | 配置导入 / 导出（换机 / 分享） | 写 | ✅ 已实现 | `--export-config`；`--import-config` | 单 JSON、密钥脱敏、合并导入、导入前自动备份 |
| 6.4-06 | §6.4 | 跨设备配置同步（WebDAV） | 写 | ✅ 已实现 | `--sync-webdav-push` | 同 6.2-15，此处为设置页入口 |
| 6.4-07 | §6.4 | GitHub token（提升检查配额） | 写 | ✅ 已实现 | `--set-github-token` | 同 6.2-16，此处为设置页入口 |
| 6.4-08 | §6.4 | 版本 / 构建号 | 读 | ✅ 已实现 | `--version` | version.json 单源真相 |
| 6.5-01 | §6.5 | 主题（浅色 / 深色 / 跟随系统） | 读 | ✅ 已实现 | GUI `prefers-color-scheme`；GUI `data-theme` | — |
| 6.5-02 | §6.5 | ⌘K 命令面板（分组 + 过滤 + 键盘导航） | 读 | ✅ 已实现 | GUI `palette` | — |
| 6.5-03 | §6.5 | 右侧详情 Sheet（技能 / 客户端） | 读 | ✅ 已实现 | GUI `sheet` | — |
| 6.5-04 | §6.5 | Toast 栈（进度 → 成功 / 失败） | 读 | ✅ 已实现 | GUI `showToast` | — |
| 6.5-05 | §6.5 | 全局 Esc 逐级关闭 | 读 | ✅ 已实现 | GUI `"Escape"` | — |
| 6.5-06 | §6.5 | 可访问性（无 emoji 图标 / focus ring / reduced-motion） | 读 | ✅ 已实现 | GUI `prefers-reduced-motion` | reduced-motion 覆盖动画；aria-hidden 39 处 |
| 6.6-01 | §6.6（补） | Hook 页：事件词表 + 每客户端接入状态 | 读 | ✅ 已实现 | `--list-hooks`；GUI `data-page="hooks"` | PRD §6 原缺 Hook 页需求，本次补入 |
| 6.6-02 | §6.6（补） | Hook 写入 / 移除（带备份） | 写（业务） | ✅ 已实现 | `--fix-hooks`；`--remove-hooks` | — |
| 6.6-03 | §6.6（补） | Hook 漂移检测与关键事件缺失提示 | 读 | ✅ 已实现 | `gui/dashboard.html` → `missing_key_events` | — |
| 6.7-01 | §6.7（补） | 变更详情：快照 diff（4 维度） | 读 | ✅ 已实现 | `--snapshot`；GUI `renderChanges` | PRD §6 原缺变更详情页需求，本次补入 |
| 6.7-02 | §6.7（补） | 变更接受 / 忽略 / 取消忽略（忽略清单幂等） | 写（本地） | ✅ 已实现 | `--ignore-change`；`--unignore-change`；`--list-ignored` | 忽略清单存本地 |
| 6.8-01 | §6.8（补） | 概览：受管客户端 / 已安装 / 仅配置 / 未安装 / 统一技能 / 主流已纳入 六项 KPI | 读 | ✅ 已实现 | GUI `受管客户端`；GUI `主流已纳入` | PRD §6 原缺概览页需求，本次补入；**概览不含 MCP 探活 KPI**（探活已移至独立「端点状态」区，§5.3 已改正） |
| 6.8-02 | §6.8（补） | 概览：端点连通性独立呈现（与配置审计分离） | 读 | ✅ 已实现 | GUI `endpoint-status`；`--endpoint-status` | 审计只判配置，通断独立，避免总览颜色误导 |
| 6.8-03 | §6.8（补） | 概览：快捷操作（添加客户端 / 修复链接 / 全量检查 / 管理端点） | 读 | ✅ 已实现 | GUI `quickbox` | — |
| 7-01 | §7 | 写操作统一「备份 → 原子写 → 校验 → 回滚」 | 非功能 | ✅ 已实现 | `core/file_atomic.py` → `def backup_path`；`core/skill_link_migrator.py` → `os.replace` | symlink 用 os.symlink(tmp)+os.replace，无删除窗口 |
| 7-02 | §7 | 破坏性写命令支持 --dry-run | 非功能 | ✅ 已实现 | `--dry-run` | — |
| 7-03 | §7 | GUI 写命令经 Rust 白名单收口，拒绝重定向参数 | 非功能 | ✅ 已实现 | `src-tauri/src/lib.rs` → `DENIED_FLAG_PREFIXES` | 实测拒绝 --config / --prof / --active-prof / --progress-file |
| 7-04 | §7 | GUI / CLI 审计结论一致（回归 gate） | 非功能 | ✅ 已实现 | `scripts/verify_gui_consistency.sh` → `verify` | — |
| 7-05 | §7 | 无参数 CLI 只读；--full 不隐含 git / cleanup / fix | 非功能 | ✅ 已实现 | `--full`；`scan.py` → `完整只读模式` | — |
| 7-06 | §7 | 离线可用（字体自托管、无 CDN） | 非功能 | ✅ 已实现 | GUI `IBM Plex Mono` | — |
| 7-07 | §7 | 退出码 0 / 1 / 2 语义 | 非功能 | ✅ 已实现 | `tests/test_exit_codes.py` → `returns_2` | 有独立测试文件守着 |
| 7-08 | §7 | 三平台构建（macOS / Windows / Linux） | 非功能 | 🟡 部分实现 | `.github/workflows/build-windows.yml` → `msi`；`.github/workflows/build-linux.yml` → `appimage` | 构建与单测已绿；**未做 Win/Linux 真机 GUI 冒烟**（缺口 #6） |
| 7-09 | §7 | 跨平台路径分派（by_os） | 非功能 | ✅ 已实现 | `core/mainstream_registry_data.py` → `_current_os` | 实测 20 处 windows / 21 处 linux 覆盖 |
| 8-01 | §8 | 不做技能市场 / 商店平台（只做消费方） | 边界 | 🚫 刻意不做 | 自建索引/排行/托管分发不做；--market search/install/upgrade 属消费方 | 判据：成为分发方=不做；仅消费上游=做 |
| 8-02 | §8 | 不做多用户权限体系与云端托管 | 边界 | 🚫 刻意不做 | 本地工具；WebDAV 只搬用户自己的配置文件 | WebDAV 只搬用户自己的配置小层，不搬技能资产与凭据 |
| 8-03 | §8 | 不内置任何特定工具的 Hook 命令 | 边界 | ✅ 已实现 | `--apply-hook-preset`；`--set-hook-template` | v0.29.0 剥离 ai-memory 后确立；用户自定义模板 |
| 8-04 | §8 | 不内置 MCP server 远程入口 | 边界 | 🚫 刻意不做 | unified_mcp_server.py 已删除 | 留待后续专项立项 |
| 8-05 | §8 | 运行时按会话加载（会话级注入） | 边界 | 🚫 刻意不做 | 启停已落地；会话级注入仍未做 | 属增值层，立项时独立决策 |

## 4. 未实现 / 部分实现明细

### 4.1 §6.2.1 技能关闭（8 条，全部未实现）

| ID | 需求 | 依赖 | 阻塞点 |
|---|---|---|---|
| R1 | 长期未使用检测 | 已有 `--skill-insight` 的 `never_used` / `last_used` | 无（可直接做） |
| R2 | 阈值可配 | 同上 | 无 |
| R3 | 候选清单 + 勾选 | 技能页 N/M 徽标 | 无 |
| R4 | 批量关闭 | `--disable-skill` | **缺口 #7：`root` 形态客户端无法逐技能关闭** |
| R5 | 关闭前预览与代价说明 | — | 无 |
| R6 | 提醒节流 | overlay 写层 | 无 |
| R7 | 入口与触发时机 | 技能页 | 无 |
| R8 | 与 MCP 的边界 | MCP 页既有分类 | 无 |

**建议实施顺序**：R1 + R2 + R3（纯只读，不碰写路径）→ R5 + R7（文案与入口）
→ R4 + R6（写与节流）→ R8（边界断言）。R1–R3 落地后即可回答「本机到底有多少个
真该关」，再决定 R4 的形态。

### 4.2 部分实现

| ID | 能力 | 已完成 | 未闭合 |
|---|---|---|---|
| 7-08 | 三平台构建 | 三平台 CI 构建与单测全绿；注册表 `by_os` 已铺 20/21 处平台路径 | **未做 Win/Linux 真机 GUI 冒烟**（缺口 #6）——「能构建」不等于「能用」 |

## 5. 与 PRD 缺口看板的对应关系

| PRD 缺口看板 | 本清单条目 | 状态 |
|---|---|---|
| #5 技能关闭（长期未使用清理） | 6.2.1-R1 ~ R8 | ⬜ 未实现 |
| #6 Windows / Linux 运行时冒烟 | 7-08 | 🟡 部分实现 |
| #7 `root` 形态无法逐技能启停 | 6.2-05 备注、阻塞 6.2.1-R4 | ⬜ 缺引导 |
| #8 使用统计依赖日志完整性 | 6.2-12 备注 | ⬜ 待增强 |

> 本清单**不替代**缺口看板：看板记「产品欠了什么」，本清单记「PRD 的每一条现在
> 是什么状态、证据在哪」。两者以 ID 互相引用。

## 6. 维护规则

1. **改实现 → 同步矩阵**：新增 CLI flag、改代码符号名、改 GUI 选择器后，
   `tests/test_prd_impl_matrix.py` 会因证据找不到而报红，此时必须更新
   `prd_impl_matrix.json` 并重新生成本文件。
2. **改需求 → 先改 PRD，再改矩阵**：矩阵的 `prd` 列必须能对上 PRD 里真实存在的
   章节号（该对应关系也有断言）。
3. **状态只能升不能悄悄降**：把 ✅ 改回 ⬜ 必须同时在 PRD §8 缺口看板登记原因，
   否则视为掩盖回归。
