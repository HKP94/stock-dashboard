"""KB증권 OpenAPI 잔고 자동화 — 클라이언트 가드·토큰·매핑·전량 스왑 테스트.

전부 모킹. 실계좌/실API 호출 테스트는 금지(키 노출·쿼터·부작용).
"""
from __future__ import annotations

import pytest

from src import collect_kb_portfolio as kbp
from src import kb_client


# ── 주문 API 차단 가드 (절대 규칙) ────────────────────────────────────────────
class TestOrderAPIBlocked:
    """CLAUDE.md §0 자동 주문 금지 — 주문 계열 코드는 호출 자체가 예외여야 한다."""

    ORDER_CODES = [
        "ssam1801", "ssam1802", "ssam1805", "ssam1806",   # 국내 매도/매수/정정/취소
        "ssam0831", "ssam5762", "ssam5763", "ssam5764",   # 예약·소수점 주문
        "skam2101", "skam2102", "skam2201", "skam2202",   # 해외 주문·정정·취소
        "spao2104", "spao2106",                           # 해외 예약주문
    ]

    @pytest.mark.parametrize("code", ORDER_CODES)
    def test_order_api_raises(self, code, monkeypatch):
        # 네트워크가 열려 있어도 도달하기 전에 차단돼야 한다.
        monkeypatch.setattr(kb_client, "_get_token", lambda force=False: "tok")
        with pytest.raises(kb_client.KBOrderAPIBlocked):
            kb_client.call(code, {})

    @pytest.mark.parametrize("code", ORDER_CODES)
    def test_order_api_not_whitelisted(self, code):
        assert code not in kb_client.ALLOWED_APIS

    def test_case_and_space_insensitive(self, monkeypatch):
        monkeypatch.setattr(kb_client, "_get_token", lambda force=False: "tok")
        with pytest.raises(kb_client.KBOrderAPIBlocked):
            kb_client.call("  SSAM1802 ", {})

    def test_whitelist_is_query_only(self):
        """화이트리스트에 주문 계열 접두사가 새로 들어오면 실패."""
        for code in kb_client.ALLOWED_APIS:
            assert not code.startswith(("ssam", "skam", "spao")), code


# ── 토큰 발급·캐시·재발급 ─────────────────────────────────────────────────────
class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


def _token_payload(token="tok-1", expires=86400):
    return {"dataHeader": {"processFlag": "A"},
            "dataBody": {"access_token": token, "token_type": "Bearer", "expires_in": expires}}


def _ok_body(body):
    return {"dataHeader": {"processFlag": "A", "processCode": "0011"}, "dataBody": body}


@pytest.fixture(autouse=True)
def _clean_token(monkeypatch):
    monkeypatch.setenv("KB_APP_KEY", "K" * 36)
    monkeypatch.setenv("KB_APP_SECRET", "S" * 32)
    kb_client._TOKEN.update({"value": None, "exp": 0.0})
    kb_client._DATA_HEADER.clear()
    kb_client._DATA_HEADER.update({"ipAddr": "127.0.0.1", "macAddr": "AABBCCDDEEFF"})
    yield
    kb_client._TOKEN.update({"value": None, "exp": 0.0})


