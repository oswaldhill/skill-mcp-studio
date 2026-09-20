# 详细设计文档 · 阶段五增量 · MCP 条目删除与清理

- 日期：2026-09-20
- 状态：设计已评审（待实施）
- 前置：`docs/design/详细设计文档-阶段五-通用管理台重塑.md`（该文档定义 MCP 条目三分类）

## 1. 背景与问题

阶段五把管理台的 MCP 面板做成「每客户端 MCP 条目分类」视图（已挂载 / 旧通道 /
未纳管），但**只有旧通道可清**，其余是只读的：

| 现状 | 位置 |
| --- | --- |
| `--remove-legacy-mcp` 是唯一删除路径，且只按 legacy 名单批量删 | `core/mcp_fixer.py:748` |
| 未纳管条目**刻意只读**，UI 明确写「不提供删除」 | `gui/dashboard.html:3360-3362` |
| 覆盖矩阵纯只读，没有取消挂载的 GUI 入口 | `gui/dashboard.html:2623` |

本机实测暴露了这种只读设计的实际代价——「未纳管」里混着三类性质完全不同的东西：

| 客户端 | key | 地址 | 性质 |
| --- | --- | --- | --- |
| Codex | `node_repl` | `/Applications/ChatGPT.app/.../cua_node/bin/node_repl` | 客户端自带 |
| Codex | `computer-use` | `./Codex Computer Use.app/.../SkyComputerUseClient` | 客户端自带 |
| DeepSeek Harness | `image-vision` | `/usr/local/bin/python3` | 用户自建（视觉工具依赖） |
| WorkBuddy | `context7` | `npx` | 用户自建（第三方） |
| WorkBuddy / Reasonix | `my-mcp` | `https://example.internal/mcp` | 测试残留 |

前两行删了会弄坏 Codex 的 computer-use 能力，后三行恰恰是用户最想清理的对象——
**当前 UI 把这两类一视同仁地锁死**。本增量要提供删除与清理能力，并把「疑似客户端
自带」与「普通条目」区分对待。

## 2. 需求结论（评审已确认）

1. **覆盖范围**：三类全覆盖——`attached` / `legacy` / `unmanaged` 均可删。
2. **防误删强度**：分两级——命中「疑似客户端自带」的条目走强化确认，普通条目常规确认。
3. **回滚能力**：完整回滚——列出配置的历史备份并可一键还原。

## 3. 语义与安全模型

### 3.1 三类条目「删除」的确切含义

| 类别 | 单条删 | 按类批量清 | 附加动作 |
| --- | --- | --- | --- |
| `unmanaged` | ✅ | ✅（默认跳过高风险） | 无 |
| `legacy` | ✅ | ✅（等价现有 `--remove-legacy-mcp`） | 无 |
| `attached` | ✅ | ✅ | **同步从挂载声明摘除该端点** |

`attached` 必须同步改声明，否则该客户端的 `mcp_attach` 仍声明挂载，
`--fix-mcp` 会在下一次把它装回来，状态自相矛盾。

**关键映射陷阱**：声明用端点 **key**，配置文件里用的是端点 **name**，两者不同。
本机实测：`mcp_attach=['K8s-uat','hermes-home']`，而配置里的条目 key 是 `hermes`
（端点库中 `key=hermes-home`、`name=hermes`）。因此删除 `attached` 条目时必须
**通过 inventory 条目的 `endpoint_key` 字段回映**到声明 key，不能拿配置 key 直接改声明。

**缺省语义**：客户端没有显式 `mcp_attach` 时，语义是「挂载端点库里**全部**端点」
（`core/endpoint_library.py:9,45`）。此时删除必须先**物化显式列表**
（全部端点 − 被删项）再写入，否则下次扫描仍认为它挂载全部。

**空声明的陷阱（本次不修，但必须拦住）**：`resolve_client_attach` 用 `if attach:`
判断，**空列表与「未声明」不可区分**，两者都回落到「挂载全部端点」。因此「把某客户端
的挂载声明清空」在本项目现有语义下**无法表达「一个都不挂载」**——写入空列表只会让它
回到「挂载全部」。故：**若删除集合含 `attached` 条目、且删除后该客户端的显式声明将变
为空，则整个操作拒绝**，并提示改用端点库 / 客户端管理。`unmanaged` / `legacy` 的删除
不受此限（不影响声明），可以删到一条不剩。

### 3.5 已知语义边界（建议后续单独立项）

