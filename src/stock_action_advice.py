from __future__ import annotations

from typing import Optional


BAND_RANGES = {
    "exit": (0.0, 1.0),
    "starter": (0.0, 3.0),
    "build": (3.0, 6.0),
    "core": (6.0, 10.0),
}

# ──────────────────────────────────────────────────────────────
# 신규-D: 보유성격(장기보유/모멘텀/단기) + 집중 리스크 관찰
#   - 비중 권고(target_weight/weight_action)는 계산·저장은 유지하되 종목 카드 표시에서만 제외.
#   - 보유성격은 기존 재료(수동분해·퀀트·정배열·안전마진·RSI·뉴스이벤트)로 결정론 분류. LLM은 해설만.
#   - 집중 리스크는 "관찰"(사실+영향)만. 가치판단/지시어 금지.
# 임계값(설계 §9 — 스모크 분포 보고 후 보정 대상). config 추출 가능.
# ──────────────────────────────────────────────────────────────
HOLD_CHARACTERS = ("장기보유", "모멘텀", "단기", "정보부족")
LONG_SAFETY_FLOOR = 65.0
QUALITY_FLOOR = 60.0
MOM_FLOOR = 60.0
SLOPE_FLOOR = 0.0
RSI_OVERHEAT = 70.0
RSI_OVERSOLD = 30.0
CONCENTRATION_OBSERVE_PCT = 15.0   # 관찰 노트 발화 트리거(비중 상한·강제 아님)

# ──────────────────────────────────────────────────────────────
# 신규-A2: 매력도 3축 종합 등급 (매수/관망/축소)
#   - 등급은 축 방향(강/중/약)의 "정렬 패턴"에서 결정론 규칙으로 도출 — 값 합산 아님.
#   - 임계는 기존 AxesCard._level과 동일(퀀트 60/40·컨센서스 20/5·별점 4/2).
#   - 시장점수(5-B)·베타(A1)는 퀀트 축 경로로만 작용(비대칭: 하방 민감·상방 신중).
# ──────────────────────────────────────────────────────────────
GRADES = ("매수", "관망", "축소")
GRADE_QUANT_STRONG = 60.0
GRADE_QUANT_WEAK = 40.0
GRADE_CONS_STRONG = 20.0
GRADE_CONS_WEAK = 5.0
GRADE_MY_STRONG = 4.0
GRADE_MY_WEAK = 2.0
GRADE_BETA_HIGH = 1.2   # 시장·베타 보정 트리거(고베타)

# 집중 리스크 관찰 금지어 — 지시·가치판단 배제(사실+영향만 허용).
# 평가형용사(부담/과도/적정/권장/바람직 등)와 지시동사(줄이/축소/매도 등)를 모두 차단한다.
CONCENTRATION_BANNED_WORDS = (
    "줄이", "줄여", "축소", "매도", "낮추", "덜어",
    "과도", "과하", "지나치", "부담", "위험한", "위험하니",
    "적정", "권장", "권고", "바람직", "추천", "초과", "비중을 조정",
)