class TestToken:
    def test_issue_and_cache(self, monkeypatch):
        calls = []

        def fake_post(url, **kw):
            calls.append(url)
            return _Resp(payload=_token_payload())

        monkeypatch.setattr(kb_client.requests, "post", fake_post)
        assert kb_client._get_token() == "tok-1"
        assert kb_client._get_token() == "tok-1"
        assert len(calls) == 1  # 캐시 적중

    def test_envelope_used(self, monkeypatch):
        """토큰 요청은 dataHeader/dataBody 봉투여야 한다(평면 body는 500 E021)."""
        seen = {}

        def fake_post(url, **kw):
            seen.update(kw["json"])
            return _Resp(payload=_token_payload())

        monkeypatch.setattr(kb_client.requests, "post", fake_post)
        kb_client._get_token()
        assert "dataBody" in seen and seen["dataBody"]["grantType"] == "client_credentials"

    def test_expiry_triggers_reissue(self, monkeypatch):
        tokens = iter(["tok-1", "tok-2"])
        monkeypatch.setattr(
            kb_client.requests, "post",
            lambda url, **kw: _Resp(payload=_token_payload(next(tokens), expires=1)),
        )
        assert kb_client._get_token() == "tok-1"
        # expires_in=1 → 만료 60초 여유 규칙에 걸려 즉시 재발급
        assert kb_client._get_token() == "tok-2"

    def test_401_reissues_token_and_retries(self, monkeypatch):
        tokens = iter(["stale", "fresh"])
        seen_auth = []

        def fake_post(url, **kw):
            if url.endswith("/oauth2/token"):
                return _Resp(payload=_token_payload(next(tokens)))
            seen_auth.append(kw["headers"]["Authorization"])
            if len(seen_auth) == 1:
                return _Resp(status=401, text="expired")
            return _Resp(payload=_ok_body({"ok": 1}))

        monkeypatch.setattr(kb_client.requests, "post", fake_post)
        assert kb_client.call("ssqm0004", {}) == {"ok": 1}
        assert seen_auth == ["bearer stale", "bearer fresh"]

    def test_secrets_never_leak_in_errors(self, monkeypatch):
        secret = "S" * 32
        monkeypatch.setattr(
            kb_client.requests, "post",
            lambda url, **kw: _Resp(status=500, text=f"bad key for {secret}"),
        )
        with pytest.raises(kb_client.KBApiError) as exc:
            kb_client._get_token()
        assert secret not in str(exc.value)
        assert "***SSSS" in str(exc.value)


class TestCall:
    def test_business_error_raises(self, monkeypatch):
        monkeypatch.setattr(kb_client, "_get_token", lambda force=False: "tok")
        monkeypatch.setattr(
            kb_client.requests, "post",
            lambda url, **kw: _Resp(payload={
                "dataHeader": {"processFlag": "B", "processCode": "9999",
                               "processMessage": "입력 전문 확인"},
                "dataBody": {}}),
        )
        with pytest.raises(kb_client.KBApiError):
            kb_client.call("ssqm2952", {})

    def test_empty_result_is_not_an_error(self, monkeypatch):
        """조회 0건(processFlag=A)은 정상 — 호출부가 판단한다."""
        monkeypatch.setattr(kb_client, "_get_token", lambda force=False: "tok")
        monkeypatch.setattr(
            kb_client.requests, "post",
            lambda url, **kw: _Resp(payload=_ok_body({"Record1": []})),
        )
        assert kb_client.call("ssqm2952", {}) == {"Record1": []}

    def test_5xx_retries_then_fails(self, monkeypatch):
        monkeypatch.setattr(kb_client, "_get_token", lambda force=False: "tok")
        monkeypatch.setattr(kb_client.time, "sleep", lambda s: None)
        n = []
        monkeypatch.setattr(
            kb_client.requests, "post",
            lambda url, **kw: (n.append(1), _Resp(status=503, text="boom"))[1],
        )
        with pytest.raises(kb_client.KBApiError):
            kb_client.call("ssqm0004", {})
        assert len(n) == kb_client.RETRIES  # 무한재시도 금지


# ── 파싱·매핑 ────────────────────────────────────────────────────────────────
class TestParsing:
    @pytest.mark.parametrize("raw,expected", [
        ("005930", "005930"), ("A005930", "005930"), ("KR7005930003", "005930"),
        ("  085670 ", "085670"),
    ])
    def test_domestic_code(self, raw, expected):
        assert kbp._domestic_code(raw) == expected

    def test_num_handles_padding_and_blanks(self):
        assert kbp._num("000000000000000024") == 24.0
        assert kbp._num("   ") == 0.0
        assert kbp._num(None) == 0.0

    def test_qty_sums_fractional_shares(self):
        # 10주 + 0.5주, 현재가 100 → 평가 1050
        assert kbp._qty(10.0, 0.5, 1050.0, 100.0) == pytest.approx(10.5)

    def test_qty_avoids_double_count_when_p6_is_total(self):
        # p6가 '전체수량'인 계좌: 평가금액÷현재가가 10.5라 합산(20.5)이 아닌 10.5를 고른다
        assert kbp._qty(10.0, 10.5, 1050.0, 100.0) == pytest.approx(10.5)

    def test_qty_falls_back_to_sum_without_price(self):
        assert kbp._qty(10.0, 0.5, 0.0, 0.0) == pytest.approx(10.5)


