#!/usr/bin/env bash
# 以「与 CI 等价」的条件运行 Python 单元测试。
#
# 为什么需要它：约 35 个「渲染护栏」用例依赖 node，找不到 node 时它们会
# skip 而不是 failed —— 于是会出现「本地全绿、CI 变红」。CI runner 上 node
# 在 PATH 中，本地非登录 shell 却常把 Homebrew 前缀（/opt/homebrew/bin）
# 排除在外，于是本地静默少跑 35 个用例。
#
# 本脚本先确认前置条件，再用与 .github/workflows/test.yml 完全相同的命令
# 运行，并把 skipped 数与 CI 基线（2）对照，避免再次出现上述盲区。
#
# 用法:
#   scripts/ci_parity.sh                # 跑全部单元测试
#   scripts/ci_parity.sh -v             # 额外参数透传给 unittest
#   PYTHON=python3.11 scripts/ci_parity.sh

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CI_PATTERN='test_*.py'
# CI 基线：CI 上稳定出现的 skip 数。
# 允许用环境变量覆盖 —— CI 侧若新增/移除可选依赖，skip 数会变化，
# 硬编码会让本脚本对「正确的结果」误报不一致，退化成噪音源。
# Q2-2：基线 2 对应下面这两条「与环境耦合」的可选用例（避免后人看到 skipped=3 无从判断）：
#   1) test_combined_checker.CombinedCheckerTest.test_dsh_installed_via_config_evidence
#      —— 本机无 ~/.dsh 配置证据时跳过（T-6 环境耦合）
#   2) test_stdio_probe 中依赖外部 MCP stdio 可执行文件的用例
# 若你机器上实际 skipped 与此不同，先确认是不是新增了环境耦合用例，再改这个值。
CI_BASELINE_SKIPPED="${CI_BASELINE_SKIPPED:-2}"

PY="${PYTHON:-python3}"

note() { printf '%s\n' "$*"; }

note "== CI 等价基线检查 =="

# 1) Python 解释器
if ! command -v "$PY" >/dev/null 2>&1; then
  note "✗ 找不到解释器 '$PY'（可用 PYTHON=... 指定）"
  exit 1
fi
note "✓ Python  $("$PY" --version 2>&1)  [$(command -v "$PY")]"

# 1b) 解释器版本 —— CI 固定 3.11，项目要求 >=3.11。
#     版本不符时测试会以与代码无关的原因失败，必须先拦下来并说清原因。
if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)'; then
  note "✗ 解释器版本过低：$("$PY" --version 2>&1) < 3.11"
  note "  CI 用的是 Python 3.11，低版本会以与代码无关的原因失败。"
  for cand in /opt/homebrew/opt/python@3.11/bin/python3.11 /opt/homebrew/bin/python3.11; do
    if [ -x "$cand" ]; then
      note "  → 发现 ${cand}，本次运行改用它"
      PY="$cand"
      break
    fi
  done
  if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)'; then
    note "  请安装 Python >= 3.11 后重试（或用 PYTHON=... 指定）"
    exit 1
  fi
  note "✓ Python  $("$PY" --version 2>&1)  [$(command -v "$PY")]  （已回退到 3.11）"
fi

# 2a) cargo —— 本地门禁要跑 cargo test（Q0-5）。rustup 默认装在 ~/.cargo/bin，
#     非交互式 shell 里通常不在 PATH。
if ! command -v cargo >/dev/null 2>&1 && [ -x "$HOME/.cargo/bin/cargo" ]; then
  note "· 发现 $HOME/.cargo/bin/cargo，本次运行临时并入 PATH"
  PATH="$HOME/.cargo/bin:$PATH"
  export PATH
fi

# 2) node —— 缺失会让约 35 个渲染护栏用例静默跳过
if ! command -v node >/dev/null 2>&1; then
  note "✗ node 不在 PATH —— 渲染护栏用例会被跳过，本地结论将与 CI 不等价"
  for cand in /opt/homebrew/bin /usr/local/bin; do
    if [ -x "$cand/node" ]; then
      note "  → 发现 $cand/node，本次运行临时并入 PATH"
      PATH="$cand:$PATH"
      export PATH
      break
    fi
  done
  if ! command -v node >/dev/null 2>&1; then
    note "  请先安装 node 后重试"
    exit 1
  fi
fi
note "✓ node    $(node --version 2>&1)  [$(command -v node)]"

# 3) 运行时依赖（缺失时相关用例同样会 skip）
# Q0-6：缺依赖必须**硬失败**。此前只打一行 ✗ 就继续跑 —— 相关用例会 skip，
# 于是「本地全绿」并不代表 CI 全绿，而脚本头部却宣称「与 CI 等价」。
if "$PY" -c 'import yaml' >/dev/null 2>&1; then
  note "✓ PyYAML"
