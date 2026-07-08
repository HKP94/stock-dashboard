#!/usr/bin/env bash
# ATLAS 대시보드 상주 supervisor (launchd 로그인 에이전트용)
#
# start_dashboard.sh의 서버 부분만 — export·브라우저 오픈 없이 local_api(8765)+vite(5173)를
# 기동하고, 이후 포어그라운드로 상주하며 크래시된 서버를 자동 재기동한다.
# launchd(com.atlas.dashboard)가 로그인 시 호출(RunAtLoad) + KeepAlive로 이 스크립트 자체도 복구.
# export/data.json 갱신은 local_refresh.py(launchd 스케줄, 하루 2회)가 담당하므로 여기선 안 한다.
#
# 바인딩: local_api=127.0.0.1, vite=기본(localhost) — 둘 다 로컬 전용, 외부 노출 없음(--host 금지).

set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

PY="$DIR/.venv/bin/python"
[ -x "$PY" ] || { echo "✗ .venv 없음: $DIR/.venv"; exit 1; }

port_up() { lsof -ti ":$1" >/dev/null 2>&1; }
wait_for_port() { local p="$1" t="${2:-30}" i=0; while ! port_up "$p"; do sleep 1; i=$((i+1)); [ "$i" -ge "$t" ] && return 1; done; return 0; }

start_local_api() {
  echo "local_api 기동 중 (8765)…"
  nohup "$PY" -m src.local_api >"$DIR/.local_api.log" 2>&1 &
  wait_for_port 8765 15 && echo "✓ local_api 기동" || echo "! local_api 응답 지연 — .local_api.log 확인"
}

start_vite() {
  if [ ! -d "$DIR/dashboard-web/node_modules" ]; then
    echo "프론트 의존성 설치 (최초 1회)…"
    ( cd "$DIR/dashboard-web" && npm install ) || { echo "✗ npm install 실패"; return 1; }
  fi
  echo "vite 기동 중 (5173)…"
  ( cd "$DIR/dashboard-web" && nohup npm run dev >"$DIR/.vite.log" 2>&1 & )
  wait_for_port 5173 40 && echo "✓ vite 기동" || echo "! vite 기동 지연 — .vite.log 확인"
}

# 최초 기동(포트 가드로 idempotent — 이미 떠 있으면 스킵)
port_up 8765 && echo "✓ local_api 이미 실행 중 (8765)" || start_local_api
port_up 5173 && echo "✓ vite 이미 실행 중 (5173)" || start_vite

echo "✓ 대시보드 준비 완료 → http://localhost:5173 (상주 감시 시작)"

# 상주 감시: 15초마다 포트 점검, 크래시된 서버만 재기동. 서버는 nohup이라 이 루프와 독립.
# 이 스크립트가 죽으면 launchd KeepAlive가 재실행 → 여기서 다시 포트 점검(살아있으면 no-op).
while true; do
  sleep 15
  port_up 8765 || { echo "$(date '+%F %T') local_api 다운 감지 → 재기동"; start_local_api; }
  port_up 5173 || { echo "$(date '+%F %T') vite 다운 감지 → 재기동"; start_vite; }
done
