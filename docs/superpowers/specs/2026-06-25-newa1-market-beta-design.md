# 신규-A1 시장 상관·베타 설계 — 종목의 시장 민감도

> 설계 문서 (구현 아님). 종목과 자국 지수의 베타·상관을 결정론 계산해 ① 신규-D 집중 관찰 노트의 빈 베타 자리를 채우고 ② 퀀트 축 안의 시장 민감도 팩터로 표시한다. **A2(3축 해설·등급)·5-B 시장방향 연동은 이번 범위 아님** — 이번은 베타 값 자체의 계산·저장·표시까지.

## 0. 배경·원칙

- 시장 급락 시 고베타 종목이 더 위험 → 집중 종목의 변동성 기여를 "관찰"로 드러낼 때 베타가 필요.
- 베타·상관은 **과거 가격 기반 진짜 계산**(§F7 룩어헤드 없음, 회고 아님).
- **결정론 계산(코드), LLM은 서술만.** 베타는 **퀀트 축 안의 별도 팩터**로만 — 컨센서스·내 판단 축 불변, 단일 종합점수로 합치지 않음(3축 분리).

---

## 1. 베타·상관 계산 방법

### 벤치마크 (자국 지수)
- KR 종목(`watchlist.market='KR'`) → **코스피 `^KS11`**
- US 종목(`market='US'`) → **S&P500 `^GSPC`**
- 매핑은 코드 상수 `BETA_BENCHMARK = {"KR": "^KS11", "US": "^GSPC"}`.

### 입력 (저장 데이터만 — §F7-clean, 네트워크 없음)
- 종목 일간 종가: `prices_daily.close` (ticker)
- 지수 일간 종가: **`index_daily.close`** (`index_code` = 자국 지수)
  - ⚠️ 퀀트가 현재 쓰는 `compute_quant._fetch_market_history()`는 **yfinance 라이브**다. 베타는 그 경로가 아니라 **`index_daily`(저장·5년)**를 쓴다 — 재현성·§F7·무네트워크. (라이브 그래프 정점에서의 룩어헤드 위험도 제거.)
  - 확인: `index_daily`에 `^KS11`(1221행)·`^GSPC`(1255행) ~5년 존재. 부족 시 §1-결측 처리.

### 기간
- 표준 `BETA_WINDOW_DAYS = 252`(약 1년 거래일). **환경변수 `BETA_WINDOW_DAYS`로 덮어쓰기 가능.**
- 두 시계열의 **공통 거래일** 교집합에서 최근 `WINDOW`개 일간 수익률을 사용한다.

### 공식 (순수 numpy OLS — 기존 `compute_quant` idio-vol 계산과 동일 계열)
```
r_s = 종목 일간 수익률 = close.pct_change()
r_m = 지수 일간 수익률 = index_close.pct_change()
공통 거래일 정렬 → x=r_m, y=r_s
beta = cov(x, y) / var(x)             # var(x)=0이면 None
market_corr = cov(x, y) / (std(x)*std(y))   # 분모 0이면 None
```
- 읽기 경계에서 `float()` 변환(Decimal 혼용 금지), `np.log`·나눗셈 직전 방어.

### 결측·상장기간 부족 처리
- 공통 거래일 수 < `BETA_MIN_OBS`(예: 60) → `beta=None`, `market_corr=None`(가짜 값 금지).
- 지수 시계열 없음/짧음, 종목 신규상장(데이터 부족) → None.
- `var(x)=0`(지수 무변동, 비정상) → None.
- None은 저장·표시·노트 모두에서 "미산출"로 그대로 노출(추정·0 채움 금지).

---

## 2. 저장 — `quant_scores` 확장 (신규 테이블 아님)

베타는 `(ticker, asof)` 단위의 퀀트 축 지표이므로 **기존 `quant_scores`에 컬럼 추가**(ADD COLUMN, 기존 컬럼·데이터 보존). 신규 테이블/조인 불필요, 기존 종목별 최신 조회·export 경로 재사용.

