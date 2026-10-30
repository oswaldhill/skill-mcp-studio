# 文档索引

本文件是 `docs/` 下**全部 Markdown 文档**的索引：共 **37** 个 `.md`（本索引 1 个 + 文档 **36** 篇）。
每一条都是可点击的相对链接，并标注该文档的**状态**——不是所有文档都还代表现状。

> **一句话准则**：能据此判断「现在应该是什么样」的只有标了 **当前有效** 的那几份；
> 其余是历史留档，只回答「当时为什么这么定」。

## 单一事实源（先看这里，别在文档里找版本号）

**判断现状只认下面这 6 处**（其中两处是代码/配置文件，不在本目录）。索引里标「当前有效」的其余几篇
是战略与取证文档，它们自身的口径也让位给这 6 处；标「历史归档」「已被取代」的只用来查来龙去脉。

| 想知道什么 | 唯一事实源 | 口径说明 |
| --- | --- | --- |
| 当前版本号 / 构建号 | 仓库根 `version.json` 的 `version` / `build` 字段 | 文档一律不内嵌版本快照，避免随发版漂移；变更历史见 `CHANGELOG.md`。（重建本索引时读到 0.31.4 / build 131，以文件当前值为准） |
| 某条需求到底实现了没有 | `docs/product/prd_impl_matrix.json` | PRD ↔ 实现的**单一数据源**；Markdown 清单由它派生，`tests/test_prd_impl_matrix.py` 逐条核对证据（CLI 参数、代码符号、GUI 选择器），文档虚标或代码改名都会让门禁报红。（重建本索引时 80 条，之后会随需求增删变化） |
| 产品应该是什么样 | `docs/product/PRD-产品需求文档.md`（v1.7，八页管理台） | 产品层唯一权威；纪律是「实现落地的那一版就要回写」，未回写视为未交付 |
| 界面应该长什么样 | `docs/DESIGN.md` | `gui/dashboard.html` 的唯一设计依据，由 `tests/test_design_spec.py`、`tests/test_dashboard_design_tokens.py`、`tests/test_design_spec_contract.py` 强制校验 |
| 决策为什么这么定 | `docs/decisions/决策记录-待决问题定案.md` | ADR 合集（D1–D22），含后续实机反馈定案 |
| 各平台默认路径是什么 | `core/mainstream_registry.py` 的注册表 | 文档里的路径矩阵只是取证底座与快照，条目数以注册表返回值为准 |

## 状态三分

| 状态 | 含义 | 怎么用 |
| --- | --- | --- |
| **当前有效** | 描述当前产品、当前实现或当前界面规范 | 可以据此判断现状，可以据此写代码与测试 |
| **历史归档** | 描述某个已交付版本、某一轮评审、某次交接或某个已落地方案的**当时形态** | 只能查「当时为什么这么定」，**不能拿它校验当前实现** |
| **已被取代** | 结论已被更可靠的单一事实源取代 | 保留仅作历史；要看现状请读取代它的那一份 |

**推荐阅读顺序**：产品层（`product/`）→ 实现层（`design/`）→ 决策层（`decisions/`）→
过程记录（`reviews/`、`superpowers/`）→ 取证（`research/`）。

---

## 一、`docs/` 顶层（3 篇）

界面规范、最新一轮版本评审、以及托盘/后台巡检的原始方案。

| 文档 | 状态 | 一句话说明 |
| --- | --- | --- |
| [`DESIGN.md`](DESIGN.md) | 当前有效 | 管理台界面规范：design read、token 体系、组件规约、状态覆盖与检查清单，是 `gui/dashboard.html` 的唯一设计依据，改界面必须先按它找组件、找不到再补并且补回本文件 |
| [`REVIEW-v0.31.0.md`](REVIEW-v0.31.0.md) | 历史归档 | 2026-10-23 对 v0.30.0（build 126）之后 43 个提交的版本评审清单，P0 阻塞 4 项与 P2 缺陷 6 项已全部修复并随 v0.31.0（build 127）发布，文末附逐项验收记录 |
| [`方案-托盘常驻与Hook管理.md`](方案-托盘常驻与Hook管理.md) | 历史归档 | 托盘常驻、后台巡检、变更通知、Hook 管理四块的新功能方案（含架构、分五阶段实现路径、风险与待确认决策点）；主体已落地为 `src-tauri/src/lib.rs` 的 tray、popover、通知与巡检，仅「开机自启」未做，§9 的待确认问题已被实现结果取代 |

