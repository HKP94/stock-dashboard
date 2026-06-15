// ATLAS — Tabs B: Screener, Market, Research
const { useState: useStateB } = React;

const grade = (v) => v >= 88 ? "A+" : v >= 80 ? "A" : v >= 72 ? "B+" : v >= 64 ? "B" : v >= 56 ? "C+" : v >= 48 ? "C" : "D";
const gradeCol = (v) => v >= 80 ? C.ok : v >= 64 ? C.warn : v >= 48 ? C.ink2 : C.bad;

function GradeChip({ value }) {
  const col = gradeCol(value);
  return <span className="mono" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", minWidth: 30, padding: "3px 7px", borderRadius: 6, background: col + "14", border: `1px solid ${col}33`, color: col, fontSize: 12.5, fontWeight: 700 }}>{grade(value)}</span>;
}

// ============================ SCREENER ============================
function Screener({ nav }) {
  const D = window.ATLAS_DATA;
  const [showAll, setShowAll] = useStateB(false);
  const [sortKey, setSortKey] = useStateB("comp");
  const [sortDir, setSortDir] = useStateB("desc");

  const momentum = [...D.stocks].sort((a, b) => b.f.m - a.f.m).slice(0, 9);
  const longterm = [...D.stocks].filter((s) => s.fscore >= 7).sort((a, b) => (b.f.q + b.f.v) - (a.f.q + a.f.v)).slice(0, 9);

  const sortVal = (s, k) => k === "comp" ? s.comp : k === "rsi" ? s.rsi : k === "fscore" ? s.fscore : s.f[k];
  const unified = [...D.stocks].sort((a, b) => {
    const d = sortVal(b, sortKey) - sortVal(a, sortKey);
    return sortDir === "desc" ? d : -d;
  });
  const setSort = (k) => { if (sortKey === k) setSortDir(sortDir === "desc" ? "asc" : "desc"); else { setSortKey(k); setSortDir("desc"); } };

  const Th = ({ k, label, w }) => <th onClick={k ? () => setSort(k) : undefined} style={{ padding: "9px 10px", textAlign: k ? "right" : "left", cursor: k ? "pointer" : "default", width: w, userSelect: "none" }}>
    <MonoCaps style={{ fontSize: 9.5 }} color={sortKey === k ? C.acc : C.ink3}>{label}{sortKey === k ? (sortDir === "desc" ? " ↓" : " ↑") : ""}</MonoCaps>
  </th>;

  return <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
    <div style={{ background: C.accTint, border: `1px solid ${C.acc}22`, borderRadius: 10, padding: "13px 18px", display: "flex", gap: 24, alignItems: "center" }}>
      <span style={{ fontSize: 13, color: C.ink, lineHeight: 1.5 }}>
        <strong style={{ color: C.acc }}>모멘텀 픽</strong> = 타이밍 시그널(언제 사는가) · <strong style={{ color: C.ink }}>장기 보유 후보</strong> = F-Score 7+ 퀄리티 필터(무엇을 오래 들고 가는가)
      </span>
    </div>

    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}>
      {/* momentum */}
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
              <td style={{ padding: "10px 12px", textAlign: "right" }}><Num size={13} weight={600} color={s.rsi >= 70 ? C.bad : s.rsi <= 35 ? C.acc : C.ink2}>{s.rsi.toFixed(0)}</Num></td>
            </tr>)}
          </tbody>
        </table>
        <div style={{ padding: "11px 16px", borderTop: `1px solid ${C.line}`, background: C.surface2, borderRadius: "0 0 10px 10px" }}>
          <span style={{ fontSize: 11.5, color: C.ink2 }}><strong style={{ color: C.ink }}>선정 기준</strong> · 모멘텀 점수 상위 + 정배열/골든크로스 등 추세 시그널. 단기 진입 타이밍 판단용.</span>
        </div>
      </Panel>

      {/* long term */}
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
                <span className="mono" style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12, fontWeight: 700, color: s.fscore >= 8 ? C.ok : C.warn }}>{s.fscore}<span style={{ color: C.ink3, fontWeight: 500 }}>/9</span></span>
              </td>
            </tr>)}
          </tbody>
        </table>
        <div style={{ padding: "11px 16px", borderTop: `1px solid ${C.line}`, background: C.surface2, borderRadius: "0 0 10px 10px" }}>
          <span style={{ fontSize: 11.5, color: C.ink2 }}><strong style={{ color: C.ink }}>선정 기준</strong> · Piotroski F-Score 7+ 통과 후 퀄리티·가치 합산 상위. 재무 건전성 기반 장기 보유.</span>
        </div>
      </Panel>
    </div>

    {/* unified */}
    <Panel title="전체 종목 · 통합 정렬" sub={`${D.stocks.length}종목 · 컬럼 클릭 시 정렬`}
      right={<button onClick={() => setShowAll(!showAll)} style={{ ...btnGhost, display: "flex", alignItems: "center", gap: 5 }}>{showAll ? "접기 −" : "펼치기 +"}</button>}>
      {showAll && <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr style={{ borderBottom: `1px solid ${C.line2}` }}>
          <Th label="종목" /><Th k="comp" label="Composite" /><Th k="m" label="모멘텀" /><Th k="v" label="가치" /><Th k="q" label="퀄리티" /><Th k="g" label="성장" /><Th k="s" label="감성" /><Th k="rsi" label="RSI" /><Th k="fscore" label="F-Score" />
        </tr></thead>
        <tbody>
          {unified.map((s) => <tr key={s.t} onClick={() => nav(s.t)} className="row-hover" style={{ borderBottom: `1px solid ${C.line}`, cursor: "pointer" }}>
            <td style={{ padding: "9px 10px" }}><div style={{ display: "flex", alignItems: "center", gap: 7 }}><HoldDot on={s.hold} /><span style={{ fontSize: 12.5, fontWeight: 700 }}>{s.name}</span><span className="mono" style={{ fontSize: 9.5, color: C.ink3 }}>{s.t}·{s.mk}</span></div></td>
            <td style={{ padding: "9px 10px", textAlign: "right" }}><Num size={13} weight={700} color={compColor(s.comp)}>{s.comp}</Num></td>
            {["m", "v", "q", "g", "s"].map((k) => <td key={k} style={{ padding: "9px 10px", textAlign: "right" }}><Num size={12.5} weight={600} color={sortKey === k ? gradeCol(s.f[k]) : C.ink2}>{s.f[k]}</Num></td>)}
            <td style={{ padding: "9px 10px", textAlign: "right" }}><Num size={12.5} weight={600} color={s.rsi >= 70 ? C.bad : s.rsi <= 35 ? C.acc : C.ink2}>{s.rsi.toFixed(0)}</Num></td>
            <td style={{ padding: "9px 10px", textAlign: "right" }}><span className="mono" style={{ fontSize: 12, fontWeight: 700, color: s.fscore >= 7 ? C.ok : C.ink2 }}>{s.fscore}</span></td>
          </tr>)}
        </tbody>
      </table>}
      {!showAll && <div style={{ padding: "16px 18px", color: C.ink3, fontSize: 12.5 }}>펼치기를 눌러 34개 종목 전체를 모든 팩터로 정렬하세요.</div>}
    </Panel>
  </div>;
}

