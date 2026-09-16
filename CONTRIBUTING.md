# 贡献指南

感谢你对 skill-mcp-studio 的关注。本文说明如何搭建开发环境、运行测试、提交代码。

## 环境要求

- **Python ≥ 3.11**（运行时唯一依赖 `PyYAML`）
- **Rust ≥ 1.77** + **Tauri v2**（仅桌面 App 构建需要）
- **Node.js** + npm（仅构建 Tauri 壳的 tauri-cli 需要）

## 开发环境

```bash
git clone <repo> && cd skill-mcp-studio

# 从源码直接运行 CLI（无需安装）
python3 scan.py --help
python3 scan.py --full            # 只读审计
```

## 运行测试

测试使用标准库 `unittest`，无需额外安装 pytest：

```bash
python3 -m unittest discover -s tests -t . -v
```

> 说明：`tests/` 不含 `__init__.py`，用 `unittest discover` 时需指定顶层目录 `-t .`；
> 或使用 pytest（`pip install pytest` 后 `python3 -m pytest tests/ -q`）。

## 构建桌面 App（macOS）

```bash
cd src-tauri
cargo tauri build              # 产出 target/release/bundle/macos/skill-mcp-studio.app
```

详细步骤见 [`src-tauri/BUILD.md`](src-tauri/BUILD.md)。

## 项目结构

- `scan.py` — CLI 入口
- `core/` — 领域逻辑（39 模块，扁平顶层模块）
- `gui/dashboard.html` — 前端管理台（单文件静态页）
- `src-tauri/` — Tauri 桌面壳
- `docs/` — 产品 / 设计 / 决策 / 评审文档（见 [`docs/README.md`](docs/README.md)）

## 提交规范

- 提交信息采用 Conventional Commits 风格：`fix:` / `feat:` / `docs:` / `refactor:` /
  `chore:` / `test:`。
- 一个提交只做一件事，避免混合无关改动。
- 涉及写操作的代码路径必须遵循既有的「备份 → 原子写 → 校验 → 回滚」安全链范式。

## 提交 PR 前检查

1. `python3 -m unittest discover -s tests -t .` 全部通过；
2. 若改动影响 GUI/CLI 结论，运行 `scripts/verify_gui_consistency.sh` 保证一致性；
3. 不向仓库提交个人拓扑 / 真实端点 / 密钥（保持 `config.yaml` 通用化、个人端点放仓库外）。

## 上报问题

- Bug / 功能请求 → 新建 [Issue](https://github.com/OWNER/REPO/issues)
- 安全漏洞 → 按 [`SECURITY.md`](SECURITY.md) 非公开上报