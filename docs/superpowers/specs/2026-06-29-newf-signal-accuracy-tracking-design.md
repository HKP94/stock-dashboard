# 신규-F 신호 적중률 추적 설계

> 설계 문서 (구현 아님). ATLAS가 생성한 신호·등급이 사후에 맞았는지를 결정론으로 측정하는 **전향 자기검증 틀**이다. 1차 추적 대상은 A2 등급(매수/관망/축소). 같은 틀로 E1/E2/5-B 신호를 확장할 수 있다.

---

## 0. 원칙 & 면책

- **§F7 전향검증(forward test)**: asof 시점의 등급은 그 시점까지의 정보만으로 만들었다(룩어헤드 없음). 사후 성과 측정은 asof 이후 가격만 사용한다.
- **결정론 계산**: 적중 여부·수익률·IC는 코드가 계산한다. LLM은 해설만.
- **통계적 겸손 필수**: 초기에는 표본이 수십 건 미만이라 통계 검정력이 없다. 모든 지표에 `n` 을 병기하고, n < 30인 경우 "통계적 의미 미달" 경고를 표시한다.
- **생존편향 경고**: 추적 시점에 active=FALSE로 비활성화된 종목은 과거 등급 기록이 있더라도 조회에서 누락될 수 있다. 조회 시 active 필터를 건 경우 이를 명시한다.
- **실제 매매 성과 아님**: 신호 발생 다음 거래일 종가 기준이며, 체결가·슬리피지·수수료·세금이 미반영되어 실제 수익률과 다르다. "신호 성과(signal P&L)"이지 "포트폴리오 수익률"이 아니다.
- **3축 비합산 원칙 유지**: A2 등급은 3축 정렬 패턴으로 도출되었으므로, 적중률 측정도 A2 등급 단위로만 한다. 퀀트·컨센서스·내 판단 점수를 합산해 별도 점수를 만들지 않는다.

---

## 1. 데이터 소스 & 룩어헤드 방지

### 1.1 소스 테이블

| 테이블 | 사용 컬럼 | 용도 |
|---|---|---|
| `stock_action_advice` | `ticker, asof, grade, grade_confidence` | 과거 등급 이력 (시계열) |
| `prices_daily` | `ticker, date, close` | 진입가·청산가 계산 |
| `index_daily` | `ticker(^KS11/^KQ11/^GSPC), date, close` | 벤치마크 수익률 |
| `watchlist` | `ticker, market` | 벤치마크 배정(KR→KOSPI·KOSDAQ, US→S&P500) |

### 1.2 수익률 계산 정의

```
진입가 (entry_close):
  prices_daily WHERE ticker=T AND date = (asof 이후 첫 거래일 종가)

N일 후 청산가 (exit_close):
  prices_daily WHERE ticker=T AND date >= (진입일 + N 영업일)
  ORDER BY date ASC LIMIT 1

raw_return   = exit_close / entry_close - 1
bench_return = (벤치마크 exit_close / 벤치마크 entry_close) - 1
excess_return = raw_return - bench_return
```

**룩어헤드 방지 체크리스트**:
- ✅ 등급 생성(asof)에는 asof 이전 데이터만 사용됨 (compute_quant·derive_grade 결정론)
- ✅ 성과 측정은 asof 이후의 `prices_daily` 값만 참조
- ✅ 진입가는 asof 당일이 아니라 **다음 거래일 종가** (당일 장마감 후 등급 확정 → 다음날 진입 가정)
- ⚠️ 배당·액면분할 미조정: `prices_daily`가 수정주가면 OK, 원주가면 과거 분할 종목 왜곡 가능 → 메타데이터에 명시

### 1.3 벤치마크 배정

| 시장 | 기본 벤치마크 | 코스닥 종목 예외 |
|---|---|---|
| KR | `^KS11` (KOSPI) | `KOSDAQ_TICKERS` env 목록 → `^KQ11` |
| US | `^GSPC` (S&P500) | — |

벤치마크 가격도 `index_daily` 테이블에서 읽는다(yfinance 라이브 호출 금지 — §F7 재현성, 무네트워크).

---

## 2. 추적 기간 (N)

복수 기간을 병행 계산한다. 단일 기간에 집착하면 노이즈에 취약하고, 기간마다 전략 성격이 다르기 때문이다.

| N (영업일) | 약 달력 기간 | 적합 신호 | 이유 |
|---|---|---|---|
| **5일** | ~1주 | E1 트레이딩 신호, E2 수급 신호 | 단기 모멘텀 반응 확인 |
| **20일** | ~1달 | A2 등급, E1/E2 교차 | 중기 추세 반응; 뉴스·이벤트 소화 기간 |
| **60일** | ~3달 | A2 등급, 5-B 시장 방향 | 퀀트·컨센서스 기반 등급은 분기 단위가 현실적 |

