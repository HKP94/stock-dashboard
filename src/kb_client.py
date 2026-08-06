"""
kb_client.py — KB증권 OpenAPI 최소 클라이언트 (**조회 전용**)

베이스 https://developer.kbsec.com:32484, REST POST/JSON.
인증: POST /oauth2/token (grantType=client_credentials + appKey/appSecret) → Bearer access_token
(String 440, expires_in 86400=24h). 계좌번호·계좌비번 INPUT 없음 — 토큰에 계좌가 귀속된다.

★ 전문 봉투(명세 엑셀 미기재 — 실호출로 확인)
  엑셀 시트의 INPUT/OUTPUT 표는 **dataBody 안쪽**만 기술한다. 실제 요청·응답은
      {"dataHeader": {...}, "dataBody": {...}}
  형태이며, 토큰 발급도 동일하다(평면 body는 500 E021 "앱키로 앱정보 추출 중 오류").
  조회 API의 dataHeader에는 ipAddr·macAddr이 **필수**(누락 시 "입력 전문 [dataHeader.x]을
  확인해 주세요"). 응답 dataHeader.processFlag = A(정상) / B(오류) — 조회 결과 0건도 A다.

★ 절대 규칙 (CLAUDE.md §0 자동 주문 금지)
  주문·정정·취소 계열(SSAM*/SKAM*/SPAO*/예약주문)은 **영구 미구현**이다.
  ALLOWED_APIS 화이트리스트 밖 코드는 KBOrderAPIBlocked로 즉시 차단한다(회귀 테스트 있음).

★ 시크릿
  appKey/appSecret/access_token은 환경변수에서만 읽고, 로그·예외 문자열에 남기지 않는다
  (_scrub이 응답 본문·예외 메시지에서 마스킹).
"""

from __future__ import annotations

import logging
import os
import socket
import time
import uuid
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL: str = os.environ.get("KB_BASE_URL", "https://developer.kbsec.com:32484")
TIMEOUT_SECONDS: float = float(os.environ.get("KB_TIMEOUT_SECONDS", "15"))
RETRIES: int = 3  # 지수 백오프(1s→2s→4s). 무한재시도 금지.

# 조회 API 화이트리스트. **주문 계열은 여기에 절대 추가하지 않는다.**
ALLOWED_APIS: frozenset[str] = frozenset(
    {
        "ssqm2952",  # 잔고현황 조회(체결기준) — 국내 보유 전종목 + 예수금·순자산
        "spqm2226",  # 해외주식계좌잔고평가조회
        "ssqm0004",  # 예수금내역
        "siqm4900",  # 종목기본정보(티커 판별 보조)
        "ivu10430",  # 투자자별 매매동향(수급) — 계좌 무관 시세계 API
    }
)


class KBOrderAPIBlocked(RuntimeError):
    """주문·정정·취소 등 화이트리스트 밖 API 호출 시도 — 설계상 영구 차단."""


class KBApiError(RuntimeError):
    """KB API 호출 실패(마스킹된 메시지)."""


_TOKEN: dict = {"value": None, "exp": 0.0}
_DATA_HEADER: dict = {}
# 마지막 응답의 HTTP 헤더·상태 — rate limit 한도 관찰용(2단계 파일럿). 시크릿 없음.
LAST_RESPONSE: dict = {"status": None, "headers": {}}


def _data_header() -> dict:
    """조회 API 필수 dataHeader(ipAddr·macAddr). 1회 계산 후 재사용."""
    if not _DATA_HEADER:
        node = uuid.getnode()
        _DATA_HEADER.update(
            {
                "ipAddr": socket.gethostbyname(socket.gethostname()),
                "macAddr": "".join(f"{(node >> i) & 0xFF:02X}" for i in range(40, -1, -8)),
            }
        )
    return _DATA_HEADER


def kb_enabled() -> bool:
    """키 2종이 모두 있을 때만 활성."""
    return bool(os.environ.get("KB_APP_KEY") and os.environ.get("KB_APP_SECRET"))


def _creds() -> tuple[str, str]:
    key = os.environ.get("KB_APP_KEY", "")
    secret = os.environ.get("KB_APP_SECRET", "")
    if not (key and secret):
        raise KBApiError("KB_APP_KEY/KB_APP_SECRET 미설정 (.env 확인)")
    return key, secret


