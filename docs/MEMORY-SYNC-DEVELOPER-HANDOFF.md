# 给开发 Agent：原生 MCP 记忆同步的现状与开发责任

核对时间：2026-11-06。用户本轮要求检查配置并交接开发要求，不要求本 Agent 补写自动同步功能。本轮没有修改客户端/服务端配置，没有启用定时任务、Hook、桥接或队列处理。

## 1. 已有能力与缺口

skill-mcp-studio 已有的是原生 MCP **接入与身份治理**，不是自动记忆采集器：检查安装/配置、预览应用、私有备份、冲突回滚、双真实对话验收。专用身份验收 Skill 明确禁止写记忆和项目事件。

当前 Codex 根据任务规则主动通过原生 Hermes MCP 调用 ai_memory_query、ai_memory_handoff_begin 和 memory_add。PuddingHomeLan 的 hermes-continuity Skill 另要求重要进展调用 note_write，实际提交后调用 commit_capture 并回读。这是 Agent 的执行规则，不是可靠的后台触发器，不能保证每次提交或定时必达。

## 2. 实际配置核对

| 对象 | 当前形式 | 结论与边界 |
|---|---|---|
| 当前 Codex | `~/.codex/config.toml` 的 `hermes` 原生 HTTPS MCP；凭据采用环境变量引用 | 环境注入由现有钥匙串 LaunchAgent 提供；它是凭据注入，不是记忆采集 Hook，不输出凭据 |
| WorkBuddy | `~/.workbuddy/mcp.json` 的 `WorkBuddy` 原生 HTTPS 连接，指向 NAS 统一 MCP | Authorization 已配置且非占位符，原生 clientInfo.name=WorkBuddy；不调用外部程序代连 |
| WorkBuddy 生命周期 Hook | `~/.workbuddy/settings.json` 未配置 Hook 事件 | 不能宣称已有提交/周期记忆触发器 |
| WorkBuddy 身份 Skill | 共享技能目录存在 `sms-workbuddy-native-identity` | 只读验收用；用原生 Skill 替换 CODEBUDDY_SESSION_ID，不承担记忆写入 |
| WorkBuddy 通用连续性 Skill | 共享技能目录未发现 `hermes-continuity`；Pudding 仓库 `.agents/skills/` 内存在该规则 | 未验证 WorkBuddy 会自动加载仓库规则；不能把“文件存在”当作“执行已生效” |
| Pudding 仓库旧 Codex Hook | `.codex/hooks.json` 无 Hook 事件 | 旧 session_binding/tool_completion 链路已停用 |
| Pudding Git Hook | post-commit、post-rewrite 为停用说明加 exit 0 | 不采集提交、不投递记忆 |
| 本机旧 continuity-worker | LaunchAgent 未加载 | plist 仍保留不是运行证据；禁止恢复 |
| NAS 统一 MCP | `mcp-edge-hermes-unified-mcp-1` 健康运行 | 宿主原生调用的接收入口，不负责凭空推断客户端聊天内容或未上报提交 |
| NAS AI Memory 与相关服务 | ai-memory、hermes、hermes-memory-coordinator-shadow、hermes-memory-delivery、hermes-knowledge-callback 健康 | 进程健康不能替代逐事件送达、提取、归档验收 |

本轮用户明确指定 Hermes 指 **NAS 统一 MCP 服务**。本机 `~/.hermes/config.yaml` 中另有六类 CodeIsland Hook，命令入口为 codeisland-bridge；这是另一套本机客户端集成配置，不是本轮 NAS 服务配置，也没有据此证明它向 AI Memory 写入。没有执行或修改这些 Hook。

NAS 当前用户 crontab 有 host_schedule_fence 管理的周期入口。这证明服务端存在调度框架，不证明它会自动采集 WorkBuddy 的每次提交或当前聊天；本轮未修改/执行调度任务。

## 3. 服务端当前能力与风险

通过原生 MCP 的 `hermes_continuity_direct_status` 只读返回：

```json
{"protocol":"direct-v3","enabled":false,"commit_status_direct":false,"exact_event_read":false,"local_queue_required":false,"coordinator_promotion_claimed":false}
```

**原生 MCP 传输**和 **direct-v3 服务端写入协议**是不同层。原生身份查询成功，不等于 direct-v3 提交写入、精确事件回读已经启用。也不能把此结果泛化为所有记忆工具不可写：本聊天的 handoff/memory_add 已获得独立接收回执。

仓库 `ops/mcp-edge/unified_mcp_server.py` 的 direct 状态由 coordinator read/write 开关及关闭 dual-write 共同决定；当前回执只能确认组合条件未满足，不能推断是哪一个具体开关不同。要求 direct-v3 的写入会在不可用时明确拒绝，不允许默默降级。

本轮对**既有授权 PuddingHomeLan 项目范围**的只读状态：

- knowledge：completed=85，其余 pending/claimed/retry/dead/revoked 均为0。
- archive：completed=8、dead=77，其余 pending/claimed/retry/revoked 均为0。

这是项目聚合快照，不证明本轮某条 handoff 已提取或归档；77 条 dead 是服务端归档记录，**不是本机228条旧 pending**。后续开发需逐事件定位原因，再提出处理方案，本轮没有重试、删除、重新归属或自动修复。

## 4. 交给开发 Agent 的开发任务

### A. 分离两种产品能力

