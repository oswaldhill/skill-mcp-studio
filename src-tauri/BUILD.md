# Tauri 壳构建说明（阶段五 P4+/P5 · macOS）

本目录是通用 Skill/MCP 管理台的 Tauri 2 壳：webview 渲染
`../gui/dashboard.html`，原生侧暴露两个命令——只读快照 `run_audit`
（`skill-mcp-studio --all-profiles --format json`）与通用透传 `run_cli`
（`skill-mcp-studio <args...>`，返回 `{code,stdout,stderr}` 结构，供三栏
管理台的端点库增删、客户端添加、统一目录设置等写操作转发）。写操作
**不重实现于 Rust**，仍走 CLI 的备份 → 原子写 → 校验 → 回滚安全链；
lib.rs 不解析、不重算、不写盘。

> ✅ 状态：已构建验证通过——`cargo tauri build` 全绿，产出
> `target/release/bundle/macos/skill-mcp-studio.app`；`.dmg` 由
> `scripts/build_dmg.sh` 产出（`target/release/bundle/dmg/`，2026-09-05 打通）。
> Rust 工具链（1.98.1）安装于**仓库本地目录**：`.rustup-home/`（RUSTUP_HOME）
> + `.cargo-home/`（CARGO_HOME，均已在根 .gitignore 排除），不依赖系统路径；
> 使用前 `export PATH="$PWD/../.cargo-home/bin:$PATH"`（在 src-tauri 下）。

## 1. 前置条件

```bash
# CLI 必须已可独立调用（GUI 依赖它产出快照）。
# 源码树直接运行时，装一个指向本仓库 scan.py 的 wrapper（本机已装，2026-09-05）：
#   printf '%s\n' '#!/bin/sh' \
#     'exec <绝对路径python3> <repo>/scan.py "$@"' \
#     > ~/.local/bin/skill-mcp-studio && chmod +x ~/.local/bin/skill-mcp-studio
# 本机实装：解释器用 /opt/homebrew/opt/python@3.11/bin/python3.11（绝对路径，
# 勿用 /usr/local/bin/python3——本机不存在；勿用裸命令名）。
# 原因：.app 从 Finder 启动时 PATH 仅 /usr/bin:/bin:/usr/sbin:/sbin，
# 且 lib.rs 回退查找 ~/.local/bin → /usr/local/bin → /opt/homebrew/bin。
# 验证（模拟 Finder PATH）：
#   env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin HOME="$HOME" \
#     ~/.local/bin/skill-mcp-studio --all-profiles --format json | head
which skill-mcp-studio || ls ~/.local/bin/skill-mcp-studio || pipx install skill-mcp-studio

# Rust 工具链：安装于仓库本地目录（不碰系统路径；根 .gitignore 已排除
# .cargo-home/ .rustup-home/ src-tauri/target/）。首次安装：
#   curl -sSf https://static.rust-lang.org/rustup/dist/aarch64-apple-darwin/rustup-init \
#     -o .cargo-home/rustup-init && chmod +x .cargo-home/rustup-init
#   RUSTUP_HOME="$PWD/.rustup-home" CARGO_HOME="$PWD/.cargo-home" \
#     ./.cargo-home/rustup-init -y --default-toolchain stable --profile minimal --no-modify-path
# 日常使用（在 src-tauri/ 下）—— 注意：下面写法含 `..`，见紧随其后的告警：
export RUSTUP_HOME="$PWD/../.rustup-home"
export CARGO_HOME="$PWD/../.cargo-home"
export PATH="$CARGO_HOME/bin:$PATH"
rustc --version && cargo --version

# macOS 桌面构建需要 Xcode Command Line Tools
xcode-select -p    # 非空即已装；未装则 `xcode-select --install`
```

> ⚠️ **PATH 陷阱（2026-09-20 实测）**：上面 `export` 里的 `$CARGO_HOME` 含 `..`，会导致该 PATH
> 项解析失败，表现为 `cargo: command not found`（受限沙箱会话下稳定复现；`command -v cargo`
> 为空，改用绝对路径即可用）。构建失败时先用下面的归一化写法排除此因，再去怀疑工具链本身：

```bash
cd src-tauri
export CARGO_HOME="$(cd .. && pwd)/.cargo-home"
export RUSTUP_HOME="$(cd .. && pwd)/.rustup-home"
export PATH="$CARGO_HOME/bin:$PATH"
cargo --version    # 应能解析
```

## 2. 图标（已生成）

`icons/` 下已含 `32x32.png` / `128x128.png` / `128x128@2x.png` / `icon.ico` /
`icon.icns`（由 PIL + macOS `iconutil` 生成）。如需换源图重生成：

```bash
# 换 PNG 后重出 iconset → icns（macOS）
# 其余用仓库 scripts 或 PIL 重写即可；完整重生成用 tauri-cli：
cargo install tauri-cli --locked
cargo tauri icon ../docs/new-icon.png
```

> `generate_context!` 只要求 `tauri.conf.json` 里 `bundle.icon` 列出的文件存在；
> 缺失会报 `No such file or directory`，补齐即可。

## 3. 构建

```bash
cd src-tauri
cargo build --release                 # 编译二进制（最小编译验证）
cargo tauri build                     # 产出 macOS .app bundle（targets: ["app"]）
# 无全局 tauri-cli 时等价命令（node 在 PATH 即可）：
#   npm_config_cache="$PWD/../.npm-cache" npx -y @tauri-apps/cli@2 build

../scripts/build_dmg.sh               # .app → .dmg 安装映像（§3.1）
```

