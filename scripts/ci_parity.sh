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
CI_BASELINE_SKIPPED=2

PY="${PYTHON:-python3}"

note() { printf '%s\n' "$*"; }

note "== CI 等价基线检查 =="

# 1) Python 解释器
if ! command -v "$PY" >/dev/null 2>&1; then
  note "✗ 找不到解释器 '$PY'（可用 PYTHON=... 指定）"
  exit 1
fi
note "✓ Python  $("$PY" --version 2>&1)  [$(command -v "$PY")]"

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
if "$PY" -c 'import yaml' >/dev/null 2>&1; then
  note "✓ PyYAML"
else
  note "✗ 缺少 PyYAML（$PY -m pip install PyYAML）"
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
  note "==> 失败（exit=$rc）"
  exit "$rc"
fi

if [ -z "$skipped" ]; then
  note "==> 通过，但未能从汇总行解析 skipped 数"
  exit 0
fi

if [ "$skipped" -eq "$CI_BASELINE_SKIPPED" ]; then
  note "==> 通过，skipped=$skipped，与 CI 基线一致"
  exit 0
fi

note "==> 通过，但 skipped=$skipped ≠ CI 基线 $CI_BASELINE_SKIPPED"
note "    多出的 skip 表示有用例没真正执行，本地结论不足以代表 CI。"
note "    最常见原因：node 不在 PATH（见上），或缺少可选依赖。"
exit 0
