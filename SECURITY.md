# 安全政策

## 上报安全漏洞

skill-mcp-studio 本身是一款 **Skill / MCP 合规审计与修复工具**，它会处理本机 IDE/Agent
的配置、Skills 链接与 MCP 端点信息，因此安全漏洞可能意味着敏感信息的意外泄露或未授权
写入。

**请不要在公开 Issue 中披露安全漏洞。** 请通过以下方式非公开上报：

- 邮件至维护者邮箱（沿用 LICENSE 中的版权署名邮箱），或
- 在仓库安全页使用 GitHub 的 **Private vulnerability reporting** 功能。

请在报告中包含：

1. 受影响版本（`skill-mcp-studio --version`）；
2. 触发路径 / 复现步骤；
3. 影响范围（可能泄露的数据、可被利用的写入路径）；
4. 若有补丁建议，一并附上。

## 响应承诺

- **确认**：7 天内确认收到并评估；
- **修复**：确认后按严重程度优先修复，一般 30 天内发布修复版本；
- **披露**：修复发布后，在 `CHANGELOG.md` 中记录，并与上报者协调披露时间。

## 支持版本

仅支持最新发布版本（当前 `v0.23.0`）。历史版本不单独提供安全补丁。

## 安全模型（给审计者）

- 写操作统一走「备份 → 原子写 → 校验 → 回滚」链，见 `core/mcp_fixer.py` 与相关模块；
- 个人真实端点 / 密钥**不在本仓库**：经 `profile_sources` 从仓库外
  `~/.skills-manager/profiles.local.yaml` 合并，仓库内 `config.yaml` 仅保留通用占位；
- 诊断输出会脱敏凭据（见 `scripts/unified_mcp_server.py` 的 `_redact`）。