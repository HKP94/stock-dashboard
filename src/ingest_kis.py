"""
ingest_kis.py — KIS Developers(한국투자증권 OpenAPI) 보조 수집 경로 (옵션, 기본 OFF)

PR-4: 환경변수 KIS_APPKEY / KIS_APPSECRET 가 있을 때만 활성화된다.
키가 없으면 모든 함수가 빈 결과({}/None)로 **조용히 스킵** → 네이버/FnGuide 기본 경로 유지.
KIS가 활성화되면 재무비율(ROE·부채비율)·투자의견/목표가를 '있으면 우선' 보강한다.

⚠️ 이 모듈은 **읽기 전용 조회**만 한다(시세·재무·컨센서스). 주문/체결 API는 호출하지 않는다.
⚠️ 시크릿(APPKEY/SECRET/토큰)은 환경변수에서만 읽고 로그·문서에 남기지 않는다.
⚠️ 실제 키 연동·검증은 사용자 몫. 본 파일은 키 없는 환경에서 에러 없이 스킵되는 골격이다.

참고 엔드포인트(운영 시 확인 필요, 구조는 바뀔 수 있음):
  - POST /oauth2/tokenP                              : 접근토큰 발급
  - GET  /uapi/domestic-stock/v1/finance/financial-ratio : 재무비율(ROE 등)
  - GET  /uapi/domestic-stock/v1/finance/stability-ratio : 안정성비율(부채비율 등)
  - GET  /uapi/domestic-stock/v1/quotations/inquire-...   : 투자의견/목표가(제공 시)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

KIS_BASE_URL: str = os.environ.get("KIS_BASE_URL", "https://openapi.koreainvestment.com:9443")
_TOKEN_CACHE: dict = {"token": None, "exp": 0.0}


def kis_enabled() -> bool:
    """KIS 보조 경로 활성 여부(키 2종 모두 존재할 때만)."""
    return bool(os.environ.get("KIS_APPKEY") and os.environ.get("KIS_APPSECRET"))


def _get_token() -> Optional[str]:
    """접근토큰 발급(간이 캐시). 비활성/실패 시 None."""
    if not kis_enabled():
        return None
    now = time.time()
    if _TOKEN_CACHE["token"] and _TOKEN_CACHE["exp"] > now + 60:
        return _TOKEN_CACHE["token"]
    try:
        import requests
        resp = requests.post(
            f"{KIS_BASE_URL}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": os.environ["KIS_APPKEY"],
                "appsecret": os.environ["KIS_APPSECRET"],
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token")
        if token:
            _TOKEN_CACHE["token"] = token
            _TOKEN_CACHE["exp"] = now + float(data.get("expires_in", 86400))
            return token
    except Exception as exc:
        logger.warning("KIS 토큰 발급 실패(스킵): %s", exc)
    return None


def fetch_kis_metrics(code: str) -> dict:
    """
    KIS 재무비율/투자의견 조회 → {roe, debt_ratio, target_price, rating, n_analysts} 중 가능한 항목.
    비활성(키 없음)·실패 시 빈 dict 반환(상위에서 네이버/FnGuide 값 유지).

    NOTE: 실제 TR_ID·파라미터·응답 필드는 KIS 문서/계정 권한에 따라 다르다. 사용자가 키 연동 시
          아래 TODO를 실제 엔드포인트로 채운다. 키 없는 환경에서는 항상 {} 를 반환한다.
    """
    if not kis_enabled():
        return {}
    token = _get_token()
    if not token:
        return {}

    out: dict = {}
    try:
        import requests  # noqa: F401  (실제 호출 시 사용)
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": os.environ["KIS_APPKEY"],
            "appsecret": os.environ["KIS_APPSECRET"],
            "content-type": "application/json",
        }
        # TODO(PM): 재무비율(ROE)·안정성비율(부채비율)·투자의견/목표가 엔드포인트 호출 후
        #           out["roe"], out["debt_ratio"], out["target_price"], out["rating"],
        #           out["n_analysts"] 에 매핑. ROE는 비율(0.07) 단위로 정규화.
        #           현재는 골격만 — 실제 키 연동 시 구현.
        _ = headers  # 미사용 경고 방지(골격)
        logger.info("KIS 활성: %s 보강 시도(골격 — 실제 매핑 미구현)", code)
    except Exception as exc:
        logger.warning("KIS 조회 실패(스킵) %s: %s", code, exc)
        return {}
    return out
