# GitHub 分支清理记录（2026-11-14）

用户要求 GitHub 上只保留 `master`。清理前快照如下（`git ls-remote --heads github`）。

## 删除的分支

### 已完整合入 master（删除无信息损失）

| 分支 | SHA |
|---|---|
| `add-macos-ci` | `028a71a544833bcabe0af9048efe772e527ca0fa` |
| `docs-status-update` | `acc3cbf305c2a5e64d14a6d2a803246418dc8303` |
| `enhance-macos-ci` | `db8d21d93ef71f25416b021a1fed2fddf2223c76` |
| `fix-ci-conditional` | `4dc8574020421c75fcd4a672039f575f413670ce` |

### dependabot 依赖升级（**未合入 master**，删除后需重新开启才有）

| 分支 | SHA | 内容 |
|---|---|---|
| `dependabot/cargo/src-tauri/serde_json-1.0.154` | `cc9e42f7a18140b60d84950704d8c89d71b21f1a` | serde_json 1.0.154 |
| `dependabot/cargo/src-tauri/tauri-build-2.7.2` | `e187cef1ddba4474b7e8fe9f54b7c9495b337838` | tauri-build 2.7.1 → 2.7.2 |
| `dependabot/cargo/src-tauri/tauri-plugin-dialog-2.8.2` | `861d3d0e353cc1de642a6190d5dd1eee97b2d186` | tauri-plugin-dialog 2.7.3 → 2.8.2 |
| `dependabot/cargo/src-tauri/tauri-plugin-notification-2.6.0` | `85f992dbdac23f5a3af8d94b4de7d97bc9e992b3` | tauri-plugin-notification → 2.6.0 |
| `dependabot/github_actions/actions/download-artifact-7` | `3d8910f53bb0f530a5d2207d59a916d4fb59b8fe` | download-artifact 6 → 7 |
| `dependabot/github_actions/actions/setup-node-6` | `e556e06ff8d1c3bda0f917875c44118e5dd35313` | setup-node 5 → 6 |
| `dependabot/github_actions/actions/setup-python-7` | `c73de42791b70901a2b49eef4f36cf0adc301567` | setup-python 6 → 7 |
| `dependabot/github_actions/actions/upload-artifact-7` | `58df7b35716a07edc377f0e7b93f42bae35329d2` | upload-artifact 6 → 7 |
| `dependabot/github_actions/dtolnay/rust-toolchain-1.120.0` | `a6f4072ec37123a2076402d50f1a08c426ed48b1` | rust-toolchain 1.98.1 → 1.120.0 |

### develop

| 分支 | SHA |
|---|---|
| `develop` | `3f1b557218c2514e8a65461ec419122be36353bb`（与 master 同点，内容无损失） |

## 恢复方式

dependabot 分支由 GitHub 自动维护，重新开启 dependabot 即可再生；
上述 SHA 在 GitHub 未被 GC 前仍可通过 `git fetch origin <sha>` 取回。
Codeup（`origin`）上的同名分支**未受影响**。
