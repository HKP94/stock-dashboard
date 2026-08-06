"""KB Open API 클라이언트 — 주문 차단 가드·토큰·봉투 테스트 + IVU10430 파싱 관례차 가드.

전부 모킹. 실호출 테스트 금지(키 노출·쿼터·부작용).
"""
from __future__ import annotations

import pytest

from src import kb_client
from scripts.kb_supply_pilot import KB_UNIT_KRW, _kb_rows_by_date


class TestOrderAPIBlocked:
    """CLAUDE.md §0 자동 주문 금지 — 주문 계열은 호출 자체가 예외여야 한다."""

    ORDER_CODES = [
        "ssam1801", "ssam1802", "ssam1805", "ssam1806",
        "ssam0831", "ssam5762", "ssam5763", "ssam5764",
        "skam2101", "skam2102", "skam2201", "skam2202",
        "spao2104", "spao2106",
    ]

    @pytest.mark.parametrize("code", ORDER_CODES)
    def test_order_api_raises(self, code, monkeypatch):
        monkeypatch.setattr(kb_client, "_get_token", lambda force=False: "tok")
        with pytest.raises(kb_client.KBOrderAPIBlocked):
            kb_client.call(code, {})

    def test_whitelist_is_query_only(self):
        """화이트리스트에 주문 계열 접두사가 새로 들어오면 실패."""
        for code in kb_client.ALLOWED_APIS:
            assert not code.startswith(("ssam", "skam", "spao")), code

    def test_supply_api_is_allowed(self):
        """2단계 수급 파일럿 — 계좌 무관 조회 API만 추가된다."""
        assert "ivu10430" in kb_client.ALLOWED_APIS


class _Resp:
    def __init__(self, status=200, payload=None, text="", headers=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload


def _ok(body):
    return {"dataHeader": {"processFlag": "A", "processCode": "0011"}, "dataBody": body}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("KB_APP_KEY", "K" * 36)
    monkeypatch.setenv("KB_APP_SECRET", "S" * 32)
    kb_client._TOKEN.update({"value": None, "exp": 0.0})
    kb_client._DATA_HEADER.clear()
    kb_client._DATA_HEADER.update({"ipAddr": "127.0.0.1", "macAddr": "AABBCCDDEEFF"})
    yield
    kb_client._TOKEN.update({"value": None, "exp": 0.0})


class TestEnvelope:
    def test_request_wraps_in_data_body(self, monkeypatch):
        """엑셀 명세의 INPUT은 dataBody 안쪽 — 평면 body는 KB가 거부한다."""
        seen = {}
        monkeypatch.setattr(kb_client, "_get_token", lambda force=False: "tok")
        monkeypatch.setattr(kb_client.requests, "post",
                            lambda url, **kw: (seen.update(kw["json"]), _Resp(payload=_ok({"out": []})))[1])
        kb_client.call("ivu10430", {"is_cd": "005930"})
        assert seen["dataBody"] == {"is_cd": "005930"}
        assert set(seen["dataHeader"]) >= {"ipAddr", "macAddr"}  # 조회 API 필수

    def test_business_error_raises(self, monkeypatch):
        monkeypatch.setattr(kb_client, "_get_token", lambda force=False: "tok")
        monkeypatch.setattr(kb_client.requests, "post", lambda url, **kw: _Resp(
            payload={"dataHeader": {"processFlag": "B", "processCode": "9999",
                                    "processMessage": "입력 전문 확인"}, "dataBody": {}}))
        with pytest.raises(kb_client.KBApiError):
            kb_client.call("ivu10430", {})

    def test_response_headers_captured_for_rate_limit_observation(self, monkeypatch):
        monkeypatch.setattr(kb_client, "_get_token", lambda force=False: "tok")
        monkeypatch.setattr(kb_client.requests, "post", lambda url, **kw: _Resp(
            payload=_ok({"out": []}), headers={"X-RateLimit-Remaining": "99"}))
        kb_client.call("ivu10430", {})
        assert kb_client.LAST_RESPONSE["headers"]["X-RateLimit-Remaining"] == "99"

    def test_secret_never_leaks_in_errors(self, monkeypatch):
        secret = "S" * 32
        monkeypatch.setattr(kb_client.requests, "post",
                            lambda url, **kw: _Resp(status=500, text=f"bad {secret}"))
        with pytest.raises(kb_client.KBApiError) as exc:
            kb_client._get_token()
        assert secret not in str(exc.value)


class TestSupplyParsing:
    """IVU10430 관례차 가드 — 실측(2026-08-06, 5종목×5거래일 75셀)으로 확정된 규칙."""

    REC = {"mtrl_clsf": "0", "dt": "20260806", "cls_prc": "70000",
           "fgnr": "-1693585", "ntv_fgnr": "16486",
           "ogn": "-422181", "indv": "2039284",
           "scrt": "-100000", "insr": "0", "invst_trst": "-200000", "invst_bnk": "0",
           "bnk": "0", "fnd": "-122180", "prv_o_fnd": "0", "etc_corp": "1",
           "ntn": "0", "pgm": "-500", "frgn_afflt_dl_orgn_sum": "-1000"}

    def test_unit_is_millions_of_krw(self):
        """★관례차 1 — KB 금액은 백만원, pykrx/investor_flow는 원."""
        row = _kb_rows_by_date([self.REC])["20260806"]
        assert row["institution"] == -422181 * KB_UNIT_KRW
        assert row["individual"] == 2039284 * KB_UNIT_KRW
        assert KB_UNIT_KRW == 1_000_000

    def test_foreign_total_includes_native_foreigner(self):
        """★관례차 2 — pykrx 외국인합계 == KB fgnr + ntv_fgnr(내외국인)."""
        row = _kb_rows_by_date([self.REC])["20260806"]
        assert row["foreign"] == (-1693585 + 16486) * KB_UNIT_KRW
        assert row["foreign_narrow"] == -1693585 * KB_UNIT_KRW
        assert row["foreign"] != row["foreign_narrow"]  # 혼동하면 조용히 틀린 값

    def test_estimate_rows_excluded(self):
        """mtrl_clsf=1(추정치)은 대조·통합 대상이 아니다(확정치만)."""
        est = dict(self.REC, mtrl_clsf="1", dt="20260807")
        rows = _kb_rows_by_date([self.REC, est])
        assert set(rows) == {"20260806"}

    def test_details_also_scaled(self):
        row = _kb_rows_by_date([self.REC])["20260806"]
        assert row["details"]["증권"] == -100000 * KB_UNIT_KRW
        assert row["details"]["프로그램"] == -500 * KB_UNIT_KRW
