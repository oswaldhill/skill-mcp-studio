#!/usr/bin/env bash
# 发布流程固化（评审 P2-13）。
#
# 为什么需要它：本仓库的发布顺序原先全靠人记 ——
#   bump_version.py --bump minor → 手改 CHANGELOG → commit → merge master →
#   git tag -a → push master + push tag。
# 步骤多、有顺序依赖、且中途失败会留下半成品（例如 tag 打了但 CHANGELOG 没写、
# 或 master 合并了却没打 tag）。本脚本把这些顺序与前置校验写死，让「漏一步」
# 在本地就暴露，而不是等到 release workflow 触发后才发现。
#
# 与 P0-2 的关系：那是 CI 侧的 tag ↔ version.json 一致性校验，属**事后**拦截；
# 本脚本是**事前**同源校验（打的 tag 必须等于 version.json 里的 version），
# 两者构成双保险。
#
# 用法::
#   scripts/release.sh --bump minor            # 预演：跑校验 + bump 预览，不改任何东西
#   scripts/release.sh --bump minor --apply    # 真正执行本地部分（bump + 提交）
#   scripts/release.sh --bump minor --apply --tag      # 额外打 tag
#   scripts/release.sh --bump minor --apply --tag --push   # 额外推送（需显式开启）
#   scripts/release.sh ... --push --remote github          # 指定推送远端（默认 github）
#
# 设计取舍：
# - **默认预演**。发布不可逆（tag 与远端历史），必须显式 --apply 才动手。
# - **默认不推送**。本仓库有「未经允许不得 push」的门禁 hook（P0-6），
#   脚本不该绕过它；--push 是显式授权，且推送前会再确认一次。
# - CHANGELOG 正文**不自动生成**：bump_version.py 已经刻意不生成（变更内容
#   需要人写）。脚本只校验「新版本段落是否存在且非空」，缺失就停下让你去写。

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BUMP=""
APPLY=0
TAG=0
PUSH=0
TARGET_BRANCH="master"
SOURCE_BRANCH="develop"
# 推送目标远端。默认 github —— 因为 tag-version-consistency、三个 build workflow
# 与 release-notes.yml **只在 GitHub 上运行**。此前硬编码 `git push origin`，
# 而本仓库的 origin 是 Codeup：--push 推完 tag 之后，CI 侧什么都不会发生，
# 脚本却宣称「release workflow 会被 tag 触发」—— 一次静默失效的发布。
# 可用 --remote <name> 或环境变量 RELEASE_REMOTE 覆盖。
RELEASE_REMOTE="${RELEASE_REMOTE:-github}"

note()  { printf '%s\n' "$*"; }
warn()  { printf '%s\n' "$*" >&2; }
die()   { warn "✗ $*"; exit 1; }
step()  { printf '\n== %s ==\n' "$*"; }

usage() {
  sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --bump)   BUMP="${2:-}"; shift 2 ;;
    --apply)  APPLY=1; shift ;;
    --tag)    TAG=1; shift ;;
    --push)   PUSH=1; shift ;;
    --remote) RELEASE_REMOTE="${2:-}"; shift 2 ;;
    --target) TARGET_BRANCH="${2:-}"; shift 2 ;;
    --source) SOURCE_BRANCH="${2:-}"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) die "未知参数: $1（用 --help 看用法）" ;;
  esac
done

[ -n "$BUMP" ] || die "必须指定 --bump patch|minor|major"
case "$BUMP" in patch|minor|major) ;; *) die "--bump 只接受 patch|minor|major，收到: $BUMP" ;; esac

PY="${PYTHON:-python3}"

# ---------------------------------------------------------------------------
step "前置校验"
# ---------------------------------------------------------------------------

# 1) 工作区必须干净 —— 否则 bump 会与未提交改动混在一起，事后无法分辨。
if [ -n "$(git status --porcelain)" ]; then
  warn "  工作区不干净："
  git status --short | sed 's/^/    /' >&2
  die "先提交或 stash 再发布"
