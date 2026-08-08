"""Phase 1 색 축 분리 회귀 가드.

과거엔 C.ok/C.bad 두 색이 '등락'과 '상태'를 겸했다(등락 19줄 + 상태 12줄, 총 200회).
등락만 한국 관례로 뒤집으면 '긍정 심리'까지 빨강이 되므로 축을 갈랐다.
이 가드는 그 분리가 무너지는 것을 막는다.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "dashboard-web/src"
CODE = ["ui.jsx", "App.jsx", "tabsA.jsx", "tabsB.jsx", "tabsC.jsx", "tabsD.jsx", "tabsE.jsx", "display.js"]


def _text(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


def test_no_ok_bad_identifiers_left():
    """★검수 게이트: C.ok/C.bad 잔존 0. 이름이 두 의미를 겸하던 원인이라 되살리지 않는다."""
    offenders = []
    for f in CODE:
        for i, line in enumerate(_text(f).splitlines(), 1):
            if re.search(r"\bC\.(ok|bad)(Bg)?\b", line):
                offenders.append(f"{f}:{i}")
    assert not offenders, f"C.ok/C.bad 잔존: {offenders}"


def test_palette_is_token_backed():
    """팔레트가 값을 직접 들고 있으면 테마 전환이 안 먹는다 — 전부 var(--…)여야 한다."""
    src = _text("ui.jsx")
    m = re.search(r"export const C = \{(.*?)\n\};", src, re.S)
    assert m, "C 팔레트를 찾지 못함"
    body = m.group(1)
    assert not re.search(r"#[0-9a-fA-F]{3,8}", body), "팔레트에 하드코딩 색상값이 남아 있다"
    for key in ("up", "down", "flat", "pos", "warn", "neg"):
        assert re.search(rf"\b{key}:\s*\"var\(--", body), f"{key} 토큰 배선 없음"


def test_price_axis_uses_korean_convention():
    """등락 토큰이 한국 관례(상승 빨강 / 하락 파랑)를 가리키는지."""
    tokens = (SRC / "tokens.css").read_text(encoding="utf-8")
    assert "--price-up: #FF4D4F" in tokens
    assert "--price-down: #3B82F6" in tokens


def test_price_direction_sites_use_price_axis():
    """가격·손익 방향 표시는 상태축(pos/neg)이 아니라 등락축(up/down)을 써야 한다."""
    checks = [
        ("tabsC.jsx", r"totalPnlKrw >= 0 \? C\.up : C\.down"),
        ("tabsD.jsx", r"pctColor = .*C\.up : C\.down"),
        ("tabsB.jsx", r"ix\.chg > 0 \? C\.up"),
        ("tabsA.jsx", r"total_pnl >= 0 \? C\.up : C\.down"),
        ("ui.jsx", r"flat \? C\.flat : up \? C\.up : C\.down"),
    ]
    for f, pat in checks:
        assert re.search(pat, _text(f)), f"{f}: 등락축 배선 없음 ({pat})"


def test_state_axis_kept_for_sentiment():
    """심리·신호는 상태축 유지 — 등락으로 넘어가면 '긍정'이 빨강이 된다."""
    ui = _text("ui.jsx")
    assert re.search(r'label === "긍정" \? \{ c: C\.pos', ui)
    assert re.search(r'signal\.label === "매수" \? C\.pos', ui)


def test_no_hardcoded_white_text():
    """다크에서 '밝은 배경 + 흰 글자'로 사라지던 패턴 재발 방지.

    실제 위험은 **같은 style 객체 안에** `background: C.ink`와 흰 글자가 같이 있는 경우다
    (로고 마크·저장 버튼이 그랬다 — 다크에서 C.ink가 밝아지며 흰 글자가 묻혔다).
    `background: C.ink` 단독은 차트 범례 견본 등 정당한 용도가 있어 금지하지 않는다.
    """
    for f in CODE:
        src = _text(f)
        assert not re.search(r'color:\s*"#[fF]{3,6}"', src), f"{f}: 흰색 하드코딩"
        for m in re.finditer(r"style=\{\{[^}]*\}\}", src):
            block = m.group(0)
            if "background: C.ink," in block and ("#fff" in block or "onAcc" in block):
                raise AssertionError(f"{f}: 잉크 배경 + 흰 글자 조합 — 다크에서 사라진다")


def test_app_css_removed():
    """Vite 스캐폴드 잔재 — import되지도 않았다."""
    assert not (SRC / "App.css").exists()


def test_internal_terms_not_shown_raw():
    """⑤ 내부 용어(fallback 등)가 사용자에게 그대로 노출되지 않게."""
    disp = _text("display.js")
    assert "export function userFlagLabel" in disp
    tabs = _text("tabsA.jsx")
    assert "fallback" in _text("tabsA.jsx").split("isDataQuality")[1][:200], "fallback이 데이터품질로 분류되지 않음"
    assert "{a.f}</span>" not in tabs, "가공 없는 원본 플래그가 렌더된다"
