// ATLAS — Tabs C: Portfolio
// PR-4: 포트폴리오 탭 — GET/POST/DELETE /api/portfolio (127.0.0.1:8765)
// 투자 자문 아님 / 원금 손실 가능

import { useState, useEffect, useCallback } from 'react';
import { C, MonoCaps, Num, ChangePct, HoldDot, fmtPrice, btnGhost } from './ui.jsx';
import { Panel } from './tabsA.jsx';

const API = "http://127.0.0.1:8765";

function fmtMoney(v, currency) {
  if (v == null) return "—";
  if (currency === "USD") return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  return "₩" + Math.round(v).toLocaleString("ko-KR");
}

// PR-3: KRW 전체 숫자(만/억 축약 금지)
function fmtKrwFull(v) {
  if (v == null) return "—";
  return "₩" + Math.round(v).toLocaleString("ko-KR");
}

function PnlCell({ pnl, pnl_pct, currency }) {
  if (pnl == null) return <span style={{ color: C.ink3 }}>—</span>;
  const pos = pnl >= 0;
  const col = pos ? C.ok : C.bad;
  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 700, color: col }}>
        {pnl >= 0 ? "+" : ""}{fmtMoney(pnl, currency)}
      </div>
      {pnl_pct != null && (
        <div style={{ fontSize: 11.5, fontWeight: 700, color: col }}>
          ({pnl_pct >= 0 ? "+" : ""}{pnl_pct.toFixed(2)}%)
        </div>
      )}
    </div>
  );
}

