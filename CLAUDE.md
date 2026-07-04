# CLAUDE.md — ATLAS 빌더 지침 (Claude Code 전용)

> 너(Claude Code)는 이 프로젝트의 **빌더 엔지니어**다. 설계·계약·수용 기준은 `PRD.md`가 SSOT다. 임의로 아키텍처를 바꾸지 말고, 바꿔야 하면 먼저 PM(대화 세션의 Claude)에게 제안한다.

## 0. 절대 규칙 (위반 금지)
- **시크릿 금지**: API 키/토큰/계좌번호/비밀번호를 코드·로그·커밋·문서·시트에 **절대** 하드코딩하지 않는다. 모두 환경변수(`.env`, gitignore) 또는 n8n Credentials로만 읽는다.
- **표시 신호 허용·자동 주문 금지**: 근거·신뢰도를 동반한 매수/관망/축소 신호는 허용한다. 주문·체결·이체 등 자산을 움직이는 코드와 외부 주문 API 호출은 작성하지 않는다.
- **계약 준수**: DB 스키마(PRD §5.1)·JSON 스키마(PRD §5.3)를 벗어나는 입출력을 만들지 않는다. 스키마 변경은 PRD 갱신 후에만.
- **결정론은 코드로**: 지표·퀀트 점수·룰 알림은 LLM 호출 없이 Python으로 계산한다.
- **부분 실패 격리**: 종목 단위 `try/except`. 한 종목/소스 실패가 전체 실행을 멈추면 안 된다. 실패는 `runs.errors`에 기록.
- **MCP 접근 경계 = 판단 기록만 쓰기, 자동 수집은 읽기 전용**: Claude 웹(MCP)은 **판단 기록 계열**(`judgment_notes`·`stock_notes`·`stock_note_history`·`manual_research_entries/horizons/points/consensus`·`research_items`·`market_view_manual`)만 쓰기 허용 — Claude가 대화 결론을 여기에 적극 영속화한다. **판단 기록 스키마**: `judgment_notes`(append-only 대화 판단 로그, 세션 간 승계 — DDL `migrations/g1_judgment_notes.sql`, 뷰 `v_current_judgment`/`v_latest_judgment`). **물리 2차 방어**: 전용 role `atlas_note_writer`(`db/atlas_note_writer_role.sql`, 소유자가 수동 1회 실행)는 판단 기록 계열만 INSERT/UPDATE·나머지 SELECT 전용·**DELETE 미부여(append-only 강제)**. 이 role 로 붙은 쓰기 커넥터에서 `prices_daily` 등 수집 테이블 쓰기는 DB가 물리 거부(`permission denied`). 단, 현 공식 MCP는 관리 토큰이라 다운스코프 불가 → 물리 방어는 별도 Postgres 접속문자열 MCP(atlas_note_writer 자격) 연결 시에만 실효. **자동 수집·파이프라인 관리 테이블**(`prices_daily`·`indicators_daily`·`quant_scores`·`investor_flow`·`news_analysis`·`news_raw`·`signal_grade_track`·`market_score`·`fundamentals`·`valuation`·`analyst` 등)은 **읽기 전용** — 수집 데이터 무결성이 신뢰성 트랙의 근간이므로 MCP·수동 경로로 **절대 쓰지 않는다**(파이프라인만 씀). MCP는 `project_ref` 스코프 + database 그룹 한정, **Vercel 미사용**(로컬 집중). RLS 미설정은 PM이 리스크 수용(로컬 데이터·실자금 아님) → 보안 트랙 우선순위 낮음.

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
│   ├── ingest_index_history.py  # KOSPI/S&P500/NASDAQ 5년 이력 → index_daily (true backtest 비교용)
│   ├── ingest_portfolio.py # KIS 잔고(또는 선택 옵션) → portfolio*
│   ├── compute_indicators.py  # SMA/RSI/추세기울기/정배열 (기존 main.py 로직 이식)
│   ├── compute_quant.py    # 팩터 스코어링 (PRD §F4)
│   ├── strategies.py       # true/retrospective 전략 레지스트리 (Wave 3)
│   ├── rules.py            # 알림 룰 엔진 (PRD §F6-1)
│   ├── enrich_gemini.py    # Gemini 호출 래퍼 (스키마 검증 포함)
│   ├── ingest_drivers.py   # 종목 핵심 동인 자동 추정 + 프록시 가격 수집 (Wave 4-C)
│   ├── assemble.py         # 종목 일일 레코드(PRD §5.2) 조립 뷰
│   ├── run_pipeline.py     # 06시 호환 래퍼(설계 §9-6): ingest→analysis→synthesis('daily')→assemble. 레거시 _step_*는 stage 8까지 잔존
│   ├── pipeline_common.py  # 파이프라인 분리 공유 헬퍼(유니버스 조회·KR/US 분리·오류 dict·상태 확정, 설계 §5)
│   ├── pipeline_ingest.py  # 수집 실행기(--profile daily|refresh). 수집 단계만, 지표·LLM·export 금지(설계 §4.1)
│   ├── pipeline_analysis.py # 분석 실행기(--profile daily|refresh). 지표→퀀트→포폴→백테스트(refresh=지표·퀀트), 외부·LLM·export 금지(설계 §4.2)
│   ├── pipeline_synthesis.py # 종합 실행기(--profile daily|refresh). Step7 enrich+액션제언(refresh=뉴스요약·시황·시장뉴스요약), 수집·계산·주문 금지(설계 §4.3)
│   ├── send_telegram.py    # 아침 브리핑 텔레그램 발송
│   ├── backfill.py         # 누락/부족 종목 자동탐지 + 2년/5년 가격 백필 + 지표·퀀트 재계산
│   ├── news_refresh.py     # 18:00 호환 래퍼(설계 §9-6): ingest→analysis→synthesis('refresh')→export. 레거시 _refresh_prices_light는 stage 8까지 잔존
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
- **장기 벤치마크 이력(W3-A)**: KOSPI/S&P500/NASDAQ 5년 일봉은 `index_daily`에 저장한다. `market_daily`는 최신 스냅샷/요약 전용이며, true backtest 비교 시 두 테이블을 혼용하지 않는다.
- **전략 비교 저장 형식(W3-B)**: `backtest_results`는 `(strategy, track, horizon)` 단위로 1Y/3Y/5Y 결과를 저장한다. `track='true'`와 `track='retrospective'`는 export와 UI에서 별도 섹션으로만 노출하며, retrospective는 항상 선택편향 경고와 함께 보여준다.
- **전략 제언(W3-C)**: 현재 국면 추천 전략은 `backtest_results`의 국면별 성과를 읽어 **표시 전용**으로만 노출한다. true track이 1차 근거이며, retrospective는 참고용 경고와 함께만 붙인다. 주문 실행 경로는 만들지 않는다.
- **시장 뉴스 pseudo-ticker**: 시장 시황 뉴스는 `_MARKET_KR`/`_MARKET_US` ticker로 `news_raw`에 저장. 이들은 watchlist에 없으므로 종목 카드/enrich 종목요약 대상에서 제외(`enrich_news_batch`는 watchlist 종목만 처리).
- **시장 뉴스 영속화(W2-B)**: 종목 뉴스와 별도로 `market_news`(원천)와 `market_news_summary`(일일 KR/US/Global 요약)를 유지한다. 시장전망 탭의 "오늘의 시장 뉴스 요약"은 이 테이블만 읽는다.
- **거시 백본(W4-B)**: `macro_indicators`는 지표별 시계열, `macro_summary`는 일일 양면 해석(우호/부담/체크포인트) 전용이다. 시장전망 탭의 "거시 환경" 카드는 이 두 테이블만 읽고, 종목 export처럼 지표별 최신 행을 개별 선택한다(글로벌 max(asof) 금지).
- **거시 시크릿 규칙(W4-B)**: FRED/ECOS 키는 요청에만 사용한다. DB 컬럼·저장 URL·로그 메시지·예외 문자열에 키가 남으면 버그다. HTTP 오류는 원본 URL을 그대로 올리지 말고 마스킹/일반화한다.
- **종목 드라이버(W4-C)**: `ticker_drivers`는 `(ticker, driver_code)` 단위로 저장하며 `origin='user'`가 항상 우선이다. 자동 추정 결과는 user 행을 덮어쓰지 못하고, stale auto만 교체한다. 가격은 `macro_indicators`/`index_daily` 재사용을 우선하고, 전용 프록시만 `driver_prices`에 적재한다.
- **종목 드라이버 운용(W4-C 후속)**: 자동 매핑은 활성 유니버스 전체(현재 39종목)를 대상으로 돌리고, `driver_prices` 전용 프록시는 5년 깊이로 유지한다. Gemini가 놓치면 종목명·섹터·원자재/공급망 연관(리튬·메모리·유가·구리 등) 휴리스틱으로 보강하되 `origin='user'`는 절대 덮어쓰지 않는다.
- **드라이버 해석 톤(W4-C)**: 종목상세 "핵심 동인" 카드는 support/oppose 관찰 문장만 보여준다. 자동 추정은 반드시 "추정" 뱃지와 rationale을 같이 노출하고, 매매 단정 문구를 만들지 않는다.
- **누적 인사이트 영속화(W2-C)**: Gemini 종목 뉴스 요약은 `ticker_context`에도 `context_type='news_summary'`로 저장한다. 종목상세 "누적 인사이트"는 최근 30일만 보여주고, `valid_until < today` 항목은 삭제하지 말고 조회에서만 제외한다.
- **신선도 라벨(W2-D)**: export는 `generatedAt`와 시장별 최신 거래일로 `refreshContext`를 계산한다. 헤더/시장전망 탭은 반드시 "미국 종가 기준 (06시 갱신)" 또는 "한국 종가 기준 (18시 갱신)"을 표시하고, 18시 갱신본에서는 KR 가격·뉴스만 최신이며 US 가격은 전날 종가임을 명시한다.
- **시장 등락률**: `ingest_market`이 거래일 기준 전일대비 등락을 `market_daily.payload.changes`에 저장(주말 carry-over 0.00% 버그 방지). export는 changes 우선, 폴백은 상대오차 1e-5 초과 시만 인정.
- **KR 밸류/컨센서스 = 네이버금융 + FnGuide 무료 스크래핑** (`ingest_kr.fetch_kr_valuation_analyst`). PER/PBR/현재가/목표가/투자의견=네이버 종목메인, ROE/부채비율=FnGuide `#highlight_D_A`. **yfinance KR 절대 금지**. KIS(`ingest_kis.py`)는 키 있을 때만 활성 보조. ROE는 비율(0.07) 단위로 정규화해 US와 통일(표시 시 ×100 %).
- **애널리스트 컨센서스/논거 (Wave 4-D-1)**: 기존 `analyst` 저장 경로를 정규 컨센서스 저장소로 재사용하고 `rating_label/rating_score/eps_fwd/source`를 함께 저장한다(중복 테이블 금지). 정성 논거는 `analyst_views`에 `stance='bull'|'bear'`로 분리 저장하며, Gemini는 `news_raw`·`news_analysis`·`ticker_context`를 읽어 **실제 기사에 인용된 애널리스트/증권사 코멘트만** 추출하고 `source_url`을 반드시 보존한다.
- **애널리스트 뷰 탭 (Wave 4-D-2)**: 리서치 탭은 "애널리스트 뷰"로 재편한다. 종목 검색/시장·섹터 필터는 기존 `filterStocks` 패턴을 재사용하고, 화면은 `consensus`(최신) + `consensusHistory`(종목별 최근 시계열) + `analystViews.bull/bear` + `insightHistory`만 읽는다. 괴리율은 프론트에서 `(targetPrice / price - 1)`로 계산하고, 강세/약세 한쪽이 비면 "수집된 논거 없음"으로 그대로 표시한다(가짜 채우기 금지).
- **수동 AI 분해 (Wave 4-D-3)**: 자유 텍스트 수동 입력은 `manual_research_entries`(부모) + `manual_research_horizons/points/consensus`(자식) 구조로 누적 저장하고 raw_text는 DB에만 원문 보존한다. `manual_research_horizons`의 평가는 숫자 점수가 아니라 `attractiveness_label + rationale`로 저장하며, `aiDecompositionSummary`는 최신 entry id·단/중/장 라벨·bull/bear 개수만 가진 얇은 파생값이어야 한다(합산 점수 금지). raw_text 변경 재분해 시 `is_user_confirmed=false` 행만 교체하고, 사용자가 직접 수정한 horizon/point/consensus는 `is_user_confirmed=true`로 보호한다. 시장 수동 입력은 `market_view_manual(scope='market')`에 저장하고, 로그에는 raw_text 전체를 남기지 않고 길이/해시만 기록한다.
- **종목 액션 제언 (Wave 5-A)**: `stock_action_advice`는 `UNIQUE (ticker, asof)`의 **일 단위 시계열**이다. 같은 날 재실행은 upsert, 과거 날짜는 보존한다. 현재 비중·목표 비중 레인지·진입/이탈 구간은 반드시 코드가 계산하고 LLM은 rationale/divergence 설명만 만든다(숫자 생성 금지). 상위 모델 호출 우선순위는 ① 보유 7종목 매일 ② 신호 변화/뉴스 이벤트 종목 ③ 남은 예산 시 순환 종목이며, 예산 초과/이월은 `runs.errors`에 남긴다. export는 `actionAdviceLatest/actionAdviceHistory`만 노출하고, UI는 최신 1건+과거 토글만 보여준다.
- **종목 카드 = 보유성격 판단(신규-D, 비중 강요 금지)**: 종목 카드는 "비중 늘려/줄여"를 **강요하지 않는다**(KPH 집중 투자 철학). 핵심은 **보유성격(장기보유/모멘텀/단기/정보부족)** — `stock_action_advice.derive_hold_character`가 기존 재료(수동분해 단/중/장·퀀트/모멘텀·정배열·안전마진·RSI/뉴스이벤트)로 **결정론** 판정(우선순위 장기→모멘텀→단기, primary+secondary+근거). LLM은 라벨을 만들지 않고 해설만. 비중 권고(`target_weight/weight_action/direction`)는 **계산·DB 저장은 유지하되 종목 카드 표시에서만 제외**(데이터 보존·포트폴리오 탭/5-C 재사용 — 절대 DROP 금지). 집중 리스크는 `concentration_note`로 **"관찰"(사실+영향)만** — 결정론 템플릿 기본, LLM은 어휘만 다듬고 `is_observation_clean` **금지어 가드**(줄이/축소/매도/과도/부담/적정/권장/바람직 등 가치판단·지시어 차단)+수치 보존(`finalize_concentration_note`). 비중·집중도 **관리(목표비중·리밸런싱)**는 포트폴리오 탭(5-C) 소관이지 종목 카드가 아니다. 3축 비합산·종목별 최신 조회 유지.
- **export는 종목별 '최신' 조회만 사용**(`SELECT DISTINCT ON (ticker) ... ORDER BY ticker, asof/date DESC`). 글로벌 `max(asof)`/특정날짜 고정 금지 — KR/US 수집일이 달라 한쪽이 통째로 누락되는 버그의 근원(indicators·quant·price·**valuation·analyst** 전부 적용).
- **테이블별 키 컬럼명이 다르다 — 새 쿼리는 실제 스키마 대조 필수**: `prices_daily`=`(ticker, date)`, `index_daily`=`(index_code, asof)`, 대부분의 `*_daily`/스냅샷 테이블=`asof`. 한 테이블 관례를 다른 테이블에 복붙하면 `column "date" does not exist`로 조용히 전량 실패한다(신규-F signal_track이 index_daily를 `date`/`ticker`로 조회해 매일 ~48건 insert 실패한 회귀). **새 SQL은 `db/schema.sql`에서 컬럼명을 확인하고, 머지 전 실제 DB 대상 1행 스모크(insert/select 성공)로 컬럼 존재를 검증**한다(단위테스트는 mock이라 컬럼 오타를 못 잡는다).
- **UI 텍스트에 내부 스크립트명·명령어(.py / `python -m ...`) 노출 금지.** 사용자 친화 문구만. 빈 상태/에러도 "잠시 후 다시" 식으로.
- **가격 갱신 = 하루 2회** (06:00 auto_run + 18:00 news_refresh 경량). 18:00은 KR 장마감 후라 KR 당일종가, 06:00은 US 종가 직후. 헤더는 `priceAsof`(실제 가격 기준일) 표시.
- **종목 뉴스는 호재/악재 균형 수집**: KR Google News는 기본 쿼리 외 `리스크/하락/우려`, US는 `risk/decline/concern` 쿼리를 병행 수집한다. 종목당 캡은 유지하고 url_hash dedupe로 중복 제거한다.
- **US 뉴스 소스**: yfinance.news + **Yahoo Finance RSS**(`feeds.finance.yahoo.com`, 429 시 무재시도 스킵) + **Finnhub**(`FINNHUB_API_KEY` 있을 때만) + Google News RSS(영문 정식명+티커 복수쿼리). KR은 네이버 HTML + Google News RSS. 전부 url_hash dedupe·종목격리.
- **시장 뉴스 소스**: MarketWatch RSS(US), 한국경제 RSS(KR), 매일경제 공개 RSS(file.mk 경로, KR), Google News RSS 시장 쿼리(KR/US/Global), FRED API(`FRED_API_KEY` 있을 때만)를 사용한다. 소스별 실패는 로그만 남기고 전체 실행은 계속한다.
- **텔레그램은 보류(비활성)**. `TELEGRAM_ENABLED=false`(기본)면 `send_telegram.run_send`가 no-op 성공. 살리려면 PRD §F5 메모 참고(플래그 true + 워크플로 step 주석 해제).
- **포트폴리오 총자산 = 보유종목 평가액 + 현금**(둘 다 KRW 환산). 현금=`portfolio_cash`(통화별), `compute_portfolio`가 `cash_total`/`asset_total`을 snapshot payload에 저장.
- **총자산 표시는 단일 경로**: 오버뷰·포트폴리오 모두 `portfolio_snapshot.payload.asset_total`을 공용 `portfolioAssetTotal`로 표시한다. 구형 export만 `total_eval + cash_total` 폴백을 허용한다.
- **관심종목 active 토글**: 제외는 하드딜리트가 아니라 `watchlist.active=false`(데이터 보존). export/quant/recompute는 **active=TRUE만** 대상. 신규 추가는 `backfill_single`로 그 종목만 가격+지표+퀀트 백필(local_api 백그라운드).
- **관심종목 섹터 편집 UX**: 관심종목 관리의 섹터 입력은 로컬 draft state로 유지하고, 저장은 onBlur/명시적 저장 버튼/디바운스로 분리한다. 매 keystroke마다 PATCH나 refetch를 호출하지 않는다. 행 컴포넌트 key는 반드시 `ticker` 같은 안정 식별자만 쓰고, 입력 중 포커스/스크롤이 유지되도록 중첩 컴포넌트 재정의로 인한 리마운트를 피한다.
- **관심종목 티커/국가 정정 = 제거+추가**: 티커는 `prices_daily`·`quant_scores`·`news_raw`·`stock_action_advice` 등 거의 모든 테이블의 사실상 키다. 오타 정정 시 `watchlist.ticker`를 **단순 UPDATE하면 잘못된 티커로 쌓인 데이터가 올바른 티커에 잘못 붙어 정합성이 깨진다**. 따라서 정정은 `POST /api/watchlist/{old}/correct`로 **잘못된 종목 비활성(active=false, 데이터 보존) + 올바른 종목 추가**를 한 트랜잭션(commit/rollback)으로 처리하고, 새 종목만 백그라운드 백필한다. 기존(잘못된) 종목 데이터는 1차에서 물리 삭제하지 않는다(export는 active만 조회→화면에서 자연 소멸). 보유(`portfolio_holdings`)는 자동 이전하지 않는다. 검증: 새 티커 공백 금지·KR|US만·기존과 동일 금지·이미 활성이면 409. 정정 draft도 섹터처럼 부모 state로 유지(포커스 튐 방지).
- **백필 단독 완결성**: `src/backfill.py`와 `python -m src.backfill --5y`는 가격만 채우고 끝나면 안 된다. 영향 종목 `indicators_daily` 재계산과 active 유니버스 `quant_scores` 재계산까지 같은 실행 안에서 끝내야 하며, 수동 `python -m src.recompute`를 운영 필수 단계로 요구하지 않는다. `recompute.py`는 수복/재실행용 별도 도구로만 유지한다.
- **운영 모델 = CI가 DB(대부분), 로컬이 수급+화면**: GitHub Actions(auto_run 06시·news_refresh 18시)가 enrich 포함 **DB를 매일 자동 최신화**한다(Secrets: DB_PASSWORD·DART_API_KEY·GEMINI_API_KEY). **예외 = E-2 investor_flow(KRX 수급)**: KRX가 CI IP를 차단하므로 **로컬(맥, 한국 IP)이 담당**한다 — `scripts/local_refresh.py`(investor_flow 수집 + data.json export)를 launchd가 하루 2회(19:10 KR수급확정후·08:00 CI완료후) 호출. CI의 investor_flow 단계는 `SKIP_INVESTOR_FLOW=1`로 조용히 스킵(로그인 실패 노이즈 제거). 로컬 크론이 실패해도 CI 무관(완전 분리), 백필 창(~10일)으로 며칠 꺼져도 자가치유. **`data.json`은 CI 산출이 gitignore라 버려진다** — 화면 최신화는 로컬 담당: `scripts/local_refresh.py`(스케줄) 또는 `./start_dashboard.sh`(수동, export→서버→브라우저), 서버 상시화는 launchd `com.atlas.dashboard`(로그인 시 `scripts/dashboard_up.sh` idempotent 기동). 대시보드는 외부 접근 불필요(로컬 전용). 설치: `scripts/install_local_automation.sh`(KPH 1회). 로그: `~/atlas_logs/`, 상태: `~/atlas_logs/local_refresh_state.json`.
- **시크릿은 Secrets 등록 + 워크플로 env 배선 둘 다 필요**(등록만으로 CI 전달 안 됨): `secrets.X`는 자동으로 프로세스 env가 되지 않는다 — 반드시 각 워크플로 `env:` 블록에 `X: ${{ secrets.X }}`로 명시 배선해야 `os.getenv("X")`가 읽는다. 새 시크릿(KRX_ID/KRX_PW 등) 추가 시 **Secrets 등록과 auto_run.yml·news_refresh.yml 두 파일 env 배선을 함께** 하지 않으면, 코드는 조용히 폴백(예: KRX 익명조회→investor_flow 0건)만 남긴다(run #158 실사고: Secrets는 06-28 등록됐으나 .yml 미배선으로 E-2 수급 매일 0건). .yml 수정 후 `yaml.safe_load` 파싱 검증 필수.
- **KRX 로그인은 CI(GitHub Actions IP)에서 차단됨 — 확정**(run #159, 2026-07-03): KRX_ID/KRX_PW를 배선해도 CI에서 `login_krx`가 **빈 응답→`JSONDecodeError: Expecting value: line 1 column 1`**로 실패한다(KRX가 미국 데이터센터 IP를 지오/방화벽 차단). 동일 코드가 **로컬(한국 IP)에선 로그인 성공**. 따라서 E-2 investor_flow는 **CI로 수집 불가** — 로컬/한국 IP 수집이나 프록시가 필요하다(PR #72 env 배선은 필요조건이었으나 충분조건 아님). investor_flow DB가 특정일에 멈춰 있으면 export 버그가 아니라 이 CI 수집 실패가 1순위 원인.
- **데이터 신선도 가드**: export는 `generatedAt`/`generatedAtLabel`을 data.json에 넣고, 헤더가 "데이터 생성: {시각}"을 표시. 생성 후 2일+이면 헤더에 옅은 경고(스크립트 재실행 권장). 사용자가 지금 보는 게 언제 것인지 항상 인지하게.
- **KR 18시 종가 기준일**: KR 일봉 조회 종료일은 서버 로컬시간이 아니라 **KST 기준**으로 판단한다. 장마감 전에는 직전 영업일, 장마감 후에는 당일을 요청하고, 휴장/미확정이면 pykrx가 반환한 실제 마지막 거래일을 로그에 남긴다. `priceAsofByMarket["KR"]`는 이 실제 적재 기준일과 일치해야 한다.
- **표시 텍스트 마크다운 정리**: 뉴스 요약·시장 시황·포트폴리오 조언 등 사용자 표시 문자열은 raw `*`/`**`를 그대로 노출하지 말고 렌더 단계에서 평문화/정리한다. Gemini/Hermes 계열 프롬프트에도 과도한 강조 표시를 자제하라는 지침을 넣는다.
- **local_api CORS는 PATCH 포함 필수**: 토글류는 `PATCH /api/watchlist/{ticker}`를 쓴다. `allow_methods`에 PATCH가 빠지면 크로스오리진 프리플라이트(OPTIONS)가 400으로 막혀 **버튼이 조용히 무반응**(curl은 CORS 우회라 200이라 백엔드만 보면 못 잡음). 새 메서드(PATCH/OPTIONS 등) 엔드포인트 추가 시 CORS `allow_methods` 동기화. 토글 UI는 **낙관적 업데이트+실패 롤백+에러 표시**로 견고하게(조용한 실패 금지).
- **스크리너 장기보유 = 안전마진**(PRD §F4-6): 단일 "F-Score 7+" 필터는 **구조적으로 빔**(신호 7·8 미수집→실질 만점 7). 안전마진 = 가치40%+퀄리티35%+재무건전성25%(F-Score 없으면 ROE·부채 대체). **F-Score는 `quant_scores.fscore`에 영속화**(export `fscore=None` 하드코딩 금지 — 과거 버그). 가중치/SAFETY_FLOOR는 export 상단 상수. 후보 0이면 빈 화면 금지("충족 종목 없음" 명시).
- **시장 베타·상관(신규-A1)**: 종목 vs 자국 지수 베타·상관은 `compute_quant.compute_beta_corr`가 `prices_daily`+`index_daily`(저장 데이터, **yfinance 라이브 금지** — 재현성·§F7·무네트워크)로 결정론 계산(`BETA_WINDOW_DAYS=252`/`BETA_MIN_OBS=60` env, OLS cov/var, 결측·상장부족·var0 → **None**, 0·추정 금지). 벤치마크: US→`^GSPC`, KR→`^KS11`(코스피 기본)·**`^KQ11`(코스닥)**. 코스닥 판별은 `_KOSDAQ_DEFAULT` allowlist + `KOSDAQ_TICKERS` env(보드 자동분류는 백로그 — pykrx 보드 엔드포인트 불안정). `quant_scores.beta/market_corr`에 저장하되 **`composite`에 합산하지 않는다**(퀀트 축 내 별도 시장 민감도 팩터, 3축 비합산). 베타는 §F7 진짜 계산(룩어헤드 없음)이며 회고와 구분. 신규-D 집중 관찰 노트가 이 베타를 사실+영향으로만 인용(평가어 금지). `index_daily` 벤치마크(^KS11/^KQ11/^GSPC)는 W3-A 5년 백필 경로로 유지.
- **시장 방향·매력도 점수(Wave 5-B)**: 지역(KR/US)별 시장 매력도는 `compute_market_score.compute_market_scores`가 **결정론**으로 산출(지수 추세·VIX·매크로 Δ·정배열율 가중합 → 0~100 + 방향 강세/중립/약세 + 신뢰도 상/중/하). LLM은 방향 **해설만**(점수·방향 생성·매매 단정 금지). **정확도 가드**: 서브스코어가 강하게 충돌하면(부호 혼조+분산≥임계) 신뢰도 '하'에 그치지 말고 **점수도 50(중립)쪽으로 수축**(`MS_SHRINK`) — "강한 점수+낮은 신뢰도" 조합 금지. 데이터 부족(<`MIN_COMPONENTS`)도 수축. 저장은 신규 `market_score`(시장 단위 asof 이력, 분석 소유 — `market_daily`와 분리). **뉴스 심리는 점수 코어에 넣지 않는다**(해설 전용). 시장→종목 영향은 **신규-A1 베타 경로로만**(export `marketBetaNote`, 사실+영향·매매 단정 없음). **`composite`에 직접 합산 금지**(3축 비합산, 실제 반영은 보수적 후속 cap). §F7: 지수=진짜, **매크로는 발표 시점(`asof≤평가일`)만**(룩어헤드 금지). 점수=분석(`_step_market_score`)·해설=종합(`enrich_market_summary`), 분석→종합 순서.
- **재무 시계열**(PR-2): `fundamentals.ocf/fcf`(영업/잉여 현금흐름)는 ingest_us 현금흐름표에서 수집(FCF=OCF+CapEx). 종목상세 "재무 추이" 카드(recharts)는 연간 매출·영업이익·순이익·영업이익률·OCF·FCF. KR 일부(삼성·하이닉스 등)는 DART 결측이라 **empty state**(빈 박스 금지). 컨센서스 전망은 기존 analyst(목표가·의견)·valuation(per_f) 재사용.
- **포트폴리오 전략 조언(`portfolio_advice.py`)**: CoT 4단계(구성/리스크/국면/종합)를 코드로 분리하고 모든 단계에 `ABSOLUTE_RULES`를 주입한다. 코드가 제공한 표시 신호는 근거·신뢰도와 함께 설명할 수 있으나 LLM이 새 신호·목표가를 만들면 안 된다. 주문·체결·이체 실행은 금지한다. 매 단계 `response_mime_type=json`+pydantic 검증, 키 없음/STEP1 실패 시 규칙기반 폴백, `cache_key` 증분 캐시를 유지한다.
- **매력도 3축 = 절대 단일 점수로 합치지 마라**(확인편향 방지): 종목상세 `AxesCard`는 퀀트(composite)·컨센서스(상승여력)·내 판단(별점)을 **나란히** 보여주고 각 축에 출처 라벨을 단다. 평균/가중합으로 한 숫자를 만들지 않는다. 축이 엇갈리면(한 축 높음+다른 축 낮음) "확인 필요" 코멘트로 **괴리를 드러낸다**. 컨센서스 데이터 없으면 "컨센서스 없음", 별점 없으면 "내 판단 미입력"(0점 아님).
- **3축 종합 등급(신규-A2)**: 매력도 3축 위에 **매매 기준이 되는 명확한 등급**(매수/관망/축소) 결론 레이어를 둔다. 등급은 `stock_action_advice.derive_grade`가 **결정론**으로, 각 축을 강/중/약으로 레벨화(임계는 `AxesCard._level`과 동일: 퀀트 60/40·컨센서스 20/5%·별점 4/2)한 뒤 **방향 정렬 패턴**에서 도출한다 — **단일 점수 합산 금지**(컴포지트·상승여력·별점을 더하거나 평균하지 않는다, 방향 투표만). 규칙: 2축+ 강·반대 없음→매수, 강∧약 충돌→관망·신뢰도 하, 다수 약→축소, **한 축만 강→관망(약한 매수 만들지 않음, 상방 신중)**, 한 축만 약→축소(하방 민감), 단일 축/전부 중립→관망·하. 시장점수(5-B)·베타(A1)는 **퀀트 축 경로로만·비대칭**(시장 약세+고베타 β≥1.2 → 퀀트 강을 한 단계 보수화 / 시장 강세는 등급을 끌어올리지 않음 — 고점 매수 방지). 저장은 `stock_action_advice.grade/grade_confidence/grade_basis`(신규 테이블 없음, ADD COLUMN). LLM은 **등급 해설만**(새 등급·숫자 생성 금지, 폴백은 `grade_fallback_rationale` 결정론 템플릿). 종목상세는 **등급을 상위 결론(헤드라인)**으로, 횡단면 `display_signals`는 퀀트 축 내부 위치로 강등(중복 금지). 스크리너는 등급 컬럼+"매수만" 필터+등급순 정렬(매수>관망>축소·신뢰도 상 우선)로 **발굴**. `composite` 미합산·3축 비표시 보존·§F7 진짜 계산 유지.
- **상승여력 `up`은 퍼센트 계약**: `analyst.upside`는 **분수**(0.378)로 저장하지만 export `stock.up`은 **퍼센트**(`upside*100`=37.8)로 내보낸다. 표시(`{up}%`)·컨센서스 축 임계(20/5)·`daily_brief` 괴리(up<5/up≥20)·A2 등급이 전부 퍼센트를 가정한다(분수를 그대로 흘리면 컨센서스 축이 구조적으로 항상 '낮음'이 되는 버그).
- **내 판단은 누적 이력**: `stock_notes`는 3축용 최신 상태, `stock_note_history`는 명시적으로 제출한 판단의 불변 이력이다. 여러 줄 입력을 타임스탬프와 함께 최신순으로 보여주며 빈 판단은 저장하지 않는다.
- **용어 한글화는 표시 레이어만**: 내부 `regime/sentiment/momentum/value/quality/growth`와 `m/v/q/g/s` 키는 유지하고 UI에서는 국면/심리/모멘텀/가치/우량성/성장으로 표시한다.
- **리서치 항목**(`research_items`): local_api `GET/POST/DELETE /api/research`로 종목상세에서 직접 추가·삭제(유형 youtube/article/report/quant/memo). 추가 후 `_patch_data_json_research`로 해당 종목 `researchItems`만 패치(전체 재생성 회피). 공용 `ResearchItemCard`/`toYtEmbed`는 **tabsA.jsx에 정의**(tabsB가 import — tabsB→tabsA 단방향, 순환 import 금지).
- **오버뷰 요약밴드**(`dailyBrief`, export `_build_daily_brief`): 주목/주의/3축괴리/시장 한줄을 규칙 기반으로 합성하고 시장 한 줄은 기존 Gemini 시황을 재사용한다. 괴리 종목은 주목에서 제외하며 문장 한 줄은 `_short_line`으로 소수점에서 끊지 않는다.
- **표시 신호 계약**: 활성 종목의 퀀트 종합 횡단면 백분위가 70 이상이면 매수, 30 이하면 축소, 나머지는 관망이다. 신호는 `label/percentile/reason/confidence`를 항상 함께 제공하며 단독 라벨은 버그다. 계산은 `display_signals.py`의 순수 Python이고 주문 실행 경로가 없다.
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
- 대량(종목별 뉴스 요약)=저렴 모델, 종합(시황 1회)=상위 모델. 모델명은 config로. **현행 유효 모델**(2026-06-17 실호출 검증): `GEMINI_BULK_MODEL=gemini-2.5-flash-lite`, `GEMINI_SYNTH_MODEL=gemini-2.5-flash`(3.5-flash에서 2.5 계열로 정리). 무효 모델명이면 호출 전량 실패하므로 변경 시 반드시 실호출 검증.
- **중요뉴스 큐레이션 = 2단계·모델 분리로 비용 관리**(`curate_ticker_news`): **STEP A 선별/스코어링 = Flash-Lite**(impact_score·category·direction), 임계값(`CURATION_THRESHOLD=60`) 통과분만 **STEP B 인사이트 = 2.5-Flash**. 비용 가드: 입력 뉴스 캡(`CURATION_MAX_NEWS=12`)·top-K(6)·증분(enrich 종목만). 예상 비용 월 1만원 안쪽(36종목·하루 2회). 빈 큐레이션도 정상("중요 뉴스 없음"). 요약이 폴백이면 큐레이션 스킵. 결과는 `news_analysis.curated`(빈 []로 기존값 덮어쓰지 않음).
- **뉴스 선별 편향 금지**: 종목 뉴스 요약과 STEP A 선별 프롬프트는 부정·리스크 뉴스도 중요하게 평가하도록 명시한다. 긍정/호재 편향 문구를 넣지 않는다.
- 입력 뉴스는 dedupe + 상위 N건 + 본문 길이 캡. 새 뉴스 없으면 호출 스킵(전일 재사용).
- 항상 `response_mime_type="application/json"` + 스키마 강제. 파싱 실패 핸들링 필수.
- **키 쿼터(429)가 진짜 병목**: Gemini 키는 일일 쿼터 한계가 있어, 일일 파이프라인(38종목+시황)이 쿼터를 초과하면 **`429 RESOURCE_EXHAUSTED`로 종목별 폴백이 무더기 발생**(과거 "분석 실패" 광범위 노출의 근본원인). 따라서 ① **ad-hoc enrich/진단 호출로 쿼터를 태우지 말 것**(파이프라인이 유일 소비자가 이상적), ② 일시오류는 `_call_gemini_with_backoff`(429/503/타임아웃 **지수 백오프 3회**, 파싱 재시도와 분리)로 흡수, ③ 그래도 실패하면 **폴백을 `based_on='fallback_old'`로 표식**한다.
- **무인 CI 시간 상한 필수**: 외부 호출(Gemini·yfinance·FRED·ECOS·RSS/HTML 스크래핑)은 모두 명시적 timeout이 있어야 하며, 배치형 Gemini 단계는 총 시간 예산을 넘기면 남은 종목을 폴백/다음 실행으로 이월한다. GitHub Actions 워크플로 자체에도 `timeout-minutes`를 둬 사람이 강제종료하지 않아도 종료되게 유지한다.
- **모델 비용 원칙 = 안정화까지 Flash 계열만(무료티어 자격)**: 2주에 ~$21 소진(주범=액션제언 pro 매일 전 종목 + 이중과금 + 503 재시도 폭증). 파이프라인 안정화 전까지 **Flash 계열만** 쓴다. `pro`(2.5-pro, 출력 $10/1M)는 **최상급 추론이 실제로 필요한 저빈도·온디맨드 지점에만 선별** 사용하고, **매일 전 종목 pro 호출은 금지**. 현행: 뉴스요약/큐레이션 STEP A/애널리스트논거=Flash-Lite(`GEMINI_BULK_MODEL`), 시황/큐레이션 STEP B=Flash(`GEMINI_SYNTH_MODEL`), **액션제언=Flash(`ACTION_ADVICE_MODEL`, 기본 `gemini-2.5-flash`)**, 수동리서치 분해(local_api, 사용자 온디맨드)만 pro 유지.
- **액션제언 모델 = `ACTION_ADVICE_MODEL` 값 하나로 pro↔flash 전환**: `enrich_gemini._get_action_advice_model()`(기본 flash). pro 복귀는 **파이프라인 안정 확인 + PM 승인 후** `ACTION_ADVICE_MODEL=gemini-2.5-pro` 한 값으로. pro 코드경로/프롬프트/60s 하드타임아웃(`ACTION_ADVICE_LLM_TIMEOUT_SECONDS`)은 **삭제하지 말고 유휴 보존**(복귀 쉽게). 60s는 대기가 아닌 상한이라 빠른 flash엔 트립되지 않는다.
- **503/일시오류 회복력 = 지터+지수백오프+서킷브레이커**: `_call_gemini_with_backoff`는 지수백오프에 **지터**(`GEMINI_BACKOFF_JITTER=1.0`, thundering-herd 방지)를 더하고, **연속 일시오류가 임계(`GEMINI_CIRCUIT_BREAKER_THRESHOLD=5`) 이상이면 서킷을 열어** 이후 호출은 API를 때리지 않고 즉시 실패시켜 쿼터·시간을 보존한다(우아한 degrade → 상위가 폴백 저장 후 계속). 성공 1회로 리셋, 쿨다운(`GEMINI_CIRCUIT_BREAKER_COOLDOWN=300s`) 경과 시 half-open 프로브 1회 허용. 파이프라인은 단명 프로세스라 다음 실행은 0에서 시작. `reset_circuit_breaker()`로 명시 리셋(테스트/새 배치).
- **일일 Gemini 호출 예산(무료티어 1,500/day 대비)**: 39종목 기준 정상 1회 풀런 재시도 제외 — 06시 flash-lite ~117 / flash ~43–82, 18시 flash-lite ~78 / flash ~42. **일 합계 ~319콜(재시도 제외)**, 재시도 포함 이론상한 3×이나 서킷브레이커가 폭주를 차단해 실측 ~1.3×(~415). **무료티어(모델별 분리 카운트) 수용 가능**. 배치API/컨텍스트캐싱 도입은 PM 결정 사항(현재 불필요).
- **(백로그) SIGALRM alarm이 재시도 backoff 전체를 감쌈**: `summarize_stock_action_advice`의 `signal.alarm`이 `_call_gemini_with_backoff`(재시도 루프 포함)를 통째로 감싸, 하드타임아웃이 pro p95를 넘기면 false-timeout→이중과금 재발 소지(#70에서 20→60s 상향은 증상 완화). **backoff를 alarm 바깥으로 빼는 리팩터**는 액션제언 구조 PR과 함께(향후). flash 전환으로 당장 위험은 낮음.
- **(백로그) 06시 수집 53분 병목**: 별도 트랙으로 진단 예정. ingest 서브로그(KRX 재로그인/yfinance 레이트리밋/DART)로 병목 특정 필요.
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
