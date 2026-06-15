// ATLAS — Tabs A: Overview, Stock Detail, News
const { useState, useMemo } = React;

function Panel({ title, sub, right, children, style, bodyStyle }) {
  return <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10, boxShadow: "0 1px 2px rgba(15,23,42,0.04)", display: "flex", flexDirection: "column", ...style }}>
    {title && <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "13px 16px", borderBottom: `1px solid ${C.line}` }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 9 }}>
        <span style={{ fontSize: 14.5, fontWeight: 700, color: C.ink, letterSpacing: "-0.01em", whiteSpace: "nowrap" }}>{title}</span>
        {sub && <MonoCaps style={{ fontSize: 10 }}>{sub}</MonoCaps>}
      </div>
      {right}
    </div>}
    <div style={{ flex: 1, ...bodyStyle }}>{children}</div>
  </div>;
}

function FilterTabs({ value, onChange, options }) {
  return <div style={{ display: "flex", gap: 2, background: C.surface2, borderRadius: 8, padding: 3 }}>
    {options.map((o) => <button key={o.k} onClick={() => onChange(o.k)} style={{
      border: "none", cursor: "pointer", fontSize: 12, fontWeight: 600, padding: "5px 12px", borderRadius: 6,
      background: value === o.k ? C.surface : "transparent", color: value === o.k ? C.ink : C.ink2,
      boxShadow: value === o.k ? "0 1px 2px rgba(15,23,42,0.08)" : "none", transition: "all .15s",
    }}>{o.label}</button>)}
  </div>;
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

// ============================ OVERVIEW ============================
function Overview({ nav, goNews }) {
  const D = window.ATLAS_DATA;
  const [filter, setFilter] = useState("all");
  const rows = useMemo(() => {
    let r = [...D.stocks];
    if (filter === "KR") r = r.filter((s) => s.mk === "KR");
    else if (filter === "US") r = r.filter((s) => s.mk === "US");
    else if (filter === "hold") r = r.filter((s) => s.hold);
    return r.sort((a, b) => b.comp - a.comp);
  }, [filter]);

  const alerts = [];
  D.stocks.forEach((s) => s.flags.forEach((f) => alerts.push({ s, f })));
  const sortRank = (f) => (/과열|데드크로스|과매도|약세|경계|하회/.test(f) ? 0 : /임박|급증|골든/.test(f) ? 1 : 2);
  alerts.sort((a, b) => sortRank(a.f) - sortRank(b.f));
  const topNews = D.news.filter((n) => n.hot).slice(0, 4);

  return <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
    {/* index strip */}
    <div style={{ display: "grid", gridTemplateColumns: "repeat(6,1fr)", gap: 10 }}>
      {D.market.indices.map((ix) => {
        const up = ix.inv ? ix.chg < 0 : ix.chg > 0;
        return <div key={ix.k} style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10, padding: "11px 13px", display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <MonoCaps style={{ fontSize: 9.5 }}>{ix.k}</MonoCaps>
            <span style={{ width: 5, height: 5, borderRadius: 999, background: up ? C.ok : C.bad }}></span>
          </div>
          <Num size={19} weight={700}>{ix.v}</Num>
          <ChangePct v={ix.chg} inv={ix.inv} size={12} />
        </div>;
      })}
    </div>

    <div style={{ display: "grid", gridTemplateColumns: "1fr 420px", gap: 16, alignItems: "start" }}>
      {/* ranking table */}
      <Panel title="관심종목 랭킹" sub={`COMPOSITE 내림차순 · ${rows.length}종목`}
        right={<FilterTabs value={filter} onChange={setFilter} options={[{ k: "all", label: "전체" }, { k: "KR", label: "KR" }, { k: "US", label: "US" }, { k: "hold", label: "보유" }]} />}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${C.line2}` }}>
              {["", "종목", "현재가", "COMPOSITE", "M·V·Q·G·S", "RSI", "추세", "주요 플래그"].map((h, i) => (
                <th key={i} style={{ textAlign: i >= 2 && i <= 5 ? "left" : "left", padding: "9px 12px", position: "sticky", top: 0 }}>
                  <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{h}</MonoCaps>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.t} onClick={() => nav(s.t)} className="row-hover" style={{ borderBottom: `1px solid ${C.line}`, cursor: "pointer" }}>
                <td style={{ padding: "10px 12px", width: 18 }}><HoldDot on={s.hold} /></td>
                <td style={{ padding: "10px 12px" }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                    <span style={{ fontSize: 13.5, fontWeight: 700, color: C.ink }}>{s.name}</span>
                    <span className="mono" style={{ fontSize: 10, color: C.ink3, letterSpacing: "0.02em" }}>{s.t} · {s.mk}</span>
                  </div>
                </td>
                <td style={{ padding: "10px 12px" }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 1, alignItems: "flex-start" }}>
                    <Num size={13.5} weight={600}>{fmtPrice(s)}</Num>
                    <ChangePct v={s.chg} size={11.5} />
                  </div>
                </td>
                <td style={{ padding: "10px 12px", width: 150 }}><CompositeCell value={s.comp} /></td>
                <td style={{ padding: "10px 12px" }}><MiniBars f={s.f} /></td>
                <td style={{ padding: "10px 12px" }}><Num size={13} weight={600} color={s.rsi >= 70 ? C.bad : s.rsi <= 35 ? C.acc : C.ink2}>{s.rsi.toFixed(0)}</Num></td>
                <td style={{ padding: "10px 12px" }}><AlignBadge on={s.align} /></td>
                <td style={{ padding: "10px 12px", maxWidth: 150 }}>
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                    {s.flags.slice(0, 2).map((f) => <span key={f} style={{ fontSize: 10.5, fontWeight: 600, color: flagTone(f), background: C.surface2, border: `1px solid ${C.line}`, borderRadius: 5, padding: "2px 6px", whiteSpace: "nowrap" }}>{f}</span>)}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      {/* right column */}
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <Panel title="오늘의 알림" sub={`${alerts.length} RULES FLAGGED`} bodyStyle={{ maxHeight: 320, overflowY: "auto" }}>
          {alerts.map((a, i) => (
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
        </Panel>

        <Panel title="주목 뉴스" sub="HIGH-SIGNAL" right={<button onClick={goNews} style={btnGhost}>전체 보기 →</button>}>
          {topNews.map((n, i) => {
            const st = D.stocks.find((s) => s.t === n.t);
            return <div key={i} onClick={() => nav(n.t)} className="row-hover" style={{ padding: "11px 16px", borderBottom: `1px solid ${C.line}`, cursor: "pointer" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 5 }}>
                <span style={{ fontSize: 11.5, fontWeight: 700, color: C.ink }}>{st ? st.name : n.t}</span>
                <SentBadge label={n.sent} sm />
                <span className="mono" style={{ fontSize: 9.5, color: C.ink3, marginLeft: "auto" }}>{n.time}</span>
              </div>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: C.ink, lineHeight: 1.4 }}>{n.high}</div>
            </div>;
          })}
        </Panel>
      </div>
    </div>
  </div>;
}

const btnGhost = { border: "none", background: "transparent", color: C.acc, fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "var(--sans)" };

// ============================ STOCK DETAIL ============================
function StockDetail({ ticker, nav }) {
  const D = window.ATLAS_DATA;
  const s = D.stocks.find((x) => x.t === ticker) || D.stocks[0];
  const sectorPeers = D.stocks.filter((x) => x.sec === s.sec).length;
  const factors = [["m", s.f.m], ["v", s.f.v], ["q", s.f.q], ["g", s.f.g], ["s", s.f.s]];

  const indicators = [
    { label: "RSI (14)", val: s.rsi.toFixed(1), tone: s.rsi >= 70 ? "bad" : s.rsi <= 35 ? "acc" : "neutral", note: s.rsi >= 70 ? "과열" : s.rsi <= 35 ? "과매도" : "중립" },
    { label: "Forward PER", val: s.per.toFixed(1) + "x", tone: s.per > 40 ? "warn" : "neutral", note: s.cur === "₩" ? "" : "12M fwd" },
    { label: "ROE", val: s.roe.toFixed(1) + "%", tone: s.roe >= 20 ? "ok" : s.roe < 8 ? "warn" : "neutral", note: "" },
    { label: "매출 성장률", val: (s.rev > 0 ? "+" : "") + s.rev.toFixed(1) + "%", tone: s.rev >= 20 ? "ok" : s.rev < 0 ? "bad" : "neutral", note: "YoY" },
    { label: "목표주가", val: s.cur === "₩" ? "₩" + s.tp.toLocaleString() : "$" + s.tp, tone: "neutral", note: "컨센서스" },
    { label: "상승 여력", val: (s.up > 0 ? "+" : "") + s.up.toFixed(1) + "%", tone: s.up >= 10 ? "ok" : s.up < 0 ? "bad" : "warn", note: "vs 현재가" },
    { label: "이동평균 배열", val: s.align ? "정배열" : "역배열", tone: s.align ? "ok" : "bad", note: `20·60·120일` },
    { label: "컨센서스 의견", val: s.rating, tone: /Strong Buy|Buy/.test(s.rating) ? "ok" : s.rating === "Hold" ? "warn" : "bad", note: "애널리스트" },
  ];
  const toneCol = (t) => ({ ok: C.ok, bad: C.bad, warn: C.warn, acc: C.acc, neutral: C.ink }[t] || C.ink);

  return <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
    {/* header */}
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

    {/* stock switcher */}
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
      {[...D.stocks].sort((a, b) => b.comp - a.comp).map((x) => (
        <button key={x.t} onClick={() => nav(x.t)} style={{
          border: `1px solid ${x.t === s.t ? C.acc : C.line2}`, background: x.t === s.t ? C.accTint : C.surface,
          color: x.t === s.t ? C.acc : C.ink2, borderRadius: 999, padding: "4px 11px", fontSize: 12, fontWeight: 600, cursor: "pointer",
        }}>{x.name}</button>
      ))}
    </div>

    <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 16, alignItems: "start" }}>
      <Panel title="가격 추이" sub="6개월 · 일봉" right={<div style={{ display: "flex", gap: 14, alignItems: "center" }}>
        <span style={{ display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 14, height: 2, background: s.series[s.series.length - 1] >= s.series[0] ? C.ok : C.bad }}></span><MonoCaps style={{ fontSize: 9 }}>종가</MonoCaps></span>
        <span style={{ display: "flex", alignItems: "center", gap: 5 }}><span style={{ width: 14, height: 2, background: C.acc, opacity: 0.7 }}></span><MonoCaps style={{ fontSize: 9 }}>SMA20</MonoCaps></span>
      </div>}>
        <div style={{ padding: "14px 16px" }}><PriceChart stock={s} w={560} h={250} /></div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", borderTop: `1px solid ${C.line}` }}>
          {[["SMA 20", s.sma20], ["SMA 60", s.sma50], ["SMA 120", s.sma200], ["20일 이격도", s.disparity + "%"]].map(([l, v], i) => (
            <div key={l} style={{ padding: "11px 16px", borderRight: i < 3 ? `1px solid ${C.line}` : "none" }}>
              <MonoCaps style={{ fontSize: 9 }}>{l}</MonoCaps>
              <div><Num size={14} weight={600}>{typeof v === "number" ? (s.cur === "₩" ? "₩" + Math.round(v).toLocaleString() : "$" + v) : v}</Num></div>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="팩터 점수" sub={`${s.sec} · ${sectorPeers}종목 중 ${s.rank[0] > sectorPeers ? Math.min(s.rank[0], sectorPeers) : s.rank[0]}위`}>
        <div style={{ padding: "16px 18px", borderBottom: `1px solid ${C.line}`, display: "flex", alignItems: "center", gap: 18 }}>
          <div>
            <MonoCaps style={{ fontSize: 9 }}>COMPOSITE</MonoCaps>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <Num size={48} weight={800} color={compColor(s.comp)}>{s.comp}</Num>
              <span style={{ fontSize: 13, color: C.ink3 }}>/ 100</span>
            </div>
          </div>
          <div style={{ flex: 1, paddingLeft: 18, borderLeft: `1px solid ${C.line}` }}>
            <MonoCaps style={{ fontSize: 9 }}>섹터 순위</MonoCaps>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
              <Num size={28} weight={800} color={C.acc}>{s.rank[0]}</Num>
              <span style={{ fontSize: 13, color: C.ink2 }}>위 / {s.rank[1].toLocaleString()}종목</span>
            </div>
            <div style={{ marginTop: 4 }}><Sparkline data={s.compHist} color={C.acc} w={140} h={22} fill /></div>
          </div>
        </div>
        <div style={{ padding: "8px 18px 14px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
            <MonoCaps style={{ fontSize: 9 }} color={C.acc}>타이밍 그룹 — 단기 시그널</MonoCaps>
          </div>
          {factors.filter(([k]) => D.factorMeta[k].group === "timing").map(([k, v]) => <FactorBar key={k} label={D.factorMeta[k].ko} value={v} group="timing" />)}
          <div style={{ height: 1, background: C.line, margin: "8px 0" }}></div>
          <div style={{ marginBottom: 4 }}><MonoCaps style={{ fontSize: 9 }}>미스프라이싱 그룹 — 장기 보유 판단</MonoCaps></div>
          {factors.filter(([k]) => D.factorMeta[k].group === "mispricing").map(([k, v]) => <FactorBar key={k} label={D.factorMeta[k].ko} value={v} group="mispricing" />)}
        </div>
      </Panel>
    </div>

    {/* indicator grid */}
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

    <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 16, alignItems: "start" }}>
      {/* news summary */}
      <Panel title="뉴스 · AI 분석 요약" sub="GEMINI SENTIMENT" right={<SentBadge label={s.sent} score={s.sscore} />}>
        <div style={{ padding: "14px 18px" }}>
          <MonoCaps style={{ fontSize: 9 }}>핵심 요약</MonoCaps>
          <ul style={{ margin: "8px 0 0", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 9 }}>
            {s.sum.map((b, i) => <li key={i} style={{ display: "flex", gap: 9, fontSize: 13, color: C.ink, lineHeight: 1.5 }}>
              <span style={{ color: sentMeta(s.sent).c, fontWeight: 800, flexShrink: 0 }}>—</span><span>{b}</span>
            </li>)}
          </ul>
          <div style={{ height: 1, background: C.line, margin: "14px 0" }}></div>
          <MonoCaps style={{ fontSize: 9 }}>주요 캐털리스트</MonoCaps>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
            {s.cat.map((c, i) => <div key={i} style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <span className="mono" style={{ fontSize: 11.5, fontWeight: 600, color: C.acc, background: C.accTint, padding: "2px 8px", borderRadius: 5 }}>{c[0]}</span>
              <span style={{ fontSize: 12.5, color: C.ink2 }}>{c[1]}</span>
            </div>)}
          </div>
        </div>
      </Panel>

      {/* score history */}
      <Panel title="점수 히스토리" sub="최근 16주 추이">
        <div style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 16 }}>
          {[["COMPOSITE", s.compHist, C.acc, s.comp], ["모멘텀", s.momHist, C.ok, s.f.m]].map(([lbl, data, col, cur]) => {
            const delta = data[data.length - 1] - data[0];
            return <div key={lbl}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
                <MonoCaps style={{ fontSize: 9.5 }}>{lbl}</MonoCaps>
                <span className="tnum" style={{ fontSize: 11.5, fontWeight: 700, color: delta >= 0 ? C.ok : C.bad }}>{delta >= 0 ? "+" : ""}{delta} (16주)</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <Num size={24} weight={800} color={col}>{cur}</Num>
                <div style={{ flex: 1 }}><Sparkline data={data} color={col} w={200} h={36} fill /></div>
              </div>
            </div>;
          })}
        </div>
      </Panel>
    </div>
  </div>;
}

// ============================ NEWS ============================
function NewsTab({ filterTicker, setFilterTicker, nav }) {
  const D = window.ATLAS_DATA;
  const [mkt, setMkt] = useState("all");
  const [sent, setSent] = useState("all");
  const [q, setQ] = useState("");

  const sentCounts = useMemo(() => {
    return D.stocks.map((s) => {
      const seed = s.t.length + s.comp;
      const pos = s.sent === "긍정" ? 5 + (seed % 3) : s.sent === "중립" ? 2 + (seed % 2) : 1;
      const neg = s.sent === "부정" ? 5 + (seed % 3) : s.sent === "중립" ? 2 : 1;
      const neu = 2 + (seed % 3);
      return { s, pos, neu, neg, total: pos + neu + neg };
    }).sort((a, b) => b.total - a.total);
  }, []);

  const feed = useMemo(() => {
    let f = [...D.news];
    if (filterTicker) f = f.filter((n) => n.t === filterTicker);
    if (mkt !== "all") {
      f = f.filter((n) => { const st = D.stocks.find((s) => s.t === n.t); return mkt === "hold" ? st && st.hold : st && st.mk === mkt; });
    }
    if (sent !== "all") f = f.filter((n) => n.sent === sent);
    if (q) f = f.filter((n) => { const st = D.stocks.find((s) => s.t === n.t); return (st && st.name.includes(q)) || n.t.includes(q) || n.high.includes(q); });
    return f;
  }, [filterTicker, mkt, sent, q]);

  const activeStock = filterTicker ? D.stocks.find((s) => s.t === filterTicker) : null;

  return <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 16, alignItems: "start" }}>
    <Panel title="관심종목 뉴스" sub={`${feed.length}건${activeStock ? " · " + activeStock.name : ""}`}
      right={<div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        {filterTicker && <button onClick={() => setFilterTicker(null)} style={btnGhost}>필터 해제 ✕</button>}
        <FilterTabs value={mkt} onChange={setMkt} options={[{ k: "all", label: "전체" }, { k: "KR", label: "KR" }, { k: "US", label: "US" }, { k: "hold", label: "보유" }]} />
      </div>}>
      <div style={{ display: "flex", gap: 10, padding: "11px 16px", borderBottom: `1px solid ${C.line}`, alignItems: "center" }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="종목 검색…" style={{ flex: 1, border: `1px solid ${C.line2}`, borderRadius: 7, padding: "7px 11px", fontSize: 12.5, fontFamily: "var(--sans)", outline: "none", color: C.ink }} />
        <FilterTabs value={sent} onChange={setSent} options={[{ k: "all", label: "전체" }, { k: "긍정", label: "긍정" }, { k: "부정", label: "부정" }]} />
      </div>
      <div style={{ maxHeight: 620, overflowY: "auto" }}>
        {feed.map((n, i) => {
          const st = D.stocks.find((s) => s.t === n.t);
          return <div key={i} style={{ padding: "14px 16px", borderBottom: `1px solid ${C.line}` }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
              <button onClick={() => nav(n.t)} className="chip-hover" style={{ border: `1px solid ${C.line2}`, background: C.surface, borderRadius: 999, padding: "2px 9px", fontSize: 11, fontWeight: 700, color: C.ink, cursor: "pointer", display: "flex", gap: 5, alignItems: "center" }}>
                <HoldDot on={st && st.hold} />{st ? st.name : n.t}
              </button>
              <SentBadge label={n.sent} sm />
              <span className="mono" style={{ fontSize: 10, color: C.ink3 }}>{n.time}</span>
              <span style={{ fontSize: 11, color: C.ink3, marginLeft: "auto" }}>{n.src}</span>
            </div>
            <div style={{ fontSize: 14.5, fontWeight: 700, color: C.ink, lineHeight: 1.4, marginBottom: 5, letterSpacing: "-0.01em" }}>{n.high}</div>
            <div style={{ fontSize: 12.5, color: C.ink2, lineHeight: 1.55 }}>{n.body}</div>
          </div>;
        })}
        {feed.length === 0 && <div style={{ padding: 40, textAlign: "center", color: C.ink3, fontSize: 13 }}>해당 조건의 뉴스가 없습니다.</div>}
      </div>
    </Panel>

    {/* sentiment bars */}
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
  </div>;
}

Object.assign(window, { Panel, FilterTabs, Overview, StockDetail, NewsTab, btnGhost });
