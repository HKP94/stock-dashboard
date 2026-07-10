# START_HERE.md — ATLAS 실행 런북

> 목적: "무엇을 결정하고, 무엇을 발급하고, 어떻게 세팅하고, 각 AI에게 어떻게 지시하는지"를 순서대로. 위에서부터 체크하며 진행한다. 설계 근거는 `PRD.md`.

## 작업 진행 방식 한눈에
```
[너] 결정 확정 → [너] 키 발급 + 환경 세팅 → [너→Claude Code] 킥오프 프롬프트 투입
   → [Claude Code] PR 제출 → [너] 실행/테스트 → [너→PM(이 대화)] 결과 보고
   → [PM] 계약 기준 검수 + 다음 작업 지시 → 반복
```
- **PM(이 대화의 Claude)** = 설계·계약·검수·다음 지시.  **Claude Code** = 실제 코드.  **Gemini** = 코드가 호출하는 요약기.  **Hermes** = (Phase 3) 메모리+텔레그램.
- 한 번에 하나의 작업(PR)만. 다 만들고 한꺼번에 합치지 않는다.

---

## STEP 0 — 결정 (추천 기본값 그대로 가도 됨)
아래 기본값이면 막힘 없이 시작 가능. 바꾸고 싶은 항목만 PM에게 알려주면 PRD에 반영한다.

| # | 항목 | 추천 기본값 | 이유 / 메모 |
|---|---|---|---|
| 1 | **F1 계좌현황** | 수동 보유 + 자동 시세 | 수량/평단만 거래 시 입력, 평가손익은 자동. KB 개인 API 여부만 1회 확인 |
| 2 | **KR 데이터(F2/F3)** | pykrx(무key) + DART(무료) | yfinance KR 의존 제거. KIS는 선택(실시간 장중/향후 확장 시) |
| 3 | **US 데이터** | yfinance + (선택)Finnhub 무료 | 컨센서스 부실하면 그때 Finnhub/FMP 추가 |
| 4 | **n8n 호스팅** | 상시 PC 있으면 self-host(Docker), 없으면 n8n Cloud | 상시 켜둘 기기 유무로 결정 |
| 5 | **DB** | Supabase Postgres(무료) | self-host/Cloud 양쪽 호환, 서버관리 불필요 |
| 6 | **Hermes 도입 시점** | **Phase 3**에 클라우드 모델로 추가 | v1 브리핑은 n8n+Gemini로 먼저 출시(복잡도 분산) |
| 7 | **관심종목** | 기존 34종목 유지 | 추후 watchlist 테이블에서 추가/삭제 |
| 8 | **알림 채널** | 텔레그램만, 장중 알림은 P2 | 아침 브리핑 먼저, 장중 알림은 나중 |

> 핵심 판단 2개만 정하면 됨: **(4) 상시 켜둘 기기가 있나? (6) Hermes를 처음부터 쓸까 나중에 붙일까?** 나머지는 기본값 권장.

---

## STEP 1 — 네가 발급할 것 (계정/키)
무료부터. 발급한 키는 **절대 코드/시트/문서에 평문으로 두지 말고** 메모장에 임시 보관 → 나중에 `.env`/n8n Credentials로 이동.

- [ ] **DART OpenAPI 인증키** (KR 재무·공시, 무료) — opendart.fss.or.kr → 인증키 신청. (거의 즉시 발급)
- [ ] **Gemini API 키** (무료 티어 있음) — aistudio.google.com → Get API key.
- [ ] **텔레그램 봇 토큰 + 내 chat_id** — 텔레그램에서 `@BotFather` → `/newbot` → 토큰. chat_id는 `@userinfobot`에게 말 걸면 알려줌.
- [ ] (선택) **Finnhub 또는 FMP 무료 키** — US 컨센서스 보강용. 없으면 yfinance로 시작.
- [ ] (선택) **KIS Developers appkey/appsecret** — 한국투자증권 계좌 보유 시, KIS Developers에서 앱 등록. *F1 해결용 아님*(시세/장중/확장용).
- [ ] **Google 서비스계정 JSON** — 기존 시트 연동에 쓰던 `GCP_SERVICE_ACCOUNT` 재사용(Sheets 미러용).
- [ ] (KB 확인) KB증권 고객센터에 "개인이 본인 계좌 잔고를 OpenAPI로 조회 가능한지" 1회 문의.