// ============================ MARKET ============================
function MarketColumn({ flag, title, m }) {
  return <Panel title={title} right={<RegimeBadge regime={m.regime} />}>
    <div style={{ padding: "16px 18px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 18 }}>
        {m.idx.map((ix) => {
          const up = ix.chg > 0;
          return <div key={ix.k} style={{ border: `1px solid ${C.line2}`, borderRadius: 8, padding: "11px 14px" }}>
            <MonoCaps style={{ fontSize: 9.5 }}>{ix.k}</MonoCaps>
            <div style={{ marginTop: 3 }}><Num size={20} weight={700}>{ix.v}</Num></div>
            <div style={{ marginTop: 2 }}><ChangePct v={ix.chg} size={12.5} /></div>
          </div>;
        })}
      </div>
      <MonoCaps style={{ fontSize: 9.5 }}>시장폭 · 변동성</MonoCaps>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, margin: "10px 0 18px" }}>
        {m.gauges.map((g) => <div key={g.label}>
          <div style={{ fontSize: 12, color: C.ink2, marginBottom: 5 }}>{g.label}</div>
          <GaugeBar value={g.v} max={g.label.includes("RSI") || g.label.includes("VIX") ? (g.label.includes("VIX") ? 40 : 100) : 100} tone={g.tone} suffix={g.unit} />
        </div>)}
      </div>
      <div style={{ borderTop: `1px solid ${C.line}`, paddingTop: 14 }}>
        <MonoCaps style={{ fontSize: 9.5 }} color={C.acc}>Gemini 시황 종합</MonoCaps>
        <p style={{ margin: "8px 0 0", fontSize: 13, color: C.ink, lineHeight: 1.65, textWrap: "pretty" }}>{m.summary}</p>
      </div>
    </div>
  </Panel>;
}