```sql
ALTER TABLE quant_scores ADD COLUMN IF NOT EXISTS beta        NUMERIC;
ALTER TABLE quant_scores ADD COLUMN IF NOT EXISTS market_corr NUMERIC;
```
- `beta`: 자국 지수 대비 베타(예: 1.30). `market_corr`: 상관계수(−1~1).
- 벤치마크 지수는 종목 `market`에서 결정(KR→^KS11, US→^GSPC)되므로 별도 컬럼 불필요. 기간은 `BETA_WINDOW_DAYS` 상수(문서·로그로 추적).
- `QuantScoresRow`(pydantic)에 `beta: Optional[float]=None`, `market_corr: Optional[float]=None` 추가. 읽기 경계 float.
- **종목별 최신 조회 유지**: export는 기존 `SELECT DISTINCT ON (ticker) ... FROM quant_scores ORDER BY ticker, asof DESC`에 두 컬럼만 추가.

대안(검토 후 비채택): 신규 `market_sensitivity` 테이블 — 같은 grain·같은 조회 패턴이라 분리 이득 없음. quant_scores 확장이 단순·일관.

---

## 3. 퀀트 축 반영 방법

- 베타·상관은 **퀀트 축 안의 별도 "시장 민감도" 팩터**로 둔다. 기존 5팩터(모멘텀/가치/우량성/성장/심리)와 **병렬**.
- **`composite`(퀀트 종합)에 합산하지 않는다.** 베타는 percentile/zscore로 5팩터에 섞지 않고, **원시 값(raw beta·corr)**으로 별도 표시·저장한다. → 3축 비합산 + 퀀트 종합 의미 보존.
- 즉 이번 단계의 퀀트 축 변화는 "composite 옆에 시장 민감도(베타) 보조 지표 추가"이며, **점수 가중치·composite 공식·사전필터는 불변**.
- **시장 전망 연동은 5-B 이후**: "시장 전망이 나쁠 때 고베타 종목 매력도 하향"은 5-B(시장방향)가 나온 뒤 별도 단계. 이번엔 베타 값 자체의 계산·저장·표시까지만. (단, 표시 문구에서 "베타↑ = 시장 변동에 민감"이라는 중립적 사실 설명은 허용.)

---

## 4. 신규-D 관찰 노트 연동

- `stock_action_advice.derive_concentration_note(current_weight, beta=...)`는 이미 베타 인자를 받는다. 현재 `build_action_frame`은 `stock.get("beta")`를 넘기는데 export가 beta를 안 실어 항상 None이었다.
- **연동**: export가 `beta`를 stock dict에 실으면(§5) 노트가 자동으로 베타를 채운다.
  - 예: `현재 비중 33.9% · 베타 1.30 — 단일 종목 비중이 높아 시장 급락 시 포트폴리오 변동성에 크게 기여합니다. 판단은 본인 몫입니다.`
- **톤은 신규-D 그대로**: 사실+영향만, 평가어·지시어 금지(`is_observation_clean` 가드 그대로). 베타는 수치 사실로만("베타 1.30"), "고위험/줄여라" 같은 판단 금지.
- beta=None이면 기존처럼 베타 문구 생략(graceful).

---

## 5. 표시 (UI)

### 종목상세 — 퀀트 축(AxesCard) 안
- 퀀트 축 영역에 **"시장 민감도" 보조 라인** 추가: `베타 1.30 · 상관 0.62 (코스피, 1년)`.
  - 벤치마크명(코스피/S&P500)·기간(1년) 라벨 동반(출처 명시).
  - composite 점수와 **분리** 표기 — 합산처럼 보이지 않게.
  - beta=None → "시장 민감도 미산출"(데이터 부족), 0 채움 금지.
- 매력도 3축은 그대로(퀀트/컨센서스/내 판단 나란히). 베타는 퀀트 축 내부 보조 지표일 뿐 새 축이 아니다.

