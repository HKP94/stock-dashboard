// ATLAS — Tabs C: Portfolio
// PR-4: 포트폴리오 탭 — GET/POST/DELETE /api/portfolio (127.0.0.1:8765)

import { useState, useEffect, useCallback } from 'react';
import { C, MonoCaps, Num, ChangePct, HoldDot, fmtPrice, btnGhost } from './ui.jsx';
import { Panel } from './tabsA.jsx';
import { portfolioAssetTotal } from './display.js';

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
  // PR-2: 현금
  const [cashRows, setCashRows] = useState([]);
  const [cashForm, setCashForm] = useState({ currency: "KRW", amount: "" });
  const [cashSaving, setCashSaving] = useState(false);
  const [summary, setSummary] = useState(D.portfolio || null);

  const loadPortfolio = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/portfolio`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setRows(await res.json());
      try {
        const cr = await fetch(`${API}/api/cash`);
        if (cr.ok) setCashRows(await cr.json());
      } catch (_) {}
      try {
        const sr = await fetch(`${API}/api/portfolio/summary`);
        if (sr.ok) setSummary(await sr.json());
      } catch (_) {}
      setApiOk(true);
    } catch (e) {
      setApiOk(false);
      setError("데이터 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.");
    }
  }, []);

  useEffect(() => { loadPortfolio(); }, [loadPortfolio]);

  const handleSaveCash = async () => {
    if (parseFloat(cashForm.amount) < 0 || cashForm.amount === "") return;
    setCashSaving(true);
    try {
      await fetch(`${API}/api/cash`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ currency: cashForm.currency, amount: parseFloat(cashForm.amount) }),
      });
      await loadPortfolio();
      setCashForm((f) => ({ ...f, amount: "" }));
    } catch (_) {}
    setCashSaving(false);
  };

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

  // PR-2: 현금 KRW 환산 + 총자산(주식 + 현금)
  let cashKrw = 0;
  (cashRows || []).forEach((c) => {
    const k = toKrw(c.amount || 0, c.currency);
    if (k != null) cashKrw += k;
  });
  const assetTotalKrw = portfolioAssetTotal(summary) ?? (totalEvalKrw + cashKrw);
  const hasAny = (rows && rows.length > 0) || cashKrw > 0;

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
        <MonoCaps style={{ fontSize: 9 }} color={C.ink3}>보유 현황과 전략 분석</MonoCaps>
      </div>

      {/* 합계 (PR-2: 주식 / 현금 / 총자산 분리, ₩ 환산 전체 숫자) */}
      {hasAny && (
        <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10, padding: "14px 22px" }}>
          <div style={{ display: "flex", gap: 28, alignItems: "flex-end", flexWrap: "wrap" }}>
            <div>
              <MonoCaps style={{ fontSize: 9 }}>주식 평가액 (₩)</MonoCaps>
              <Num size={20} weight={800} style={{ marginTop: 4, textDecoration: "none" }}>{fmtKrwFull(totalEvalKrw)}</Num>
            </div>
            <div style={{ fontSize: 18, color: C.ink3, paddingBottom: 2 }}>+</div>
            <div>
              <MonoCaps style={{ fontSize: 9 }}>현금 (₩)</MonoCaps>
              <Num size={20} weight={800} color={C.ink2} style={{ marginTop: 4, textDecoration: "none" }}>{fmtKrwFull(cashKrw)}</Num>
            </div>
            <div style={{ fontSize: 18, color: C.ink3, paddingBottom: 2 }}>=</div>
            <div>
              <MonoCaps style={{ fontSize: 9 }} color={C.acc}>총자산 (₩)</MonoCaps>
              <Num size={22} weight={800} color={C.acc} style={{ marginTop: 4, textDecoration: "none" }}>{fmtKrwFull(assetTotalKrw)}</Num>
            </div>
            <div style={{ width: 1, height: 36, background: C.line2 }}></div>
            <div>
              <MonoCaps style={{ fontSize: 9 }}>주식 손익 (₩)</MonoCaps>
              <div style={{ marginTop: 4 }}>
                <Num size={18} weight={800} color={totalPnlKrw >= 0 ? C.ok : C.bad} style={{ textDecoration: "none" }}>
                  {totalPnlKrw >= 0 ? "+" : ""}{fmtKrwFull(totalPnlKrw)}
                </Num>
                {totalPnlPct != null && (
                  <span style={{ marginLeft: 8, fontSize: 12.5, fontWeight: 700, color: totalPnlKrw >= 0 ? C.ok : C.bad }}>
                    ({totalPnlPct >= 0 ? "+" : ""}{totalPnlPct.toFixed(2)}%)
                  </span>
                )}
              </div>
            </div>
            <div style={{ marginLeft: "auto", textAlign: "right" }}>
              <MonoCaps style={{ fontSize: 9 }}>{(rows || []).length}종목 보유</MonoCaps>
            </div>
          </div>
          <div style={{ marginTop: 8, fontSize: 10.5, color: C.ink3 }}>
            {fx ? `적용 환율 USD/KRW ${Math.round(fx).toLocaleString("ko-KR")} · USD 자산은 환산 반영` : "환율 데이터 없음 — KRW만 합산"}
            {fxMissing && " · 일부 USD 환산 제외"}
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

      {/* PR-2: 현금 관리 */}
      <Panel title="현금" sub="통화별 현금 (총자산에 합산)">
        <div style={{ padding: "14px 18px" }}>
          {cashRows.length > 0 && (
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
              {cashRows.map((c) => (
                <span key={c.currency} style={{ fontSize: 12.5, fontWeight: 600, color: C.ink, background: C.surface2, border: `1px solid ${C.line}`, borderRadius: 7, padding: "5px 12px" }}>
                  {c.currency} {fmtMoney(c.amount, c.currency)}
                </span>
              ))}
            </div>
          )}
          <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <MonoCaps style={{ fontSize: 9.5 }}>통화</MonoCaps>
              <select
                value={cashForm.currency}
                onChange={(e) => setCashForm((f) => ({ ...f, currency: e.target.value }))}
                style={{ border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 13, fontFamily: "var(--sans)", color: C.ink, background: C.surface, cursor: "pointer", outline: "none" }}
              >
                <option value="KRW">KRW</option>
                <option value="USD">USD</option>
              </select>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <MonoCaps style={{ fontSize: 9.5 }}>금액 (0 입력 시 삭제)</MonoCaps>
              <input
                type="number" placeholder="예: 1000000" value={cashForm.amount}
                onChange={(e) => setCashForm((f) => ({ ...f, amount: e.target.value }))}
                style={{ border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 13, width: 180, outline: "none", fontFamily: "var(--sans)", color: C.ink }}
              />
            </div>
            <button
              onClick={handleSaveCash}
              disabled={cashSaving || cashForm.amount === ""}
              style={{ background: C.ink, color: "#fff", border: "none", borderRadius: 7, padding: "10px 22px", fontSize: 13, fontWeight: 600, cursor: (cashSaving || cashForm.amount === "") ? "default" : "pointer", opacity: (cashSaving || cashForm.amount === "") ? 0.45 : 1 }}
            >
              {cashSaving ? "저장 중…" : "현금 저장"}
            </button>
          </div>
        </div>
      </Panel>

      {/* CoT 전략 조언 (참고용) */}
      <PortfolioAdvice D={D} hasHoldings={(rows || []).length > 0} />
    </div>
  );
}

// ── CoT 포트폴리오 전략 조언 (참고용) ─────────────────────────────────
function AdviceSection({ label, color, open, onToggle, children }) {
  return (
    <div style={{ borderTop: `1px solid ${C.line}` }}>
      <button onClick={onToggle} style={{ width: "100%", textAlign: "left", border: "none", background: "none", cursor: "pointer", padding: "11px 16px", display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ width: 3, height: 14, background: color, borderRadius: 2 }}></span>
        <span style={{ fontSize: 12.5, fontWeight: 700, color: C.ink }}>{label}</span>
        <span style={{ marginLeft: "auto", color: C.ink3, fontSize: 12 }}>{open ? "−" : "+"}</span>
      </button>
      {open && <div style={{ padding: "0 16px 14px 27px" }}>{children}</div>}
    </div>
  );
}

function Bullets({ items, color }) {
  return (
    <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
      {(items || []).map((t, i) => (
        <li key={i} style={{ display: "flex", gap: 8, fontSize: 12.5, color: C.ink2, lineHeight: 1.55 }}>
          <span style={{ color: color || C.ink3, flexShrink: 0 }}>·</span><span>{t}</span>
        </li>
      ))}
    </ul>
  );
}

function PortfolioAdvice({ D, hasHoldings }) {
  const [advice, setAdvice] = useState(D.portfolioAdvice || null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState({ s1: false, s2: true, s3: false });

  useEffect(() => {
    fetch(`${API}/api/portfolio/advice`).then((r) => r.json()).then((d) => { if (d) setAdvice(d); }).catch(() => {});
  }, []);

  const regenerate = async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/portfolio/advice`, { method: "POST" });
      if (r.ok) setAdvice(await r.json());
    } catch (_) {}
    setLoading(false);
  };

  const srcBadge = advice && (
    <span style={{ fontSize: 9.5, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
      background: advice.source === "gemini" ? C.accTint : C.surface2,
      color: advice.source === "gemini" ? C.acc : C.ink3, border: `1px solid ${C.line2}` }}>
      {advice.source === "gemini" ? "Gemini CoT" : "규칙기반"}
    </span>
  );

  return (
    <Panel title="전략 조언" sub="단계분리 분석"
      right={
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {srcBadge}
          <button onClick={regenerate} disabled={loading || !hasHoldings} style={{ ...btnGhost, opacity: (loading || !hasHoldings) ? 0.5 : 1 }}>
            {loading ? "분석 중…" : "다시 분석"}
          </button>
        </div>
      }>
      {!hasHoldings ? (
        <div style={{ padding: "26px 18px", textAlign: "center", color: C.ink3, fontSize: 12.5 }}>
          보유종목을 추가하면 포트폴리오 전략 조언(구성·리스크·국면 정합성·종합 관찰)을 볼 수 있습니다.
        </div>
      ) : !advice || advice.empty ? (
        <div style={{ padding: "26px 18px", textAlign: "center", color: C.ink3, fontSize: 12.5 }}>
          아직 분석이 없습니다. <b>다시 분석</b>을 눌러 생성하세요.
        </div>
      ) : (
        <>
          {advice.stale && (
            <div style={{ padding: "8px 16px", background: C.warnBg, fontSize: 11.5, color: C.warn }}>
              보유가 바뀐 뒤 분석이 갱신되지 않았습니다 — <b>다시 분석</b>을 권장합니다.
            </div>
          )}
          {/* STEP4 종합 관찰 (상단 강조) */}
          <div style={{ padding: "14px 16px" }}>
            <MonoCaps style={{ fontSize: 9, marginBottom: 6, display: "block" }} color={C.acc}>종합 관찰</MonoCaps>
            <div style={{ fontSize: 13.5, color: C.ink, lineHeight: 1.65 }}>{advice.step4?.summary}</div>
            {(advice.step4?.questions || []).length > 0 && (
              <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 5 }}>
                {advice.step4.questions.map((q, i) => (
                  <div key={i} style={{ fontSize: 12, color: C.ink2, display: "flex", gap: 7 }}>
                    <span style={{ color: C.acc }}>?</span><span>{q}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          {/* 펼침 3단계 */}
          <AdviceSection label="① 구성 분석" color={C.ink} open={open.s1} onToggle={() => setOpen((o) => ({ ...o, s1: !o.s1 }))}>
            <Bullets items={advice.step1?.facts} />
            <div style={{ marginTop: 8, fontSize: 12, color: C.ink3, lineHeight: 1.6 }}>
              {advice.step1?.concentration_note} {advice.step1?.allocation_note} {advice.step1?.cash_note}
            </div>
          </AdviceSection>
          <AdviceSection label="② 리스크 식별" color={C.bad} open={open.s2} onToggle={() => setOpen((o) => ({ ...o, s2: !o.s2 }))}>
            <Bullets items={advice.step2?.risks} color={C.bad} />
          </AdviceSection>
          <AdviceSection label="③ 국면 정합성" color={C.warn} open={open.s3} onToggle={() => setOpen((o) => ({ ...o, s3: !o.s3 }))}>
            <div style={{ fontSize: 12.5, color: C.ink2, lineHeight: 1.6 }}>
              <div>현재 국면: <b style={{ color: C.ink }}>{advice.regime}</b></div>
              <div style={{ marginTop: 5 }}>{advice.step3?.tilt_note}</div>
              <div style={{ marginTop: 5 }}>{advice.step3?.alignment_note}</div>
            </div>
          </AdviceSection>
          {/* 생성시각 */}
          <div style={{ padding: "9px 16px", borderTop: `1px solid ${C.line}`, background: C.surface2, borderRadius: "0 0 10px 10px", display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
            <span className="mono" style={{ fontSize: 9.5, color: C.ink3 }}>생성: {advice.generatedAtLabel}</span>
          </div>
        </>
      )}
    </Panel>
  );
}
