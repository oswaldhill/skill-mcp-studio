# Hook 能力取证（docs/research/）

本目录保存 **hook 事件能力表**的调研取证，用于回答「为什么 config.yaml 里是这些事件」。

## 文件

| 文件 | 覆盖客户端 | 性质 |
|---|---|---|
| `hook-capability-claude-workbuddy.json` | Claude Code、WorkBuddy | **原始调研输出**（2026-10-12，含官方文档来源与本机实测标注） |
| `hook-capability-codex-opencode.json` | Codex、OpenCode | **原始调研输出**（2026-10-12；Codex 的 12 项与官方源码双向印证） |
| `hook-capability-cursor-trae.rebuilt.json` | Cursor、TRAE | **重建**，见下 |

## 关于「重建」的那一份

Cursor / TRAE 的原始调研输出**只存在于会话消息中，未能落盘找回**。该文件由
`config.yaml` 的既有条目 + 本机实测文件重建，并**逐条标注 `provenance`**：

- `official`：官方文档确认（来自原始调研的转述）
- `local`：本机实测文件确认
- `rebuilt`：由 config.yaml 反推，**未见原始依据**

> 使用时请注意：重建件的可信度**低于**前两份原始取证。若要据此做重大改动，
> 请先复核官方文档。Cursor 的条目形态（扁平，非嵌套）已用本机 ai-memory 实际写入的
> 条目复核过，不是推断。

## 与 config.yaml 的关系

`config.yaml` 的 `hooks.events`（47 项规范词表）是这些取证的并集；
`hooks.clients[].events` 是各客户端的能力子集。改动事件表时应同步本目录。
