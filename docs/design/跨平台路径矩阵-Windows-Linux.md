# 跨平台路径矩阵（Windows / Linux）

| 版本 | 日期 | 说明 |
|------|------|------|
| v0.1 | 2026-09-07 | 首次调研：15 个主流客户端在 Windows 与 Linux 的真实默认路径；macOS 现有路径见 `core/mainstream_registry.py` / `config.yaml` |
| v0.2 | 2026-09-07 | 追加国产客户端：CodeBuddy / WorkBuddy / Qoder / QwenWork(千问办公) / Trae / TraeWork / 豆包(Doubao)，共 7 个 |

> 本文档是「三平台支持（决策 A：`paths_by_os` + `sys.platform` 分派）」需求的事实底座。
> 每条路径标注确定度：**verified**（官方文档/源码核实）与 **best-effort**（社区/推断，仅依据 VS Code fork 或 Electron 惯例）。
> 「宁缺毋滥」：查无权威来源的字段留空（`[]` 或 `""`），绝不用猜测填充。

## 路径约定

- **Windows**：`%USERPROFILE%`（家目录）、`%APPDATA%`（Roaming）、`%LOCALAPPDATA%`（Local）。工具运行时展开环境变量，不硬编码盘符/用户名。
- **Linux**：遵循 XDG（`~/.config` 优先）与 Ubuntu/Debian 口径，`~` = 家目录。
- **字段**：`app_bundles`（GUI 应用）、`commands`（PATH 可执行）、`config_paths`（配置/MCP 文件）、`skills_path`（技能目录）、`mcp_config_path`（MCP 写入目标）。

---

## 一、CLI 优先的 AI 编码助手

### Claude Code

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | `%USERPROFILE%\.local\bin\claude.exe` (verified) | `~/.local/bin/claude` (verified) |
| commands | `claude` | `claude` |
| config_paths | `%USERPROFILE%\.claude\settings.json`、`%USERPROFILE%\.claude.json` | `~/.claude/settings.json`、`~/.claude.json` |
| skills_path | `%USERPROFILE%\.claude\skills` (verified) | `~/.claude/skills` (verified) |
| mcp_config_path | `%USERPROFILE%\.claude.json` | `~/.claude.json` |

来源：官方 `code.claude.com/docs`（setup / settings / claude-directory / skills）。

### Codex (OpenAI)

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | （CLI，无 GUI） | （CLI，无 GUI） |
| commands | `codex` | `codex` |
| config_paths | `%USERPROFILE%\.codex\config.toml`、`%USERPROFILE%\.codex\auth.json` | `~/.codex/config.toml`、`~/.codex/auth.json` (verified) |
| skills_path | `%USERPROFILE%\.agents\skills` (best-effort 映射) | `~/.agents/skills` (verified) |
| mcp_config_path | `%USERPROFILE%\.codex\config.toml`（`[mcp_servers]` 段） | `~/.codex/config.toml` |

来源：`developers.openai.com/codex`（config-reference / auth / skills）。

### Gemini CLI (Google)

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | （CLI，无 GUI） | （CLI，无 GUI） |
| commands | `gemini` | `gemini` |
| config_paths | `%USERPROFILE%\.gemini\settings.json`、`%USERPROFILE%\.gemini\.env` | `~/.gemini/settings.json`、`~/.gemini/.env` (verified) |
| skills_path | `%USERPROFILE%\.gemini\skills` (best-effort) | `~/.gemini/skills` (verified，别名 `~/.agents/skills`) |
| mcp_config_path | `%USERPROFILE%\.gemini\settings.json` | `~/.gemini/settings.json` |

来源：`geminicli.com/docs`（settings / skills / mcp-server）+ 官方 GitHub。