## 二、`docs/product/` 产品层（4 篇）

回答「做什么、为什么」。这一组的 4 篇都仍在使用，但**只有 PRD 与实现对照清单是产品口径的权威**。

| 文档 | 状态 | 一句话说明 |
| --- | --- | --- |
| [`PRD-产品需求文档.md`](product/PRD-产品需求文档.md) | 当前有效 | 产品层单一权威 PRD（v1.7）：八页管理台的能力、口径、缺口看板，外加 §12 的深入评审记录（9 处「实现先行、PRD 未回写」的纠正过程）与「落地即回写」纪律 |
| [`PRD-实现对照清单.md`](product/PRD-实现对照清单.md) | 当前有效 | 由 `prd_impl_matrix.json` 派生的逐条 PRD↔实现对照表，每条「证据」都由门禁自动核验，因此不会出现「文档写了但代码没有」或代码改名后静默过期 |
| [`产品定位与路线图规划.md`](product/产品定位与路线图规划.md) | 当前有效 | 定位、差异化、阶段路线图的战略文档（v1.4），但页面口径仍停在「七页」，与 PRD v1.7 的八页不一致——战略结论可用，页面/能力口径以 PRD 为准 |
| [`产品形态与开发计划.md`](product/产品形态与开发计划.md) | 当前有效 | 总纲：形态阶梯 L1–L3、分阶段可执行开发计划与文档体系图（附录 A/C），同样需按 PRD v1.7 勘正页面口径后再引用 |

## 三、`docs/design/` 实现层（7 篇）

回答「怎么做」，主体是阶段一~五的历史设计文档；**当前实现形态只有跨平台路径矩阵这一篇还在用作事实底座**。

| 文档 | 状态 | 一句话说明 |
| --- | --- | --- |
| [`详细设计文档-阶段一-endpoint-profile-抽象.md`](design/详细设计文档-阶段一-endpoint-profile-抽象.md) | 历史归档 | 阶段一「endpoint profile 抽象」的详细设计：配置 schema、模块职责、接口签名、关键流程、兼容性策略与测试方案，并约定阶段二/三的数据契约 |
| [`详细设计文档-阶段二-CLI-通用化.md`](design/详细设计文档-阶段二-CLI-通用化.md) | 历史归档 | 阶段二「把内部工具变成陌生人可用的产品」：能力组模板库、跨 profile 汇总报告、独立打包分发、stdio 传输活体探测四条主线，附退出码约定与技术债清理 |
| [`详细设计文档-阶段三-Tauri-图形层.md`](design/详细设计文档-阶段三-Tauri-图形层.md) | 历史归档 | 阶段三 Tauri 图形层与路径处理设计；文首已自标「GUI 只读是硬边界」这一结论自阶段五起失效，其余抽象与阶段内决策依据仍可参考 |
| [`详细设计文档-阶段四-按需加载与启停.md`](design/详细设计文档-阶段四-按需加载与启停.md) | 历史归档 | 阶段四按需加载与启停的设计；同样自标「GUI 只读」结论失效，逐技能启停已于 v0.20.0 交付，启停矩阵与形态迁移后续也已落地 |
| [`详细设计文档-阶段五-通用管理台重塑.md`](design/详细设计文档-阶段五-通用管理台重塑.md) | 历史归档 | 产品转向的定案记录：从「只读审计看板」改为可写通用管理台（三栏 + 端点库 + 每客户端多端点挂载 + GUI 写操作），含转向目标与用户确认的决策；三栏形态已被 PRD §5.3 的八页取代 |
| [`详细设计文档-阶段五增量-MCP条目删除与清理.md`](design/详细设计文档-阶段五增量-MCP条目删除与清理.md) | 历史归档 | 2026-09-20 的增量设计，状态「已实施」：把 MCP 面板从「只有旧通道可清」扩到任意客户端条目的删除/清理，含疑似客户端自带条目的强化确认与基于配置备份的一键回滚 |
| [`跨平台路径矩阵-Windows-Linux.md`](design/跨平台路径矩阵-Windows-Linux.md) | 当前有效 | 15 个国际客户端 + 7 个国产客户端在 Windows/Linux 的真实默认路径，逐条标 verified / best-effort、查无权威来源就留空；它是三平台 `by_os` 分派的事实底座，但条目数是 v0.2 快照，现状以 `core/mainstream_registry.py` 为准 |

## 四、`docs/decisions/` 决策层（2 篇）

回答「为何如此定」。ADR 仍在增补，立项评估已完成使命。

