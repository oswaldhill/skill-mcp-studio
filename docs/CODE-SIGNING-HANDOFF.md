# 代码签名身份交接：oswaldhill Local Development

2026-11-07。给需要在新设备上构建 `skill-mcp-studio.app` 的开发者。

## 1. 这份文档解决什么问题

`src-tauri/tauri.conf.json` 里指定了签名身份：

```json
"bundle": {
  "macOS": {
    "signingIdentity": "oswaldhill Local Development"
  }
}
```

新设备上没有这张证书时，`cargo tauri build` 会在签名步骤失败。有两种可能的表现：

| 表现 | 原因 |
|---|---|
| `security find-identity` 显示 0 个有效身份 | 钥匙串里没有这张证书 |
| 构建报 `failed to sign` / `no identity found` | 同上 |

**注意区分两种「失败」**：

- **证书缺失** → 构建失败，必须导入证书（本文档）
- **证书存在但 `spctl` 报 rejected** → 构建**成功**，只是 Gatekeeper 不信任自签证书（见 §6，这是正常的）

## 2. 证书是什么

| 项 | 值 |
|---|---|
| 名称（CN） | `oswaldhill Local Development` |
| 组织（O） | `Local Development` |
| SHA-1 | `E2F6D1A521D4E93F1FED9A44E46508BC90BC1F2F` |
| 有效期 | 2026-09-26 ~ **2036-09-23** |
| 类型 | **自签证书**（非 Apple Developer ID） |
| 用途 | 本地开发签名，不做分发公证 |

**它是自签证书，不是 Apple 签发的。** 这意味着：

- 本机双击可正常打开
- 分发给他人的机器上，对方需要**右键 → 打开**才能绕过 Gatekeeper
- `spctl -a` 判定为 `rejected` 是预期行为，不是配置错误

如果需要正式分发，见 §7。

## 3. 旧设备：导出

在**持有证书的机器**上执行：

```bash
bash scripts/export-signing-identity.sh ~/Desktop
```

产出两个文件：

| 文件 | 内容 | 机密性 |
|---|---|---|
| `oswaldhill-dev.crt` | 证书（公开部分） | 公开 |
| `oswaldhill-dev-signing.p12` | 证书 + **私钥** | **机密** |

### 为什么要用脚本而不是一条命令

macOS 把私钥锁在钥匙串里。`security export -t identities` 导出时**必须**由用户在系统弹窗里点「允许」并输入登录密码。

这不是脚本可以绕过的东西 —— 实测静默执行会卡住 60 秒以上直到超时。脚本的作用是把容易出错的参数固定下来，你只需要点一次授权。

### 如果导出脚本卡住

1. 检查是否有系统弹窗被其他窗口挡住（切换到 Finder 或终端窗口）
2. 可能弹出多次，每次都点「允许」
3. 若中途点了「拒绝」，重跑脚本

## 4. 新设备：导入

```bash
bash scripts/import-signing-identity.sh /path/to/oswaldhill-dev-signing.p12
```

脚本会：

1. 把 p12 导入登录钥匙串
2. 检查身份是否可用
3. 修复私钥访问控制（让 `codesign` 不再每次弹授权）
4. 尝试把证书加入**用户域**的代码签名信任（不需要 sudo）
5. 实际签一个临时文件验证

### 验证成功的标志

```bash
security find-identity -v -p codesigning | grep oswaldhill
# 应输出：
#   E2F6D1A521D4E93F1FED9A44E46508BC90BC1F2F "oswaldhill Local Development"
```

```bash
cd src-tauri && cargo tauri build
# 应能完成，产物签名正确：
codesign -dvv target/release/bundle/macos/skill-mcp-studio.app 2>&1 | grep Authority
# 应输出：
#   Authority=oswaldhill Local Development
```

## 5. 故障排查

### 5.1 `security find-identity` 返回 0 个身份

先排除最常见的原因：**钥匙串被锁定**。

```bash
security unlock-keychain ~/Library/Keychains/login.keychain-db
security find-identity -v -p codesigning
```

锁定的钥匙串会让所有身份「消失」，看起来像证书不存在。这是误判的头号来源。

### 5.2 身份存在但签名报 `errSecInternalComponent`

私钥访问控制没放行 `codesign`。

**命令行修复**（需要登录密码）：

```bash
security set-key-partition-list -S apple-tool:,apple:,codesign: \
  -s -k "" ~/Library/Keychains/login.keychain-db
```

**图形界面修复**：

1. 打开「钥匙串访问」
2. 左侧选「登录」→「我的证书」
3. 找到 `oswaldhill Local Development`，点左侧箭头展开
4. 双击下面的私钥
5. 「访问控制」标签 → 选「允许所有应用程序访问此项目」→ 存储

### 5.3 出现两个同名身份

如果 `find-identity` 显示两行相同的 SHA-1，说明证书被重复导入过。**不影响签名**，但可以清理：