### OpenCode

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | （CLI，无 GUI） | （CLI 为主，无权威 Linux GUI 路径） |
| commands | `opencode` | `opencode` |
| config_paths | `%USERPROFILE%\.config\opencode\opencode.json` (best-effort) | `~/.config/opencode/opencode.json`、`~/.config/opencode/tui.json` (verified) |
| skills_path | `%USERPROFILE%\.config\opencode\skills` (best-effort) | `~/.config/opencode/skills` (verified，兼容 `~/.claude/skills`、`~/.agents/skills`) |
| mcp_config_path | `%USERPROFILE%\.config\opencode\opencode.json` | `~/.config/opencode/opencode.json` |

来源：`opencode.ai/docs`（config / skills / windows-wsl）。

### Aider

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | （CLI，无 GUI） | （CLI，无 GUI） |
| commands | `aider` | `aider` |
| config_paths | `%USERPROFILE%\.aider.conf.yml`、`%USERPROFILE%\.env` | `~/.aider.conf.yml`、`~/.env` (verified) |
| skills_path | （无 skills 目录） | （无 skills 目录） |
| mcp_config_path | （无内建 MCP 客户端） | （无内建 MCP 客户端） |

来源：`aider.chat/docs`（config / dotenv）。

---

## 二、桌面型 AI IDE

### Cursor

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | `%LOCALAPPDATA%\Programs\Cursor\Cursor.exe` (best-effort) | （apt/yum/AppImage，无固定目录） |
| commands | `cursor`、`agent` | `cursor`、`agent` |
| config_paths | `%APPDATA%\Cursor\User\settings.json` (best-effort)、`%USERPROFILE%\.cursor\mcp.json` (verified) | `~/.config/Cursor/User/settings.json` (best-effort)、`~/.cursor/mcp.json` (verified) |
| skills_path | `%USERPROFILE%\.cursor\skills` (verified) | `~/.cursor/skills` (verified，亦支持 `~/.agents/skills`) |
| mcp_config_path | `%USERPROFILE%\.cursor\mcp.json` | `~/.cursor/mcp.json` |

来源：`cursor.com/docs`（mcp / skills / cli / quickstart）。

### Windsurf

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | `%LOCALAPPDATA%\Programs\Windsurf\Windsurf.exe` (best-effort) | （AppImage/deb，无固定目录） |
| commands | `windsurf` | `windsurf` |
| config_paths | `%APPDATA%\Windsurf\User\settings.json` (best-effort)、`%USERPROFILE%\.codeium\windsurf\mcp_config.json` (best-effort 映射) | `~/.config/Windsurf/User/settings.json` (best-effort)、`~/.codeium/windsurf/mcp_config.json` (verified) |
| skills_path | （无权威 Skills 目录） | （无权威 Skills 目录） |
| mcp_config_path | `%USERPROFILE%\.codeium\windsurf\mcp_config.json` | `~/.codeium/windsurf/mcp_config.json` |

来源：Windsurf 官方 MCP 文档（web.archive）+ 第三方 README。

### Zed

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | `%LOCALAPPDATA%\Programs\Zed\zed.exe` (best-effort) | `~/.local/zed.app/bin/zed` (verified) |
| commands | `zed` | `zed` |
| config_paths | `%APPDATA%\Zed\settings.json` (verified) | `~/.config/zed/settings.json` (verified) |
| skills_path | `%USERPROFILE%\.agents\skills` (verified) | `~/.agents/skills` (verified) |
| mcp_config_path | `%APPDATA%\Zed\settings.json`（`context_servers` 字段） | `~/.config/zed/settings.json`（`context_servers` 字段） |

来源：`zed.dev/docs` + 官方源码（configuring-zed / ai/mcp / ai/skills / windows / linux）。

### VS Code

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | `%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe`、`C:\Program Files\Microsoft VS Code\Code.exe` (verified) | （.deb/.rpm/AppImage，无固定目录） |
| commands | `code` | `code` |
| config_paths | `%APPDATA%\Code\User\settings.json` (verified) | `~/.config/Code/User/settings.json` (verified) |
| skills_path | （无内建 skills 目录） | （无内建 skills 目录） |
| mcp_config_path | `%APPDATA%\Code\User\mcp.json` (verified) | `~/.config/Code/User/mcp.json` (verified) |