`core/endpoint_library.py` 以 `if attach:` / `bool(tool.get("mcp_attach"))` 判定
「是否显式声明」（`resolve_client_attach`、`has_explicit_attach`、`attach_map` 三处），
把「未声明」与「声明为空」混为一谈。若要支持「显式不挂载任何端点」，需改为
`attach is not None` 判定——这会**改变既有检查模型语义**（配置中若已存在空列表，行为
将由「全部」变为「无」），影响 `has_explicit_attach` 闸门与覆盖矩阵取值，故不在本增量
范围内，建议单独立项评估。

### 3.2 高风险分级（防误删）

判定规则（实现于 core，确定性、可单测）：

| 规则 | 内容 |
| --- | --- |
| **R1** | 条目的 `command` / `args` 中绝对路径落在该客户端注册表的 `app_bundles` 任一前缀下 |
| **R2** | 路径含 `.app/Contents/`（覆盖 Codex 的相对路径 `./Codex Computer Use.app/...`） |
| **R3** | 条目 key 归一化后等于客户端名或其 alias |

命中即 `high_risk=true` 并给出 `risk_reason`（人话，如「命令位于
/Applications/ChatGPT.app 内」）。

R1 之所以成立，是因为注册表已有该数据：Codex 的 `app_bundles` 含
`/Applications/ChatGPT.app`（`config.yaml:111`），正好覆盖它那两个自带条目。

**交互分级**：

- 普通条目：常规确认弹窗（列出 key、地址、目标配置文件路径）→ 删除。
- 高风险条目：**红色强确认，必须手动输入 key 名**才解锁删除按钮；CLI 侧对应要求
  `--force-high-risk`，否则拒绝执行。
- 批量清理：**默认跳过**高风险条目，需显式勾选「包含疑似客户端自带」才纳入。

### 3.3 写入安全链

完全复用现有范式，**不新增任何写盘路径**：

```
解析配置 → 备份 <config>.bak-<时间戳> → 移除条目 → 重新序列化
        → 再次解析校验 → 原子写（同目录临时文件 + rename，保留原权限位）
        → 返回 {status, message, backup, path}
```

解析失败一律不动原文件并报错。

### 3.4 拒绝条件与边界

| 情形 | 结果 |
| --- | --- |
| 客户端未安装 / 配置文件缺失 | `missing`，不做改动 |
| `fix_supported: false` | `unsupported`，拒绝 |
| 指定 key 在配置中不存在 | `unchanged`，**不误报成功** |
| 删除集合含 `attached` 且删除后显式声明将为空 | `refused`，拒绝并说明「空声明 == 挂载全部」的语义（见 §3.1） |
| 删除后一条不剩（不含 `attached`） | 允许（用户有权清空），结果里提示可「从备份恢复」 |

## 4. 实现方案

**选定方案：泛化现有 legacy 删除链路。**

理由：`_render_without_legacy` 本质就是「按任意 key 集合删」，与 legacy 无关，只是
命名如此；json / jsonc / yaml / toml / reasonix / reasonix_toml / cordis_yaml 六种
格式已全部覆盖。泛化等于「改名 + 放宽 key 集合」，比重写便宜且安全；而删除的正确性
高度依赖既有安全链与六种格式渲染，重复实现会带来长期漂移。

- `_render_without_legacy(tool, text, keys)` → 泛化为 `_render_without_entries(...)`，
  legacy 调用点传 legacy 名单。
- `remove_legacy_mcp_tool(...)` → 泛化为 `remove_mcp_entries_tool(tool, keys, ...)`；
  保留 `remove_legacy_mcp_*` 作为薄包装，**旧 CLI 参数行为与输出逐字不变**。

被否决的方案：新建独立 `mcp_entry_editor.py`（六种格式需重实现或跨模块调私有函数，
漂移风险高）；一步做到「增/改/删 + 矩阵勾选」（范围约 2–3 倍，且「手动条目 vs 端点库」
语义需额外定案）。

## 5. CLI 接口

新增 4 个参数，全部支持 `--dry-run`：

| 参数 | 作用 | 约束 |
| --- | --- | --- |
| `--remove-mcp-entry KEY[,KEY...] --client NAME` | 精确删指定条目 | 命中高风险需 `--force-high-risk` |
| `--remove-mcp-class attached\|legacy\|unmanaged --client NAME` | 按类批量清 | 默认跳过高风险，需 `--include-high-risk`；`attached` 受 §3.1 空声明限制 |
| `--list-config-backups --client NAME` | 只读列该客户端配置的历史备份 | 无副作用 |
| `--restore-config-backup PATH --client NAME` | 还原到指定备份 | PATH 必须属于该客户端 |

