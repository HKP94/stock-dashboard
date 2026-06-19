## Wave 2-A — 부정·리스크 뉴스 수집 및 노출

### 목표
- 종목 뉴스 수집이 긍정/호재 편향으로 기울지 않도록 부정·리스크 키워드 쿼리를 병행 수집한다.
- Gemini 선별 프롬프트가 부정 뉴스도 중요하게 다루도록 명시한다.
- 뉴스 탭에서 전체/긍정/중립/부정 필터와 배지 색상 구분을 제공한다.

### 범위
- `src/ingest_news.py`
- `src/enrich_gemini.py`
- `src/export_dashboard_data.py`
- `dashboard-web/src/tabsA.jsx`
- 관련 테스트

### 구현 메모
1. 수집
- KR: `{종목명} 리스크`, `{종목명} 하락`, `{종목명} 우려`
- US: `{ticker} risk`, `{ticker} decline`, `{ticker} concern`
- 기존 dedupe(url_hash)와 종목당 캡 유지

2. Gemini 선별
- STEP A 프롬프트에 부정·리스크 뉴스 중요도 상향 명시
- 긍정 편향 표현 제거

3. UI
- 감성 필터: 전체/긍정/중립/부정
- 배지 색상: 긍정=초록, 중립=회색, 부정=빨강

### 검증
- ingest unit test: 리스크 쿼리 확장 포함
- Gemini prompt/unit test: 부정 뉴스 중요도 문구 포함
- frontend test: 중립 필터와 정렬 동작 확인
