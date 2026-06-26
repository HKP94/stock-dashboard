// ATLAS — Tabs B: Screener, Market, Research
import { useEffect, useMemo, useState } from 'react';
import {
  C, compColor, flagTone,
  MonoCaps, Num, SentBadge, HoldDot,
  GaugeBar, RegimeBadge, SignalCard, WeightBars, btnGhost,
} from './ui.jsx';
import { InsightHistoryCard, Panel } from './tabsA.jsx';
import {
  analystConsensusGap,
  analystViewCounts,
  buildAiDecompositionBadges,
  cleanDisplayText,
  extractBullets,
  filterStocks,
  hasAnalystCoverage,
  sortStocksByLabel,
} from './display.js';

const API = "http://127.0.0.1:8765";

const grade = (v) => v >= 88 ? "A+" : v >= 80 ? "A" : v >= 72 ? "B+" : v >= 64 ? "B" : v >= 56 ? "C+" : v >= 48 ? "C" : "D";
const gradeCol = (v) => v >= 80 ? C.ok : v >= 64 ? C.warn : v >= 48 ? C.ink2 : C.bad;
const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);
const num = (v, digits = 2) => (v == null ? "—" : Number(v).toLocaleString('ko-KR', { maximumFractionDigits: digits, minimumFractionDigits: digits }));
const deltaLabel = (v, digits = 2) => (v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(digits)}`);
const filterSelectStyle = {
  flex: 1,
  width: "100%",
  minWidth: 0,
  boxSizing: "border-box",
  border: `1px solid ${C.line2}`,
  borderRadius: 7,
  padding: "8px 10px",
  fontSize: 12.5,
  fontFamily: "var(--sans)",
  background: C.surface,
  color: C.ink,
};

function GradeChip({ value }) {
  const col = gradeCol(value);
  return <span className="mono" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", minWidth: 30, padding: "3px 7px", borderRadius: 6, background: col + "14", border: `1px solid ${col}33`, color: col, fontSize: 12.5, fontWeight: 700 }}>{grade(value)}</span>;
}

function Sparkline({ series = [], color = C.acc }) {
  if (!series.length) return <div style={{ height: 30 }} />;
  const values = series.map((point) => Number(point.value)).filter((value) => Number.isFinite(value));
  if (!values.length) return <div style={{ height: 30 }} />;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const width = 120;
  const height = 30;
  const pts = values.map((value, idx) => {
    const x = (idx / Math.max(values.length - 1, 1)) * width;
    const y = height - ((value - min) / range) * height;
    return `${x},${y}`;
  }).join(' ');
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <polyline fill="none" stroke={color} strokeWidth="2.2" points={pts} />
    </svg>
  );
}

function MacroCard({ item }) {
  const tone = item.deltaMonth > 0 ? C.ok : item.deltaMonth < 0 ? C.bad : C.ink2;
  return (
    <div style={{ border: `1px solid ${C.line2}`, borderRadius: 10, padding: "12px 14px", background: C.surface }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <MonoCaps style={{ fontSize: 9.5 }}>{item.region}</MonoCaps>
        <span style={{ fontSize: 13, fontWeight: 700, color: C.ink }}>{item.name}</span>
      </div>
      <div style={{ marginTop: 6, display: "flex", alignItems: "end", justifyContent: "space-between", gap: 8 }}>
        <div>
          <div style={{ fontSize: 21, fontWeight: 800, color: C.ink }}>{num(item.value, item.unit === "%" ? 2 : 1)}</div>
          <div style={{ fontSize: 11.5, color: C.ink3 }}>{item.unit} · {item.asof}</div>
        </div>
        <Sparkline series={item.series} color={tone === C.ink2 ? C.acc : tone} />
      </div>
      <div style={{ marginTop: 8, display: "flex", gap: 14, flexWrap: "wrap" }}>
        <span style={{ fontSize: 11.5, color: C.ink2 }}>전일 대비 <strong style={{ color: item.deltaDay > 0 ? C.ok : item.deltaDay < 0 ? C.bad : C.ink }}>{deltaLabel(item.deltaDay, 2)}</strong></span>
        <span style={{ fontSize: 11.5, color: C.ink2 }}>전월 대비 <strong style={{ color: tone }}>{deltaLabel(item.deltaMonth, 2)}</strong></span>
      </div>
    </div>
  );
}

// ============================ SCREENER ============================
export function Screener({ D, nav }) {
  const [showAll, setShowAll] = useState(false);
  const [sortKey, setSortKey] = useState("comp");
  const [sortDir, setSortDir] = useState("desc");

  const overall = D.market.overall;
  const regimeBasis = D.market.kr?.regimeBasis || D.market.us?.regimeBasis || "";

  const momentum = [...D.stocks].sort((a, b) => b.f.m - a.f.m).slice(0, 9);
  // PR-1: 장기보유 = 안전마진(가치+퀄리티+재무건전성) 복합 기준. 단일 F-Score 7+ 필터 폐기(구조적으로 비어).
  const SAFETY_FLOOR = 55;
  const longterm = [...D.stocks]
    .filter((s) => (s.safety ?? -1) >= SAFETY_FLOOR && s.hasData)
    .sort((a, b) => (b.safety ?? 0) - (a.safety ?? 0))
    .slice(0, 9);

  const sortVal = (s, k) => k === "comp" ? (s.comp ?? -1) : k === "rsi" ? s.rsi : k === "fscore" ? (s.fscore ?? 0) : s.f[k];
  const unified = [...D.stocks].sort((a, b) => {
    const d = sortVal(b, sortKey) - sortVal(a, sortKey);
    return sortDir === "desc" ? d : -d;
  });
  const setSort = (k) => { if (sortKey === k) setSortDir(sortDir === "desc" ? "asc" : "desc"); else { setSortKey(k); setSortDir("desc"); } };

  const Th = ({ k, label }) => <th onClick={k ? () => setSort(k) : undefined} style={{ padding: "9px 10px", textAlign: k ? "right" : "left", cursor: k ? "pointer" : "default", userSelect: "none" }}>
    <MonoCaps style={{ fontSize: 9.5 }} color={sortKey === k ? C.acc : C.ink3}>{label}{sortKey === k ? (sortDir === "desc" ? " ↓" : " ↑") : ""}</MonoCaps>
  </th>;

  return <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
    {/* 개선: 현재 레짐 판정 근거 한 줄 */}
    {regimeBasis && <div style={{ background: C.accTint, border: `1px solid ${C.acc}22`, borderRadius: 10, padding: "11px 18px", display: "flex", alignItems: "center", gap: 12 }}>
      <RegimeBadge regime={overall} regimes={D.regimes} />
      <span style={{ fontSize: 13, color: C.ink2 }}>{regimeBasis}</span>
    </div>}

    <div style={{ background: C.accTint, border: `1px solid ${C.acc}22`, borderRadius: 10, padding: "13px 18px", display: "flex", gap: 24, alignItems: "center" }}>
      <span style={{ fontSize: 13, color: C.ink, lineHeight: 1.5 }}>
        <strong style={{ color: C.acc }}>모멘텀 픽</strong> = 타이밍 시그널(언제 사는가) · <strong style={{ color: C.ink }}>장기 보유 후보</strong> = 안전마진(가치+퀄리티+재무건전성) 종합(무엇을 오래 들고 가는가)
      </span>
    </div>

    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}>
      <Panel title="모멘텀 픽" sub="타이밍 시그널" right={<MonoCaps style={{ fontSize: 9.5 }} color={C.acc}>모멘텀 내림차순</MonoCaps>}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr style={{ borderBottom: `1px solid ${C.line2}` }}>
            {["#", "종목", "모멘텀", "심리", "RSI"].map((h, i) => <th key={i} style={{ padding: "8px 12px", textAlign: i >= 2 ? "right" : "left" }}><MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{h}</MonoCaps></th>)}
          </tr></thead>
          <tbody>
            {momentum.map((s, i) => <tr key={s.t} onClick={() => nav(s.t)} className="row-hover" style={{ borderBottom: `1px solid ${C.line}`, cursor: "pointer" }}>
              <td style={{ padding: "10px 12px" }}><Num size={13} weight={700} color={i < 3 ? C.acc : C.ink3}>{i + 1}</Num></td>
              <td style={{ padding: "10px 12px" }}><div style={{ display: "flex", alignItems: "center", gap: 7 }}><HoldDot on={s.hold} /><span style={{ fontSize: 13, fontWeight: 700 }}>{s.name}</span><span className="mono" style={{ fontSize: 10, color: C.ink3 }}>{s.mk}</span></div></td>
              <td style={{ padding: "10px 12px", textAlign: "right" }}><div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8 }}><Num size={13} weight={600} color={gradeCol(s.f.m)}>{s.f.m}</Num><GradeChip value={s.f.m} /></div></td>
              <td style={{ padding: "10px 12px", textAlign: "right" }}><SentBadge label={s.sent} sm /></td>
              <td style={{ padding: "10px 12px", textAlign: "right" }}><Num size={13} weight={600} color={s.rsi >= 70 ? C.bad : s.rsi <= 35 ? C.acc : C.ink2}>{s.rsi?.toFixed(0)}</Num></td>
            </tr>)}
          </tbody>
        </table>
        <div style={{ padding: "11px 16px", borderTop: `1px solid ${C.line}`, background: C.surface2, borderRadius: "0 0 10px 10px" }}>
          <span style={{ fontSize: 11.5, color: C.ink2 }}><strong style={{ color: C.ink }}>선정 기준</strong> · 모멘텀 점수 상위 + 정배열/골든크로스 등 추세 시그널. 단기 진입 타이밍 판단용.</span>
        </div>
      </Panel>

      <Panel title="장기 보유 후보" sub="안전마진 종합" right={<MonoCaps style={{ fontSize: 9.5 }}>안전마진 ≥ {SAFETY_FLOOR}</MonoCaps>}>
        {longterm.length === 0 ? (
          <div style={{ padding: "28px 18px", textAlign: "center", color: C.ink3, fontSize: 12.5 }}>
            현재 기준(안전마진 {SAFETY_FLOOR}+)을 충족하는 종목이 없습니다.
          </div>
        ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr style={{ borderBottom: `1px solid ${C.line2}` }}>
            {["#", "종목", "안전마진", "가치", "퀄리티", "F-Score"].map((h, i) => <th key={i} style={{ padding: "8px 12px", textAlign: i >= 2 ? "right" : "left" }}><MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{h}</MonoCaps></th>)}
          </tr></thead>
          <tbody>
            {longterm.map((s, i) => <tr key={s.t} onClick={() => nav(s.t)} className="row-hover" style={{ borderBottom: `1px solid ${C.line}`, cursor: "pointer" }}>
              <td style={{ padding: "10px 12px", verticalAlign: "top" }}><Num size={13} weight={700} color={i < 3 ? C.ok : C.ink3}>{i + 1}</Num></td>
              <td style={{ padding: "10px 12px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}><HoldDot on={s.hold} /><span style={{ fontSize: 13, fontWeight: 700 }}>{s.name}</span><span className="mono" style={{ fontSize: 10, color: C.ink3 }}>{s.mk}</span></div>
                {s.safetyReason && <div style={{ fontSize: 10.5, color: C.ink3, marginTop: 2, lineHeight: 1.35 }}>{s.safetyReason}</div>}
              </td>
              <td style={{ padding: "10px 12px", textAlign: "right", verticalAlign: "top" }}><div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8 }}><Num size={13} weight={700} color={gradeCol(s.safety)}>{s.safety}</Num><GradeChip value={s.safety} /></div></td>
              <td style={{ padding: "10px 12px", textAlign: "right", verticalAlign: "top" }}><Num size={13} weight={600} color={gradeCol(s.f.v)}>{s.f.v}</Num></td>
              <td style={{ padding: "10px 12px", textAlign: "right", verticalAlign: "top" }}><Num size={13} weight={600} color={gradeCol(s.f.q)}>{s.f.q}</Num></td>
              <td style={{ padding: "10px 12px", textAlign: "right", verticalAlign: "top" }}>
                <span className="mono" style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12, fontWeight: 700, color: (s.fscore ?? 0) >= 6 ? C.ok : C.warn }}>{s.fscore ?? "—"}<span style={{ color: C.ink3, fontWeight: 500 }}>/9</span></span>
              </td>
            </tr>)}
          </tbody>
        </table>
        )}
        <div style={{ padding: "11px 16px", borderTop: `1px solid ${C.line}`, background: C.surface2, borderRadius: "0 0 10px 10px" }}>
          <span style={{ fontSize: 11.5, color: C.ink2 }}><strong style={{ color: C.ink }}>선정 기준</strong> · 안전마진 = 가치(저평가) 40% + 퀄리티 35% + 재무건전성(F-Score, 없으면 ROE·부채비율) 25%. F-Score는 실질 만점 7(2개 신호 미수집).</span>
        </div>
      </Panel>
    </div>

    <Panel title="전체 종목 · 통합 정렬" sub={`${D.stocks.length}종목 · 컬럼 클릭 시 정렬`}
      right={<button onClick={() => setShowAll(!showAll)} style={{ ...btnGhost, display: "flex", alignItems: "center", gap: 5 }}>{showAll ? "접기 −" : "펼치기 +"}</button>}>
      {showAll && <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr style={{ borderBottom: `1px solid ${C.line2}` }}>
          <Th label="종목" /><Th k="comp" label="종합" /><Th label="신호" /><Th k="m" label="모멘텀" /><Th k="v" label="가치" /><Th k="q" label="우량성" /><Th k="g" label="성장" /><Th k="s" label="심리" /><Th k="rsi" label="RSI" /><Th k="fscore" label="F-Score" />
        </tr></thead>
        <tbody>
          {unified.map((s) => <tr key={s.t} onClick={() => nav(s.t)} className="row-hover" style={{ borderBottom: `1px solid ${C.line}`, cursor: "pointer" }}>
            <td style={{ padding: "9px 10px" }}><div style={{ display: "flex", alignItems: "center", gap: 7 }}><HoldDot on={s.hold} /><span style={{ fontSize: 12.5, fontWeight: 700 }}>{s.name}</span><span className="mono" style={{ fontSize: 9.5, color: C.ink3 }}>{s.t}·{s.mk}</span></div></td>
            <td style={{ padding: "9px 10px", textAlign: "right" }}><Num size={13} weight={700} color={compColor(s.comp ?? 0)}>{s.comp ?? "—"}</Num></td>
            <td style={{ padding: "7px 10px" }}><SignalCard signal={s.signal} compact /></td>
            {["m", "v", "q", "g", "s"].map((k) => <td key={k} style={{ padding: "9px 10px", textAlign: "right" }}><Num size={12.5} weight={600} color={sortKey === k ? gradeCol(s.f[k]) : C.ink2}>{s.f[k]}</Num></td>)}
            <td style={{ padding: "9px 10px", textAlign: "right" }}><Num size={12.5} weight={600} color={s.rsi >= 70 ? C.bad : s.rsi <= 35 ? C.acc : C.ink2}>{s.rsi?.toFixed(0)}</Num></td>
            <td style={{ padding: "9px 10px", textAlign: "right" }}><span className="mono" style={{ fontSize: 12, fontWeight: 700, color: s.fscore >= 7 ? C.ok : C.ink2 }}>{s.fscore ?? "—"}</span></td>
          </tr>)}
        </tbody>
      </table>}
      {!showAll && <div style={{ padding: "16px 18px", color: C.ink3, fontSize: 12.5 }}>펼치기를 눌러 {D.stocks.length}개 종목 전체를 모든 팩터로 정렬하세요.</div>}
    </Panel>
  </div>;
}

// ============================ MARKET ============================
function MarketColumn({ title, m, regimes }) {
  // PR-4: summaryMd(시장 전용 전체 시황)를 불릿으로. 없으면 summary 폴백.
  const bullets = extractBullets(m.summaryMd || "");
  // PR-2: 시장 매력도(진입 환경) — 레짐·시장폭·변동성 종합. 단일 점수 아님, 환경 평가.
  const att = m.attractiveness;
  const envCol = att ? (att.env === "우호" ? C.ok : att.env === "비우호" ? C.bad : C.ink2) : C.ink3;
  // Wave 5-B: 시장 매력도 점수·방향·신뢰도(결정론). 단일 점수 강요 아님 — 근거·신뢰도 동반.
  const ms = m.marketScore;
  const dirCol = ms ? (ms.direction === "강세" ? C.ok : ms.direction === "약세" ? C.bad : C.ink2) : C.ink3;
  return <Panel title={title} right={<RegimeBadge regime={m.regime} regimes={regimes} />}>
    <div style={{ padding: "16px 18px" }}>
      {ms && (
        <div style={{ border: `1px solid ${dirCol}33`, background: dirCol + "0E", borderRadius: 9, padding: "12px 14px", marginBottom: 12 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
            <MonoCaps style={{ fontSize: 9 }} color={C.ink3}>시장 매력도</MonoCaps>
            <Num size={26} weight={800} color={dirCol}>{ms.score}</Num>
            <span style={{ fontSize: 11, color: C.ink3 }}>/100</span>
            <span style={{ fontSize: 13, fontWeight: 800, color: dirCol, background: dirCol + "14", border: `1px solid ${dirCol}33`, borderRadius: 999, padding: "3px 10px" }}>{ms.direction}</span>
            <span style={{ fontSize: 11, color: C.ink2 }}>신뢰도 {ms.confidence}</span>
          </div>
          {ms.components?.subscores && (
            <div style={{ display: "flex", gap: 5, marginTop: 9, flexWrap: "wrap" }}>
              {Object.entries({ trend: "추세", vol: "변동성", macro: "매크로", breadth: "시장폭" }).map(([k, lbl]) =>
                ms.components.subscores[k] != null && (
                  <span key={k} style={{ fontSize: 10, color: C.ink2, background: C.surface2, border: `1px solid ${C.line}`, borderRadius: 5, padding: "2px 6px" }}>
                    {lbl} <b style={{ color: ms.components.subscores[k] > 0 ? C.ok : ms.components.subscores[k] < 0 ? C.bad : C.ink2 }}>{ms.components.subscores[k] > 0 ? "+" : ""}{ms.components.subscores[k]}</b>
                  </span>
                ))}
            </div>
          )}
          {ms.divergenceNote && (
            <div style={{ fontSize: 11, color: C.warn, marginTop: 8, lineHeight: 1.5 }}>⚠ {ms.divergenceNote}</div>
          )}
          <div style={{ fontSize: 10.5, color: C.ink3, marginTop: 7 }}>환경·방향 평가일 뿐 매매 신호가 아닙니다.</div>
        </div>
      )}
      {att && (
        <div style={{ border: `1px solid ${envCol}33`, background: envCol + "0E", borderRadius: 9, padding: "12px 14px", marginBottom: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <MonoCaps style={{ fontSize: 9 }} color={C.ink3}>진입 환경</MonoCaps>
            <span style={{ fontSize: 15, fontWeight: 800, color: envCol }}>{att.env}</span>
            <span style={{ marginLeft: "auto", fontSize: 11, color: C.ink2 }}>{att.basis}</span>
          </div>
          <div style={{ fontSize: 11.5, color: C.ink2, marginTop: 6, lineHeight: 1.5 }}>{att.note}</div>
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 18 }}>
        {m.idx.map((ix) => <div key={ix.k} style={{ border: `1px solid ${C.line2}`, borderRadius: 8, padding: "11px 14px" }}>
          <MonoCaps style={{ fontSize: 9.5 }}>{ix.k}</MonoCaps>
          <div style={{ marginTop: 3 }}><Num size={20} weight={700}>{ix.v}</Num></div>
          <div style={{ marginTop: 2 }}>
            {ix.chg == null
              ? <span className="tnum" style={{ fontSize: 12.5, fontWeight: 600, color: C.ink3 }}>—</span>
              : <span className="tnum" style={{ fontSize: 12.5, fontWeight: 600, color: ix.chg > 0 ? C.ok : ix.chg < 0 ? C.bad : C.ink3 }}>{ix.chg > 0 ? "▲ +" : ix.chg < 0 ? "▼ " : "· "}{ix.chg.toFixed(2)}%</span>}
          </div>
        </div>)}
      </div>
      <MonoCaps style={{ fontSize: 9.5 }}>시장폭 · 변동성</MonoCaps>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, margin: "10px 0 18px" }}>
        {m.gauges.map((g) => <div key={g.label}>
          <div style={{ fontSize: 12, color: C.ink2, marginBottom: 5 }}>{g.label}</div>
          <GaugeBar value={g.v} max={g.label.includes("RSI") || g.label.includes("VIX") ? (g.label.includes("VIX") ? 40 : 100) : 100} tone={g.tone} suffix={g.unit} />
        </div>)}
      </div>
      <div style={{ borderTop: `1px solid ${C.line}`, paddingTop: 14 }}>
        <MonoCaps style={{ fontSize: 9.5 }} color={C.acc}>Gemini 시황 종합 ({title.includes("한국") ? "한국 전용" : "미국 전용"})</MonoCaps>
        {bullets.length > 0 ? (
          <ul style={{ margin: "8px 0 0", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
            {bullets.map((b, i) => (
              <li key={i} style={{ display: "flex", gap: 8, fontSize: 13, color: C.ink, lineHeight: 1.6 }}>
                <span style={{ color: C.acc, fontWeight: 800, flexShrink: 0 }}>·</span><span>{b}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p style={{ margin: "8px 0 0", fontSize: 13, color: C.ink3, lineHeight: 1.65 }}>{cleanDisplayText(m.summary || "시황 분석 준비 중입니다.")}</p>
        )}
      </div>
    </div>
  </Panel>;
}

export function Market({ D }) {
  const overall = D.market.overall;
  const w = D.regimes[overall].w;
  const newsSummary = D.market.newsSummary || {};
  const macro = D.market.macro || {};
  const refreshContext = D.refreshContext || D.market.refreshContext || {};
  const strategyGuidance = D.strategyGuidance;
  const [marketText, setMarketText] = useState("");
  const [marketSource, setMarketSource] = useState("");
  const [marketSourceUrl, setMarketSourceUrl] = useState("");
  const [marketSaving, setMarketSaving] = useState(false);
  const [marketError, setMarketError] = useState("");
  const [marketManualLatest, setMarketManualLatest] = useState(D.market.manualViewLatest || null);
  const [marketManualHistory, setMarketManualHistory] = useState(D.market.manualViewHistory || []);
  const [showMarketHistory, setShowMarketHistory] = useState(false);
  const interp = overall === "bull"
    ? "강세 국면 — 모멘텀 비중을 최대(45%)로 끌어올려 추세에 올라타되, 심리·과열 신호로 진입 타이밍을 조절합니다."
    : overall === "neutral"
      ? "중립 국면 — 모멘텀과 가치·우량성을 균형 있게 배분합니다. 추세에 일부 올라타되 펀더멘털이 받쳐주는 종목 위주로 선별합니다."
      : "약세 국면 — 우량성(45%)·가치(35%)에 무게를 실어 방어합니다. 모멘텀 비중을 최소화하고 재무 건전성 높은 종목으로 포트폴리오를 압축합니다.";

  useEffect(() => {
    let active = true;
    fetch(`${API}/api/market-manual`)
      .then((response) => response.ok ? response.json() : null)
      .then((payload) => {
        if (!active || !payload) return;
        setMarketManualLatest(payload.latest || null);
        setMarketManualHistory(payload.history || []);
      })
      .catch(() => {});
    return () => { active = false; };
  }, []);

  const submitMarketManual = async () => {
    if (!marketText.trim()) return;
    setMarketSaving(true);
    setMarketError("");
    try {
      const response = await fetch(`${API}/api/market-manual`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          asof: new Date().toISOString().slice(0, 10),
          raw_text: marketText,
          source: marketSource || null,
          source_url: marketSourceUrl || null,
        }),
      });
      if (!response.ok) throw new Error("market manual submit failed");
      const payload = await response.json();
      setMarketText("");
      setMarketSource("");
      setMarketSourceUrl("");
      setMarketManualLatest(payload.latest || null);
      setMarketManualHistory(payload.history || []);
    } catch (_) {
      setMarketError("시장 분석 저장에 실패했습니다. 로컬 API 상태를 확인해 주세요.");
    } finally {
      setMarketSaving(false);
    }
  };

  return <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
    {refreshContext.label && (
      <div style={{ border: `1px solid ${C.line2}`, background: C.surface2, borderRadius: 10, padding: "12px 16px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <MonoCaps style={{ fontSize: 9 }} color={C.ink3}>업데이트 기준</MonoCaps>
          <span style={{ fontSize: 13, fontWeight: 800, color: C.ink }}>{refreshContext.label}</span>
        </div>
        {refreshContext.note && (
          <div style={{ marginTop: 6, fontSize: 12, color: C.ink2, lineHeight: 1.55 }}>{refreshContext.note}</div>
        )}
      </div>
    )}

    {strategyGuidance?.primary && (
      <Panel title="현재 국면 추천 전략" sub="표시 전용 · true track 우선">
        <div style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ border: `1px solid ${C.acc}33`, background: C.accTint, borderRadius: 10, padding: "14px 16px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{strategyGuidance.label}</MonoCaps>
              <span style={{ fontSize: 18, fontWeight: 800, color: C.acc }}>{strategyGuidance.primary.label}</span>
              <span style={{ fontSize: 11, fontWeight: 700, color: C.ok, background: C.okBg, border: `1px solid ${C.ok}33`, borderRadius: 999, padding: "3px 8px" }}>true</span>
              <span style={{ marginLeft: "auto", fontSize: 12, color: C.ink2 }}>신뢰도 {strategyGuidance.primary.confidence}</span>
            </div>
            <div style={{ marginTop: 8, fontSize: 13, color: C.ink, lineHeight: 1.65 }}>{strategyGuidance.primary.reason}</div>
            <div style={{ marginTop: 10, display: "flex", gap: 10, flexWrap: "wrap" }}>
              <span style={{ fontSize: 12, color: C.ink2 }}>국면 수익률 {pct(strategyGuidance.primary.regimeReturn)}</span>
              <span style={{ fontSize: 12, color: C.ink2 }}>근거 구간 {strategyGuidance.primary.horizon}</span>
            </div>
          </div>

          {strategyGuidance.reference && (
            <div style={{ border: `1px solid ${C.warn}33`, background: C.warnBg, borderRadius: 10, padding: "12px 14px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: C.warn }}>참고용 회고</span>
                <span style={{ fontSize: 12, color: C.ink }}>{strategyGuidance.reference.label}</span>
                <span style={{ fontSize: 11, color: C.ink2 }}>{pct(strategyGuidance.reference.regimeReturn)} · {strategyGuidance.reference.horizon}</span>
              </div>
              <div style={{ marginTop: 6, fontSize: 12, color: C.ink2, lineHeight: 1.6 }}>{strategyGuidance.reference.reason}</div>
              {strategyGuidance.reference.warning && (
                <div style={{ marginTop: 6, fontSize: 11.5, color: C.bad }}>{strategyGuidance.reference.warning}</div>
              )}
            </div>
          )}

          <div style={{ fontSize: 11.5, color: C.ink3 }}>{strategyGuidance.note}</div>
        </div>
      </Panel>
    )}

    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}>
      <MarketColumn title="🇰🇷 한국 시장" m={D.market.kr} regimes={D.regimes} />
      <MarketColumn title="🇺🇸 미국 시장" m={D.market.us} regimes={D.regimes} />
    </div>

    <Panel title="거시 환경" sub={macro.asof ? `${macro.asof} 기준` : "최근 거시 지표"}>
      <div style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 16 }}>
          <div style={{ border: `1px solid ${C.line2}`, borderRadius: 10, padding: "14px 16px", background: C.surface2 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>Macro</MonoCaps>
              <span style={{ fontSize: 18, fontWeight: 800, color: C.acc }}>{macro.summary?.headline || "거시 환경 요약 준비 중"}</span>
            </div>
            {macro.summary?.summaryMd ? (
              <ul style={{ margin: "10px 0 0", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
                {extractBullets(macro.summary.summaryMd, { limit: 4 }).map((bullet, idx) => (
                  <li key={idx} style={{ display: "flex", gap: 8, fontSize: 13, color: C.ink, lineHeight: 1.6 }}>
                    <span style={{ color: C.acc, fontWeight: 800, flexShrink: 0 }}>·</span><span>{bullet}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div style={{ marginTop: 10, fontSize: 12.5, color: C.ink3 }}>거시 요약 생성 전입니다.</div>
            )}
            <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div style={{ border: `1px solid ${C.ok}33`, background: C.ok + "10", borderRadius: 9, padding: "10px 12px" }}>
                <MonoCaps style={{ fontSize: 9.5 }} color={C.ok}>우호 해석</MonoCaps>
                <div style={{ marginTop: 6, fontSize: 12.5, color: C.ink, lineHeight: 1.6 }}>{cleanDisplayText(macro.summary?.support || "—")}</div>
              </div>
              <div style={{ border: `1px solid ${C.bad}33`, background: C.bad + "10", borderRadius: 9, padding: "10px 12px" }}>
                <MonoCaps style={{ fontSize: 9.5 }} color={C.bad}>부담 해석</MonoCaps>
                <div style={{ marginTop: 6, fontSize: 12.5, color: C.ink, lineHeight: 1.6 }}>{cleanDisplayText(macro.summary?.oppose || "—")}</div>
              </div>
            </div>
            {!!macro.summary?.watchPoints?.length && (
              <div style={{ marginTop: 12, fontSize: 12, color: C.ink2 }}>
                체크포인트: {macro.summary.watchPoints.map((item) => cleanDisplayText(item)).join(" · ")}
              </div>
            )}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 10 }}>
            {(macro.indicators || []).slice(0, 4).map((item) => <MacroCard key={item.code} item={item} />)}
          </div>
        </div>

        {macro.indicators?.length > 4 && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
            {macro.indicators.slice(4).map((item) => <MacroCard key={item.code} item={item} />)}
          </div>
        )}
      </div>
    </Panel>

    <Panel title="오늘의 시장 뉴스 요약" sub={newsSummary.asof ? `${newsSummary.asof} 기준` : "최근 시장 헤드라인 기반"}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, padding: "16px 18px" }}>
        {[
          ["한국", newsSummary.krSummary],
          ["미국", newsSummary.usSummary],
          ["글로벌", newsSummary.globalSummary],
        ].map(([label, body]) => (
          <div key={label} style={{ border: `1px solid ${C.line2}`, borderRadius: 10, padding: "14px 14px 15px", background: C.surface2 }}>
            <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{label}</MonoCaps>
            <p style={{ margin: "8px 0 0", fontSize: 13, color: body ? C.ink : C.ink3, lineHeight: 1.65 }}>
              {body || "시장 뉴스 요약 준비 중입니다."}
            </p>
          </div>
        ))}
      </div>
    </Panel>

    <Panel title="직접 입력 시장 분석" sub="외부 시장 코멘트 · AI 분해">
      <div style={{ padding: "16px 18px", display: "grid", gridTemplateColumns: "1fr 1.1fr", gap: 16, alignItems: "start" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <textarea
            value={marketText}
            onChange={(event) => setMarketText(event.target.value)}
            placeholder="시장 전망·매크로 코멘트·리포트 요약을 붙여넣으세요."
            style={{ width: "100%", minHeight: 170, border: `1px solid ${C.line2}`, borderRadius: 8, padding: "10px 12px", fontSize: 12.5, color: C.ink, resize: "vertical", boxSizing: "border-box", outline: "none" }}
          />
          <input
            value={marketSource}
            onChange={(event) => setMarketSource(event.target.value)}
            placeholder="출처 메모"
            style={{ width: "100%", border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 12.5, color: C.ink, boxSizing: "border-box", outline: "none" }}
          />
          <input
            value={marketSourceUrl}
            onChange={(event) => setMarketSourceUrl(event.target.value)}
            placeholder="출처 URL (선택)"
            style={{ width: "100%", border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 12.5, color: C.ink, boxSizing: "border-box", outline: "none" }}
          />
          <button
            onClick={submitMarketManual}
            disabled={marketSaving || !marketText.trim()}
            style={{ border: "none", borderRadius: 8, padding: "10px 12px", background: C.ink, color: "#fff", fontSize: 12.5, fontWeight: 700, cursor: "pointer", opacity: marketSaving || !marketText.trim() ? 0.45 : 1 }}
          >
            {marketSaving ? "분석 중…" : "시장 분석"}
          </button>
          {marketError && <div style={{ fontSize: 11.5, color: C.bad }}>{marketError}</div>}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {!marketManualLatest ? (
            <div style={{ border: `1px solid ${C.line}`, borderRadius: 10, padding: "18px 16px", background: C.surface2, fontSize: 12.5, color: C.ink3 }}>
              직접 입력한 시장 분석이 없습니다.
            </div>
          ) : (
            <div style={{ border: `1px solid ${C.line}`, borderRadius: 10, overflow: "hidden" }}>
              <div style={{ padding: "12px 14px", display: "flex", alignItems: "center", gap: 8, borderBottom: `1px solid ${C.line}`, background: C.surface2 }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: C.acc, background: C.accTint, border: `1px solid ${C.acc}33`, borderRadius: 999, padding: "4px 9px" }}>직접입력</span>
                <span style={{ fontSize: 11.5, color: C.ink2 }}>{marketManualLatest.asof}</span>
              </div>
              <div style={{ padding: "14px 16px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <div style={{ border: `1px solid ${C.ok}33`, borderRadius: 8, background: C.ok + "10", padding: "10px 12px" }}>
                  <MonoCaps style={{ fontSize: 9.5 }} color={C.ok}>강세 시나리오</MonoCaps>
                  <div style={{ marginTop: 7, fontSize: 12.5, color: C.ink, lineHeight: 1.65 }}>{cleanDisplayText(marketManualLatest.bullScenario || "수집된 강세 시나리오 없음")}</div>
                </div>
                <div style={{ border: `1px solid ${C.bad}33`, borderRadius: 8, background: C.bad + "10", padding: "10px 12px" }}>
                  <MonoCaps style={{ fontSize: 9.5 }} color={C.bad}>약세 시나리오</MonoCaps>
                  <div style={{ marginTop: 7, fontSize: 12.5, color: C.ink, lineHeight: 1.65 }}>{cleanDisplayText(marketManualLatest.bearScenario || "수집된 약세 시나리오 없음")}</div>
                </div>
              </div>
              <details style={{ padding: "0 16px 14px" }}>
                <summary style={{ cursor: "pointer", fontSize: 11.5, color: C.ink2 }}>원문 보기</summary>
                <div style={{ marginTop: 10, whiteSpace: "pre-wrap", fontSize: 12, lineHeight: 1.6, color: C.ink2, background: C.surface2, border: `1px solid ${C.line}`, borderRadius: 8, padding: "10px 12px" }}>
                  {marketManualLatest.rawText}
                </div>
              </details>
            </div>
          )}

          <Panel
            title="과거 입력 보기"
            sub={`${marketManualHistory.length}건`}
            right={<button onClick={() => setShowMarketHistory((v) => !v)} style={{ ...btnGhost, fontSize: 11.5 }}>{showMarketHistory ? "접기 −" : "펼치기 +"}</button>}
          >
            {!showMarketHistory ? (
              <div style={{ padding: "16px", fontSize: 12, color: C.ink3 }}>
                {marketManualHistory.length ? "최신 입력만 보이는 상태입니다. 펼치면 이전 시장 분석을 확인할 수 있습니다." : "직접 입력한 시장 분석 이력이 없습니다."}
              </div>
            ) : (
              <div style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
                {marketManualHistory.map((entry) => (
                  <div key={entry.id} style={{ border: `1px solid ${C.line}`, borderRadius: 8, padding: "10px 12px", background: C.surface2 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: C.acc }}>#{entry.id}</span>
                      <span style={{ fontSize: 11, color: C.ink3 }}>{entry.asof}</span>
                    </div>
                    <div style={{ marginTop: 8, fontSize: 12, color: C.ink2, lineHeight: 1.55 }}>
                      강세: {cleanDisplayText(entry.bullScenario || "없음")}
                    </div>
                    <div style={{ marginTop: 4, fontSize: 12, color: C.ink2, lineHeight: 1.55 }}>
                      약세: {cleanDisplayText(entry.bearScenario || "없음")}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>
      </div>
    </Panel>

    <Panel title="현재 국면 → 전략 가중치" sub="동적 팩터 모델">
      <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", gap: 0 }}>
        <div style={{ padding: "20px 22px", borderRight: `1px solid ${C.line}` }}>
          <MonoCaps style={{ fontSize: 9.5 }}>종합 국면</MonoCaps>
          <div style={{ margin: "10px 0 14px" }}><RegimeBadge regime={overall} lg regimes={D.regimes} /></div>
          <p style={{ fontSize: 13, color: C.ink2, lineHeight: 1.65, margin: 0 }}>{interp}</p>
          <div style={{ marginTop: 16, display: "flex", gap: 14 }}>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: C.acc }}></span><span style={{ fontSize: 11, color: C.ink2 }}>타이밍 그룹</span></span>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: C.ink, opacity: 0.85 }}></span><span style={{ fontSize: 11, color: C.ink2 }}>미스프라이싱 그룹</span></span>
          </div>
        </div>
        <div style={{ padding: "20px 22px" }}>
          <WeightBars w={w} />
          <div style={{ marginTop: 16, paddingTop: 14, borderTop: `1px solid ${C.line}`, display: "flex", gap: 20 }}>
            {["bull", "neutral", "bear"].map((r) => <div key={r} style={{ flex: 1, padding: "10px 12px", borderRadius: 8, border: `1px solid ${r === overall ? C.acc : C.line2}`, background: r === overall ? C.accTint : C.surface }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}><RegimeBadge regime={r} regimes={D.regimes} /></div>
              <div className="mono" style={{ fontSize: 10.5, color: C.ink2, lineHeight: 1.7 }}>
                모멘텀 {D.regimes[r].w.m} · 가치 {D.regimes[r].w.v} · 우량성 {D.regimes[r].w.q}<br />성장 {D.regimes[r].w.g} · 심리 {D.regimes[r].w.s}
              </div>
            </div>)}
          </div>
        </div>
      </div>
    </Panel>
  </div>;
}

const trendValue = (point) => Number(point?.targetPrice);

function fmtConsensusPrice(value, currency) {
  if (value == null) return "—";
  return currency === "₩"
    ? `₩${Math.round(Number(value)).toLocaleString("ko-KR")}`
    : `$${Number(value).toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

function pctText(value) {
  return value == null ? "—" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}%`;
}

function ratingTone(label) {
  if (label === "매수") return { bg: C.ok + "14", border: C.ok + "33", color: C.ok };
  if (label === "중립") return { bg: C.warnBg, border: C.warn + "33", color: C.warn };
  if (label === "매도") return { bg: C.bad + "14", border: C.bad + "33", color: C.bad };
  return { bg: C.surface2, border: C.line2, color: C.ink2 };
}

function ConsensusStat({ label, value, note, tone = "neutral" }) {
  const color = tone === "ok" ? C.ok : tone === "bad" ? C.bad : tone === "warn" ? C.warn : C.ink;
  return (
    <div style={{ border: `1px solid ${C.line}`, borderRadius: 9, padding: "12px 14px", background: C.surface2 }}>
      <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{label}</MonoCaps>
      <div style={{ marginTop: 6, fontSize: 20, fontWeight: 800, color }}>{value}</div>
      <div style={{ marginTop: 4, fontSize: 11.5, color: note ? C.ink2 : C.ink3 }}>{note || "데이터 없음"}</div>
    </div>
  );
}

function ConsensusSummaryCard({ stock }) {
  const consensus = stock?.consensus;
  if (!consensus) {
    return (
      <Panel title="컨센서스 요약" sub="목표가 · 의견 · EPS 전망">
        <div style={{ padding: "26px 18px", fontSize: 12.5, color: C.ink3 }}>
          컨센서스 미수집
        </div>
      </Panel>
    );
  }

  const gap = analystConsensusGap(consensus, stock?.price);
  const labelTone = ratingTone(consensus.ratingLabel);

  return (
    <Panel title="컨센서스 요약" sub="최신 기준 원자료">
      <div style={{ padding: "14px 16px 16px", display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 12 }}>
        <ConsensusStat
          label="목표가"
          value={fmtConsensusPrice(consensus.targetPrice, stock?.cur)}
          note={consensus.asof ? `기준일 ${consensus.asof}` : "기준일 미상"}
        />
        <ConsensusStat
          label="현재가 대비 괴리율"
          value={pctText(gap)}
          note={stock?.price != null ? `현재가 ${fmtConsensusPrice(stock.price, stock.cur)}` : "현재가 없음"}
          tone={gap != null ? (gap >= 0.1 ? "ok" : gap < 0 ? "bad" : "warn") : "neutral"}
        />
        <div style={{ border: `1px solid ${C.line}`, borderRadius: 9, padding: "12px 14px", background: C.surface2 }}>
          <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>투자의견</MonoCaps>
          <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ display: "inline-flex", alignItems: "center", borderRadius: 999, padding: "5px 10px", fontSize: 12, fontWeight: 700, background: labelTone.bg, border: `1px solid ${labelTone.border}`, color: labelTone.color }}>
              {consensus.ratingLabel || "의견 없음"}
            </span>
            <span style={{ fontSize: 12, color: C.ink2 }}>
              {consensus.nAnalysts != null ? `${consensus.nAnalysts}명 기준` : "참여 인원 미상"}
            </span>
          </div>
          <div style={{ marginTop: 7, fontSize: 11.5, color: C.ink3 }}>{consensus.source || "출처 미상"}</div>
        </div>
        <ConsensusStat
          label="EPS 전망"
          value={consensus.epsFwd != null ? Number(consensus.epsFwd).toLocaleString("en-US", { maximumFractionDigits: 2 }) : "—"}
          note={consensus.epsFwd != null ? "향후 EPS 전망치" : "EPS 전망 미수집"}
        />
      </div>
    </Panel>
  );
}

function ConsensusTrendCard({ history = [], currency }) {
  const usable = history.filter((point) => Number.isFinite(trendValue(point)));
  const latest = usable[usable.length - 1];

  return (
    <Panel title="목표가 · 의견 추이" sub={usable.length > 1 ? "시계열이 있는 만큼 표시" : "단일 관측치"}>
      {usable.length === 0 ? (
        <div style={{ padding: "26px 18px", fontSize: 12.5, color: C.ink3 }}>
          추이 데이터가 없습니다.
        </div>
      ) : usable.length === 1 ? (
        <div style={{ padding: "18px 16px" }}>
          <div style={{ fontSize: 24, fontWeight: 800, color: C.ink }}>{fmtConsensusPrice(latest.targetPrice, currency)}</div>
          <div style={{ marginTop: 6, fontSize: 12, color: C.ink2 }}>{latest.asof} · {latest.ratingLabel || "의견 미상"}</div>
        </div>
      ) : (
        <div style={{ padding: "14px 16px 16px" }}>
          <div style={{ display: "flex", alignItems: "end", gap: 16, marginBottom: 8 }}>
            <div>
              <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>최신 목표가</MonoCaps>
              <div style={{ fontSize: 22, fontWeight: 800, color: C.ink }}>{fmtConsensusPrice(latest.targetPrice, currency)}</div>
            </div>
            <div style={{ fontSize: 12, color: C.ink2 }}>{latest.asof} · {latest.ratingLabel || "의견 미상"}</div>
          </div>
          <Sparkline series={usable.map((point) => ({ value: point.targetPrice }))} color={C.acc} />
          <div style={{ marginTop: 10, display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", fontSize: 11.5, color: C.ink3 }}>
            <span>{usable[0].asof}</span>
            <span>{usable[usable.length - 1].asof}</span>
          </div>
        </div>
      )}
    </Panel>
  );
}

function AnalystPointsCard({ title, tone, points, emptyText }) {
  const count = points.length;
  const color = tone === "bull" ? C.ok : C.bad;
  return (
    <Panel
      title={title}
      sub={`${count}건`}
      right={<span style={{ fontSize: 11.5, fontWeight: 700, color, background: color + "14", border: `1px solid ${color}33`, borderRadius: 999, padding: "4px 10px" }}>{count}건</span>}
    >
      {points.length === 0 ? (
        <div style={{ padding: "24px 18px", fontSize: 12.5, color: C.ink3 }}>{emptyText}</div>
      ) : (
        <div style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
          {points.map((item, idx) => (
            <div key={`${tone}-${idx}-${item.point}`} style={{ border: `1px solid ${C.line}`, borderRadius: 8, background: C.surface2, padding: "10px 12px" }}>
              <div style={{ fontSize: 12.5, color: C.ink, lineHeight: 1.6 }}>{cleanDisplayText(item.point)}</div>
              <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                {item.asof && <span className="mono" style={{ fontSize: 10, color: C.ink3 }}>{item.asof}</span>}
                {item.source && <span style={{ fontSize: 10.5, color: C.ink3 }}>{item.source}</span>}
                {item.sourceUrl ? (
                  <a href={item.sourceUrl} target="_blank" rel="noopener noreferrer" style={{ marginLeft: "auto", fontSize: 11, fontWeight: 700, color, textDecoration: "none" }}>
                    원문 보기 ↗
                  </a>
                ) : (
                  <span style={{ marginLeft: "auto", fontSize: 10.5, color: C.ink3 }}>원문 링크 없음</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function buildAiSummaryFromEntry(entry) {
  if (!entry) return null;
  return {
    entryId: entry.id,
    labels: Object.fromEntries((entry.horizons || []).map((item) => [item.horizon, item.attractivenessLabel])),
    bullCount: (entry.bull || []).length,
    bearCount: (entry.bear || []).length,
  };
}

function _manual_research_summary_fallback(entry, existing) {
  return existing || buildAiSummaryFromEntry(entry);
}

function ManualAiDecompositionCard({ entry, summary, emptyText = "직접 입력한 분석 없음" }) {
  const [showRaw, setShowRaw] = useState(false);
  const badges = buildAiDecompositionBadges(summary);
  if (!entry) {
    return (
      <Panel title="AI 분해 분석" sub="외부 자료 구조화">
        <div style={{ padding: "24px 18px", fontSize: 12.5, color: C.ink3 }}>{emptyText}</div>
      </Panel>
    );
  }
  return (
    <Panel title="AI 분해 분석" sub="최신 직접 입력 1건">
      <div style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: C.acc, background: C.accTint, border: `1px solid ${C.acc}33`, borderRadius: 999, padding: "4px 9px" }}>직접입력</span>
          {(badges.length ? badges : ["단·중·장 분석 대기"]).map((badge) => (
            <span key={badge} style={{ fontSize: 11, fontWeight: 700, color: C.ink2, background: C.surface2, border: `1px solid ${C.line2}`, borderRadius: 999, padding: "4px 9px" }}>{badge}</span>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10 }}>
          {(entry.horizons || []).map((item) => (
            <div key={item.horizon} style={{ border: `1px solid ${C.line}`, borderRadius: 8, padding: "10px 12px", background: C.surface2 }}>
              <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{item.horizon === "short" ? "단기" : item.horizon === "mid" ? "중기" : "장기"}</MonoCaps>
              <div style={{ marginTop: 6, fontSize: 14, fontWeight: 800, color: C.ink }}>{item.attractivenessLabel}</div>
              <div style={{ marginTop: 6, fontSize: 12, lineHeight: 1.6, color: C.ink2 }}>{cleanDisplayText(item.rationale)}</div>
            </div>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, padding: "10px 12px", background: C.surface2 }}>
            <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>강세 논거</MonoCaps>
            <div style={{ marginTop: 6, fontSize: 12, color: C.ink }}>{(entry.bull || []).length ? `${entry.bull.length}건` : "수집된 강세 논거 없음"}</div>
          </div>
          <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, padding: "10px 12px", background: C.surface2 }}>
            <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>약세 논거</MonoCaps>
            <div style={{ marginTop: 6, fontSize: 12, color: C.ink }}>{(entry.bear || []).length ? `${entry.bear.length}건` : "수집된 약세 논거 없음"}</div>
          </div>
        </div>
        {entry.consensus && (
          <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, padding: "10px 12px", background: C.surface2 }}>
            <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>원문에서 추출한 컨센서스</MonoCaps>
            <div style={{ marginTop: 6, fontSize: 12.5, color: C.ink }}>
              {entry.consensus.targetPrice != null ? `목표가 ${entry.consensus.targetPrice.toLocaleString("ko-KR")}` : "목표가 미추출"}
              {" · "}
              {entry.consensus.ratingLabel || "의견 미추출"}
            </div>
          </div>
        )}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <button onClick={() => setShowRaw((v) => !v)} style={{ ...btnGhost, fontSize: 11.5 }}>
            {showRaw ? "원문 숨기기" : "원문 보기"}
          </button>
          <span style={{ fontSize: 11, color: C.ink3 }}>{entry.createdAt ? `입력 시각 ${entry.createdAt}` : "입력 시각 미상"}</span>
        </div>
        {showRaw && (
          <div style={{ whiteSpace: "pre-wrap", fontSize: 12, lineHeight: 1.6, color: C.ink2, background: C.surface2, border: `1px solid ${C.line}`, borderRadius: 8, padding: "10px 12px" }}>
            {entry.rawText}
          </div>
        )}
      </div>
    </Panel>
  );
}

export function Research({ D, nav }) {
  const [ticker, setTicker] = useState(D.stocks[0]?.t);
  const [stockQuery, setStockQuery] = useState("");
  const [marketFilter, setMarketFilter] = useState("all");
  const [sectorFilter, setSectorFilter] = useState("all");
  const [manualText, setManualText] = useState("");
  const [manualSource, setManualSource] = useState("");
  const [manualSourceUrl, setManualSourceUrl] = useState("");
  const [manualSaving, setManualSaving] = useState(false);
  const [manualError, setManualError] = useState("");
  const [showManualHistory, setShowManualHistory] = useState(false);
  const [manualLatest, setManualLatest] = useState(null);
  const [manualHistory, setManualHistory] = useState([]);

  const sectors = useMemo(
    () => [...new Set(D.stocks.map((stock) => stock.sec).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ko")),
    [D.stocks],
  );
  const sorted = useMemo(
    () => sortStocksByLabel(D.stocks),
    [D.stocks],
  );
  const filteredStocks = useMemo(
    () => filterStocks(sorted, { query: stockQuery, market: marketFilter, sector: sectorFilter }),
    [sorted, stockQuery, marketFilter, sectorFilter],
  );

  useEffect(() => {
    if (!filteredStocks.length) return;
    if (!filteredStocks.some((stock) => stock.t === ticker)) setTicker(filteredStocks[0].t);
  }, [filteredStocks, ticker]);

  const s = D.stocks.find((x) => x.t === ticker) || filteredStocks[0] || D.stocks[0];
  const counts = analystViewCounts(s?.analystViews);

  useEffect(() => {
    if (!s?.t) return;
    let active = true;
    setManualLatest(s.manualResearchLatest || null);
    setManualHistory(s.manualResearchHistory || []);
    fetch(`${API}/api/manual-research/${s.t}`)
      .then((response) => response.ok ? response.json() : null)
      .then((payload) => {
        if (!active || !payload) return;
        setManualLatest(payload.latest || null);
        setManualHistory(payload.history || []);
      })
      .catch(() => {});
    return () => { active = false; };
  }, [s?.t, s?.manualResearchLatest, s?.manualResearchHistory]);

  const submitManualResearch = async () => {
    if (!manualText.trim() || !s?.t) return;
    setManualSaving(true);
    setManualError("");
    try {
      const response = await fetch(`${API}/api/manual-research`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: s.t,
          raw_text: manualText,
          source: manualSource || null,
          source_url: manualSourceUrl || null,
        }),
      });
      if (!response.ok) throw new Error("manual research submit failed");
      const payload = await response.json();
      setManualText("");
      setManualSource("");
      setManualSourceUrl("");
      setManualLatest(payload.latest || null);
      setManualHistory(payload.history || []);
    } catch (_) {
      setManualError("직접 입력 분석 저장에 실패했습니다. 로컬 API 상태를 확인해 주세요.");
    } finally {
      setManualSaving(false);
    }
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", gap: 16, alignItems: "start" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <Panel title="종목 선택" sub={`${D.stocks.length}종목`}>
          <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
            <input value={stockQuery} onChange={(event) => setStockQuery(event.target.value)} placeholder="티커·종목명 검색"
              style={{ width: "100%", border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 12.5, color: C.ink, outline: "none", boxSizing: "border-box" }} />
            <div style={{ display: "flex", gap: 8 }}>
              <select value={marketFilter} onChange={(event) => setMarketFilter(event.target.value)}
                style={filterSelectStyle}>
                <option value="all">전체 시장</option>
                <option value="KR">한국</option>
                <option value="US">미국</option>
              </select>
              <select value={sectorFilter} onChange={(event) => setSectorFilter(event.target.value)}
                style={filterSelectStyle}>
                <option value="all">전체 섹터</option>
                {sectors.map((sector) => <option key={sector} value={sector}>{sector}</option>)}
              </select>
            </div>
            <select
              value={s?.t || ""}
              onChange={(e) => setTicker(e.target.value)}
              disabled={filteredStocks.length === 0}
              style={{ width: "100%", border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 13, fontFamily: "var(--sans)", color: C.ink, background: C.surface, cursor: "pointer", outline: "none" }}
            >
              {filteredStocks.length === 0 ? (
                <option value="">검색 결과 없음</option>
              ) : (
                filteredStocks.map((x) => (
                  <option key={x.t} value={x.t}>
                    {x.name} ({x.t})
                  </option>
                ))
              )}
            </select>
          </div>
        </Panel>

        <Panel title="선택 종목 요약" sub="애널리스트 뷰 기준">
          <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
                <HoldDot on={s?.hold} />
                <span style={{ fontSize: 16, fontWeight: 800, color: C.ink }}>{s?.name}</span>
                <span className="mono" style={{ fontSize: 10.5, color: C.ink3 }}>{s?.t} · {s?.mk}</span>
              </div>
              <div style={{ marginTop: 4, fontSize: 12, color: C.ink2 }}>{s?.sec || "섹터 미분류"}</div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8 }}>
              <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, padding: "10px 10px", background: C.surface2 }}>
                <MonoCaps style={{ fontSize: 9 }} color={C.ink3}>종합 점수</MonoCaps>
                <div style={{ marginTop: 4 }}><Num size={18} weight={800} color={compColor(s?.comp ?? 0)}>{s?.comp ?? "—"}</Num></div>
              </div>
              <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, padding: "10px 10px", background: C.surface2 }}>
                <MonoCaps style={{ fontSize: 9 }} color={C.ink3}>강세 논거</MonoCaps>
                <div style={{ marginTop: 4, fontSize: 18, fontWeight: 800, color: C.ok }}>{counts.bull}</div>
              </div>
              <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, padding: "10px 10px", background: C.surface2 }}>
                <MonoCaps style={{ fontSize: 9 }} color={C.ink3}>약세 논거</MonoCaps>
                <div style={{ marginTop: 4, fontSize: 18, fontWeight: 800, color: C.bad }}>{counts.bear}</div>
              </div>
            </div>
            <button onClick={() => nav(s.t)} style={{ ...btnGhost, width: "100%", justifyContent: "center", fontSize: 12 }}>
              종목 상세 보기 →
            </button>
          </div>
        </Panel>

        <Panel title="직접 분석 입력" sub="외부 자료 자유 텍스트">
          <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
            <textarea
              value={manualText}
              onChange={(event) => setManualText(event.target.value)}
              placeholder="애널리스트 보고서·유튜브 요약·시장 코멘트를 붙여넣으세요."
              style={{ width: "100%", minHeight: 160, border: `1px solid ${C.line2}`, borderRadius: 8, padding: "10px 12px", fontSize: 12.5, color: C.ink, resize: "vertical", boxSizing: "border-box", outline: "none" }}
            />
            <input
              value={manualSource}
              onChange={(event) => setManualSource(event.target.value)}
              placeholder="출처 메모 (증권사명·유튜버명 등)"
              style={{ width: "100%", border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 12.5, color: C.ink, boxSizing: "border-box", outline: "none" }}
            />
            <input
              value={manualSourceUrl}
              onChange={(event) => setManualSourceUrl(event.target.value)}
              placeholder="출처 URL (선택)"
              style={{ width: "100%", border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 12.5, color: C.ink, boxSizing: "border-box", outline: "none" }}
            />
            <button
              onClick={submitManualResearch}
              disabled={manualSaving || !manualText.trim()}
              style={{ border: "none", borderRadius: 8, padding: "10px 12px", background: C.ink, color: "#fff", fontSize: 12.5, fontWeight: 700, cursor: "pointer", opacity: manualSaving || !manualText.trim() ? 0.45 : 1 }}
            >
              {manualSaving ? "분석 중…" : "분석"}
            </button>
            {manualError && <div style={{ fontSize: 11.5, color: C.bad }}>{manualError}</div>}
          </div>
        </Panel>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10, padding: "18px 22px", display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
              <span style={{ fontSize: 24, fontWeight: 800, color: C.ink }}>{s?.name}</span>
              <span className="mono" style={{ fontSize: 13, color: C.ink3 }}>{s?.t} · {s?.mk}</span>
            </div>
            <div style={{ marginTop: 6, fontSize: 12.5, color: C.ink2 }}>
              전문가들이 보는 강세·약세 논거와 최신 컨센서스를 한 화면에 모았습니다.
            </div>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 11.5, fontWeight: 700, color: C.ok, background: C.ok + "14", border: `1px solid ${C.ok}33`, borderRadius: 999, padding: "5px 10px" }}>강세 {counts.bull}</span>
            <span style={{ fontSize: 11.5, fontWeight: 700, color: C.bad, background: C.bad + "14", border: `1px solid ${C.bad}33`, borderRadius: 999, padding: "5px 10px" }}>약세 {counts.bear}</span>
            {!hasAnalystCoverage(s) && (
              <span style={{ fontSize: 11.5, fontWeight: 700, color: C.ink2, background: C.surface2, border: `1px solid ${C.line2}`, borderRadius: 999, padding: "5px 10px" }}>수집 대기</span>
            )}
          </div>
        </div>

        <ConsensusSummaryCard stock={s} />

        <ManualAiDecompositionCard
          entry={manualLatest}
          summary={manualLatest ? _manual_research_summary_fallback(manualLatest, s?.aiDecompositionSummary) : s?.aiDecompositionSummary}
        />

        <Panel
          title="과거 입력 보기"
          sub={`${manualHistory.length}건`}
          right={<button onClick={() => setShowManualHistory((v) => !v)} style={{ ...btnGhost, fontSize: 11.5 }}>{showManualHistory ? "접기 −" : "펼치기 +"}</button>}
        >
          {!showManualHistory ? (
            <div style={{ padding: "18px 16px", fontSize: 12, color: C.ink3 }}>
              {manualHistory.length ? "최신 입력만 보이는 상태입니다. 펼치면 이전 입력 이력을 확인할 수 있습니다." : "직접 입력한 분석 이력이 없습니다."}
            </div>
          ) : (
            <div style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
              {manualHistory.map((entry) => (
                <div key={entry.id} style={{ border: `1px solid ${C.line}`, borderRadius: 8, padding: "10px 12px", background: C.surface2 }}>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: C.acc, background: C.accTint, border: `1px solid ${C.acc}33`, borderRadius: 999, padding: "4px 8px" }}>entry #{entry.id}</span>
                    <span style={{ fontSize: 11, color: C.ink3 }}>{entry.createdAt}</span>
                  </div>
                  <div style={{ marginTop: 8, fontSize: 12, color: C.ink2, lineHeight: 1.6 }}>
                    {buildAiDecompositionBadges(_buildAiSummaryFromEntry(entry)).join(" · ") || "분해 결과 없음"}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>

        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.05fr) minmax(0, 1fr)", gap: 16, alignItems: "start" }}>
          <ConsensusTrendCard history={s?.consensusHistory || []} currency={s?.cur} />
          <Panel title="표시 원칙" sub="이 탭이 보여주는 것">
            <div style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
              {[
                "컨센서스는 전문가 의견의 현재 상태를 보여주는 참고 자료입니다.",
                "강세와 약세 논거를 나란히 보여 주며, 한쪽이 비어 있으면 비어 있는 그대로 표시합니다.",
                "현재가 대비 괴리율은 화면에서만 계산하며 저장값을 다시 쓰지 않습니다.",
              ].map((line) => (
                <div key={line} style={{ fontSize: 12.5, color: C.ink2, lineHeight: 1.6 }}>{line}</div>
              ))}
            </div>
          </Panel>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}>
          <AnalystPointsCard title="강세 논거" tone="bull" points={s?.analystViews?.bull || []} emptyText="수집된 강세 논거 없음" />
          <AnalystPointsCard title="약세 논거" tone="bear" points={s?.analystViews?.bear || []} emptyText="수집된 약세 논거 없음" />
        </div>

        <InsightHistoryCard items={s?.insightHistory || []} />
      </div>
    </div>
  );
}