def _scrub(text: str) -> str:
    """키·시크릿·토큰이 메시지에 섞여 나오면 마스킹(로그·예외 노출 금지)."""
    out = text or ""
    for secret in (os.environ.get("KB_APP_KEY"), os.environ.get("KB_APP_SECRET"), _TOKEN["value"]):
        if secret and len(secret) >= 8:
            out = out.replace(secret, f"***{secret[-4:]}")
    return out


def _get_token(force: bool = False) -> str:
    """접근토큰(메모리 캐시). 만료 60초 전 또는 force(401)면 재발급."""
    now = time.time()
    if not force and _TOKEN["value"] and _TOKEN["exp"] > now + 60:
        return _TOKEN["value"]
    key, secret = _creds()
    try:
        resp = requests.post(
            f"{BASE_URL}/oauth2/token",
            json={
                "dataHeader": {},
                "dataBody": {
                    "grantType": "client_credentials",
                    "appKey": key,
                    "appSecret": secret,
                },
            },
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise KBApiError(f"토큰 발급 통신 실패: {_scrub(str(exc))}") from None
    if resp.status_code != 200:
        raise KBApiError(f"토큰 발급 실패 HTTP {resp.status_code}: {_scrub(resp.text[:200])}")
    data = (resp.json() or {}).get("dataBody") or {}
    token = data.get("access_token")
    if not token:
        raise KBApiError("토큰 발급 응답에 access_token 없음")
    _TOKEN["value"] = token
    _TOKEN["exp"] = now + float(data.get("expires_in") or 86400)
    logger.info("KB 토큰 발급 완료(유효 %ss)", data.get("expires_in"))
    return token


def call(api_code: str, payload: Optional[dict] = None) -> dict:
    """
    조회 API 1건 호출 → 응답의 **dataBody** dict.

    - 화이트리스트 밖 코드(주문 계열 포함)는 KBOrderAPIBlocked.
    - 401은 토큰 재발급 후 1회 재시도(24h 만료 대비).
    - 통신 오류/5xx는 지수 백오프 최대 RETRIES회. 그 외 4xx는 즉시 실패.
    - 업무 오류(dataHeader.processFlag='B')는 KBApiError. 조회 0건은 정상('A')이라
      빈 Record로 반환된다(호출부가 판단).
    """
    code = (api_code or "").strip().lower()
    if code not in ALLOWED_APIS:
        raise KBOrderAPIBlocked(
            f"차단된 API: {code!r} — kb_client는 조회 전용이며 주문·정정·취소 API를 지원하지 않는다"
        )
    url = f"{BASE_URL}/api/v1/{code}"
    reauthed = False
    delay = 1.0
    last_err = ""

    for attempt in range(RETRIES):
        try:
            resp = requests.post(
                url,
                json={"dataHeader": _data_header(), "dataBody": payload or {}},
                headers={
                    "Authorization": f"bearer {_get_token()}",
                    "Content-Type": "application/json",
                },
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            last_err = f"통신 실패: {_scrub(str(exc))}"
            if attempt == RETRIES - 1:
                break
            time.sleep(delay)
            delay *= 2
            continue

        LAST_RESPONSE.update({"status": resp.status_code, "headers": dict(resp.headers)})
        if resp.status_code == 401 and not reauthed:
            reauthed = True
            logger.info("KB %s 401 — 토큰 재발급 후 재시도", code)
            _get_token(force=True)
            continue
        if resp.status_code >= 500:
            last_err = f"HTTP {resp.status_code}: {_scrub(resp.text[:200])}"
            if attempt == RETRIES - 1:
                break
            time.sleep(delay)
            delay *= 2
            continue
        if resp.status_code != 200:
            raise KBApiError(f"{code} HTTP {resp.status_code}: {_scrub(resp.text[:200])}")

        data = resp.json() or {}
        head = data.get("dataHeader") or {}
        body = data.get("dataBody")
        if head.get("processFlag") == "B" or body is None:
            raise KBApiError(
                f"{code} 업무오류 {head.get('processCode')}: {_scrub(str(head.get('processMessage')))}"
            )
        return body

    raise KBApiError(f"{code} 재시도 소진 — {last_err}")
