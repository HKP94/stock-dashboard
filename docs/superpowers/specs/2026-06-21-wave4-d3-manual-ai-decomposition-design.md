# Wave 4-D-3 수동 자유 텍스트 → AI 분해 설계

## 목표

사용자가 종목 단위 또는 시장 단위 자유 텍스트를 붙여넣으면, ATLAS가 이를 구조화된 분석 결과로 분해해 저장하고 기존 자동 수집분과 함께 보여준다. 이 기능은 기존 `내 판단` 축을 대체하지 않으며, 별도 `AI 분해 분석` 레이어로 유지한다.

## 비목표

- 자동 주문, 주문 유도, 실행 경로 추가
- `stock_notes` / `stock_note_history` 구조 변경
- 대량 뉴스 처리 모델 교체
- 시장 입력을 종목과 직접 연결하는 기능의 이번 단계 구현

## 확정 원칙

- `내 판단`과 `AI 분해 분석`은 별도 레이어로 유지한다.
- 자동 수집(뉴스·컨센서스)과 수동 AI 분해를 합산·병합하지 않는다.
- `raw_text`는 DB에 전체 저장하되 UI 기본 숨김, 로그 전체 출력 금지.
- 수동 입력은 누적 저장하고 덮어쓰지 않는다. 기본 화면은 최신 1건, 과거 입력 보기를 별도 제공한다.
- `origin='user'` 성격의 자료는 자동 재생성이나 재분해가 덮어쓰지 않게 보호한다.
- 단/중/장 매력도는 숫자 점수가 아니라 `label + rationale` 구조로 저장한다.
- Gemini 상위 모델은 이 수동 분해 기능에만 사용하고, 대량 뉴스 선별은 기존 Flash-Lite 유지한다.

## 접근 방식

이번 기능은 분리 보존형 저장 구조를 따른다.

- 자동 수집분은 기존 `analyst`, `analyst_views`, `ticker_context`, `news_analysis`를 유지한다.
- 수동 자유 텍스트 입력은 새 부모-자식 구조에 저장한다.
- 화면은 세 출처를 나란히 보여준다.
  1. 내 판단(사용자 직접 입력)
  2. AI 분해 분석(사용자 제공 외부 자료의 구조화 결과)
  3. 자동 수집(뉴스·컨센서스)

이 구조는 출처 경계를 흐리지 않고, 수정 보호와 이력 추적을 단순하게 만든다.

## 데이터 모델

### 1) 종목 수동 입력 부모: `manual_research_entries`

한 번의 자유 텍스트 입력을 나타낸다.

권장 컬럼:

- `id BIGSERIAL PRIMARY KEY`
- `ticker TEXT NOT NULL`
- `raw_text TEXT NOT NULL`
- `source TEXT` — 증권사명/유튜버명/자유 메모
- `source_url TEXT`
- `inferred_source TEXT` — Gemini가 원문에서 추정한 출처명
- `created_at TIMESTAMPTZ DEFAULT now()`
- `updated_at TIMESTAMPTZ DEFAULT now()`

규칙:

- 같은 종목에 여러 행이 누적된다.
- 새 입력은 기존 행을 덮어쓰지 않는다.
- `raw_text`는 검증용 1차 근거로 보존한다.

### 2) 종목 수동 입력 horizon: `manual_research_horizons`

각 입력에 대해 단기/중기/장기 관점을 저장한다.

권장 컬럼:

- `id BIGSERIAL PRIMARY KEY`
- `entry_id BIGINT NOT NULL REFERENCES manual_research_entries(id) ON DELETE CASCADE`
- `horizon TEXT NOT NULL` — `short | mid | long`
- `attractiveness_label TEXT NOT NULL` — 예: `매력적 | 다소 매력적 | 중립 | 다소 비매력적 | 비매력적`
- `rationale TEXT NOT NULL`
- `is_user_confirmed BOOLEAN DEFAULT FALSE`
- `created_at TIMESTAMPTZ DEFAULT now()`
- `updated_at TIMESTAMPTZ DEFAULT now()`
- `UNIQUE(entry_id, horizon)`

규칙:

- 숫자 점수 금지
- `is_user_confirmed=true`면 이후 raw_text 재분해가 이 행을 덮어쓰지 못한다.

### 3) 종목 수동 입력 논거: `manual_research_points`

각 입력에 대해 bull/bear 논거를 여러 개 저장한다.

권장 컬럼:

- `id BIGSERIAL PRIMARY KEY`
- `entry_id BIGINT NOT NULL REFERENCES manual_research_entries(id) ON DELETE CASCADE`
- `stance TEXT NOT NULL` — `bull | bear`
- `point TEXT NOT NULL`
- `source_label TEXT`
- `source_url TEXT`
- `is_user_confirmed BOOLEAN DEFAULT FALSE`
- `created_at TIMESTAMPTZ DEFAULT now()`
- `updated_at TIMESTAMPTZ DEFAULT now()`

규칙:

- 사용자가 논거 문구를 직접 수정하면 해당 행을 `is_user_confirmed=true`로 바꾼다.
- 이후 재분해는 이 사용자 확정 행을 삭제/갱신하지 못한다.

### 4) 종목 수동 입력 컨센서스 추출: `manual_research_consensus`

원문에 목표가/투자의견이 있으면 추출해 저장한다.

권장 컬럼:

- `entry_id BIGINT PRIMARY KEY REFERENCES manual_research_entries(id) ON DELETE CASCADE`
- `target_price NUMERIC`
- `rating_label TEXT`
- `rating_score NUMERIC`
- `is_user_confirmed BOOLEAN DEFAULT FALSE`
- `created_at TIMESTAMPTZ DEFAULT now()`
- `updated_at TIMESTAMPTZ DEFAULT now()`

규칙:

- 없으면 `NULL`
- 사용자가 직접 수정하면 `is_user_confirmed=true`
- 읽기 경계에서는 float 변환

### 5) 시장 수동 입력: `market_view_manual`

시장 단위 자유 텍스트 1건을 저장한다.

권장 컬럼:

- `id BIGSERIAL PRIMARY KEY`
- `asof DATE NOT NULL`
- `scope TEXT NOT NULL DEFAULT 'market'`
- `raw_text TEXT NOT NULL`
- `bull_scenario TEXT`
- `bear_scenario TEXT`
- `source TEXT`
- `source_url TEXT`
- `created_at TIMESTAMPTZ DEFAULT now()`
- `updated_at TIMESTAMPTZ DEFAULT now()`

규칙:

- 이번 단계는 `scope='market'`만 사용한다.
- 향후 종목 연결 확장을 위해 `scope`만 미리 둔다. 종목 연결 기능은 구현하지 않는다.

## Gemini 분해 계약

### 종목 입력

입력:

- ticker
- 회사명
- raw_text
- 사용자 입력 source/source_url

출력 구조:

- `inferredSource: string | null`
- `consensus: { targetPrice, ratingLabel, ratingScore } | null`
- `bullPoints: [{ point, sourceLabel, sourceUrl }]`
- `bearPoints: [{ point, sourceLabel, sourceUrl }]`
- `horizons: [
    { horizon: 'short', attractivenessLabel, rationale },
    { horizon: 'mid', attractivenessLabel, rationale },
    { horizon: 'long', attractivenessLabel, rationale }
  ]`

제약:

- 입력 텍스트에 근거한 것만 추출
- 기사/리포트/스크립트에 없는 내용을 만들지 않음
- 강세/약세가 한 문서에 함께 있으면 분리
- 매매 단정 문구 금지
- 출처 URL이 없으면 null 허용

모델:

- 상위 모델 전용 상수 사용 예: `GEMINI_MANUAL_RESEARCH_MODEL`
- 기존 bulk/news 모델과 분리
- timeout과 전체 시간 예산 준수

### 시장 입력

입력:

- raw_text
- source/source_url
- asof

출력 구조:

- `bullScenario`
- `bearScenario`

제약:

- 양면 시나리오만 제시
- 입력 텍스트에 없는 낙관/비관 시나리오 창작 금지
- 정책·금리·유가·환율·실적 시즌 등 원문 근거 중심 요약

## 수정/재분해 정책

### raw_text 수정

- 같은 `entry_id`의 `raw_text`가 바뀌면 재분해 허용
- 단, 사용자 확정(`is_user_confirmed=true`) 행은 보호
- 보호되지 않은 AI 생성 horizon/point/consensus만 새 결과로 갱신

### 분해 결과 직접 수정

- 사용자가 horizon label/rationale, bull/bear 논거, 추출 컨센서스를 직접 수정 가능
- 수정된 항목은 즉시 `is_user_confirmed=true`
- 이후 재분해는 해당 항목을 덮어쓰지 못함

이 정책으로 AI 생성값과 사용자 확정값을 명시적으로 분리한다.

## local_api 설계

### 종목 수동 입력

필수 엔드포인트:

- `POST /api/manual-research` — 새 raw_text 입력 + Gemini 분해 + 저장
- `GET /api/manual-research/{ticker}` — 최신 1건 + 이력
- `PATCH /api/manual-research/{entry_id}`
  - raw_text/source/source_url 수정
  - horizon/point/consensus 직접 수정
- `DELETE /api/manual-research/{entry_id}` — 부모와 자식 삭제

### 시장 수동 입력

필수 엔드포인트:

- `POST /api/manual-market-view`
- `GET /api/manual-market-view`
- `PATCH /api/manual-market-view/{id}`
- `DELETE /api/manual-market-view/{id}`

공통 규칙:

- CORS `allow_methods`에 `PATCH`, `DELETE`, `OPTIONS` 포함
- DB 쓰기는 단계별 commit/rollback
- raw_text 전체 로그 금지; 길이/sha256 일부만 로깅

## export 설계

### 종목 payload 확장

각 stock payload에 추가:

- `manualResearchLatest`
  - 최신 1건
  - raw_text는 기본 포함 가능하되 UI는 접힘 표시
- `manualResearchHistory`
  - 최신순 목록
- `aiDecompositionSummary`
  - 화면 합성 편의를 위한 얇은 파생 필드

표시 규칙:

- 최신 1건 기준으로 `AI 분해 분석` 카드 구성
- 과거 입력은 토글로 확장
- 조회는 종목별 최신/최근만 사용. 글로벌 max(asof) 금지

### 시장 payload 확장

- `market.manualViewLatest`
- `market.manualViewHistory`

## UI 설계

### 1) 리서치 탭(애널리스트 뷰)

추가 구성:

- 종목 선택 아래 큰 textarea
- 선택 입력: 출처 메모, 출처 URL
- `분석` 버튼
- 분석 완료 후 `AI 분해 분석` 카드
  - 단기/중기/장기 attractiveness label + rationale
  - bull 논거 / bear 논거
  - 추출된 목표가·투자의견(있으면)
  - 출처 배지: `직접입력`, `AI 분해`, `자동`
  - `원문 보기` 토글(기본 닫힘)
  - `과거 입력 보기` 토글

빈 상태:

- 수동 입력 없으면 `직접 입력한 분석 없음`
- 한쪽 논거가 없으면 `수집된 약세 논거 없음` 같은 문구 유지

### 2) 종목상세 탭

세 출처 병렬 표시:

1. `내 판단`
2. `AI 분해 분석`
3. `자동 수집 근거`

목표:

- 세 출처의 일치/괴리를 읽게 함
- 합산 점수 금지
- 기존 `AxesCard`와 충돌하지 않도록 별도 섹션으로 배치

### 3) 시장전망 탭

추가 구성:

- 자유 텍스트 입력 textarea
- 출처 메모/URL
- `분석` 버튼
- 최신 시장 수동 분석 카드
  - 강세 시나리오
  - 약세 시나리오
  - 원문 보기 토글
  - 과거 입력 보기 토글

## 테스트 전략

### 백엔드

- 스키마/DDL 테스트
- manual research row grouping/export 테스트
- local_api CRUD 테스트
- CORS 회귀 테스트
- Gemini 출력 파서 테스트
- 사용자 확정 플래그 보호 테스트
- raw_text 수정 시 재분해 갱신 테스트

### 프런트

- 표시 헬퍼 테스트
- 최신 1건 / 과거 토글 렌더 규칙 테스트
- 빈 상태 텍스트 테스트
- 출처 배지/원문 토글 테스트

### 스모크(필수)

실제 애널리스트 보고서 성격 텍스트 1건으로 확인:

- 목표가/투자의견 추출 여부
- bull/bear 논거 수
- 단기/중기/장기 label + rationale
- 원문과 결과 대조 가능 여부
- 로그에 raw_text 전체 미노출 여부(길이/해시만)

## 구현 순서 제안

1. DDL + pydantic/local_api 입력 모델
2. Gemini 수동 분해 계약 + 파서
3. local_api 종목/시장 CRUD
4. export 확장
5. 리서치 탭 UI
6. 종목상세/시장전망 통합 표시
7. 스모크 + 문서 갱신

## 리스크와 완화

- **AI 창작 위험** → 스키마와 프롬프트에서 입력 근거만 허용, 원문 보존으로 검증 가능하게
- **재분해가 사용자 수정 덮어쓰기** → `is_user_confirmed` 보호
- **화면 과밀화** → 최신 1건 기본 + 토글 확장
- **비용 증가** → 수동 분해에만 상위 모델, 대량 처리 모델 분리 유지
- **민감정보 유출** → raw_text 로그 금지, DB 저장만 허용
