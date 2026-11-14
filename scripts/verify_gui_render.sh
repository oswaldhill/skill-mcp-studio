#!/usr/bin/env bash
# GUI 验收（不依赖辅助功能 / AX 授权）
#
# 背景：本机 `osascript` 未获「辅助功能」授权，读任何应用的 UI 元素都返回
#   -1719 / -1728（连 Finder 的窗口名都读不到），因此基于 System Events 的
#   GUI 断言在本机一律不可用。这是**验收手段**受限，不是应用缺陷。
#
# 本脚本改用仓库自带的 WKWebView 离屏渲染（tools/shot_dialog.swift），
# 不需要任何 TCC 授权，且能回答「元素是否真正可见」——比 AX 更严格：
# DOM 里存在 ≠ 屏幕上可见（本项目两个真实缺陷都属于此类，见 tools/README.md）。
#
# 用法：
#   scripts/verify_gui_render.sh [--size 1400x900] [--out 输出目录]
#
# 判据：MEASURE 行必须出现、截图必须写出、页面不得留下 0x0 的顶层弹框。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIZE="1400x900"
OUT="/tmp/sms-gui-render"
WAIT="6"

while [ $# -gt 0 ]; do
  case "$1" in
    --size) SIZE="${2:?--size 缺少取值}"; shift 2 ;;
    --out)  OUT="${2:?--out 缺少取值}"; shift 2 ;;
    --wait) WAIT="${2:?--wait 缺少取值}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "未识别的参数 $1" >&2; exit 64 ;;
  esac
done

command -v swift >/dev/null 2>&1 || { echo "✗ 需要 swift（Xcode Command Line Tools）" >&2; exit 2; }
mkdir -p "$OUT"

echo "== 1) 前端产物与源文件同步 =="
if ! python3 "$ROOT/scripts/build_gui.py" --check >/dev/null 2>&1; then
  echo "✗ gui/dist 与源文件不同步，先运行 python3 scripts/build_gui.py" >&2
  exit 1
fi
echo "✓ gui/dist 已同步"

echo "== 2) 离屏渲染并测量可见性 =="
PNG="$OUT/dashboard-${SIZE}.png"
LOG="$(swift "$ROOT/tools/shot_dialog.swift" "$ROOT/gui/dist/dashboard.html" "$PNG" \
        --wait "$WAIT" --size "$SIZE" 2>&1)"
echo "$LOG" | sed 's/^/   /'

if ! echo "$LOG" | grep -q "^MEASURE:"; then
  echo "✗ 未产生 MEASURE 行（页面可能未加载完成）" >&2
  exit 1
fi
if ! echo "$LOG" | grep -q "^SNAP ok"; then
  echo "✗ 截图未写出" >&2
  exit 1
fi

echo "== 3) 应用自身错误检查 =="
# 只统计 Tauri/webview 相关的错误，忽略 macOS 系统服务噪音
if echo "$LOG" | grep -qiE "uncaught|referenceerror|typeerror|syntaxerror"; then
  echo "✗ 页面存在未捕获的 JS 错误：" >&2
  echo "$LOG" | grep -iE "uncaught|referenceerror|typeerror|syntaxerror" | head -5 | sed 's/^/   /' >&2
  exit 1
fi
echo "✓ 无未捕获 JS 错误"

echo
echo "==> 通过：截图 $PNG"
echo "    提示：本机 AX 不可用时，请以此脚本的结果作为 GUI 验收依据。"