| 文档 | 状态 | 一句话说明 |
| --- | --- | --- |
| [`决策记录-待决问题定案.md`](decisions/决策记录-待决问题定案.md) | 当前有效 | ADR 合集：D1–D22 的定案（许可证、公开策略、profile 分发、多 MCP 语义，以及后续如 D22「按钮都没用」的作用域嵌套盲区与哨兵定案），并附需回填原文档的联动修订清单 |
| [`立项评估-阶段四-按需加载与启停.md`](decisions/立项评估-阶段四-按需加载与启停.md) | 历史归档 | 阶段四立项评估：按「需求确认 / 形态选择 / 安全对齐 / 边界复核」四维度评估，结论为立项通过，并把差异化方向定为启停一致性审计、禁用生效验证与回滚幂等；后续设计见阶段四详细设计文档 |

## 五、`docs/reviews/` 过程记录（7 篇）

各轮评审与核对。**基本都只记录某个时点的发现，不代表现状**；其中一篇已明确标注「已被取代」，
其余按「历史归档」处理。

| 文档 | 状态 | 一句话说明 |
| --- | --- | --- |
| [`评审整改问题清单-2026-09-04.md`](reviews/评审整改问题清单-2026-09-04.md) | 历史归档 | 8 视角并行智能体评审（对照 ui-ux-pro-max、web-design-guidelines、python-code-style、TDD、Diátaxis）对照阶段一~四设计文档产出的 45 条问题：13 major、26 minor、6 info，去重后约 8 个顶层问题 |
| [`评审整改报告-阶段五管理台.md`](reviews/评审整改报告-阶段五管理台.md) | 历史归档 | 阶段五三栏管理台的四角度并行评审（架构、UI-UX、数据契约、功能覆盖）加截图核验：31 条问题（3 blocker、9 high），当前功能覆盖度约 50%，阻断项为合规语义 BUG、一键合并只 dry-run、个人拓扑被写进版本控制 |
| [`评审报告-GUI二轮-结构与交互优化.md`](reviews/评审报告-GUI二轮-结构与交互优化.md) | 历史归档 | GUI 结构与交互的二轮评审裁定：配色不整体照搬参照项目（保留 zinc 骨架、强调色回归自有 Brand Blue），并把交互密度补齐到命令面板、右侧详情抽屉、toast、分段筛选、空态 CTA 等 |
| [`评审报告-v0.20.0-六维度深度评审.md`](reviews/评审报告-v0.20.0-六维度深度评审.md) | 历史归档 | 对 v0.20.0（build 104，基线 `821dbf1`）的多智能体并行六维度评审：产品设计、架构、代码质量、测试、UI/UX、构建与多平台 |
| [`评审-v0.23.0-整改与优化清单.md`](reviews/评审-v0.23.0-整改与优化清单.md) | 历史归档 | 以 v0.23.0（build 109）为基线的 P0/P1/P2 整改清单，也是下一版本需求池；含 ruff 是否强制执行等批次决策与实测结论，文末附「v0.23.0 已修」避免重复立项 |
| [`评审-v0.24.0-待完善清单.md`](reviews/评审-v0.24.0-待完善清单.md) | 历史归档 | 第十三轮评审：CI/CD、工具脚本、版本一致性、依赖治理与仓库卫生，Q0/Q1/Q2 分级并逐条复核证据；正文有修复进度表（含反向验证记录），条目均已 ✅ |
| [`需求完成度核对-2026-10-21.md`](reviews/需求完成度核对-2026-10-21.md) | 已被取代 | 2026-10-21 对 develop `9c48cfb`（v0.29.2 / build 125）的完成度核对，结论为「PRD 需求与缺口看板已全部完成、剩余 20 项 v0.30+ 增强」；该结论已被 `docs/product/prd_impl_matrix.json`（配合派生的 PRD-实现对照清单）取代，保留仅作历史 |

## 六、`docs/superpowers/` 交接（2 篇）

跨设备续作用的时点快照，前一份的细节仍被后一份引用。

| 文档 | 状态 | 一句话说明 |
| --- | --- | --- |
| [`HANDOFF-v0.29.0.md`](superpowers/HANDOFF-v0.29.0.md) | 历史归档 | 2026-10-16 的交接文档：v0.29.0「Hook 写入可配置 + ai-memory 剥离」的版本与代码状态、环境要求、续作清单；v0.29.x 的 Hook 与 ai-memory 细节仍以它为准 |
| [`HANDOFF-v0.31.0.md`](superpowers/HANDOFF-v0.31.0.md) | 历史归档 | 2026-10-23 的交接文档：v0.31.0（build 127，1295 tests OK）「技能版本管理 + 市场源 + 升级链路」的状态、环境要求与续作清单，明确以它为 v0.31.x 续作入口 |