else
  note "✗ 缺少 PyYAML —— 相关用例会 skip，本地结论无法代表 CI"
  note "  安装：$PY -m pip install PyYAML"
  note ""
  note "==> 失败：依赖不满足（Q0-6）。本脚本的用途是复现 CI 结论，缺依赖时必须停下。"
  exit 1
fi

# 1c) 脚本卫生自检（P2-18）—— 这两条都是「会伪装成测试失败」的缺陷，必须前置拦截。
# 背景：用 qclaw-text-file 的 write_text.py 重写脚本时不继承权限，可执行位丢失后
# bash 直接执行仍正常、但 Python subprocess 调用会 PermissionError，
# 表现为 exit!=0 且日志里没有任何 "Ran N tests" 行，极易被误判为测试失败。
hygiene_fail=0

if [ -d .git ]; then
  bad_mode="$(git ls-files -s -- 'scripts/*.sh' 2>/dev/null | awk '$1 != "100755" {print $4}')"
  if [ -n "$bad_mode" ]; then
    note "✗ scripts/*.sh 缺少可执行位（git mode 应为 100755）："
    printf '    %s\n' $bad_mode
    note "  → 修复：chmod +x <file> && git add <file>"
    hygiene_fail=1
  else
    note "✓ scripts/*.sh 的 git mode 均为 100755"
  fi
fi

