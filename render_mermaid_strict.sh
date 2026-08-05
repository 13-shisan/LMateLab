#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

IN="${1:-artifacts/graph.mmd}"

BASE="${2:-artifacts/graph}"
BASE="${BASE%.svg}"
BASE="${BASE%.png}"
SVG_OUT="${BASE}.svg"
PNG_OUT="${BASE}.png"
REPORT_OUT="${BASE}.validate.report.txt"

QUIET="${QUIET:-1}"                  # 1=终端安静；0=显示 mmdc 日志
SCALE="${SCALE:-2}"                  # PNG 清晰度倍率
MERMAID_CFG="${MERMAID_CFG:-artifacts/mermaid.config.json}"
PUP_CFG="${PUP_CFG:-}"
STRICT_TEXT_ONLY="${STRICT_TEXT_ONLY:-1}"  # 1=校验不通过退出2；0=仅警告
FORCE_INIT="${FORCE_INIT:-1}"        # 1=必要时注入 init 强制 htmlLabels:false

fail() { echo "ERROR: $*" >&2; exit 1; }

mmdc() {
  if [[ -n "$PUP_CFG" ]]; then
    npx -y @mermaid-js/mermaid-cli@latest -c "$MERMAID_CFG" -p "$PUP_CFG" "$@"
  else
    npx -y @mermaid-js/mermaid-cli@latest -c "$MERMAID_CFG" "$@"
  fi
}

run() {
  if [[ "$QUIET" == "1" ]]; then
    if ! mmdc "$@" 1>/dev/null 2>&1; then
      # 失败时把真实错误打印出来（否则太难排）
      mmdc "$@"
      exit 1
    fi
  else
    mmdc "$@"
  fi
}

[[ -f "$IN" ]] || fail "input not found: $IN"
[[ -f "$MERMAID_CFG" ]] || fail "mermaid config not found: $MERMAID_CFG"

TMP_IN="$IN"
tmpfile=""
cleanup() { [[ -n "${tmpfile:-}" && -f "${tmpfile:-}" ]] && rm -f "$tmpfile"; }
trap cleanup EXIT

# 若 mmd 顶部已经有 init，就不注入（避免冲突）；否则注入强制 htmlLabels:false
if [[ "$FORCE_INIT" == "1" ]]; then
  if ! head -n 10 "$IN" | grep -q '%%{[[:space:]]*init:'; then
    tmpfile="$(mktemp /tmp/mermaid.XXXXXX.mmd)"
    {
      echo "%%{init: {'flowchart': {'htmlLabels': false}}}%%"
      cat "$IN"
    } > "$tmpfile"
    TMP_IN="$tmpfile"
  fi
fi

# 1) 先生成 SVG + PNG（保证两份都出）
run -i "$TMP_IN" -o "$SVG_OUT"
run -i "$TMP_IN" -o "$PNG_OUT" -s "$SCALE"

# 2) 再校验（不在终端展开长行；写 report）
TEXT_COUNT="$(grep -c '<text' "$SVG_OUT" 2>/dev/null || true)"
FO_COUNT="$(grep -c '<foreignObject' "$SVG_OUT" 2>/dev/null || true)"

: > "$REPORT_OUT"
{
  echo "input=$IN"
  echo "svg=$SVG_OUT"
  echo "png=$PNG_OUT"
  echo "mermaid_cfg=$MERMAID_CFG"
  [[ -n "$PUP_CFG" ]] && echo "puppeteer_cfg=$PUP_CFG"
  echo "text_count=$TEXT_COUNT"
  echo "foreignObject_count=$FO_COUNT"
  echo
  echo "foreignObject line numbers (first 50):"
  # 只输出行号，不输出整行内容（避免刷屏）
  grep -n '<foreignObject' "$SVG_OUT" | cut -d: -f1 | head -n 50 || true
  echo
  echo "mmd has init directive near top? (first 10 lines):"
  head -n 10 "$IN" | nl -ba
} >> "$REPORT_OUT"

if [[ "$FO_COUNT" -gt 0 ]]; then
  msg="SVG contains <foreignObject> ($FO_COUNT). Report written to: $REPORT_OUT"
  if [[ "$STRICT_TEXT_ONLY" == "1" ]]; then
    echo "ERROR: $msg" >&2
    exit 2
  else
    echo "WARN: $msg" >&2
  fi
fi

# 成功时只打印输出路径（两行）
echo "$SVG_OUT"
echo "$PNG_OUT"
