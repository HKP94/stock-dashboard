#!/usr/bin/env bash
# ATLAS 대시보드 서버 idempotent 기동 (launchd 로그인 에이전트용)
#
# start_dashboard.sh의 서버 부분만 — export·브라우저 오픈 없이 local_api(8765)+vite(5173)를
# "떠 있지 않을 때만" 기동한다. launchd(com.atlas.dashboard)가 로그인 시 호출.
# export/data.json 갱신은 local_refresh.py(launchd 스케줄)가 담당하므로 여기선 안 한다.
#
# ponytail: 로그인-기동 + 포트 가드로 충분(개인 대시보드). 서버 크래시 자동복구까지 필요하면
#           plist에 KeepAlive=true + 이 스크립트를 foreground wait로 바꾸는 게 업그레이드 경로.

set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

PY="$DIR/.venv/bin/python"
[ -x "$PY" ] || { echo "✗ .venv 없음: $DIR/.venv"; exit 1; }

port_up() { lsof -ti ":$1" >/dev/null 2>&1; }
wait_for_port() { local p="$1" t="${2:-30}" i=0; while ! port_up "$p"; do sleep 1; i=$((i+1)); [ "$i" -ge "$t" ] && return 1; done; return 0; }

# local_api (8765)
if port_up 8765; then
  echo "✓ local_api 이미 실행 중 (8765)"
else
  echo "local_api 기동 중 (8765)…"
  nohup "$PY" -m src.local_api >"$DIR/.local_api.log" 2>&1 &
  wait_for_port 8765 15 && echo "✓ local_api 기동" || echo "! local_api 응답 지연 — .local_api.log 확인"
fi

# vite (5173)
if port_up 5173; then
  echo "✓ vite 이미 실행 중 (5173)"
else
  if [ ! -d "$DIR/dashboard-web/node_modules" ]; then
    echo "프론트 의존성 설치 (최초 1회)…"
    ( cd "$DIR/dashboard-web" && npm install ) || { echo "✗ npm install 실패"; exit 1; }
  fi
  echo "vite 기동 중 (5173)…"
  ( cd "$DIR/dashboard-web" && nohup npm run dev >"$DIR/.vite.log" 2>&1 & )
  wait_for_port 5173 40 && echo "✓ vite 기동" || { echo "✗ vite 기동 실패 — .vite.log 확인"; exit 1; }
fi

echo "✓ 대시보드 서버 준비 완료 → http://localhost:5173"