来源：`code.visualstudio.com/docs`（settings / mcp-configuration / profiles / linux）。

### JetBrains（IntelliJ IDEA / PyCharm / WebStorm）

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | `%LOCALAPPDATA%\JetBrains\Toolbox\apps`（其下 `<Product>/ch-0/<build>/bin`）(best-effort) | `~/.local/share/JetBrains/Toolbox/apps` (best-effort) |
| commands | （默认不入 PATH） | `idea` / `pycharm` / `webstorm`（Toolbox 生成，best-effort） |
| config_paths | `%APPDATA%\JetBrains\<Product><version>` (verified) | `~/.config/JetBrains/<Product><version>` (verified) |
| skills_path | （无 agent skills 目录） | （无 agent skills 目录） |
| mcp_config_path | （无独立权威 MCP 文件） | （无独立权威 MCP 文件） |

来源：`jetbrains.com/help/idea/directories-...` + webstorm installation-guide。

### TRAE（ByteDance 国际版）

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | `%LOCALAPPDATA%\Programs\Trae\Trae.exe` (best-effort) | （AppImage/deb，无固定目录） |
| commands | `trae` | `trae` |
| config_paths | `%APPDATA%\Trae\User\settings.json` (best-effort) | `~/.config/Trae/User/settings.json` (best-effort) |
| skills_path | （无权威来源） | （无权威来源） |
| mcp_config_path | （无权威来源） | （无权威来源） |

来源：社区教程（CSDN / GitHub issue / 腾讯云）。注：国内版 **Trae CN** 目录为 `%APPDATA%\Trae CN` 与 `~/.config/Trae CN`，需单独区分。

### Cherry Studio

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | `%LOCALAPPDATA%\Programs\Cherry Studio\Cherry Studio.exe` (verified) | （AppImage/deb/rpm，无固定目录） |
| commands | （无） | （无） |
| config_paths | `%APPDATA%\CherryStudio` (best-effort) | `~/.config/CherryStudio` (best-effort) |
| skills_path | （无权威来源） | （无权威来源） |
| mcp_config_path | （GUI 内管理，无独立权威文件） | （GUI 内管理，无独立权威文件） |

来源：`github.com/CherryHQ/cherry-studio`（electron-builder.yml / diagnostics / issue）。

---

## 三、VS Code 扩展类（无独立可执行文件）

### Cline

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles / commands | （VS Code 扩展 `saoudrizwan.claude-dev`，无独立可执行文件） | 同左 |
| config_paths | `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json` (文件名 verified，绝对路径 best-effort) | `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` |
| skills_path | `%USERPROFILE%\.cline\skills` (verified) | `~/.cline/skills` (verified) |
| mcp_config_path | 同 config_paths | 同 config_paths |

来源：`github.com/cline/cline`（skill-directories / disk / package.json）。

### Roo Code

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles / commands | （VS Code 扩展 `RooVeterinaryInc.roo-cline`，无独立可执行文件） | 同左 |
| config_paths | `%APPDATA%\Code\User\globalStorage\RooVeterinaryInc.roo-cline\settings\mcp_settings.json` | `~/.config/Code/User/globalStorage/RooVeterinaryInc.roo-cline/settings/mcp_settings.json` |
| skills_path | `%USERPROFILE%\.roo\skills` (verified) | `~/.roo/skills` (verified) |
| mcp_config_path | 同 config_paths；项目级 `<workspace>\.roo\mcp.json` | 同左；项目级 `<workspace>/.roo/mcp.json` |

来源：`github.com/RooCodeInc/Roo-Code`（skills.mdx / McpHub / globalFileNames / roo-config）。

---

## 四、AI Agent 桌面/CLI

### Goose (Block → AAIF)

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | （Desktop 为便携 zip，无固定位置） | （DEB/RPM/Flatpak，无固定位置） |
| commands | `goose` | `goose`（`~/.local/bin/goose`） |
| config_paths | `%APPDATA%\Block\goose\config\config.yaml` (verified) | `~/.config/goose/config.yaml` (verified) |
| skills_path | `%USERPROFILE%\.agents\skills` (verified) | `~/.agents/skills` (verified) |
| mcp_config_path | `%APPDATA%\Block\goose\config\config.yaml`（extensions 段） | `~/.config/goose/config.yaml`（extensions 段） |

