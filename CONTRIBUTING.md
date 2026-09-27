# 贡献指南

感谢你对 skill-mcp-studio 的关注。本文说明如何搭建开发环境、运行测试、提交代码。

## 环境要求

- **Python ≥ 3.11**（运行时唯一依赖 `PyYAML`）
- **Rust ≥ 1.77** + **Tauri v2**（仅桌面 App 构建需要）
- **Node.js**（渲染护栏测试需要；缺失时相关用例会静默跳过，见「运行测试」）
- **npm**（仅构建 Tauri 壳的 tauri-cli 需要）

## 开发环境

```bash
git clone <repo> && cd skill-mcp-studio
scripts/install-hooks.sh        # 启用提交门禁，见下节（只需一次）

# 从源码直接运行 CLI（无需安装）
python3 scan.py --help
python3 scan.py --full            # 只读审计
```

### 启用提交门禁（clone 后必做一次）

仓库自带一个 `pre-push` 门禁：**默认拦截**推送到 GitHub 的请求，只有显式设置
`GITHUB_PUSH_ALLOW=1` 时才放行。

`.git/hooks/` 不随仓库提交，所以门禁脚本放在 `scripts/git-hooks/`，并用
`core.hooksPath` 让 git 直接从仓库内加载：

```bash
scripts/install-hooks.sh
```

该脚本会设置 `core.hooksPath=scripts/git-hooks` 并补上可执行位。

> **不执行这一步，门禁不会生效，而且不会有任何提示。**
> 新克隆的仓库、换机器、或 `.git` 目录被重建后，都需要重新执行一次。

放行某次推送（仅在确实需要提交 GitHub 时）：

```bash
GITHUB_PUSH_ALLOW=1 git push github <branch>
```

## 运行测试

测试使用标准库 `unittest`，无需额外安装 pytest。**请使用与 CI 完全一致的命令**：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

> **不要加 `-t .`**：`tests/` 目录不含 `__init__.py`，一旦指定顶层目录，`discover` 会直接抛
> `ImportError: Start directory is not importable`。省略 `-t`（顶层目录默认即 `tests/`）才能正常收集，
> 这也正是 CI 的用法。

### 必须让 `node` 在 PATH 上

约 35 个「渲染护栏」用例依赖 `node`。找不到 `node` 时它们会 **skip 而不是 failed**，
于是会出现「本地全绿、CI 变红」的假象。跑完请核对汇总行：

- 与 CI 等价 → `OK (skipped=2)`
- 若 skipped 数明显偏大 → `node` 多半不在 PATH。Homebrew 安装的 node 位于
  `/opt/homebrew/bin`，该前缀常不在非登录 shell 的 PATH 中：

```bash
export PATH="/opt/homebrew/bin:$PATH"
node --version
python3 -m unittest discover -s tests -p 'test_*.py'
```

更省事的方式是直接跑一键脚本，它会自动补齐前置条件（含解释器版本与 node）
并与 CI 基线对照：

```bash
scripts/ci_parity.sh
```

## 构建桌面 App（macOS）

```bash
cd src-tauri
cargo tauri build              # 产出 target/release/bundle/macos/skill-mcp-studio.app
```

详细步骤见 [`src-tauri/BUILD.md`](src-tauri/BUILD.md)。

### 改 GUI 不必重建：开发态热加载

生产构建会把 `gui/` 整体嵌入二进制（`tauri.conf.json` 的 `frontendDist`），
所以默认情况下改一行 `dashboard.html` 都要重新 build + 重装。

开发时可以设 `SMS_GUI_DEV=1`：桌面壳启动后会把主窗口导航到**源树里的**
`gui/dashboard.html`，于是改完只需在窗口里刷新（macOS 上 `Cmd+R`）。

```bash
cd src-tauri
SMS_GUI_DEV=1 cargo tauri dev
```

- 不设该变量时完全走原有嵌入资源路径，**生产行为不变**。
- 三处异常（未找到窗口 / 路径无法转为 `file://` URL / 导航失败）都会在 stderr
  打印 `[SMS_GUI_DEV]` 前缀的告警，便于排查。
- 这是「直读磁盘」，不是文件监听：改完仍需手动刷新一次，但无需重新编译。


## 发布新版本

发布流程已固化为 `scripts/release.sh`。**不要手敲那一串步骤** ——
它把顺序与前置校验写死，让「漏一步」在本地就暴露，而不是等 release workflow
触发后才发现。

```bash
scripts/release.sh --bump minor                      # 预演：跑校验 + bump 预览，不改任何东西
scripts/release.sh --bump minor --apply             # 执行本地部分（bump + 提交）
scripts/release.sh --bump minor --apply --tag       # 额外打 tag
scripts/release.sh --bump minor --apply --tag --push  # 额外推送
```

三条设计约束，知道了才不会误用：

- **默认预演**：发布不可逆（tag 与远端历史），必须显式 `--apply` 才动手。
- **默认不推送**：本仓库有「未经允许不得 push」的门禁 hook（P0-6），
  脚本不绕过它；`--push` 是显式授权，且推送前会再确认一次。
- **CHANGELOG 正文不自动生成**：脚本只校验「新版本段落存在且非空」，
  缺失就停下让你去写 —— 变更内容需要人写，不该编。

与 CI 的关系：CI 的 `tag-version-consistency` job 会在 tag 与 `version.json`
不一致时**事后**拦下；本脚本做的是**事前**同源校验（要打的 tag 必须等于
`version.json` 里的 version）。两者构成双保险，不是重复。

## 项目结构

- `scan.py` — CLI 入口
- `core/` — 领域逻辑（扁平顶层模块）
- `gui/dashboard.html` — 前端管理台（单文件静态页）
- `src-tauri/` — Tauri 桌面壳
- `scripts/git-hooks/` — 随仓库分发的 git hooks（用 `scripts/install-hooks.sh` 启用）
- `docs/` — 产品 / 设计 / 决策 / 评审文档（见 [`docs/README.md`](docs/README.md)）

## 提交规范

- 提交信息采用 Conventional Commits 风格：`fix:` / `feat:` / `docs:` / `refactor:` /
  `chore:` / `test:`。
- 一个提交只做一件事，避免混合无关改动。
- 涉及写操作的代码路径必须遵循既有的「备份 → 原子写 → 校验 → 回滚」安全链范式。

## 提交 PR 前检查

1. `scripts/ci_parity.sh` 通过（等价于 CI 的
   `python3 -m unittest discover -s tests -p 'test_*.py'`，并会核对 skipped 数）；
2. 若改动影响 GUI/CLI 结论，运行 `scripts/verify_gui_consistency.sh` 保证一致性；
3. 不向仓库提交个人拓扑 / 真实端点 / 密钥（保持 `config.yaml` 通用化、个人端点放仓库外）。

## 上报问题

- Bug / 功能请求 → 新建 [Issue](https://github.com/oswaldhill/skill-mcp-studio/issues)
- 安全漏洞 → 按 [`SECURITY.md`](SECURITY.md) 非公开上报
