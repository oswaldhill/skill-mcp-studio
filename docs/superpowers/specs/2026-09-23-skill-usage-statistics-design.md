# 技能使用统计设计（FEAT-10）

日期：2026-09-23　状态：已实现
关联：`docs/superpowers/specs/2026-09-23-skill-market-integration-design.md`（FEAT-9）
代码：`core/skill_usage.py`、`scan.py --skill-usage`、`gui/dashboard.html` 的 `usage-panel`

## 1. 要解决的问题

「整理 skill」的前提是知道**哪些技能真的在用**。目录 mtime 与 `.skill-lock.json`
只能说明"装过/改过"，不能说明"被调用过"。本功能回答三个问题：

1. 每个技能最近一次被使用是什么时候？
2. 哪些技能装了但从没用过（清理候选）？
3. 哪些技能在同一个动作上重叠（后续合并的判断依据）？

约束（用户定）：**最简单的无侵入方式**——只读客户端已有的落盘日志，
不装 hook、不改任何客户端配置、不写盘。

## 2. 数据源调研：采纳与否决

| 候选信号 | 结论 | 理由 |
| --- | --- | --- |
| 文件 atime | **否决** | 实测 122/186 个技能的 atime≈mtime，说明挂载/同步时被批量 touch 过，不反映读取 |
| 目录 mtime | **否决** | 只反映"被改写过"，与"被使用"无关 |
| 按技能名 grep 日志 | **否决（关键）** | 每个 Codex 会话都会把**全量技能清单**注入 developer message（`world_state.state.host_skills.body`），直接 grep 名字 → 每个技能在每个会话里都"命中"，100% 误报 |
| `function_call_output` 里的路径 | **否决** | 工具返回内容会回显别家技能的 `SKILL.md` 路径，同样不是使用证据 |
| **`function_call` / `custom_tool_call` 参数里的技能路径** | **采纳** | 这是模型真正发起的一次读/写动作，是唯一可靠通路 |
| Claude / Cursor / Hermes 会话日志 | **暂缓** | 目录存在但格式不稳定；留 `source` 字段扩展，不并入本轮 |

采纳的目录：`~/.codex/archived_sessions`（930 个 `.jsonl`）与
`~/.codex/sessions`（**按日期嵌套** `sessions/YYYY/MM/DD/`，递归收集得 1438 个，
比归档目录还多 500+ 个，且含当天最新会话）。只扫顶层会漏掉全部活跃会话。

## 3. 日志结构（实测）

```
每行一个 JSON：{ timestamp, ordinal, type, payload }
type ∈ { response_item, event_msg, session_meta, compacted }
工具调用只在 type == "response_item" 的 payload 里：
  payload.type ∈ { function_call, function_call_output, message, reasoning,
                   custom_tool_call, custom_tool_call_output, web_search_call, ... }
  function_call    : { type, name, arguments, call_id }        # arguments 是 JSON 字符串
  custom_tool_call : { type, status, call_id, name, input }    # input 是原始文本
timestamp 为 UTC ISO 8601（2026-05-09T05:19:27.508Z），字典序即时间序。
带技能路径的工具：exec_command / exec / apply_patch / request_permissions / spawn_agent。
```

## 4. 两个解析坑（都实际踩过）

1. **`arguments` 是二次编码的 JSON 字符串**，路径里的 `/` 可能被写成 `\/`。
   匹配前统一 `text.replace("\\/", "/")`，否则多数行静默落空。
2. **尾斜杠不等于深入目录**。`ls .../skills/hermes/` 只引用目录，是浏览；
   `cat .../skills/hermes/SKILL.md` 才触达具体文件。早期用 `(\/)?` 前瞻把前者
   误判成 load（被自己的测试 `test_directory_listing_only_counts_as_browse` 抓到）。
   现用两条正则：`skills/<name>/` 后**必须还有非空路径段**才算 deep。

另外 `json.loads` 可能返回 `null`/标量，必须先 `isinstance(rec, dict)` 再取键。

## 5. 动作分档

| 档 | 判据 | 含义 |
| --- | --- | --- |
| `load` | 触达 `<skill>/` 下具体文件；或 `spawn_agent` 以 `type=skill` 显式派发；或 `request_permissions` 点名读 `SKILL.md` | **在用**的强信号 |
| `browse` | 仅目录级引用（典型 `ls`） | 浏览/探查，弱信号 |
| `edit` | `apply_patch`/`write`/`edit` 改写技能文件 | 维护动作，**不计入使用**，但提示该技能正被人工调整 |

`--usage-since <ISO_DATE>` 按动作时间戳过滤窗口（无时间戳的记录在限定窗口时不计入）。

## 6. 本机实测结果

全时段（2368 个会话文件、4786 次技能相关工具调用、约 32 秒）：

- 已装 202 个技能
- 被真正加载过：**74 个**
- 仅浏览/改写、从未加载：1 个
- **零触达：127 个** ← 清理与合并的首要目标集

高频前列：`test-driven-development`(634)、`taste-skill`(415)、
`systematic-debugging`(401)、`hermes`(379)、`git-commit`(269)、
`codebase-inspection`(215)。近 30 天窗口下 63 个技能被加载，排名稳定，
说明热点集中在开发流程类与飞书类技能。

## 7. 顺带发现的缺陷

`toggleMarketPanel()` 引用了从未声明的 `MARKET_DATA`，`node --check` 与全部单测
都是绿的，但用户第一次点「技能市场」就抛 `ReferenceError`，面板永远空白。
已补声明与写入，并加**静态守卫** `UndeclaredStateRefTest`：剥离字符串/注释后
扫描「全大写对象被引用却无声明」的差集，另配植入样本的守卫自检防止守卫空转。

## 8. 局限与下一步

- 只覆盖 Codex 一个客户端。DSH/Claude/Cursor 侧尚未接入，`source` 字段是扩展点。
- `load` 统计的是"技能被读取"的次数，不等于"任务因此变好"；用于排序与筛僵尸够用，
  做效果评估不够。
- 下一步（FEAT-10 → FEAT-11）：以 127 个零触达 + 同族命名（`grafana-*`、`lark-*`、
  `sensteed-*-review`、`wecomcli-*`、`firecrawl-*`）为输入，产出**合并/归组建议清单**，
  仍走只读预览 + 二次确认，不自动删改。