fi
note "✓ 工作区干净"

# 2) 分支必须是发布源分支 —— 在 feature 分支上打 release tag 是常见事故。
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" != "$SOURCE_BRANCH" ]; then
  die "当前在 '$BRANCH'，发布应从 '$SOURCE_BRANCH' 出发（可用 --source 覆盖）"
fi
note "✓ 分支为 $SOURCE_BRANCH"

# 3) 远端同步性 —— 落后必须拦下；领先只在「不打 tag / 不推送」时才有意义：
#    若本地有未推提交而 --push 关闭，tag 会指向远端并不存在的提交，
#    于是 release-notes.yml 拿不到对应源码。此前这里只检查了 BEHIND，
#    注释却写着「落后或有本地未推提交都说明状态可疑」—— 注释与实现不符。
if git rev-parse --abbrev-ref '@{upstream}' >/dev/null 2>&1; then
  AHEAD_BEHIND="$(git rev-list --left-right --count '@{upstream}...HEAD' 2>/dev/null || echo '0	0')"
  BEHIND="$(printf '%s' "$AHEAD_BEHIND" | cut -f1)"
  AHEAD="$(printf '%s' "$AHEAD_BEHIND" | cut -f2)"
  if [ "${BEHIND:-0}" -gt 0 ]; then
    die "本地落后 upstream $BEHIND 个提交，先 pull/rebase"
  fi
  if [ "${AHEAD:-0}" -gt 0 ]; then
    if [ "$PUSH" -eq 0 ]; then
      die "本地领先 upstream ${AHEAD} 个提交，且未开启 --push —— tag 会指向远端不存在的提交（先推送，或加 --push）"
    fi
    note "· 本地领先 upstream ${AHEAD} 个提交（--push 会一并推送）"
  else
    note "✓ 未落后 upstream"
  fi
else
  note "· 无 upstream（跳过远端同步性检查）"
fi

# 4) 全量测试 —— 发布前必须绿。门槛与 CI 完全一致。
step "全量测试（scripts/ci_parity.sh）"
if [ ! -x scripts/ci_parity.sh ]; then
  die "找不到可执行的 scripts/ci_parity.sh"
fi
if ! scripts/ci_parity.sh; then
  die "测试未通过 —— 发布中止"
fi
note "✓ 测试通过"

# 5) bump 预演 —— 先看清版本会从多少变成多少，再决定是否 --apply。
step "版本变更预演"
BEFORE_JSON="$(cat version.json)"
"$PY" scripts/bump_version.py --bump "$BUMP" --dry-run || die "bump_version.py --dry-run 失败"
# dry-run 的输出格式不由本脚本掌控，因此版本号一律从「落盘后」的 version.json 读，
# 预演阶段只提示会按哪个分量升级，不做字符串解析（解析别家脚本的输出很脆）。
note "  version.json 当前: $(printf '%s' "$BEFORE_JSON" | tr -d '\n')"
note "  将按 '$BUMP' 分量升级（--apply 后生效）"

if [ "$APPLY" -eq 0 ]; then
  step "预演结束（未改动任何文件）"
  note "  加 --apply 才会真正执行 bump 与提交。"
  note "  完整链路: --apply [--tag] [--push]"
  exit 0
fi

# ---------------------------------------------------------------------------
step "执行 bump（--apply）"
# ---------------------------------------------------------------------------
"$PY" scripts/bump_version.py --bump "$BUMP" || die "bump_version.py 失败"

NEW_VERSION="$("$PY" -c 'import json;print(json.load(open("version.json"))["version"])')"
NEW_TAG="v${NEW_VERSION}"
note "✓ 新版本: ${NEW_VERSION}（tag 将为 ${NEW_TAG}）"

