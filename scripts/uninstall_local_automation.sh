#!/usr/bin/env bash
# ATLAS 로컬 자동화 제거 — launchd 에이전트 언로드 + plist 삭제.
# (수급 수집·대시보드 자동기동을 멈춘다. 로그·상태파일은 남긴다.)

set -uo pipefail

AGENTS="$HOME/Library/LaunchAgents"
LABELS=(com.atlas.local-refresh com.atlas.supply-early com.atlas.dashboard com.atlas.discovery)

for label in "${LABELS[@]}"; do
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null && echo "✓ 언로드: $label" || echo "· 이미 언로드됨: $label"
  rm -f "$AGENTS/$label.plist" && echo "✓ plist 삭제: $label.plist"
done

echo "완료. (대시보드 서버가 이미 떠 있으면 ./stop_dashboard.sh로 종료)"
