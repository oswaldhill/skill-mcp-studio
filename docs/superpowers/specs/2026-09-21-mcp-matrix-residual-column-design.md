# MCP 覆盖矩阵：最后一列不再重复「已挂载」

- 日期：2026-09-21 ｜ 分支：develop ｜ HEAD 5be00a1
- 文件：`gui/dashboard.html`、`tests/test_dashboard_mcp_ui.py`

## 问题

合并成「客户端 × 端点」矩阵后同一事实被表达三遍：端点列已逐列给出挂载状态；
「挂载」列给出 `N / M`；最后一列又把每个已挂载条目列一遍 `xxx · 已挂载`，
`xxx` 就是表头里已有的端点名。第三项纯冗余，且让行宽随端点数量线性增长。
该列还按 `inventory` 原始顺序渲染，行间次序会抖动。

## 什么算「端点列表达不了」

据 `core/mcp_inventory.py`：

- `attached`：挂在端点库已登记端点上，必带 `endpoint_key`（见 :35），
  表头必有它的列 —— 已表达，删除。
- `legacy` / `unmanaged`：端点列无法表达 —— 保留。
- `attached` + `high_risk`：疑似客户端自带，端点列只说得出「已挂载」，
  说不出「谁塞进来的」—— 保留。

## 方案

1. 过滤：丢弃「`attached` 且端点已在表头」的条目；若 `endpoint_key` 不在表头
   （数据不一致）仍保留，避免静默丢失。
2. 稳定排序：`旧通道 -> 未纳管 -> 其他`，同组按条目名排序。
3. 过滤后为空沿用既有 `无` 文案。
4. 「挂载」列的 `N / M` 改为按钮，点击打开既有「已挂载端点」详情面板
   （`showMcpClass(name, "attached")`）—— 明细移走后仍可达，且不加宽行。

## 刻意不动

`core/mcp_inventory.py`、快照结构、`scan.py` 输出不变（GUI/CLI 结论须一致），
改动只在渲染层；计数与三态（`N / M`、`不支持`、`无端点`）、异常行标识不变。

## 验证

`ResidualEntryColumnTest` 6 条断言（node 执行 `renderMcpClients` 后断言 HTML）：
不重复、顺序稳定、风险条目保留、表头外端点不丢、`N / M` 可点、异常行可点。
另更新两条既有断言末列期望 `s1 · 已挂载` / `g · 已挂载` → `无`（行为变更）。

结果：护栏 32 项全绿；全量 pytest 576 passed / 28 subtests；
`verify_gui_consistency.sh` 输出 `OK: GUI/CLI 审计结论完全一致`。
