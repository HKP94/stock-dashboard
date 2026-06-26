# Wave 5-B 구현 계획 (설계 `2026-06-25-wave5b-market-direction-design.md` 승인본)

승인 + 1가지 강화(divergence 시 점수도 중립 수축)에 따른 구현.

## 강화 반영
- 강한 충돌(서브스코어 부호 혼조 + 분산≥`MS_CONFLICT_DISPERSION`)이면 **신뢰도 '하'** + **점수도 50쪽으로 수축**(`MS_SHRINK` 기본 0.6, env). "강한 점수 + 낮은 신뢰도" 조합 회피. 데이터 부족(<MIN_COMPONENTS)도 동일 수축.

## 묶음
1. **DDL/스키마/저장**: 신규 `market_score(asof, region, score, direction, confidence, components, divergence_note)`(라이브 CREATE 적용). `MarketScoreRow`·`upsert_market_score`.
2. **결정론 엔진**(`compute_market_score.py`): 서브스코어 추세(`index_daily` vs SMA200·기울기)·변동성(VIX)·매크로(금리·10Y·DXY Δ 부호)·시장폭(정배열율). 가중합→0~100, 방향(60/40), 신뢰도(정합성·divergence), **divergence 수축**. 매크로는 `asof≤평가일`만(§F7 룩어헤드 금지). 뉴스 심리는 점수 미사용(해설 전용).
3. **파이프라인**(`pipeline_analysis`): `_step_market_score`(quant 뒤, daily·refresh 모두). 비치명적 격리.
4. **export**: `market.kr/us.marketScore` 부착 + 종목 `marketBetaNote`(시장점수+베타→조건부 관찰, composite 미변경). `_market_beta_note`.
5. **LLM 해설**(`enrich_market_summary`, 종합): 지역 metrics에 `MarketScore` 주입 + 프롬프트에 "점수·방향은 코드값, 설명만·매매 단정 금지" 가드. 분석→종합 순서 유지.
6. **UI**: 시장전망 탭 MarketColumn에 점수·방향 뱃지·신뢰도·서브스코어·divergence 경고("매매 신호 아님"). 종목 카드 퀀트 축에 `marketBetaNote` 한 줄.
7. **테스트**: `tests/test_market_score.py`(11) 서브스코어·공식·방향·신뢰도·**divergence 수축**·데이터부족·베타 경로 문구(매매 단정 없음). analysis 행위테스트에 `_step_market_score` 스텁(시장 점수는 새 테이블, 기존 비교 밖).

## 행위 보존/가드
- 점수·방향·신뢰도=코드, LLM=해설만. **시장→종목은 베타 경로 관찰 표시까지·composite 미합산**(3축 비합산 유지).
- 정확도 최우선: 정합성·divergence 점검, 단일 지표 의존 회피, 충돌 시 신뢰도↓ + 점수 중립 수축(가짜 확신 금지).
- §F7: 지수=진짜 계산, 매크로=발표 시점만. 시장별 최신 조회·NUMERIC float·시크릿 비저장.

## 스모크 결과(라이브 2026-06-25)
| 지역 | 점수 | 방향 | 신뢰도 | 서브스코어 |
|---|---|---|---|---|
| KR | 63.2 | 강세 | 중 | 추세+1.0·변동성−0.13·매크로+0.5·시장폭+0.36 |
| US | 56.0 | 중립 | 중 | 추세+0.47·변동성−0.13·매크로+0.33·시장폭 0 |

현재 데이터(코스피 SMA200 위·VIX 18.9 보통)에선 KR 완만 강세·US 중립 — 상식적. 구성 시나리오 검증:
- **급락+VIX35** → 26.5 **약세**(conf 상).  - **강세 추세 vs VIX35+긴축+강달러** → raw 47.2→**48.9 중립·conf 하**(divergence 수축 작동).  - **우상향+VIX12+완화** → 72.1 **강세**(conf 상).

## 후속(이번 비범위)
composite 실제 반영(보수적 cap), 트레이딩(신규-E), 매크로 서브스코어 세부 보정, 뉴스 점수 편입 여부.
