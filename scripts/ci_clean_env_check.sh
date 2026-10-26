#!/usr/bin/env bash
# 干净环境自检：模拟 GitHub Actions 的「无本机技能目录 / 无用户数据」环境跑全量单测。
#
# 为什么需要它：2026-10-23 CI 上 Python unit tests 失败，本地却全绿——
# 3 个 execute_plan 测试依赖了本机真实存在的 ~/.skills-manager/skills/<name>
# 目录（execute_plan 内会调 verify_installed 读文件系统）。本机有目录所以过，
# CI 干净环境没有所以挂。这类「本地过、CI 挂」只有换一个空 HOME 才暴露得出来。
#
# 做法：用临时 HOME 跑测试，但显式保留原 site-packages 搜索路径——否则连
# PyYAML / certifi 都会因 HOME 变化而 import 失败，测出的失败与产品无关。
#
# 用法：bash scripts/ci_clean_env_check.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 解释器选择：优先 PYTHON 环境变量（调用方 scripts/ci_parity.sh 会把它选定的
# 解释器传下来），否则退回裸 python3。选定后必须校验版本 —— 低于 3.11 时用例会
# 因语法/typing 不支持而整批导入失败，报出几十条 _FailedTest，极易被误读成
# 「干净环境自检失败」这个产品结论。2026-10-26 实测：PATH 被收窄后落到
# /usr/bin/python3（3.9.6），正是这种假阳性。
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "✗ 找不到解释器（PYTHON=${PY}），可用 PYTHON=... 指定" >&2
  exit 1
fi
if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)'; then
  echo "✗ 解释器版本过低：$("$PY" --version 2>&1) < 3.11（CI 用 3.11）" >&2
  echo "  低版本会以与产品无关的原因整批导入失败，请用 PYTHON=... 指定 >= 3.11 的解释器。" >&2
  exit 1
fi

TMP_HOME="$(mktemp -d)"
cleanup() { rm -rf "$TMP_HOME"; }
trap cleanup EXIT

# 只保留包搜索路径，不保留原 HOME 下的用户数据（技能库、lock、data/ 等）
SITE_PATH="$("$PY" - <<'PYCODE'
import sys
print(":".join(p for p in sys.path if p and ("site-packages" in p or "dist-packages" in p)))
PYCODE
)"

echo "==> 干净环境自检（临时 HOME=${TMP_HOME}）"
# 用 tee 保留完整输出，失败时把尾部打出来（否则管道吞掉退出码）
LOG="$(mktemp)"
set +e
HOME="$TMP_HOME" PYTHONPATH="$SITE_PATH" \
  "$PY" -m unittest discover -s tests -p 'test_*.py' > "$LOG" 2>&1
CODE=$?
set -e
grep -E '^(FAIL|ERROR):' "$LOG" || true
grep -E '^Ran |^OK|^FAILED' "$LOG" | tail -2
rm -f "$LOG"

if [ "$CODE" -ne 0 ]; then
  echo "==> 干净环境自检未通过：存在依赖本机用户数据的测试（CI 上会挂）" >&2
  exit "$CODE"
fi
echo "==> 干净环境自检通过"