来源：`goose-docs.ai/docs`（config-files / installation）+ `aaif-goose/goose` 源码。

---

## 五、跨客户端的「统一惯例」清单（三平台收敛）

调研暴露了一个强信号：多数客户端遵循 **「家目录下 `.agents/skills`」或自目录 `.xxx/skills`** 的演进惯例：

- **`~/.agents/skills`（跨代理通用技能目录）**：Zed、Codex、Gemini CLI、OpenCode、Cline、Roo Code、Goose 均支持或默认。
- **`~/.claude/skills`（事实标准）**：Claude Code 定义，OpenCode 等多个客户端兼容读取。
- **Windows 的 VS Code/fork 家族**：`%APPDATA%\<Product>\User\settings.json`；MCP 文件多数落在 `%USERPROFILE%\.xxx\mcp.json` 或 `%APPDATA%\...\mcp.json`。

这组惯例可作为 `auto_discover` 跨平台扫描路径的骨架（见 PRD / 技术方案）。

---

## 六、国产客户端（腾讯 / 阿里 / 字节）

> 身份易混，均已在 identity 字段核实。标注「无 Linux 桌面版」的客户端在 Linux 扫描时直接跳过（各字段留空）。

### CodeBuddy（腾讯云代码助手）

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | `%LOCALAPPDATA%\Programs\CodeBuddy` (verified) | （.deb 系统级安装，无固定目录） |
| commands | `codebuddy`、`buddycn` | `codebuddy`、`buddycn` |
| config_paths | `%USERPROFILE%\.codebuddy\{settings.json, settings.local.json, CODEBUDDY.md, models.json}` | `~/.codebuddy/{settings.json, settings.local.json, CODEBUDDY.md, models.json}` (verified) |
| skills_path | `%USERPROFILE%\.codebuddy\skills` | `~/.codebuddy/skills` |
| mcp_config_path | `%USERPROFILE%\.codebuddy\mcp.json` | `~/.codebuddy/mcp.json` |

来源：`cloud.tencent.cn/document/product/1831/*` + `codebuddy.ai/docs/cli/*`。
注：与 WorkBuddy 是不同 SKU；CLI 为 `codebuddy`，IDE 打开命令为 `buddycn`。

### WorkBuddy（腾讯云办公工作台）

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | `%LOCALAPPDATA%\Programs\WorkBuddy` (verified) | （UOS/Kylin 商店，通用发行版无固定目录） |
| commands | （无 PATH 命令） | `workbuddy` |
| config_paths | `%USERPROFILE%\.workbuddy\{settings.json, models.json}` | `~/.workbuddy/{settings.json, models.json}` (structure verified) |
| skills_path | `%USERPROFILE%\.workbuddy\skills` | `~/.workbuddy/skills` |
| mcp_config_path | `%USERPROFILE%\.workbuddy\mcp.json` | `~/.workbuddy/mcp.json` |

来源：`github.com/oceanbase/powercontext`（configure-workbuddy）+ 腾讯云社区。
注：与 CodeBuddy 同属腾讯云但为办公自动化智能体（非代码助手）；`~/.workbuddy` 结构与 macOS 一致。

### Qoder（阿里云，原「通义灵码」新品牌）

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | `%LOCALAPPDATA%\Programs\Qoder` (best-effort) | （.deb/.rpm，无固定目录） |
| commands | `qoder` | `qoder` |
| config_paths | `%USERPROFILE%\.qoder\{settings.json, 根目录}` | `~/.qoder/{settings.json, 根目录}` (verified) |
| skills_path | `%USERPROFILE%\.qoder\skills` | `~/.qoder/skills` |
| mcp_config_path | `%USERPROFILE%\.qoder\settings.json` | `~/.qoder/settings.json`（`mcpServers` 段） |

