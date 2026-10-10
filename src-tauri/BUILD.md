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
> + `.cargo-home/`（CARGO_HOME），不依赖系统路径；
> 使用前 `export PATH="$PWD/../.cargo-home/bin:$PATH"`（在 src-tauri 下）。
>
> ⚠️ **更正（2026-10-08 核实）**：此处原写「均已在根 .gitignore 排除」，**与事实不符**。
> v0.24.0 的 P2-1 移除了这两个目录的忽略条目（缘由见根 `.gitignore` 第 22-25 行注释），
> 用意是把「工具链指向仓库内」从预期布局改回 `$HOME`。因此它们**并未被忽略**，会一直
> 出现在 `git status` 的未跟踪列表里（本机两者合计约 736MB），而这不是待提交内容。
> 桩因（本机现状与 P2-1 的预期不一致）：`$HOME/.cargo` 不存在、`$HOME/.rustup` 存在但
> 构建实际依赖仓库内这份工具链，所以上述 `export` 仍是本机可用做法。若要回归 P2-1 的
> 预期布局，请把 `RUSTUP_HOME`/`CARGO_HOME` 指回 `$HOME` 并在那里重新安装工具链。
> 二者**从未被提交进仓库历史**，因此不涉及任何历史清理。
>
> ✅ **P2-1 预期布局已达成（2026-10-10 核实）**：仓库内 `.cargo-home/`、`.rustup-home/`
> **均已不存在**，工具链现在确实位于 `$HOME/.cargo`（1.98.1）+ `$HOME/.rustup`，
> `~/.cargo/bin/cargo-tauri`（tauri-cli 2.11.5）已装。因此 §1 的仓库内 `export` 写法
> **已过时**，本机日常用法见 §1；受限会话下的构建边界见 §1.1、CI 门禁工具链见 §1.2。

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

# Rust 工具链：**现位于 $HOME（P2-1 预期布局已达成，2026-10-10）**。
# 仓库内的 .cargo-home/ 与 .rustup-home/ 均已不存在，下述「仓库本地目录」写法保留
# 仅作历史记录 —— 本机当前用法见下方「日常使用（当前）」。
# 忽略状态：src-tauri/target/ 由根 .gitignore 排除。
# 首次安装（历史写法，仓库本地）：
#   curl -sSf https://static.rust-lang.org/rustup/dist/aarch64-apple-darwin/rustup-init \
#     -o .cargo-home/rustup-init && chmod +x .cargo-home/rustup-init
#   RUSTUP_HOME="$PWD/.rustup-home" CARGO_HOME="$PWD/.cargo-home" \
#     ./.cargo-home/rustup-init -y --default-toolchain stable --profile minimal --no-modify-path
# 日常使用（当前，在 src-tauri/ 下）：
export RUSTUP_HOME="$HOME/.rustup"
export CARGO_HOME="$HOME/.cargo"
export PATH="$CARGO_HOME/bin:$PATH"
rustc --version && cargo --version   # 1.98.1 / 1.98.1；cargo tauri --version = 2.11.5

