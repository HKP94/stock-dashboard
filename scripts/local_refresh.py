"""로컬 보조 수집 — KRX investor_flow 수집 + data.json export. launchd가 하루 2회 호출.

CI(GitHub Actions)가 못 하는 것만 로컬(맥, 한국 IP)에서 한다:
  1) investor_flow: KRX가 CI IP를 차단하므로 로컬에서만 수집(기존 run_investor_flow_ingest 재사용).
  2) export: DB→data.json 갱신(아침 CI 완료 후 재생성해 US T-1 스테일 해소).

설계: CI 파이프라인과 완전 분리 — 여기가 실패해도 CI 무관. 재시도/데몬화 없음
(네트워크 실패 시 그냥 실패-종료, 다음 스케줄이 백필로 자가치유). 로그·상태파일로
신선도 감시 훅을 남긴다.
"""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# 스크립트 모드 실행 시 리포 루트를 path에 추가 (src 패키지 인식)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

LOG_DIR = Path.home() / "atlas_logs"
STATE_FILE = LOG_DIR / "local_refresh_state.json"

logger = logging.getLogger("local_refresh")


def _setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logfile = LOG_DIR / f"local_refresh_{datetime.now():%Y%m%d}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(logfile, encoding="utf-8"), logging.StreamHandler()],
    )


def _write_state(ok: bool, rows: int, error: str | None = None) -> None:
    """마지막 실행 상태 기록(신선도 감시가 읽을 훅). 성공 시각은 ok=True일 때만 갱신."""
    now = datetime.now(timezone.utc).isoformat()
    state: dict = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except Exception:
            state = {}
    state["last_run_utc"] = now
    state["last_ok"] = ok
    state["last_investor_flow_rows"] = rows
    state["last_error"] = error
    if ok:
        state["last_success_utc"] = now
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def main() -> int:
    load_dotenv()
    _setup_logging()
    logger.info("=== local_refresh 시작 ===")

    from src import export_dashboard_data
    from src.db import get_conn
    from src.ingest_investor_flow import run_investor_flow_ingest
    from src.pipeline_common import active_universe, split_kr_us

    rows = 0
    try:
        # 1) KRX investor_flow (로컬 전용)
        with get_conn() as conn:
            watchlist = active_universe(conn)
            kr_tickers, _us, _all = split_kr_us(watchlist)
            logger.info("investor_flow 수집: KR %d종목", len(kr_tickers))
            result = run_investor_flow_ingest(conn, kr_tickers)
            rows = result["counts"]["rows"]
            n_err = len(result["errors"])
            logger.info("investor_flow: %d행 저장, 실패 %d건", rows, n_err)

        # 2) DB → data.json export (CI 완료 후 최신 반영)
        logger.info("export: data.json 갱신")
        export_dashboard_data.main()

        _write_state(ok=True, rows=rows)
        logger.info("=== local_refresh 완료 (investor_flow %d행) ===", rows)
        return 0
    except Exception as exc:
        logger.error("local_refresh 실패: %s", exc, exc_info=True)
        _write_state(ok=False, rows=rows, error=str(exc)[:200])
        return 1


if __name__ == "__main__":
    sys.exit(main())
