#!/bin/bash
# 在**新设备**上执行，导入 oswaldhill Local Development 签名身份。
#
# 前提：已从旧设备拿到 oswaldhill-dev-signing.p12 和它的保护密码。
#
# 用法：
#   bash import-signing-identity.sh /path/to/oswaldhill-dev-signing.p12
#
# 导入后效果：
#   - codesign 可用 "oswaldhill Local Development" 签名
#   - 本机 tauri build 不再卡在签名步骤
#   - 仍不是 Developer ID，分发给他人时对方需右键打开（见交接文档）

set -euo pipefail

P12="${1:-}"
IDENTITY="oswaldhill Local Development"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"

if [ -z "$P12" ] || [ ! -f "$P12" ]; then
  echo "用法: bash import-signing-identity.sh /path/to/oswaldhill-dev-signing.p12" >&2
  exit 1
fi

echo "==> 导入前状态"
security find-identity -v -p codesigning | tail -3

echo
echo "==> 导入 p12 到登录钥匙串（会提示输入 p12 密码和登录密码）"
security import "$P12" -k "$KEYCHAIN" -P "" -T /usr/bin/codesign -T /usr/bin/security 2>&1 \
  || security import "$P12" -k "$KEYCHAIN" -T /usr/bin/codesign -T /usr/bin/security

echo
echo "==> 检查导入结果"
if ! security find-identity -v -p codesigning | grep -q "$IDENTITY"; then
  echo "错误：导入后仍未找到 \"$IDENTITY\" 身份。" >&2
  echo "常见原因：" >&2
  echo "  1) p12 密码错误 —— 重新导入" >&2
  echo "  2) 私钥访问控制未放行 codesign —— 见下方「修复私钥 ACL」" >&2
  exit 1
fi
security find-identity -v -p codesigning | grep "$IDENTITY"

echo
echo "==> 修复私钥访问控制（让 codesign 无需每次授权）"
# 新导入的私钥默认只允许 ssh/security 访问，codesign 会被拒。
# 用 -T 在导入时已声明 codesign；此处再补一次，覆盖既有条目的情况。
security set-key-partition-list -S apple-tool:,apple:,codesign: \
  -s -k "" "$KEYCHAIN" >/dev/null 2>&1 \
  || echo "  提示：set-key-partition-list 需要登录密码，已跳过（可能每次签名弹一次授权）"

echo
echo "==> 自签证书信任设置（可选，只影响本机 spctl 判定）"
CRT_TMP="$(mktemp -t cert).pem"
security find-certificate -c "$IDENTITY" -p > "$CRT_TMP" 2>/dev/null || true
if [ -s "$CRT_TMP" ]; then
  # 仅加入用户域、仅 codeSign 策略，不碰系统域（不需要 sudo）
  security add-trusted-cert -r trustRoot -p codeSign \
    -k "$KEYCHAIN" "$CRT_TMP" 2>/dev/null \
    && echo "  已加入用户信任（codeSign）" \
    || echo "  跳过信任设置（不影响 codesign，仅 spctl 仍报 rejected）"
fi
rm -f "$CRT_TMP"

echo
echo "==> 实际签名验证"
TESTBIN="$(mktemp -t signtest)"
cp /bin/echo "$TESTBIN"
if codesign --force --sign "$IDENTITY" "$TESTBIN" 2>/dev/null; then
  echo "  ✓ 签名成功"
  codesign -dvv "$TESTBIN" 2>&1 | grep -E "Authority" || true
else
  echo "  ✗ 签名失败 —— 私钥 ACL 可能未放行 codesign" >&2
  echo "    手动修复：打开「钥匙串访问」→ 我的证书 → 展开该证书 → 双击私钥 →" >&2
  echo "    「访问控制」→ 选「允许所有应用程序访问此项目」" >&2
fi
rm -f "$TESTBIN"

echo
echo "完成。下一步："
echo "  1) 确认 src-tauri/tauri.conf.json 中 bundle.macOS.signingIdentity"
echo "     为 \"$IDENTITY\""
echo "  2) 重新构建：cd src-tauri && cargo tauri build"