# macOS 桌面构建需要 Xcode Command Line Tools
xcode-select -p    # 非空即已装；未装则 `xcode-select --install`
```

> ⚠️ **PATH 陷阱（2026-09-20 实测）**：上面 `export` 里的 `$CARGO_HOME` 含 `..`，会导致该 PATH
> 项解析失败，表现为 `cargo: command not found`（受限沙箱会话下稳定复现；`command -v cargo`
> 为空，改用绝对路径即可用）。构建失败时先用下面的归一化写法排除此因，再去怀疑工具链本身。
> **注意（2026-10-10）**：下面写法的目标是已不存在的仓库内 `.cargo-home`/`.rustup-home`，
> 保留仅作历史；当前应改用 §1 的 `$HOME` 版本：

```bash
cd src-tauri
export CARGO_HOME="$(cd .. && pwd)/.cargo-home"   # ⚠️ 该目录已不存在（历史写法）
export RUSTUP_HOME="$(cd .. && pwd)/.rustup-home" # ⚠️ 该目录已不存在（历史写法）
export PATH="$CARGO_HOME/bin:$PATH"
cargo --version    # 应能解析
```

### 1.1 受限会话下的构建边界（2026-10-10 回归实测）

工具链迁回 `$HOME` 后，「能不能在受限沙箱里构建」取决于 **cargo 是否需要写 `CARGO_HOME`**，
而不是取决于构建本身。三种情形实测（`cargo`/`rustc` 1.98.1，workspace-write 沙箱）：

| 场景 | 是否写工作区之外 | 结果 |
| --- | --- | --- |
| 依赖已在缓存 → `cargo test` | 否 | ✅ 通过（12 passed） |
| 依赖已在缓存 → `cargo tauri build`（增量/热构建） | 否 | ✅ 通过，正常出包 + 签名 |
| **Cargo.lock 变动 → 需下载新 crate** → `cargo tauri build` | **是**（`$HOME/.cargo/registry`） | ❌ `failed to open .../registry/cache/...crate: Operation not permitted` |

**结论**：受限会话里能用，但只在「依赖集合未变」时才成立。**只要 Cargo.lock 有变动
（如 develop 分支带入的新依赖），首次构建必须用完整访问权限**；此后同一依赖集合内的
重建可在受限会话完成。**先看 Cargo.lock 有没有变，再决定要不要放大权限** —— 不要因为
一次失败就断言「沙箱内一律不能构建」（本次初次构建失败正是 Cargo.lock 变动所致）。

同类边界（同一晚实测）：

- `python3 -m pip install "ruff==0.16.9"` → ❌ `Operation not permitted:
  '~/Library/Python/3.11/lib/python/site-packages/ruff'`（CI 门禁依赖 ruff，见 §1.2）；
- 安装 `.app` 到 `/Applications`、写 `~/.skill-mcp-studio-backups` → ❌ 需完整访问权限（同 §3.2）；
- 沙箱内 `/usr/bin/sudo` 亦被拒（`Operation not permitted`），故**任何需要 root 的
  Spotlight 隐私列表写入都无法自动化**（见 §3.5）。

### 1.2 CI 门禁工具链与本机对照（2026-10-10 实测）

**背景（本次回归踩到的坑）**：本机缺 ruff 时，`scripts/ci_parity.sh` 会在 ruff 段判失败并
**立即退出**，于是**后面的 Python 单元测试一条都没跑** —— 输出停在「✗ 未找到 ruff」，
`exit=1`。这与「测试失败」在现象上难以区分，处置却完全不同（前者是环境缺件，后者是代码
回归）。**⚠️ 该缺陷已于 2026-10-10 修复**，见本节末「已修复」段。

装齐工具链后全绿：

```bash
python3 -m pip install "ruff==0.16.9"   # 与 CI 同版本（本次须完整访问权限，见 §1.1）
scripts/ci_parity.sh                     # ==> 全部通过，skipped=2，与 CI 基线一致
```

本机与 CI 的版本对照（2026-10-10）：

| 组件 | 本机 | CI 钉定 | 一致 |
| --- | --- | --- | --- |
| rustc / cargo | 1.98.1 / 1.98.1 | 1.98.1（`dtolnay/rust-toolchain@1.98.1`） | ✅ |
| tauri-cli | 2.11.5（`~/.cargo/bin/cargo-tauri`） | 未钉（`cargo tauri` 仅本地构建用） | — |
| Python | 3.11.17（`/Users/oswaldhill/bin/python3`） | 3.11 | ✅ |
| ruff | 0.16.9 | 0.16.9 | ✅ |
| PyYAML | 6.0.3 | 随 pip 最新 | — |
| node | **v26.11.0**（`/opt/homebrew/bin/node`） | **20** | ⚠️ 大版本不一致 |

> ⚠️ **node 大版本不一致值得留意**：CI 钉 node 20，本机是 26。
> **`scripts/ci_parity.sh` 确实会告警这一差异**（Q1-1，`CI_NODE_MAJOR=20` 对比
> `process.versions.node` 主版本，实测会打印「⚠ node 主版本不一致：本地 v26 vs CI v20」），
> 所以「本地全绿」时你至少会被提醒去考虑 `node --test` 跨大版本的行为差异。
> 本次 `node --test tests/gui_helpers.test.mjs`（5 passed）与 Python 侧 1088 用例均通过，
> 未发现实际分歧。
>
> 📌 **文档更正**：本节初稿曾写「脚本只校验 node 存在、不校验版本」—— **该说法与事实
> 不符**（脚本第 361-370 行就是主版本比对）。误判来源：当时只看了 `ci_parity.sh` 输出的
> 末尾几行（`tail`），而告警在输出的中段（JS 用例段），没有读到。**教训：读门禁输出要看
> 全量，不要只看 tail** —— 与本节开头「一次误导性的门禁输出比没有门禁更危险」同源。

**已修复（2026-10-10）**：`scripts/ci_parity.sh` 改为**失败累加**——能跑的门禁全部跑完，
`record_failure` 逐项记录，末尾 `print_summary_and_exit` 统一汇总（退出码仍为非零）。
只有「无论如何都跑不下去」的前置条件（无解释器 / 版本 < 3.11）才立即退出。
实测（强制 ruff 缺失）：**`Ran 1088 tests` 正常出现**，`exit=1`，汇总列出
`✗ ruff 不可用（P1-11 / Q0-6）`。回归护栏为
[`tests/test_ci_parity_gate.py`](../tests/test_ci_parity_gate.py)（6 例，静态断言
「ruff 段到 unittest 之间不得有可执行行提前退出」，并校验 `CI_PATTERN` /
`CI_NODE_MAJOR` 与 workflow 实际值一致）。

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

### 3.2 安装到 `/Applications`（本机实操记录，2026-09-21）

构建产物不会自动替换已安装应用，需手工安装。本机步骤（`master` = 合并
`develop` 后的 `0.21.0` build 106）：

```bash
cd src-tauri
export CARGO_HOME="$(cd .. && pwd)/.cargo-home"   # 必须规范化，见 §1 PATH 陷阱
export RUSTUP_HOME="$(cd .. && pwd)/.rustup-home"
export PATH="$CARGO_HOME/bin:$PATH"
cargo tauri build                                  # 28.7s，BUILD_EXIT=0

