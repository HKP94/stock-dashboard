// ATLAS — Tabs C: Portfolio
// PR-4: 포트폴리오 탭 — GET/POST/DELETE /api/portfolio (127.0.0.1:8765)

import { useState, useEffect, useCallback, useMemo } from 'react';
import { C, MonoCaps, Num, btnGhost } from './ui.jsx';
import { Panel } from './tabsA.jsx';
// 총자산은 assetEquation을 거치고, 그 내부가 공용 portfolioAssetTotal을 호출한다
// (CLAUDE.md "총자산 표시는 단일 경로" — 여기서 asset_total을 직접 읽으면 오버뷰와 갈린다).
import { cleanDisplayText, assetEquation, holdingWeightPct, holdingChangePoints } from './display.js';
import { ComposedChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceDot } from 'recharts';

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
  const col = pos ? C.up : C.down;   // 등락축(평가손익)
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

// P④: 통화 그룹. 한 화면 2그룹(탭 아님) — 탭이면 전체 비중 감각이 끊긴다.
const CURRENCY_GROUPS = [
  { ccy: "KRW", label: "국내" },
  { ccy: "USD", label: "해외" },
];

// ── 자산흐름 (Phase 3, P③) ────────────────────────────────────────
// ★이 차트는 **성과 곡선이 아니다.** 매매로 n_holdings가 바뀌면 계단으로 꺾이고,
// 현금이 수동 입력이라 매도대금 반영 시점이 어긋나면 총자산도 튄다(실측 07-31 +755,874).
// 그래서 ① 캡션으로 명시하고 ② n_holdings 변화일에 마커를 찍어 계단의 원인을 그 자리에서 밝힌다.
// TWR 등 성과지표는 입출금 기록이 없어 정직하게 계산할 수 없으므로 만들지 않는다(PM 승인).
function AssetFlowChart({ history }) {
  const [range, setRange] = useState("all");
  const all = history || [];
  const data = useMemo(() => (range === "1m" ? all.slice(-31) : all), [all, range]);
  const markers = useMemo(() => holdingChangePoints(data), [data]);
  const assetFrom = useMemo(() => data.find((r) => r.asset != null)?.asof ?? null, [data]);
  // 총자산 범위에 5% 여백. 0에서 시작하지 않으므로 캡션에 그 사실을 반드시 밝힌다
  // (비-제로 기준선은 작은 변동을 크게 보이게 하는 반대 방향의 왜곡이다).
  const domain = useMemo(() => {
    const vals = data.map((r) => r.asset).filter((v) => v != null);
    if (!vals.length) return ["auto", "auto"];
    const lo = Math.min(...vals), hi = Math.max(...vals), pad = (hi - lo || hi * 0.02) * 0.5;
    return [Math.floor(lo - pad), Math.ceil(hi + pad)];
  }, [data]);

  if (all.length < 2) {
    return (
      <Panel title="자산흐름" sub="총자산 추이">
        <div style={{ padding: "26px 18px", textAlign: "center", color: C.ink3, fontSize: 12.5 }}>
          이력이 아직 부족합니다. 스냅샷이 이틀 이상 쌓이면 표시됩니다.
        </div>
      </Panel>
    );
  }

  const fmtAxis = (v) => (v >= 1e8 ? `${(v / 1e8).toFixed(1)}억` : `${Math.round(v / 1e4).toLocaleString("ko-KR")}만`);

  return (
    <Panel
      title="자산흐름"
      sub={`${all[0].asof}부터 · ${all.length}일`}
      right={
        <div style={{ display: "flex", gap: 4 }}>
          {[["1m", "1개월"], ["all", "전체"]].map(([k, lbl]) => (
            <button key={k} onClick={() => setRange(k)} style={{
              border: `1px solid ${range === k ? C.acc : C.line2}`, background: range === k ? C.accTint : C.surface,
              color: range === k ? C.acc : C.ink2, borderRadius: 6, padding: "3px 10px",
              fontSize: 11.5, fontWeight: 600, cursor: "pointer", fontFamily: "var(--sans)",
            }}>{lbl}</button>
          ))}
        </div>
      }
    >
      <div style={{ padding: "12px 12px 4px" }}>
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={data} margin={{ top: 6, right: 12, left: 4, bottom: 2 }}>
            <CartesianGrid stroke={C.line} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="asof" tick={{ fontSize: 10, fill: C.ink3 }} tickLine={false} axisLine={{ stroke: C.line2 }} minTickGap={28} />
            {/* 축을 총자산 범위에 맞춘다. 주식 평가액을 같은 축에 겹치면 매매로 0.4M~7M을
                오가는 탓에 눈금이 0~1,200만으로 벌어져 정작 총자산 선이 평평해진다(실측). */}
            <YAxis tick={{ fontSize: 10, fill: C.ink3 }} tickLine={false} axisLine={false} width={52}
                   tickFormatter={fmtAxis} domain={domain} allowDataOverflow={false} />
            <Tooltip
              contentStyle={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 8, fontSize: 12 }}
              labelStyle={{ color: C.ink2, fontSize: 11 }}
              formatter={(v, name) => [v == null ? "—" : `₩${Math.round(v).toLocaleString("ko-KR")}`, name]}
            />
            <Line type="monotone" dataKey="asset" name="총자산" stroke={C.acc} strokeWidth={2} dot={false} />
            {markers.map((m) => (
              <ReferenceDot key={m.asof} x={m.asof} y={m.asset} r={4} fill={C.warn} stroke={C.surface} strokeWidth={1.5}
                            label={{ value: `${m.from}→${m.to}`, position: "top", fontSize: 9, fill: C.warn }} />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div style={{ padding: "8px 16px 12px", borderTop: `1px solid ${C.line}`, fontSize: 11, color: C.ink3, lineHeight: 1.6 }}>
        매매·입출금·현금 수정이 포함된 <b style={{ color: C.ink2 }}>잔고 추이</b>입니다 — 수익률이 아닙니다.
        {markers.length > 0 && <> 주황 점은 보유 종목 수가 바뀐 날입니다(계단의 원인).</>}
        {" "}세로축은 0에서 시작하지 않습니다 — 변동 폭이 실제보다 커 보일 수 있습니다.
        {/* 초기 스냅샷엔 현금이 없어 총자산이 비어 있다. 선이 늦게 시작하는 이유를 밝힌다. */}
        {assetFrom && assetFrom !== data[0].asof && <> 총자산 선은 현금 기록이 시작된 {assetFrom}부터입니다.</>}
      </div>
    </Panel>
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

  // ★P① 수정: 「주식 + 현금 = 총자산」 세 항을 **summary 한 소스**에서만 읽는다.
  // 종전엔 주식=rows·현금=cashRows·총자산=summary로 소스가 3개였고 순차 await라
  // rows만 먼저 도착한 ~1초 동안 「현금 ₩0 = 총자산 8,784,009」 모순이 보였다(실측).
  // 클라이언트 합산(toKrw/totalEvalKrw/cashKrw)은 삭제했다 — 서버가 이미 정합하게 계산한다.
  const eq = assetEquation(summary);
  const fx = eq?.fxRate ?? null;
  const toKrw = (amt, ccy) => (ccy === "USD" ? (fx ? amt * fx : null) : amt);

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

      {/* 총자산 히어로 — eq가 null이면 아예 렌더하지 않는다(P①: 돈 화면의 ₩0은 '없음'으로 읽힌다) */}
      {eq === null ? (
        <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10, padding: "22px", textAlign: "center", color: C.ink3, fontSize: 12.5 }}>
          자산 합계를 불러오는 중…
        </div>
      ) : (
        <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10, padding: "14px 22px" }}>
          <div style={{ display: "flex", gap: 28, alignItems: "flex-end", flexWrap: "wrap" }}>
            <div>
              <MonoCaps style={{ fontSize: 9 }}>주식 평가액 (₩)</MonoCaps>
              <Num size={20} weight={800} style={{ marginTop: 4, textDecoration: "none" }}>{fmtKrwFull(eq.stock)}</Num>
            </div>
            <div style={{ fontSize: 18, color: C.ink3, paddingBottom: 2 }}>+</div>
            <div>
              <MonoCaps style={{ fontSize: 9 }}>현금 (₩)</MonoCaps>
              <Num size={20} weight={800} color={C.ink2} style={{ marginTop: 4, textDecoration: "none" }}>{fmtKrwFull(eq.cash)}</Num>
            </div>
            <div style={{ fontSize: 18, color: C.ink3, paddingBottom: 2 }}>=</div>
            <div>
              <MonoCaps style={{ fontSize: 9 }} color={C.acc}>총자산 (₩)</MonoCaps>
              <Num size={22} weight={800} color={C.acc} style={{ marginTop: 4, textDecoration: "none" }}>{fmtKrwFull(eq.asset)}</Num>
            </div>
            <div style={{ width: 1, height: 36, background: C.line2 }}></div>
            <div>
              <MonoCaps style={{ fontSize: 9 }}>주식 손익 (₩)</MonoCaps>
              <div style={{ marginTop: 4 }}>
                <Num size={18} weight={800} color={eq.pnl >= 0 ? C.up : C.down} style={{ textDecoration: "none" }}>
                  {eq.pnl >= 0 ? "+" : ""}{fmtKrwFull(eq.pnl)}
                </Num>
                {eq.pnlPct != null && (
                  <span style={{ marginLeft: 8, fontSize: 12.5, fontWeight: 700, color: eq.pnl >= 0 ? C.up : C.down }}>
                    ({eq.pnlPct >= 0 ? "+" : ""}{eq.pnlPct.toFixed(2)}%)
                  </span>
                )}
              </div>
            </div>
            <div style={{ marginLeft: "auto", textAlign: "right" }}>
              <MonoCaps style={{ fontSize: 9 }}>{eq.nHoldings ?? (rows || []).length}종목 보유</MonoCaps>
            </div>
          </div>
          <div style={{ marginTop: 8, fontSize: 10.5, color: C.ink3 }}>
            {fx ? `적용 환율 USD/KRW ${Math.round(fx).toLocaleString("ko-KR")} · USD 자산은 환산 반영` : "환율 데이터 없음 — KRW만 합산"}
            {eq.fxMissing && " · 일부 USD 환산 제외"}
            {D.priceAsof && ` · 가격 기준일 ${D.priceAsof}`}
          </div>
          {/* 한 소스라 어긋날 일이 없지만, 어긋나면 서버 계산 버그다 — 숨기지 않는다 */}
          {!eq.balanced && (
            <div style={{ marginTop: 8, fontSize: 11, color: C.warn, background: C.warnBg, borderRadius: 6, padding: "6px 10px" }}>
              주식 + 현금 합계가 총자산과 일치하지 않습니다. 값 확인이 필요합니다.
            </div>
          )}
        </div>
      )}

      {/* 자산흐름 — ★성과 곡선이 아니다(매매·입출금·현금 수정 포함) */}
      <AssetFlowChart history={D.portfolioHistory} />

      {/* 보유 테이블 — P④ 통화 2그룹(탭 아님: 탭이면 전체 비중 감각이 끊긴다) */}
      <Panel
        title="보유종목"
        sub={rows == null ? "로딩중…" : `${rows.length}건 · 국내/해외 구분`}
        right={eq && <span style={{ fontSize: 10, color: C.ink3 }}>비중 = 총자산(현금 포함) 대비</span>}
      >
        {rows == null ? (
          <div style={{ padding: 32, textAlign: "center", color: C.ink3 }}>로딩중…</div>
        ) : rows.length === 0 ? (
          <div style={{ padding: 32, textAlign: "center", color: C.ink3 }}>보유종목이 없습니다. 아래 폼에서 추가하세요.</div>
        ) : (
          CURRENCY_GROUPS.filter((g) => rows.some((r) => r.currency === g.ccy)).map((g) => {
            const gr = rows.filter((r) => r.currency === g.ccy);
            const subEval = gr.reduce((a, r) => a + (r.eval_amount || 0), 0);
            const subEvalKrw = toKrw(subEval, g.ccy);
            const subPnl = gr.reduce((a, r) => a + (r.pnl || 0), 0);
            return (
              <div key={g.ccy}>
                {/* 그룹 헤더 — 소계 + (USD면) 환산 기준 명시 */}
                <div style={{ display: "flex", alignItems: "baseline", gap: 10, padding: "9px 14px", background: C.surface2, borderTop: `1px solid ${C.line}`, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 12.5, fontWeight: 800, color: C.ink }}>{g.label}</span>
                  <MonoCaps style={{ fontSize: 9 }} color={C.ink3}>{g.ccy} · {gr.length}종목</MonoCaps>
                  <span style={{ marginLeft: "auto", display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                    <span className="tnum" style={{ fontSize: 12.5, fontWeight: 700, color: C.ink }}>{fmtMoney(subEval, g.ccy)}</span>
                    {g.ccy === "USD" && (
                      <span className="tnum" style={{ fontSize: 11, color: C.ink3 }}>
                        {subEvalKrw != null ? `≈ ${fmtKrwFull(subEvalKrw)}` : "환율 없음 — 환산 불가"}
                        {fx ? ` (USD/KRW ${Math.round(fx).toLocaleString("ko-KR")}${D.priceAsof ? `, ${D.priceAsof} 기준` : ""})` : ""}
                      </span>
                    )}
                    <span className="tnum" style={{ fontSize: 11.5, fontWeight: 700, color: subPnl >= 0 ? C.up : C.down }}>
                      {subPnl >= 0 ? "+" : ""}{fmtMoney(subPnl, g.ccy)}
                    </span>
                  </span>
                </div>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: `1px solid ${C.line2}` }}>
                      {["종목", "수량", "평단가", "현재가", "평가금액", "비중", "손익", ""].map((h, i) => (
                        <th key={i} title={h === "비중" ? "총자산(현금 포함) 대비 평가금액 비율 — 사실 표시이며 목표 비중이 아닙니다" : undefined}
                            style={{ textAlign: "left", padding: "9px 14px", cursor: h === "비중" ? "help" : "default" }}>
                          <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{h}</MonoCaps>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {gr.map((r) => {
                      const s = D.stocks.find((x) => x.t === r.ticker);
                      const wPct = holdingWeightPct(toKrw(r.eval_amount, r.currency), eq?.asset);
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
                          <td style={{ padding: "11px 14px" }}>
                            {wPct == null
                              ? <span style={{ fontSize: 12, color: C.ink3 }}>—</span>
                              : <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                                  <Num size={13} weight={700} style={{ textDecoration: "none", width: 42, textAlign: "right" }}>{wPct.toFixed(1)}%</Num>
                                  <div style={{ width: 44, height: 5, background: C.surface2, borderRadius: 999, overflow: "hidden" }}>
                                    <div style={{ width: `${Math.min(100, wPct)}%`, height: "100%", background: C.acc, borderRadius: 999 }}></div>
                                  </div>
                                </div>}
                          </td>
                          <td style={{ padding: "11px 14px" }}><PnlCell pnl={r.pnl} pnl_pct={r.pnl_pct} currency={r.currency} /></td>
                          <td style={{ padding: "11px 14px" }}>
                            <button onClick={() => handleDelete(r.ticker)} style={{ border: `1px solid ${C.line2}`, background: C.surface, color: C.neg, borderRadius: 6, padding: "4px 10px", fontSize: 11.5, fontWeight: 600, cursor: "pointer" }}>삭제</button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            );
          })
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
            style={{ background: C.acc, color: C.onAcc, border: "none", borderRadius: 7, padding: "10px 22px", fontSize: 13, fontWeight: 600, cursor: (saving || !formValid) ? "default" : "pointer", opacity: (saving || !formValid) ? 0.45 : 1 }}
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
              style={{ background: C.acc, color: C.onAcc, border: "none", borderRadius: 7, padding: "10px 22px", fontSize: 13, fontWeight: 600, cursor: (cashSaving || cashForm.amount === "") ? "default" : "pointer", opacity: (cashSaving || cashForm.amount === "") ? 0.45 : 1 }}
            >
              {cashSaving ? "저장 중…" : "현금 저장"}
            </button>
          </div>
        </div>
      </Panel>

      {/* CoT 전략 조언 (참고용) */}
      <PortfolioAdvice D={D} hasHoldings={(rows || []).length > 0} nowHoldings={eq?.nHoldings ?? (rows || []).length} />
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
          <span style={{ color: color || C.ink3, flexShrink: 0 }}>·</span><span>{cleanDisplayText(t)}</span>
        </li>
      ))}
    </ul>
  );
}

// P②: 며칠 전 보유 기준으로 쓰인 본문이 그대로 노출되면 옛 사실을 현재로 오독한다
// (실측: 2026-07-01 생성분이 옛 총자산 10,066,443과 매도한 종목들을 서술 중).
// A③ 교훈 "스테일은 본문 강등" — 경고 1줄이 아니라 **본문 자체를 접는다**.
function StaleAdviceGate({ advice, nowHoldings, onExpand }) {
  const then = advice.holdingsCount;
  const days = (() => {
    const t = Date.parse(advice.generatedAt);
    return Number.isFinite(t) ? Math.floor((Date.now() - t) / 86400000) : null;
  })();
  return (
    <div style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 10, alignItems: "flex-start" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 10, fontWeight: 800, color: C.warn, background: C.warnBg, border: `1px solid ${C.warn}44`, borderRadius: 999, padding: "3px 10px" }}>
          지난 분석
        </span>
        <span className="mono" style={{ fontSize: 11, color: C.ink2 }}>
          {advice.generatedAtLabel}{days != null ? ` · ${days}일 경과` : ""}
        </span>
      </div>
      <div style={{ fontSize: 12.5, color: C.ink2, lineHeight: 1.6 }}>
        {/* 티커 목록은 저장돼 있지 않아 개수로만 표시한다(PM 결정 (a)) */}
        {then != null && nowHoldings != null && then !== nowHoldings
          ? <>작성 당시 <b style={{ color: C.ink }}>{then}종목</b> 기준이며, 현재는 <b style={{ color: C.ink }}>{nowHoldings}종목</b>입니다. 본문의 종목·금액은 지금과 다릅니다.</>
          : <>보유가 바뀐 뒤 분석이 갱신되지 않았습니다. 본문의 종목·금액은 지금과 다를 수 있습니다.</>}
      </div>
      <button onClick={onExpand} style={{ border: `1px solid ${C.line2}`, background: C.surface, color: C.ink2, borderRadius: 7, padding: "6px 14px", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "var(--sans)" }}>
        그래도 지난 분석 보기
      </button>
    </div>
  );
}

function PortfolioAdvice({ D, hasHoldings, nowHoldings }) {
  const [advice, setAdvice] = useState(D.portfolioAdvice || null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState({ s1: false, s2: true, s3: false });
  const [staleOpen, setStaleOpen] = useState(false);

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
      ) : (advice.stale && !staleOpen) ? (
        <StaleAdviceGate advice={advice} nowHoldings={nowHoldings} onExpand={() => setStaleOpen(true)} />
      ) : (
        <>
          {advice.stale && (
            <div style={{ padding: "8px 16px", background: C.warnBg, fontSize: 11.5, color: C.warn, display: "flex", alignItems: "center", gap: 8 }}>
              <b>당시 기준</b>
              <span>{advice.generatedAtLabel} 작성{advice.holdingsCount != null ? ` · 당시 ${advice.holdingsCount}종목` : ""} — 아래 종목·금액은 지금과 다릅니다.</span>
              <button onClick={() => setStaleOpen(false)} style={{ ...btnGhost, marginLeft: "auto", color: C.warn }}>접기</button>
            </div>
          )}
          {/* STEP4 종합 관찰 (상단 강조) */}
          <div style={{ padding: "14px 16px" }}>
            <MonoCaps style={{ fontSize: 9, marginBottom: 6, display: "block" }} color={C.acc}>종합 관찰</MonoCaps>
            <div style={{ fontSize: 13.5, color: C.ink, lineHeight: 1.65 }}>{cleanDisplayText(advice.step4?.summary)}</div>
            {(advice.step4?.questions || []).length > 0 && (
              <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 5 }}>
                {advice.step4.questions.map((q, i) => (
                  <div key={i} style={{ fontSize: 12, color: C.ink2, display: "flex", gap: 7 }}>
                    <span style={{ color: C.acc }}>?</span><span>{cleanDisplayText(q)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          {/* 펼침 3단계 */}
          <AdviceSection label="① 구성 분석" color={C.ink} open={open.s1} onToggle={() => setOpen((o) => ({ ...o, s1: !o.s1 }))}>
            <Bullets items={advice.step1?.facts} />
            <div style={{ marginTop: 8, fontSize: 12, color: C.ink3, lineHeight: 1.6 }}>
              {cleanDisplayText(advice.step1?.concentration_note)} {cleanDisplayText(advice.step1?.allocation_note)} {cleanDisplayText(advice.step1?.cash_note)}
            </div>
          </AdviceSection>
          <AdviceSection label="② 리스크 식별" color={C.neg} open={open.s2} onToggle={() => setOpen((o) => ({ ...o, s2: !o.s2 }))}>
            <Bullets items={advice.step2?.risks} color={C.neg} />
          </AdviceSection>
          <AdviceSection label="③ 국면 정합성" color={C.warn} open={open.s3} onToggle={() => setOpen((o) => ({ ...o, s3: !o.s3 }))}>
            <div style={{ fontSize: 12.5, color: C.ink2, lineHeight: 1.6 }}>
              <div>현재 국면: <b style={{ color: C.ink }}>{advice.regime}</b></div>
              <div style={{ marginTop: 5 }}>{cleanDisplayText(advice.step3?.tilt_note)}</div>
              <div style={{ marginTop: 5 }}>{cleanDisplayText(advice.step3?.alignment_note)}</div>
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