## 七、`docs/superpowers/plans/` 实施计划（2 篇）

逐任务 checkbox 的实施计划，**两篇文首均已自标「历史存档」**：文中所有 `pytest` 命令已过时，项目现统一为标准库 unittest（`scripts/ci_parity.sh` 是等价入口）。

| 文档 | 状态 | 一句话说明 |
| --- | --- | --- |
| [`2026-09-20-mcp-entry-removal.md`](superpowers/plans/2026-09-20-mcp-entry-removal.md) | 历史归档 | 「MCP 条目删除与清理」的实施计划：让管理台能删除/清理任意客户端的 MCP 条目（含未纳管），对疑似客户端自带条目做强化确认，并提供基于配置备份的一键回滚；对应增量设计已实施 |
| [`2026-09-23-skill-market-integration.md`](superpowers/plans/2026-09-23-skill-market-integration.md) | 历史归档 | 「技能市场接入 + 版本更新检测 + 在线升级」的实施计划：只读的搜索/已装清单/更新检测，加经用户确认的在线安装与升级，GUI 以逐技能进度展示 |

## 八、`docs/superpowers/specs/` 功能设计（8 篇）

单个功能的实现设计（不是产品方案）。**全部已落地或已批准并随版本交付**，因此统一归档；
要判断这些功能现在的行为，请回到 PRD 与实现对照清单。

| 文档 | 状态 | 一句话说明 |
| --- | --- | --- |
| [`2026-09-21-mcp-matrix-residual-column-design.md`](superpowers/specs/2026-09-21-mcp-matrix-residual-column-design.md) | 历史归档 | MCP 覆盖矩阵最后一列的冗余治理：同一事实被表达三遍、行宽随端点数量线性增长、按 inventory 原序渲染导致行间抖动，定案为删掉重复列 |
| [`2026-09-23-skill-market-integration-design.md`](superpowers/specs/2026-09-23-skill-market-integration-design.md) | 历史归档 | 技能市场接入设计：在 GUI 搜索并安装市场技能、检查已装技能上游更新、在线升级到最新版；新增 `core/skill_market.py` 并接进 `scan.py` 与 `dashboard.html` |
| [`2026-09-23-skill-merge-advice-design.md`](superpowers/specs/2026-09-23-skill-merge-advice-design.md) | 历史归档 | 技能整理建议（FEAT-11）设计：区分「同一目标的双重存在该归并」与「看着像其实是有意变体不该动」，产出可执行合并组、上游标注组、被否决变体对三份可核验清单；已实现为 `core/skill_merge_advisor.py` + `--merge-advice`，执行能力另由 `core/skill_merge_exec.py` 落地 |
| [`2026-09-23-skill-usage-statistics-design.md`](superpowers/specs/2026-09-23-skill-usage-statistics-design.md) | 历史归档 | 技能使用统计（FEAT-10）设计：目录 mtime 与 `.skill-lock.json` 只能说明「装过/改过」而非「被调用过」，因此改从会话日志取证；已实现为 `core/skill_usage.py` + `--skill-usage` + GUI 的 `usage-panel` |
| [`2026-10-15-auto-discover-active-profile-gui-design.md`](superpowers/specs/2026-10-15-auto-discover-active-profile-gui-design.md) | 历史归档 | 设置页「自动发现 / 活动端点」可写化设计：补 `--set-auto-discover` 与 `--set-active-profile` 两条后端写命令，把 UI 上的「即将支持」变成可操作；定位是 PRD §10 当时的唯一未实现项 |
| [`2026-10-16-hook-write-configurable-design.md`](superpowers/specs/2026-10-16-hook-write-configurable-design.md) | 历史归档 | v0.29.0 核心改动的设计（修订至 v3）：Hook 写入可配置 + 全面剥离 ai-memory，含 Hook 与 MCP 的完整能力清单、耦合点、剥离后边界，以及四维评审补齐的 5 个阻断项与 6 条改进建议 |
| [`2026-10-21-config-porter-and-hook-interpolation-design.md`](superpowers/specs/2026-10-21-config-porter-and-hook-interpolation-design.md) | 历史归档 | 两件事的设计（状态：已实施，D1/D2/D3/E/F/H 七步全落地）：补 v0.29.0 遗留的 Hook 命令变量插值，以及配置导入/导出（v0.30.0 #3 本地 + iCloud）；实施中还修了 auto_discover overlay 断链与引号加固 |
| [`2026-10-22-skill-version-and-market-sources-design.md`](superpowers/specs/2026-10-22-skill-version-and-market-sources-design.md) | 历史归档 | 技能版本管理 + 市场源可配置的设计（状态：用户 2026-10-22 已批准），定案 QwenWork / 企业 MCP 不是市场源、skills.sh 为默认源且可删改；已随 v0.31.0 交付（更新检查后续扩到五态） |

