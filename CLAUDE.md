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
│   ├── ingest_kr.py        # KR 가격(pykrx)·재무(DART)·밸류/컨센서스(네이버+FnGuide 무료)
│   ├── ingest_kis.py       # KIS Developers 옵션 보조(키 있을 때만, ROE/부채/컨센서스 보강)
│   ├── ingest_news.py      # 뉴스 수집 + url_hash dedupe → news_raw
│   ├── ingest_market.py    # 지수/VIX/환율/금리 → market_daily
│   ├── ingest_portfolio.py # KIS 잔고(또는 선택 옵션) → portfolio*
│   ├── compute_indicators.py  # SMA/RSI/추세기울기/정배열 (기존 main.py 로직 이식)
│   ├── compute_quant.py    # 팩터 스코어링 (PRD §F4)
│   ├── rules.py            # 알림 룰 엔진 (PRD §F6-1)
│   ├── enrich_gemini.py    # Gemini 호출 래퍼 (스키마 검증 포함)
│   ├── assemble.py         # 종목 일일 레코드(PRD §5.2) 조립 뷰
│   ├── run_pipeline.py     # 일일 파이프라인 실행기(수집→연산→LLM→조립)
│   ├── send_telegram.py    # 아침 브리핑 텔레그램 발송
│   ├── backfill.py         # 누락/부족 종목 자동탐지 + 2년치 가격 백필 + 지표·퀀트 재계산
│   ├── news_refresh.py     # 18:00 KST 잡: 경량 가격갱신(prices+indicators+quant) + 뉴스+요약+export
│   ├── recompute.py        # prices_daily 기준 indicators→quant 재계산(1회용)
│   ├── compute_portfolio.py  # portfolio_holdings × prices_daily → portfolio upsert (F1, USD→KRW 환산)
│   ├── backtest.py           # 모멘텀 진짜 백테스트 + 팩터 회고 → backtest_results (PRD §F7)
│   ├── local_api.py          # FastAPI 로컬 쓰기 API (127.0.0.1:8765, CORS=5173만 허용)
│   └── export_dashboard_data.py  # DB → dashboard-web/src/data.json (1회용/CI)
├── dashboard/
│   ├── app.py              # Streamlit 대시보드 — 레거시, 유지보수 안 함
│   ├── watchlist_admin.py  # watchlist 관리 도구 (SQL 없이 추가·비활성·보유토글)
│   └── README.md           # 레거시 설명 + watchlist_admin 실행법
├── dashboard-web/          # React 대시보드 (현행 메인)
│   ├── src/
│   │   ├── main.jsx        # 진입점
│   │   ├── App.jsx         # 앱 셸 + 탭 라우터
│   │   ├── ui.jsx          # 공유 UI 컴포넌트 + SVG 차트
│   │   ├── tabsA.jsx       # Overview·StockDetail·News
│   │   ├── tabsB.jsx       # Screener·Market·Research
│   │   ├── tabsC.jsx       # Portfolio (로컬 API 연동)
│   │   ├── tabsD.jsx       # Strategy 전략 비교 (백테스트 recharts + 회고)
│   │   ├── tabsE.jsx       # WatchlistAdmin 관심종목 관리 (추가/active토글, 로컬 API)
│   │   ├── data.js         # data.json import (없으면 mock fallback)
│   │   ├── data.json       # export_dashboard_data.py 생성 (gitignore 권장)
│   │   ├── index.css       # 전역 스타일 + Pretendard 폰트
│   │   └── PretendardVariable.ttf
│   ├── index.html
│   ├── vite.config.js
│   └── package.json
├── .github/
│   └── workflows/
│       ├── auto_run.yml    # 06:00 KST 전체 파이프라인 + 텔레그램
│       ├── news_refresh.yml # 18:00 KST 뉴스 수집+요약+export (가벼운 잡)
│       └── recompute.yml   # 수동 지표·퀀트 재계산
├── n8n/
│   └── workflows/*.json    # 워크플로 export
├── hermes/
│   └── skills/*.md         # Hermes 스킬 정의
└── tests/
    └── test_*.py
```

## 3. 코딩 컨벤션 & PR 표준 절차
- **PR마다 PRD.md §11 로드맵과 변경 이력을 갱신한다** (PR 본문에 '무엇을/왜/어떻게 검증'과 함께). 이 규칙은 모든 PR에 상시 적용된다.
- **백테스트 vs 회고 절대 구분 (PRD §F7)**: 모멘텀만 진짜 백테스트(과거 시점 데이터만). 가치·퀄리티·성장·복합은 오늘 스냅샷뿐이라 "회고"(선정시점편향) — 화면·코드에서 절대 혼동 금지, 회고는 "백테스트 아님" 경고 필수.
- **시장 뉴스 pseudo-ticker**: 시장 시황 뉴스는 `_MARKET_KR`/`_MARKET_US` ticker로 `news_raw`에 저장. 이들은 watchlist에 없으므로 종목 카드/enrich 종목요약 대상에서 제외(`enrich_news_batch`는 watchlist 종목만 처리).
- **시장 등락률**: `ingest_market`이 거래일 기준 전일대비 등락을 `market_daily.payload.changes`에 저장(주말 carry-over 0.00% 버그 방지). export는 changes 우선, 폴백은 상대오차 1e-5 초과 시만 인정.
- **KR 밸류/컨센서스 = 네이버금융 + FnGuide 무료 스크래핑** (`ingest_kr.fetch_kr_valuation_analyst`). PER/PBR/현재가/목표가/투자의견=네이버 종목메인, ROE/부채비율=FnGuide `#highlight_D_A`. **yfinance KR 절대 금지**. KIS(`ingest_kis.py`)는 키 있을 때만 활성 보조. ROE는 비율(0.07) 단위로 정규화해 US와 통일(표시 시 ×100 %).
- **export는 종목별 '최신' 조회만 사용**(`SELECT DISTINCT ON (ticker) ... ORDER BY ticker, asof/date DESC`). 글로벌 `max(asof)`/특정날짜 고정 금지 — KR/US 수집일이 달라 한쪽이 통째로 누락되는 버그의 근원(indicators·quant·price·**valuation·analyst** 전부 적용).
- **UI 텍스트에 내부 스크립트명·명령어(.py / `python -m ...`) 노출 금지.** 사용자 친화 문구만. 빈 상태/에러도 "잠시 후 다시" 식으로.
- **가격 갱신 = 하루 2회** (06:00 auto_run + 18:00 news_refresh 경량). 18:00은 KR 장마감 후라 KR 당일종가, 06:00은 US 종가 직후. 헤더는 `priceAsof`(실제 가격 기준일) 표시.
- **US 뉴스 소스**: yfinance.news + **Yahoo Finance RSS**(`feeds.finance.yahoo.com`, 429 시 무재시도 스킵) + **Finnhub**(`FINNHUB_API_KEY` 있을 때만) + Google News RSS(영문 정식명+티커 복수쿼리). KR은 네이버 HTML + Google News RSS. 전부 url_hash dedupe·종목격리.
- **텔레그램은 보류(비활성)**. `TELEGRAM_ENABLED=false`(기본)면 `send_telegram.run_send`가 no-op 성공. 살리려면 PRD §F5 메모 참고(플래그 true + 워크플로 step 주석 해제).
- **포트폴리오 총자산 = 보유종목 평가액 + 현금**(둘 다 KRW 환산). 현금=`portfolio_cash`(통화별), `compute_portfolio`가 `cash_total`/`asset_total`을 snapshot payload에 저장.
- **관심종목 active 토글**: 제외는 하드딜리트가 아니라 `watchlist.active=false`(데이터 보존). export/quant/recompute는 **active=TRUE만** 대상. 신규 추가는 `backfill_single`로 그 종목만 가격+지표+퀀트 백필(local_api 백그라운드).
- **운영 모델 = CI가 DB, 집 PC가 화면**: GitHub Actions(auto_run 06시·news_refresh 18시)가 enrich 포함 **DB를 매일 자동 최신화**한다(Secrets: DB_PASSWORD·DART_API_KEY·GEMINI_API_KEY). **`data.json`은 CI 산출이 gitignore라 버려진다** — 화면 최신화는 집 PC의 `./start_dashboard.sh`(export→local_api+vite→브라우저)가 담당. 대시보드는 외부 접근/상시 서버 불필요(로컬 전용). 스크립트는 포트(8765·5173)가 떠 있으면 재사용하고, export 실패 시 DB접속/데이터부재를 구분해 에러를 낸다.
- **데이터 신선도 가드**: export는 `generatedAt`/`generatedAtLabel`을 data.json에 넣고, 헤더가 "데이터 생성: {시각}"을 표시. 생성 후 2일+이면 헤더에 옅은 경고(스크립트 재실행 권장). 사용자가 지금 보는 게 언제 것인지 항상 인지하게.
- **local_api CORS는 PATCH 포함 필수**: 토글류는 `PATCH /api/watchlist/{ticker}`를 쓴다. `allow_methods`에 PATCH가 빠지면 크로스오리진 프리플라이트(OPTIONS)가 400으로 막혀 **버튼이 조용히 무반응**(curl은 CORS 우회라 200이라 백엔드만 보면 못 잡음). 새 메서드(PATCH/OPTIONS 등) 엔드포인트 추가 시 CORS `allow_methods` 동기화. 토글 UI는 **낙관적 업데이트+실패 롤백+에러 표시**로 견고하게(조용한 실패 금지).
- **스크리너 장기보유 = 안전마진**(PRD §F4-6): 단일 "F-Score 7+" 필터는 **구조적으로 빔**(신호 7·8 미수집→실질 만점 7). 안전마진 = 가치40%+퀄리티35%+재무건전성25%(F-Score 없으면 ROE·부채 대체). **F-Score는 `quant_scores.fscore`에 영속화**(export `fscore=None` 하드코딩 금지 — 과거 버그). 가중치/SAFETY_FLOOR는 export 상단 상수. 후보 0이면 빈 화면 금지("충족 종목 없음" 명시).
- **재무 시계열**(PR-2): `fundamentals.ocf/fcf`(영업/잉여 현금흐름)는 ingest_us 현금흐름표에서 수집(FCF=OCF+CapEx). 종목상세 "재무 추이" 카드(recharts)는 연간 매출·영업이익·순이익·영업이익률·OCF·FCF. KR 일부(삼성·하이닉스 등)는 DART 결측이라 **empty state**(빈 박스 금지). 컨센서스 전망은 기존 analyst(목표가·의견)·valuation(per_f) 재사용.
- **매력도 3축 = 절대 단일 점수로 합치지 마라**(확인편향 방지): 종목상세 `AxesCard`는 퀀트(composite)·컨센서스(상승여력)·내 판단(별점)을 **나란히** 보여주고 각 축에 출처 라벨을 단다. 평균/가중합으로 한 숫자를 만들지 않는다. 축이 엇갈리면(한 축 높음+다른 축 낮음) "확인 필요" 코멘트로 **괴리를 드러낸다**. 컨센서스 데이터 없으면 "컨센서스 없음", 별점 없으면 "내 판단 미입력"(0점 아님).
- **리서치 항목**(`research_items`): local_api `GET/POST/DELETE /api/research`로 종목상세에서 직접 추가·삭제(유형 youtube/article/report/quant/memo). 추가 후 `_patch_data_json_research`로 해당 종목 `researchItems`만 패치(전체 재생성 회피). 공용 `ResearchItemCard`/`toYtEmbed`는 **tabsA.jsx에 정의**(tabsB가 import — tabsB→tabsA 단방향, 순환 import 금지).
- **오버뷰 요약밴드**(`dailyBrief`, export `_build_daily_brief`): 주목/주의/3축괴리/시장 한줄을 **규칙 기반으로 합성**(키 없어도 동작). 시장 한 줄은 이미 생성된 Gemini 시황(`market_daily.summary`)을 재사용(ad-hoc 호출 금지). 전부 '관찰/정보'로 서술, 매수매도 단정·면책 유지. **괴리 종목은 주목에서 제외**(메시지 혼선 방지). 문장 한 줄은 `_short_line`으로 소수점에서 안 끊기게.
- **시장 매력도**(`market.kr/us.attractiveness`, export `_attach_market_attractiveness`): 진입 환경(우호/중립/비우호)을 레짐+시장폭(정배열율)+변동성(VIX)으로 평가하고 근거를 서술. **단일 점수로 강요 금지**(3축 원칙과 동일 — 환경 평가+근거).
- **탭 간 종목 컨텍스트 연속성**: 전역 `ticker`(App.jsx)가 selectedTicker. 어느 탭에서든 종목을 '포커스'하면 `ticker`를 갱신해야 종목상세로 가도 유지된다(스크리너·포트폴리오는 `nav(tk)`로, 뉴스는 `selectNewsTicker`로 동기화). 새 탭에서 종목 선택 UI를 만들면 반드시 전역 `ticker`도 갱신.
- Python 3.12, 타입힌트 필수, `pydantic` v2로 외부 데이터·LLM 출력 검증.
- 모든 외부 수집 함수는 **순수 함수에 가깝게**: 입력(ticker 등) → 표준화된 dict/모델 반환. DB 쓰기는 `db.py`로 분리.
- 재시도: 네트워크/LLM 호출은 지수 백오프 3회. 실패 시 예외를 삼키지 말고 호출부에서 종목 단위로 격리.
- 모델명·가중치·임계값 등은 코드 상단 상수 또는 `config.yaml`로 추출(하드코딩 금지). 예: `GEMINI_BULK_MODEL`, `GEMINI_SYNTH_MODEL`, `QUANT_WEIGHTS`, `RSI_OVERHEAT=70`.
- 로깅: 표준 `logging`. 실행 시작/종료/오류를 `runs`에 적재.
- **DB NUMERIC은 읽기 경계에서 float로 변환(Decimal 혼용 금지)**: psycopg3는 NUMERIC을 `decimal.Decimal`로 반환하는데, Decimal이 `float`·`np.log`·나눗셈(`float / Decimal`)에 섞이면 `TypeError`로 계산이 죽는다(indicators/quant 0건 사고의 근본 원인). `db.get_conn`이 NUMERIC→float 로더를 등록하지만, 모든 DB 읽기 경계(쿼리 결과 dict, DataFrame 컬럼)에서 `float()`/`pd.to_numeric`로 한 번 더 방어한다. 특히 `np.log`·나눗셈 직전.
- **DB 쓰기는 단계별 커밋**: 한 트랜잭션에 장시간(네트워크 I/O 포함) 묶지 말 것. 각 저장 단계 직후 `conn.commit()`, 예외 시 `conn.rollback()`으로 회복(앞 단계 오류가 뒤 단계 저장을 무효화하지 않게). Supabase Pooler는 유휴 연결을 끊으므로 긴 단일 트랜잭션은 커밋 유실 위험.

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
- **키 쿼터(429)가 진짜 병목**: Gemini 키는 일일 쿼터 한계가 있어, 일일 파이프라인(38종목+시황)이 쿼터를 초과하면 **`429 RESOURCE_EXHAUSTED`로 종목별 폴백이 무더기 발생**(과거 "분석 실패" 광범위 노출의 근본원인). 따라서 ① **ad-hoc enrich/진단 호출로 쿼터를 태우지 말 것**(파이프라인이 유일 소비자가 이상적), ② 일시오류는 `_call_gemini_with_backoff`(429/503/타임아웃 **지수 백오프 3회**, 파싱 재시도와 분리)로 흡수, ③ 그래도 실패하면 **폴백을 `based_on='fallback_old'`로 표식**한다.
- **폴백은 절대 UI에 노출 금지**: 폴백 판정은 단일 출처 `is_fallback_summary(summary_md, based_on)`("분석 실패"/"일시 보류" 마커 + `fallback_old`). export(`export_dashboard_data`)는 **실제 요약을 폴백보다 우선**(낡은 실제 > 새 실패)하고, 실제가 없으면 **규칙기반 한 줄 인사이트(수치+해석)**로 채운다 — 사용자 화면에 "분석 실패" 문자열이 나오면 버그.
- **폴백 가시성·자가치유**: 폴백 발생 시 `runs.errors`에 사유 기록(과거엔 조용히 묻혀 추적 불가했음). 최신 분석이 폴백인 종목은 `reenrich_stale_fallbacks`(run_pipeline Step 7a')가 최근 뉴스로 재요약해 복구한다.
- **로컬 키 로딩**: `GEMINI_API_KEY`는 `.env`에 있고, `enrich_gemini._ensure_env()`가 `load_dotenv()`로 로드한다(src 어디에도 load_dotenv가 없어 로컬 enrich가 키 UNSET으로 통째 죽던 문제 수정). DB_*는 `.streamlit/secrets.toml`.

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