来源：`docs.qoder.com/zh/cli/*`。
注：CLI 与 IDE 共用 `~/.qoder`；区别于开源 Qwen Code CLI（`~/.qwen`）。

### QwenWork（千问办公，qwenwork.cn）

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | （官方未文档化具体路径） | **无 Linux 桌面版** |
| commands | （无） | — |
| config_paths | `%USERPROFILE%\.qwenworkcn` (verified) | — |
| skills_path | `%USERPROFILE%\.qwenworkcn\skills` (verified) | — |
| mcp_config_path | （GUI 录入口，未文档化落盘文件） | — |

来源：`help.aliyun.com/zh/qwenwork/*`。
注：**仅 macOS / Windows / HarmonyOS**，Linux 跳过；MCP 仅走 GUI 配置。

### Trae（字节跳动国际版）

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | `%LOCALAPPDATA%\Programs\Trae` (best-effort) | （.deb/.rpm/AppImage，无固定目录） |
| commands | `trae` | `trae` |
| config_paths | `%APPDATA%\Trae\User\settings.json` (best-effort) | `~/.config/Trae/User/settings.json` (verified) |
| skills_path | `%APPDATA%\Trae\skills` (community verified) | `~/.trae/skills` (community verified) |
| mcp_config_path | `%APPDATA%\Trae\User\mcp.json` | `~/.config/Trae/User/mcp.json` |

来源：`docs.trae.ai/ide/skills` + 社区实测（ToolUniverse / agent-config）。
注：**Trae 国际版**与**国内版 Trae CN**目录不同——CN 版 Windows 为 `%APPDATA%\Trae CN`、Linux 为 `~/.config/Trae CN`（国内版带 CN 后缀）。

### TraeWork（字节跳动 AI 工作台，前身 TraeCode SOLO）

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | （无权威来源） | **无 Linux 桌面版** |
| commands | （无） | — |
| config_paths | `%USERPROFILE%\.trae-cn` (verified) | — |
| skills_path | `%USERPROFILE%\.trae-cn\skills` (verified) | — |
| mcp_config_path | （GUI 录入口，未公开本地文件） | — |

来源：`docs.trae.cn/work_*`。
注：前身 TraeCode SOLO、2026-08 并入豆包体系；桌面版仅 macOS/Windows，Linux 仅网页版（无本地数据目录）。

### 豆包（Doubao，字节跳动通用 AI 助手，含专业版）

| 字段 | Windows | Linux |
|------|---------|-------|
| app_bundles | `%LOCALAPPDATA%\Doubao`（主程序 `...\Doubao\Application\app\Doubao.exe`）(verified) | **无 Linux 原生客户端** |
| commands | （无） | — |
| config_paths | `%LOCALAPPDATA%\Doubao`（Electron 数据目录） | — |
| skills_path | **无本地 skills 目录** | — |
| mcp_config_path | **无 MCP 客户端配置** | — |

来源：卸载信息库 + 社区实测。
注：通用对话助手，**非编程 IDE**，无本地 skills/MCP 语义；Linux 仅网页版。扫描时仅能判断 Windows 是否安装，不参与 skills/MCP 检查。

---

## 附：确定度统计（v0.2 合并后）

| 类别 | 客户端 |
|------|------|
| 全部/核心字段 verified | Claude Code、Codex、Gemini CLI、OpenCode、Aider、Zed、VS Code、Goose、Cline、Roo Code、CodeBuddy、WorkBuddy(结构)、Qoder、QwenWork(Win)、Trae(skills/MCP)、TraeWork(Win) |
| 仅 best-effort（无官方路径文档） | TRAE(app)、Cherry Studio、Windsurf(skills)、JetBrains(app)、豆包(社区实测) |
| 明确「无 skills / 无 MCP 客户端」 | Aider、VS Code、JetBrains、Windsurf(skills 否)、豆包 |
| **无 Linux 桌面版（Linux 扫描跳过）** | QwenWork(千问办公)、TraeWork（Linux 仅网页版）、豆包 |