function Market() {
  const D = window.ATLAS_DATA;
  const overall = D.market.overall;
  const w = D.regimes[overall].w;
  const interp = overall === "bull"
    ? "강세 국면 — 모멘텀 비중을 최대(45%)로 끌어올려 추세에 올라타되, 감성·과열 신호로 진입 타이밍을 조절합니다."
    : overall === "neutral"
      ? "중립 국면 — 모멘텀과 가치·퀄리티를 균형 있게 배분합니다. 추세에 일부 올라타되 펀더멘털이 받쳐주는 종목 위주로 선별합니다."
      : "약세 국면 — 퀄리티(45%)·가치(35%)에 무게를 실어 방어합니다. 모멘텀 비중을 최소화하고 재무 건전성 높은 종목으로 포트폴리오를 압축합니다.";

  return <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, alignItems: "start" }}>
      <MarketColumn flag="🇰🇷" title="🇰🇷 한국 시장" m={D.market.kr} />
      <MarketColumn flag="🇺🇸" title="🇺🇸 미국 시장" m={D.market.us} />
    </div>

    <Panel title="현재 국면 → 전략 가중치" sub="동적 팩터 모델">
      <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", gap: 0 }}>
        <div style={{ padding: "20px 22px", borderRight: `1px solid ${C.line}` }}>
          <MonoCaps style={{ fontSize: 9.5 }}>종합 레짐</MonoCaps>
          <div style={{ margin: "10px 0 14px" }}><RegimeBadge regime={overall} lg /></div>
          <p style={{ fontSize: 13, color: C.ink2, lineHeight: 1.65, margin: 0, textWrap: "pretty" }}>{interp}</p>
          <div style={{ marginTop: 16, display: "flex", gap: 14 }}>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: C.acc }}></span><span style={{ fontSize: 11, color: C.ink2 }}>타이밍 그룹</span></span>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: C.ink, opacity: 0.85 }}></span><span style={{ fontSize: 11, color: C.ink2 }}>미스프라이싱 그룹</span></span>
          </div>
        </div>
        <div style={{ padding: "20px 22px" }}>
          <WeightBars w={w} />
          <div style={{ marginTop: 16, paddingTop: 14, borderTop: `1px solid ${C.line}`, display: "flex", gap: 20 }}>
            {["bull", "neutral", "bear"].map((r) => <div key={r} onClick={() => {}} style={{ flex: 1, padding: "10px 12px", borderRadius: 8, border: `1px solid ${r === overall ? C.acc : C.line2}`, background: r === overall ? C.accTint : C.surface }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}><RegimeBadge regime={r} /></div>
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

// ============================ RESEARCH ============================
function Research({ nav }) {
  const D = window.ATLAS_DATA;
  const withNotes = D.stocks.filter((s) => D.research.files[s.t]);
  const [ticker, setTicker] = useStateB(withNotes[0].t);
  const s = D.stocks.find((x) => x.t === ticker);
  const files = D.research.files[ticker] || [];
  const [activeFile, setActiveFile] = useStateB(files[0]);
  const [memo, setMemo] = useStateB(D.research.notes[ticker] || "");
  const [tags, setTags] = useStateB(D.research.activeTags[ticker] || []);
  const [saved, setSaved] = useStateB(false);

  const onTicker = (t) => {
    setTicker(t);
    const f = D.research.files[t] || [];
    setActiveFile(f[0]); setMemo(D.research.notes[t] || ""); setTags(D.research.activeTags[t] || []); setSaved(false);
  };
  const toggleTag = (t) => { setTags(tags.includes(t) ? tags.filter((x) => x !== t) : [...tags, t]); setSaved(false); };

  return <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", gap: 16, alignItems: "start" }}>
    {/* left: files */}
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Panel title="리서치 종목">
        <div style={{ padding: "14px 16px" }}>
          <select value={ticker} onChange={(e) => onTicker(e.target.value)} style={{ width: "100%", border: `1px solid ${C.line2}`, borderRadius: 7, padding: "9px 11px", fontSize: 13, fontWeight: 600, fontFamily: "var(--sans)", color: C.ink, background: C.surface, cursor: "pointer", outline: "none" }}>
            {withNotes.map((x) => <option key={x.t} value={x.t}>{x.name} ({x.t})</option>)}
          </select>
          <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 8 }}>
            <Num size={20} weight={800} color={compColor(s.comp)}>{s.comp}</Num>
            <span style={{ fontSize: 11.5, color: C.ink3 }}>COMPOSITE</span>
            <button onClick={() => nav(s.t)} style={{ ...btnGhost, marginLeft: "auto" }}>종목 상세 →</button>
          </div>
        </div>
      </Panel>
      <Panel title="첨부 파일" sub={`${files.length} FILES`} right={<button style={{ border: `1px dashed ${C.line2}`, background: C.surface, color: C.acc, borderRadius: 7, padding: "4px 10px", fontSize: 11.5, fontWeight: 600, cursor: "pointer" }}>+ 업로드</button>}>
        <div>
          {files.map((f) => <div key={f.name} onClick={() => setActiveFile(f)} className="row-hover" style={{
            display: "flex", alignItems: "center", gap: 11, padding: "12px 16px", borderBottom: `1px solid ${C.line}`, cursor: "pointer",
            background: activeFile && activeFile.name === f.name ? C.accTint : "transparent",
          }}>
            <span className="mono" style={{ fontSize: 9, fontWeight: 700, color: f.type === "pdf" ? C.bad : C.acc, border: `1px solid ${(f.type === "pdf" ? C.bad : C.acc)}33`, borderRadius: 4, padding: "3px 5px" }}>{f.type.toUpperCase()}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: C.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.name}</div>
              <span className="mono" style={{ fontSize: 9.5, color: C.ink3 }}>{f.date}</span>
            </div>
          </div>)}
        </div>
      </Panel>
    </div>

    {/* right: viewer + memo */}
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Panel title={activeFile ? activeFile.name : "문서 뷰어"} sub="VIEWER">
        <div style={{ padding: 22, minHeight: 240, background: C.surface2, borderRadius: "0 0 0 0", display: "flex", flexDirection: "column", gap: 11 }}>
          {/* fake document preview */}
          <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 6, padding: "26px 30px", boxShadow: "0 1px 3px rgba(15,23,42,0.06)" }}>
            <div style={{ fontSize: 17, fontWeight: 800, color: C.ink, marginBottom: 4 }}>{s.name} · {activeFile ? activeFile.name.replace(/\.(pdf|md)$/, "") : "리서치"}</div>
            <div className="mono" style={{ fontSize: 10.5, color: C.ink3, marginBottom: 18 }}>{activeFile ? activeFile.date : ""} · {activeFile ? activeFile.type.toUpperCase() : ""}</div>
            {[100, 92, 96, 70].map((wd, i) => <div key={i} style={{ height: 9, width: wd + "%", background: C.tint, borderRadius: 3, marginBottom: 9 }}></div>)}
            <div style={{ height: 80, background: C.surface2, border: `1px solid ${C.line}`, borderRadius: 6, margin: "14px 0", display: "flex", alignItems: "center", justifyContent: "center" }}><MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>차트 / 표 영역</MonoCaps></div>
            {[88, 95, 60].map((wd, i) => <div key={i} style={{ height: 9, width: wd + "%", background: C.tint, borderRadius: 3, marginBottom: 9 }}></div>)}
          </div>
        </div>
      </Panel>

      <Panel title="투자 메모" sub="자유 기록" right={<div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        {saved && <MonoCaps style={{ fontSize: 9.5 }} color={C.ok}>✓ 저장됨</MonoCaps>}
        <button onClick={() => setSaved(true)} style={{ background: C.ink, color: "#fff", border: "none", borderRadius: 7, padding: "7px 16px", fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>저장</button>
      </div>}>
        <div style={{ padding: "14px 18px" }}>
          <textarea value={memo} onChange={(e) => { setMemo(e.target.value); setSaved(false); }} placeholder="이 종목에 대한 메모를 자유롭게 기록하세요…" style={{
            width: "100%", minHeight: 110, border: `1px solid ${C.line2}`, borderRadius: 8, padding: "12px 14px",
            fontSize: 13.5, fontFamily: "var(--sans)", lineHeight: 1.6, color: C.ink, resize: "vertical", outline: "none",
          }} />
          <div style={{ marginTop: 14 }}>
            <MonoCaps style={{ fontSize: 9.5 }}>태그</MonoCaps>
            <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginTop: 9 }}>
              {D.research.tags.map((t) => {
                const on = tags.includes(t);
                return <button key={t} onClick={() => toggleTag(t)} style={{
                  border: `1px solid ${on ? C.acc : C.line2}`, background: on ? C.acc : C.surface, color: on ? "#fff" : C.ink2,
                  borderRadius: 999, padding: "5px 13px", fontSize: 12, fontWeight: 600, cursor: "pointer", transition: "all .15s",
                }}>{t}</button>;
              })}
            </div>
          </div>
        </div>
      </Panel>
    </div>
  </div>;
}

Object.assign(window, { Screener, Market, Research });
