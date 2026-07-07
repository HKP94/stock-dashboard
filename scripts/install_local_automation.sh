#!/usr/bin/env bash
# ATLAS 로컬 자동화 설치 (macOS launchd) — KPH 1회 수동 실행.
#   1) com.atlas.local-refresh : 하루 2회 KRX 수급 수집 + data.json export
#   2) com.atlas.dashboard     : 로그인 시 대시보드 서버 자동 기동
#   3) com.atlas.discovery     : 주간 1회 발굴 스크린(관심종목 밖, 뉴스·LLM 없음)
#
# templates/*.plist.template의 __REPO__/__PY__/__HOME__를 실제 경로로 치환해
# ~/Library/LaunchAgents/에 설치하고 load 한다. 재실행해도 안전(재설치).

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
AGENTS="$HOME/Library/LaunchAgents"
LABELS=(com.atlas.local-refresh com.atlas.dashboard com.atlas.discovery)

[ -x "$PY" ] || { echo "✗ .venv 없음: $PY — 먼저 venv+requirements 설치"; exit 1; }
mkdir -p "$AGENTS" "$HOME/atlas_logs"

# ── macOS 프라이버시(TCC) 사전 점검 ──────────────────────────────────
# launchd 에이전트는 ~/Desktop·~/Documents·~/Downloads 아래 파일을 실행/접근할 수 없다
# (TCC 보호 → "Operation not permitted", exit 126). bootstrap은 성공해도 잡이 즉시 죽는다.
# plist를 고쳐도 우회 불가 — 리포 이동 또는 전체 디스크 접근(FDA) 부여가 필요하다.
TCC_RISK=0
case "$REPO/" in
  "$HOME/Desktop/"*|"$HOME/Documents/"*|"$HOME/Downloads/"*)
    TCC_RISK=1
    echo "⚠️  리포가 macOS 프라이버시 보호 폴더 아래에 있습니다:"
    echo "      $REPO"
    echo "    launchd가 여기 파일을 실행할 수 없어(Operation not permitted·exit 126) 잡이 즉시 죽습니다."
    echo "    해결(둘 중 하나):"
    echo "      ① 리포를 비보호 경로로 이동(권장): 예) mv \"$REPO\" ~/atlas  후 거기서 재설치"
    echo "      ② 시스템 설정 > 개인정보 보호 및 보안 > 전체 디스크 접근에 /bin/bash 추가 후 재실행"
    echo ""
    ;;
esac

for label in "${LABELS[@]}"; do
  tpl="$REPO/templates/$label.plist.template"
  dst="$AGENTS/$label.plist"
  [ -f "$tpl" ] || { echo "✗ 템플릿 없음: $tpl"; exit 1; }
  sed -e "s#__REPO__#$REPO#g" -e "s#__PY__#$PY#g" -e "s#__HOME__#$HOME#g" "$tpl" > "$dst"
  plutil -lint "$dst" >/dev/null || { echo "✗ plist 문법 오류: $dst"; exit 1; }
  # 이미 로드돼 있으면 먼저 언로드(재설치 안전)
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$dst"
  echo "✓ bootstrap: $label"
done

# ── 헬스 체크: bootstrap 성공 ≠ 실행 성공. RunAtLoad 잡(dashboard)의 실제 종료코드를 확인해
#    거짓 성공(126/127 등)을 드러낸다. RunAtLoad=false(local-refresh·discovery)는 스케줄 실행이라 스킵.
sleep 2
FAILED=0
for label in "${LABELS[@]}"; do
  st="$(launchctl list | awk -v l="$label" '$3==l {print $2}')"
  case "$st" in
    ""|"-"|0) : ;;                                  # 미실행(스케줄 대기) 또는 정상
    126|127)
      FAILED=1
      echo "✗ $label 로드됐으나 실행 실패(exit $st) — 위 프라이버시(TCC) 경고 참고. ~/atlas_logs/launchd_*.err 확인"
      ;;
    *) echo "! $label 최근 종료코드 $st — ~/atlas_logs/launchd_*.err 확인" ;;
  esac
done

echo ""
if [ "$FAILED" = 1 ] || [ "$TCC_RISK" = 1 ]; then
  echo "⚠️  일부 잡이 실행되지 않습니다(위 참고). 리포 이동/FDA 해결 후 이 스크립트를 다시 실행하세요."
else
  echo "완료."
fi
echo "확인:"
echo "  launchctl list | grep com.atlas   (3열=라벨, 2열=최근 종료코드·0이 정상)"
echo "  즉시 수급 테스트:  launchctl kickstart -k gui/$(id -u)/com.atlas.local-refresh"
echo "  로그:  ~/atlas_logs/local_refresh_YYYYMMDD.log  ·  상태: ~/atlas_logs/local_refresh_state.json"
