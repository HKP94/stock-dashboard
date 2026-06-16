#!/usr/bin/env bash
# ATLAS 대시보드 종료 — local_api(8765) + vite(5173) 백그라운드 프로세스 정리
set -uo pipefail
for port in 5173 8765; do
  pids=$(lsof -ti ":$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    kill $pids 2>/dev/null && echo "✓ 포트 $port 종료 (PID: $pids)"
  else
    echo "· 포트 $port 실행 중 아님"
  fi
done