구현 시 세 값을 모두 계산·저장한다. UI는 기본 20일 기준 노출, 5/60일을 탭/드롭다운으로 전환.

---

## 3. 적중(Hit) 정의

### 3.1 A2 등급별 적중 기준

초과수익(`excess_return = raw_return - bench_return`)을 기본 기준으로 한다. 절대수익(`raw_return`)은 부수 참고 지표로 병행 계산한다.

| 등급 | 적중(hit=1) | 비적중(hit=0) | 미결(pending) |
|---|---|---|---|
| **매수** | `excess_return > 0` | `excess_return ≤ 0` | 아직 N일 미경과 |
| **축소** | `excess_return < 0` | `excess_return ≥ 0` | 아직 N일 미경과 |
| **관망** | `\|excess_return\| ≤ NEUTRAL_BAND` | `\|excess_return\| > NEUTRAL_BAND` | 아직 N일 미경과 |

`NEUTRAL_BAND`: 관망 적중 판정 허용 구간. 초기값 10%p (= −10% < excess_return < +10%). 구현 시 코드 상수로 추출(`GRADE_NEUTRAL_BAND = 0.10`).

**관망 적중 해석 주의**: "관망 = 시장을 크게 이기지도 지지도 않는 구간"이라는 정의는 임의적이다. 관망의 주된 의미는 "지금 매수 추가나 축소 행동을 안 해도 된다"이므로, **관망 적중률보다 매수·축소의 방향 정확도(IC)**가 더 유의미한 지표다.

### 3.2 초과수익 vs 절대수익 선택 이유

초과수익 기준을 기본으로 하는 이유: 강세장에서는 매수 절대수익이 양수이기 쉬워 적중률이 과대평가된다. 초과수익 기준은 "시장 대비 신호의 부가가치"를 측정하므로 알파 추정에 더 적합하다.

단, 개인 투자자 관점에서 "내 계좌가 실제로 올랐나"는 절대수익이 직관적이므로, 양쪽 모두 계산해 UI에서 전환 가능하게 설계한다.

---

## 4. 측정 지표 (Metrics)

### 4.1 등급별 지표

| 지표 | 설명 | 수식/방법 |
|---|---|---|
| `hit_rate` | 적중 비율 | `sum(hit) / n` (pending 제외) |
| `mean_excess` | 평균 초과수익 | `mean(excess_return)` |
| `mean_raw` | 평균 절대수익 | `mean(raw_return)` |
| `std_excess` | 초과수익 표준편차 | `std(excess_return)` |
| `n` | 표본 수 | 미결 제외 |
| `n_pending` | 미결(아직 N일 미경과) 수 | — |

### 4.2 전체 신호 지표

| 지표 | 설명 | 비고 |
|---|---|---|
| `IC` | Spearman(grade_score, excess_return) | grade 숫자화: 매수=+1, 관망=0, 축소=−1 |
| `IC_raw` | Spearman(grade_score, raw_return) | 부수 참고 |
| `IC_se` | IC 표준오차 ≈ 1/√n | 신뢰구간: IC ± 1.96 × IC_se |
| `p_value` | IC t-검정 (양측) | n < 30이면 p 의미 없음 명시 |

**IC 해석**: IC > 0.05를 "약한 예측력", IC > 0.10을 "중간 예측력"으로 참고(업계 팩터 관행). 단, n이 작을 때는 IC 자체가 노이즈다.

### 4.3 표본 크기 경고 기준

| n | 경고 |
|---|---|
| < 10 | "표본 부족 — 참고 불가" |
| 10 ~ 29 | "표본 소규모 — 추세 참고만" |
| ≥ 30 | 기본 통계 해석 가능 |
| ≥ 100 | IC t-검정 유의성 신뢰 가능 |

---

## 5. 저장 스키마: `signal_grade_track`

재계산 비용이 낮고(prices_daily JOIN만 필요) 확장 대상 신호가 여럿이므로, **계산 후 저장(캐시)** 방식을 택한다. 새로운 N일이 경과한 행이 생길 때마다 UPDATE로 채운다.

