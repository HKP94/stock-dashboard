// ATLAS — Tabs A: Overview, Stock Detail, News
import { useState, useMemo, useEffect } from 'react';
import {
  C, fmtPrice, compColor, sentMeta, flagTone,
  MonoCaps, Num, ChangePct, SentBadge, HoldDot, AlignBadge,
  CompositeCell, MiniBars, FactorBar, Sparkline, PriceChart,
  SentStack, Pill, RegimeBadge, btnGhost,
} from './ui.jsx';

export function Panel({ title, sub, right, children, style, bodyStyle }) {
  return (
    <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10, boxShadow: "0 1px 2px rgba(15,23,42,0.04)", display: "flex", flexDirection: "column", ...style }}>
      {title && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "13px 16px", borderBottom: `1px solid ${C.line}` }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 9 }}>
            <span style={{ fontSize: 14.5, fontWeight: 700, color: C.ink, letterSpacing: "-0.01em", whiteSpace: "nowrap" }}>{title}</span>
            {sub && <MonoCaps style={{ fontSize: 10 }}>{sub}</MonoCaps>}
          </div>
          {right}
        </div>
      )}
      <div style={{ flex: 1, ...bodyStyle }}>{children}</div>
    </div>
  );
}

export function FilterTabs({ value, onChange, options }) {
  return (
    <div style={{ display: "flex", gap: 2, background: C.surface2, borderRadius: 8, padding: 3 }}>
      {options.map((o) => {
        const active = value === o.k;
        return (
          <button key={o.k} onClick={() => onChange(o.k)} style={{
            border: "none", cursor: "pointer", fontSize: 12, fontWeight: 600,
            padding: "5px 12px", borderRadius: 6,
            background: active ? C.surface : "transparent",
            color: active ? C.ink : C.ink2,
            boxShadow: active ? "0 1px 2px rgba(15,23,42,0.08)" : "none",
            transition: "all .15s",
          }}>
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

const flagDesc = (f, s) => {
  if (/RSI 과열/.test(f)) return `RSI ${s.rsi} — 단기 과열 구간, 추격 매수 주의`;
  if (/RSI 과매도/.test(f)) return `RSI ${s.rsi} — 과매도 근접, 기술적 반등 가능`;
  if (/골든크로스 임박/.test(f)) return "20일선이 60일선 상향 돌파 임박";
  if (/골든크로스 발생/.test(f)) return "20일선이 60일선 상향 돌파 — 추세 전환 신호";
  if (/데드크로스/.test(f)) return "20일선이 60일선 하향 돌파 — 추세 약화";
  if (/거래량 급증/.test(f)) return "최근 거래량 20일 평균 대비 급증";
  if (/정배열 강세/.test(f)) return "20 > 60 > 120일선 정배열, 추세 강세";
  if (/정배열 유지/.test(f)) return "이동평균선 정배열 유지 중";
  if (/신고가/.test(f)) return f + " 수준에서 거래";
  if (/배당/.test(f)) return "배당 매력 섹터 상위, 안정적 현금흐름";
  if (/저변동/.test(f)) return "낮은 베타·변동성, 방어적 특성";
  if (/HBM/.test(f)) return "HBM 사이클 수혜 — 구조적 모멘텀";
  if (/고밸류|경계/.test(f)) return "밸류에이션 부담 — 변동성 확대 유의";
  if (/약세/.test(f)) return "추세 기울기 하락, 약세 흐름";
  return f;
};

// PR-3: 플래그 분류 헬퍼 (data.json이 분리되어 있지만 fallback 포함)
const isDataQuality = (f) => /데이터 부족|사전필터 제외|발행주식수 데이터 없음|데이터 없음/.test(f);

// ============================ OVERVIEW ============================
export function Overview({ D, nav, goNews }) {
  const [filter, setFilter] = useState("all");
  const [qualityOpen, setQualityOpen] = useState(false);

  const rows = useMemo(() => {
    let r = [...D.stocks];
    if (filter === "KR") r = r.filter((s) => s.mk === "KR");
    else if (filter === "US") r = r.filter((s) => s.mk === "US");
    else if (filter === "hold") r = r.filter((s) => s.hold);
    // PR-1: 데이터 수집 중 종목은 맨 아래로, 그 안에서 composite 내림차순
    return r.sort((a, b) => {
      const ad = a.hasData === false ? 1 : 0;
      const bd = b.hasData === false ? 1 : 0;
      if (ad !== bd) return ad - bd;
      return (b.comp ?? 0) - (a.comp ?? 0);
    });
  }, [filter, D.stocks]);

  // PR-3: 플래그 분리
  const actionAlerts = [], qualityAlerts = [];
  D.stocks.forEach((s) => {
    const af = s.flagsAction ?? (s.flags || []).filter((f) => !isDataQuality(f));
    const qf = s.flagsQuality ?? (s.flags || []).filter(isDataQuality);
    af.forEach((f) => actionAlerts.push({ s, f }));
    qf.forEach((f) => qualityAlerts.push({ s, f }));
  });
  const sortRank = (f) => (/과열|데드크로스|과매도|약세|경계|하회/.test(f) ? 0 : /임박|급증|골든/.test(f) ? 1 : 2);
  actionAlerts.sort((a, b) => sortRank(a.f) - sortRank(b.f));

  const topNews = D.news.filter((n) => n.hot).slice(0, 4);

  // PR-2: 시장 코멘트
  const summaryMd = D.market?.summaryMd || D.market?.kr?.summaryMd || "";
  const summaryText = summaryMd
    ? summaryMd.split("\n").filter(l => l.trim().startsWith("-")).slice(0, 2).map(l => l.replace(/^-+\s*/, "")).join(" / ")
    : "";
  const overall = D.market.overall;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* 지수 스트립 */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(6,1fr)", gap: 10 }}>
        {D.market.indices.map((ix) => {
          const chgNum = ix.chg;
          const hasChg = chgNum != null;
          const up = hasChg && (ix.inv ? chgNum < 0 : chgNum > 0);
          return (
            <div key={ix.k} style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10, padding: "11px 13px", display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <MonoCaps style={{ fontSize: 9.5 }}>{ix.k}</MonoCaps>
                <span style={{ width: 5, height: 5, borderRadius: 999, background: !hasChg ? C.ink3 : up ? C.ok : C.bad }}></span>
              </div>
              <Num size={19} weight={700}>{ix.v}</Num>
              <ChangePct v={chgNum} inv={ix.inv} size={12} />
            </div>
          );
        })}
      </div>

      {/* PR-2: 시장 코멘트 카드 */}
      {summaryText && (
        <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10, padding: "12px 16px", display: "flex", alignItems: "center", gap: 12 }}>
          <RegimeBadge regime={overall} regimes={D.regimes} />
          <span style={{ fontSize: 12.5, color: C.ink2, lineHeight: 1.5, flex: 1 }}>{summaryText}</span>
          <button onClick={() => nav(null, "market")} style={{ ...btnGhost, flexShrink: 0 }}>시장 전망 →</button>
        </div>
      )}

      {/* PR-3: 포트폴리오 요약 카드 — ₩ 환산 전체 숫자 */}
      {D.portfolio && D.portfolio.total_eval != null && (
        <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10, padding: "14px 20px", display: "flex", alignItems: "center", gap: 24 }}>
          <div>
            <MonoCaps style={{ fontSize: 9 }}>내 포트폴리오 (₩ 환산)</MonoCaps>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 4 }}>
              <Num size={22} weight={800} style={{ textDecoration: "none" }}>
                ₩{Math.round(D.portfolio.total_eval).toLocaleString("ko-KR")}
              </Num>
              <span style={{ fontSize: 12, color: C.ink3 }}>총평가</span>
            </div>
          </div>
          <div style={{ width: 1, height: 36, background: C.line2 }}></div>
          <div>
            <MonoCaps style={{ fontSize: 9 }}>총손익</MonoCaps>
            <div style={{ marginTop: 4 }}>
              <Num size={18} weight={700} style={{ textDecoration: "none" }}
                color={D.portfolio.total_pnl >= 0 ? C.ok : C.bad}>
                {D.portfolio.total_pnl >= 0 ? "+" : ""}₩{Math.round(D.portfolio.total_pnl).toLocaleString("ko-KR")}
              </Num>
              <span style={{ marginLeft: 8, fontSize: 13, fontWeight: 700,
                color: D.portfolio.total_pnl_pct >= 0 ? C.ok : C.bad }}>
                ({D.portfolio.total_pnl_pct >= 0 ? "+" : ""}{D.portfolio.total_pnl_pct?.toFixed(2)}%)
              </span>
            </div>
          </div>
          <div style={{ marginLeft: "auto", textAlign: "right" }}>
            <MonoCaps style={{ fontSize: 9 }} color={C.ink3}>{D.portfolio.n_holdings}종목 보유</MonoCaps>
            {D.portfolio.fx_rate && <div style={{ fontSize: 9.5, color: C.ink3, marginTop: 2 }}>USD/KRW {Math.round(D.portfolio.fx_rate).toLocaleString("ko-KR")}</div>}
          </div>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 420px", gap: 16, alignItems: "start" }}>
        {/* 랭킹 테이블 */}
        <Panel
          title="관심종목 랭킹"
          sub={`COMPOSITE 내림차순 · ${rows.length}종목`}
          right={<FilterTabs value={filter} onChange={setFilter} options={[{ k: "all", label: "전체" }, { k: "KR", label: "KR" }, { k: "US", label: "US" }, { k: "hold", label: "보유" }]} />}
        >
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${C.line2}` }}>
                {["", "종목", "현재가", "COMPOSITE", "M·V·Q·G·S", "RSI", "추세", "주요 플래그", "판단"].map((h, i) => (
                  <th key={i} style={{ textAlign: "left", padding: "9px 12px" }}>
                    <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{h}</MonoCaps>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const af = s.flagsAction ?? (s.flags || []).filter((f) => !isDataQuality(f));
                const collecting = s.hasData === false;  // PR-1: 데이터 수집 중
                return (
                  <tr key={s.t} onClick={() => nav(s.t)} className="row-hover" style={{ borderBottom: `1px solid ${C.line}`, cursor: "pointer", opacity: collecting ? 0.6 : 1 }}>
                    <td style={{ padding: "10px 12px", width: 18 }}><HoldDot on={s.hold} /></td>
                    <td style={{ padding: "10px 12px" }}>
                      <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                        <span style={{ fontSize: 13.5, fontWeight: 700, color: C.ink }}>{s.name}</span>
                        <span className="mono" style={{ fontSize: 10, color: C.ink3, letterSpacing: "0.02em" }}>{s.t} · {s.mk}</span>
                      </div>
                    </td>
                    {collecting ? (
                      <td colSpan={7} style={{ padding: "10px 12px" }}>
                        <span style={{ fontSize: 11.5, fontWeight: 700, color: C.warn, background: C.warnBg, border: `1px solid ${C.warn}33`, borderRadius: 5, padding: "3px 10px" }}>데이터 수집 중</span>
                      </td>
                    ) : (
                    <>
                    <td style={{ padding: "10px 12px" }}>
                      <div style={{ display: "flex", flexDirection: "column", gap: 1, alignItems: "flex-start" }}>
                        <Num size={13.5} weight={600}>{fmtPrice(s)}</Num>
                        <ChangePct v={s.chg} size={11.5} />
                      </div>
                    </td>
                    <td style={{ padding: "10px 12px", width: 150 }}><CompositeCell value={s.comp} /></td>
                    <td style={{ padding: "10px 12px" }}><MiniBars f={s.f} /></td>
                    <td style={{ padding: "10px 12px" }}><Num size={13} weight={600} color={s.rsi == null ? C.ink3 : s.rsi >= 70 ? C.bad : s.rsi <= 35 ? C.acc : C.ink2}>{s.rsi == null ? "—" : s.rsi.toFixed(0)}</Num></td>
                    <td style={{ padding: "10px 12px" }}><AlignBadge on={s.align} /></td>
                    <td style={{ padding: "10px 12px", maxWidth: 150 }}>
                      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                        {af.slice(0, 2).map((f) => (
                          <span key={f} style={{ fontSize: 10.5, fontWeight: 600, color: flagTone(f), background: C.surface2, border: `1px solid ${C.line}`, borderRadius: 5, padding: "2px 6px", whiteSpace: "nowrap" }}>{f}</span>
                        ))}
                      </div>
                    </td>
                    <td style={{ padding: "10px 12px" }}>
                      {s.note?.horizon && (
                        <span style={{
                          fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 4, whiteSpace: "nowrap",
                          background: s.note.horizon === "short" ? C.accTint : s.note.horizon === "long" ? C.okBg : C.surface2,
                          color: s.note.horizon === "short" ? C.acc : s.note.horizon === "long" ? C.ok : C.ink3,
                        }}>
                          {s.note.horizon === "short" ? "단기" : s.note.horizon === "long" ? "장기" : "관망"}
                          {s.note.attractiveness && ` ${"★".repeat(s.note.attractiveness)}`}
                        </span>
                      )}
                    </td>
                    </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Panel>

        {/* 우측 패널 */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* PR-3: 액션 신호 메인 */}
          <Panel
            title="오늘의 알림"
            sub={`${actionAlerts.length} RULES FLAGGED`}
            bodyStyle={{ maxHeight: 320, overflowY: "auto" }}
          >
            {actionAlerts.map((a, i) => (
              <div key={i} onClick={() => nav(a.s.t)} className="row-hover" style={{ display: "flex", gap: 11, padding: "11px 16px", borderBottom: `1px solid ${C.line}`, cursor: "pointer", alignItems: "flex-start" }}>
                <span style={{ width: 3, alignSelf: "stretch", borderRadius: 2, background: flagTone(a.f), flexShrink: 0 }}></span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 2 }}>
                    <span style={{ fontSize: 12.5, fontWeight: 700, color: C.ink }}>{a.s.name}</span>
                    <span style={{ fontSize: 11, fontWeight: 700, color: flagTone(a.f) }}>{a.f}</span>
                  </div>
                  <div style={{ fontSize: 11.5, color: C.ink2, lineHeight: 1.4 }}>{flagDesc(a.f, a.s)}</div>
                </div>
              </div>
            ))}
            {actionAlerts.length === 0 && (
              <div style={{ padding: "18px 16px", fontSize: 12.5, color: C.ink3, textAlign: "center" }}>액션 신호 없음</div>
            )}

            {/* PR-3: 데이터 품질 접을 수 있는 섹션 */}
            {qualityAlerts.length > 0 && (
              <div style={{ borderTop: `1px solid ${C.line}` }}>
                <button
                  onClick={() => setQualityOpen(!qualityOpen)}
                  style={{ width: "100%", background: C.surface2, border: "none", padding: "8px 16px", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between" }}
                >
                  <MonoCaps style={{ fontSize: 9 }} color={C.ink3}>데이터 품질 안내 {qualityAlerts.length}건</MonoCaps>
                  <span style={{ fontSize: 10, color: C.ink3 }}>{qualityOpen ? "▲" : "▼"}</span>
                </button>
                {qualityOpen && qualityAlerts.map((a, i) => (
                  <div key={i} style={{ padding: "8px 16px", borderTop: `1px solid ${C.line}`, display: "flex", gap: 9, alignItems: "center" }}>
                    <span style={{ width: 3, height: 12, borderRadius: 2, background: C.ink3, flexShrink: 0 }}></span>
                    <span style={{ fontSize: 11.5, fontWeight: 700, color: C.ink2 }}>{a.s.name}</span>
                    <span style={{ fontSize: 11, color: C.ink3 }}>{a.f}</span>
                  </div>
                ))}
              </div>
            )}
          </Panel>

          <Panel title="주목 뉴스" sub="HIGH-SIGNAL" right={<button onClick={goNews} style={btnGhost}>전체 보기 →</button>}>
            {topNews.map((n, i) => {
              const st = D.stocks.find((s) => s.t === n.t);
              return (
                <div key={i} onClick={() => nav(n.t)} className="row-hover" style={{ padding: "11px 16px", borderBottom: `1px solid ${C.line}`, cursor: "pointer" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 5 }}>
                    <span style={{ fontSize: 11.5, fontWeight: 700, color: C.ink }}>{st ? st.name : n.t}</span>
                    <SentBadge label={n.sent} sm />
                    <span className="mono" style={{ fontSize: 9.5, color: C.ink3, marginLeft: "auto" }}>{n.time}</span>
                  </div>
                  <div style={{ fontSize: 12.5, fontWeight: 600, color: C.ink, lineHeight: 1.4 }}>{n.high}</div>
                </div>
              );
            })}
          </Panel>
        </div>
      </div>
    </div>
  );
}

// ============================ STOCK DETAIL ============================

// PR-1: 드롭다운 select (전체 34종목, "이름 (티커) · 시장" 형식)
function StockDropdown({ stocks, currentTicker, onSelect }) {
  return (
    <select
      value={currentTicker}
      onChange={(e) => onSelect(e.target.value)}
      style={{
        border: `1px solid ${C.line2}`, borderRadius: 8, padding: "7px 12px",
        fontSize: 13, fontWeight: 600, fontFamily: "var(--sans)",
        color: C.ink, background: C.surface, cursor: "pointer", outline: "none",
        minWidth: 240,
      }}
    >
      {stocks.map((s) => (
        <option key={s.t} value={s.t}>
          {s.name} ({s.t}) · {s.mk}
        </option>
      ))}
    </select>
  );
}

const API = "http://127.0.0.1:8765";
const HORIZON_LABEL = { short: "단기 트레이딩", long: "장기 보유", watch: "관망" };

function InvestmentNoteCard({ ticker, initialNote }) {
  const [note, setNote] = useState(initialNote || { horizon: null, attractiveness: null, thesis: "" });
  const [loaded, setLoaded] = useState(!!initialNote);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setNote(initialNote || { horizon: null, attractiveness: null, thesis: "" });
    setLoaded(true); setSaved(false);
  }, [ticker, initialNote]);

  // 로컬 API에서 최신값 로드 (API 없으면 조용히 실패)
  useEffect(() => {
    fetch(`${API}/api/notes/${ticker}`)
      .then((r) => r.json())
      .then((d) => { if (d) setNote(d); setLoaded(true); })
      .catch(() => setLoaded(true));
  }, [ticker]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await fetch(`${API}/api/notes/${ticker}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ horizon: note.horizon, attractiveness: note.attractiveness, thesis: note.thesis }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (_) {}
    setSaving(false);
  };

  return (
    <Panel
      title="내 투자 판단"
      sub="로컬 저장 · 투자 자문 아님"
      right={
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {saved && <MonoCaps style={{ fontSize: 9.5 }} color={C.ok}>✓ 저장됨</MonoCaps>}
          <button
            onClick={handleSave}
            disabled={saving}
            style={{ background: C.ink, color: "#fff", border: "none", borderRadius: 7, padding: "6px 14px", fontSize: 12, fontWeight: 600, cursor: "pointer", opacity: saving ? 0.6 : 1 }}
          >
            {saving ? "저장 중…" : "저장"}
          </button>
        </div>
      }
    >
      <div style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 14 }}>
        {/* horizon */}
        <div>
          <MonoCaps style={{ fontSize: 9.5, marginBottom: 8, display: "block" }}>투자 방향</MonoCaps>
          <div style={{ display: "flex", gap: 8 }}>
            {["short", "long", "watch"].map((h) => (
              <button
                key={h}
                onClick={() => setNote((n) => ({ ...n, horizon: n.horizon === h ? null : h }))}
                style={{
                  border: `1px solid ${note.horizon === h ? (h === "short" ? C.acc : h === "long" ? C.ok : C.ink3) : C.line2}`,
                  background: note.horizon === h ? (h === "short" ? C.accTint : h === "long" ? C.okBg : C.surface2) : C.surface,
                  color: note.horizon === h ? (h === "short" ? C.acc : h === "long" ? C.ok : C.ink3) : C.ink2,
                  borderRadius: 7, padding: "7px 16px", fontSize: 13, fontWeight: 600, cursor: "pointer",
                }}
              >
                {HORIZON_LABEL[h]}
              </button>
            ))}
          </div>
        </div>

        {/* attractiveness */}
        <div>
          <MonoCaps style={{ fontSize: 9.5, marginBottom: 8, display: "block" }}>매력도</MonoCaps>
          <div style={{ display: "flex", gap: 6 }}>
            {[1, 2, 3, 4, 5].map((n) => (
              <button
                key={n}
                onClick={() => setNote((prev) => ({ ...prev, attractiveness: prev.attractiveness === n ? null : n }))}
                style={{
                  border: "none", background: "none", cursor: "pointer", padding: 0,
                  fontSize: 22, color: (note.attractiveness || 0) >= n ? "#F59E0B" : C.line2,
                }}
              >
                ★
              </button>
            ))}
            {note.attractiveness && <span style={{ fontSize: 12, color: C.ink3, alignSelf: "center" }}>{note.attractiveness}/5</span>}
          </div>
        </div>

        {/* thesis */}
        <div>
          <MonoCaps style={{ fontSize: 9.5, marginBottom: 8, display: "block" }}>투자 논거</MonoCaps>
          <textarea
            value={note.thesis || ""}
            onChange={(e) => setNote((n) => ({ ...n, thesis: e.target.value }))}
            placeholder="유튜브·리포트에서 본 내용, 나만의 투자 근거를 자유롭게 기록하세요…"
            style={{
              width: "100%", minHeight: 90, border: `1px solid ${C.line2}`, borderRadius: 8,
              padding: "10px 12px", fontSize: 13.5, fontFamily: "var(--sans)", lineHeight: 1.6,
              color: C.ink, resize: "vertical", outline: "none", boxSizing: "border-box",
            }}
          />
        </div>
      </div>
    </Panel>
  );
}

