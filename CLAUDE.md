# CLAUDE.md — ATLAS 빌더 지침 (Claude Code 전용)

> 너(Claude Code)는 이 프로젝트의 **빌더 엔지니어**다. 설계·계약·수용 기준은 `PRD.md`가 SSOT다. 임의로 아키텍처를 바꾸지 말고, 바꿔야 하면 먼저 PM(대화 세션의 Claude)에게 제안한다.

## 0. 절대 규칙 (위반 금지)
- **시크릿 금지**: API 키/토큰/계좌번호/비밀번호를 코드·로그·커밋·문서·시트에 **절대** 하드코딩하지 않는다. 모두 환경변수(`.env`, gitignore) 또는 n8n Credentials로만 읽는다.
- **자동 주문 금지**: v1은 **읽기 전용**. 매수/매도/이체 등 자산을 움직이는 코드는 작성하지 않는다(요청받아도 PM에게 에스컬레이션).
- **계약 준수**: DB 스키마(PRD §5.1)·JSON 스키마(PRD §5.3)를 벗어나는 입출력을 만들지 않는다. 스키마 변경은 PRD 갱신 후에만.
- **결정론은 코드로**: 지표·퀀트 점수·룰 알림은 LLM 호출 없이 Python으로 계산한다.
- **부분 실패 격리**: 종목 단위 `try/except`. 한 종목/소스 실패가 전체 실행을 멈추면 안 된다. 실패는 `runs.errors`에 기록.
- **면책**: 사용자 대상 출력 텍스트에는 "투자 자문 아님 / 원금 손실 가능"을 포함한다.

## 1. 프로젝트 개요
GitHub Actions + Google Sheets 기반 기존 주식 분석 파이프라인(`main.py`)을, **n8n + Postgres + Gemini + Hermes Agent** 구조로 재설계한다. 기존의 핵심 문제는 ① Sheets를 DB로 사용 ② KR 종목 yfinance 의존 ③ 취약한 뉴스 스크래핑 ④ 모놀리식. 이를 계층 분리·소스 교체로 해결한다. 자세한 진단·아키텍처는 `PRD.md` §1~§4.

## 2. 목표 리포지토리 구조
```
/
├── PRD.md                  # SSOT (수정 금지, 제안만)
├── CLAUDE.md               # 이 파일
├── prompts/
│   ├── GEMINI_PROMPT.md
│   └── HERMES_PROMPT.md
├── .env.example            # 키 이름만, 값은 비움
├── requirements.txt
├── src/
│   ├── db.py               # Postgres 연결·upsert 헬퍼 (psycopg/sqlalchemy)
│   ├── schemas.py          # pydantic 모델 = PRD §5.2/§5.3 계약 코드화
│   ├── ingest_us.py        # US 가격·재무·밸류·컨센서스 (FMP/Finnhub + yfinance 폴백)
│   ├── ingest_kr.py        # KR 가격(pykrx)·재무(DART)·시세/잔고(KIS)
│   ├── ingest_news.py      # 뉴스 수집 + url_hash dedupe → news_raw
│   ├── ingest_market.py    # 지수/VIX/환율/금리 → market_daily
│   ├── ingest_portfolio.py # KIS 잔고(또는 선택 옵션) → portfolio*
│   ├── compute_indicators.py  # SMA/RSI/추세기울기/정배열 (기존 main.py 로직 이식)
│   ├── compute_quant.py    # 팩터 스코어링 (PRD §F4)
│   ├── rules.py            # 알림 룰 엔진 (PRD §F6-1)
│   ├── enrich_gemini.py    # Gemini 호출 래퍼 (스키마 검증 포함)
│   └── assemble.py         # 종목 일일 레코드(PRD §5.2) 조립 뷰
├── n8n/
│   └── workflows/*.json    # 워크플로 export
├── hermes/
│   └── skills/*.md         # Hermes 스킬 정의
└── tests/
    └── test_*.py
```

## 3. 코딩 컨벤션
- Python 3.12, 타입힌트 필수, `pydantic` v2로 외부 데이터·LLM 출력 검증.
- 모든 외부 수집 함수는 **순수 함수에 가깝게**: 입력(ticker 등) → 표준화된 dict/모델 반환. DB 쓰기는 `db.py`로 분리.
- 재시도: 네트워크/LLM 호출은 지수 백오프 3회. 실패 시 예외를 삼키지 말고 호출부에서 종목 단위로 격리.
- 모델명·가중치·임계값 등은 코드 상단 상수 또는 `config.yaml`로 추출(하드코딩 금지). 예: `GEMINI_BULK_MODEL`, `GEMINI_SYNTH_MODEL`, `QUANT_WEIGHTS`, `RSI_OVERHEAT=70`.
- 로깅: 표준 `logging`. 실행 시작/종료/오류를 `runs`에 적재.

