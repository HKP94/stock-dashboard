-- 신규-G: 급등·급락 감지 + 뉴스 귀인 (관찰 레이어)
-- 결정론 감지(변동성조정 z + 지수대비 excess) + 귀인/분류 결과를 종목·일 단위로 저장.
-- §F7 오늘 스냅샷(소급 백필 없음), 파이프라인만 씀(자동수집 무결성).
CREATE TABLE IF NOT EXISTS move_anomalies (
    ticker            TEXT    NOT NULL,
    asof              DATE    NOT NULL,          -- 움직임이 일어난 거래일(종목별 최신, §8)
    ret_pct           NUMERIC,                   -- 일간 수익률 (%)
    z_score           NUMERIC,                   -- ret / 종목 트레일링 60일 일간수익률 σ
    excess_pct        NUMERIC,                   -- r − β·r_index (%), 지수대비 초과
    direction         TEXT    CHECK (direction IN ('급등', '급락')),
    idiosyncratic     BOOLEAN,                   -- true=자체 이동(귀인 필요), false=지수 동반
    attribution_class TEXT    CHECK (attribution_class IN ('가치이벤트', '정보·펀더멘털', '정서·수급', '이유 불명')),
    explained         BOOLEAN,                   -- 설명 뉴스/수급 포착 여부
    reason            TEXT,                       -- 결정론 서술(관찰, 매매 지시 금지)
    sources           JSONB   NOT NULL DEFAULT '[]',  -- [{type,title,url,...}] 귀인 근거
    PRIMARY KEY (ticker, asof)
);

CREATE INDEX IF NOT EXISTS move_anomalies_asof ON move_anomalies (asof DESC);