```sql
CREATE TABLE IF NOT EXISTS signal_grade_track (
    id          BIGSERIAL PRIMARY KEY,
    signal_type TEXT        NOT NULL,          -- 'A2_grade' | 'E1_trading' | 'E2_investor' | '5B_market'
    ticker      TEXT        NOT NULL,          -- 종목 티커 (시장 신호면 'KR'/'US' 등 pseudo)
    asof        DATE        NOT NULL,          -- 신호 생성일
    grade       TEXT        NOT NULL,          -- 원 신호 값 ('매수'/'관망'/'축소' 또는 각 신호 라벨)
    grade_conf  TEXT,                          -- 신뢰도 (있으면)
    n_days      INTEGER     NOT NULL,          -- 5 | 20 | 60
    entry_date  DATE,                          -- 진입일 (asof 다음 거래일)
    entry_price NUMERIC,                       -- 진입가 (종가)
    exit_date   DATE,                          -- 청산일 (entry_date + n_days 영업일)
    exit_price  NUMERIC,                       -- 청산가 (종가)
    bench_entry NUMERIC,                       -- 벤치마크 진입가
    bench_exit  NUMERIC,                       -- 벤치마크 청산가
    raw_return  NUMERIC,                       -- (exit/entry - 1)
    bench_return NUMERIC,                      -- 벤치마크 동기간 수익률
    excess_return NUMERIC,                     -- raw_return - bench_return
    hit_excess  BOOLEAN,                       -- excess_return 기준 적중 (pending이면 NULL)
    hit_raw     BOOLEAN,                       -- raw_return > 0 기준 적중 (pending이면 NULL)
    pending     BOOLEAN     NOT NULL DEFAULT TRUE,  -- 아직 N일 미경과
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (signal_type, ticker, asof, n_days)
);

CREATE INDEX IF NOT EXISTS idx_sgt_type_ticker ON signal_grade_track (signal_type, ticker);
CREATE INDEX IF NOT EXISTS idx_sgt_asof ON signal_grade_track (asof);
CREATE INDEX IF NOT EXISTS idx_sgt_pending ON signal_grade_track (signal_type, pending);
```

**`pending` 플래그 운영**: 매 실행 시 `pending=TRUE`이고 `exit_date <= today`인 행을 찾아 `prices_daily`에서 exit_price를 채운다. N일이 아직 안 지난 행은 pending 상태 유지.

---

## 6. 계산 위치 & 파이프라인 통합

### 6.1 모듈: `compute_signal_track.py` (신규)

```
역할: signal_grade_track 테이블 채우기
입력: signal_type 필터, 계산할 n_days 목록, 기준일(오늘)
출력: upsert 행 수 (로그)

흐름:
  1. stock_action_advice에서 아직 signal_grade_track에 없는 (ticker, asof, grade) 신규 행 조회
  2. entry_date·entry_price 채우기 (prices_daily 조인)
  3. n_days별로 exit_date 계산 → prices_daily에서 exit_price 조회
  4. 수익률·hit 계산 → upsert
  5. pending=TRUE인 행 중 exit_date <= today인 행 UPDATE (pending→FALSE, 수익률 채우기)
```

- 결정론 계산 (네트워크·LLM 없음)
- 단일 DB 조인으로 처리 (종목별 루프 최소화)
- 실패 시 `runs.errors` 기록, 파이프라인 전체 중단 안 함 (부분 실패 격리)

### 6.2 실행 주기

`compute_signal_track`은 **매일 파이프라인 필수 단계가 아니다**. 두 가지 방식을 병행:

1. **pipeline_analysis에 선택적 단계로 통합**: 분석 실행기 마지막에 `_step_signal_track(conn, errors)` 추가. daily 프로파일에서만 실행 (refresh는 스킵).
2. **수동 재계산**: `python -m src.compute_signal_track` — 최초 구축 또는 과거 A2 등급 일괄 처리.

### 6.3 초기 과거 데이터 처리

`stock_action_advice`에 이미 축적된 과거 asof별 등급이 있다면, 수동 1회 실행으로 일괄 계산한다. 이때 오늘 기준으로 N일이 이미 지난 과거 행은 즉시 hit 계산이 가능하다.

---

## 7. 표시 설계: "신호 성과" 뷰

### 7.1 위치

리서치(애널리스트 뷰) 탭 하단 또는 별도 "성과 추적" 섹션. 연구 도구이지 메인 워크플로가 아니므로 하단 배치.

### 7.2 요약 카드 (등급별 × N기간)

```
[A2 등급 신호 성과] — n=32, 추적 시작: 2026-05-15
                 5일      20일     60일
매수 적중률      58%      62%      —¹
  평균 초과수익  +2.1%    +4.3%    —¹
축소 적중률      44%      51%      55%
  평균 초과수익  −1.3%    −3.1%    −5.2%
IC(등급↔초과수익)  0.06    0.11     0.09
                (p=0.28) (p=0.05) (p=0.12)

¹ 60일 미경과(pending 중)
※ 통계적 의미: n=32, 추가 데이터 필요 (n≥100 권장)
※ 실제 매매 성과 아님 — 다음 거래일 종가 기준, 수수료·세금 미포함
```

### 7.3 시계열 차트

