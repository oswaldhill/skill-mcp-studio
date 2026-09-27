#!/usr/bin/env bash
# GUI/CLI 一致性 gate（阶段三 DoD 护栏）。
#
# 跑一次 CLI 产出审计快照（`--all-profiles --format json`），用引擎侧
# `gui_consistency.verify_snapshot` 复算每个 record 的 state 与 ok，逐字段断言
# 「GUI 消费的快照 == CLI 结论」。违规数非零即退出 1。
#
# 用法:
#   scripts/verify_gui_consistency.sh            # 用仓库默认 config.yaml
#   scripts/verify_gui_consistency.sh -c CUSTOM  # 指定 config
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FLAG=()

while getopts "c:" opt; do
  case "$opt" in
    c) CONFIG_FLAG=(--config "$OPTARG") ;;
    *) echo "usage: $0 [-c CONFIG]" >&2; exit 2 ;;
  esac
done

SNAPSHOT_JSON="$(mktemp)"
trap 'rm -f "$SNAPSHOT_JSON"' EXIT

# scan.py 退出码约定（阶段三 §3.1 / 决策记录 D9）：0=全绿，1=存在不合规项，
# 2=运行/配置错误。0 与 1 都产出有效 JSON 快照，必须放行进入复算；仅 2（或
# 其它异常码）阻断——与 GUI 把 exit 2 显示为「工具运行失败」横幅的语义一致。
set +e
python3 "${ROOT}/scan.py" "${CONFIG_FLAG[@]+"${CONFIG_FLAG[@]}"}" --all-profiles --format json >"$SNAPSHOT_JSON" 2>/dev/null
SCAN_RC=$?
set -e
if [ "$SCAN_RC" -eq 2 ]; then
  echo "FAIL: CLI 运行/配置错误（exit 2），未产出有效快照" >&2
  exit 1
elif [ "$SCAN_RC" -ne 0 ] && [ "$SCAN_RC" -ne 1 ]; then
  echo "FAIL: CLI 异常退出（exit ${SCAN_RC}），未产出有效快照" >&2
  exit 1
fi

PYTHONPATH="${ROOT}/core" python3 - "$SNAPSHOT_JSON" <<'PY'
import json
import sys

from gui_consistency import verify_snapshot  # noqa: E402

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as handle:
    raw = handle.read()
try:
    snapshot = json.loads(raw)
except json.JSONDecodeError as exc:
    print(f"FAIL: CLI 未产出有效 JSON: {exc}")
    sys.exit(1)

violations = verify_snapshot(snapshot)
if violations:
    print("FAIL: GUI/CLI 结论不一致（{} 处违规）:".format(len(violations)))
    for v in violations:
        print("  - " + v)
    sys.exit(1)

print(
    "OK: GUI/CLI 审计结论完全一致（{} profiles, {} results）".format(
        len(snapshot.get("profiles", [])), len(snapshot.get("results", []))
    )
)
PY
