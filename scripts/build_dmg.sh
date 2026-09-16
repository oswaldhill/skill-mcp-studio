#!/usr/bin/env bash
# .dmg 出包脚本（阶段三 · macOS 安装映像出口，2026-09-05 增设）。
#
# 背景：tauri 内置 `cargo tauri build --bundles dmg` 调用 bundle_dmg.sh 时，
# 以「相对输出名 + CWD=bundle/macos」方式传参，使 `rw.$$.<name>.dmg` 临时工作
# 映像落入**源目录**（脚本第 313-316 行：DMG_TEMP_NAME 取 dirname(输出)）；
# 随后 `hdiutil create -srcfolder` 把源目录内容拷入映像时递归包含该正在写入
# 的临时映像自身，报「设备上无剩余空间」而失败（2026-09-05 三次复现实锤；
# 此前被误判为「系统磁盘映像权限限制」，实为沙箱权限 + 本缺陷叠加）。
#
# 本脚本修复：输出用绝对路径（临时映像落在 bundle/dmg/，不入源目录）、
# 先清理源目录残留与陈旧挂载，复用 tauri 生成的 bundle_dmg.sh（带窗口布局）；
# 若该脚本不存在（纯 `--bundles app` 构建），退化为纯 `hdiutil` 直出
# （含 Applications 拖拽快捷方式，无自定义窗口布局）。
#
# 前置：已执行 `cargo tauri build`（或 `npx @tauri-apps/cli@2 build`），
#       产出 src-tauri/target/release/bundle/macos/skill-mcp-studio.app。
# 权限：需 `hdiutil` 磁盘映像权限（受限沙箱会话需升级完全访问）。
#
# 用法：
#   scripts/build_dmg.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE="$ROOT/src-tauri/target/release/bundle"
APP="$BUNDLE/macos/skill-mcp-studio.app"
FANCY="$BUNDLE/dmg/bundle_dmg.sh"
CONF="$ROOT/src-tauri/tauri.conf.json"

if [[ ! -d "$APP" ]]; then
  echo "错误：缺少 $APP" >&2
  echo "请先在 src-tauri/ 执行 cargo tauri build（工具链安装见 BUILD.md §1）" >&2
  exit 2
fi

# 陈旧挂载与失败残留清理（递归自包含缺陷的防御）
hdiutil detach "/Volumes/skill-mcp-studio" -force >/dev/null 2>&1 || true
rm -f "$BUNDLE/macos/rw."*.dmg "$BUNDLE/dmg/rw."*.dmg

VERSION="$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$CONF" | head -1)"
ARCH="$(uname -m)"
mkdir -p "$BUNDLE/dmg"
OUT="$BUNDLE/dmg/skill-mcp-studio_${VERSION}_${ARCH}.dmg"
rm -f "$OUT"

if [[ -x "$FANCY" ]]; then
  # 复用 tauri 生成的 create-dmg fork（窗口布局 + Applications 快捷方式）。
  # 关键：OUT 为绝对路径 → rw 临时映像落在 bundle/dmg/，不入源目录。
  "$FANCY" \
    --volname "skill-mcp-studio" \
    --icon "skill-mcp-studio.app" 180 170 \
    --app-drop-link 480 170 \
    --window-size 660 400 \
    --icon-size 128 \
    --hide-extension "skill-mcp-studio.app" \
    "$OUT" "$BUNDLE/macos"
else
  # 纯 hdiutil 退化路径：staging 目录 + Applications 软链
  STAGING="$(mktemp -d)"
  trap 'rm -rf "$STAGING"' EXIT
  cp -R "$APP" "$STAGING/"
  ln -s /Applications "$STAGING/Applications"
  hdiutil create -srcfolder "$STAGING" -volname "skill-mcp-studio" \
    -fs "HFS+" -format UDZO -imagekey zlib-level=9 "$OUT"
fi

# 验证：挂载 → 检查 .app 存在 → 卸载
hdiutil attach "$OUT" -nobrowse -readonly >/dev/null
if [[ ! -d "/Volumes/skill-mcp-studio/skill-mcp-studio.app" ]]; then
  hdiutil detach "/Volumes/skill-mcp-studio" -force >/dev/null 2>&1 || true
  echo "错误：生成的映像缺少 .app" >&2
  exit 1
fi
hdiutil detach "/Volumes/skill-mcp-studio" -force >/dev/null
echo "OK: $OUT"
ls -lh "$OUT"
