from __future__ import annotations

from decimal import Decimal


def test_portfolio_snapshot_payload_converts_numeric_and_includes_cash() -> None:
    from src.local_api import _portfolio_snapshot_payload

    result = _portfolio_snapshot_payload({
        "total_value": Decimal("100"),
        "total_cost": Decimal("80"),
        "total_pnl": Decimal("20"),
        "payload": {
            "pnl_pct": Decimal("25"),
            "cash_total": Decimal("30"),
            "asset_total": Decimal("130"),
            "fx_rate": Decimal("1400"),
        },
    })

    assert result["total_eval"] == 100.0
    assert result["cash_total"] == 30.0
    assert result["asset_total"] == 130.0
    assert result["fx_rate"] == 1400.0