NEW="$PWD/target/release/bundle/macos/skill-mcp-studio.app"
DEST=/Applications/skill-mcp-studio.app
BK=~/.skill-mcp-studio-backups

# 1) 先退出正在运行的实例（否则替换 bundle 行为未定义）
osascript -e 'tell application "skill-mcp-studio" to quit' || \
  pkill -TERM -f "skill-mcp-studio.app/Contents/MacOS"

# 2) 备份旧版本，再安装（ditto 保留元数据/签名）
mkdir -p "$BK"
ditto "$DEST" "$BK/skill-mcp-studio-0.21.0-premerge.app"
rm -rf "$DEST" && ditto "$NEW" "$DEST"

# 3) 校验：安装后二进制 sha256 必须与**本次构建产物**一致
#    ⚠️ 只比「刚构建的 $NEW」与「刚装好的 $DEST」，不要拿已安装的旧版本去比 ——
#    自签名的 CMS 内嵌签名时间，重建产物与上一次的 sha256 必然不同（见 §3.6）。
shasum -a 256 "$NEW/Contents/MacOS/skill-mcp-studio" "$DEST/Contents/MacOS/skill-mcp-studio"

# 4) 收尾：删掉仓库内的产物 .app，否则 Spotlight/Launchpad 会出现第二个图标（§3.5）
rm -rf "$NEW"
mdfind "kMDItemCFBundleIdentifier == 'io.skillmcp.studio'"   # 期望恰好 1 行
```

**权限**：`/Applications` 与 `~/.skill-mcp-studio-backups` 均在会话工作区之外，
workspace-write 沙箱下 `rm`/`ditto` 报 `Operation not permitted`，需完全访问权限。

**本次结果**：产物与安装后 sha256 均为
`e253763e449a76e8333d29e88e91f6fa5482461593f3e54188271088c784970c`（逐字节一致）；
旧版备份在 `~/.skill-mcp-studio-backups/skill-mcp-studio-0.21.0-premerge.app`。

> ⚠️ **替换本 .app 会使系统授权失效**：本机 DSH 为 ad-hoc 签名
> （`Identifier=com.deepseek.harness.local`、`Signature=adhoc`、
> `TeamIdentifier=not set`），macOS TCC 记录按 **cdhash** 绑定；新 bundle 的
> cdhash 已变 ⇒ 屏幕录制 / 辅助功能授权失效。**同类触发源与处置见 §3.3。**

**启动后自检**（`AXUIElement` 读无障碍树，比截图可靠）：

```
AXStaticText 'v0.21.0 (build 106)'     ← 版本署名
AXButton     'MCP 2'                    ← 侧栏渲染完成
AXButton     'IDE / Agent 6'            ← 8dc646e 后空壳 CLI 不再计为已装（原 7）
```

### 3.3 TCC 授权失效：**DSH 本体更新**才是更常见的触发源

2026-09-21 实测：GUI 实证验证中途，屏幕录制与辅助功能**同时**失效，且反复
「重新授权 + 重启」三轮均无效。结论记此以免重复排查。

**判据（关键：拿无关系统进程做对照）**

```bash
# 1) 进程自问是否受信任 —— 最直接的判据
python3 -c "import ApplicationServices as AS; print(AS.AXIsProcessTrusted())"

