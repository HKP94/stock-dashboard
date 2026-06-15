// ATLAS — Tabs B: Screener, Market, Research
import { useState } from 'react';
import {
  C, compColor, flagTone,
  MonoCaps, Num, SentBadge, HoldDot,
  GaugeBar, RegimeBadge, WeightBars, btnGhost,
} from './ui.jsx';
import { Panel } from './tabsA.jsx';

const grade = (v) => v >= 88 ? "A+" : v >= 80 ? "A" : v >= 72 ? "B+" : v >= 64 ? "B" : v >= 56 ? "C+" : v >= 48 ? "C" : "D";
const gradeCol = (v) => v >= 80 ? C.ok : v >= 64 ? C.warn : v >= 48 ? C.ink2 : C.bad;

function GradeChip({ value }) {
  const col = gradeCol(value);
  return <span className="mono" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", minWidth: 30, padding: "3px 7px", borderRadius: 6, background: col + "14", border: `1px solid ${col}33`, color: col, fontSize: 12.5, fontWeight: 700 }}>{grade(value)}</span>;
}

// ============================ SCREENER ============================
export function Screener({ D, nav }) {
  const [showAll, setShowAll] = useState(false);
  const [sortKey, setSortKey] = useState("comp");
  const [sortDir, setSortDir] = useState("desc");

  const overall = D.market.overall;
  const regimeBasis = D.market.kr?.regimeBasis || D.market.us?.regimeBasis || "";

  const momentum = [...D.stocks].sort((a, b) => b.f.m - a.f.m).slice(0, 9);
  const longterm = [...D.stocks].filter((s) => s.fscore >= 7).sort((a, b) => (b.f.q + b.f.v) - (a.f.q + a.f.v)).slice(0, 9);

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
        <strong style={{ color: C.acc }}>모멘텀 픽</strong> = 타이밍 시그널(언제 사는가) · <strong style={{ color: C.ink }}>장기 보유 후보</strong> = F-Score 7+ 퀄리티 필터(무엇을 오래 들고 가는가)
      </span>
    </div>

    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}>
      <Panel title="모멘텀 픽" sub="타이밍 시그널" right={<MonoCaps style={{ fontSize: 9.5 }} color={C.acc}>모멘텀 내림차순</MonoCaps>}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr style={{ borderBottom: `1px solid ${C.line2}` }}>
            {["#", "종목", "모멘텀", "감성", "RSI"].map((h, i) => <th key={i} style={{ padding: "8px 12px", textAlign: i >= 2 ? "right" : "left" }}><MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{h}</MonoCaps></th>)}
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

      <Panel title="장기 보유 후보" sub="퀄리티 필터" right={<MonoCaps style={{ fontSize: 9.5 }}>F-SCORE 7+</MonoCaps>}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr style={{ borderBottom: `1px solid ${C.line2}` }}>
            {["#", "종목", "퀄리티", "가치", "F-Score"].map((h, i) => <th key={i} style={{ padding: "8px 12px", textAlign: i >= 2 ? "right" : "left" }}><MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{h}</MonoCaps></th>)}
          </tr></thead>
          <tbody>
            {longterm.map((s, i) => <tr key={s.t} onClick={() => nav(s.t)} className="row-hover" style={{ borderBottom: `1px solid ${C.line}`, cursor: "pointer" }}>
              <td style={{ padding: "10px 12px" }}><Num size={13} weight={700} color={i < 3 ? C.ok : C.ink3}>{i + 1}</Num></td>
              <td style={{ padding: "10px 12px" }}><div style={{ display: "flex", alignItems: "center", gap: 7 }}><HoldDot on={s.hold} /><span style={{ fontSize: 13, fontWeight: 700 }}>{s.name}</span><span className="mono" style={{ fontSize: 10, color: C.ink3 }}>{s.mk}</span></div></td>
              <td style={{ padding: "10px 12px", textAlign: "right" }}><Num size={13} weight={600} color={gradeCol(s.f.q)}>{s.f.q}</Num></td>
              <td style={{ padding: "10px 12px", textAlign: "right" }}><Num size={13} weight={600} color={gradeCol(s.f.v)}>{s.f.v}</Num></td>
              <td style={{ padding: "10px 12px", textAlign: "right" }}>
                <span className="mono" style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12, fontWeight: 700, color: s.fscore >= 8 ? C.ok : C.warn }}>{s.fscore ?? "—"}<span style={{ color: C.ink3, fontWeight: 500 }}>/9</span></span>
              </td>
            </tr>)}
          </tbody>
        </table>
        <div style={{ padding: "11px 16px", borderTop: `1px solid ${C.line}`, background: C.surface2, borderRadius: "0 0 10px 10px" }}>
          <span style={{ fontSize: 11.5, color: C.ink2 }}><strong style={{ color: C.ink }}>선정 기준</strong> · Piotroski F-Score 7+ 통과 후 퀄리티·가치 합산 상위. 재무 건전성 기반 장기 보유.</span>
        </div>
      </Panel>
    </div>

    <Panel title="전체 종목 · 통합 정렬" sub={`${D.stocks.length}종목 · 컬럼 클릭 시 정렬`}
      right={<button onClick={() => setShowAll(!showAll)} style={{ ...btnGhost, display: "flex", alignItems: "center", gap: 5 }}>{showAll ? "접기 −" : "펼치기 +"}</button>}>
      {showAll && <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr style={{ borderBottom: `1px solid ${C.line2}` }}>
          <Th label="종목" /><Th k="comp" label="Composite" /><Th k="m" label="모멘텀" /><Th k="v" label="가치" /><Th k="q" label="퀄리티" /><Th k="g" label="성장" /><Th k="s" label="감성" /><Th k="rsi" label="RSI" /><Th k="fscore" label="F-Score" />
        </tr></thead>
        <tbody>
          {unified.map((s) => <tr key={s.t} onClick={() => nav(s.t)} className="row-hover" style={{ borderBottom: `1px solid ${C.line}`, cursor: "pointer" }}>
            <td style={{ padding: "9px 10px" }}><div style={{ display: "flex", alignItems: "center", gap: 7 }}><HoldDot on={s.hold} /><span style={{ fontSize: 12.5, fontWeight: 700 }}>{s.name}</span><span className="mono" style={{ fontSize: 9.5, color: C.ink3 }}>{s.t}·{s.mk}</span></div></td>
            <td style={{ padding: "9px 10px", textAlign: "right" }}><Num size={13} weight={700} color={compColor(s.comp ?? 0)}>{s.comp ?? "—"}</Num></td>
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
  const bullets = (m.summaryMd || "")
    .split("\n").map((l) => l.replace(/^[-*]\s*/, "").trim()).filter(Boolean);
  return <Panel title={title} right={<RegimeBadge regime={m.regime} regimes={regimes} />}>
    <div style={{ padding: "16px 18px" }}>
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
          <p style={{ margin: "8px 0 0", fontSize: 13, color: C.ink3, lineHeight: 1.65 }}>{m.summary || "시황 분석 준비 중입니다."}</p>
        )}
      </div>
    </div>
  </Panel>;
}