def _num(val) -> Optional[float]:
    """DB NUMERIC/문자열 혼입 방어 — 읽기 경계 float 변환."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def is_observation_clean(text: Optional[str]) -> bool:
    """집중 리스크 노트가 관찰 톤(사실+영향)인지 — 금지어가 없으면 clean."""
    if not text:
        return True
    return not any(bad in text for bad in CONCENTRATION_BANNED_WORDS)


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


def _ai_decomposition_labels(stock: dict) -> dict:
    """수동 AI 분해(4-D-3) 단/중/장 매력도 라벨 {short|mid|long: 매력적|중립|비매력}."""
    summary = stock.get("aiDecompositionSummary") or {}
    return summary.get("labels") or {}


def derive_hold_character(stock: dict, regime: str) -> tuple[str, list[str], list[dict]]:
    """보유성격(장기보유/모멘텀/단기/정보부족)을 결정론 규칙으로 판정.

    우선순위(집중 투자 철학상 장기 우선): 장기보유 → 모멘텀 → 단기 → 정보부족.
    primary 1개 + secondary(동시 충족) 목록 + 근거(basis)를 반환. LLM은 이 라벨을 만들지 않는다.
    """
    labels = _ai_decomposition_labels(stock)
    factors = stock.get("f") or {}
    safety = _num(stock.get("safety"))
    fq = _num(factors.get("q"))
    fm = _num(factors.get("m"))
    align = bool(stock.get("align"))
    slope = _num(stock.get("slope"))
    rsi = _num(stock.get("rsi"))
    curated = stock.get("newsCuratedCount") or 0
    basis: list[dict] = []

    def is_long() -> bool:
        if labels.get("long") == "매력적":
            basis.append({"source": "수동분해(장기)", "value": "매력적", "effect": "장기보유"})
            return True
        if safety is not None and fq is not None and safety >= LONG_SAFETY_FLOOR and fq >= QUALITY_FLOOR:
            basis.append({"source": "안전마진", "value": str(round(safety)), "effect": "장기보유"})
            basis.append({"source": "퀄리티", "value": str(round(fq)), "effect": "장기보유"})
            return True
        return False

    def is_momentum() -> bool:
        if align and slope is not None and slope > SLOPE_FLOOR and fm is not None and fm >= MOM_FLOOR:
            basis.append({"source": "정배열·추세", "value": f"slope {round(slope, 1)}", "effect": "모멘텀"})
            basis.append({"source": "모멘텀팩터", "value": str(round(fm)), "effect": "모멘텀"})
            return True
        return False

    def is_short() -> bool:
        if labels.get("short") == "매력적":
            basis.append({"source": "수동분해(단기)", "value": "매력적", "effect": "단기"})
            return True
        if curated and curated > 0:
            basis.append({"source": "중요뉴스", "value": f"{curated}건", "effect": "단기 이벤트"})
            return True
        if rsi is not None and (rsi >= RSI_OVERHEAT or rsi <= RSI_OVERSOLD):
            basis.append({"source": "RSI", "value": str(round(rsi)), "effect": "단기 과열/침체"})
            return True
        return False

    matched = [name for name, fn in (("장기보유", is_long), ("모멘텀", is_momentum), ("단기", is_short)) if fn()]
    if not matched:
        return "정보부족", [], [{"source": "데이터", "value": "부족", "effect": "성격 판단 보류"}]
    return matched[0], matched[1:], basis


def _axis_level(value: Optional[float], strong: float, weak: float, *, weak_inclusive: bool = False) -> Optional[str]:
    """축 원시값 → 강/중/약. 결측은 None('축 없음', 0점 아님)."""
    v = _num(value)
    if v is None:
        return None
    if v >= strong:
        return "강"
    if (v <= weak) if weak_inclusive else (v < weak):
        return "약"
    return "중"


def derive_grade(stock: dict, *, market_direction: Optional[str] = None) -> tuple[str, str, dict]:
    """매력도 3축 정렬 패턴 → 등급(매수/관망/축소) + 신뢰도(상/중/하) + 근거(basis).

    합산이 아니라 축 '방향'(강/중/약)의 조합만 본다(방향 투표). 컴포지트·상승여력·별점
    숫자를 더하거나 평균하지 않는다. 시장·베타는 퀀트 축 경로로만, 비대칭으로 작용한다
    (시장 약세+고베타 → 보수화 가능 / 시장 강세 → 등급 끌어올리지 않음, 고점 매수 방지).
    """
    quant = _axis_level(stock.get("comp"), GRADE_QUANT_STRONG, GRADE_QUANT_WEAK)
    cons = _axis_level(stock.get("up"), GRADE_CONS_STRONG, GRADE_CONS_WEAK)
    my = _axis_level((stock.get("note") or {}).get("attractiveness"), GRADE_MY_STRONG, GRADE_MY_WEAK, weak_inclusive=True)

    # 시장·베타 보정(퀀트 축 경로로만, 하방 민감·상방 신중). 강세는 끌어올리지 않는다.
    beta = _num(stock.get("beta"))
    market_adjust = None
    if quant == "강" and market_direction == "약세" and beta is not None and beta >= GRADE_BETA_HIGH:
        market_adjust = {"applied": True, "axis": "quant", "from": "강", "to": "중",
                         "reason": f"시장 약세 · 베타 {round(beta, 2)} — 시장 역풍 시 낙폭 확대 가능(보수화)"}
        quant = "중"

    levels = {"quant": quant, "consensus": cons, "judgment": my}
    present = [lv for lv in levels.values() if lv is not None]
    strong = present.count("강")
    weak = present.count("약")
    npresent = len(present)

    divergence = None
    if npresent <= 1:
        grade, confidence = "관망", "하"   # 단일 축 — 근거 부족, 매수/축소 단정 금지
    elif strong >= 1 and weak >= 1:
        grade, confidence = "관망", "하"   # 축 충돌 → 확인 우선
        divergence = "축이 엇갈립니다 — 확인 필요"
    elif strong >= 2 and weak == 0:
        grade, confidence = "매수", ("상" if strong == npresent else "중")
    elif weak >= 2 and strong == 0:
        grade, confidence = "축소", ("상" if weak == npresent else "중")
    elif strong == 1 and weak == 0:
        grade, confidence = "관망", "중"   # 한 축만 강 → 약한 매수 만들지 않음(상방 신중)
    elif weak == 1 and strong == 0:
        grade, confidence = "축소", "중"   # 한 축만 약 → 하방 민감
    else:
        grade, confidence = "관망", "하"   # 전부 중립

    basis = {
        "axes": levels,
        "present": npresent,
        "strong": strong,
        "weak": weak,
        "marketAdjust": market_adjust,
        "divergence": divergence,
    }
    return grade, confidence, basis


_GRADE_AXIS_LABEL = {"quant": "퀀트", "consensus": "컨센서스", "judgment": "내 판단"}


def grade_fallback_rationale(frame: dict) -> str:
    """LLM 없음/폴백 시 등급 해설 — 결정론 템플릿(사실+근거, 매매 단정 없음)."""
    basis = frame.get("grade_basis") or {}
    axes = basis.get("axes") or {}
    parts = [f"{_GRADE_AXIS_LABEL[k]} {v}" for k, v in axes.items() if v]
    axis_str = " · ".join(parts) if parts else "축 데이터 부족"
    note = " 축이 엇갈려 확인이 필요합니다." if basis.get("divergence") else ""
    return (f"{frame.get('grade', '관망')} 등급(신뢰도 {frame.get('grade_confidence', '하')}) — "
            f"3축 정렬: {axis_str}.{note} 매매 단정이 아닌 관찰입니다.")


def derive_concentration_note(current_weight: Optional[float], *, beta: Optional[float] = None) -> Optional[str]:
    """집중 리스크 '관찰' 노트(결정론 템플릿). 사실+영향만 — 지시·가치판단 없음.

    비중이 트리거 미만이면 None. 베타는 신규-A 도입 후 채워지며, 없으면 비중만 서술한다.
    """
    cw = _num(current_weight)
    if cw is None or cw < CONCENTRATION_OBSERVE_PCT:
        return None
    parts = [f"현재 비중 {round(cw, 1)}%"]
    b = _num(beta)
    if b is not None:
        parts.append(f"베타 {round(b, 2)}")
    return " · ".join(parts) + " — 단일 종목 비중이 높아 시장 급락 시 포트폴리오 변동성에 크게 기여합니다. 판단은 본인 몫입니다."


def finalize_concentration_note(deterministic: Optional[str], polished: Optional[str], current_weight: Optional[float]) -> Optional[str]:
    """LLM이 어휘만 다듬은 노트를 가드 통과 시에만 채택, 아니면 결정론 노트 유지.

    가드: 금지어 없음 + 비중 수치 보존(새 숫자 창작 방지). 하나라도 어기면 결정론 노트로 폴백.
    """
    if not polished:
        return deterministic
    if not is_observation_clean(polished):
        return deterministic
    cw = _num(current_weight)
    if cw is not None and f"{round(cw, 1)}" not in polished and f"{round(cw)}" not in polished:
        return deterministic
    return polished


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

    # 신규-D: 보유성격 + 집중 리스크 관찰(결정론). 비중 권고 숫자는 아래에서 계속 계산(데이터 보존).
    hold_character, hold_secondary, hold_basis = derive_hold_character(stock, regime)
    concentration_note = derive_concentration_note(current_weight, beta=_num(stock.get("beta")))

    # 신규-A2: 매력도 3축 종합 등급(매수/관망/축소) — 정렬 패턴, 값 합산 아님.
    grade, grade_confidence, grade_basis = derive_grade(stock, market_direction=stock.get("marketScoreDirection"))

    signal_label = (stock.get("signal") or {}).get("label")
    direction = "유지"
    if not stock.get("holding"):
        direction = "매수" if signal_label == "매수" else "유지"
    elif weight_action == "줄임":
        direction = "매도" if high <= 1.0 else "비중축소"
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
        # 신규-D 추가(표시는 보유성격·관찰 중심, 위 비중 숫자는 DB 보존·포트폴리오 탭 재사용)
        "hold_character": hold_character,
        "hold_character_secondary": hold_secondary,
        "hold_character_basis": hold_basis,
        "concentration_note": concentration_note,
        # 신규-A2: 3축 종합 등급(결론 레이어, composite 미합산)
        "grade": grade,
        "grade_confidence": grade_confidence,
        "grade_basis": grade_basis,
    }