1. 接入/身份治理继续只管理原生配置和身份验收。
2. 另设记忆连续性模块，负责策略、触发、最小摘要、提交、精确回读与状态展示。
3. UI 分别显示：配置存在、认证成功、当前会话已识别、项目授权、任务绑定、记忆已接收、原文已回读、提取状态、归档状态。不能用一个“已同步”覆盖全部阶段。

### B. 先建立可执行的宿主规则

- 提供仓库无关的原生连续性 Skill/宿主规则模板，配置真实的设备/Agent/当前会话来源；不要复制 Pudding 的固定项目 ID 到其他仓库。
- 配置前检查宿主实际支持的加载位置与原生 Skill 加载方式；验收需看到真实工具调用，不能只检查文件存在。
- 任务开始查相关记忆并解析项目/绑定；重要进展写有界 work_state；实际创建 commit 后按精确 SHA 写 checkpoint；任务结束保存交接。
- 对 unbound/未授权任务明确阻断任务级提交，不创建假 task_id，不借用旧聊天任务。不应因身份验收返回合法 unbound 就宣称任务级写入已就绪。
- “规则已安装”和“运行时强制触发”必须是不同状态。宿主只能支持 Agent 自觉执行时，标记 agent_rules，不承诺可靠自动同步。

### C. 提交与周期触发

- 每次提交仅在 Agent 确认实际 commit 成功、取得完整 SHA 后触发原生 MCP checkpoint；不得为了验收自动 commit/push。
- 周期检查点应定义触发间隔、最小有效变化、去抖合并、活跃/空闲和会话结束行为；无变化不制造重复事件。
- 要承诺可靠自动触发，必须提供目标宿主**当前版本确实支持**的原生运行时/调度能力证据。缺少支持则标记 unsupported/manual/agent_rules，不能另起外部 MCP 客户端冒充原生调用。
- 不用 Git post-commit/post-rewrite、旧 session/tool Hook、stdio bridge、旧 worker 或 outbox。不得把它们改名后作为“新原生适配器”重新引入。
- 不启动新的周期任务或扩张自动写入范围，直到策略与项目/任务边界明确并经过用户选择。

### D. 原生写入契约

- 原生调用 note_write/commit_capture；具体参数按公开工具 schema，区分 commit_capture 的 session_id 与绑定工具的 native_session_id。
- 请求/元数据携带真实 Agent、当前原生会话、远端项目、仓库规范键/指纹、任务与 binding_revision；传输 session 不能充当聊天 ID。
- 提交事件使用稳定 `git-<full-sha>`；检查点使用稳定事件身份及内容哈希。超时先精确对账，再决定是否同 ID 重试；不能换 ID 重复提交。
- 只发送有界中文摘要、必要文件路径/变更统计与来源关联；不自动上传完整聊天、源码、diff、环境变量或凭据。
- 独立报告 accepted、readback_verified、extraction、archive 状态；保留 event_id/note_id/revision/content_hash 以便审计。
- 若选用 direct-v3，先检查服务端能力；当前未启用时停止并报告，不能省略协议参数绕过。服务端启用/提升需单独审查发布与回滚，不在配置检查时自动翻开关。
- 不新增或自动消费本机旧队列；失败/未知显示具体状态。可靠重试机制如有新设计，必须另行说明持久化责任、去重和用户授权，不能偷用旧 pending。

### E. 服务端开发与运维责任

- 核对 direct-v3 的实际组合开关、映射与绑定前提；提供清晰的受阻原因和可审查迁移计划，不只返回一个 false。
- 明确 handoff/memory_add 与任务级 note/commit 的存储、提取、归档路径；不同回执不可混用。
- 排查项目 archive 的77条 dead：逐项来源、任务、内容哈希、失败阶段和错误类型；先对账再提出重试策略，保留原始证据。
- 服务端只对已接收事件进行提取、归档和投递；它无法仅凭一个设备 key 自动读取另一客户端未上报的当前对话。
- 不直接修改上游 AI Memory 源码。若需适配，遵守 Pudding 的补丁链/升级机制及 ACR 发布纪律。

## 5. 必须完成的验收

- 两个真实宿主、各两个真实对话：同设备但 Agent 可区分、同 Agent 的会话不同，写入元数据与真实当前对话一致，不串任务。
- 身份只读验收与记忆写入验收分开；写入测试须选定授权测试项目与任务。不得把目前四条 unbound 身份测试聊天自动绑上任务。
- 一次真实重要进展、一次用户授权的实际 commit、一次符合策略的周期检查点，以及无变化时不重复写入。
- 对照原生工具历史和远端精确回执，检查原文哈希、提交 SHA、事件 ID、绑定修订及提取/归档状态；不采用 Agent 最终回答充当证据。
- 测试鉴权失败、绑定变化、开关禁用、超时未知、同 ID 重试、重复触发、跨会话并发；保证不降级到旧链路。
- 旧 outbox 最终记录总数与逐记录安全元数据哈希必须与基线一致：总362，pending228、acked134；不能仅以 grep 无命中断言未改动。

## 6. 交付物及本轮边界

开发 Agent 应交付宿主支持矩阵、策略 schema、配置计划与回滚、原生写入/对账模块、服务端状态说明、真实验收报告及失败处理说明。

本轮只创建这份开发说明并发布共享交接；没有实现自动同步，没有修改 NAS/WorkBuddy 配置，没有重放旧队列，也没有向不相关开发聊天派发任务。
