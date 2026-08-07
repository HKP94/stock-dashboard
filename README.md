# ATLAS — 개인 주식 인텔리전스 대시보드

KR/US 관심종목을 **수집 → 지표·퀀트 → Gemini 요약 → 대시보드**로 매일 정리한다.
설계·계약·수용 기준의 SSOT는 [`PRD.md`](PRD.md), 빌더 지침은 [`CLAUDE.md`](CLAUDE.md).

> 표시 신호는 근거·신뢰도를 포함하며 자동 주문을 실행하지 않습니다.

---

## 운영 방식 (한눈에)

| 구분 | 누가 | 언제 | 무엇을 |
|---|---|---|---|
| **DB 최신화** | GitHub Actions (자동) | 매일 06:00·18:00 KST | 가격·재무·뉴스 수집 + 지표·퀀트 + Gemini 요약 → **Supabase DB** |
| **화면 보기** | 집 PC (수동) | 볼 때마다 | `./start_dashboard.sh` 한 번 → DB에서 `data.json` 최신화 + 대시보드 자동 오픈 |

- **DB는 클라우드(Supabase)에 있고 CI가 매일 자동으로 채운다.** 집 PC는 켜둘 필요 없다.
- **대시보드는 집 PC에서만** 본다(외부 접근·상시 서버 불필요). 볼 때 스크립트 한 번 실행하면 그 시점 최신 DB로 화면이 뜬다.

---

## 매일 사용법 (집 PC)

```bash
./start_dashboard.sh
```
또는 Finder에서 **`start_dashboard.command` 더블클릭**.

스크립트가 하는 일:
1. `.venv` 활성화
2. `python -m src.export_dashboard_data` — DB → `dashboard-web/src/data.json` 최신화
3. `local_api`(127.0.0.1:8765) + `vite`(5173) 기동 (이미 떠 있으면 재사용)
4. 기본 브라우저로 `http://localhost:5173` 자동 오픈

- 헤더의 **"데이터 생성: …"** 가 지금 보는 데이터의 시각이다. 생성 후 2일 이상 지나면 화면 상단에 옅은 경고가 뜨니, 스크립트를 다시 실행하면 된다.
- 종료: `./stop_dashboard.sh`

---

## 최초 1회 설정

### 1) 로컬 (집 PC)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd dashboard-web && npm install && cd ..
```

DB 접속 정보는 `.streamlit/secrets.toml` 에 둔다(예시는 `.streamlit/secrets.toml.example`). **시크릿은 절대 커밋 금지**(gitignore 처리됨).

### 1-b) 로컬 자동화(launchd) 설치

```bash
cd ~/atlas/stock-dashboard
bash scripts/install_local_automation.sh      # ★반드시 bash로. 멱등(재실행 안전)
```

설치되는 잡 4개:

| 라벨 | 시각 | 하는 일 |
|---|---|---|
| `com.atlas.supply-early` | 18:30 | **당일 수급만** 조기 적재(21시 브리핑 전). export 안 함 |
| `com.atlas.local-refresh` | 22:30 · 08:00 | 수급 + 포트폴리오 재계산 + `data.json` export |
| `com.atlas.dashboard` | 로그인 시 | 대시보드 서버 상주 |
| `com.atlas.discovery` | 주 1회 | 관심종목 밖 발굴 스크린 |

**전제조건 (안 지키면 설치가 실패한다)**

1. **`bash`로 실행할 것.** `zsh scripts/...`나 `source`로 실행하면 스크립트가 자기 위치를 못 찾는다(`BASH_SOURCE`는 bash 전용). 지금은 `exit 2` + 원인 안내가 나오지만, 그냥 `bash`를 쓰는 게 맞다.
2. **리포가 `~/Desktop`·`~/Documents`·`~/Downloads` 아래에 있으면 안 된다.** macOS 프라이버시(TCC) 보호 폴더라 launchd가 파일을 실행하지 못하고(`Operation not permitted`, exit 126) 잡이 즉시 죽는다. 스크립트가 경고하지만 **plist로는 우회 불가** — 리포를 `~/atlas` 같은 비보호 경로로 옮기거나, 시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근에 `/bin/bash`를 추가한다.
3. **`.venv`가 만들어져 있어야 한다**(위 1) 단계). 잡은 `.venv/bin/python`을 절대경로로 실행하므로 셸 PATH와 무관하다.

**종료코드**: `0` 정상 · `2` 리포 경로 해석 실패(셸 문제) · `3` `.venv` 없음 · `4` `launchctl bootstrap` 실패 · `5` 설치는 됐으나 잡 실행 실패(TCC 등).

**확인·수동 실행**

```bash
launchctl list | grep com.atlas                              # 4잡 (2열=최근 종료코드, 0이 정상)
launchctl kickstart -k gui/$(id -u)/com.atlas.supply-early   # 즉시 1회 실행
tail -f ~/atlas_logs/launchd_supply_early.err                # 실행 로그
```

제거는 `bash scripts/uninstall_local_automation.sh`.

### 2) GitHub Actions Secrets (DB 자동 최신화용)

리포 **Settings → Secrets and variables → Actions → New repository secret** 에서 등록:

| Secret 이름 | 용도 | 필수 |
|---|---|---|
| `DB_PASSWORD` | Supabase Postgres 비밀번호 | ✅ |
| `DART_API_KEY` | KR 재무(DART) | ✅(KR) |
| `GEMINI_API_KEY` | **뉴스·시황 Gemini 요약** | ✅(요약) |

- **`GEMINI_API_KEY` 가 없으면** CI의 enrich 단계가 실패하고 요약이 **중립 폴백**으로 채워진다(화면엔 규칙기반 한 줄로 표시되어 "분석 실패"가 노출되진 않음). 풍부한 요약을 원하면 반드시 등록.
- Gemini 키는 **일일 쿼터**가 있다. 파이프라인(06시·18시)이 유일 소비자가 되도록, 로컬에서 ad-hoc 호출로 쿼터를 태우지 말 것.

---

## 자동 워크플로 (`.github/workflows/`)

| 워크플로 | 스케줄(KST) | 하는 일 |
|---|---|---|
| `auto_run.yml` | 06:00 | 전체 파이프라인(시장·KR·US 수집 → 지표·퀀트 → Gemini 요약 → 포트폴리오·백테스트·조립) |
| `news_refresh.yml` | 18:00 | 경량 가격 갱신(KR 당일종가) + 뉴스 + Gemini 요약 + export |
| `recompute.yml` | 수동 | 기존 가격으로 지표·퀀트만 재계산(복구용) |

- 사용 모델: `GEMINI_BULK_MODEL=gemini-2.5-flash-lite`(종목 요약), `GEMINI_SYNTH_MODEL=gemini-3.5-flash`(시황). 둘 다 현행 Gemini API 유효 모델.
- enrich 성공/실패·폴백 사유는 DB `runs` 테이블에 기록된다.
- 실행 상태 확인: GitHub의 **Actions** 탭, 또는 `gh run list`.

> 참고: CI는 DB만 갱신한다. CI가 만드는 `data.json`은 gitignore 대상이라 집 PC로 오지 않는다 — 그래서 화면 최신화는 집 PC의 `start_dashboard.sh` 가 담당한다.

---

## 테스트

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
```
