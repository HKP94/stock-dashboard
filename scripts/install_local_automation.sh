#!/usr/bin/env bash
# ATLAS 로컬 자동화 설치 (macOS launchd) — KPH 1회 수동 실행.
#   1) com.atlas.local-refresh : 하루 2회 KRX 수급 수집 + data.json export
#   2) com.atlas.dashboard     : 로그인 시 대시보드 서버 자동 기동
#
# templates/*.plist.template의 __REPO__/__PY__/__HOME__를 실제 경로로 치환해
# ~/Library/LaunchAgents/에 설치하고 load 한다. 재실행해도 안전(재설치).

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
AGENTS="$HOME/Library/LaunchAgents"
LABELS=(com.atlas.local-refresh com.atlas.dashboard)

[ -x "$PY" ] || { echo "✗ .venv 없음: $PY — 먼저 venv+requirements 설치"; exit 1; }
mkdir -p "$AGENTS" "$HOME/atlas_logs"

for label in "${LABELS[@]}"; do
  tpl="$REPO/templates/$label.plist.template"
  dst="$AGENTS/$label.plist"
  [ -f "$tpl" ] || { echo "✗ 템플릿 없음: $tpl"; exit 1; }
  sed -e "s#__REPO__#$REPO#g" -e "s#__PY__#$PY#g" -e "s#__HOME__#$HOME#g" "$tpl" > "$dst"
  plutil -lint "$dst" >/dev/null || { echo "✗ plist 문법 오류: $dst"; exit 1; }
  # 이미 로드돼 있으면 먼저 언로드(재설치 안전)
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$dst"
  echo "✓ 설치·로드: $label"
done

echo ""
echo "완료. 확인:"
echo "  launchctl list | grep com.atlas"
echo "  즉시 수급 테스트:  launchctl kickstart -k gui/$(id -u)/com.atlas.local-refresh"
echo "  로그:  ~/atlas_logs/local_refresh_YYYYMMDD.log  ·  상태: ~/atlas_logs/local_refresh_state.json"