// ── 포트폴리오 탭 ──────────────────────────────────────────────────
export function Portfolio({ D, nav }) {
  const [rows, setRows] = useState(null);  // null = 로딩중
  const [error, setError] = useState(null);
  const [form, setForm] = useState({ ticker: "", qty: "", avg_price: "", currency: "KRW" });  // PR-4: 기본 미선택
  const [saving, setSaving] = useState(false);
  const [apiOk, setApiOk] = useState(true);

  const loadPortfolio = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/portfolio`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setRows(await res.json());
      setApiOk(true);
    } catch (e) {
      setApiOk(false);
      setError("데이터 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.");
    }
  }, []);

  useEffect(() => { loadPortfolio(); }, [loadPortfolio]);

  // PR-4: 종목 미선택 / 수량·평단가 0 이하면 저장 비활성
  const formValid = form.ticker && parseFloat(form.qty) > 0 && parseFloat(form.avg_price) > 0;

  const handleSave = async () => {
    if (!formValid) return;
    setSaving(true);
    try {
      await fetch(`${API}/api/portfolio`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: form.ticker, qty: parseFloat(form.qty), avg_price: parseFloat(form.avg_price), currency: form.currency }),
      });
      await loadPortfolio();
      setForm((f) => ({ ...f, qty: "", avg_price: "" }));
    } catch (_) {}
    setSaving(false);
  };

  const handleDelete = async (ticker) => {
    const nm = D.stocks.find((s) => s.t === ticker)?.name || ticker;
    if (!confirm(`'${nm}(${ticker})' 보유 종목을 삭제할까요? 되돌릴 수 없습니다.`)) return;
    await fetch(`${API}/api/portfolio/${ticker}`, { method: "DELETE" });
    await loadPortfolio();
  };

  // PR-3: USD→KRW 환산 후 합계. 환율은 data.json portfolio.fx_rate, 없으면 시장 USD/KRW.
  const fxFromMarket = (() => {
    const ix = D.market?.indices?.find((x) => x.k === "USD/KRW");
    if (!ix || !ix.v) return null;
    const num = parseFloat(String(ix.v).replace(/,/g, ""));
    return Number.isFinite(num) ? num : null;
  })();
  const fx = D.portfolio?.fx_rate || fxFromMarket;
  const toKrw = (amt, ccy) => (ccy === "USD" ? (fx ? amt * fx : null) : amt);

  let totalEvalKrw = 0, totalPnlKrw = 0, fxMissing = false;
  (rows || []).forEach((r) => {
    const ev = toKrw(r.eval_amount || 0, r.currency);
    const pn = toKrw(r.pnl || 0, r.currency);
    if (ev == null || pn == null) { fxMissing = true; return; }
    totalEvalKrw += ev; totalPnlKrw += pn;
  });
  const totalCostKrw = totalEvalKrw - totalPnlKrw;
  const totalPnlPct = totalCostKrw > 0 ? (totalPnlKrw / totalCostKrw) * 100 : null;

  if (!apiOk) return (
    <div style={{ background: C.warnBg, border: `1px solid ${C.warn}33`, borderRadius: 10, padding: "24px 28px" }}>
      <div style={{ fontSize: 14.5, fontWeight: 700, color: C.warn, marginBottom: 8 }}>데이터 서버에 연결할 수 없습니다</div>
      <div style={{ fontSize: 13, color: C.ink2, lineHeight: 1.6 }}>
        포트폴리오 기능을 사용하려면 데이터 서버 연결이 필요합니다. 잠시 후 다시 시도해 주세요.
      </div>
      <button onClick={loadPortfolio} style={{ marginTop: 14, border: `1px solid ${C.warn}`, background: C.warnBg, color: C.warn, borderRadius: 7, padding: "7px 16px", fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>다시 연결</button>
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 12.5, fontWeight: 700, color: C.ink }}>포트폴리오</span>
        <MonoCaps style={{ fontSize: 9 }} color={C.ink3}>투자 자문 아님 / 원금 손실 가능</MonoCaps>
      </div>

      {/* 합계 (PR-3: ₩ 환산 전체 숫자) */}
      {rows && rows.length > 0 && (
        <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10, padding: "14px 22px" }}>
          <div style={{ display: "flex", gap: 32, alignItems: "flex-end" }}>
            <div>
              <MonoCaps style={{ fontSize: 9 }}>총 평가금액 (₩ 환산)</MonoCaps>
              <Num size={22} weight={800} style={{ marginTop: 4, textDecoration: "none" }}>{fmtKrwFull(totalEvalKrw)}</Num>
            </div>
            <div style={{ width: 1, height: 36, background: C.line2 }}></div>
            <div>
              <MonoCaps style={{ fontSize: 9 }}>총 손익 (₩ 환산)</MonoCaps>
              <div style={{ marginTop: 4 }}>
                <Num size={22} weight={800} color={totalPnlKrw >= 0 ? C.ok : C.bad} style={{ textDecoration: "none" }}>
                  {totalPnlKrw >= 0 ? "+" : ""}{fmtKrwFull(totalPnlKrw)}
                </Num>
                {totalPnlPct != null && (
                  <span style={{ marginLeft: 8, fontSize: 13, fontWeight: 700, color: totalPnlKrw >= 0 ? C.ok : C.bad }}>
                    ({totalPnlPct >= 0 ? "+" : ""}{totalPnlPct.toFixed(2)}%)
                  </span>
                )}
              </div>
            </div>
            <div style={{ marginLeft: "auto", textAlign: "right" }}>
              <MonoCaps style={{ fontSize: 9 }}>{rows.length}종목 보유</MonoCaps>
            </div>
          </div>
          <div style={{ marginTop: 8, fontSize: 10.5, color: C.ink3 }}>
            {fx ? `적용 환율 USD/KRW ${Math.round(fx).toLocaleString("ko-KR")} · USD 보유는 환산 반영` : "환율 데이터 없음 — KRW 종목만 합산"}
            {fxMissing && " · 일부 USD 포지션 환산 제외"}
          </div>
        </div>
      )}

      {/* 보유 테이블 */}
      <Panel title="보유종목" sub={rows == null ? "로딩중…" : `${rows.length}건`}>
        {rows == null ? (
          <div style={{ padding: 32, textAlign: "center", color: C.ink3 }}>로딩중…</div>
        ) : rows.length === 0 ? (
          <div style={{ padding: 32, textAlign: "center", color: C.ink3 }}>보유종목이 없습니다. 아래 폼에서 추가하세요.</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${C.line2}` }}>
                {["종목", "수량", "평단가", "현재가", "평가금액", "손익", ""].map((h, i) => (
                  <th key={i} style={{ textAlign: "left", padding: "9px 14px" }}>
                    <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{h}</MonoCaps>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const s = D.stocks.find((x) => x.t === r.ticker);
                return (
                  <tr key={r.ticker} className="row-hover" style={{ borderBottom: `1px solid ${C.line}` }}>
                    <td style={{ padding: "11px 14px" }}>
                      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        <button onClick={() => nav(r.ticker)} style={{ ...btnGhost, padding: 0, fontSize: 13.5, fontWeight: 700, color: C.ink, textAlign: "left" }}>
                          {s?.name || r.ticker}
                        </button>
                        <span className="mono" style={{ fontSize: 10, color: C.ink3 }}>{r.ticker} · {r.currency}</span>
                      </div>
                    </td>
                    <td style={{ padding: "11px 14px" }}><Num size={13} weight={600} style={{ textDecoration: "none" }}>{r.qty}</Num></td>
                    <td style={{ padding: "11px 14px" }}><Num size={13} weight={600} style={{ textDecoration: "none" }}>{fmtMoney(r.avg_price, r.currency)}</Num></td>
                    <td style={{ padding: "11px 14px" }}><Num size={13} weight={600} style={{ textDecoration: "none" }}>{r.cur_price != null ? fmtMoney(r.cur_price, r.currency) : "—"}</Num></td>
                    <td style={{ padding: "11px 14px" }}><Num size={13} weight={600} style={{ textDecoration: "none" }}>{fmtMoney(r.eval_amount, r.currency)}</Num></td>
                    <td style={{ padding: "11px 14px" }}><PnlCell pnl={r.pnl} pnl_pct={r.pnl_pct} currency={r.currency} /></td>
                    <td style={{ padding: "11px 14px" }}>
                      <button onClick={() => handleDelete(r.ticker)} style={{ border: `1px solid ${C.line2}`, background: C.surface, color: C.bad, borderRadius: 6, padding: "4px 10px", fontSize: 11.5, fontWeight: 600, cursor: "pointer" }}>삭제</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Panel>

      {/* 추가/수정 폼 */}
      <Panel title="보유 추가 / 수정">
        <div style={{ padding: "16px 18px", display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 5, minWidth: 200 }}>
            <MonoCaps style={{ fontSize: 9.5 }}>종목</MonoCaps>
            <select
              value={form.ticker}
              onChange={(e) => setForm((f) => ({ ...f, ticker: e.target.value }))}
              style={{ border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 13, fontFamily: "var(--sans)", color: form.ticker ? C.ink : C.ink3, background: C.surface, cursor: "pointer", outline: "none" }}
            >
              <option value="">선택하세요</option>
              {D.stocks.map((s) => <option key={s.t} value={s.t}>{s.name} ({s.t})</option>)}
            </select>
          </div>
          {[["수량", "qty", "예: 10", "number"], ["평단가", "avg_price", "예: 50000", "number"]].map(([label, key, ph, type]) => (
            <div key={key} style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <MonoCaps style={{ fontSize: 9.5 }}>{label}</MonoCaps>
              <input
                type={type} placeholder={ph} value={form[key]}
                onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                style={{ border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 13, width: 140, outline: "none", fontFamily: "var(--sans)", color: C.ink }}
              />
            </div>
          ))}
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <MonoCaps style={{ fontSize: 9.5 }}>통화</MonoCaps>
            <select
              value={form.currency}
              onChange={(e) => setForm((f) => ({ ...f, currency: e.target.value }))}
              style={{ border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 13, fontFamily: "var(--sans)", color: C.ink, background: C.surface, cursor: "pointer", outline: "none" }}
            >
              <option value="KRW">KRW</option>
              <option value="USD">USD</option>
            </select>
          </div>
          <button
            onClick={handleSave}
            disabled={saving || !formValid}
            style={{ background: C.ink, color: "#fff", border: "none", borderRadius: 7, padding: "10px 22px", fontSize: 13, fontWeight: 600, cursor: (saving || !formValid) ? "default" : "pointer", opacity: (saving || !formValid) ? 0.45 : 1 }}
          >
            {saving ? "저장 중…" : "저장"}
          </button>
        </div>
      </Panel>
    </div>
  );
}