```bash
# 先确认是同一张证书
security find-certificate -a -c "oswaldhill Local Development" -Z | grep "SHA-1"
```

清理方法：钥匙串访问里删掉多余的那条（保留带私钥的一条）。

### 5.4 构建仍然失败

确认配置指向的名称与钥匙串里的**完全一致**（含大小写和空格）：

```bash
python3 -c "import json; print(json.load(open('src-tauri/tauri.conf.json'))['bundle']['macOS']['signingIdentity'])"
security find-identity -v -p codesigning
```

## 6. `spctl rejected` 是正常的

```bash
$ spctl -a -vv /Applications/skill-mcp-studio.app
/Applications/skill-mcp-studio.app: rejected
origin=oswaldhill Local Development
```

注意 `origin` 显示的是证书名 —— 系统**认出了签名者，只是不信任它**。

原因有两个，缺一不可：

1. 自签证书不在 Apple 信任链里
2. 未经过 Apple 公证（notarization）

**这不影响本机使用。** 双击 app 能正常启动。

如果希望本机 `spctl` 也通过，可以把证书设为代码签名信任：

```bash
security add-trusted-cert -r trustRoot -p codeSign \
  -k ~/Library/Keychains/login.keychain-db ~/Desktop/oswaldhill-dev.crt
```

但这只影响**这一台机器**，对分发给别人没有帮助。

## 7. 如果要正式分发给他人

当前自签证书**做不到**。需要 Apple Developer Program 账号（个人 $99/年）。

| 方式 | 要求 | 他人体验 |
|---|---|---|
| 自签（当前） | 无 | 需右键打开，且每次更新都可能要重新放行 |
| Developer ID + 公证 | $99/年 | 双击直接打开 |
| Mac App Store | $99/年 + 审核 | 从商店安装 |

**Developer ID 路径需要 6 个 CI secrets**（若走 GitHub Actions）：

| Secret | 内容 |
|---|---|
| `APPLE_CERTIFICATE` | Developer ID Application 证书的 base64（`.p12`） |
| `APPLE_CERTIFICATE_PASSWORD` | 上述 p12 的密码 |
| `APPLE_SIGNING_IDENTITY` | 形如 `Developer ID Application: Name (TEAMID)` |
| `APPLE_ID` | Apple 账号邮箱 |
| `APPLE_PASSWORD` | app-specific password（不是登录密码） |
| `APPLE_TEAM_ID` | 10 位 Team ID |

本地构建则需要：把 Developer ID 证书装进钥匙串，并把 `signingIdentity` 改成该证书全名。

## 8. 安全提醒

**`.p12` 文件等同于你的签名能力。** 拿到它的人可以签出「看起来是你签的」应用。

- 不要提交 Git（检查 `.gitignore`）
- 不要发微信群 / 邮件附件 / 公共网盘
- 传输用加密渠道，密码与文件分开传达
- 用完删除本机副本，或移到加密卷
- 若怀疑泄露：作废该证书并重新生成，然后按本文档重新分发

`.crt` 文件是公开部分，可以自由传递。

## 9. 备选方案：新设备重新生成自签证书

如果不方便从旧设备导出（或旧设备已不可用），可以在新设备上重新生成一张。

**代价**：新旧设备的签名身份不同，SHA-1 会变。对本机开发无影响，但如果两边的构建产物需要互相校验签名，就会不一致。

```bash
IDENTITY="oswaldhill Local Development"

# 生成私钥与自签证书（10 年有效期，带 codeSigning 用途）
openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
  -keyout /tmp/oswaldhill.key -out /tmp/oswaldhill.crt \
  -subj "/CN=$IDENTITY/O=Local Development" \
  -addext "extendedKeyUsage=codeSigning" \
  -addext "basicConstraints=critical,CA:false"

# 打包成 p12 并导入
openssl pkcs12 -export -out /tmp/oswaldhill.p12 \
  -inkey /tmp/oswaldhill.key -in /tmp/oswaldhill.crt \
  -passout pass:CHANGE_ME
security import /tmp/oswaldhill.p12 -k ~/Library/Keychains/login.keychain-db \
  -P CHANGE_ME -T /usr/bin/codesign

rm -f /tmp/oswaldhill.key /tmp/oswaldhill.crt /tmp/oswaldhill.p12

# 验证
security find-identity -v -p codesigning | grep oswaldhill
```

## 10. 文件清单

| 文件 | 位置 | 用途 |
|---|---|---|
| `oswaldhill-dev.crt` | 由导出脚本生成 | 证书公开部分，可直接分发 |
| `scripts/export-signing-identity.sh` | 项目内（已提交） | 旧设备导出（含私钥，需授权） |
| `scripts/import-signing-identity.sh` | 项目内（已提交） | 新设备导入并验证 |
| `oswaldhill-dev-signing.p12` | 由导出脚本生成 | **机密**，证书+私钥 |

---

**本文档不含任何私钥或密码。** `.p12` 的保护密码由导出者通过独立渠道告知。