export function Market({ D }) {
  const overall = D.market.overall;
  const w = D.regimes[overall].w;
  const interp = overall === "bull"
    ? "강세 국면 — 모멘텀 비중을 최대(45%)로 끌어올려 추세에 올라타되, 감성·과열 신호로 진입 타이밍을 조절합니다."
    : overall === "neutral"
      ? "중립 국면 — 모멘텀과 가치·퀄리티를 균형 있게 배분합니다. 추세에 일부 올라타되 펀더멘털이 받쳐주는 종목 위주로 선별합니다."
      : "약세 국면 — 퀄리티(45%)·가치(35%)에 무게를 실어 방어합니다. 모멘텀 비중을 최소화하고 재무 건전성 높은 종목으로 포트폴리오를 압축합니다.";

  return <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}>
      <MarketColumn title="🇰🇷 한국 시장" m={D.market.kr} regimes={D.regimes} />
      <MarketColumn title="🇺🇸 미국 시장" m={D.market.us} regimes={D.regimes} />
    </div>

    <Panel title="현재 국면 → 전략 가중치" sub="동적 팩터 모델">
      <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", gap: 0 }}>
        <div style={{ padding: "20px 22px", borderRight: `1px solid ${C.line}` }}>
          <MonoCaps style={{ fontSize: 9.5 }}>종합 레짐</MonoCaps>
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
                M {D.regimes[r].w.m} · V {D.regimes[r].w.v} · Q {D.regimes[r].w.q}<br />G {D.regimes[r].w.g} · S {D.regimes[r].w.s}
              </div>
            </div>)}
          </div>
        </div>
      </div>
    </Panel>
  </div>;
}

