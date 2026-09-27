#!/bin/sh
# 一次性启用仓库自带的 git hooks。
#
# 背景：.git/hooks/ 不随仓库提交，门禁脚本只有放在仓库内的 scripts/git-hooks/
# 才不会在换机器或重新 clone 后丢失。用 core.hooksPath 指向它，git 就会直接从
# 仓库内加载 hook。
#
# 用法（clone 后执行一次即可）：
#   scripts/install-hooks.sh
#
# 说明：core.hooksPath 使用相对路径（相对于仓库根），因此该配置不依赖任何
# 机器上的绝对路径，仓库内通用。

set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -d scripts/git-hooks ]; then
  echo "✗ 找不到 scripts/git-hooks，无法安装" >&2
  exit 1
fi

# git 只执行带可执行位的 hook；clone 后该权限可能丢失，这里统一补上。
chmod +x scripts/git-hooks/*

git config core.hooksPath scripts/git-hooks

echo "✓ 已启用仓库内 git hooks"
echo "  core.hooksPath = $(git config --get core.hooksPath)"
echo "  已装载的 hook："
for f in scripts/git-hooks/*; do
  echo "    $(basename "$f")"
done
echo
echo "  验证：以下命令应被门禁拦截（非零退出）"
echo "    git push github <branch>"
echo "  明确放行时："
echo "    GITHUB_PUSH_ALLOW=1 git push github <branch>"