# 2) 对照：Finder / Dock 与本项目无关
#    err=-25211（kAXErrorAPIDisabled）⇒ 是「我方授权」问题，不是被测应用卡住
# 3) 屏幕录制
screencapture -x /tmp/perm.png     # 失败：could not create image from display
# 4) 交叉印证：缺屏幕录制时 kCGWindowName 被系统屏蔽为 None
```

**本次实测输出**（全部指向「授权丢失」，而非应用缺陷）：

```
AXIsProcessTrusted()   → False
AX 读 Finder / Dock    → err=-25211
screencapture          → could not create image from display
kCGWindowName          → None
DSH CDHash             → 362933c1dd01244d502a8a5c5922448b7518cfc1
DSH .app 文件时间      → 当日 10:20（当天被更新过）
```

> **不要因为 AX 读不到就把结论写成「应用卡死」**——先读 Finder/Dock 对照。
> 本次若只看被测应用，会误判为 GUI 崩溃；对照后确认是自身授权丢失。

**根因**：DSH 为 **ad-hoc 签名且无 TeamIdentifier**，macOS 无法用
identifier/TeamID 表述其身份，只能回退到 **cdhash 基准**（实测其 designated
requirement 即 `cdhash H"362933c1..."`）。于是：

- **DSH 本体每次更新（或重建/替换）cdhash 即变** ⇒ 既有 TCC 记录全部指向失效身份；
- 系统设置里的开关**看起来仍是开的**，但运行中的进程判定为未授权；
- **TCC 在进程启动时求值并缓存** ⇒ 只重启被测 `.app` 无用，必须重启 **DSH 本体**；
- ad-hoc 下反复「删记录 → 重新授权 → 重启」**不稳定**，本次三轮后仍为 `False`。

**根治手段与为何 Agent 做不了**：换稳定签名（自签证书或 Apple Development
证书）可让授权跨更新持久化，但 `codesign` 需**交互式**访问钥匙串私钥。沙箱/非
交互环境下实测**连极小文件都失败**：

```
codesign --force --sign "Apple Development: …" /tmp/testbin
  → unknown exception            （退出码 1）
codesign --force --sign - /tmp/testbin      # 对照：ad-hoc 可用
  → 退出码 0
```

> **⚠️ 更正（2026-09-29 实测）**：上面「非交互会话内 `codesign` 必然失败」的结论
> **已不成立**。本机在同样的受限会话中实测**自签证书**可非交互签名成功：
>
> ```
> codesign --force --sign "oswaldhill Local Development" <testbin>
>   → 退出码 0；DR = identifier testbin and certificate root = H"e2f6d1a5…"
> ```
>
> 当年失败的是一次 `Apple Development:` 身份。可确认的是：**「签名必须人工交互」不是
> 普遍规律**；能否非交互签名取决于该身份在钥匙串中的访问控制（ACL）是否已授权
> `codesign`、以及钥匙串是否处于解锁状态（这两点在本次与当年之间哪里不同，未逐一
> 验证，不在本文断言）。**实践结论：本仓库的 macOS 构建现默认使用自签证书，见 §3.4。**

失败与体积（1.2 G）、Electron 结构、`--deep` **均无关**——纯粹是钥匙串访问被拒。
**切勿在 Agent 会话内替换 `/Applications/DeepSeek Harness.app`**：签坏会导致 DSH
无法启动。确需根治请在**普通终端**由本人执行（会弹钥匙串授权，确认即可）：

```bash
cp -R "/Applications/DeepSeek Harness.app" /tmp/dsh-resign.app    # 1.2G，先在副本上做
codesign -d --entitlements :- "/Applications/DeepSeek Harness.app" > /tmp/dsh-ents.plist
codesign --force --deep --sign "Apple Development: <证书名>" \
  --entitlements /tmp/dsh-ents.plist /tmp/dsh-resign.app
