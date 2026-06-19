## Wave 2-B — 시장 뉴스·리포트 채널 다변화

### 목표
- 종목 뉴스와 별도로 시장 전체 헤드라인을 수집해 시황/전망 근거를 따로 저장한다.
- `market_news` 원천 테이블과 `market_news_summary` 요약 테이블을 추가한다.
- 시장전망 탭에 `kr_summary / us_summary / global_summary` 카드 섹션을 노출한다.

### 구현 방향
1. 새 수집 모듈 `src/ingest_market_news.py`
- MarketWatch RSS
- Hankyung RSS
- Maeil Business RSS(file.mk 경로)
- Google News RSS 시장 쿼리
- FRED API 보조(키 있을 때만)

2. DB/스키마
- `market_news`
- `market_news_summary`
- url_hash SHA256 dedupe 유지

3. Gemini 요약
- Gemini 2.5 Flash 1회 호출
- 출력: `kr_summary`, `us_summary`, `global_summary`

4. 파이프라인 연결
- `run_pipeline`, `news_refresh`에 시장 뉴스 수집 + 요약 추가
- 단계별 commit/rollback 유지

5. UI/export
- export가 최신 `market_news_summary`를 싣고
- 시장전망 탭에 카드 3개 노출

### 검증
- 시장 뉴스 수집 단위 테스트
- 요약 프롬프트/파서 테스트
- export/UI 회귀 테스트
