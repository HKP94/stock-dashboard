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

## 자주 막히는 지점 (미리 알아둘 것)
- **KR 컨센서스/목표가**가 무료 소스에서 비면 → 해당 팩터는 자동으로 중립(50) 처리되니 파이프라인은 안 멈춤. 부족하면 그때 유료 검토.
- **무료 데이터 레이트리밋** → n8n에서 호출 간격·배치로 제어(Claude Code가 처리).
- **로컬 모델 툴콜**(Hermes 로컬 시) 신뢰성 → 처음엔 클라우드 모델 권장.
- 무엇이든 막히면 에러 로그째로 PM에 붙이면 됨.

---
*이 정보는 참고용이며 투자 자문이 아닙니다.*
