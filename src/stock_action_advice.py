from __future__ import annotations

from typing import Optional


BAND_RANGES = {
    "exit": (0.0, 1.0),
    "starter": (0.0, 3.0),
    "build": (3.0, 6.0),
    "core": (6.0, 10.0),
}


def compute_current_weight(eval_amount: float | None, asset_total: float | None) -> float:
    if not eval_amount or not asset_total:
        return 0.0
    return round(float(eval_amount) / float(asset_total) * 100, 2)


def _consensus_gap(consensus: dict | None, price: float | None) -> float | None:
    if not consensus or consensus.get("targetPrice") is None or price in (None, 0):
        return None
    return float(consensus["targetPrice"]) / float(price) - 1.0


def allocation_band_to_range(band: str, *, regime: str) -> tuple[float, float]:
    low, high = BAND_RANGES[band]
    if regime == "bear" and band == "core":
        return (3.0, 6.0)
    return (low, min(high, 10.0))


def derive_allocation_band(
    *,
    is_holding: bool,
    signal_label: str | None,
    regime: str,
    confidence: str,
    consensus_gap: float | None,
) -> str:
    if signal_label == "축소":
        return "exit" if is_holding and regime == "bear" else "starter"
    if signal_label == "관망":
        return "starter" if not is_holding else "build"
    if signal_label == "매수":
        if not is_holding:
            if confidence == "상" and (consensus_gap or 0) >= 0.1:
                return "build"
            return "starter"
        if regime == "bull" and confidence == "상":
            return "core"
        return "build"
    return "starter"


def derive_weight_action(current_weight: float, low: float, high: float) -> str:
    if current_weight < low:
        return "늘림"
    if current_weight > high:
        return "줄임"
    return "유지"


def derive_entry_exit_zones(stock: dict) -> tuple[str | None, str | None, list[dict]]:
    reasons: list[dict] = []
    entry_zone = None
    exit_zone = None
    sma50 = stock.get("sma50")
    sma20 = stock.get("sma20")
    consensus = stock.get("consensus") or {}
    price = stock.get("price")

    if sma50:
        entry_zone = "SMA60 부근 재확인 시"
        reasons.append({"source": "기술", "value": "SMA60/중기 추세선"})
    if consensus.get("targetPrice") is not None and price:
        gap = _consensus_gap(consensus, price)
        if gap is not None and gap > 0.05:
            exit_zone = "목표가 근접 시"
            reasons.append({"source": "컨센서스", "value": "목표가 대비 괴리"})
    elif sma20:
        exit_zone = "SMA20 이탈 시"
        reasons.append({"source": "기술", "value": "SMA20/단기 추세선"})

    return entry_zone, exit_zone, reasons


def derive_confidence_and_factors(stock: dict, regime: str) -> tuple[str, list[dict], list[dict], str | None]:
    supporting: list[dict] = []
    opposing: list[dict] = []

    signal = stock.get("signal") or {}
    if signal.get("label") == "매수":
        supporting.append({"source": "퀀트신호", "value": "매수"})
    elif signal.get("label") == "축소":
        opposing.append({"source": "퀀트신호", "value": "축소"})

    consensus = stock.get("consensus") or {}
    gap = _consensus_gap(consensus, stock.get("price"))
    if gap is not None:
        if gap >= 0.1:
            supporting.append({"source": "컨센서스", "value": f"{round(gap * 100, 1)}% 괴리"})
        elif gap < 0:
            opposing.append({"source": "컨센서스", "value": f"{round(gap * 100, 1)}% 괴리"})

    analyst_views = stock.get("analystViews") or {}
    if len(analyst_views.get("bull") or []) > len(analyst_views.get("bear") or []):
        supporting.append({"source": "뉴스심리", "value": "강세 논거 우세"})
    elif len(analyst_views.get("bear") or []) > len(analyst_views.get("bull") or []):
        opposing.append({"source": "뉴스심리", "value": "약세 논거 우세"})

    if regime == "bull":
        supporting.append({"source": "매크로", "value": "bull 국면"})
    elif regime == "bear":
        opposing.append({"source": "매크로", "value": "bear 국면"})

    divergence = None
    if supporting and opposing:
        confidence = "중"
        divergence = "지지 재료와 반대 재료가 함께 있어 변동성 구간으로 해석"
    elif len(supporting) >= 2:
        confidence = "상"
    else:
        confidence = "하"
    return confidence, supporting, opposing, divergence


def build_action_frame(stock: dict, portfolio_snapshot: dict, regime: str) -> dict:
    current_weight = compute_current_weight(
        (stock.get("holding") or {}).get("eval_amount"),
        portfolio_snapshot.get("asset_total"),
    )
    confidence, supporting, opposing, divergence = derive_confidence_and_factors(stock, regime)
    gap = _consensus_gap(stock.get("consensus"), stock.get("price"))
    band = derive_allocation_band(
        is_holding=bool(stock.get("holding")),
        signal_label=(stock.get("signal") or {}).get("label"),
        regime=regime,
        confidence=confidence,
        consensus_gap=gap,
    )
    low, high = allocation_band_to_range(band, regime=regime)
    weight_action = derive_weight_action(current_weight, low, high)
    entry_zone, exit_zone, zone_reasons = derive_entry_exit_zones(stock)
    supporting = supporting + zone_reasons

    signal_label = (stock.get("signal") or {}).get("label")
    direction = "유지"
    if not stock.get("holding"):
        direction = "매수" if signal_label == "매수" else "유지"
    elif signal_label == "매수":
        direction = "비중확대" if weight_action == "늘림" else "유지"
    elif signal_label == "축소":
        direction = "매도" if high <= 1.0 else "비중축소"

    return {
        "ticker": stock.get("t"),
        "direction": direction,
        "current_weight": current_weight,
        "target_weight_low": low,
        "target_weight_high": high,
        "weight_action": weight_action,
        "entry_zone": entry_zone,
        "exit_zone": exit_zone,
        "confidence": confidence,
        "supporting_factors": supporting,
        "opposing_factors": opposing,
        "divergence_note": divergence,
        "consensus_gap": gap,
        "allocation_band": band,
    }