## 4. 우선 작업 (Phase 순서대로, 각 PR 단위)
> PR마다 ‘무엇을/왜/검증방법’을 PR 본문에 적고 PM 검수 요청.

**Phase 1 — 데이터 백본 ✅ 완료**
1. ✅ `schemas.py`: PRD §5.2/§5.3을 pydantic 모델로. (먼저 만든다 — 모든 모듈의 계약 기준)
2. ✅ `db.py`: 연결 + `upsert_*` 헬퍼 + `log_run()`.
3. ✅ `ingest_us.py` / `ingest_kr.py`: **KR은 pykrx+DART+KIS, US는 FMP/Finnhub+yfinance 폴백**. 기존 `main.py`의 `get_*` 로직을 참고하되 소스를 교체. 결측은 `None`으로 명확히(문자열 'N/A' 금지).
4. ✅ `ingest_news.py`: 네이버 HTML 스크래핑(KR) + yfinance.news(US) → `news_raw`, `url_hash`로 dedupe. (DDGS 완전 제거)
5. ✅ `ingest_market.py`: ^KS11·^KQ11·^GSPC·^IXIC·^VIX·KRW=X·^TNX → `market_daily`.
6. ✅ `compute_indicators.py`: 기존 SMA/RSI/이격도/정배열 로직 이식 + 추세기울기. **단위 테스트 20개**.
7. `n8n/workflows/ingest.json`: 05:30/06:00/15:40 스케줄로 위 모듈 호출(Execute Command 또는 HTTP).

**Phase 2 — 인텔리전스 (핵심 완료)**
8. ✅ `compute_quant.py`: PRD §F4 팩터 스코어. 레짐 감지·사전필터(F-Score·고유변동성)·5팩터·동적가중치. **단위 테스트 35개 (단조성·레짐·결측 검증)**.
9. ✅ `rules.py`: RSI 과열/침체, 골든·데드크로스 임박, 목표가 근접, 급등락, 이격도 과열 (8개 룰). **단위 테스트 64개**.
10. ✅ `enrich_gemini.py`: `prompts/GEMINI_PROMPT.md` 스키마로 호출, 출력 `pydantic` 검증 실패 시 1회 재시도 후 중립값. **증분**: 새 뉴스 있는 종목만. **단위 테스트 46개**.
11. `ingest_portfolio.py`: 확정된 F1 옵션 구현.

**Phase 3 — 전달**
12. ✅ `assemble.py`: 종목 일일 레코드 뷰 조립 (§5.2 StockDailyRecord). **단위 테스트 26개**.
13. `hermes/skills/morning_brief.md` + 텔레그램 발송 경로.
14. Sheets 미러 + 기존 Apps Script 뷰어 연계(`report_url`).

## 5. Gemini 호출 규칙 (토큰 절약)
- 대량(종목별 뉴스 요약)=저렴 모델, 종합(시황 1회)=상위 모델. 모델명은 config로.
- 입력 뉴스는 dedupe + 상위 N건 + 본문 길이 캡. 새 뉴스 없으면 호출 스킵(전일 재사용).
- 항상 `response_mime_type="application/json"` + 스키마 강제. 파싱 실패 핸들링 필수.

## 6. 테스트 & 검증
- `compute_indicators`, `compute_quant`, `rules`는 합성 데이터로 단위 테스트(LLM·네트워크 의존 없이).
- 수집 모듈은 1~2 종목 스모크 테스트.
- 통합: 드라이런으로 DB 적재 → `assemble.py` 출력이 §5.2 스키마와 일치하는지 확인.

## 7. 핸드오프 프로토콜
- 너는 **코드·워크플로·스킬**을 만든다. 런타임에 너를 호출하지 않는다(빌드 타임 전용).
- Gemini는 `enrich_gemini.py`가 호출하고, 출력은 §5.3 계약만 신뢰한다.
- Hermes는 `assemble.py` 결과(§5.2)와 DB만 읽는다. 너는 Hermes가 읽을 데이터의 모양을 보장한다.
- 막히거나 계약을 바꿔야 하면 코드 주석 `# TODO(PM):`로 표시하고 PM에게 보고.

## 8. 기존 코드에서 가져올 것 / 버릴 것
- **가져옴**: `get_momentum_data`의 SMA/RSI/정배열·기울기 판정, 컬럼 구성(`ordered_cols`)을 스키마로 정리, Gemini 뉴스 프롬프트의 의도(핵심팩트 가중·날짜 가중).
- **버림**: `worksheet.clear()`+전체 업로드, KR yfinance 재무, DDGS, 단일 파일 구조, 문자열 'N/A' 채움.
