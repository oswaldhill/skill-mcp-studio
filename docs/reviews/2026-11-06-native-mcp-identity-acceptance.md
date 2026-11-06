# 原生 MCP 身份治理实现与双对话验收

2026-11-06，skill-mcp-studio。

## 结果

WorkBuddy 与 DeepSeek Harness 均已通过两个真实对话的原生 MCP 验收。Studio 从宿主原始工具历史回读远端 RPC 回执，并再次核验后判定通过；未使用模型摘要代替证据，也未由 Studio 代连 MCP。

| 宿主 | 应用版本 | 远端 clientInfo | 对话 A | 对话 B |
|---|---|---|---|---|
| WorkBuddy | 5.9.3 | WorkBuddy / 1.0.0 | `142f0f84-4369-48ad-8264-34f345377602` | `7a4b5817-8159-435e-8e54-cc9e81b46d94` |
| DeepSeek Harness | 0.2.2-rc.1 | DeepSeek Harness / 0.0.1 | `session-95320dc1-aed7-4184-8202-b77f567399eb` | `session-27e40315-4ad6-4cf1-b11c-61e6cbab2f4f` |

四条对话均为同一 registered MacBook Pro；两个 Agent 的原生名称不同，每个 Agent 内两个原生对话 ID 不同。绑定查询显式传入各自当前 ID；全部为 `unbound / binding_revision=0`，没有新建、重新绑定或更新任务。

验收使用既有授权的 PuddingHomeLan 作为只读测试目标。skill-mcp-studio 自身的远端仓库身份尚未匹配，本轮未自动注册或借用其他项目任务记录实现工作。

## 实现交付

- 版本限定的宿主适配器：安装证据、原生配置、Agent 名称、凭据策略、信任与重载边界。
- 只读检查 → 计划哈希 → 私有备份 → 原子应用 → 读回校验 → 冲突保护回滚。
- GUI 与 CLI 共享服务；专用 MCP 面板支持预览、应用、回滚、历史验收恢复、两个会话的源证据读取和比较。
- 通用修复入口对已注册原生适配器停止覆盖，避免重复连接、错误 env 占位 Header 和 Cordis insert 被展平。
- 当前客户端原生连接已合规，本次实际 apply 仅安装/更新两个独立身份 Skill，配置字节与应用原件保持不变；没有自动重启。

## 真实失败与复验

WorkBuddy A 首次拆分 `repository_key` 并遗漏 `|.`，远端返回 400；证据采集器拒绝签收该轮，返回 `native_rpc_error_or_invalid_result`。随后明确要求完整原样传参，并在**同一真实对话**重新加载原生 Skill、重新执行三项只读检查，每项一次成功。最终采集器核验该新的 challenge 轮次，旧失败历史保留。Skill 与生成指令已补充完整参数要求，没有放宽证据判据。

## 检查

- 全量 Python：1,609 项，2 项既有条件跳过；原生相关测试集合 34 项通过。
- `CI_BASELINE_SKIPPED=2 scripts/ci_parity.sh` 全部通过：ruff、卫生与密钥检查、6 项 Node helper、12 项 Rust、全量 Python 和空用户目录检查。
- 使用 2 的环境基线原因：本机实际安装 DeepSeek，使原先基线里因无 DSH 配置而跳过的用例得到执行；不是增加跳过项或降低判据。
- 既有 `test_merged_config_still_has_endpoints` 原先依赖个人覆盖层，在空用户目录必失败；现改为显式临时覆盖层夹具，不改变产品端点数据。
- GUI/CLI 一致性 gate 使用隔离的离线配置夹具通过；真实设备身份验收由上述原生宿主完成。GUI renderer 实际执行并检查转义，设计规范契约通过，前端分发资源已同步。
- 本轮没有重建或安装桌面 App 安装包；源码及 CLI 已可使用，既有打包流程下次构建会包含面板与 Rust 命令白名单。
- DeepSeek App ASAR SHA-256 保持 `f21d83abfb33d463822a52c439cc9b15c8245dbce4ae4cf9424c90eae8eba94f`。

## 旧队列保持原状

只读核对全部 362 条记录：acked 134，pending 228。逐记录安全元数据（不含 lease token）哈希与先前对账报告一致：

`552250dd5a08fe2d02c8c98d5fb06d71a4f1c04fd5ca78031d61e38ce793ea2a`

未重放、删除、重新绑定或启动队列处理程序；没有恢复 Hook 或桥接。

## 判定范围

通过范围为 `explicit_session_tool_argument`：设备认证、原生 Agent 名称及当前会话参数链路。**不主张**通用 MCP 每次调用都自动携带对话 ID，不主张 clientInfo 是独立密码学认证，不把 unbound 解释为历史上从未绑定。

可复核的最小回执、真实 callId、参数、结果哈希与两个 run ID 见 [脱敏证据 JSON](2026-11-06-native-mcp-identity-evidence.json)。原始聊天历史和含原配置的私有备份留在本机，不提交仓库。实现说明见 [能力契约](../NATIVE-MCP-IDENTITY.md)。未自动 commit/push。
