-- 신규-G 후속: 급등·급락 귀인에 '뉴스 있음(요약 대기)' 분류 추가.
-- Gemini 요약 실패 시에도 원문 뉴스가 있으면 '이유 불명'이 아니라 '요약 대기'로 구분(요약≠수집).
ALTER TABLE move_anomalies DROP CONSTRAINT IF EXISTS move_anomalies_attribution_class_check;
ALTER TABLE move_anomalies ADD CONSTRAINT move_anomalies_attribution_class_check
    CHECK (attribution_class IN ('가치이벤트', '정보·펀더멘털', '정서·수급', '뉴스 있음(요약 대기)', '이유 불명'));
