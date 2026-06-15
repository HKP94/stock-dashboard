// ATLAS — Tabs E: 관심종목 관리 (PR-3)
// 대시보드에서 종목 추가/제외(SQL 없이). 로컬 API(127.0.0.1:8765) 연동.
import { useState, useEffect, useCallback } from 'react';
import { C, MonoCaps, Num, HoldDot, btnGhost } from './ui.jsx';
import { Panel } from './tabsA.jsx';

const API = "http://127.0.0.1:8765";

export function WatchlistAdmin({ D }) {
  const [list, setList] = useState(null);     // null=로딩
  const [apiOk, setApiOk] = useState(true);
  const [form, setForm] = useState({ ticker: "", name: "", market: "US", sector: "" });
  const [adding, setAdding] = useState(false);
  const [msg, setMsg] = useState("");
  const [collecting, setCollecting] = useState([]);  // 수집 중 티커

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/watchlist`);
      if (!res.ok) throw new Error();
      setList(await res.json());
      setApiOk(true);
    } catch (_) { setApiOk(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleAdd = async () => {
    if (!form.ticker.trim() || !form.name.trim()) return;
    setAdding(true); setMsg("");
    try {
      const res = await fetch(`${API}/api/watchlist`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const j = await res.json();
      const tk = form.ticker.trim();
      setMsg(`'${form.name}' 추가됨 — 데이터 수집 중입니다. 잠시 후 랭킹에 등장합니다.`);
      setCollecting((c) => [...c, tk]);
      setForm({ ticker: "", name: "", market: "US", sector: "" });
      await load();
      // 30초 후 수집 완료 가정 표시 해제 + 재조회
      setTimeout(async () => { setCollecting((c) => c.filter((x) => x !== tk)); await load(); }, 30000);
    } catch (_) { setMsg("추가 실패 — 잠시 후 다시 시도해 주세요."); }
    setAdding(false);
  };

  const toggleActive = async (ticker, next) => {
    await fetch(`${API}/api/watchlist/${ticker}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active: next }),
    });
    await load();
  };

  if (!apiOk) return (
    <div style={{ background: C.warnBg, border: `1px solid ${C.warn}33`, borderRadius: 10, padding: "24px 28px" }}>
      <div style={{ fontSize: 14.5, fontWeight: 700, color: C.warn, marginBottom: 8 }}>데이터 서버에 연결할 수 없습니다</div>
      <div style={{ fontSize: 13, color: C.ink2 }}>관심종목 관리는 데이터 서버 연결이 필요합니다. 잠시 후 다시 시도해 주세요.</div>
      <button onClick={load} style={{ marginTop: 14, border: `1px solid ${C.warn}`, background: C.warnBg, color: C.warn, borderRadius: 7, padding: "7px 16px", fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>다시 연결</button>
    </div>
  );

  const active = (list || []).filter((w) => w.active);
  const inactive = (list || []).filter((w) => !w.active);

  const Row = ({ w }) => (
    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 16px", borderBottom: `1px solid ${C.line}` }}>
      <HoldDot on={w.is_holding} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <span style={{ fontSize: 13.5, fontWeight: 700, color: C.ink }}>{w.name}</span>
        <span className="mono" style={{ fontSize: 10, color: C.ink3, marginLeft: 7 }}>{w.ticker} · {w.market}{w.sector ? " · " + w.sector : ""}</span>
      </div>
      {collecting.includes(w.ticker) || !w.has_data ? (
        <span style={{ fontSize: 10.5, fontWeight: 700, color: C.warn, background: C.warnBg, border: `1px solid ${C.warn}33`, borderRadius: 5, padding: "2px 8px" }}>데이터 수집 중</span>
      ) : (
        <span style={{ fontSize: 10.5, fontWeight: 600, color: C.ok }}>준비됨</span>
      )}
      {/* active 토글 스위치 */}
      <button onClick={() => toggleActive(w.ticker, !w.active)}
        title={w.active ? "관심 제외(데이터 보존)" : "관심 추가"}
        style={{ width: 44, height: 24, borderRadius: 999, border: "none", cursor: "pointer", position: "relative",
          background: w.active ? C.acc : C.line2, transition: "background .15s" }}>
        <span style={{ position: "absolute", top: 3, left: w.active ? 23 : 3, width: 18, height: 18, borderRadius: 999, background: "#fff", transition: "left .15s" }}></span>
      </button>
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 12.5, fontWeight: 700, color: C.ink }}>관심종목 관리</span>
        <MonoCaps style={{ fontSize: 9 }} color={C.ink3}>대시보드에서 직접 추가·제외</MonoCaps>
      </div>

      {/* 추가 폼 */}
      <Panel title="종목 추가" sub="추가 즉시 데이터 수집(가격·지표·퀀트)">
        <div style={{ padding: "16px 18px", display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
          {[["티커", "ticker", "예: TSLA / 005930.KS"], ["종목명", "name", "예: 테슬라"], ["섹터", "sector", "예: 자동차(선택)"]].map(([label, key, ph]) => (
            <div key={key} style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <MonoCaps style={{ fontSize: 9.5 }}>{label}</MonoCaps>
              <input value={form[key]} placeholder={ph}
                onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                style={{ border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 13, width: key === "ticker" ? 170 : 150, outline: "none", fontFamily: "var(--sans)", color: C.ink }} />
            </div>
          ))}
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <MonoCaps style={{ fontSize: 9.5 }}>시장</MonoCaps>
            <select value={form.market} onChange={(e) => setForm((f) => ({ ...f, market: e.target.value }))}
              style={{ border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 13, fontFamily: "var(--sans)", color: C.ink, background: C.surface, cursor: "pointer", outline: "none" }}>
              <option value="US">US</option>
              <option value="KR">KR</option>
            </select>
          </div>
          <button onClick={handleAdd} disabled={adding || !form.ticker.trim() || !form.name.trim()}
            style={{ background: C.ink, color: "#fff", border: "none", borderRadius: 7, padding: "10px 22px", fontSize: 13, fontWeight: 600,
              cursor: (adding || !form.ticker.trim() || !form.name.trim()) ? "default" : "pointer", opacity: (adding || !form.ticker.trim() || !form.name.trim()) ? 0.45 : 1 }}>
            {adding ? "추가 중…" : "추가"}
          </button>
        </div>
        {msg && <div style={{ padding: "0 18px 14px", fontSize: 12, color: C.acc }}>{msg}</div>}
      </Panel>

      {/* 활성 목록 */}
      <Panel title="관심종목" sub={`${active.length}종목 · 활성`}>
        {list == null ? <div style={{ padding: 32, textAlign: "center", color: C.ink3 }}>로딩중…</div>
          : active.length === 0 ? <div style={{ padding: 32, textAlign: "center", color: C.ink3 }}>관심종목이 없습니다.</div>
          : active.map((w) => <Row key={w.ticker} w={w} />)}
      </Panel>

      {/* 비활성 목록 */}
      {inactive.length > 0 && (
        <Panel title="제외된 종목" sub={`${inactive.length}종목 · 비활성(데이터 보존)`}>
          {inactive.map((w) => <Row key={w.ticker} w={w} />)}
        </Panel>
      )}
    </div>
  );
}
