"""
백필 종목 단위 격리 회귀 가드 (정리 라운드 S1 후속).

■ 왜 이 파일이 생겼나
`feat/backfill-prices` 브랜치에 테스트 12개가 있었는데 main에는 없다는 사실이 트랙
재고조사에서 드러났다. 그런데 복원해 보니 **그 12개는 복원할 수 없다** — 세 대상 함수
(`_is_kr`·`backfill_prices`·`recompute_indicators`)가 전부 사라졌고 모듈이 재설계됐다.
재판정 결과:
  - KR/US 라우팅·5년 창 → `tests/test_benchmark_backfill.py`가 이미 커버(이름이 달라 못 찾았던 것)
  - 지표·퀀트 재계산 배선 → 같은 파일이 커버
  - 접미사 폴백 → **설계상 제거**(이제 `market`을 호출부가 넘긴다) — 위험 자체가 없다
  - ★**종목 단위 격리** → 미커버. 기존 테스트는 1종목 happy path만 본다.

CLAUDE.md §0은 "부분 실패 격리 — 한 종목/소스 실패가 전체 실행을 멈추면 안 되고 실패는
`runs.errors`에 기록"을 절대 규칙으로 둔다. 그 규칙이 무방비였으므로 여기서만 좁게 닫는다.
프로덕션 코드는 건드리지 않았다(테스트 전용).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src import backfill as bf


def _conn() -> MagicMock:
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    return conn


def _gap(ticker: str, market: str = "US") -> dict:
    return {"ticker": ticker, "market": market, "name": ticker,
            "reason": "가격 부족", "rows": 0, "last_date": None}


def test_one_ticker_failure_does_not_stop_the_rest():
    """★핵심: 한 종목이 예외를 던져도 나머지 종목의 백필은 계속돼야 한다(§0 부분 실패 격리)."""
    conn = _conn()
    gaps = [_gap("BAD"), _gap("GOOD1"), _gap("GOOD2")]
    rows = [MagicMock()]

    def flaky(ticker, market, years=2):
        if ticker == "BAD":
            raise RuntimeError("소스 장애")
        return rows

    with patch("src.backfill.get_conn", return_value=conn), \
         patch("src.backfill.log_run_start", return_value=1), \
         patch("src.backfill.log_run_finish"), \
         patch("src.backfill.detect_gap_tickers", return_value=gaps), \
         patch("src.backfill._backfill_one", side_effect=flaky), \
         patch("src.backfill.upsert_price_daily") as upsert_prices, \
         patch("src.backfill.compute_quant_universe", return_value=[]), \
         patch("src.backfill.upsert_quant_scores"), \
         patch("src.backfill.recompute_indicators_to_db", return_value=2):
        result = bf.run_backfill()

    # 실패한 1종목을 빼고 나머지 2종목이 백필돼야 한다
    assert result["backfilled"] == 2, result
    assert upsert_prices.call_count == 2
    # 실패는 삼키지 말고 기록
    assert any(e.get("ticker") == "BAD" for e in result["errors"]), result["errors"]
    conn.rollback.assert_called()


def test_failed_ticker_excluded_from_indicator_recompute():
    """실패 종목은 '영향 종목'에 들어가면 안 된다 — 없는 데이터로 지표를 돌리지 않게."""
    conn = _conn()
    gaps = [_gap("BAD"), _gap("GOOD")]

    def flaky(ticker, market, years=2):
        if ticker == "BAD":
            raise RuntimeError("소스 장애")
        return [MagicMock()]

    with patch("src.backfill.get_conn", return_value=conn), \
         patch("src.backfill.log_run_start", return_value=1), \
         patch("src.backfill.log_run_finish"), \
         patch("src.backfill.detect_gap_tickers", return_value=gaps), \
         patch("src.backfill._backfill_one", side_effect=flaky), \
         patch("src.backfill.upsert_price_daily"), \
         patch("src.backfill.compute_quant_universe", return_value=[]), \
         patch("src.backfill.upsert_quant_scores"), \
         patch("src.backfill.recompute_indicators_to_db", return_value=1) as recompute:
        bf.run_backfill()

    recompute.assert_called_once_with(conn, ["GOOD"])


def test_zero_rows_not_upserted_and_recorded_as_error():
    """수집 0행은 upsert하지 않고 오류로 남긴다 — 조용한 빈 백필 금지."""
    conn = _conn()

    with patch("src.backfill.get_conn", return_value=conn), \
         patch("src.backfill.log_run_start", return_value=1), \
         patch("src.backfill.log_run_finish"), \
         patch("src.backfill.detect_gap_tickers", return_value=[_gap("EMPTY")]), \
         patch("src.backfill._backfill_one", return_value=[]), \
         patch("src.backfill.upsert_price_daily") as upsert_prices, \
         patch("src.backfill.compute_quant_universe", return_value=[]), \
         patch("src.backfill.upsert_quant_scores"), \
         patch("src.backfill.recompute_indicators_to_db", return_value=0) as recompute:
        result = bf.run_backfill()

    upsert_prices.assert_not_called()
    recompute.assert_not_called()          # 영향 종목 없음 → 재계산도 없음
    assert result["backfilled"] == 0
    assert any(e.get("error") == "0 rows" for e in result["errors"]), result["errors"]


def test_check_only_does_not_write():
    """check_only는 탐지만 — 어떤 쓰기도 하지 않는다."""
    conn = _conn()

    with patch("src.backfill.get_conn", return_value=conn), \
         patch("src.backfill.log_run_start", return_value=1), \
         patch("src.backfill.log_run_finish"), \
         patch("src.backfill.detect_gap_tickers", return_value=[_gap("AAPL")]), \
         patch("src.backfill._backfill_one") as one, \
         patch("src.backfill.upsert_price_daily") as upsert_prices:
        result = bf.run_backfill(check_only=True)

    one.assert_not_called()
    upsert_prices.assert_not_called()
    assert result["check_only"] is True and result["backfilled"] == 0


def test_backfill_single_isolates_indicator_failure():
    """backfill_single: 지표 실패가 가격 적재 성과를 무효화하지 않는다(단계별 격리)."""
    conn = _conn()

    with patch("src.backfill._load_secrets_if_needed"), \
         patch("src.backfill.get_conn", return_value=conn), \
         patch("src.backfill._backfill_one", return_value=[MagicMock(), MagicMock()]), \
         patch("src.backfill.upsert_price_daily"), \
         patch("src.compute_indicators.recompute_indicators_to_db", side_effect=RuntimeError("지표 장애")), \
         patch("src.compute_quant.compute_quant_universe", return_value=[]):
        result = bf.backfill_single("AAPL", "US")

    assert result["prices"] == 2
    assert result["indicators"] == 0
    assert result["ok"] is True     # 가격이 들어갔으면 성공으로 본다
