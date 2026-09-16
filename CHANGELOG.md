# 变更日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 约定，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

> 注：项目早期历史未按版本逐次发布，以下按可识别的版本里程碑汇总。

## [v0.19.0] - 2026-09

当前发布版本（build 103）。

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

## [Unreleased]

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

[Unreleased]: https://github.com/oswaldhill/skill-mcp-studio/compare/v0.19.0...HEAD
[v0.19.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.19.0
[v0.18.0]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.18.0
[v0.16.1]: https://github.com/oswaldhill/skill-mcp-studio/releases/tag/v0.16.1