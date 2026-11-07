#!/bin/bash
# ============================================================================
# 导出 oswaldhill Local Development 代码签名身份到 ~/Downloads
#
# 直接执行（任何目录下都行）：
#     bash ~/Downloads/export-signing-identity.sh
#
# 会在 ~/Downloads 产出：
#     oswaldhill-dev.crt            证书（公开部分，可自由传递）
#     oswaldhill-dev-signing.p12    证书+私钥（机密！）
#
# 为什么需要交互：macOS 把私钥锁在钥匙串里，导出时必须由你在系统弹窗里
# 点「允许」并输入登录密码。这是系统安全设计，任何工具都无法绕过。
# 如果看不到弹窗，请检查是否被其他窗口挡住，或切到「终端」App 再看。
# ============================================================================

set -uo pipefail

IDENTITY="oswaldhill Local Development"
OUT_DIR="$HOME/Downloads"
OUT_P12="$OUT_DIR/oswaldhill-dev-signing.p12"
OUT_CRT="$OUT_DIR/oswaldhill-dev.crt"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"

step() { printf "\n\033[1m==> %s\033[0m\n" "$1"; }
ok()   { printf "    \033[32m✓\033[0m %s\n" "$1"; }
warn() { printf "    \033[33m!\033[0m %s\n" "$1"; }
die()  { printf "\n\033[31m✗ %s\033[0m\n" "$1" >&2; exit 1; }

step "检查签名身份"
if ! security find-identity -v -p codesigning 2>/dev/null | grep -q "$IDENTITY"; then
  warn "当前找不到 \"$IDENTITY\""
  echo "    先尝试解锁钥匙串后重试："
  echo "      security unlock-keychain $KEYCHAIN"
  echo
  echo "    如果仍然找不到，说明这台机器不是证书持有者。"
  exit 1
fi
security find-identity -v -p codesigning | grep "$IDENTITY" | sed 's/^/    /'

step "导出证书（公开部分，无需授权）"
mkdir -p "$OUT_DIR"
if ! security find-certificate -c "$IDENTITY" -p > "$OUT_CRT" 2>/dev/null || [ ! -s "$OUT_CRT" ]; then
  die "证书导出失败"
fi
openssl x509 -in "$OUT_CRT" -noout -subject -dates 2>/dev/null | sed 's/^/    /'
ok "$OUT_CRT"

step "导出私钥（需要你点授权）"
cat <<'TIP'
    接下来会弹出系统对话框，要求访问钥匙串中的私钥。
    · 输入你的登录密码（不是 Apple ID 密码）
    · 点「允许」或「始终允许」
    · 可能弹 1-3 次，每次都允许
    · 若长时间无反应：切到「终端」App，看是否有窗口被挡住
TIP
echo

read -r -s -p "    为 .p12 设一个保护密码（至少 8 位，请记住）: " P12PASS
echo
[ "${#P12PASS}" -ge 8 ] || die "密码至少 8 位"

TMP_ALL="$(mktemp -t all-id).p12"
TMP_PEM="$(mktemp -t all-id).pem"
cleanup() { rm -f "$TMP_ALL" "$TMP_PEM" "$OUT_P12.crt.pem" "$OUT_P12.key.pem"; }
trap cleanup EXIT

echo "    正在导出（等待授权中，最长 120 秒）..."
if ! timeout 120 security export -t identities -f pkcs12 -o "$TMP_ALL" -P "$P12PASS" 2>/dev/null; then
  cat <<'FAIL'

    ✗ 导出未完成。常见原因与对策：

      A) 授权被取消 → 重跑本脚本，弹窗时点「允许」

      B) 完全没有弹窗（终端无 GUI 权限）→ 改用钥匙串访问手动导出：
         1. 打开「钥匙串访问」App
         2. 左侧选「登录」→ 分类选「我的证书」
         3. 找到 "oswaldhill Local Development"，右键 →「导出项目…」
         4. 格式选「个人信息交换 (.p12)」，存为 ~/Downloads/oswaldhill-dev-signing.p12
         5. 设置导出密码（至少 8 位）
         6. 把该 .p12 传到新设备，直接跑导入脚本即可（无需再跑本脚本）：
              bash import-signing-identity.sh ~/Downloads/oswaldhill-dev-signing.p12
FAIL
  exit 1
fi
ok "已导出到临时文件"