- X축: 분기(등급 생성 시기), Y축: 해당 분기 매수 적중률
- 점선: 50% 기준선 (무작위 기준)
- 등급별 평균 초과수익 막대 (양수=초과, 음수=미달)

### 7.4 종목별 드릴다운

스크리너에서 종목 선택 시 해당 종목의 등급별 적중 이력 테이블 표시:

```
005930.KS (삼성전자)
asof       등급   신뢰도   진입가  20일후   초과수익  적중
2026-05-01 매수   중      72,400   75,200   +4.2%    ✓
2026-04-01 관망   하      74,000   71,800   −3.8%    —
2026-03-01 축소   상      78,500   72,100   −8.3%    ✓
```

### 7.5 면책 표시 (고정)

> "신호 성과는 전향검증 결과이며 실제 매매 수익률이 아닙니다. 슬리피지·수수료·세금 미반영. 투자 자문 아님 / 원금 손실 가능."

---

## 8. 확장성: 다른 신호 추가 방법

`signal_grade_track.signal_type` 컬럼이 확장 포인트다. 새 신호를 추가할 때:

1. `signal_type` 값과 `grade` 어휘를 정의한다.
2. 소스 테이블과 조인 방법을 `compute_signal_track.py`에 등록한다.
3. 벤치마크·N일·적중 기준을 상수로 추가한다.

| 신호 유형 | `signal_type` | 소스 테이블 | 적합 N | 적중 기준 |
|---|---|---|---|---|
| A2 등급 (1차) | `'A2_grade'` | `stock_action_advice.grade` | 5/20/60 | excess > 0 (매수), < 0 (축소) |
| E1 트레이딩 신호 | `'E1_trading'` | `indicators_daily.trading_signal` | 5/20 | excess > 0 (단기매수우호) |
| E2 투자자 수급 | `'E2_investor'` | `investor_flow.signal` | 5/20 | excess > 0 (강세) |
| 5-B 시장 방향 | `'5B_market'` | `market_score.direction` | 20/60 | 지수 return > 0 (강세) |

티커가 없는 시장 신호(5-B)는 `ticker = 'KR'` 또는 `ticker = 'US'` pseudo-ticker를 사용하고, 가격 대신 `index_daily` 수익률을 raw_return으로 사용한다.

---

## 9. §F7 전향검증 요건 체크리스트

| 요건 | 구현 방법 | 상태 |
|---|---|---|
| asof 이전 정보만으로 등급 생성 | compute_quant·derive_grade가 asof 당일까지 데이터만 사용 (기존 설계 ✓) | 기존 보장 |
| 성과 측정은 asof 이후 가격만 | entry_date = asof 다음 거래일, exit_date = entry_date + N일 | 설계 |
| 생존편향 경고 | active=FALSE 종목 포함 여부를 UI에 명시 | 설계 |
| 표본 크기 표시 | 모든 지표에 n, n_pending 병기 | 설계 |
| 실제 체결 아님 명시 | UI 고정 면책 문구 | 설계 |
| 배당/분할 조정 여부 명시 | 메타데이터에 "prices_daily 수정주가 여부" 기록 | 구현 시 확인 |
| 선택편향 부재 | 등급을 생성한 모든 종목을 대상 (선별 없음) | 설계 |

---

## 10. 구현 우선순위 제안

설계만 확정하고 구현은 데이터 축적 후 의미가 생기므로 **지금 당장 구현할 필요 없다**. 제안 순서:

1. **마이그레이션**: `signal_grade_track` 테이블 생성 (데이터 축적 선행)
2. **`compute_signal_track.py`**: A2 등급 전용 계산기 (100줄 내외)
3. **pipeline_analysis 통합**: `_step_signal_track` (5줄 호출 래퍼)
4. **export 추가**: `signalAccuracy` 섹션 (등급별 요약)
5. **UI**: 리서치 탭 하단 "신호 성과" 카드

E1/E2/5-B 확장은 A2 검증 후 동일 틀로 순차 추가.

---

## 11. 미결 질문 (PM 확인 필요)

1. **관망 적중 기준**: `NEUTRAL_BAND=10%p` 가 적절한가, 아니면 관망 적중률 자체를 표시하지 않는 것이 나은가?
2. **prices_daily 수정주가**: 현재 prices_daily는 수정주가인가 원주가인가? 과거 분할 종목(삼성전자 2018년 50:1 분할 등) 처리 여부 확인 필요.
3. **export 포함 여부**: signalAccuracy를 data.json에 넣으면 로컬 전용. 표본이 쌓이면 추가하기로.
4. **pipeline_analysis 통합 시점**: 표본이 의미 있는 크기(n≥30)가 될 때 UI를 활성화하는 게 맞는가?