// ============================ RESEARCH (PR-4) ============================

// YouTube watch URL → embed URL 변환
function toYtEmbed(url) {
  if (!url) return null;
  // youtu.be/ID 또는 youtube.com/watch?v=ID
  const m = url.match(/(?:youtu\.be\/|[?&]v=)([\w-]{11})/);
  return m ? `https://www.youtube.com/embed/${m[1]}` : null;
}

const TYPE_LABEL = { youtube: "유튜브", article: "기사", report: "리포트", quant: "퀀트", memo: "메모" };
const TYPE_COLOR = { youtube: C.bad, article: C.acc, report: C.warn, quant: C.ok, memo: C.ink3 };

function ResearchItemCard({ item }) {
  const ytEmbed = item.type === "youtube" ? toYtEmbed(item.url) : null;
  return (
    <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 8, overflow: "hidden", marginBottom: 12 }}>
      <div style={{ padding: "10px 14px", display: "flex", alignItems: "center", gap: 10, borderBottom: ytEmbed ? `1px solid ${C.line}` : "none" }}>
        <span style={{
          fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 4,
          background: (TYPE_COLOR[item.type] || C.ink3) + "18",
          color: TYPE_COLOR[item.type] || C.ink3, border: `1px solid ${(TYPE_COLOR[item.type] || C.ink3)}33`,
        }}>{TYPE_LABEL[item.type] || item.type}</span>
        {item.url ? (
          <a href={item.url} target="_blank" rel="noopener noreferrer"
            style={{ fontSize: 13.5, fontWeight: 700, color: C.ink, textDecoration: "none", flex: 1 }}>
            {item.title}
          </a>
        ) : (
          <span style={{ fontSize: 13.5, fontWeight: 700, color: C.ink, flex: 1 }}>{item.title}</span>
        )}
        <span className="mono" style={{ fontSize: 9.5, color: C.ink3, flexShrink: 0 }}>{item.addedAt}</span>
        {item.url && <a href={item.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 11, color: C.acc, textDecoration: "none", flexShrink: 0 }}>↗</a>}
      </div>
      {ytEmbed && (
        <div style={{ position: "relative", paddingBottom: "56.25%", background: "#000" }}>
          <iframe
            src={ytEmbed}
            title={item.title}
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%", border: "none" }}
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
          />
        </div>
      )}
      {item.note && (
        <div style={{ padding: "8px 14px", fontSize: 12.5, color: C.ink2, lineHeight: 1.55, background: C.surface2 }}>
          {item.note}
        </div>
      )}
    </div>
  );
}

