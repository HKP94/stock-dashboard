#!/usr/bin/env bash
# ATLAS 대시보드 원클릭 기동 (macOS / 집 PC 전용)
#
# 하는 일:
#   1) .venv 활성화
#   2) DB → data.json 최신화 (python -m src.export_dashboard_data)
#   3) local_api(127.0.0.1:8765) + vite(5173) 기동 (이미 떠 있으면 재사용)
#   4) http://localhost:5173 기본 브라우저로 자동 오픈
#
# 매일: 이 스크립트를 한 번 실행하면 최신 데이터로 대시보드가 열립니다.
#   - DB 자체는 GitHub Actions가 매일 자동 최신화하므로, 여기서는 DB→화면만 갱신합니다.
#
# 사용: ./start_dashboard.sh   (또는 start_dashboard.command 더블클릭)

set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YLW=$'\033[0;33m'; NC=$'\033[0m'
say()  { printf "%s\n" "$1"; }
ok()   { printf "${GRN}✓ %s${NC}\n" "$1"; }
warn() { printf "${YLW}! %s${NC}\n" "$1"; }
err()  { printf "${RED}✗ %s${NC}\n" "$1"; }

port_up() { lsof -ti ":$1" >/dev/null 2>&1; }
wait_for_port() {  # $1=port $2=timeout_sec
  local p="$1" t="${2:-30}" i=0
  while ! port_up "$p"; do
    sleep 1; i=$((i+1))
    [ "$i" -ge "$t" ] && return 1
  done
  return 0
}

say "──────────────────────────────────────────"
say " ATLAS 대시보드 기동"
say "──────────────────────────────────────────"

# 1) venv
if [ ! -x "$DIR/.venv/bin/python" ]; then
  err ".venv 가상환경이 없습니다: $DIR/.venv"
  err "먼저 'python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt' 를 실행하세요."
  exit 1
fi
PY="$DIR/.venv/bin/python"
ok "가상환경 확인"

# 2) DB → data.json 최신화
say "DB에서 최신 데이터를 받아오는 중… (수 초 소요)"
if "$PY" -m src.export_dashboard_data; then
  ok "data.json 최신화 완료"
else
  if [ -f "$DIR/dashboard-web/src/data.json" ]; then
    warn "최신화 실패(DB 접속/네트워크 확인) — 이전 데이터로 표시합니다."
    warn "DB 접속 정보는 .streamlit/secrets.toml 을 확인하세요."
  else
    err "최신화 실패 + 표시할 데이터(data.json)도 없습니다. DB 접속을 확인하세요."
    err "확인: .streamlit/secrets.toml 의 DB_HOST/DB_USER/DB_PASSWORD"
    exit 1
  fi
fi

# 3) local_api (8765)
if port_up 8765; then
  ok "local_api 이미 실행 중 (8765)"
else
  say "local_api 기동 중 (8765)…"
  nohup "$PY" -m src.local_api >"$DIR/.local_api.log" 2>&1 &
  if wait_for_port 8765 15; then ok "local_api 기동"; else warn "local_api 응답 지연 — .local_api.log 확인"; fi
fi

# 4) vite (5173)
if port_up 5173; then
  ok "vite 이미 실행 중 (5173)"
else
  if [ ! -d "$DIR/dashboard-web/node_modules" ]; then
    say "프론트 의존성 설치 중 (최초 1회)…"
    ( cd "$DIR/dashboard-web" && npm install ) || { err "npm install 실패"; exit 1; }
  fi
  say "대시보드(vite) 기동 중 (5173)…"
  ( cd "$DIR/dashboard-web" && nohup npm run dev >"$DIR/.vite.log" 2>&1 & )
  if wait_for_port 5173 40; then ok "대시보드 기동"; else err "대시보드 기동 실패 — .vite.log 확인"; exit 1; fi
fi

# 5) 브라우저 오픈
sleep 1
open "http://localhost:5173"
say "──────────────────────────────────────────"
ok "준비 완료 → http://localhost:5173"
say "  · 서버는 백그라운드에서 계속 실행됩니다."
say "  · 종료하려면: ./stop_dashboard.sh (또는 포트 5173·8765 프로세스 종료)"
say "──────────────────────────────────────────"
