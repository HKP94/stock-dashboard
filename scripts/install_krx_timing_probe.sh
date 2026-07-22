#!/usr/bin/env bash
# KRX 수급 확정시각 실측용 임시 launchd 잡 설치 (PR-B 항목5 선행).
#
# 16·17·18·19·20·22시 KST에 샘플을 떠서 값이 언제 굳는지 잰다.
# **측정이 끝나면 반드시 제거**: ./scripts/install_krx_timing_probe.sh --uninstall
set -euo pipefail

LABEL="com.atlas.krx-timing-probe"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
  rm -f "$PLIST"
  echo "제거 완료: $LABEL"
  exit 0
fi

if [[ ! -x "$REPO/.venv/bin/python" ]]; then
  echo "오류: $REPO/.venv/bin/python 없음" >&2
  exit 1
fi

mkdir -p "$HOME/atlas_logs"

{
  echo '<?xml version="1.0" encoding="UTF-8"?>'
  echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
  echo '<plist version="1.0"><dict>'
  echo "  <key>Label</key><string>${LABEL}</string>"
  echo '  <key>ProgramArguments</key><array>'
  echo "    <string>${REPO}/.venv/bin/python</string>"
  echo "    <string>${REPO}/scripts/probe_krx_flow_timing.py</string>"
  echo '  </array>'
  echo "  <key>WorkingDirectory</key><string>${REPO}</string>"
  echo '  <key>StartCalendarInterval</key><array>'
  for h in 16 17 18 19 20 22; do
    echo "    <dict><key>Hour</key><integer>${h}</integer><key>Minute</key><integer>5</integer></dict>"
  done
  echo '  </array>'
  echo "  <key>StandardOutPath</key><string>${HOME}/atlas_logs/krx_timing_probe.log</string>"
  echo "  <key>StandardErrorPath</key><string>${HOME}/atlas_logs/krx_timing_probe.log</string>"
  echo '  <key>RunAtLoad</key><false/>'
  echo '</dict></plist>'
} > "$PLIST"

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "설치 완료: $LABEL (16·17·18·19·20·22시 KST)"
echo "  분석:   .venv/bin/python scripts/probe_krx_flow_timing.py --report"
echo "  제거:   ./scripts/install_krx_timing_probe.sh --uninstall"
echo "※ 2~3거래일 모은 뒤 제거할 것 — 상시 잡이 아니다."