export function Research({ D, nav }) {
  const allTickers = D.stocks.map((s) => s.t);
  const withItems = D.stocks.filter((s) => (s.researchItems || []).length > 0);
  const [ticker, setTicker] = useState(withItems.length > 0 ? withItems[0].t : allTickers[0]);
  const [typeFilter, setTypeFilter] = useState("all");

  const s = D.stocks.find((x) => x.t === ticker) || D.stocks[0];
  const items = s?.researchItems || [];
  const filtered = typeFilter === "all" ? items : items.filter((i) => i.type === typeFilter);
  const typeCounts = items.reduce((acc, i) => { acc[i.type] = (acc[i.type] || 0) + 1; return acc; }, {});

  // 종목명으로 검색 보조 URL (reportUrl 필드 제거됨 → 여기서 직접 생성)
  const ytSearchUrl = `https://www.youtube.com/results?search_query=${encodeURIComponent(s?.name || "")}+주식+분석`;
  const reportSearchUrl = s
    ? (s.mk === "KR"
        ? `https://finance.naver.com/research/company_list.naver?searchType=itemCode&itemCode=${s.t.split(".")[0]}`
        : `https://www.tipranks.com/stocks/${s.t}/forecast`)
    : "";

  return (
    <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 16, alignItems: "start" }}>
      {/* 좌측: 종목 선택 */}
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <Panel title="리서치 종목">
          <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
            <select
              value={ticker}
              onChange={(e) => { setTicker(e.target.value); setTypeFilter("all"); }}
              style={{ width: "100%", border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 13, fontFamily: "var(--sans)", color: C.ink, background: C.surface, cursor: "pointer", outline: "none" }}
            >
              {D.stocks.map((x) => (
                <option key={x.t} value={x.t}>
                  {x.name} ({x.t}) {(x.researchItems || []).length > 0 ? "·" + (x.researchItems || []).length : ""}
                </option>
              ))}
            </select>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Num size={18} weight={800} color={compColor(s?.comp ?? 0)}>{s?.comp ?? "—"}</Num>
              <span style={{ fontSize: 11, color: C.ink3 }}>COMPOSITE</span>
              <button onClick={() => nav(s.t)} style={{ ...btnGhost, marginLeft: "auto", fontSize: 11 }}>상세 →</button>
            </div>
          </div>
        </Panel>

        <Panel title="검색 보조">
          <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
            <a href={ytSearchUrl} target="_blank" rel="noopener noreferrer"
              style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderRadius: 7, background: "#FF000014", border: "1px solid #FF000033", color: C.bad, fontSize: 12.5, fontWeight: 600, textDecoration: "none" }}>
              ▶ 유튜브에서 "{s?.name}" 분석 찾기
            </a>
            {reportSearchUrl && (
              <a href={reportSearchUrl} target="_blank" rel="noopener noreferrer"
                style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderRadius: 7, background: C.warnBg, border: "1px solid #B4530933", color: C.warn, fontSize: 12.5, fontWeight: 600, textDecoration: "none" }}>
                📄 리포트 검색 ({s?.mk === "KR" ? "네이버" : "TipRanks"})
              </a>
            )}
            <span style={{ fontSize: 11, color: C.ink3 }}>항목 추가: watchlist_admin.py → 리서치 항목</span>
          </div>
        </Panel>
      </div>

      {/* 우측: 항목 표시 */}
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
          <span style={{ fontSize: 14.5, fontWeight: 700, color: C.ink }}>{s?.name} 리서치</span>
          <MonoCaps style={{ fontSize: 9.5 }}>{items.length}건</MonoCaps>
          <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            {["all", "youtube", "article", "report", "quant", "memo"].map((t) => {
              if (t !== "all" && !typeCounts[t]) return null;
              const active = typeFilter === t;
              return (
                <button key={t} onClick={() => setTypeFilter(t)} style={{
                  border: `1px solid ${active ? C.acc : C.line2}`,
                  background: active ? C.acc : C.surface, color: active ? "#fff" : C.ink2,
                  borderRadius: 999, padding: "4px 11px", fontSize: 11.5, fontWeight: 600, cursor: "pointer",
                }}>
                  {t === "all" ? "전체" : TYPE_LABEL[t]}{t !== "all" ? ` ${typeCounts[t]}` : ""}
                </button>
              );
            })}
          </div>
        </div>

        {filtered.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", color: C.ink3, fontSize: 13, background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10 }}>
            {items.length === 0
              ? "리서치 항목이 없습니다. watchlist_admin.py에서 추가하세요."
              : "해당 유형의 항목이 없습니다."}
          </div>
        ) : (
          filtered.map((item) => <ResearchItemCard key={item.id} item={item} />)
        )}
      </div>
    </div>
  );
}
