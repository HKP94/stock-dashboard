-- s1: 레거시 티커 표기 정정 (레이블 rename — 데이터 이동 없음)
-- 설계: docs/design/2026-08-08-legacy-ticker-correction.md (PM 승인 2026-08-08)
--
-- ★왜 '제거+추가'(CLAUDE.md 관례)가 아니라 UPDATE인가
--   관례는 '오타 티커로 쌓인 잘못된 데이터'를 상정한다. 여기서는 데이터와 종목의 대응이
--   처음부터 옳았고 **표기(접미사)만** 틀렸다. 제거+추가하면 11,048행 이력이 소실된다.
--   전제: 대상 6티커의 데이터 정합을 사전 확인했고(전 테이블 행수 스냅샷 + 백업),
--   ticker 기반 FK 0개·PK/UNIQUE 실제 충돌 0건을 실측했다.
--
-- 멱등성: WHERE 조건이 이미 정정된 경우 0행 UPDATE로 만든다(재실행 안전).
-- 충돌 시 동작: UNIQUE 위반으로 트랜잭션 전체 롤백 — 조용한 부분 적용보다 크게 실패한다.
-- 동적 SQL(information_schema 순회)을 쓰지 않는다 — 스키마가 늘 때 리뷰 없이 새 테이블을
-- 건드리는 것보다, 명시 목록이 검토 가능하고 의도가 드러난다.
--
-- 정정 근거: KB SIQM4900.is_dtl_typ_cd (11=상장주식 .KS / 12=코스닥주식 .KQ / 10=코넥스)


-- 미코: 059090.KS → 059090.KQ
UPDATE analyst SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE analyst_views SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE discovery_screen SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE earnings_calendar SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE fundamentals SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE indicators_daily SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE investor_flow SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE judgment_notes SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE manual_research_entries SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE move_anomalies SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE news_analysis SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE news_raw SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE portfolio SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE portfolio_holdings SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE prices_daily SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE quant_scores SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE research_items SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE signal_grade_track SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE stock_action_advice SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE stock_note_history SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE stock_notes SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE ticker_context SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE ticker_drivers SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE valuation SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE valuation_xcheck SET ticker = '059090.KQ' WHERE ticker = '059090.KS';
UPDATE watchlist SET ticker = '059090.KQ' WHERE ticker = '059090.KS';

-- 한양디지텍: 078350.KS → 078350.KQ
UPDATE analyst SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE analyst_views SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE discovery_screen SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE earnings_calendar SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE fundamentals SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE indicators_daily SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE investor_flow SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE judgment_notes SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE manual_research_entries SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE move_anomalies SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE news_analysis SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE news_raw SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE portfolio SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE portfolio_holdings SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE prices_daily SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE quant_scores SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE research_items SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE signal_grade_track SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE stock_action_advice SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE stock_note_history SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE stock_notes SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE ticker_context SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE ticker_drivers SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE valuation SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE valuation_xcheck SET ticker = '078350.KQ' WHERE ticker = '078350.KS';
UPDATE watchlist SET ticker = '078350.KQ' WHERE ticker = '078350.KS';

-- 덕산네오룩스: 213420.KS → 213420.KQ
UPDATE analyst SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE analyst_views SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE discovery_screen SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE earnings_calendar SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE fundamentals SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE indicators_daily SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE investor_flow SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE judgment_notes SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE manual_research_entries SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE move_anomalies SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE news_analysis SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE news_raw SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE portfolio SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE portfolio_holdings SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE prices_daily SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE quant_scores SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE research_items SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE signal_grade_track SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE stock_action_advice SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE stock_note_history SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE stock_notes SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE ticker_context SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE ticker_drivers SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE valuation SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE valuation_xcheck SET ticker = '213420.KQ' WHERE ticker = '213420.KS';
UPDATE watchlist SET ticker = '213420.KQ' WHERE ticker = '213420.KS';

-- 뷰노: 338220.KS → 338220.KQ
UPDATE analyst SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE analyst_views SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE discovery_screen SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE earnings_calendar SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE fundamentals SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE indicators_daily SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE investor_flow SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE judgment_notes SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE manual_research_entries SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE move_anomalies SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE news_analysis SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE news_raw SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE portfolio SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE portfolio_holdings SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE prices_daily SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE quant_scores SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE research_items SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE signal_grade_track SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE stock_action_advice SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE stock_note_history SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE stock_notes SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE ticker_context SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE ticker_drivers SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE valuation SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE valuation_xcheck SET ticker = '338220.KQ' WHERE ticker = '338220.KS';
UPDATE watchlist SET ticker = '338220.KQ' WHERE ticker = '338220.KS';

-- APR: 278470.KR → 278470.KS
UPDATE analyst SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE analyst_views SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE discovery_screen SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE earnings_calendar SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE fundamentals SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE indicators_daily SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE investor_flow SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE judgment_notes SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE manual_research_entries SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE move_anomalies SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE news_analysis SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE news_raw SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE portfolio SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE portfolio_holdings SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE prices_daily SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE quant_scores SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE research_items SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE signal_grade_track SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE stock_action_advice SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE stock_note_history SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE stock_notes SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE ticker_context SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE ticker_drivers SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE valuation SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE valuation_xcheck SET ticker = '278470.KS' WHERE ticker = '278470.KR';
UPDATE watchlist SET ticker = '278470.KS' WHERE ticker = '278470.KR';

-- 엔솔바이오사이언스(140610)는 **코넥스**라 .KS·.KQ 어느 쪽도 아니다 → rename하지 않는다.
-- 코넥스는 투자자별 수급·컨센서스 공시가 부재해 영구 결측이므로 관찰 대상에서 내린다.
-- 데이터는 보존(삭제 아님) — export가 active만 조회하므로 화면에서 자연 소멸한다.
UPDATE watchlist SET active = FALSE WHERE ticker = '140610.KS' AND active;