---

## STEP 2 — 환경 세팅 (둘 중 하나)

### 경로 A — self-host (상시 켜둘 PC/미니PC/홈서버가 있을 때, 비용 최소)
- [ ] Docker / Docker Compose 설치
- [ ] `docker-compose.yml`로 **n8n + Postgres** 컨테이너 기동 (Claude Code에게 작성 요청 가능)
- [ ] n8n 웹UI 접속 → 위 키들을 **Credentials**로 등록

### 경로 B — 노옵스 (상시 기기 없음)
- [ ] **n8n Cloud** 가입(Starter)
- [ ] **Supabase** 가입 → 새 프로젝트(무료 Postgres) → 연결 문자열 확보
- [ ] n8n Cloud에 Postgres·Gemini·Telegram Credentials 등록

### 공통
- [ ] GitHub 새 리포지토리 생성(또는 기존 리포 새 브랜치) → `PRD.md`, `CLAUDE.md`, `prompts/`, `START_HERE.md` 커밋
- [ ] 로컬에 Python 3.12 + 가상환경
- [ ] `.env.example` 작성(키 *이름만*), `.env`는 `.gitignore`

---

## STEP 3 — 각 AI에게 지시하는 법

### 3-1. Claude Code (빌더) — 가장 많이 쓰는 도구
- 리포지토리를 연 상태에서 실행(루트에 `PRD.md`·`CLAUDE.md`가 있어야 자동으로 읽음).
- **작업 단위로** 아래 킥오프 프롬프트를 던진다. 한 PR 끝나면 다음 프롬프트.
- 막히거나 설계를 바꿔야 하면 코드에 `# TODO(PM):`로 남기게 돼 있음 → 그 부분을 PM에 보고.

**▶ 킥오프 프롬프트 #1 (Phase 0~1 기반: 스키마·DB·DDL)** — 복붙용
```
이 리포의 PRD.md와 CLAUDE.md를 먼저 읽어. 너는 빌더다(0번 절대규칙 준수: 시크릿/자동주문 금지, 계약 준수).
아래를 한 PR로 만들어줘:
1) requirements.txt, .env.example(키 이름만), .gitignore
2) src/schemas.py : PRD §5.2(종목 일일 레코드)와 §5.3(LLM 입출력 A/B)을 pydantic v2 모델로
3) src/db.py : Postgres 연결 + upsert 헬퍼 + log_run(). 환경변수에서만 접속정보 읽기
4) PRD §5.1 DDL을 db/schema.sql 로 정리(실행 가능하게)
PR 본문에 '무엇을/왜/어떻게 검증' 적어줘. 외부 네트워크/LLM 호출은 이 PR에 넣지 마.
```

**▶ 킥오프 프롬프트 #2 (Phase 1: KR/US 수집 + 지표)** — #1 머지 후
```
PRD.md, CLAUDE.md 기준으로 다음을 PR로 만들어줘:
1) src/ingest_kr.py : 가격=pykrx, 재무=DART OpenAPI. (KIS는 아직 X) 결측은 None으로(문자열 'N/A' 금지)
2) src/ingest_us.py : 가격/재무=yfinance 폴백 기반(키 없는 무료 경로부터)
3) src/compute_indicators.py : 기존 main.py의 SMA20/50/200·RSI14·이격도·정배열 로직 이식 + 추세기울기. tests/로 단위테스트
모든 수집은 종목 단위 try/except로 격리하고 실패는 runs.errors에 남겨. 1~2 종목 스모크 테스트 포함.
```
> 기존 `main.py`를 같은 리포에 넣어두면 Claude Code가 로직을 참고·이식하기 쉽다.