# 变量名紧跟全角标点：bash 在部分 locale 下会把标点首字节并入变量名，
# 配合 set -u 直接 "unbound variable" 中止脚本。必须写成 ${var}。
bad_var="$(
  grep -nE '\$[A-Za-z_][A-Za-z_0-9]*[，。：；（）「」、！？]' scripts/*.sh 2>/dev/null \
    | grep -v '\${' || true
)"
if [ -n "$bad_var" ]; then
  note "✗ scripts/*.sh 存在「\$var 紧跟全角标点」写法（须写 \${var}）："
  printf '    %s\n' "$bad_var"
  hygiene_fail=1
else
  note "✓ scripts/*.sh 无「\$var 紧跟全角标点」写法"
fi

# hook 生效性自检（P0-6）——「门禁配了但不可执行」= 静默失效，最危险的一类。
# 背景：git 对**不可执行**的 hook 会**静默跳过**，既不报错也不提示。
# 本仓库用 core.hooksPath=scripts/git-hooks 提供禁推门禁，而该文件 git mode 为
# 100644（可执行位由 install-hooks.sh 的 chmod +x 赋予）—— 一旦没跑过安装脚本
# 或权限被覆盖，禁推门禁就形同不存在，且没有任何迹象。实际发生过一次。
# 只在本地生效：core.hooksPath 是本地 git config，CI 上不存在，故不影响 CI。
if [ -d .git ]; then
  hooks_path="$(git config --get core.hooksPath 2>/dev/null || true)"
  if [ -z "$hooks_path" ]; then
    note "· 未启用仓库内 git hooks（core.hooksPath 未设置），跳过生效性检查"
    note "  如需启用：bash scripts/install-hooks.sh"
  else
    case "$hooks_path" in
      /*) hooks_dir="$hooks_path" ;;
      *)  hooks_dir="$ROOT/$hooks_path" ;;
    esac
    if [ ! -d "$hooks_dir" ]; then
      note "✗ core.hooksPath 指向的目录不存在，门禁不会生效：$hooks_dir"
      note "  → 修复：bash scripts/install-hooks.sh"
      hygiene_fail=1
    else
      bad_hooks=""
      for h in "$hooks_dir"/*; do
        [ -f "$h" ] || continue
        [ -x "$h" ] || bad_hooks="$bad_hooks $h"
      done
      if [ -n "$bad_hooks" ]; then
        note "✗ core.hooksPath 下的 hook 缺少可执行位 —— git 会静默跳过，门禁等于未生效："
        printf '    %s\n' $bad_hooks
        note "  → 修复：bash scripts/install-hooks.sh"
        hygiene_fail=1
      else
        note "✓ core.hooksPath=$hooks_path 下的 hook 均可执行（门禁生效）"
      fi
    fi
  fi
fi

if [ "$hygiene_fail" -ne 0 ]; then
  note ""
  note "==> 失败：脚本卫生自检未通过（P2-18 / P0-6）。此类缺陷会伪装成「测试失败」或「门禁本不存在」，故在跑测试前拦截。"
  exit 1
fi


# 1d) 文本卫生自检（P2-17 / P2-14）—— 与 CI 的 text-hygiene job 等价。
#     之所以放进本脚本：此前该检查只存在于 CI workflow，本地 ci_parity.sh 跑不到，
#     于是「本地全绿」与「CI 拦下」之间存在盲区 —— 实际发生过一次：
#     P2-16 拆分产出的 6 个模块末尾多出空行，本地门禁全绿而无人发现。
#     判据比 CI 更严一格：不仅要求「有末尾换行」，还要求「恰好一个」
#     （末尾空行会让 diff 与后续追加都产生噪音）。
note "== 文本卫生自检（P2-17 / P2-14）=="
if ! "$PY" - <<'INNER'
import subprocess, sys

SKIP_SUFFIX = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".icns",
    ".pdf", ".zip", ".gz", ".woff", ".woff2", ".ttf", ".otf",
    ".dmg", ".exe", ".msi", ".deb", ".rpm", ".so", ".dylib",
)
files = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split()
problems, checked = [], 0
for f in files:
    if f.lower().endswith(SKIP_SUFFIX):
        continue
    try:
        raw = open(f, "rb").read()
    except OSError:
        continue
    if b"\x00" in raw[:8000]:
        continue
    checked += 1
    if raw.startswith(b"\xef\xbb\xbf"):
        problems.append(f + ": 含 UTF-8 BOM")
    if b"\r\n" in raw:
        problems.append(f + ": 含 CRLF（本仓库统一 LF）")
    if not raw.endswith(b"\n"):
        problems.append(f + ": 末尾缺少换行")
    elif raw.endswith(b"\n\n"):
        problems.append(f + ": 末尾多余空行（应恰好一个换行）")
print("  检查了 " + str(checked) + " 个文本文件")
if problems:
    print("发现以下问题：", file=sys.stderr)
    for x in problems:
        print("  - " + x, file=sys.stderr)
    sys.exit(1)
INNER
then
  note "==> 失败：文本卫生自检未通过（P2-17 / P2-14）。"
  note "    修法：补齐/去掉末尾换行，或去掉 BOM、把 CRLF 转为 LF。"
  exit 1
fi
note "✓ 文本文件：无 BOM、无 CRLF、末尾恰好一个换行"

note ""
# 1e) ruff 静态检查（P1-11）——与 CI 的 lint-ruff job 同判据、同路径。
#     为什么放进本脚本：此前 ruff 只存在于 CI workflow，本地跑不到；
#     而本仓库只做本地提交、从不推送 → CI 从未运行 → **ruff 实际从未被强制过**。
#     与 P2-17（文本卫生只在 CI）是同一类盲区，这里一并补上。
#     版本刻意与 CI 锁一致：ruff 的诊断集合随版本变化，不锁会让两边结论漂移。
RUFF_VERSION="0.16.9"
note "== ruff 静态检查（P1-11，ruff==${RUFF_VERSION}）=="
RUFF_BIN=""
if command -v ruff >/dev/null 2>&1; then
  RUFF_BIN="$(command -v ruff)"
elif [ -x .venv/bin/ruff ]; then
  # 项目内 venv 是贡献者的标准位置（.venv/ 已在 .gitignore 中）。
  # 此前这里找的是 /tmp/p05/venv/bin/ruff 这种个人临时目录 —— 换台机器即失效（Q0-3）。
  RUFF_BIN=".venv/bin/ruff"
elif [ -x /opt/homebrew/bin/ruff ]; then
  RUFF_BIN="/opt/homebrew/bin/ruff"
elif "$PY" -m ruff --version >/dev/null 2>&1; then
  RUFF_BIN="$PY -m ruff"
fi
if [ -z "$RUFF_BIN" ]; then
  # 原注释写「本地缺此步不会让结论与 CI 相反」—— 这句是错的：lint 有错时
  # 本地绿、CI 红，正是 P1-11 要根治的盲区。缺 ruff 必须硬失败。
  note "✗ 未找到 ruff —— 静态检查无法执行，本地结论不能代表 CI"
  note "  安装：$PY -m pip install \"ruff==${RUFF_VERSION}\""
  note ""
  note "==> 失败：ruff 不可用（Q0-6）。"
  exit 1
else
  have="$($RUFF_BIN --version 2>&1 | awk '{print $2}')"
  if [ "$have" != "$RUFF_VERSION" ]; then
    note "  ⚠ ruff 版本为 ${have}，CI 锁的是 ${RUFF_VERSION} —— 诊断集合可能不同"
  fi
  if ! $RUFF_BIN check core tests scan.py scripts setup.py; then
    note ""
    note "==> 失败：ruff 静态检查未通过（P1-11）。CI 的 lint-ruff 会用同一命令拦下。"
    exit 1
  fi
  note "✓ ruff check 通过（$(printf '%s' "$RUFF_BIN")）"
fi
note ""

# 1f) JS 用例（T-3）——与 CI 的 test-js job 同命令。
#     这是第三处「只在 CI 生效」的检查：node 本地可用（上面已自动并入 PATH），
#     命令 `node --test tests/gui_helpers.test.mjs` 本地完全可跑，却从未被本脚本执行。
#     它测的是 gui/dashboard.html 内联脚本的纯函数（escapeHtml/stripAnsi/
#     cliErrDetail/cliFailLines/dotFor）—— 恰好是 GUI 改动最容易碰坏的地方。
note "== JS 用例（T-3，node --test）=="
# Q1-1：本地 node 主版本与 CI 不一致时必须显式告警。
# `node --test` 在 node 20 与 26 上并非完全等价（报告格式与部分 API 行为跨大版本有变化），
# 而 T-3 是 GUI 纯函数（escapeHtml/stripAnsi 等）的主要防线 —— 不告警就会出现
# 「本地绿不保证 CI 绿，反之亦然」而无人察觉。
CI_NODE_MAJOR=20
LOCAL_NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo '')"
if [ -n "$LOCAL_NODE_MAJOR" ] && [ "$LOCAL_NODE_MAJOR" != "$CI_NODE_MAJOR" ]; then
  note "  ⚠ node 主版本不一致：本地 v$LOCAL_NODE_MAJOR vs CI v$CI_NODE_MAJOR"
  note "    node --test 跨大版本的报告格式/API 行为有差异，本地结论未必等价于 CI。"
fi
if ! command -v node >/dev/null 2>&1; then
  note "  ⚠ node 不在 PATH，跳过 JS 用例（上面已尝试并入 /opt/homebrew/bin）"
elif [ ! -f tests/gui_helpers.test.mjs ]; then
  note "  ⚠ 找不到 tests/gui_helpers.test.mjs，跳过"
else
  if ! node --test tests/gui_helpers.test.mjs; then
    note ""
    note "==> 失败：JS 用例未通过（T-3）。CI 的 test-js 会用同一命令拦下。"
    exit 1
  fi
  note "✓ node --test tests/gui_helpers.test.mjs 通过"
fi
note ""

note ""
# 1g) Rust 单元测试（Q0-5）—— 与 CI 的 test-rust job 同命令。
#     此前本地门禁完全没有 cargo，而脚本头部宣称「与 CI 等价」：
#     lib.rs 的 run_cli/open_url 安全边界回归在本地永远看不见（本地绿、CI 红）。
note "== Rust 单元测试（Q0-5，CI test-rust 同命令）=="
if ! command -v cargo >/dev/null 2>&1; then
  note "  ⚠ 未找到 cargo，跳过 cargo test —— 本次结果**不含** Rust 侧（lib.rs）"
  note "     这是覆盖缺口，不是通过：CI 的 test-rust 仍会跑。"
  note "     安装 Rust：https://rustup.rs"
else
  if ! (cd src-tauri && cargo test --quiet); then
    note ""
    note "==> 失败：cargo test 未通过（Q0-5）。CI 的 test-rust 会用同一命令拦下。"
    exit 1
  fi
  note "✓ cargo test 通过（src-tauri）"
fi
note ""

note "== 运行（命令与 .github/workflows/test.yml 一致）=="
note "   $PY -m unittest discover -s tests -p '$CI_PATTERN' $*"
note ""

out="$("$PY" -m unittest discover -s tests -p "$CI_PATTERN" "$@" 2>&1)"
rc=$?
printf '%s\n' "$out" | tail -n 15

skipped="$(printf '%s\n' "$out" | sed -n 's/.*skipped=\([0-9][0-9]*\)).*/\1/p' | tail -n 1)"

note ""
if [ "$rc" -ne 0 ]; then
  note "==> 失败（exit=${rc}）"
  exit "$rc"
fi

if [ -z "$skipped" ]; then
  note "==> 通过，但未能从汇总行解析 skipped 数"
  exit 0
fi

if [ "$skipped" -eq "$CI_BASELINE_SKIPPED" ]; then
  note "==> 通过，skipped=${skipped}，与 CI 基线一致"
  exit 0
fi

note "==> skipped=$skipped ≠ CI 基线 $CI_BASELINE_SKIPPED"
note "    多出的 skip 表示有用例没真正执行，本地结论不足以代表 CI。"
note "    最常见原因：node 不在 PATH（见上），或缺少可选依赖。"
if [ "${CI_ALLOW_SKIP_DRIFT:-}" = "1" ]; then
  note "    CI_ALLOW_SKIP_DRIFT=1 已显式豁免，按通过处理。"
  exit 0
fi
note "    Q0-6：这一不一致本身就是失败信号（此前仍以 0 退出）。"
note "    确认无碍时用 CI_ALLOW_SKIP_DRIFT=1 显式豁免。"
exit 1
