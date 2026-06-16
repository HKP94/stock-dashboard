"""
tests/test_local_api_cors.py — local_api CORS 회귀 방지 (PR-1)

watchlist active 토글은 PATCH를 쓴다. CORS allow_methods에 PATCH가 빠지면
브라우저 프리플라이트(OPTIONS)가 막혀 토글이 무반응이 된다. 그 회귀를 막는다.
(DB·네트워크 불필요 — 미들웨어 설정만 검사)
"""

from __future__ import annotations


def _cors_options() -> dict:
    from src.local_api import app
    for mw in app.user_middleware:
        if mw.cls.__name__ == "CORSMiddleware":
            # starlette 버전에 따라 kwargs 또는 options 보관
            opts = getattr(mw, "kwargs", None) or getattr(mw, "options", None) or {}
            return dict(opts)
    raise AssertionError("CORSMiddleware not configured")


def test_cors_allows_patch():
    methods = _cors_options().get("allow_methods", [])
    assert "PATCH" in methods, f"PATCH must be allowed for watchlist toggle, got {methods}"


def test_cors_allows_core_methods():
    methods = set(_cors_options().get("allow_methods", []))
    assert {"GET", "POST", "PUT", "DELETE"}.issubset(methods)


def test_cors_origin_is_vite_dev():
    origins = _cors_options().get("allow_origins", [])
    assert "http://localhost:5173" in origins