step "提取目标身份（排除无关证书）"
# macOS 的 security export 用 RC2-40-CBC 加密 p12，OpenSSL 3.x 默认禁用了该
# 弱算法，直接 openssl pkcs12 会报 "unknown cipher:RC2-40-CBC"。必须加 -legacy。
if ! openssl pkcs12 -legacy -in "$TMP_ALL" -passin "pass:$P12PASS" -nodes -out "$TMP_PEM" 2>/dev/null; then
  # 老版本 OpenSSL（1.x）不认 -legacy，回退普通方式
  openssl pkcs12 -in "$TMP_ALL" -passin "pass:$P12PASS" -nodes -out "$TMP_PEM" 2>/dev/null \
    || die "临时 p12 解密失败"
fi

python3 - "$TMP_PEM" "$OUT_P12" "$P12PASS" "$IDENTITY" <<'PY'
import re, subprocess, sys, pathlib
pem_path, out_p12, password, identity = sys.argv[1:5]
# 证书属性头（friendlyName 等）可能含中文，非 UTF-8；用 errors='ignore' 容错。
# 需要匹配的 PEM 块本身是 ASCII，不受影响。
text = pathlib.Path(pem_path).read_bytes().decode('utf-8', errors='ignore')
certs = re.findall(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', text, re.S)
keys = re.findall(r'-----BEGIN (?:RSA |EC |ENCRYPTED )?PRIVATE KEY-----.*?-----END (?:RSA |EC |ENCRYPTED )?PRIVATE KEY-----', text, re.S)

target = None
for cert in certs:
    info = subprocess.run(['openssl','x509','-noout','-subject'],
                          input=cert, capture_output=True, text=True).stdout
    if identity in info:
        target = cert
        break
if target is None:
    sys.exit('    未在导出内容中找到目标证书')
if not keys:
    sys.exit('    导出内容中没有私钥（授权可能未完成）')

def mod_cert(c):
    return subprocess.run(['openssl','x509','-noout','-modulus'],
                          input=c, capture_output=True, text=True).stdout.strip()
def mod_key(k):
    return subprocess.run(['openssl','rsa','-noout','-modulus'],
                          input=k, capture_output=True, text=True).stdout.strip()

# 按索引配对在输出顺序错乱时会静默配错，生成「能导入但签不出名」的坏 p12。
# 用 RSA modulus 交叉校验，不匹配则遍历全部私钥精确查找。
want = mod_cert(target)
key = keys[0]
if mod_key(key) != want:
    for candidate in keys:
        if mod_key(candidate) == want:
            key = candidate
            break
    else:
        sys.exit('    私钥与证书不匹配，且未找到配对私钥')

crt_tmp, key_tmp = out_p12 + '.crt.pem', out_p12 + '.key.pem'
pathlib.Path(crt_tmp).write_text(target + '\n')
pathlib.Path(key_tmp).write_text(key + '\n')
# 必须用 -legacy 导出：OpenSSL 3.x 默认生成 AES-256 + SHA-256 的现代 p12，
# 而 macOS 的 security import 只认旧格式（RC2/3DES + SHA-1 MAC），
# 现代格式会报 "MAC verification failed during PKCS12 import (wrong password?)"。
r = subprocess.run(['openssl','pkcs12','-export','-legacy','-out',out_p12,
                    '-inkey',key_tmp,'-in',crt_tmp,
                    '-passout','pass:'+password], capture_output=True, text=True)
if r.returncode != 0:
    sys.exit('    重新打包失败: ' + r.stderr.strip())
print('    ✓ 已生成 ' + out_p12)
PY
[ $? -eq 0 ] || die "提取失败"

step "校验产物"
openssl pkcs12 -in "$OUT_P12" -passin "pass:$P12PASS" -nokeys -info 2>/dev/null \
  | grep -E "subject=" | head -2 | sed 's/^/    /'
chmod 600 "$OUT_P12"
ok "权限已设为 600"

step "完成"
cat <<EOF

    产物：
      $OUT_CRT    证书，可自由传递
      $OUT_P12    含私钥，机密！

    下一步：
      1. 把 .p12 通过加密渠道传到新设备（不要发群/公共网盘）
      2. 密码用另一渠道告知
      3. 新设备执行：bash import-signing-identity.sh <p12路径>

    安全提醒：.p12 等同于你的签名能力。用完请删除本机副本。

    ⚠ 你刚才设置的 .p12 密码是：$P12PASS
      请立刻记到密码管理器。新设备导入时必须用它；
      输错会报「MAC verification failed」或直接失败。
EOF