codesign -d -r- /tmp/dsh-resign.app    # 期望 DR 不再是 cdhash，而是 identifier 基准
```

成功后先备份原件再替换，并重新授权一次，此后即可跨更新持久化。
注意 Electron 需保留原 entitlements（本机为 `allow-jit` /
`allow-unsigned-executable-memory` / `disable-library-validation`）。

**缓解**：不做重签名时，每次 DSH 更新后到「隐私与安全性」**删除旧记录**再授权。
另需明确：**授权失效只影响 Agent 读取 GUI 的能力**，不影响版本与产物核验——
`Info.plist`、二进制 sha256、CLI 自报、`CGWindowListCopyWindowInfo` 均不依赖 TCC。

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

### 3.4 自签证书签名（默认构建方式，2026-09-29 起）

**默认行为**：`cargo tauri build` 产出的 `.app` **自动由本机自签证书签名**，无需额外
参数或环境变量 —— 签名身份固化在 `tauri.conf.json`：

```json
"bundle": { "macOS": { "signingIdentity": "oswaldhill Local Development" } }
```

**为什么必须这么做**：签名身份决定 macOS 如何表述这个应用。

| | ad-hoc（改造前） | 自签证书（现在） |
|---|---|---|
| 身份表述 | 无（`Signature=adhoc`） | `Authority=oswaldhill Local Development` |
| designated requirement | `cdhash H"…"` | `identifier "io.skillmcp.studio" and certificate root = H"e2f6d1a5…"` |
| 重建之后 | **cdhash 变 ⇒ 身份变**，依赖签名的记录全部失效 | **身份不变**（同一证书下证书指纹恒定） |

ad-hoc 无 TeamIdentifier，macOS 只能用 cdhash 指认它，而 cdhash 每次重建都不同 ——
这就是「每次重建都要重新授权」的机制性根因（与 §3.3 里 DSH 自身 TCC 失效同源）。

**实测证据（2026-09-29，v0.24.1 / build 111，本机 arm64）**：

```
$ cargo tauri build
     Signing with identity "oswaldhill Local Development"   ← 构建日志，未传任何签名参数
     Finished release profile in 3m 37s                     ← 冷编译（target/ 为空）
$ codesign -dv --verbose=4 <app>
     Identifier=io.skillmcp.studio
     CodeDirectory v=20500 flags=0x10000(runtime)           ← hardened runtime 开启
     Authority=oswaldhill Local Development
     TeamIdentifier=not set
$ codesign -d -r- <app>
     designated => identifier "io.skillmcp.studio" and certificate root = H"e2f6d1a521d4e93f1f…"
$ codesign --verify --deep --strict <app>
     valid on disk / satisfies its Designated Requirement   ← 退出码 0
```

**启动实证**：`<app>/Contents/MacOS/skill-mcp-studio` 在 hardened runtime 下正常启动并持续
存活（未崩溃）。注：在受限会话（workspace-write 沙箱）里直接拉起时会打印一批 WebKit 报错
`could not create directory ~/Library/WebKit/io.skillmcp.studio/…` —— 那是**沙箱不允许写
工作区之外**所致，**不是应用缺陷**；从 Finder 正常启动不受影响。

**证书信息**（`security find-identity -v -p codesigning`）：

```
"oswaldhill Local Development"
  自签（subject == issuer），O=Local Development，有效期至 2036-09-23
  SHA-1 E2F6D1A521D4E93F1FED9A44E46508BC90BC1F2F