新命令统一支持 `--format json`，返回：

```json
{
  "status": "updated|unchanged|missing|unsupported|refused|error|dry-run",
  "message": "人话结果",
  "path": "被改写的配置文件",
  "backup": "备份文件路径",
  "removed": ["被移除的 key"],
  "skipped_high_risk": ["因高风险被跳过的 key"],
  "attach_updated": ["声明中同步摘除的端点 key"]
}
```

**动机**：现有「清理旧 MCP」的结果判定是对 stdout 做字符串匹配
（`gui/dashboard.html:4406`，`out.includes("旧通道条目已移除")`），很脆；新命令改为
结构化输出，前端不再匹配字符串。旧参数保持字符串输出不变。

## 6. 回滚

- 备份沿用现有约定 `<config_path>.bak-<时间戳>`（`core/mcp_fixer.py:579-581`）；
  列表按时间倒序，含大小与时间。
- **还原是整文件覆盖，不只是 MCP 段**：备份是配置文件副本，还原会连带回退该文件的
  **全部后续改动**（例如之后调过的其他设置）。此点必须出现在强确认文案中。
- 还原自身也走安全链：校验 PATH 属于该客户端 → 用该格式解析备份内容（失败即拒）
  → 先把当前文件另存为新备份 → 原子写 → 校验。

## 7. 快照与 UI

### 7.1 快照扩展

`management_snapshot` 的 `mcp.clients[].inventory[]` 每条补两个字段：
`high_risk: bool`、`risk_reason: str`。其余结构不动（`endpoint_key` 已有，
`config_path` 在 client 级已有），以保证 GUI 结论 == CLI 结论的一致性 gate 不被破坏。

### 7.2 UI 改动（完全复用现有形态，不新造视觉）

1. **MCP 页第三列**（条目分类列）：标签由 `<span>` 改为可点击按钮（与 IDE 页现状
   一致），点击打开条目分类详情。
2. **条目分类详情弹窗** `showMcpClass`：每条右侧加「删除」（普通常规确认 / 高风险
   红色强确认）；顶部加「清理全部未纳管 / 全部旧通道 / 全部已挂载」+ 勾选框
   「包含疑似客户端自带（N 个）」；底部加「从备份恢复」。**改写现有那句「未纳管条目
   仅展示，不提供删除」**。
3. **客户端详情弹窗** `showAgentDetail`：条目行同样加删除；cleanbar 从只清旧通道
   扩展为旧通道 / 未纳管均可清。
4. 新增 `confirmTypedKeyModal()`：复用 `confirmModal` 样式类，输入与 key 名完全一致
   才启用确认按钮。
5. 执行走现有 `runTaskModal`（进度 → 结果），结果解析改用 JSON。

## 8. 测试与验收

- 新增 `tests/test_mcp_entry_removal.py`：
  - 六种格式各删一条（含 `cordis_yaml` / `reasonix_toml`）；
  - 不存在的 key → `unchanged`；解析失败 → 原文件不变；
  - 备份文件确实生成且内容 == 原文件；
  - 高风险 R1 / R2 / R3 各一例，外加普通条目不误判的反例；
  - `attached` 删除后声明被正确摘除（验证 `hermes` ↔ `hermes-home` 映射）；
  - 无显式 `mcp_attach` 的客户端 → 物化显式列表；
  - **声明将变空时拒绝**（`refused`），且原配置文件与 overlay 均未被改动；
  - 还原前生成新备份；非本客户端的备份被拒。
- 回归：`--remove-legacy-mcp` 旧行为与输出逐字不变。
- 一致性：`scripts/verify_gui_consistency.sh`。
- 真机验收：
  - 删 WorkBuddy 的 `my-mcp`（测试残留）应成功，且可一键还原；
  - 删 Codex 的 `node_repl` 应被高危拦截，必须输入 key 名。

## 9. 明确不做（out of scope）

- 不做条目的新增 / 修改（属方案三范畴）；
- 不做覆盖矩阵勾选挂载（挂载仍归端点库；本次仅 `attached` 删除会顺带改声明）；
- 不做「禁用 / 注释掉条目」（只做删除）；
- 不做跨客户端批量（GUI 一次一个客户端；CLI 保持 `--remove-legacy-mcp` 无 `--client`
  时的原有全部客户端行为）。