产物位置：`src-tauri/target/release/bundle/macos/skill-mcp-studio.app`
（内含 `Contents/MacOS/skill-mcp-studio` 二进制 + `Info.plist` + `Resources/icon.icns`）。

### 3.1 .dmg 出包（2026-09-05 打通，含历史误诊更正）

`.dmg` 历史上两次失败，实为**两层独立原因**（此前 BUILD.md 误记为单一
「系统磁盘映像权限限制」）：

1. **沙箱权限**：受限会话（workspace-write 沙箱）内 `hdiutil create` 直接被拒
   「操作不被允许」——需完全访问权限的宿主/会话；
2. **tauri 内置调用的递归缺陷**（根因，2026-09-05 三次复现实锤）：
   `tauri build --bundles dmg` 调 `bundle_dmg.sh` 时以「相对输出名 +
   CWD=源目录」传参，脚本第 313-316 行
   `DMG_TEMP_NAME="$DMG_DIR/rw.$$.${DMG_NAME}"`（DMG_DIR=dirname(输出)）使
   临时工作映像 `rw.<pid>.<name>.dmg` **落在源目录 `bundle/macos/` 内**；
   随后 `hdiutil create -srcfolder` 把源目录拷入映像时递归包含这份正在写入
   的临时映像自身，报「设备上无剩余空间」（磁盘明明有 33Gi）而失败，且残留
   `rw.*.dmg` 污染源目录使后续每次重试都失败。

**修复**：`scripts/build_dmg.sh`——复用 tauri 生成的 `bundle_dmg.sh`
（窗口布局 + Applications 拖拽位），但输出传**绝对路径**（工作映像落
`bundle/dmg/`，源目录外），并前置清理残留工作映像/陈旧挂载；若无
`bundle_dmg.sh`（纯 `--bundles app` 构建）则退化为裸 `hdiutil` 从干净
staging 目录直出。产物自检（挂载→核对 .app→卸载）。

产物：`target/release/bundle/dmg/skill-mcp-studio_0.1.0_arm64.dmg`
（2.6MB，UDZO 压缩率 92.5%）。`tauri.conf.json` 的 `targets` 保持
`["app"]`（tauri 内置 dmg 调用仍有缺陷 2，不要用）。

> **运行时三处已修（2026-09-04）**：
> 1. `tauri.conf.json` 开 `app.withGlobalTauri: true`——否则 Tauri 2 不注入
>    `window.__TAURI__`，看板「刷新审计」按钮不出现，`.app` 只显示示例数据；
> 2. `lib.rs` CLI 解析增加绝对路径回退（`~/.local/bin` / `/usr/local/bin` /
>    `/opt/homebrew/bin`）——Finder 启动的 GUI 进程 PATH 极小，裸命令名会找不到
>    用户目录里的 wrapper；
> 3. `gui/dashboard.html` 按 Tauri 2 形状取 `window.__TAURI__.core.invoke`
>    （v1 是顶层 `invoke`，vendored 源码证实 v2 命名空间化为
>    `app/core/event/...`），并补启动加载：桌面壳自动审计、浏览器直开渲染
>    示例——此前 `SAMPLE` 定义后从未 `render()`，任何上下文启动都是空窗口。

## 4. 验证（DOD：GUI/CLI 结论完全一致）

装好的 `.app` 与 CLI 必须对**同一环境**产出**逐字段一致**的审计结论：

```bash
# 第 1 路：CLI 直接快照
skill-mcp-studio --all-profiles --format json > cli.json

# 第 2 路：走引擎侧复算的一致性 gate（等价于 GUI 消费链路的结论）
scripts/verify_gui_consistency.sh -c config.yaml

# 桌面端手测
open 'target/release/bundle/macos/skill-mcp-studio.app'
#  → 点「刷新审计」→ 界面矩阵与 cli.json 的 records 三态逐一吻合
```

`run_audit` 返回的正是 `--all-profiles --format json` 的 stdout，未加任何加工，
故「结论一致」是结构性的；`verify_gui_consistency.sh` 与前端矩阵只是回归护栏。

## 5. GUI 暴露面

| 命令 | CLI 子进程 | 副作用 |
|------|-----------|--------|
| `run_audit` | `--all-profiles --format json` | 无（扫描 + 只读探测） |
| `run_cli` | 任意 `<argv>`（管理台转发） | 取决于 argv：只读命令（`--management` / `--list-endpoints` / `--list-mcp-inventory`）无副作用；写命令（`--add-endpoint` / `--remove-endpoint` / `--update-endpoint` / `--attach-endpoints` / `--add-client` / `--set-unified-dir`）经 CLI 的备份 → 原子写 → 校验 → 回滚链 |

> 写操作的表单由前端弹窗提供，但**落盘逻辑 100% 在 CLI**（`mcp_fixer`
> 安全范式）；Rust 壳只做 argv 透传 + 结果透传，不新增写盘代码路径。

## 6. 目录

```
src-tauri/
├── Cargo.toml          # tauri 2 + serde/serde_json
├── build.rs            # tauri_build::build()
├── tauri.conf.json     # frontendDist=../gui, window url=dashboard.html
├── src/
│   ├── main.rs         # 入口 → skill_mcp_studio_lib::run()
│   └── lib.rs          # run_audit（只读命令；缺 CLI 时提示 pipx 安装）
└── icons/              # 由 `cargo tauri icon` 生成（首次执行）
```