```

**未改变的部分**：产物**未公证**（本机无 Apple Developer ID），`spctl -a` 仍报 `rejected`、
首次打开仍需右键「打开」放行 —— 与改造前一致。本次解决的是**身份稳定性**，不是 Gatekeeper
分发问题。

**CI 不受影响**：runner 没有这张证书，`.github/workflows/build-macos.yml` 新增一步，仅在
**未配置 `APPLE_CERTIFICATE`** 时把 `APPLE_SIGNING_IDENTITY` 覆盖为 `-`（ad-hoc），与改造前
行为一致；配了正式证书的分支完全不变。依据（tauri-cli 2.11.5 源码
`src/interface/rust.rs:1467`）：**该环境变量优先于 config**。

**临时换身份 / 回到 ad-hoc / 构建前自检**：

```bash
security find-identity -v -p codesigning | grep "oswaldhill Local Development"   # 先确认证书在
APPLE_SIGNING_IDENTITY="Route Director Local Development" cargo tauri build     # 临时换证书
APPLE_SIGNING_IDENTITY=- cargo tauri build                                      # 临时回 ad-hoc
```

**换机器须知**：config 里是**证书名**，新机器若没有同名自签证书，本地构建会在签名阶段
失败。两条路：① 用「钥匙串访问 → 证书助理 → 创建证书」建同名证书（类型选「代码签名」）；
② 用 `APPLE_SIGNING_IDENTITY=-` 走 ad-hoc。**证书私钥不在仓库里，也不应进仓库。**

### 3.5 构建产物会在 Launchpad 里多出一个图标（2026-09-29 实测）

**现象**：`cargo tauri build` 在**仓库内**产出 `.app` 后，Spotlight 会索引它，于是
Launchpad 出现**第二个** `skill-mcp-studio` 图标，与 `/Applications` 里已安装的那份
重复（两者可能逐字节相同，看起来像"两个一模一样的 APP"）。

**先分清一件事**：这两个副本**未必一个好一个坏**。2026-09-29 实测两份的
`Authority` / designated requirement / 二进制 sha256 **完全一致**（都自签、都合法）。
判断"哪份是哪个"的唯一可靠办法是逐一验签，别靠图标外观：

> ⚠️ **但 sha256 相等只在「同一次构建的两份拷贝」之间成立（2026-10-10 修正）**：
> 重新构建产出的 `.app` 与上一次构建（含已安装那份）**sha256 必然不同** ——
> 原因见 §3.6，**不是缺陷**。所以「用 sha256 判断哪份是哪个」只适用于同批次产物；
> 跨构建比较 sha256 会把正常差异误判为「有东西被改坏了」。

```bash
for A in /Applications/skill-mcp-studio.app \
         "$PWD/target/release/bundle/macos/skill-mcp-studio.app"; do
  codesign -dv --verbose=4 "$A" 2>&1 | grep -E '^Authority|^TeamIdentifier'
  codesign -d -r- "$A" 2>&1 | tail -1
  shasum -a 256 "$A/Contents/MacOS/skill-mcp-studio"