# CHANGELOG 正文必须由人写 —— 这里只做「有没有」的硬校验。
step "校验 CHANGELOG 段落"
if ! grep -q "^## \[v${NEW_VERSION}\]" CHANGELOG.md; then
  warn "  CHANGELOG.md 里没有 '## [v${NEW_VERSION}]' 段落。"
  warn "  bump_version.py 刻意不生成变更正文（内容需要人写），请补上后再发布："
  warn "    1) 把 [Unreleased] 下的条目移入新的 '## [v${NEW_VERSION}] - YYYY-MM' 段"
  warn "    2) 重新运行本脚本（改动会被一并提交）"
  die "CHANGELOG 段落缺失"
fi

# 段落不能是空壳：标题到下一个 '## [' 之间要有实际内容。
SECTION_LINES="$("$PY" - "$NEW_VERSION" <<'INNER'
import re, sys
version = sys.argv[1]
text = open("CHANGELOG.md", encoding="utf-8").read()
m = re.search(rf"^## \[v{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M)
print(len([ln for ln in (m.group(1) if m else "").splitlines() if ln.strip()]))
INNER
)"
if [ "${SECTION_LINES:-0}" -lt 1 ]; then
  die "CHANGELOG 的 v${NEW_VERSION} 段落是空的 —— 变更正文不能留白"
fi
note "✓ CHANGELOG 有 v${NEW_VERSION} 段落（$SECTION_LINES 行实质内容）"

# 编码合规：与 CI 的 text-hygiene 同源，避免推上去才红。
step "文本编码校验"
# 判据**内联**在本脚本里，不再依赖 $HOME/.dsh/skills/... 这类仓库外的个人路径 ——
# 此前那条依赖在缺失时只打一行「跳过」，发布链上的编码门禁就这样静默消失了，
# 而脚本仍宣称「与 CI 的 text-hygiene 同源」。
for f in CHANGELOG.md version.json pyproject.toml README.md; do
  if ! "$PY" - "$f" <<'PYEOF'
import sys
raw = open(sys.argv[1], "rb").read()
bad = []
if raw.startswith(b"\xef\xbb\xbf"):
    bad.append("含 UTF-8 BOM")
if b"\r\n" in raw:
    bad.append("含 CRLF（本仓库统一 LF）")
if not raw.endswith(b"\n"):
    bad.append("末尾缺少换行")
elif raw.endswith(b"\n\n"):
    bad.append("末尾多余空行（应恰好一个换行）")
if bad:
    print("; ".join(bad), file=sys.stderr)
    sys.exit(1)
PYEOF
  then
    die "$f 编码不合规（BOM / CRLF / 末尾换行）"
  fi
done
note "✓ 关键文本产物编码合规"

# ---------------------------------------------------------------------------
step "提交（--apply）"
# ---------------------------------------------------------------------------
git add -A
git commit -q -m "chore(release): ${NEW_TAG}

由 scripts/release.sh 固化发布流程（评审 P2-13）。
版本: $BUMP bump → ${NEW_VERSION}
" || die "提交失败"
note "✓ 已提交: $(git log --oneline -1)"

if [ "$TAG" -eq 0 ]; then
  step "到此为止（未打 tag）"
  note "  后续手动步骤："
  note "    git checkout $TARGET_BRANCH && git merge $SOURCE_BRANCH"
  note "    git tag -a $NEW_TAG -m 'release ${NEW_TAG}'"
  note "    git push $RELEASE_REMOTE $TARGET_BRANCH && git push $RELEASE_REMOTE $NEW_TAG"
  note "  或重跑本脚本并追加 --tag --push（它会完成上述动作）。"
  exit 0
fi

# ---------------------------------------------------------------------------
step "合并到 $TARGET_BRANCH 并打 tag（--tag）"
# ---------------------------------------------------------------------------
git checkout -q "$TARGET_BRANCH" || die "切到 $TARGET_BRANCH 失败"
git merge --no-ff -q "$SOURCE_BRANCH" -m "merge: ${SOURCE_BRANCH} → ${TARGET_BRANCH}（${NEW_TAG}）" \
  || die "合并 $SOURCE_BRANCH → $TARGET_BRANCH 失败，请手工解决冲突后重试"