def _raw(domestic_recs=(), overseas_recs=(), ccy_recs=(), krw="000000004363639"):
    return {
        "domestic": {"Record1": list(domestic_recs)},
        "overseas": {"Record1": list(ccy_recs), "Record2": list(overseas_recs)},
        "cash": {"nxt2_dy_tfnd": krw},
    }


DOM_SAMSUNG = {"is_cd": "005930", "is_nm": "삼성전자", "hld_q": "000000000000000006",
               "hld_q_p6": "0000000.000000", "byng_avr_prc": "0000000000246792",
               "now_prc": "0000000000250000", "val_amt": "000000000001500000",
               "is_dtl_typ_cd": "11"}
DOM_NEWFLEX = {"is_cd": "A085670", "is_nm": "뉴프렉스", "hld_q": "000000000000000101",
               "hld_q_p6": "0000000.000000", "byng_avr_prc": "0000000000002870",
               "now_prc": "0000000000003000", "val_amt": "000000000000303000",
               "is_dtl_typ_cd": "12"}
OVS_MSFT = {"is_cd": "MSFT", "is_nm": "MICROSOFT", "crncy_clsf_nm": "USD",
            "frgn_hld_q_p6": "00000001.000000", "byng_avr_prc_p4": "00000000490.0000"}


class TestBuildRows:
    def test_watchlist_mapping_wins(self):
        holdings, _cash, unresolved = kbp.build_rows(
            _raw([DOM_SAMSUNG]), {"005930": "005930.KS"}
        )
        assert [h["ticker"] for h in holdings] == ["005930.KS"]
        assert holdings[0]["qty"] == pytest.approx(6.0)
        assert holdings[0]["avg_price"] == pytest.approx(246792.0)
        assert unresolved == []

    def test_kosdaq_suffix_from_detail_type_without_extra_call(self):
        """watchlist 미등록도 잔고 응답의 종목세부유형코드(12=코스닥)로 해결 — 추가 호출 없음."""
        holdings, _c, unresolved = kbp.build_rows(_raw([DOM_NEWFLEX]), {})
        assert [h["ticker"] for h in holdings] == ["085670.KQ"]
        assert unresolved == []

    def test_unknown_market_goes_to_unresolved(self, monkeypatch):
        monkeypatch.setattr(kb_client, "call", lambda *a, **k: {"is_dtl_typ_cd": "10"})
        rec = dict(DOM_NEWFLEX, is_dtl_typ_cd="  ")
        holdings, _c, unresolved = kbp.build_rows(_raw([rec]), {})
        assert holdings == []
        assert len(unresolved) == 1 and "085670" in unresolved[0]

    def test_overseas_symbol_kept_as_is(self):
        holdings, cash, unresolved = kbp.build_rows(
            _raw(overseas_recs=[OVS_MSFT],
                 ccy_recs=[{"crncy_clsf_nm": "USD", "tfnd": "0000000000012.34"}]), {}
        )
        assert holdings[0] == {"ticker": "MSFT", "qty": 1.0, "avg_price": 490.0,
                               "currency": "USD", "name": "MICROSOFT"}
        assert cash["USD"] == pytest.approx(12.34)
        assert cash["KRW"] == pytest.approx(4363639)
        assert unresolved == []

    def test_non_usd_market_is_unresolved(self):
        rec = dict(OVS_MSFT, is_cd="7203", crncy_clsf_nm="JPY")
        holdings, _c, unresolved = kbp.build_rows(_raw(overseas_recs=[rec]), {})
        assert holdings == [] and "JPY" in unresolved[0]

    def test_zero_qty_rows_dropped(self):
        rec = dict(DOM_SAMSUNG, hld_q="000000000000000000", hld_q_p6="0000000.000000",
                   val_amt="000000000000000000")
        holdings, _c, unresolved = kbp.build_rows(_raw([rec]), {"005930": "005930.KS"})
        assert holdings == [] and unresolved == []


