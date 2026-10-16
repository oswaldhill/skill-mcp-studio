# 自动发现与活动 Endpoint 的 GUI 编辑

> PRD §10 #1 的待实现项。本文是实现设计文档，不是产品方案。

## 1. 背景与目标

PRD §10 标注的唯一未实现功能：设置页仅有只读展示，缺少 `--set-auto-discover` /
`--set-active-profile` 后端写命令，UI 标注「即将支持」。本次补齐这两层。

## 2. CLI 后端

### 2.1 `--set-active-profile <key>`

把 `active_profile` 写入 `config.yaml` 的 `settings` 段。

- 参数：`--set-active-profile hermes-home`（空字符串 `""` 清除活动端点）
- 校验：key 必须存在于 endpoint 库（`endpoint_store._load_target` 返回的 `profiles`），
  不存在直接拒绝（exit 2），不写入
- 写入路径：`config_store` 的 overlay（gitignored），与 `--set-setting` 同一路径
- 早返回：不跑后续审计（与 `--set-setting` 同一出口）

### 2.2 `--set-auto-discover <key>=<value>`

写 `auto_discover` 段的字段（顶层键，不在 `settings` 下）。

- 参数：`--set-auto-discover enabled=true` / `enabled=false`
- 暂只支持 `enabled` 字段（scan_paths / exclude_paths 不经 GUI 编辑）
- 写入路径：`config_store` 的 overlay
- 早返回

## 3. Rust 白名单

在 `src-tauri/src/lib.rs` 的 `ALLOWED` 数组中，`--set-setting` / `--get-setting`
之后追加：

```
"--set-active-profile",
"--set-auto-discover",
```

两者是写命令但不是重定向命令（不改变 config 文件路径），不进
`DENIED_FLAG_PREFIXES`。

## 4. GUI 前端

MCP 设置 tab 新增两张卡片，插在现有端点库卡片**之前**。

### 4.1 卡片 A：活动端点

- 一个 `<select>` 下拉，列出 `settings.endpoints` 中所有 endpoint key
  （显示 `name (key)` 格式）
- 当前 `settings.active_profile` 高亮选中
- 切换后弹出确认对话框（影响所有客户端），确认后调
  `run_cli(["--set-active-profile", key])`
- 空 key = "无活动端点"（清除）

### 4.2 卡片 B：自动发现

- 开关用 segmented button（与主题/缩放同款 `.seg-btn`）
- scan_paths 只读展示（`<code class="mono">`，每行一条）
- 状态切换后调 `run_cli(["--set-auto-discover", "enabled=true|false"])`

## 5. 测试

- `test_set_active_profile.py`：写入 + 不存在 key 拒绝
- `test_set_auto_discover.py`：写入 enabled=true / false
- Rust：`cargo test` 断言白名单含两条新命令
- DESIGN.md §2.10 设置页：登记两张新卡片

## 6. 安全边界

- 两条命令不改变 config 文件路径，不是重定向，不进 `DENIED_FLAG_PREFIXES`
- `--set-active-profile` 校验 key 存在性
- `--set-auto-discover` 只接受 `enabled` 字段