done
```

**为何常规"注销注册"不管用（都实测过，别再白试）**：

| 尝试 | 结果 |
|------|------|
| `lsregister -u <产物路径>` | 返回 0，但**记录立刻回来** —— Spotlight 索引仍持有该路径，索引器会重新登记 |
| 临时把 `.app` 移出 → `-u` → 移回 | 同样无条件回来（移回后重新索引） |
| `mdutil -i off <产物目录>` | `Error: invalid operation / unknown indexing state`（该工具只认卷，不认目录） |
| 产物目录放 `.metadata_never_index` | 对**已被索引的既有路径**未生效（是否对新生成文件生效，本次未验证） |

**有效处置（二选一）**：

1. **删掉产物里的 `.app`**（本次采用，最直接）：位置不存在的 LS 记录**不会**渲染成图标
   —— 证据是 LS 库里至今还躺着一条指向**已卸载** `/Volumes/skill-mcp-studio` 的陈年记录，
   而它并没有多给你一个图标。删前用 §3.4 的 sha256 确认 DMG 里已存有同一份。
   > ⚠️ **关键补充（2026-10-10 实测）**：删 `.app` 是**每次构建后都要重做**的一步 ——
   > 任何一次 `cargo tauri build` 都会把产物 `.app` 重新写回 `target/`，于是第二个图标
   > 又出现。本次一晚内即复现：删除 → 回归重建 → 图标再次出现。若不想每次都清理，
   > 就该选下面第 2 条（一次性、永久生效）。
   >
   > **验收判据（可直接复制断言）**：
   > ```bash
   > # 期望恰好输出 1 行，且是 /Applications/...
   > mdfind "kMDItemCFBundleIdentifier == 'io.skillmcp.studio'"
   > # 期望 COUNT = 1
   > mdfind "kMDItemCFBundleIdentifier == 'io.skillmcp.studio'" | wc -l
   > ```
   > 另注：删掉路径后，**LS 库里可能仍留着指向它的陈旧记录**（本次实测 `-dump` 里
   > 仍有该路径，`lsregister -u <路径>` 与 `-gc` 都没清掉它）。这不是问题 ——
   > **位置不存在的记录不会渲染成图标**（同上「已卸载卷」证据）。本次实测 LS 库共 5 条
   > `skill-mcp-studio.app` 记录，其中 4 条指向不存在的路径（`.cache/sms-cargo-target`、
   > 产物目录、两个已卸载的 `/Volumes/*`），只有 `/Applications` 那条是活的，
   > 而 Spotlight 查询结果为 **1**。**判据是 Spotlight 查询计数，不是 LS 记录条数。**
2. **把 `src-tauri/target` 加进 Spotlight 的排除列表**：macOS 27 上的准确路径是
   「系统设置 → Spotlight → **被排除的位置**（英文 *Excluded Locations*）→ 添加要排除的文件夹或磁盘」。
   注意它**不是左侧的独立菜单项**，而是 Spotlight 面板内往下滚到底部的区块。
   > 旧版 macOS 该入口叫「搜索隐私…」（`Spotlight.prefPane`），本文档初稿沿用了旧叫法，
   > 在 macOS 27 上找不到——2026-09-29 由用户指出并更正。

   一次操作、永久生效，
   产物原地保留。注意该隐私列表落在 `/.Spotlight-V100/VolumeConfiguration.plist`，
   **脚本化写入需 root**，所以这一步交给人在 GUI 里做，本仓库不自动化。

> 顺带一条与图标无关但会一起冒出来的残留：LS 库里可能挂着**旧的 dmg 临时工作映像**
> （本次见到 `rw.<pid>.skill-mcp-studio_0.22.0_arm64.dmg` 的引用，该文件早已不存在）。
> 它不影响功能，`lsregister -kill -r` 重建库可清，但那会全量重扫，代价不值得。

### 3.6 构建可复现性：载荷可复现，**签名使整个 bundle 每次不同**（2026-10-10 实测）

**现象**：同一棵树、不改任何源码，连续 `cargo tauri build` 产出的二进制 sha256 **每次都不同**：

```
build #1 (20:06, 已安装)  7d9028760e70871a543f362031058811aa13b21dafdb81821e9193ecef8f8bb7
build #2                  4b5d7e98084a385d9575d0d8c9c5264c4aad4cd93b4d510e480be9dd192199ab
build #3                  4175f10b0462878b4d310c364b67e318e299785c84abddbf228cf9af71419ffe
build #4                  8c7af712fbf84e0f02075b1763920493c8731891dd3562ae422cd2b1c1c756f0
```

**根因**：差异**只在代码签名块**，不在编译产物。

```bash
codesign -d --verbose=4 <app> | grep "Signed Time"   # → Signed Time=Oct 10, 2026 at 20:06:20
```

自签证书的 CMS 签名内嵌**签名时间**，因此每次签名的字节都不同。验证办法（两次构建各剥签名后比对）：

```bash
codesign --remove-signature "$BIN" && shasum -a 256 "$BIN"
# build #4 →  40e613b07be08e05901319aa1f9057ed92b8df298902ee29b4311f4f2ca0ca1a
# build #5 →  40e613b07be08e05901319aa1f9057ed92b8df298902ee29b4311f4f2ca0ca1a   ← 逐字节相同
```

**实践结论**：

1. **载荷（剥离签名后）是逐字节可复现的**；`cargo`/`rustc`/链接器不引入不确定性。
2. **不要跨构建比较 sha256**。§3.2 的「安装后二进制 sha256 必须与产物一致」是**同一次
   构建内**的校验（验证 `ditto` 没损坏文件），不是「重建应与已装版本一致」的断言。
3. **CDHash 也随签名而变**（本次 #3 与 #4 的 CDHash 巧合相同 `3d13ad6b…`，但两次的
   签名字节仍不同）—— 所以**依赖 CDHash 的 TCC 授权在 ad-hoc 下每次重建都会失效**，
   这正是 §3.4 改用自签证书（以证书指纹为 designated requirement）的理由。

> ⚠️ 上文用 `codesign --remove-signature` 只是为了**测量载荷**；它会破坏该产物的签名。
> 测完请重新 `cargo tauri build`（或删除该产物）。**不要把剥签名的产物装到 `/Applications`。**

### 3.7 构建环境回归记录（2026-10-10 · develop @ e9e555f · v0.25.0 build 112）

本机全量回归，结论：**Python / JS / Rust / 打包 / 签名 / 一致性 / UI 规范门禁全部通过**。

| 判据（与 CI 同） | 命令 | 结果 |
| --- | --- | --- |
| Python 单元测试 | `python -m unittest discover -s tests -p 'test_*.py'` | ✅ **1088 passed, skipped=2**（= CI 基线） |
| CI 等价总闸 | `scripts/ci_parity.sh` | ✅ 退出码 0（含文本卫生/脚本卫生/密钥扫描/ruff/cargo test/JS） |
| ruff 静态检查 | `ruff check core tests scan.py scripts setup.py` | ✅ 0.16.9，无诊断 |
| JS 单元测试 | `node --test tests/gui_helpers.test.mjs` | ✅ 5 passed / 0 failed |
| Rust 单元测试 | `cargo test`（src-tauri） | ✅ 12 passed |
| UI 规范门禁 | `tests.test_design_spec tests.test_dashboard_design_tokens tests.test_design_spec_contract` | ✅ 50 passed |
| 构建 + 签名 | `cargo tauri build` | ✅ 0，1m12s（冷）／19s（热） |
| 签名校验 | `codesign --verify --deep --strict` | ✅ 0，DR = 证书指纹基准（跨重建稳定） |
| GUI/CLI 一致性（DOD） | `scripts/verify_gui_consistency.sh -c config.yaml` | ✅ 2 profiles / 2 results 全一致 |
| 安装核验 | `ditto` → `/Applications` + sha256 比对 | ✅ 逐字节一致，0.25.0 可启动 |
| Spotlight 唯一性 | `mdfind "kMDItemCFBundleIdentifier == 'io.skillmcp.studio'"` | ✅ 恰好 1 条 |

本次回归发现的四处盲区，**均已修复**（不只是记录）：

| # | 盲区 | 修复 |
| --- | --- | --- |
| 1 | §1.1 受限会话能否构建，取决于 Cargo.lock 是否变动（初次误判为「沙箱内一律不能构建」） | 文档写明分水岭与判据（先看 Cargo.lock 有没有变），并记录三条同类边界 |
| 2 | §1.2 漏装 ruff 时 `ci_parity.sh` **在测试之前退出**，输出被误读成「测试失败」 | **改脚本**：失败累加 + 末尾统一汇总；实测强制 ruff 缺失时 1088 用例仍跑完且 `exit=1` |
| 3 | §1.2 初稿误称「脚本不校验 node 版本」 | **改文档**：脚本本就有 Q1-1 主版本比对（实测会告警）；补记误判来源（只看 `tail` 没看全量输出） |
| 4 | §3.6 跨构建 sha256 不可比，而 §3.2/§3.5 的措辞读起来像「必须相等」 | **改文档**：§3.2 补「只比本次构建产物」注释并加入「删产物 .app」收尾步；§3.5 增加修正说明与可复制的验收判据 |

盲区 2 另加**回归护栏** [`tests/test_ci_parity_gate.py`](../tests/test_ci_parity_gate.py)
（6 例）：静态断言「ruff 段到 unittest 调用之间不得出现可执行行提前退出」，
并交叉校验脚本的 `CI_PATTERN` / `CI_NODE_MAJOR` 与 `.github/workflows/test.yml`
实际钉定的值一致 —— 后者防的是「CI 改了 node 版本、脚本里的对比基线没跟着改，
告警从此指向错误版本」。

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

## 7. 平台产物与依赖说明（B-9 定案）

- **arm64（Windows/Linux）**：当前仅产出 `x86_64`（macOS 已 universal）。
  Windows ARM64（`aarch64-pc-windows-msvc`）与 Linux ARM64（`aarch64-unknown-linux-gnu`）
  按需立项——有真实用户诉求后再加 matrix（Linux 侧可用 QEMU/`buildjet` 大幅减慢构建，
  见 [Tauri v2 Debian 交叉编译](https://v2.tauri.app/distribute/debian/)）。当前不默认产出。
- **Linux 运行时依赖**：`deb`/`rpm` 由 Tauri v2 打包器自动注入 `libwebkit2gtk-4.1-0`、
  `libgtk-3-0`（及系统托盘场景的 appindicator），构建侧已显式安装对应 `-dev` 头文件
  （`build-linux.yml` 的 `libwebkit2gtk-4.1-dev`/`libgtk-3-dev`/`libayatana-appindicator3-dev`）。
  **AppImage** 默认不自带 WebKitGTK（Tauri v2 `bundleMediaFramework` 默认关），运行时依赖
  目标机已装 `libwebkit2gtk-4.1-0`；如需完全自带可开 `bundle.linux.appimage.bundleMediaFramework`
  （体积显著增大），当前遵循 Tauri 默认值，不在配置里额外声明。
