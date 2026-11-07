#!/bin/bash
# 在**旧设备**（持有证书的机器）上执行，导出 oswaldhill Local Development 签名身份。
#
# 为什么需要脚本而不是纯命令：
#   macOS 把私钥锁在钥匙串里，`security export -t identities` 导出时**必须**
#   由用户在弹出的系统对话框里点「允许」并输入登录密码。这是系统安全设计，
#   无法静默完成（实测 60 秒无响应即卡在等待授权）。
#   本脚本把容易出错的参数固定下来，你只需点一次授权。
#
# 用法：
#   bash export-signing-identity.sh [输出目录]
# 默认输出到当前目录。

set -euo pipefail

IDENTITY="oswaldhill Local Development"
OUT_DIR="${1:-.}"
OUT_P12="$OUT_DIR/oswaldhill-dev-signing.p12"
OUT_CRT="$OUT_DIR/oswaldhill-dev.crt"

echo "==> 检查身份是否存在"
if ! security find-identity -v -p codesigning | grep -q "$IDENTITY"; then
  echo "错误：本机没有找到 \"$IDENTITY\" 签名身份。" >&2
  echo "      如果钥匙串刚解锁，请重试；否则这台机器不是证书持有者。" >&2
  exit 1
fi
security find-identity -v -p codesigning | grep "$IDENTITY"

echo
echo "==> 导出证书（公开部分，无需授权）"
security find-certificate -c "$IDENTITY" -p > "$OUT_CRT"
openssl x509 -in "$OUT_CRT" -noout -subject -dates

echo
echo "==> 导出私钥（需要你在系统弹窗里点「允许」并输入登录密码）"
echo "    提示：可能弹出 1-3 次，每次都要点「允许」。"
echo "    如果长时间无响应，说明弹窗被其他窗口挡住了。"
echo
read -r -s -p "为 .p12 设置一个保护密码（至少 8 位，自己记住）: " P12PASS
echo
if [ "${#P12PASS}" -lt 8 ]; then
  echo "错误：密码至少 8 位。" >&2
  exit 1
fi

# security export 不支持按证书名筛选，只能导出该钥匙串全部身份，
# 再用 openssl 把目标证书+私钥单独提取出来，避免把无关密钥带进交付物。
TMP_ALL="$(mktemp -t all-identities).p12"
trap 'rm -f "$TMP_ALL"' EXIT

if ! security export -t identities -f pkcs12 -o "$TMP_ALL" -P "$P12PASS" 2>/dev/null; then
  echo "错误：导出被取消或失败。" >&2
  echo "      若为「用户取消」，重跑本脚本并在弹窗中点「允许」。" >&2
  exit 1
fi

echo "==> 提取目标身份"
# 找出包含该证书的私钥。openssl 会把同一 p12 内的所有 cert/key 依次输出，
# 用 -passin 解密后按 subject 匹配目标证书，再取出其对应的私钥块。
openssl pkcs12 -in "$TMP_ALL" -passin "pass:$P12PASS" -nodes -out "$TMP_ALL.pem" 2>/dev/null || {
  echo "错误：无法解密临时 p12。" >&2
  exit 1
}

python3 - "$TMP_ALL.pem" "$OUT_P12" "$P12PASS" <<'PY'
import re, subprocess, sys, pathlib
pem_path, out_p12, password = sys.argv[1], sys.argv[2], sys.argv[3]
text = pathlib.Path(pem_path).read_text()

certs = re.findall(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', text, re.S)
keys = re.findall(r'-----BEGIN (?:RSA |EC |ENCRYPTED )?PRIVATE KEY-----.*?-----END (?:RSA |EC |ENCRYPTED )?PRIVATE KEY-----', text, re.S)

target = None
for cert in certs:
    info = subprocess.run(['openssl', 'x509', '-noout', '-subject'],
                          input=cert, capture_output=True, text=True).stdout
    if 'oswaldhill Local Development' in info:
        target = cert
        break

if target is None:
    sys.exit('未在导出的 p12 中找到目标证书')

# p12 里证书与私钥按出现顺序配对；目标证书若为第 n 个，取第 n 个私钥。
idx = certs.index(target)
if idx >= len(keys):
    sys.exit('未找到与目标证书配对的私钥（可能私钥未授权导出）')

# 按索引配对在 openssl 输出顺序与 security export 不一致时会静默配错，
# 结果是一个能导入但签不出名的坏 p12。用 RSA modulus 交叉校验兜底。
def modulus_of_cert(cert_pem: str) -> str:
    r = subprocess.run(['openssl', 'x509', '-noout', '-modulus'],
                       input=cert_pem, capture_output=True, text=True)
    return r.stdout.strip()

def modulus_of_key(key_pem: str) -> str:
    r = subprocess.run(['openssl', 'rsa', '-noout', '-modulus'],
                       input=key_pem, capture_output=True, text=True)
    return r.stdout.strip()

key = keys[idx]
want = modulus_of_cert(target)
if want and modulus_of_key(key) != want:
    # 索引错位：改为在全部私钥里按 modulus 精确查找
    for candidate in keys:
        if modulus_of_key(candidate) == want:
            key = candidate
            break
    else:
        sys.exit('私钥与证书不匹配，且未在导出内容中找到配对私钥')

pathlib.Path(out_p12 + '.crt.pem').write_text(target + '\n')
pathlib.Path(out_p12 + '.key.pem').write_text(key + '\n')
r = subprocess.run(['openssl', 'pkcs12', '-export', '-out', out_p12,
                    '-inkey', out_p12 + '.key.pem', '-in', out_p12 + '.crt.pem',
                    '-passout', 'pass:' + password], capture_output=True, text=True)
pathlib.Path(out_p12 + '.crt.pem').unlink(missing_ok=True)
pathlib.Path(out_p12 + '.key.pem').unlink(missing_ok=True)
if r.returncode != 0:
    sys.exit('重新打包 p12 失败: ' + r.stderr.strip())
print('已生成:', out_p12)
PY

rm -f "$TMP_ALL.pem"

echo
echo "==> 校验产物"
openssl pkcs12 -in "$OUT_P12" -passin "pass:$P12PASS" -nokeys -info 2>/dev/null \
  | grep -E "subject|friendlyName" | head -3
echo
echo "完成。交付这两个文件到新设备："
echo "  $OUT_CRT   （证书，公开）"
echo "  $OUT_P12   （证书+私钥，机密，密码另行传达）"
echo
echo "安全提醒："
echo "  - .p12 含私钥，等同于你的签名能力。不要提交 Git、不要发群、不要放共享盘。"
echo "  - 用完请删除本机副本，或移到加密卷。"