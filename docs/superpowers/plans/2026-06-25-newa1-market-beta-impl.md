# 신규-A1 구현 계획 (설계 `2026-06-25-newa1-market-beta-design.md` 승인본)

승인 + 1가지 반영(코스닥 벤치마크 분리)에 따른 구현.

## 코스닥 분리 결정
- `index_daily`에 `^KQ11` **없었음** → ingest_index_history에 `^KQ11` 추가 + 5년 백필(라이브 적용, 1220행).
- 보드(코스피/코스닥) 자동 판별: pykrx `get_market_ticker_list`가 현 환경에서 빈 응답(실패), Naver 마크업도 불안정 → **자동 판별 불가**.
- 따라서 설계 §1 분기대로 **1차 ^KS11 기본 + 코스닥 allowlist**:
  - `_KOSDAQ_DEFAULT = {059090 미코, 213420 덕산네오룩스, 338220 뷰노}`(공개 사실 확정 코스닥).
  - env `KOSDAQ_TICKERS`로 보강 가능. **보드 자동 분류는 후속 백로그**(pykrx 보드 엔드포인트 복구/대체 소스 또는 watchlist board 컬럼).

## 묶음
1. **DDL/스키마/저장**: `index_daily`에 `^KQ11` 추가(BENCHMARK_INDEXES). `quant_scores`에 `beta`/`market_corr` **ADD COLUMN**(라이브 멱등 적용). `QuantScoresRow`·`upsert_quant_scores` 반영.
2. **결정론 계산**(`compute_quant`): `compute_beta_corr`(OLS cov/var, corr, window=`BETA_WINDOW_DAYS`/min=`BETA_MIN_OBS`, 결측/var0 None), `_fetch_index_closes`(index_daily, float), `_market_benchmark`/`_kosdaq_codes`. `compute_quant_universe`에서 벤치마크 1회 캐시 후 종목별 산출 → row. **composite 공식 불변(베타 미합산)**.
3. **export**: quant SELECT에 beta/market_corr 추가, 종목 dict에 `beta`/`marketCorr`/`betaBenchmark`(코스피/코스닥/S&P500).
4. **신규-D 노트 연동**: build_action_frame이 이미 `stock.get("beta")`를 derive_concentration_note에 전달 → export가 beta를 실으면서 자동 충전.
5. **UI**(`tabsA` AxesCard 퀀트 축): "시장 민감도 베타 X · 상관 Y (벤치마크, 1년)" 보조 라인(composite와 분리, None=미산출).
6. **테스트**: `tests/test_market_beta.py`(공식·window·결측·var0·벤치마크 매핑·env override·composite 미합산 8).

## 행위 보존/가드
- 결정론 계산, LLM 서술만. **composite에 베타 미합산**(3축/합산 경계 — 테스트로 고정).
- §F7 진짜 계산(asof까지 과거 수익률만, 룩어헤드 없음·회고 아님). 종목별 최신 조회·NUMERIC float·시크릿 비저장.
- 분석 파이프라인(compute_quant) 소관(수집·LLM 없음). index_daily 저장 데이터 사용(yfinance 라이브 아님).

## 스모크 결과(라이브, 2026-06-25)
| 종목 | 벤치마크 | beta | corr |
|---|---|---|---|
| 삼성전자/SK하이닉스/TSM/META(반도체·고베타) | ^KS11/^GSPC | 1.28 / 1.52 / 2.04 / 1.47 | 0.89/0.85/0.68/0.51 |
| KT&G/코웨이/KB금융(방어·저베타) | ^KS11 | 0.15 / 0.32 / 0.52 | 0.21/0.34/0.53 |
| 미코/덕산네오룩스/뷰노(코스닥) | **^KQ11** | 1.12 / 1.00 / 1.00 | 0.55/0.56/0.59 |
| 효성중공업(보유 33.9%) | ^KS11 | 1.04 | 0.64 |
| AAPL/GOOG(US) | ^GSPC | 0.90 / 1.29 | 0.49/0.56 |

→ 반도체 고베타·방어주 저베타 상식적, 코스피/코스닥/S&P 각자 벤치마크 적용 확인. 이 표본에 None 없음(전부 ≥MIN_OBS); None 경로는 단위테스트로 고정(신규상장·짧은 이력 시 None).
