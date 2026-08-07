#!/usr/bin/env bash
# ATLAS 로컬 자동화 설치 (macOS launchd) — KPH 1회 수동 실행.
#   1) com.atlas.local-refresh : 하루 2회(22:30·08:00) 수급 수집 + 포트폴리오 재계산 + data.json export
#   1-b) com.atlas.supply-early : 18:30 당일 수급만 조기 적재(21시 브리핑 전). 확정시각 실측 18:05 근거
#   2) com.atlas.dashboard     : 로그인 시 대시보드 서버 자동 기동
#   3) com.atlas.discovery     : 주간 1회 발굴 스크린(관심종목 밖, 뉴스·LLM 없음)
#
# templates/*.plist.template의 __REPO__/__PY__/__HOME__를 실제 경로로 치환해
# ~/Library/LaunchAgents/에 설치하고 load 한다. 재실행해도 안전(재설치).

set -euo pipefail

# ── 리포 경로 해석 (셸 이식성) ────────────────────────────────────────
# ${BASH_SOURCE[0]}는 **bash 전용**이다. KPH 기본 셸이 zsh라 `zsh scripts/...`로 실행하면
# 이 변수가 비어 REPO가 "/"로 접히고, 그 결과 "✗ .venv 없음: //.venv/bin/python"이라는
# **엉뚱한 진단**(venv는 멀쩡한데 없다고 함)이 나온다 — 실제 KPH 설치 실패 원인이었다.
# ${BASH_SOURCE[0]:-$0}는 bash·zsh·sh 모두에서 스크립트 경로를 준다.
_SRC="${BASH_SOURCE[0]:-$0}"
REPO="$(cd "$(dirname "$_SRC")/.." 2>/dev/null && pwd)" || REPO=""
PY="$REPO/.venv/bin/python"
AGENTS="$HOME/Library/LaunchAgents"
LABELS=(com.atlas.local-refresh com.atlas.supply-early com.atlas.dashboard com.atlas.discovery)

# 경로 해석 실패를 venv 문제로 오진하지 않도록 **먼저** 검증한다(리포 표지로 확인).
if [ -z "$REPO" ] || [ ! -d "$REPO/templates" ] || [ ! -f "$REPO/scripts/local_refresh.py" ]; then
  echo "✗ 리포 경로 해석 실패: REPO='$REPO'"
  echo "  스크립트 위치를 못 찾았습니다(셸 호환 문제일 수 있음)."
  echo "  해결: 리포 루트에서 아래처럼 bash로 실행하세요."
  echo "      cd ~/atlas/stock-dashboard && bash scripts/install_local_automation.sh"
  exit 2
fi

if [ ! -x "$PY" ]; then
  echo "✗ 파이썬 실행파일 없음: $PY"
  echo "  리포는 찾았으므로($REPO) 가상환경만 없는 상태입니다."
  echo "  해결: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 3
fi
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
  # bootstrap 실패를 삼키지 않는다 — set -e로 조용히 중단되면 원인을 알 수 없다.
  if ! err="$(launchctl bootstrap "gui/$(id -u)" "$dst" 2>&1)"; then
    echo "✗ launchctl bootstrap 실패: $label"
    echo "  launchctl 메시지: ${err:-(없음)}"
    echo "  plist: $dst"
    echo "  흔한 원인: 이전 잡이 남아 있음(재실행하면 해소) · plist 경로/권한 문제"
    exit 4
  fi
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
  echo "⚠️  설치는 됐지만 일부 잡이 실행되지 않습니다(위 참고)."
  echo "    리포 이동/FDA 해결 후 이 스크립트를 다시 실행하세요."
  RC=5
else
  echo "완료 — 잡 ${#LABELS[@]}개 설치됨 (exit 0)."
  RC=0
fi
echo "확인:"
echo "  launchctl list | grep com.atlas   (3열=라벨, 2열=최근 종료코드·0이 정상)"
echo "  즉시 수급 테스트:  launchctl kickstart -k gui/$(id -u)/com.atlas.supply-early"
echo "  로그:  ~/atlas_logs/launchd_supply_early.err · ~/atlas_logs/local_refresh_YYYYMMDD.log"
exit "$RC"
