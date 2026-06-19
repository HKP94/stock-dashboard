"""
rules.py — 룰 기반 알림 플래그 엔진 (PRD §F6-1)

이 모듈의 출력은 결정론적 플래그이며 자동 주문을 실행하지 않습니다.

설계 원칙:
  - LLM 호출 없음, 네트워크 없음 — 순수 Python 계산
  - 해당 없거나 데이터 없으면 빈 리스트 반환
  - 각 룰은 독립 함수 (_check_*) → 테스트 단위 격리 용이

공개 API:
  check_rules(ticker, indicators, quant, analyst) → list[str]

indicators dict 예상 키:
  rsi14, sma50, sma200, slope50, is_aligned, disparity20,
  close, chg_pct

analyst dict 예상 키:
  target_price, upside (소수점 비율 — 예: 0.19 = 19%)

quant dict: 현재 8개 룰에서 미사용, 향후 확장용
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── 임계값 상수 (CLAUDE.md §3: 하드코딩 금지 → 상수로 추출) ─────
RSI_OVERHEAT: float = 70.0          # RSI 과열 기준
RSI_OVERSOLD: float = 30.0          # RSI 침체 기준
SURGE_PCT: float = 7.0              # 급등 기준 (%)
PLUNGE_PCT: float = -7.0            # 급락 기준 (%)
DISPARITY_OVERHEAT: float = 115.0   # 이격도 과열 기준
TARGET_PROXIMITY: float = 0.95      # 목표가 근접 기준 (현재가 / 목표가)
GOLDEN_CROSS_PROXIMITY: float = 0.98  # 골든크로스 임박: SMA50 ≥ SMA200 × 이 값


# ──────────────────────────────────────────────────────────────
# 개별 룰 함수 (None = 해당 없음 또는 데이터 없음)
# ──────────────────────────────────────────────────────────────

def _check_rsi_overheat(ind: dict) -> Optional[str]:
    """룰 1: RSI 과열 — RSI14 > 70"""
    rsi = ind.get("rsi14")
    if rsi is None:
        return None
    if rsi > RSI_OVERHEAT:
        return f"RSI 과열 ({rsi:.1f})"
    return None


def _check_rsi_oversold(ind: dict) -> Optional[str]:
    """룰 2: RSI 침체 — RSI14 < 30"""
    rsi = ind.get("rsi14")
    if rsi is None:
        return None
    if rsi < RSI_OVERSOLD:
        return f"RSI 침체 ({rsi:.1f})"
    return None


def _check_dead_cross(ind: dict) -> Optional[str]:
    """룰 3: 데드크로스 임박 — 정배열 False + slope50 < 0"""
    is_aligned = ind.get("is_aligned")
    slope50 = ind.get("slope50")
    if is_aligned is None or slope50 is None:
        return None
    if not is_aligned and slope50 < 0:
        return "데드크로스 임박"
    return None


def _check_golden_cross(ind: dict) -> Optional[str]:
    """룰 4: 골든크로스 임박 — 정배열 False + slope50 > 0 + SMA50 ≥ SMA200 × 98%"""
    is_aligned = ind.get("is_aligned")
    slope50 = ind.get("slope50")
    sma50 = ind.get("sma50")
    sma200 = ind.get("sma200")
    if any(v is None for v in [is_aligned, slope50, sma50, sma200]):
        return None
    if sma200 <= 0:
        return None
    if not is_aligned and slope50 > 0 and sma50 >= sma200 * GOLDEN_CROSS_PROXIMITY:
        return "골든크로스 임박"
    return None


def _check_target_proximity(ind: dict, ana: dict) -> Optional[str]:
    """룰 5: 목표가 근접 — 현재가 ≥ 목표가 × 95%"""
    close = ind.get("close")
    target = ana.get("target_price")
    if close is None or target is None or target <= 0:
        return None
    if close >= target * TARGET_PROXIMITY:
        # 남은 상승여력 = (목표가/현재가 - 1) × 100
        remaining_pct = (target / close - 1) * 100
        return f"목표가 근접 ({remaining_pct:.1f}%)"
    return None


def _check_surge(ind: dict) -> Optional[str]:
    """룰 6: 급등 — 전일 대비 +7% 이상"""
    chg = ind.get("chg_pct")
    if chg is None:
        return None
    if chg >= SURGE_PCT:
        return f"급등 (+{chg:.1f}%)"
    return None


def _check_plunge(ind: dict) -> Optional[str]:
    """룰 7: 급락 — 전일 대비 -7% 이하"""
    chg = ind.get("chg_pct")
    if chg is None:
        return None
    if chg <= PLUNGE_PCT:
        return f"급락 ({chg:.1f}%)"
    return None


def _check_disparity_overheat(ind: dict) -> Optional[str]:
    """룰 8: 이격도 과열 — disparity20 > 115"""
    disp = ind.get("disparity20")
    if disp is None:
        return None
    if disp > DISPARITY_OVERHEAT:
        return f"이격도 과열 ({disp:.1f})"
    return None


# ──────────────────────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────────────────────

def check_rules(
    ticker: str,
    indicators: dict,
    quant: dict,
    analyst: dict,
) -> list[str]:
    """
    종목 플래그 계산.

    반환된 플래그는 자동 주문을 실행하지 않습니다.
    투자 판단과 그 결과의 책임은 전적으로 사용자에게 있습니다.

    Parameters
    ----------
    ticker     : 종목 코드 (로깅용)
    indicators : 기술적 지표 dict — rsi14, sma50, sma200, slope50,
                 is_aligned, disparity20, close, chg_pct
    quant      : 퀀트 점수 dict (향후 룰 확장용, 현재 미사용)
    analyst    : 애널리스트 컨센서스 dict — target_price, upside

    Returns
    -------
    list[str]  해당 플래그 목록. 없으면 빈 리스트.
    """
    # quant는 현재 8개 룰에서 사용하지 않지만 시그니처에 유지
    _ = quant

    checkers = [
        _check_rsi_overheat(indicators),
        _check_rsi_oversold(indicators),
        _check_dead_cross(indicators),
        _check_golden_cross(indicators),
        _check_target_proximity(indicators, analyst),
        _check_surge(indicators),
        _check_plunge(indicators),
        _check_disparity_overheat(indicators),
    ]

    flags = [f for f in checkers if f is not None]
    if flags:
        logger.info("%s: flags = %s", ticker, flags)
    return flags