## 九、`docs/research/` 取证（1 篇）

Hook 事件能力表的调研取证索引，用于回答「为什么 `config.yaml` 里是这些事件」。

| 文档 | 状态 | 一句话说明 |
| --- | --- | --- |
| [`README.md`](research/README.md) | 当前有效 | 三份 `hook-capability-*.json` 的来源与可信度分级索引（official / local / rebuilt 三档，其中 Cursor/TRAE 那份是重建件、可信度低于原始取证），并说明 `config.yaml` 的 `hooks.events` 47 项规范词表是它们的并集，改事件表须同步本目录 |

---

## 附一、本目录下的非 Markdown 资产

这些不是文档正文，但常被正文引用，一并登记便于定位（本表刻意不给链接，避免与上面的文档条目混淆）：

| 文件 | 用途 |
| --- | --- |
| `docs/DESIGN.html` | `DESIGN.md` 的自包含可读版，含字号/按钮/控件/圆角/语义色可视化样例，浏览器直接打开 |
| `docs/方案介绍.html` | 产品方案的自包含 HTML 介绍页 |
| `docs/images/dashboard.png` | 仓库根 README 引用的管理台截图 |
| `docs/product/prd_impl_matrix.json` | PRD ↔ 实现矩阵的**单一数据源**（重建时 80 条），Markdown 清单与门禁断言都由它派生 |
| `docs/research/hook-capability-*.json` | Hook 事件能力的三份原始/重建取证（Claude+WorkBuddy、Codex+OpenCode、Cursor+TRAE 重建件） |
| `docs/reviews/review-*.json` 与 `docs/reviews/评审报告-阶段五管理台.json` | 阶段五评审四个角度（架构 / UI-UX / 数据契约 / 功能覆盖）的智能体原始输出 |

## 附二、本目录之外的仓库文档

只登记路径与用途，不在此文件里链接（避免索引职责外溢）：

| 路径 | 用途 |
| --- | --- |
| `README.md` | 仓库入口：安装、快速开始、命令速查、架构总览 |
| `SKILL.md` | 本仓库作为 Agent Skill 的元数据与使用说明 |
| `CONTRIBUTING.md` | 贡献指南 |
| `CHANGELOG.md` | 变更日志（版本历史的另一半真相，与 `version.json` 配套） |
| `SECURITY.md` | 安全漏洞报告政策 |
| `LICENSE` | MIT 许可 |
| `references/ide-agent-setup.md` | IDE / Agent 接入说明 |
| `src-tauri/BUILD.md` | Tauri 桌面壳构建说明 |
| `skill-mcp-studio-architecture.svg` | 正式架构图（暗色主题、内联 SVG、离线可用） |

## 附三、维护约定

1. **新增或改名任何 `.md`，必须同步本索引**，并给它标状态与一句话说明（说明从内容里读，不看文件名猜）。
2. 状态判定口径：描述当前行为的进「当前有效」；描述某个已交付版本 / 某轮评审 / 某次交接的进「历史归档」；
   结论被更强的单一事实源接管时改标「已被取代」，**但不删除原文件**——历史留档本身有价值。
3. **本文件只负责指路，不复制结论**：版本号去 `version.json` 查，需求状态去 `prd_impl_matrix.json` 查。
   凡是不得不写的数量或版本（如「重建时 80 条」），一律标注时点，读到时先回源核对——这正是旧索引烂掉的原因：
   它把当时的快照当成了永久事实。
4. 自查（约定：每行最多一个链接，因此按行数统计即等于链接数）：

```bash
# 在仓库根执行；链接数应等于 docs 下 md 总数减 1（本索引自身）
grep -c '\]\(' docs/README.md
find docs -name '*.md' | wc -l
```

5. 改了 `gui/dashboard.html` 或新增界面，先看 `DESIGN.md`（本文件第一节的表格里有跳转），跑完三个设计门禁再提交。