### 3-2. Gemini (요약기) — 사람이 직접 채팅하지 않음
- Gemini는 `src/enrich_gemini.py`가 `prompts/GEMINI_PROMPT.md`의 스키마로 **자동 호출**한다(Phase 2). 너는 키만 넣고, 프롬프트 수정이 필요하면 PM과 그 파일을 고친다.
- (선택) AI Studio에서 프롬프트 A/B 테스트는 가능.

### 3-3. Hermes (메모리+전달) — Phase 3
- `prompts/HERMES_PROMPT.md`의 §1을 시스템 프롬프트로, §2·§3을 스킬로 설정.
- 텔레그램 + DB(또는 n8n이 넘긴 JSON) 연결. 클라우드 모델로 시작(브리핑은 저빈도라 토큰 적음).
- v1에서는 생략 가능 — 그동안 브리핑은 n8n Telegram 노드 + Gemini 생성으로.

### 3-4. PM (이 대화)
- 각 PR/실행 결과/에러 로그를 여기 붙여줘. 계약(스키마·DDL) 위반·누락·통합 이슈를 점검하고 다음 작업과 수용기준을 준다.
- 결정 변경 시 PRD 버전을 올려 반영.

---

## STEP 4 — 첫 주 체크리스트 (이대로만)
1. [ ] STEP 0 결정 확정(특히 #4, #6) → PM에 통보
2. [ ] STEP 1에서 DART·Gemini·텔레그램 키 발급
3. [ ] STEP 2에서 DB(Supabase 또는 Docker Postgres) + 리포 + 4개 문서 커밋
4. [ ] Claude Code에 **킥오프 #1** 투입 → PR 받기 → DDL로 테이블 생성
5. [ ] PM에 PR 결과 보고 → 검수 → **킥오프 #2** 안내 받기
6. [ ] 킥오프 #2로 KR/US 수집 + 지표까지 → DB에 첫 데이터 적재 확인
> 여기까지가 "백본 살아있음" 단계. 그다음 PM이 Phase 2(퀀트 점수·뉴스 요약) 작업을 쪼개 준다.

---

## 운영 3층 분업 (현행 모델)
> 역할이 셋으로 나뉜다. 각자 하는 일과 경계가 다르다.

| 층 | 도구 | 하는 일 | 경계 |
|---|---|---|---|
| **화면** | 대시보드(로컬 React) | 데이터 스캔·조회 | 로컬 전용, 외부 접근 없음 |
| **판단 대화** | **Claude 웹(MCP)** | "내 판단" 축 상대 — 관찰·3축 괴리 지적·근거 검증 + **결론을 DB에 기록** | 판단 기록 계열만 **쓰기**, 자동 수집 테이블 **읽기 전용** |
| **개발** | Claude Code | 파이프라인·워크플로·스킬 코드 PR | PR 단위, PM 검수 후 머지 |

**Claude 웹(MCP) 사용 원칙:**
- 역할 = **내 판단 축의 대화 상대**. 종목/시장을 함께 관찰하고, 3축(퀀트·컨센서스·내 판단)이 엇갈리면 괴리를 지적하고 근거를 검증한다. **적극적으로 노트를 남긴다.**
- **판단 기록 원칙(★핵심)**: 대화에서 내린 결론(투자 논거·관찰·주의점)은 반드시 `stock_notes`/`stock_note_history`/`manual_research_*`에 **써서 남긴다**. 다음 세션은 대화 히스토리가 아니라 **DB에서 컨텍스트를 승계**한다 — "지난번에 뭐라 했더라"를 대화 로그에 의존하지 않는다.
- **쓰기 허용**: `stock_notes`, `stock_note_history`, `manual_research_entries/horizons/points/consensus`, `research_items`, `market_view_manual`.
- **읽기 전용(절대 쓰지 말 것)**: `prices_daily`·`indicators_daily`·`quant_scores`·`investor_flow`·`news_analysis`·`signal_grade_track`·`market_score` 등 자동 수집·파이프라인 테이블 — 수집 무결성이 신뢰성의 근간.
- **최종 매매/집행 판단은 KPH.** Claude는 관찰·근거·괴리까지. (투자 자문 아님 / 원금 손실 가능)
- **설정**: MCP는 `project_ref` 스코프 + database 그룹 한정. **Vercel 미사용**(로컬 집중). RLS 미설정은 리스크 수용(로컬 데이터·실자금 아님) — 보안 강화는 우선순위 낮음.

---

## 로컬 자동화 (맥, 한국 IP) — 수급 수집 + 대시보드 상시화
> KRX가 GitHub Actions IP를 차단해 E-2 수급은 CI로 못 받는다. 로컬 launchd가 이것과 화면 갱신을 맡는다. CI(나머지 전부)와 완전 분리 — 로컬이 죽어도 CI 무관.

**⚠️ 전제 — 리포 위치**: launchd 에이전트는 macOS 프라이버시(TCC) 보호 폴더(`~/Desktop`·`~/Documents`·`~/Downloads`) 아래 파일을 실행/접근할 수 없다("Operation not permitted"·exit 126 → bootstrap은 성공해도 잡이 즉시 죽음). **리포는 비보호 경로(예 `~/atlas`, `~/Developer/…`)에 둬야 한다.** `~/Desktop` 등에 있으면 리포를 옮기거나(권장), 시스템 설정 > 개인정보 보호 및 보안 > 전체 디스크 접근에 `/bin/bash`를 추가해야 한다. 설치 스크립트가 이 조건을 감지해 경고·헬스체크한다.

**1회 설치 (KPH):**
```
./scripts/install_local_automation.sh
```
- `com.atlas.local-refresh` : 하루 2회(**22:30** CI KR종가 landing 후 · **08:00** 06시 CI완료후) `local_refresh.py` = KRX 수급 수집 → **포트폴리오 재계산** → `data.json` export(이 순서). 저녁 22:30은 CI news_refresh(18시 크론)가 GitHub 지연으로 ~21:00~22:04 완료돼 KR 당일종가를 적재한 '후'라, export가 당일 KR종가·뉴스·포트폴리오를 반영한다(구 19:10은 landing 전이라 전일치 캡처=대시보드 당일 미반영). RunAtLoad=false(놓친 회차는 다음 스케줄이 ~10일 백필로 커버).
- `com.atlas.dashboard` : 로그인 시 `dashboard_up.sh`로 local_api(8765)+vite(5173) idempotent 기동 → 브라우저 열면 항상 최신, 터미널 타이핑 제로.

**확인·운영:**
- 설치 확인: `launchctl list | grep com.atlas`
- 즉시 수급 테스트: `launchctl kickstart -k gui/$(id -u)/com.atlas.local-refresh`
- 로그: `~/atlas_logs/local_refresh_YYYYMMDD.log` · 상태(신선도): `~/atlas_logs/local_refresh_state.json`(`last_success_utc`·`last_investor_flow_rows`)
- 수동 1회 갱신: `./.venv/bin/python scripts/local_refresh.py`
- 제거: `./scripts/uninstall_local_automation.sh`

**문제 시:**
- 수급이 안 쌓임 → 상태파일 `last_error` 확인. KRX 로그인 실패면 `.env`의 `KRX_ID`/`KRX_PW` 확인(로컬에서만 유효).
- 화면이 옛날 → `local_refresh` 로그의 export 성공 여부, 대시보드 서버(8765·5173) 기동 여부.

---

## 자주 막히는 지점 (미리 알아둘 것)
- **KR 컨센서스/목표가**가 무료 소스에서 비면 → 해당 팩터는 자동으로 중립(50) 처리되니 파이프라인은 안 멈춤. 부족하면 그때 유료 검토.
- **무료 데이터 레이트리밋** → n8n에서 호출 간격·배치로 제어(Claude Code가 처리).
- **로컬 모델 툴콜**(Hermes 로컬 시) 신뢰성 → 처음엔 클라우드 모델 권장.
- 무엇이든 막히면 에러 로그째로 PM에 붙이면 됨.

---
