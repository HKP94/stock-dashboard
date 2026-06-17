"""
portfolio_advice.py — 포트폴리오 "전략 조언" (의도적 단계분리 CoT)

목적: Gemini가 사용자의 보유 포트폴리오를 보고, 한 번에 답을 뱉지 않고 단계를 코드로
분리한 Chain-of-Thought로 사고한다. 각 단계 출력을 다음 단계 입력으로 전달한다.

CoT 단계:
  STEP 1 구성 분석  — 집중도·통화/시장 배분·현금 비중·섹터 쏠림을 '사실'로 정리
  STEP 2 리스크 식별 — 종목 신호(RSI과열·데드크로스·컨센서스 괴리·퀀트 약화) 관찰형 나열
  STEP 3 레짐 정합성 — 현재 레짐 가중치 대비 포트폴리오 팩터 기울기 관찰
  STEP 4 종합       — 3~4문장 관찰 요약 + 질문형 사고 유도

★ 절대 원칙(모든 단계 프롬프트에 주입):
  - 투자 자문 금지. 매수/매도/비중 늘려라·줄여라 같은 지시 금지.
  - 관찰 / 리스크 식별 / 데이터가 말하는 것까지만. 결정은 사용자.
  - 매 출력 면책 + 단정 아닌 관찰형 서술.

키 없거나 단계 실패 → 규칙기반 폴백(코드가 집중도·비중·신호로 관찰 문장 생성).
증분: 보유·가격·레짐이 안 바뀌면 cache_key로 캐시 재사용(매 조회 호출 안 함).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import date, datetime, timezone
from typing import Optional

import psycopg
from pydantic import BaseModel, Field, ValidationError

from src.compute_quant import _REGIME_WEIGHTS
from src.db import get_conn

logger = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────────────────────────
# Gemini 2.5 (분석용). 모델명은 env로 교체 가능(하드코딩 금지 원칙).
PORTFOLIO_ADVICE_MODEL: str = os.environ.get("PORTFOLIO_ADVICE_MODEL", "gemini-2.5-flash")
DISCLAIMER: str = "투자 자문 아님 · 관찰·정보 제공 · 결정은 사용자 몫 · 원금 손실 가능"
CONCENTRATION_WARN_PCT: float = 40.0   # 단일 종목 비중 경고 임계
REGIME_KO = {"bull": "강세(위험선호)", "neutral": "중립", "bear": "약세(위험회피)"}

# 모든 단계 프롬프트에 주입하는 절대 원칙
ABSOLUTE_RULES: str = (
    "★ 절대 원칙(반드시 지켜라):\n"
    "- 너는 투자 자문가가 아니다. '매수/매도/사라/팔아라/비중을 늘려라/줄여라/담아라/덜어내라' 같은 "
    "지시·권유·매매 신호를 절대 만들지 마라.\n"
    "- 오직 '관찰 / 리스크 식별 / 데이터가 말하는 것'까지만 서술한다. 최종 결정은 사용자 몫이다.\n"
    "- 단정하지 말고 관찰형으로('~로 보입니다', '~한 점이 관찰됩니다', '~는 검토해볼 만합니다').\n"
    "- 목표가·적정주가·매매 타이밍을 생성하지 마라.\n"
    "- 투자 자문이 아니며 원금 손실이 가능하다.\n"
)


# ──────────────────────────────────────────────────────────────
# 단계별 출력 스키마 (response_mime_type=json 검증)
# ──────────────────────────────────────────────────────────────

class Step1Composition(BaseModel):
    facts: list[str] = Field(min_length=1)        # 구성 사실(수치 해석)
    concentration_note: str                        # 집중도 관찰
    allocation_note: str                           # 통화/시장 배분 관찰
    cash_note: str                                 # 현금 비중 관찰


class Step2Risks(BaseModel):
    risks: list[str] = Field(min_length=1)         # 주의가 필요한 지점(관찰형)


class Step3Regime(BaseModel):
    regime: str
    tilt_note: str                                 # 포트폴리오 팩터 기울기 관찰
    alignment_note: str                            # 레짐 대비 정합성 관찰


class Step4Summary(BaseModel):
    summary: str                                   # 3~4문장 관찰 요약
    questions: list[str] = Field(min_length=1)     # 질문형 사고 유도


# ──────────────────────────────────────────────────────────────
# LLM 호출 경계 (enrich_gemini 재사용 + 테스트 격리)
#   테스트는 patch("src.portfolio_advice._llm_call")로 대체한다.
# ──────────────────────────────────────────────────────────────

def _llm_call(client, model: str, prompt: str) -> str:
    """enrich_gemini의 지수 백오프 호출 경계를 재사용."""
    from src import enrich_gemini
    return enrich_gemini._call_gemini_with_backoff(client, model, prompt)


def _has_api_key() -> bool:
    from src import enrich_gemini
    enrich_gemini._ensure_env()
    return bool(os.environ.get("GEMINI_API_KEY"))


def _get_client():
    from src import enrich_gemini
    return enrich_gemini._get_gemini_client()


def _call_step(client, prompt: str, schema: type[BaseModel]) -> Optional[BaseModel]:
    """단계 호출 + JSON 파싱 + 스키마 검증. 실패 시 1회 재시도 후 None."""
    for attempt in range(2):
        try:
            text = _llm_call(client, PORTFOLIO_ADVICE_MODEL, prompt)
            return schema.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError, Exception) as exc:  # noqa: BLE001
            logger.warning("advice 단계 파싱 실패(%d): %s", attempt, str(exc)[:120])
    return None


# ──────────────────────────────────────────────────────────────
# 컨텍스트 수집 (보유종목 + 퀀트 + 컨센서스 + 현금 + 레짐)
# ──────────────────────────────────────────────────────────────

def _detect_regime(conn) -> str:
    """export의 레짐 판정 재사용(중복 로직 방지). 실패 시 neutral."""
    try:
        from src.export_dashboard_data import _detect_regime as _dr
        return _dr(conn).get("overall", "neutral")
    except Exception:
        return "neutral"


def gather_context(conn: psycopg.Connection) -> dict:
    """보유종목·퀀트·컨센서스·현금·레짐을 advice 입력 구조로 수집."""
    from src.compute_portfolio import _load_holdings, _load_cash, _get_usdkrw, _get_latest_price

    holdings = _load_holdings(conn)
    cash_map = _load_cash(conn)
    fx = _get_usdkrw(conn)

    def to_krw(amount: float, ccy: str) -> Optional[float]:
        if ccy == "KRW":
            return amount
        if ccy == "USD":
            return amount * fx if fx else None
        return amount

    cur = conn.cursor()
    cur.execute("SELECT ticker, name, sector, market FROM watchlist")
    meta = {r["ticker"]: dict(r) for r in cur.fetchall()}
    cur.execute("""SELECT DISTINCT ON (ticker) ticker, composite, momentum, value, quality, growth, sentiment, flags
                   FROM quant_scores ORDER BY ticker, asof DESC""")
    quant = {r["ticker"]: dict(r) for r in cur.fetchall()}
    cur.execute("""SELECT DISTINCT ON (ticker) ticker, rating, upside FROM analyst ORDER BY ticker, asof DESC""")
    ana = {r["ticker"]: dict(r) for r in cur.fetchall()}

    items: list[dict] = []
    total_eval_krw = 0.0
    for h in holdings:
        tk = h["ticker"]
        ccy = (h.get("currency") or "KRW").upper()
        price = _get_latest_price(tk, conn)
        eval_native = float(h["qty"]) * price if price else 0.0
        eval_krw = to_krw(eval_native, ccy) or 0.0
        total_eval_krw += eval_krw
        q = quant.get(tk, {})
        flags = q.get("flags") or []
        if isinstance(flags, str):
            try:
                flags = json.loads(flags)
            except Exception:
                flags = []
        m = meta.get(tk, {})
        items.append({
            "ticker": tk, "name": m.get("name") or tk,
            "market": m.get("market") or "US", "sector": m.get("sector") or "기타",
            "currency": ccy, "eval_krw": round(eval_krw),
            "composite": _num(q.get("composite")),
            "factors": {k: _num(q.get(k)) for k in ("momentum", "value", "quality", "growth", "sentiment")},
            "rating": ana.get(tk, {}).get("rating"),
            "upside": _num(ana.get(tk, {}).get("upside")),
            "flags": [f for f in flags if isinstance(f, str)],
        })

    cash_krw = 0.0
    for ccy, amt in cash_map.items():
        cash_krw += to_krw(amt, ccy) or 0.0
    asset_total = total_eval_krw + cash_krw

    # 비중(%) 부여
    for it in items:
        it["weight_pct"] = round(it["eval_krw"] / asset_total * 100, 1) if asset_total > 0 else 0.0
    cash_weight = round(cash_krw / asset_total * 100, 1) if asset_total > 0 else 0.0

    regime = _detect_regime(conn)
    return {
        "holdings": sorted(items, key=lambda x: -x["eval_krw"]),
        "cash_krw": round(cash_krw), "cash_weight_pct": cash_weight,
        "cash_by_currency": {c: round(a) for c, a in cash_map.items()},
        "asset_total_krw": round(asset_total),
        "regime": regime, "regime_weights": _REGIME_WEIGHTS.get(regime, {}),
        "fx_rate": fx,
    }


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        return None


def cache_key(ctx: dict) -> str:
    """보유(종목·평가액)·현금·레짐 시그니처 해시. 안 바뀌면 캐시 재사용."""
    sig = {
        "h": [(it["ticker"], it["eval_krw"]) for it in ctx["holdings"]],
        "cash": ctx["cash_krw"], "regime": ctx["regime"],
    }
    return hashlib.sha256(json.dumps(sig, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


# ──────────────────────────────────────────────────────────────
# 규칙기반 폴백 (키 없음 / 단계 실패) — 코드가 관찰 문장 생성
# ──────────────────────────────────────────────────────────────

def _rule_step1(ctx: dict) -> Step1Composition:
    hs = ctx["holdings"]
    facts = [f"{it['name']}({it['ticker']}) 비중 {it['weight_pct']}% · 평가 ₩{it['eval_krw']:,}" for it in hs[:6]]
    kr = sum(it["weight_pct"] for it in hs if it["market"] == "KR")
    us = sum(it["weight_pct"] for it in hs if it["market"] == "US")
    top = hs[0] if hs else None
    conc = (f"최대 비중은 {top['name']} {top['weight_pct']}%로 관찰됩니다." if top else "보유 없음")
    if top and top["weight_pct"] >= CONCENTRATION_WARN_PCT:
        conc += f" 단일 종목이 {CONCENTRATION_WARN_PCT:.0f}% 이상을 차지하는 집중 구조로 보입니다."
    return Step1Composition(
        facts=facts or ["보유 종목이 없습니다."],
        concentration_note=conc,
        allocation_note=f"시장 배분은 KR {round(kr)}% · US {round(us)}%로 관찰됩니다.",
        cash_note=f"현금 비중은 {ctx['cash_weight_pct']}%로 관찰됩니다.",
    )


def _rule_step2(ctx: dict) -> Step2Risks:
    risks: list[str] = []
    hs = ctx["holdings"]
    if hs and hs[0]["weight_pct"] >= CONCENTRATION_WARN_PCT:
        risks.append(f"{hs[0]['name']} 비중이 {hs[0]['weight_pct']}%로 집중도가 높은 점이 관찰됩니다.")
    for it in hs:
        cflags = [f for f in it["flags"] if any(k in f for k in ("과열", "데드크로스", "급락", "이격도 과열"))]
        if cflags:
            risks.append(f"{it['name']}: {cflags[0]} 신호가 관찰됩니다.")
        if it["composite"] is not None and it["composite"] < 40:
            risks.append(f"{it['name']}: 퀀트 종합 {it['composite']}로 상대적으로 약한 편으로 관찰됩니다.")
        if it["upside"] is not None and it["upside"] <= -10:
            risks.append(f"{it['name']}: 컨센서스 목표가 대비 상승여력 {it['upside']}%로 고평가 구간이 관찰됩니다.")
    if not risks:
        risks.append("개별 종목에서 두드러진 위험 신호는 관찰되지 않습니다(지속 관찰 권장).")
    return Step2Risks(risks=risks[:6])


def _rule_step3(ctx: dict) -> Step3Regime:
    hs = ctx["holdings"]
    tot = sum(it["eval_krw"] for it in hs) or 1
    def wavg(f):
        vals = [(it["eval_krw"], it["factors"].get(f)) for it in hs if it["factors"].get(f) is not None]
        return round(sum(w * v for w, v in vals) / (sum(w for w, _ in vals) or 1)) if vals else None
    tilt = {f: wavg(f) for f in ("momentum", "value", "quality", "growth", "sentiment")}
    tilt_txt = ", ".join(f"{k} {v}" for k, v in tilt.items() if v is not None) or "데이터 부족"
    rk = ctx["regime"]
    return Step3Regime(
        regime=REGIME_KO.get(rk, rk),
        tilt_note=f"보유 포트폴리오의 팩터 가중평균은 {tilt_txt}로 관찰됩니다.",
        alignment_note=f"현재 레짐은 {REGIME_KO.get(rk, rk)}이며, 레짐 권장 가중치 대비 어느 팩터에 "
                       f"기울어 있는지는 위 수치로 검토해볼 만합니다.",
    )


def _rule_step4(ctx: dict, s1: Step1Composition, s2: Step2Risks, s3: Step3Regime) -> Step4Summary:
    hs = ctx["holdings"]
    parts = [f"보유 {len(hs)}종목·현금 {ctx['cash_weight_pct']}%로 구성되어 있습니다."]
    if hs:
        parts.append(s1.concentration_note)
    parts.append(f"주의가 필요할 수 있는 지점으로 {len(s2.risks)}건이 관찰되었습니다.")
    qs = []
    if hs and hs[0]["weight_pct"] >= CONCENTRATION_WARN_PCT:
        qs.append("집중도가 높은 점을 어떻게 볼지 검토해볼 만합니다.")
    qs.append("레짐 정합성(팩터 기울기)을 어떻게 해석할지 생각해볼 수 있습니다.")
    return Step4Summary(summary=" ".join(parts), questions=qs)


def _rule_based(ctx: dict) -> dict:
    s1, s2, s3 = _rule_step1(ctx), _rule_step2(ctx), _rule_step3(ctx)
    s4 = _rule_step4(ctx, s1, s2, s3)
    return _assemble(ctx, s1, s2, s3, s4, source="rule")


# ──────────────────────────────────────────────────────────────
# 프롬프트 빌더 (각 단계, 절대 원칙 주입)
# ──────────────────────────────────────────────────────────────

def _ctx_json(ctx: dict) -> str:
    slim = {
        "holdings": [{k: it[k] for k in ("ticker", "name", "market", "sector", "currency",
                                         "weight_pct", "composite", "factors", "rating", "upside", "flags")}
                     for it in ctx["holdings"]],
        "cash_weight_pct": ctx["cash_weight_pct"], "asset_total_krw": ctx["asset_total_krw"],
        "regime": ctx["regime"], "regime_weights": ctx["regime_weights"],
    }
    return json.dumps(slim, ensure_ascii=False, default=str)


def _prompt_step1(ctx: dict) -> str:
    return (
        "너는 포트폴리오 구성을 '사실 그대로' 정리하는 분석가다.\n" + ABSOLUTE_RULES +
        "\n아래 보유 데이터의 집중도(종목별 비중)·통화/시장(KR/US) 배분·현금 비중·섹터 쏠림을 "
        "수치 해석 중심으로 정리하라. 판단·권유는 하지 마라.\n\n"
        f"[보유 데이터]\n{_ctx_json(ctx)}\n\n"
        "JSON으로만 답하라: "
        '{"facts":["구성 사실 3~6개"],"concentration_note":"집중도 관찰 한두 문장",'
        '"allocation_note":"통화/시장 배분 관찰","cash_note":"현금 비중 관찰"}'
    )


def _prompt_step2(ctx: dict, s1: Step1Composition) -> str:
    return (
        "너는 포트폴리오의 '주의가 필요한 지점'을 관찰형으로 식별하는 분석가다.\n" + ABSOLUTE_RULES +
        "\n아래 STEP1 구성 분석과 각 종목 신호(RSI과열·데드크로스·컨센서스 괴리·퀀트 약화·집중도)를 바탕으로 "
        "리스크를 '관찰'로 나열하라(예: '단일 종목 X% 집중', '보유 중 X는 퀀트·컨센서스 모두 약화로 관찰'). "
        "매도·축소 같은 지시는 절대 금지.\n\n"
        f"[STEP1]\n{s1.model_dump_json()}\n\n[보유 데이터]\n{_ctx_json(ctx)}\n\n"
        'JSON으로만: {"risks":["관찰형 리스크 2~6개"]}'
    )


def _prompt_step3(ctx: dict, s2: Step2Risks) -> str:
    return (
        "너는 레짐 정합성을 관찰하는 분석가다.\n" + ABSOLUTE_RULES +
        f"\n현재 시장 레짐은 '{ctx['regime']}'이고 레짐 권장 팩터 가중치는 {json.dumps(ctx['regime_weights'])}이다. "
        "보유 포트폴리오가 어느 팩터(모멘텀/가치/퀄리티/성장/감성)에 기울어 있는지 관찰하고, "
        "레짐 대비 정합/괴리를 관찰형으로 서술하라(예: '강세 레짐인데 보유는 방어적 가치주 위주로 관찰'). "
        "판단·권유는 사용자 몫이며 하지 마라.\n\n"
        f"[STEP2 리스크]\n{s2.model_dump_json()}\n\n[보유 데이터]\n{_ctx_json(ctx)}\n\n"
        'JSON으로만: {"regime":"레짐 한글","tilt_note":"팩터 기울기 관찰","alignment_note":"레짐 정합성 관찰"}'
    )


def _prompt_step4(ctx: dict, s1, s2, s3) -> str:
    return (
        "너는 앞 3단계를 종합하는 분석가다.\n" + ABSOLUTE_RULES +
        "\n아래 STEP1~3을 3~4문장의 '관찰 요약'으로 합치고, 사용자가 스스로 사고하도록 질문형 문장 1~3개를 더하라"
        "(예: '집중도가 높은 점을 어떻게 볼지 검토해볼 만합니다'). 지시·정답 제시 금지.\n\n"
        f"[STEP1]\n{s1.model_dump_json()}\n[STEP2]\n{s2.model_dump_json()}\n[STEP3]\n{s3.model_dump_json()}\n\n"
        'JSON으로만: {"summary":"3~4문장 관찰 요약","questions":["질문형 1~3개"]}'
    )


# ──────────────────────────────────────────────────────────────
# 조립 + 메인 오케스트레이션
# ──────────────────────────────────────────────────────────────

def _assemble(ctx, s1, s2, s3, s4, source: str) -> dict:
    now = datetime.now()
    return {
        "generatedAt": now.strftime("%Y-%m-%dT%H:%M"),
        "generatedAtLabel": now.strftime("%Y-%m-%d %H:%M") + " KST",
        "source": source,                      # "gemini" | "rule"
        "cacheKey": cache_key(ctx),
        "holdingsCount": len(ctx["holdings"]),
        "regime": REGIME_KO.get(ctx["regime"], ctx["regime"]),
        "disclaimer": DISCLAIMER,
        "step1": s1.model_dump(),
        "step2": s2.model_dump(),
        "step3": s3.model_dump(),
        "step4": s4.model_dump(),
    }


def analyze_portfolio(conn: psycopg.Connection, force: bool = False) -> dict:
    """포트폴리오 전략 조언 생성(CoT). 캐시 재사용(force=True면 무시)."""
    ctx = gather_context(conn)
    if not ctx["holdings"]:
        return {
            "generatedAt": datetime.now().strftime("%Y-%m-%dT%H:%M"),
            "generatedAtLabel": datetime.now().strftime("%Y-%m-%d %H:%M") + " KST",
            "source": "empty", "cacheKey": cache_key(ctx), "holdingsCount": 0,
            "regime": REGIME_KO.get(ctx["regime"], ctx["regime"]), "disclaimer": DISCLAIMER,
            "empty": True,
        }

    key = cache_key(ctx)
    if not force:
        cached = _load_cached(conn, key)
        if cached:
            logger.info("advice 캐시 재사용 (key=%s)", key)
            return cached

    # 키 없으면 규칙기반
    if not _has_api_key():
        logger.info("GEMINI_API_KEY 없음 → 규칙기반 폴백")
        result = _rule_based(ctx)
        _save(conn, result)
        return result

    # CoT 4단계. STEP1이 LLM으로 실패하면(키 정상이나 크레딧/쿼터 소진 등) 남은 단계는
    # 호출하지 않고 전부 규칙기반으로 단락 — 불필요한 429 재시도 대기 방지.
    try:
        client = _get_client()
        s1_llm = _call_step(client, _prompt_step1(ctx), Step1Composition)
        if s1_llm is None:
            logger.info("advice STEP1 LLM 실패 → 전체 규칙기반 단락")
            s1, s2, s3 = _rule_step1(ctx), _rule_step2(ctx), _rule_step3(ctx)
            s4 = _rule_step4(ctx, s1, s2, s3)
            source = "rule"
        else:
            s1 = s1_llm
            s2 = _call_step(client, _prompt_step2(ctx, s1), Step2Risks) or _rule_step2(ctx)
            s3 = _call_step(client, _prompt_step3(ctx, s2), Step3Regime) or _rule_step3(ctx)
            s4 = _call_step(client, _prompt_step4(ctx, s1, s2, s3), Step4Summary) or _rule_step4(ctx, s1, s2, s3)
            source = "gemini"
    except Exception as exc:  # noqa: BLE001
        logger.warning("advice CoT 실패 → 규칙기반 폴백: %s", str(exc)[:120])
        s1, s2, s3 = _rule_step1(ctx), _rule_step2(ctx), _rule_step3(ctx)
        s4 = _rule_step4(ctx, s1, s2, s3)
        source = "rule"

    result = _assemble(ctx, s1, s2, s3, s4, source=source)
    _save(conn, result)
    return result


# ── DB 캐시 ──────────────────────────────────────────────────────

def _load_cached(conn: psycopg.Connection, key: str) -> Optional[dict]:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM portfolio_advice WHERE cache_key=%s", (key,))
            row = cur.fetchone()
        return dict(row["payload"]) if row else None
    except Exception:
        return None


def load_latest(conn: psycopg.Connection) -> Optional[dict]:
    """가장 최근 advice + 현재 포트폴리오 대비 stale 여부."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT payload, cache_key FROM portfolio_advice ORDER BY generated_at DESC LIMIT 1")
            row = cur.fetchone()
        if not row:
            return None
        ctx = gather_context(conn)
        payload = dict(row["payload"])
        payload["stale"] = (row["cache_key"] != cache_key(ctx))
        return payload
    except Exception:
        return None


def _save(conn: psycopg.Connection, result: dict) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO portfolio_advice (cache_key, payload, generated_at)
                   VALUES (%s, %s::jsonb, %s)
                   ON CONFLICT (cache_key) DO UPDATE SET payload=EXCLUDED.payload, generated_at=EXCLUDED.generated_at""",
                (result["cacheKey"], json.dumps(result, ensure_ascii=False),
                 datetime.now(timezone.utc)),
            )
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("advice 저장 실패(비치명적): %s", str(exc)[:120])
        conn.rollback()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    with get_conn() as conn:
        out = analyze_portfolio(conn, force=True)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    print("\n⚠️ 투자 자문 아님 / 원금 손실 가능")
