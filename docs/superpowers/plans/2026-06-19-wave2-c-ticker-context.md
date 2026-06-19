## Wave 2-C — 정보 영속화 / 지식 베이스

### 목표
- 종목 뉴스 요약을 당일성 출력으로 끝내지 않고 `ticker_context`에 누적 저장한다.
- 오래된 항목은 삭제하지 않고 `valid_until` 기준으로 만료 처리한다.
- 종목상세 하단에 최근 30일 누적 인사이트를 날짜순으로 노출한다.

### 구현 방향
1. DB/스키마
- `ticker_context`
- `(ticker, context_type, valid_from)` 인덱스

2. 저장 로직
- `enrich_news_batch`에서 `context_type='news_summary'`로 저장
- 같은 ticker/source/date/context_type는 교체 저장
- `valid_from=오늘`, `valid_until=NULL`

3. 조회 로직
- export가 최근 30일 + 만료되지 않은 항목만 싣기
- `context_type` 필터 값도 같이 제공

4. UI
- 종목상세 하단 "누적 인사이트"
- context_type 필터 + 날짜순 표시

### 검증
- ticker_context 저장/교체 테스트
- export 조회 테스트
- 종목상세 렌더 회귀