# ── 전량 스왑 + 안전장치 ─────────────────────────────────────────────────────
class _Cur:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.sql.append((" ".join(sql.split()), params))
        s = sql.strip().upper()
        if s.startswith("SELECT TICKER FROM WATCHLIST"):
            self._rows = [{"ticker": t} for t in self.conn.known]
        elif "FROM PORTFOLIO_HOLDINGS" in s and s.startswith("SELECT"):
            self._rows = [dict(r) for r in self.conn.holdings]
        elif "FROM PORTFOLIO_CASH" in s and s.startswith("SELECT"):
            self._rows = [dict(r) for r in self.conn.cash]
        else:
            self._rows = []

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, known=(), holdings=(), cash=()):
        self.known, self.holdings, self.cash = list(known), list(holdings), list(cash)
        self.sql: list = []
        self.committed = False

    def cursor(self):
        return _Cur(self)

    def commit(self):
        self.committed = True


def _writes(conn, keyword):
    return [s for s, _p in conn.sql if s.upper().startswith(keyword)]


@pytest.fixture
def _stub_fetch(monkeypatch):
    def _set(raw):
        monkeypatch.setattr(kbp, "fetch_raw", lambda: raw)
    return _set


class TestSwap:
    def _conn(self):
        return _Conn(
            known=["005930.KS", "085670.KQ"],
            holdings=[{"ticker": "005930.KS", "qty": 6, "avg_price": 246792, "currency": "KRW"},
                      {"ticker": "001450.KS", "qty": 24, "avg_price": 38429, "currency": "KRW"},
                      {"ticker": "MSFT", "qty": 1, "avg_price": 490, "currency": "USD"}],
            cash=[{"currency": "KRW", "amount": 4363639}],
        )

    def test_removes_holdings_absent_from_kb(self, _stub_fetch):
        _stub_fetch(_raw([DOM_SAMSUNG], [OVS_MSFT]))
        conn = self._conn()
        report = kbp.run(conn)
        assert report["applied"] is True
        assert report["removed"] == ["001450.KS"]          # 매도 반영
        assert _writes(conn, "DELETE")                      # 실제 삭제 SQL 발행
        assert conn.committed

    def test_empty_response_skips_delete(self, _stub_fetch):
        """API 오류로 보유 0건이 오면 DB를 전멸시키지 않는다."""
        _stub_fetch(_raw())
        conn = self._conn()
        report = kbp.run(conn)
        assert report["skipped"] == "empty_response"
        assert report["applied"] is False
        assert not _writes(conn, "DELETE") and not _writes(conn, "INSERT")

    def test_unresolved_blocks_delete_but_upserts(self, _stub_fetch, monkeypatch):
        monkeypatch.setattr(kb_client, "call", lambda *a, **k: {"is_dtl_typ_cd": "10"})
        # 코넥스 등 .KS/.KQ로 못 붙이는 종목(watchlist·기존보유에도 없음)
        _stub_fetch(_raw([DOM_SAMSUNG, dict(DOM_NEWFLEX, is_cd="140610", is_dtl_typ_cd=" ")]))
        conn = self._conn()
        report = kbp.run(conn)
        assert report["unresolved"] and report["applied"] is True
        assert _writes(conn, "INSERT") and not _writes(conn, "DELETE")

    def test_dry_run_never_writes(self, _stub_fetch, capsys):
        _stub_fetch(_raw([DOM_SAMSUNG], [OVS_MSFT]))
        conn = self._conn()
        report = kbp.run(conn, dry_run=True)
        assert report["dry_run"] is True and report["applied"] is False
        assert not _writes(conn, "INSERT") and not _writes(conn, "DELETE")
        assert not conn.committed
        out = capsys.readouterr().out
        assert "001450.KS" in out and "제거" in out

    def test_cash_upserted_per_currency(self, _stub_fetch):
        _stub_fetch(_raw([DOM_SAMSUNG], [OVS_MSFT],
                         ccy_recs=[{"crncy_clsf_nm": "USD", "tfnd": "0000000000100.00"}]))
        conn = self._conn()
        kbp.run(conn)
        cash_params = [p for s, p in conn.sql if "PORTFOLIO_CASH" in s.upper() and s.upper().startswith("INSERT")]
        assert dict((p[0], p[1]) for p in cash_params) == {"KRW": 4363639.0, "USD": 100.0}

    def test_skips_without_credentials(self, monkeypatch):
        monkeypatch.delenv("KB_APP_KEY", raising=False)
        conn = self._conn()
        assert kbp.run(conn)["skipped"] == "no_credentials"
        assert conn.sql == []