export function StockDetail({ D, ticker, nav }) {
  const sorted = useMemo(() => [...D.stocks].sort((a, b) => (b.comp ?? 0) - (a.comp ?? 0)), [D.stocks]);
  const s = D.stocks.find((x) => x.t === ticker) || D.stocks[0];

  // PR-1: 이전/다음 종목 (composite 내림차순 기준)
  const curIdx = sorted.findIndex((x) => x.t === s.t);
  const prevStock = curIdx > 0 ? sorted[curIdx - 1] : null;
  const nextStock = curIdx < sorted.length - 1 ? sorted[curIdx + 1] : null;

  // PR-1: 같은 섹터 칩 (현재 제외, composite 상위 5개)
  const sectorPeers = useMemo(() =>
    [...D.stocks]
      .filter((x) => x.sec === s.sec && x.t !== s.t && x.comp != null)
      .sort((a, b) => (b.comp ?? 0) - (a.comp ?? 0))
      .slice(0, 5),
    [D.stocks, s.t, s.sec]
  );

  const sectorStocks = D.stocks.filter((x) => x.sec === s.sec && x.comp != null);
  const sectorRank = sectorStocks.sort((a, b) => (b.comp ?? 0) - (a.comp ?? 0)).findIndex((x) => x.t === s.t) + 1;
  const sectorCount = D.stocks.filter((x) => x.sec === s.sec).length;
  const factors = [["m", s.f.m], ["v", s.f.v], ["q", s.f.q], ["g", s.f.g], ["s", s.f.s]];

  // PR-4: SMA 토글 상태
  const [smaViz, setSmaViz] = useState({ sma20: true, sma60: false, sma120: false });
  const toggleSma = (key) => setSmaViz((prev) => ({ ...prev, [key]: !prev[key] }));

  const indicators = [
    { label: "RSI (14)", val: s.rsi?.toFixed(1) ?? "—", tone: s.rsi >= 70 ? "bad" : s.rsi <= 35 ? "acc" : "neutral", note: s.rsi >= 70 ? "과열" : s.rsi <= 35 ? "과매도" : "중립" },
    { label: "Forward PER", val: s.per != null ? s.per.toFixed(1) + "x" : "—", tone: s.per > 40 ? "warn" : "neutral", note: s.cur === "₩" ? "" : "12M fwd" },
    { label: "ROE", val: s.roe != null ? s.roe.toFixed(1) + "%" : "—", tone: s.roe >= 20 ? "ok" : s.roe < 8 ? "warn" : "neutral", note: "" },
    { label: "영업이익률", val: s.rev != null ? (s.rev > 0 ? "+" : "") + s.rev.toFixed(1) + "%" : "—", tone: s.rev >= 20 ? "ok" : s.rev < 0 ? "bad" : "neutral", note: "최근 연간" },
    { label: "목표주가", val: s.tp != null ? (s.cur === "₩" ? "₩" + s.tp.toLocaleString() : "$" + s.tp) : "—", tone: "neutral", note: "컨센서스" },
    { label: "상승 여력", val: s.up != null ? (s.up > 0 ? "+" : "") + s.up.toFixed(1) + "%" : "—", tone: s.up >= 10 ? "ok" : s.up < 0 ? "bad" : "warn", note: "vs 현재가" },
    { label: "이동평균 배열", val: s.align ? "정배열" : "역배열", tone: s.align ? "ok" : "bad", note: "20·60·120일" },
    { label: "컨센서스 의견", val: s.rating ?? "—", tone: /Strong Buy|Buy/.test(s.rating) ? "ok" : s.rating === "Hold" ? "warn" : "bad", note: "애널리스트" },
  ];
  const toneCol = (t) => ({ ok: C.ok, bad: C.bad, warn: C.warn, acc: C.acc, neutral: C.ink }[t] || C.ink);
  const sectorRankText = s.comp != null ? `${s.sec} ${sectorCount}개 중 ${sectorRank}위` : `${s.sec} ${sectorCount}개`;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* 헤더 */}
      <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10, padding: "18px 22px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <button onClick={() => nav(null, "overview")} style={{ ...btnGhost, fontSize: 18, color: C.ink3 }}>←</button>
          <div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
              <span style={{ fontSize: 24, fontWeight: 800, color: C.ink, letterSpacing: "-0.02em" }}>{s.name}</span>
              <span className="mono" style={{ fontSize: 13, color: C.ink3 }}>{s.t}</span>
              <HoldDot on={s.hold} />
            </div>
            <div style={{ display: "flex", gap: 7, marginTop: 5 }}>
              <Pill tone="neutral">{s.mk === "KR" ? "🇰🇷 한국" : "🇺🇸 미국"}</Pill>
              <Pill tone="neutral">{s.sec}</Pill>
              {s.hold && <Pill tone="acc" active>보유 중</Pill>}
            </div>
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <Num size={32} weight={800}>{fmtPrice(s)}</Num>
          <div style={{ marginTop: 3 }}><ChangePct v={s.chg} size={16} /></div>
        </div>
      </div>

      {/* PR-1: 개선된 종목 네비게이션 */}
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        {/* 이전/다음 버튼 */}
        <button
          onClick={() => prevStock && nav(prevStock.t)}
          disabled={!prevStock}
          style={{ border: `1px solid ${C.line2}`, background: prevStock ? C.surface : C.surface2, color: prevStock ? C.ink : C.ink3, borderRadius: 8, padding: "7px 14px", fontSize: 12.5, fontWeight: 600, cursor: prevStock ? "pointer" : "default" }}
        >
          ◀ {prevStock ? prevStock.name : "처음"}
        </button>
        <button
          onClick={() => nextStock && nav(nextStock.t)}
          disabled={!nextStock}
          style={{ border: `1px solid ${C.line2}`, background: nextStock ? C.surface : C.surface2, color: nextStock ? C.ink : C.ink3, borderRadius: 8, padding: "7px 14px", fontSize: 12.5, fontWeight: 600, cursor: nextStock ? "pointer" : "default" }}
        >
          {nextStock ? nextStock.name : "마지막"} ▶
        </button>

        {/* 구분선 */}
        <span style={{ width: 1, height: 24, background: C.line2 }}></span>

        {/* PR-1: 드롭다운 */}
        <StockDropdown stocks={sorted} currentTicker={s.t} onSelect={(t) => nav(t)} />

        {/* 같은 섹터 칩 */}
        {sectorPeers.length > 0 && (
          <>
            <span style={{ width: 1, height: 24, background: C.line2 }}></span>
            <div style={{ display: "flex", gap: 5, alignItems: "center", flexWrap: "wrap" }}>
              <MonoCaps style={{ fontSize: 9 }} color={C.ink3}>{s.sec}</MonoCaps>
              {sectorPeers.map((x) => (
                <button key={x.t} onClick={() => nav(x.t)} style={{
                  border: `1px solid ${C.line2}`, background: C.surface, color: C.ink2,
                  borderRadius: 999, padding: "3px 10px", fontSize: 11.5, fontWeight: 600, cursor: "pointer",
                }}>
                  {x.name}
                  <span className="tnum" style={{ marginLeft: 5, fontSize: 10, color: compColor(x.comp ?? 0) }}>{x.comp ?? "—"}</span>
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      {/* PR-1: 뉴스 AI 분석 — 헤더 바로 아래, 전체폭. 모든 종목에서 항상 동일 위치·구조로 렌더 */}
      <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10, padding: "16px 22px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
          <MonoCaps style={{ fontSize: 9 }}>Gemini 뉴스 요약</MonoCaps>
          {(s.sum && s.sum.length > 0) && <SentBadge label={s.sent} score={s.sscore} />}
          {s.newsAsof && (
            <span className="mono" style={{ marginLeft: "auto", fontSize: 10, color: C.ink3 }}>기준일: {s.newsAsof}</span>
          )}
        </div>
        {(s.sum && s.sum.length > 0) ? (
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 7 }}>
            {s.sum.map((b, i) => (
              <li key={i} style={{ display: "flex", gap: 9, fontSize: 13, color: C.ink, lineHeight: 1.5 }}>
                <span style={{ color: sentMeta(s.sent).c, fontWeight: 800, flexShrink: 0 }}>—</span><span>{b}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div style={{ fontSize: 12.5, color: C.ink3, padding: "8px 0" }}>최근 뉴스 분석이 없습니다.</div>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 16, alignItems: "start" }}>
        {/* PR-4: 가격차트 + 거래량 + SMA 토글 범례 */}
        <Panel
          title="가격 추이"
          sub="6개월 · 일봉 + 거래량"
          right={(
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              {[
                { key: "sma20", label: "SMA20", color: C.acc },
                { key: "sma60", label: "SMA60", color: C.warn },
                { key: "sma120", label: "SMA120", color: C.ink3 },
              ].map(({ key, label, color }) => (
                <button
                  key={key}
                  onClick={() => toggleSma(key)}
                  style={{
                    border: "none", background: "none", cursor: "pointer", padding: "2px 0",
                    display: "flex", alignItems: "center", gap: 5, opacity: smaViz[key] ? 1 : 0.35,
                  }}
                >
                  <span style={{ width: 14, height: 2, background: color, borderRadius: 1 }}></span>
                  <MonoCaps style={{ fontSize: 9 }} color={color}>{label}</MonoCaps>
                </button>
              ))}
            </div>
          )}
        >
          <div style={{ padding: "14px 16px" }}>
            <PriceChart stock={s} w={560} h={270} showSMAs={smaViz} />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", borderTop: `1px solid ${C.line}` }}>
            {[["SMA 20", s.sma20], ["SMA 60", s.sma50], ["SMA 120", s.sma200], ["20일 이격도", s.disparity != null ? s.disparity + "%" : "—"]].map(([l, v], i) => (
              <div key={l} style={{ padding: "11px 16px", borderRight: i < 3 ? `1px solid ${C.line}` : "none" }}>
                <MonoCaps style={{ fontSize: 9 }}>{l}</MonoCaps>
                <div><Num size={14} weight={600}>{typeof v === "number" ? (s.cur === "₩" ? "₩" + Math.round(v).toLocaleString() : "$" + v) : v}</Num></div>
              </div>
            ))}
          </div>
        </Panel>

        {/* 팩터 점수 */}
        <Panel title="팩터 점수" sub={sectorRankText}>
          <div style={{ padding: "16px 18px", borderBottom: `1px solid ${C.line}`, display: "flex", alignItems: "center", gap: 18 }}>
            <div>
              <MonoCaps style={{ fontSize: 9 }}>COMPOSITE</MonoCaps>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <Num size={48} weight={800} color={compColor(s.comp ?? 0)}>{s.comp ?? "—"}</Num>
                <span style={{ fontSize: 13, color: C.ink3 }}>/ 100</span>
              </div>
            </div>
            <div style={{ flex: 1, paddingLeft: 18, borderLeft: `1px solid ${C.line}` }}>
              <MonoCaps style={{ fontSize: 9 }}>섹터 순위</MonoCaps>
              <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                <Num size={28} weight={800} color={C.acc}>{s.comp != null ? sectorRank : "—"}</Num>
                <span style={{ fontSize: 13, color: C.ink2 }}>위 / {sectorCount}종목</span>
              </div>
              {s.compHist && <div style={{ marginTop: 4 }}><Sparkline data={s.compHist} color={C.acc} w={140} h={22} fill /></div>}
            </div>
          </div>
          <div style={{ padding: "8px 18px 14px" }}>
            <MonoCaps style={{ fontSize: 9 }} color={C.acc}>타이밍 그룹 — 단기 시그널</MonoCaps>
            {factors.filter(([k]) => D.factorMeta[k].group === "timing").map(([k, v]) => <FactorBar key={k} label={D.factorMeta[k].ko} value={v} group="timing" />)}
            <div style={{ height: 1, background: C.line, margin: "8px 0" }}></div>
            <MonoCaps style={{ fontSize: 9 }}>미스프라이싱 그룹 — 장기 보유 판단</MonoCaps>
            {factors.filter(([k]) => D.factorMeta[k].group === "mispricing").map(([k, v]) => <FactorBar key={k} label={D.factorMeta[k].ko} value={v} group="mispricing" />)}
          </div>
        </Panel>
      </div>

      {/* 핵심 지표 */}
      <Panel title="핵심 지표" sub="FUNDAMENTALS · TECHNICALS">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)" }}>
          {indicators.map((ind, i) => (
            <div key={ind.label} style={{ padding: "15px 18px", borderRight: (i % 4 !== 3) ? `1px solid ${C.line}` : "none", borderBottom: i < 4 ? `1px solid ${C.line}` : "none" }}>
              <MonoCaps style={{ fontSize: 9.5 }}>{ind.label}</MonoCaps>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 4 }}>
                <Num size={22} weight={700} color={toneCol(ind.tone)}>{ind.val}</Num>
                {ind.note && <span style={{ fontSize: 11, color: C.ink3 }}>{ind.note}</span>}
              </div>
            </div>
          ))}
        </div>
      </Panel>

      {/* PR-4: 내 투자 판단 카드 */}
      <InvestmentNoteCard ticker={s.t} initialNote={s.note} />

      {/* PR-2: 내 보유 정보 카드 (is_holding=true 종목만) */}
      {s.holding && (
        <Panel title="내 보유 정보" sub="투자 자문 아님 / 원금 손실 가능">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(6,1fr)" }}>
            {[
              ["수량", s.holding.qty != null ? s.holding.qty : "—"],
              ["평단가", s.holding.avg_price != null ? (s.cur === "₩" ? "₩" + Math.round(s.holding.avg_price).toLocaleString() : "$" + s.holding.avg_price.toFixed(2)) : "—"],
              ["현재가", s.cur === "₩" ? "₩" + Math.round(s.holding.cur_price || s.price).toLocaleString() : "$" + (s.holding.cur_price || s.price).toFixed(2)],
              ["평가금액", s.holding.eval_amount != null ? (s.cur === "₩" ? "₩" + Math.round(s.holding.eval_amount).toLocaleString() : "$" + s.holding.eval_amount.toFixed(0)) : "—"],
              ["손익", s.holding.pnl != null ? (s.holding.pnl >= 0 ? "+" : "") + (s.cur === "₩" ? Math.round(s.holding.pnl).toLocaleString() + "원" : "$" + s.holding.pnl.toFixed(0)) : "—"],
              ["손익률", s.holding.pnl_pct != null ? (s.holding.pnl_pct >= 0 ? "+" : "") + s.holding.pnl_pct.toFixed(2) + "%" : "—"],
            ].map(([label, val], i) => {
              const isPnl = i === 4 || i === 5;
              const pnlPos = s.holding.pnl != null && s.holding.pnl >= 0;
              return (
                <div key={label} style={{ padding: "14px 18px", borderRight: i < 5 ? `1px solid ${C.line}` : "none" }}>
                  <MonoCaps style={{ fontSize: 9.5 }}>{label}</MonoCaps>
                  <div style={{ marginTop: 4 }}>
                    <Num size={18} weight={700} color={isPnl ? (pnlPos ? C.ok : C.bad) : C.ink}>{val}</Num>
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 16, alignItems: "start" }}>
        {/* 캐털리스트 + 뉴스탭 링크 */}
        <Panel title="캐털리스트 & 뉴스" sub="GEMINI SENTIMENT" right={<SentBadge label={s.sent} score={s.sscore} />}>
          <div style={{ padding: "14px 18px" }}>
            {(s.cat || []).length > 0 ? (
              <>
                <MonoCaps style={{ fontSize: 9 }}>주요 캐털리스트</MonoCaps>
                <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
                  {(s.cat || []).map((c, i) => (
                    <div key={i} style={{ display: "flex", gap: 12, alignItems: "center" }}>
                      <span className="mono" style={{ fontSize: 11.5, fontWeight: 600, color: C.acc, background: C.accTint, padding: "2px 8px", borderRadius: 5 }}>{c[0]}</span>
                      <span style={{ fontSize: 12.5, color: C.ink2 }}>{c[1]}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <span style={{ fontSize: 12.5, color: C.ink3 }}>캐털리스트 정보 없음</span>
            )}
          </div>
        </Panel>

        <Panel title="점수 히스토리" sub="최근 16주 추이">
          <div style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 16 }}>
            {[["COMPOSITE", s.compHist, C.acc, s.comp], ["모멘텀", s.momHist, C.ok, s.f.m]].filter(([, data]) => data).map(([lbl, data, col, cur]) => {
              const delta = data[data.length - 1] - data[0];
              return (
                <div key={lbl}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
                    <MonoCaps style={{ fontSize: 9.5 }}>{lbl}</MonoCaps>
                    <span className="tnum" style={{ fontSize: 11.5, fontWeight: 700, color: delta >= 0 ? C.ok : C.bad }}>{delta >= 0 ? "+" : ""}{delta} (16주)</span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <Num size={24} weight={800} color={col}>{cur ?? "—"}</Num>
                    <div style={{ flex: 1 }}><Sparkline data={data} color={col} w={200} h={36} fill /></div>
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>
      </div>

      {/* PR-2: 원문 뉴스 (news_raw, 링크 포함) */}
      {(s.articles && s.articles.length > 0) && (
        <Panel title="원문 뉴스" sub={`최근 ${s.articles.length}건 · 클릭 시 원문`}>
          <div>
            {s.articles.map((a, i) => (
              <a key={i} href={a.url} target="_blank" rel="noopener noreferrer"
                className="row-hover"
                style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 18px", borderBottom: `1px solid ${C.line}`, textDecoration: "none" }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: C.ink, flex: 1, lineHeight: 1.4 }}>{a.title}</span>
                <span className="mono" style={{ fontSize: 10, color: C.ink3, flexShrink: 0 }}>{a.src}</span>
                <span className="mono" style={{ fontSize: 10, color: C.ink3, flexShrink: 0, width: 96, textAlign: "right" }}>{a.time}</span>
                <span style={{ fontSize: 11, color: C.acc, flexShrink: 0 }}>↗</span>
              </a>
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}

// ============================ NEWS ============================
export function NewsTab({ D, filterTicker, setFilterTicker, nav }) {
  const [mkt, setMkt] = useState("all");
  const [sent, setSent] = useState("all");
  const [q, setQ] = useState("");

  const sentCounts = useMemo(() => {
    return D.stocks.map((s) => {
      const seed = s.t.length + (s.comp ?? 50);
      const pos = s.sent === "긍정" ? 5 + (seed % 3) : s.sent === "중립" ? 2 + (seed % 2) : 1;
      const neg = s.sent === "부정" ? 5 + (seed % 3) : s.sent === "중립" ? 2 : 1;
      const neu = 2 + (seed % 3);
      return { s, pos, neu, neg, total: pos + neu + neg };
    }).sort((a, b) => b.total - a.total);
  }, [D.stocks]);

  const feed = useMemo(() => {
    let f = [...D.news];
    if (filterTicker) f = f.filter((n) => n.t === filterTicker);
    if (mkt !== "all") {
      f = f.filter((n) => { const st = D.stocks.find((s) => s.t === n.t); return mkt === "hold" ? st && st.hold : st && st.mk === mkt; });
    }
    if (sent !== "all") f = f.filter((n) => n.sent === sent);
    if (q) f = f.filter((n) => { const st = D.stocks.find((s) => s.t === n.t); return (st && st.name.includes(q)) || n.t.includes(q) || n.high.includes(q); });
    return f;
  }, [filterTicker, mkt, sent, q, D]);

  const activeStock = filterTicker ? D.stocks.find((s) => s.t === filterTicker) : null;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 16, alignItems: "start" }}>
      <Panel
        title="관심종목 뉴스"
        sub={`${feed.length}건${activeStock ? " · " + activeStock.name : ""}`}
        right={(
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            {filterTicker && <button onClick={() => setFilterTicker(null)} style={btnGhost}>필터 해제 ✕</button>}
            <FilterTabs value={mkt} onChange={setMkt} options={[{ k: "all", label: "전체" }, { k: "KR", label: "KR" }, { k: "US", label: "US" }, { k: "hold", label: "보유" }]} />
          </div>
        )}
      >
        <div style={{ display: "flex", gap: 10, padding: "11px 16px", borderBottom: `1px solid ${C.line}`, alignItems: "center" }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="종목 검색…" style={{ flex: 1, border: `1px solid ${C.line2}`, borderRadius: 7, padding: "7px 11px", fontSize: 12.5, fontFamily: "var(--sans)", outline: "none", color: C.ink }} />
          <FilterTabs value={sent} onChange={setSent} options={[{ k: "all", label: "전체" }, { k: "긍정", label: "긍정" }, { k: "부정", label: "부정" }]} />
        </div>
        <div style={{ maxHeight: 620, overflowY: "auto" }}>
          {feed.map((n, i) => {
            const st = D.stocks.find((s) => s.t === n.t);
            return (
              <div key={i} style={{ padding: "14px 16px", borderBottom: `1px solid ${C.line}` }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <button onClick={() => nav(n.t)} className="chip-hover" style={{ border: `1px solid ${C.line2}`, background: C.surface, borderRadius: 999, padding: "2px 9px", fontSize: 11, fontWeight: 700, color: C.ink, cursor: "pointer", display: "flex", gap: 5, alignItems: "center" }}>
                    <HoldDot on={st && st.hold} />{st ? st.name : n.t}
                  </button>
                  <SentBadge label={n.sent} sm />
                  <span className="mono" style={{ fontSize: 10, color: C.ink3 }}>{n.time}</span>
                  <span style={{ fontSize: 11, color: C.ink3, marginLeft: "auto" }}>{n.src}</span>
                </div>
                {n.url ? (
                  <a href={n.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 14.5, fontWeight: 700, color: C.ink, lineHeight: 1.4, letterSpacing: "-0.01em", textDecoration: "none", display: "block" }}
                    onMouseEnter={(e) => e.currentTarget.style.color = C.acc}
                    onMouseLeave={(e) => e.currentTarget.style.color = C.ink}>
                    {n.high} <span style={{ fontSize: 11, color: C.acc }}>↗</span>
                  </a>
                ) : (
                  <div style={{ fontSize: 14.5, fontWeight: 700, color: C.ink, lineHeight: 1.4, letterSpacing: "-0.01em" }}>{n.high}</div>
                )}
                {n.body && <div style={{ fontSize: 12.5, color: C.ink2, lineHeight: 1.55, marginTop: 5 }}>{n.body}</div>}
              </div>
            );
          })}
          {feed.length === 0 && <div style={{ padding: 40, textAlign: "center", color: C.ink3, fontSize: 13 }}>해당 조건의 뉴스가 없습니다.</div>}
        </div>
      </Panel>

      <Panel title="종목별 감성" sub="최근 7일 · 클릭 시 필터">
        <div style={{ padding: "6px 0" }}>
          {sentCounts.map(({ s, pos, neu, neg }) => (
            <div key={s.t} onClick={() => setFilterTicker(filterTicker === s.t ? null : s.t)} className="row-hover" style={{
              padding: "10px 16px", cursor: "pointer", borderBottom: `1px solid ${C.line}`,
              background: filterTicker === s.t ? C.accTint : "transparent",
            }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
                <span style={{ fontSize: 12.5, fontWeight: 700, color: C.ink }}>{s.name}</span>
                <SentBadge label={s.sent} score={s.sscore} sm />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <SentStack pos={pos} neu={neu} neg={neg} w={200} />
                <span className="mono" style={{ fontSize: 10, color: C.ink3 }}>{pos + neu + neg}건</span>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
