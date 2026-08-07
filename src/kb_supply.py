"""
kb_supply.py — KB IVU10430(종목별 투자자 매매동향) 파싱 **단일 소스**

★ 관례차 3건 (2026-08-06 파일럿 실측, 5종목×5거래일 75셀 3자 대조로 확정)
  ① 단위: KB 금액은 **백만원**, pykrx/`investor_flow`는 **원** → ×1,000,000 환산.
     환산 시 종목·일자당 최대 ~1백만원 반올림 잔차가 남는다(구조적, 제거 불가).
  ② 외국인 정의: KB `fgnr`(외국인)는 pykrx `외국인합계`가 **아니다**.
     `fgnr + ntv_fgnr`(내외국인)이라야 일치한다 — `fgnr` 단독을 쓰면 대형주에서
     수십억~수백억 규모로 조용히 어긋난다(SK하이닉스 실측 -164.9억).
  ③ 확정치만: `mtrl_clsf='0'`(확정치)만 쓰고 `'1'`(추정치)은 버린다.
  ④ **전부 0인 행은 버린다** — KB는 아직 집계되지 않은 당일(장 시작 전/장중) 봉도
     `mtrl_clsf='0'`으로 내려보내면서 외국인·기관·개인을 모두 0으로 준다(실측 2026-08-07).
     그대로 적재하면 오늘 수급이 '중립 0원'으로 저장되고 3거래일 합계까지 오염된다.
     세 값이 **동시에** 0인 경우만 제외하므로(개별 0은 유지) 실거래 봉은 잃지 않는다.
     pykrx는 애초에 그런 행을 주지 않으므로, 이 가드가 두 소스의 행 집합을 일치시킨다.

이 규칙이 두 곳에 복제되면 한쪽만 고쳐져 값이 갈린다. 파이프라인 수집과 파일럿 리포트가
**모두 이 모듈을 import** 한다(회귀 가드 tests/test_kb_client.py::TestSupplyParsing).
"""

from __future__ import annotations

from datetime import date, datetime

SUPPLY_API = "ivu10430"

# ① 단위 환산: KB 백만원 → 원
KB_UNIT_KRW: int = 1_000_000

# 12분류 상세(현재는 저장하지 않고 관찰·검증용으로만 노출 — 저장은 백로그).
DETAIL_FIELDS: list[tuple[str, str]] = [
    ("scrt", "증권"), ("insr", "보험"), ("invst_trst", "투신"), ("invst_bnk", "종금"),
    ("bnk", "은행"), ("fnd", "기금"), ("prv_o_fnd", "사모펀드"), ("etc_corp", "기타법인"),
    ("ntn", "국가"), ("ntv_fgnr", "내외국인"), ("pgm", "프로그램"),
    ("frgn_afflt_dl_orgn_sum", "외국계거래원합계"),
]


def _num(value: object) -> float:
    """KB의 zero-padded 고정길이 문자열 → float. 공백/비수치는 0.0."""
    try:
        return float(str(value).strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_supply_records(records: list[dict]) -> dict[date, dict]:
    """
    IVU10430 `out` 레코드 → {체결일: {foreign, institution, individual, ...}}. **금액 단위 = 원**.

    - `foreign`은 pykrx `외국인합계`와 같은 정의(fgnr + ntv_fgnr).
    - `foreign_narrow`는 KB `fgnr` 단독(정의 차이 노출·검증용).
    - 추정치(mtrl_clsf='1')·날짜 없는 행·미집계 placeholder(3분류 전부 0)는 제외한다.
    """
    out: dict[date, dict] = {}
    for rec in records:
        if str(rec.get("mtrl_clsf") or "").strip() not in ("0", ""):
            continue  # ③ 확정치만
        raw_dt = str(rec.get("dt") or "").strip()
        if len(raw_dt) != 8 or not raw_dt.isdigit():
            continue
        bar = datetime.strptime(raw_dt, "%Y%m%d").date()
        fgnr = _num(rec.get("fgnr"))
        ntv = _num(rec.get("ntv_fgnr"))
        ogn = _num(rec.get("ogn"))
        indv = _num(rec.get("indv"))
        if (fgnr + ntv) == 0 and ogn == 0 and indv == 0:
            continue  # ④ 미집계 placeholder(당일 장중 등) — 적재하면 오늘 수급이 0으로 오염
        out[bar] = {
            "foreign": (fgnr + ntv) * KB_UNIT_KRW,        # ② ≡ pykrx 외국인합계
            "foreign_narrow": fgnr * KB_UNIT_KRW,
            "institution": ogn * KB_UNIT_KRW,
            "individual": indv * KB_UNIT_KRW,
            "close": _num(rec.get("cls_prc")),
            "details": {ko: _num(rec.get(en)) * KB_UNIT_KRW for en, ko in DETAIL_FIELDS},
            "raw": rec,
        }
    return out