### export 계약
- 종목 dict에 `beta`, `marketCorr` 추가(quant_scores 최신 행에서). `actionAdvice`는 noté로만 노출(별도 필드 불필요).
- 글로벌 max(asof) 금지 — 기존 quant DISTINCT ON 패턴 유지.

---

## 6. §F7 — 가격 기반 진짜 계산

- 베타·상관은 **asof 시점까지의 과거 일간 수익률만** 사용하는 **진짜 통계**다. 미래 데이터·룩어헤드 없음.
- §F7의 "회고(retrospective, 선정시점편향)"는 **오늘 스냅샷으로 과거 성과를 추정**하는 팩터 백테스트를 가리킨다. 베타는 그 범주가 **아니다** — 시점별로 그 시점 데이터만 쓰는 historical statistic이라 true 계산이다.
- 화면/코드에서 베타를 "백테스트 회고"와 혼동 표기하지 않는다(별도 보조 지표).

---

## 7. 파이프라인 편입 — `pipeline_analysis`(분석 소관, 수집 아님)

- 베타는 **수집(pipeline_ingest)이 아니라 분석(pipeline_analysis)** 단계에서 계산한다. 입력(prices_daily·index_daily)이 DB에 이미 있다는 전제(분석은 외부 수집·LLM 호출 안 함).
- 위치: **퀀트 계산(`compute_quant_universe`) 내부**에서 종목별로 `beta`/`market_corr`를 함께 산출해 `quant_scores` row에 채운다(이미 idio-vol에서 OLS를 쓰므로 자연스럽게 확장). 별도 step 추가도 가능하나 같은 입력·같은 grain이라 quant 내부가 단순.
- 벤치마크 시계열은 `index_daily`에서 1회 로드해 KR/US 두 시리즈를 캐시(종목마다 재쿼리 금지).
- `daily`·`refresh` 모두 퀀트를 돌리므로 양 프로필에서 갱신된다(refresh도 지표·퀀트 실행).
- 운영 주의: `index_daily` 5년 이력은 일일 cron 밖의 **별도 백필 경로**(W3-A `ingest_index_history`)다. 베타는 index_daily의 **최신 가용 asof까지**를 쓰며, 벤치마크가 며칠 지연돼도 베타(완만한 통계)에는 영향 미미. 정확도 위해 index_daily를 주기적으로 갱신(별도 운영 작업)할 것을 권고.

---

## 8. 구현 범위 / 비범위 (승인 후)

**이번(A1)에 한다:** `quant_scores`에 beta/market_corr ADD COLUMN + `QuantScoresRow` 확장, `compute_quant`에서 index_daily 기반 결정론 베타·상관 계산, export에 `beta`/`marketCorr`, 신규-D 노트 베타 자동 충전, 종목상세 퀀트 축 "시장 민감도" 표시, 단위 테스트(공식·결측·기간·벤치마크 매핑·노트 충전·composite 불변).

**안 한다(이번 범위 아님):** A2(3축 해설·등급), 5-B 시장방향 연동(고베타 매력도 하향), composite에 베타 가중 편입, 다중 벤치마크/롤링 베타 시계열.

---

## 9. 미해결/검토 포인트

1. `BETA_WINDOW_DAYS`(252) / `BETA_MIN_OBS`(60) 초기값 — 신규상장·짧은 이력 종목 None 비율 보고 후 보정.
2. KR 종목 중 코스닥 상장은 벤치마크를 ^KS11로 둘지 ^KQ11(코스닥)로 둘지 — 1차는 단순화해 KR=^KS11, 필요 시 종목별 지수 매핑 확장.
3. `index_daily` 갱신 주기(현재 별도 백필) — 베타 신선도 위해 정기화 여부.
4. 상관 표시 임계/색상(예: |corr|<0.3 "시장과 약한 연동") 문구 — 표시 단계에서 확정.

---

*설계 문서이며 구현이 아니다. 승인 후 구현. 투자 자문 아님 / 원금 손실 가능.*