# tag 必须与 version.json 一致 —— 与 P0-2 的 CI 校验同源，这里是事前拦截。
TAG_VERSION="$(git show "$TARGET_BRANCH:version.json" | "$PY" -c 'import json,sys;print(json.load(sys.stdin)["version"])')"
[ "$TAG_VERSION" = "$NEW_VERSION" ] || die "$TARGET_BRANCH 上 version.json 是 ${TAG_VERSION}，与 $NEW_VERSION 不一致"

if git rev-parse -q --verify "refs/tags/$NEW_TAG" >/dev/null; then
  die "tag $NEW_TAG 已存在（发布不可重来；如需重打请先确认是否要删除旧 tag）"
fi
git tag -a "$NEW_TAG" -m "release ${NEW_TAG}" || die "打 tag 失败"
note "✓ 已打 tag: $NEW_TAG"

if [ "$PUSH" -eq 0 ]; then
  step "到此为止（未推送）"
  note "  本仓库有「未经允许不得 push」的门禁（P0-6），脚本不会替你绕开它。"
  note "  确认无误后手动执行："
  note "    git push $RELEASE_REMOTE $TARGET_BRANCH"
  note "    git push $RELEASE_REMOTE $NEW_TAG"
  exit 0
fi

# ---------------------------------------------------------------------------
step "推送（--push，需显式授权）"
# ---------------------------------------------------------------------------
# 推送前确认目标远端存在，并检查它是否就是跑流水线的那个。
git remote get-url "$RELEASE_REMOTE" >/dev/null 2>&1 \
  || die "远端 '$RELEASE_REMOTE' 不存在（git remote -v 查看；可用 --remote 指定）"
REMOTE_URL="$(git remote get-url "$RELEASE_REMOTE")"
case "$REMOTE_URL" in
  *github.com*) : ;;
  *) warn "  ⚠ 远端 '$RELEASE_REMOTE' 不是 github.com（$REMOTE_URL）"
     warn "    .github/workflows/ 下的校验、三平台构建与 Release 正文只在该远端运行，"
     warn "    推到别处等于发布流水线不会启动。确认无误再加 --remote 显式覆盖。" ;;
esac
warn "  即将推送 $TARGET_BRANCH 与 tag $NEW_TAG 到 $RELEASE_REMOTE —— 这是不可逆的对外动作。"
if [ "${RELEASE_YES:-}" != "1" ]; then
  printf '  确认推送请输入 yes: '
  read -r REPLY || die "无法读取确认输入（非交互环境请设 RELEASE_YES=1）"
  [ "$REPLY" = "yes" ] || die "已取消推送（本地 tag 与合并仍在，可稍后手动推送）"
fi

git push "$RELEASE_REMOTE" "$TARGET_BRANCH" || die "推送 $TARGET_BRANCH 到 $RELEASE_REMOTE 失败"
git push "$RELEASE_REMOTE" "$NEW_TAG" || die "推送 tag $NEW_TAG 到 $RELEASE_REMOTE 失败"
note "✓ 已推送 $TARGET_BRANCH 与 $NEW_TAG 到 $RELEASE_REMOTE"
note ""
case "$REMOTE_URL" in
  *github.com*)
    note "tag 已推到 GitHub，release workflow 会被它触发并自动补 Release 正文（release-notes.yml）。" ;;
  *)
    note "注意：tag 推到了非 GitHub 远端，.github/workflows/ 不会运行 —— 三平台构建与" ;
    note "Release 正文都不会自动生成，需手工完成。" ;;
esac

# 收尾：回到源分支，避免把人留在 master 上继续开发。
git checkout -q "$SOURCE_BRANCH" 2>/dev/null && note "· 已切回 $SOURCE_BRANCH"
