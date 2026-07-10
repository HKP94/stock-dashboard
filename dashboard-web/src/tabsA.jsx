// ATLAS — Tabs A: Overview, Stock Detail, News
import { useState, useMemo, useEffect } from 'react';
import {
  C, fmtPrice, compColor, sentMeta, flagTone,
  MonoCaps, Num, ChangePct, SentBadge, HoldDot, AlignBadge,
  CompositeCell, MiniBars, FactorBar, Sparkline, PriceChart,
  SentStack, Pill, RegimeBadge, SignalCard, GradeBadge, btnGhost,
} from './ui.jsx';
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { cleanDisplayText, extractBullets, filterStocks, portfolioAssetTotal, sortStocksBySentiment, isCompleteSignal } from './display.js';

// PR-2: 큰 금액 포맷 (KR: 조/억, US: B/M)
function fmtBig(v, cur) {
  if (v == null) return "—";
  const neg = v < 0 ? "-" : "";
  const a = Math.abs(v);
  if (cur === "₩") {
    if (a >= 1e12) return `${neg}${(a / 1e12).toFixed(1)}조`;
    if (a >= 1e8) return `${neg}${(a / 1e8).toFixed(0)}억`;
    return `${neg}${(a / 1e4).toFixed(0)}만`;
  }
  if (a >= 1e9) return `${neg}$${(a / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${neg}$${(a / 1e6).toFixed(0)}M`;
  return `${neg}$${a.toFixed(0)}`;
}

// PR-2: 종목상세 재무 추이 카드 (매출·영업이익·순이익·OCF·FCF + 추세 + 컨센서스)
function FinancialsCard({ s }) {
  const fin = s.financials || {};
  const cur = s.cur || "$";
  const ann = (fin.annual || []).map((a) => ({ ...a, yr: (a.period || "").slice(0, 4) }));

  if (!fin.hasData || ann.length === 0) {
    return (
      <Panel title="재무 추이" sub="매출·이익·현금흐름">
        <div style={{ padding: "28px 18px", textAlign: "center", color: C.ink3, fontSize: 12.5 }}>
          재무 데이터가 없습니다. (KR 일부 종목은 공시 수집 제약으로 비어 있을 수 있습니다.)
        </div>
      </Panel>
    );
  }

  const TrendTag = ({ label, v }) => v == null ? null : (
    <span style={{ fontSize: 11, color: v >= 0 ? C.ok : C.bad, fontWeight: 600 }}>
      {label} {v >= 0 ? "▲" : "▼"} {Math.abs(v).toFixed(1)}%
    </span>
  );

  const tip = (val) => fmtBig(val, cur);
  const hasCF = ann.some((a) => a.ocf != null || a.fcf != null);

  return (
    <Panel title="재무 추이" sub="연간 · 매출·이익·현금흐름"
      right={<div style={{ display: "flex", gap: 12 }}><TrendTag label="매출" v={fin.revTrend} /><TrendTag label="영업이익" v={fin.opTrend} /></div>}>
      <div style={{ padding: "14px 12px 4px" }}>
        <MonoCaps style={{ fontSize: 9, marginLeft: 6 }} color={C.ink3}>매출 · 영업이익 · 순이익 (막대) / 영업이익률 % (선)</MonoCaps>
        <ResponsiveContainer width="100%" height={210}>
          <ComposedChart data={ann} margin={{ top: 12, right: 8, left: 4, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={C.line} vertical={false} />
            <XAxis dataKey="yr" tick={{ fontSize: 11, fill: C.ink3 }} axisLine={{ stroke: C.line2 }} tickLine={false} />
            <YAxis yAxisId="l" tick={{ fontSize: 10, fill: C.ink3 }} tickFormatter={(v) => fmtBig(v, cur)} axisLine={false} tickLine={false} width={52} />
            <YAxis yAxisId="r" orientation="right" tick={{ fontSize: 10, fill: C.acc }} tickFormatter={(v) => v + "%"} axisLine={false} tickLine={false} width={36} />
            <Tooltip formatter={(val, name) => name === "영업이익률" ? [val + "%", name] : [tip(val), name]} labelStyle={{ fontWeight: 700 }} contentStyle={{ fontSize: 12, borderRadius: 8, border: `1px solid ${C.line2}` }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar yAxisId="l" dataKey="rev" name="매출" fill={C.ink2} radius={[3, 3, 0, 0]} maxBarSize={26} />
            <Bar yAxisId="l" dataKey="op" name="영업이익" fill={C.acc} radius={[3, 3, 0, 0]} maxBarSize={26} />
            <Bar yAxisId="l" dataKey="ni" name="순이익" fill={C.ok} radius={[3, 3, 0, 0]} maxBarSize={26} />
            <Line yAxisId="r" type="monotone" dataKey="opm" name="영업이익률" stroke={C.warn} strokeWidth={2} dot={{ r: 3 }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {hasCF && (
        <div style={{ padding: "4px 12px 10px", borderTop: `1px solid ${C.line}` }}>
          <MonoCaps style={{ fontSize: 9, marginLeft: 6, marginTop: 8, display: "block" }} color={C.ink3}>영업현금흐름(OCF) · 잉여현금흐름(FCF)</MonoCaps>
          <ResponsiveContainer width="100%" height={150}>
            <ComposedChart data={ann} margin={{ top: 10, right: 8, left: 4, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={C.line} vertical={false} />
              <XAxis dataKey="yr" tick={{ fontSize: 11, fill: C.ink3 }} axisLine={{ stroke: C.line2 }} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: C.ink3 }} tickFormatter={(v) => fmtBig(v, cur)} axisLine={false} tickLine={false} width={52} />
              <Tooltip formatter={(val, name) => [tip(val), name]} contentStyle={{ fontSize: 12, borderRadius: 8, border: `1px solid ${C.line2}` }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="ocf" name="영업현금흐름" fill={C.acc} radius={[3, 3, 0, 0]} maxBarSize={26} />
              <Bar dataKey="fcf" name="잉여현금흐름" fill={C.ink3} radius={[3, 3, 0, 0]} maxBarSize={26} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* 컨센서스 전망 (있으면) */}
      {(s.tp || s.up != null || s.rating || s.per) && (
        <div style={{ padding: "11px 16px", borderTop: `1px solid ${C.line}`, background: C.surface2, borderRadius: "0 0 10px 10px", display: "flex", gap: 20, flexWrap: "wrap", alignItems: "center" }}>
          <MonoCaps style={{ fontSize: 9 }} color={C.ink3}>컨센서스 전망</MonoCaps>
          {s.tp != null && <span style={{ fontSize: 12, color: C.ink2 }}>목표가 <b style={{ color: C.ink }}>{s.cur}{Math.round(s.tp).toLocaleString()}</b></span>}
          {s.up != null && <span style={{ fontSize: 12, color: C.ink2 }}>상승여력 <b style={{ color: s.up >= 0 ? C.ok : C.bad }}>{s.up >= 0 ? "+" : ""}{s.up}%</b></span>}
          {s.rating && <span style={{ fontSize: 12, color: C.ink2 }}>투자의견 <b style={{ color: C.ink }}>{s.rating}</b></span>}
          {s.per != null && <span style={{ fontSize: 12, color: C.ink2 }}>PER <b style={{ color: C.ink }}>{s.per}</b></span>}
        </div>
      )}
    </Panel>
  );
}

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
  // PR-2: 헤더(플래그)와 본문이 중복되지 않도록 미매칭 플래그도 '근거 문장'으로
  if (/목표가 근접/.test(f)) return s.tp != null ? `컨센서스 목표가에 근접 — 추가 상승 여력 축소 점검` : "컨센서스 목표가에 근접";
  if (/골든크로스/.test(f)) return "단기·중기 이동평균선 교차 임박";
  if (/급등/.test(f)) return "단기 급등 — 변동성·차익실현 유의";
  if (/급락/.test(f)) return "단기 급락 — 과매도 여부·악재 점검";
  if (/이격도/.test(f)) return "주가가 이동평균선에서 크게 이탈 — 단기 되돌림 가능";
  return "";  // 매칭 없으면 본문 생략(헤더와 중복 방지)
};

// PR-3: 플래그 분류 헬퍼 (data.json이 분리되어 있지만 fallback 포함)
const isDataQuality = (f) => /데이터 부족|사전필터 제외|발행주식수 데이터 없음|데이터 없음/.test(f);

// ============================ OVERVIEW ============================
// PR-1: 오버뷰 최상단 "오늘의 요약 밴드" — 30초 스캔용 합성 인사이트 (정보·관찰용)
function DailyBriefBand({ b, regimes, nav }) {
  if (!b) return null;
  const regimeMeta = (regimes && regimes[b.regime]) || {};
  const Chip = ({ item, color }) => (
    <button onClick={() => nav(item.t)} className="row-hover"
      style={{ display: "block", width: "100%", textAlign: "left", border: "none", background: "none", cursor: "pointer", padding: "5px 8px", borderRadius: 6 }}>
      <span style={{ fontSize: 12.5, fontWeight: 700, color: C.ink }}>{item.name}</span>
      <span style={{ fontSize: 11, color: C.ink2, marginLeft: 6 }}>{item.why}</span>
    </button>
  );
  const Col = ({ label, color, items, empty }) => (
    <div style={{ flex: 1, minWidth: 0, padding: "10px 10px", borderLeft: `3px solid ${color}` }}>
      <MonoCaps style={{ fontSize: 9, marginLeft: 8, marginBottom: 4, display: "block" }} color={color}>{label}</MonoCaps>
      {items && items.length > 0 ? items.map((it) => <Chip key={it.t} item={it} color={color} />)
        : <div style={{ fontSize: 11, color: C.ink3, padding: "5px 8px" }}>{empty}</div>}
    </div>
  );
  return (
    <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 12, boxShadow: "0 1px 2px rgba(15,23,42,0.04)", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "11px 16px", borderBottom: `1px solid ${C.line}`, background: C.surface2 }}>
        <span style={{ fontSize: 13, fontWeight: 800, color: C.ink }}>오늘의 요약</span>
        <MonoCaps style={{ fontSize: 8.5 }} color={C.ink3}>30초 스캔 · 정보·관찰용</MonoCaps>
        <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          <RegimeBadge regime={b.regime} regimes={regimes} />
          <span style={{ fontSize: 11.5, color: C.ink2, maxWidth: 420, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={`${b.krLine}\n${b.usLine}`}>{b.usLine || b.krLine || b.marketLine}</span>
        </span>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap" }}>
        <Col label="▲ 주목 (퀀트 상위·신선 신호)" color={C.ok} items={b.highlights} empty="해당 종목 없음" />
        <Col label="▼ 주의 (위험 신호)" color={C.bad} items={b.cautions} empty="오늘 두드러진 주의 신호 없음" />
        <Col label="⚠ 3축 괴리 (확인 필요)" color={C.warn} items={b.diverge} empty="퀀트·컨센서스 큰 괴리 없음" />
      </div>
    </div>
  );
}

// 신규-G: 오늘의 이상 움직임(급등·급락 감지 + 귀인). 관찰·서술만. "이유 불명"=리스크로 부각.
function AnomaliesBand({ items, nav }) {
  if (!items || items.length === 0) return null;
  const top = items.slice(0, 6);
  return (
    <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 12, boxShadow: "0 1px 2px rgba(15,23,42,0.04)", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "11px 16px", borderBottom: `1px solid ${C.line}`, background: C.surface2 }}>
        <span style={{ fontSize: 13, fontWeight: 800, color: C.ink }}>오늘의 이상 움직임</span>
        <MonoCaps style={{ fontSize: 8.5 }} color={C.ink3}>급등·급락 감지 + 귀인 · 관찰용</MonoCaps>
        <span style={{ marginLeft: "auto", fontSize: 10.5, color: C.ink3 }}>‘이유 불명’ = 설명 뉴스·수급 미포착(정보 선반영 가능성)</span>
      </div>
      <div>
        {top.map((a) => {
          const up = a.direction === "급등";
          const unknown = a.class === "이유 불명";
          const dirColor = up ? C.ok : C.bad;
          const classColor = unknown ? C.bad : C.ink2;
          return (
            <button key={a.t} onClick={() => nav(a.t)} className="row-hover"
              style={{ display: "flex", alignItems: "center", gap: 9, width: "100%", textAlign: "left", border: "none", borderTop: `1px solid ${C.line}`, background: "none", cursor: "pointer", padding: "8px 14px" }}>
              <span style={{ fontSize: 12.5, fontWeight: 700, color: C.ink, minWidth: 96, flexShrink: 0 }}>{a.name}</span>
              <span style={{ fontSize: 12.5, fontWeight: 800, color: dirColor, minWidth: 70, flexShrink: 0 }}>{up ? "▲" : "▼"} {a.ret != null ? `${a.ret > 0 ? "+" : ""}${a.ret}%` : ""}</span>
              <span style={{ fontSize: 9.5, fontWeight: 700, color: classColor, border: `1px solid ${classColor}`, borderRadius: 4, padding: "1px 5px", flexShrink: 0 }}>{a.class}</span>
              {a.unusual && <span title="이 종목 기준 이례적 변동폭" style={{ fontSize: 9, color: C.warn, border: `1px solid ${C.warn}`, borderRadius: 4, padding: "1px 4px", flexShrink: 0 }}>이례적 z{a.z}</span>}
              {a.idiosyncratic && <span title="지수 대비 자체 이동" style={{ fontSize: 9, color: C.ink3, flexShrink: 0 }}>자체이동</span>}
              <span style={{ fontSize: 11, color: unknown ? C.bad : C.ink2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, minWidth: 0 }}>{a.reason}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

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
  const summaryText = extractBullets(summaryMd, { limit: 2 }).join(" / ");
  const overall = D.market.overall;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* PR-1: 오늘의 요약 밴드 (최상단, 지수 스트립 위) */}
      <DailyBriefBand b={D.dailyBrief} regimes={D.regimes} nav={nav} />

      {/* 신규-G: 오늘의 이상 움직임(급등·급락 감지 + 귀인) */}
      <AnomaliesBand items={D.moveAnomalies} nav={nav} />

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
      {portfolioAssetTotal(D.portfolio) != null && (
        <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10, padding: "14px 20px", display: "flex", alignItems: "center", gap: 24 }}>
          <div>
            <MonoCaps style={{ fontSize: 9 }}>내 포트폴리오 (₩ 환산)</MonoCaps>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 4 }}>
              <Num size={22} weight={800} style={{ textDecoration: "none" }}>
                ₩{Math.round(portfolioAssetTotal(D.portfolio)).toLocaleString("ko-KR")}
              </Num>
              <span style={{ fontSize: 12, color: C.ink3 }}>총자산</span>
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
          sub={`종합 점수 내림차순 · ${rows.length}종목`}
          right={<FilterTabs value={filter} onChange={setFilter} options={[{ k: "all", label: "전체" }, { k: "KR", label: "KR" }, { k: "US", label: "US" }, { k: "hold", label: "보유" }]} />}
        >
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${C.line2}` }}>
                {["", "종목", "현재가", "종합", "모멘텀·가치·우량성·성장·심리", "RSI", "추세", "주요 플래그", "판단"].map((h, i) => {
                  // PR-5: 약어 헤더 툴팁
                  const tip = {
                    "종합": "5개 팩터를 국면 가중치로 합산한 종합 점수(0~100)",
                    "모멘텀·가치·우량성·성장·심리": "모멘텀 · 가치 · 우량성 · 성장 · 심리 (5팩터 점수)",
                    "RSI": "상대강도지수(14일) — 70↑ 과열, 30↓ 과매도",
                    "추세": "이동평균선 정배열(20>60>120) 여부",
                    "판단": "내 투자 판단(방향·매력도)",
                  }[h];
                  return (
                    <th key={i} title={tip || undefined} style={{ textAlign: "left", padding: "9px 12px", cursor: tip ? "help" : "default" }}>
                      <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{h}</MonoCaps>
                    </th>
                  );
                })}
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
                    <td style={{ padding: "10px 12px", width: 150 }}>
                      {s.comp == null
                        ? <span title="사전필터(F-Score·고유변동성)로 종합점수 제외" style={{ fontSize: 10.5, fontWeight: 700, color: C.ink3, background: C.surface2, border: `1px solid ${C.line}`, borderRadius: 5, padding: "3px 8px", whiteSpace: "nowrap", cursor: "help" }}>사전필터 제외</span>
                        : <CompositeCell value={s.comp} />}
                    </td>
                    <td style={{ padding: "10px 12px" }}><MiniBars f={s.f} /></td>
                    <td style={{ padding: "10px 12px" }}><Num size={13} weight={600} color={s.rsi == null ? C.ink3 : s.rsi >= 70 ? C.bad : s.rsi <= 35 ? C.acc : C.ink2}>{s.rsi == null ? "—" : s.rsi.toFixed(0)}</Num></td>
                    <td style={{ padding: "10px 12px", whiteSpace: "nowrap" }}><AlignBadge on={s.align} /></td>
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
            {actionAlerts.map((a, i) => {
              const desc = flagDesc(a.f, a.s);  // PR-2: 헤더(플래그)와 다른 근거 문장. 빈 값이면 본문 생략
              return (
              <div key={i} onClick={() => nav(a.s.t)} className="row-hover" style={{ display: "flex", gap: 11, padding: "11px 16px", borderBottom: `1px solid ${C.line}`, cursor: "pointer", alignItems: "flex-start" }}>
                <span style={{ width: 3, alignSelf: "stretch", borderRadius: 2, background: flagTone(a.f), flexShrink: 0 }}></span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 2 }}>
                    <span style={{ fontSize: 12.5, fontWeight: 700, color: C.ink }}>{a.s.name}</span>
                    <span style={{ fontSize: 11, fontWeight: 700, color: flagTone(a.f) }}>{a.f}</span>
                  </div>
                  {desc && <div style={{ fontSize: 11.5, color: C.ink2, lineHeight: 1.4 }}>{desc}</div>}
                </div>
              </div>
            );})}
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

// ── PR-2: 리서치 항목 (종목상세·리서치 탭 공용) ──────────────────────
export function toYtEmbed(url) {
  if (!url) return null;
  const m = url.match(/(?:youtu\.be\/|[?&]v=)([\w-]{11})/);
  return m ? `https://www.youtube.com/embed/${m[1]}` : null;
}
export const RESEARCH_TYPE_LABEL = { youtube: "유튜브", article: "기사", report: "리포트", quant: "퀀트", memo: "메모" };
export const RESEARCH_TYPE_COLOR = { youtube: C.bad, article: C.acc, report: C.warn, quant: C.ok, memo: C.ink3 };

export function ResearchItemCard({ item, onDelete }) {
  const ytEmbed = item.type === "youtube" ? toYtEmbed(item.url) : null;
  const col = RESEARCH_TYPE_COLOR[item.type] || C.ink3;
  return (
    <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 8, overflow: "hidden", marginBottom: 12 }}>
      <div style={{ padding: "10px 14px", display: "flex", alignItems: "center", gap: 10, borderBottom: ytEmbed ? `1px solid ${C.line}` : "none" }}>
        <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 4, background: col + "18", color: col, border: `1px solid ${col}33` }}>{RESEARCH_TYPE_LABEL[item.type] || item.type}</span>
        {item.url ? (
          <a href={item.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 13.5, fontWeight: 700, color: C.ink, textDecoration: "none", flex: 1 }}>{item.title}</a>
        ) : (
          <span style={{ fontSize: 13.5, fontWeight: 700, color: C.ink, flex: 1 }}>{item.title}</span>
        )}
        <span className="mono" style={{ fontSize: 9.5, color: C.ink3, flexShrink: 0 }}>{item.addedAt}</span>
        {item.url && <a href={item.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 11, color: C.acc, textDecoration: "none", flexShrink: 0 }}>↗</a>}
        {onDelete && <button onClick={() => onDelete(item.id)} title="삭제" style={{ border: "none", background: "none", cursor: "pointer", color: C.ink3, fontSize: 13, flexShrink: 0, padding: 0 }}>✕</button>}
      </div>
      {ytEmbed && (
        <div style={{ position: "relative", paddingBottom: "56.25%", background: "#000" }}>
          <iframe src={ytEmbed} title={item.title} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", border: "none" }}
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowFullScreen />
        </div>
      )}
      {item.note && <div style={{ padding: "8px 14px", fontSize: 12.5, color: C.ink2, lineHeight: 1.55, background: C.surface2 }}>{item.note}</div>}
    </div>
  );
}

// PR-2: 종목상세 리서치 섹션 — 유형별 표시 + 빠른 추가(해당 ticker 프리필)
export function StockResearchSection({ s }) {
  const [items, setItems] = useState(s.researchItems || []);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ item_type: "youtube", title: "", url: "", note: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => { setItems(s.researchItems || []); setOpen(false); setForm({ item_type: "youtube", title: "", url: "", note: "" }); }, [s.t, s.researchItems]);

  const refetch = async () => {
    try { const r = await fetch(`${API}/api/research/${s.t}`); if (r.ok) setItems(await r.json()); } catch (_) {}
  };
  const add = async () => {
    if (!form.title.trim()) { setErr("제목을 입력하세요."); return; }
    setBusy(true); setErr("");
    try {
      const r = await fetch(`${API}/api/research`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...form, ticker: s.t }) });
      if (!r.ok) throw new Error();
      setForm({ item_type: "youtube", title: "", url: "", note: "" }); setOpen(false);
      await refetch();
    } catch (_) { setErr("추가 실패 — 데이터 서버 연결을 확인하세요."); }
    setBusy(false);
  };
  const del = async (id) => { try { await fetch(`${API}/api/research/${id}`, { method: "DELETE" }); await refetch(); } catch (_) {} };

  const order = ["report", "youtube", "article", "quant", "memo"];
  const grouped = order.map((t) => [t, items.filter((i) => i.type === t)]).filter(([, v]) => v.length > 0);

  return (
    <Panel title="리서치" sub="전문가 보고서 · 내가 조사한 자료"
      right={<button onClick={() => setOpen((o) => !o)} style={{ ...btnGhost }}>{open ? "닫기 −" : "+ 추가"}</button>}>
      {open && (
        <div style={{ padding: "14px 16px", borderBottom: `1px solid ${C.line}`, background: C.surface2, display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <select value={form.item_type} onChange={(e) => setForm((f) => ({ ...f, item_type: e.target.value }))}
              style={{ border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 13, fontFamily: "var(--sans)", color: C.ink, background: C.surface, cursor: "pointer" }}>
              {Object.entries(RESEARCH_TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <input value={form.title} placeholder="제목 (예: 3Q 실적 리뷰)" onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
              style={{ flex: 1, minWidth: 160, border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 13, outline: "none", color: C.ink }} />
          </div>
          <input value={form.url} placeholder="URL (유튜브/기사/리포트 링크, 선택)" onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
            style={{ border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 13, outline: "none", color: C.ink }} />
          <textarea value={form.note} placeholder="메모 (선택)" onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
            style={{ minHeight: 50, border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 13, fontFamily: "var(--sans)", resize: "vertical", outline: "none", color: C.ink, boxSizing: "border-box" }} />
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button onClick={add} disabled={busy} style={{ background: C.ink, color: "#fff", border: "none", borderRadius: 7, padding: "8px 18px", fontSize: 12.5, fontWeight: 600, cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1 }}>{busy ? "추가 중…" : "추가"}</button>
            <span className="mono" style={{ fontSize: 10, color: C.ink3 }}>{s.name} ({s.t})</span>
            {err && <span style={{ fontSize: 11.5, color: C.bad }}>{err}</span>}
          </div>
        </div>
      )}
      <div style={{ padding: "14px 16px" }}>
        {items.length === 0 ? (
          <div style={{ padding: "18px 0", textAlign: "center", color: C.ink3, fontSize: 12.5 }}>등록된 리서치가 없습니다. "+ 추가"로 전문가 보고서·유튜브·메모를 정리하세요.</div>
        ) : grouped.map(([t, list]) => (
          <div key={t} style={{ marginBottom: 8 }}>
            <MonoCaps style={{ fontSize: 9, marginBottom: 6, display: "block" }} color={RESEARCH_TYPE_COLOR[t]}>{RESEARCH_TYPE_LABEL[t]} · {list.length}</MonoCaps>
            {list.map((it) => <ResearchItemCard key={it.id} item={it} onDelete={del} />)}
          </div>
        ))}
      </div>
    </Panel>
  );
}

function DriverTonePill({ tone }) {
  const map = {
    support: { label: "우호", color: C.ok, bg: C.okBg },
    oppose: { label: "부담", color: C.bad, bg: C.badBg },
    neutral: { label: "중립", color: C.ink3, bg: C.surface2 },
  };
  const meta = map[tone] || map.neutral;
  return (
    <span style={{
      fontSize: 10.5, fontWeight: 700, color: meta.color, background: meta.bg,
      border: `1px solid ${meta.color}22`, borderRadius: 5, padding: "2px 7px",
    }}>
      {meta.label}
    </span>
  );
}

function DriverRow({ item, draft, busy, onDraftChange, onSave, onDelete }) {
  const series = (item.series || []).map((point) => Number(point.value)).filter((v) => Number.isFinite(v));
  const implication = item.implication || {};
  return (
    <div style={{ padding: "14px 16px", borderBottom: `1px solid ${C.line}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 13.5, fontWeight: 700, color: C.ink }}>{item.name}</span>
        <span className="mono" style={{ fontSize: 9.5, color: C.ink3 }}>{item.code}</span>
        <Pill tone={item.origin === "auto" ? "warn" : "neutral"}>{item.badge}</Pill>
        <span style={{ fontSize: 10.5, color: C.ink2 }}>영향도 {item.weight}/5</span>
        {item.asof && <span className="mono" style={{ marginLeft: "auto", fontSize: 9.5, color: C.ink3 }}>기준일 {item.asof}</span>}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "160px 1fr", gap: 14, marginTop: 10, alignItems: "center" }}>
        <div style={{ background: C.surface2, borderRadius: 8, padding: "10px 12px", minHeight: 76 }}>
          {series.length >= 2 ? (
            <>
              <Sparkline data={series} color={item.deltaDay >= 0 ? C.ok : C.bad} w={130} h={34} fill />
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 10.5, color: C.ink2 }}>
                <span>{item.price != null ? item.price.toLocaleString() : "—"}</span>
                <span className="tnum" style={{ color: item.deltaMonth >= 0 ? C.ok : item.deltaMonth < 0 ? C.bad : C.ink3 }}>
                  {item.deltaMonth != null ? `${item.deltaMonth > 0 ? "+" : ""}${item.deltaMonth}%` : "월간 변화 없음"}
                </span>
              </div>
            </>
          ) : (
            <div style={{ fontSize: 11.5, color: C.ink3, lineHeight: 1.5 }}>
              {item.driverSource === "proxy_none" ? "무료 프록시 없음" : "가격 이력 수집 대기 중"}
            </div>
          )}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <DriverTonePill tone={implication.tone} />
            <span style={{ fontSize: 12, color: C.ink2, lineHeight: 1.5 }}>{cleanDisplayText(implication.text || "가격 함의 계산 대기 중")}</span>
          </div>
          <div style={{ fontSize: 11.5, color: C.ink2, lineHeight: 1.55 }}>
            {cleanDisplayText(item.rationale || "") || "동인 근거 없음"}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <select
              value={draft.weight}
              onChange={(event) => onDraftChange(item.code, "weight", Number(event.target.value))}
              style={{ border: `1px solid ${C.line2}`, borderRadius: 7, padding: "7px 9px", background: C.surface, color: C.ink }}
            >
              {[1, 2, 3, 4, 5].map((weight) => <option key={weight} value={weight}>영향도 {weight}</option>)}
            </select>
            <input
              value={draft.rationale}
              placeholder="근거 메모"
              onChange={(event) => onDraftChange(item.code, "rationale", event.target.value)}
              style={{ flex: 1, minWidth: 220, border: `1px solid ${C.line2}`, borderRadius: 7, padding: "7px 10px", fontSize: 12.5, color: C.ink }}
            />
            <button onClick={() => onSave(item)} disabled={busy}
              style={{ ...btnGhost, color: C.acc, opacity: busy ? 0.6 : 1 }}>
              {busy ? "저장 중…" : "저장"}
            </button>
            <button onClick={() => onDelete(item.code)} disabled={busy}
              style={{ ...btnGhost, color: C.bad, opacity: busy ? 0.6 : 1 }}>
              삭제
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function StockDriversSection({ s }) {
  const [items, setItems] = useState(s.drivers || []);
  const [drafts, setDrafts] = useState({});
  const [busyCode, setBusyCode] = useState("");
  const [autoBusy, setAutoBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ driver_code: "", driver_name: "", driver_source: "yfinance_proxy", weight: 3, rationale: "" });

  useEffect(() => {
    setItems(s.drivers || []);
    setDrafts(Object.fromEntries((s.drivers || []).map((item) => [item.code, { weight: item.weight, rationale: item.rationale || "" }])));
    setMsg("");
    setErr("");
    setOpen(false);
    setForm({ driver_code: "", driver_name: "", driver_source: "yfinance_proxy", weight: 3, rationale: "" });
  }, [s.t, s.drivers]);

  const load = async () => {
    try {
      const response = await fetch(`${API}/api/drivers/${s.t}`);
      if (!response.ok) throw new Error();
      const rows = await response.json();
      const merged = rows.map((row) => {
        const existing = (items || []).find((item) => item.code === row.driver_code);
        return {
          code: row.driver_code,
          name: row.driver_name,
          driverSource: row.driver_source,
          weight: row.weight,
          origin: row.origin,
          badge: row.origin === "auto" ? "추정" : "사용자",
          rationale: row.rationale || "",
          asof: existing?.asof || null,
          price: existing?.price ?? null,
          deltaDay: existing?.deltaDay ?? null,
          deltaMonth: existing?.deltaMonth ?? null,
          series: existing?.series || [],
          implication: existing?.implication || { tone: "neutral", text: "가격 수집 후 함의를 표시합니다." },
        };
      });
      setItems(merged);
      setDrafts(Object.fromEntries(merged.map((item) => [item.code, { weight: item.weight, rationale: item.rationale || "" }])));
    } catch (_) {
      setErr("드라이버 목록을 다시 불러오지 못했습니다.");
    }
  };

  const patchDraft = (code, field, value) => {
    setDrafts((prev) => ({ ...prev, [code]: { ...(prev[code] || {}), [field]: value } }));
  };

  const saveItem = async (item) => {
    const draft = drafts[item.code] || { weight: item.weight, rationale: item.rationale || "" };
    setBusyCode(item.code); setErr(""); setMsg("");
    try {
      const response = await fetch(`${API}/api/drivers/${s.t}/${item.code}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ weight: draft.weight, rationale: draft.rationale }),
      });
      if (!response.ok) throw new Error();
      setItems((prev) => prev.map((entry) => entry.code === item.code ? { ...entry, weight: draft.weight, rationale: draft.rationale, origin: "user", badge: "사용자" } : entry));
      setMsg("드라이버를 저장했습니다.");
    } catch (_) {
      setErr("저장 실패 — 데이터 서버 연결을 확인하세요.");
    }
    setBusyCode("");
  };

  const deleteItem = async (code) => {
    setBusyCode(code); setErr(""); setMsg("");
    try {
      const response = await fetch(`${API}/api/drivers/${s.t}/${code}`, { method: "DELETE" });
      if (!response.ok) throw new Error();
      setItems((prev) => prev.filter((entry) => entry.code !== code));
      setDrafts((prev) => {
        const next = { ...prev };
        delete next[code];
        return next;
      });
      setMsg("드라이버를 삭제했습니다.");
    } catch (_) {
      setErr("삭제 실패 — 데이터 서버 연결을 확인하세요.");
    }
    setBusyCode("");
  };

  const addItem = async () => {
    if (!form.driver_code.trim() || !form.driver_name.trim()) {
      setErr("코드와 이름을 입력하세요.");
      return;
    }
    setBusyCode("new"); setErr(""); setMsg("");
    try {
      const response = await fetch(`${API}/api/drivers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, ticker: s.t }),
      });
      if (!response.ok) throw new Error();
      await load();
      setOpen(false);
      setForm({ driver_code: "", driver_name: "", driver_source: "yfinance_proxy", weight: 3, rationale: "" });
      setMsg("사용자 드라이버를 추가했습니다.");
    } catch (_) {
      setErr("추가 실패 — 데이터 서버 연결을 확인하세요.");
    }
    setBusyCode("");
  };

  const autoMap = async () => {
    setAutoBusy(true); setErr(""); setMsg("");
    try {
      const response = await fetch(`${API}/api/drivers/${s.t}/auto-map`, { method: "POST" });
      if (!response.ok) throw new Error();
      await load();
      setMsg("자동 추정 드라이버를 갱신했습니다. 사용자 수정값은 유지됩니다.");
    } catch (_) {
      setErr("자동 추정 실패 — 데이터 서버 연결을 확인하세요.");
    }
    setAutoBusy(false);
  };

  return (
    <Panel
      title="핵심 동인"
      sub="가격 동인 · 프록시 · 사용자 수정 우선"
      right={
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button onClick={autoMap} disabled={autoBusy} style={{ ...btnGhost, color: C.warn, opacity: autoBusy ? 0.6 : 1 }}>
            {autoBusy ? "추정 중…" : "자동 추정"}
          </button>
          <button onClick={() => setOpen((value) => !value)} style={{ ...btnGhost, color: C.acc }}>
            {open ? "닫기 −" : "+ 추가"}
          </button>
        </div>
      }
    >
      {open && (
        <div style={{ padding: "14px 16px", borderBottom: `1px solid ${C.line}`, background: C.surface2, display: "grid", gap: 10 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr 150px 120px", gap: 8 }}>
            <input value={form.driver_code} placeholder="코드 (예: SOXX)" onChange={(event) => setForm((prev) => ({ ...prev, driver_code: event.target.value.toUpperCase() }))}
              style={{ border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 12.5, color: C.ink }} />
            <input value={form.driver_name} placeholder="이름 (예: 반도체 ETF)" onChange={(event) => setForm((prev) => ({ ...prev, driver_name: event.target.value }))}
              style={{ border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 12.5, color: C.ink }} />
            <select value={form.driver_source} onChange={(event) => setForm((prev) => ({ ...prev, driver_source: event.target.value }))}
              style={{ border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", background: C.surface, color: C.ink }}>
              <option value="yfinance_proxy">프록시 가격</option>
              <option value="shared_macro">거시 재사용</option>
              <option value="proxy_none">프록시 없음</option>
            </select>
            <select value={form.weight} onChange={(event) => setForm((prev) => ({ ...prev, weight: Number(event.target.value) }))}
              style={{ border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", background: C.surface, color: C.ink }}>
              {[1, 2, 3, 4, 5].map((weight) => <option key={weight} value={weight}>영향도 {weight}</option>)}
            </select>
          </div>
          <textarea value={form.rationale} placeholder="왜 이 동인인지 1줄 메모" onChange={(event) => setForm((prev) => ({ ...prev, rationale: event.target.value }))}
            style={{ minHeight: 58, border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 12.5, fontFamily: "var(--sans)", resize: "vertical", color: C.ink }} />
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button onClick={addItem} disabled={busyCode === "new"} style={{ background: C.ink, color: "#fff", border: "none", borderRadius: 7, padding: "8px 16px", fontSize: 12.5, fontWeight: 700, opacity: busyCode === "new" ? 0.6 : 1 }}>
              {busyCode === "new" ? "추가 중…" : "추가"}
            </button>
            <span className="mono" style={{ fontSize: 9.5, color: C.ink3 }}>{s.name} · {s.t}</span>
          </div>
        </div>
      )}

      {msg && <div style={{ padding: "10px 16px 0", fontSize: 12, color: C.ok }}>{msg}</div>}
      {err && <div style={{ padding: "10px 16px 0", fontSize: 12, color: C.bad }}>{err}</div>}

      {(items || []).length === 0 ? (
        <div style={{ padding: "22px 18px", textAlign: "center", color: C.ink3, fontSize: 12.5 }}>
          아직 등록된 핵심 동인이 없습니다. 자동 추정으로 시작하거나 직접 추가하세요.
        </div>
      ) : (
        <div>
          {items.map((item) => (
            <DriverRow
              key={item.code}
              item={item}
              draft={drafts[item.code] || { weight: item.weight, rationale: item.rationale || "" }}
              busy={busyCode === item.code}
              onDraftChange={patchDraft}
              onSave={saveItem}
              onDelete={deleteItem}
            />
          ))}
        </div>
      )}
    </Panel>
  );
}

// ── PR-1+3: 매력도 3축 카드 (퀀트·컨센서스·내 판단 나란히, 단일점수 금지) ──
function _upsideGrade(up) {
  if (up == null) return null;
  if (up >= 20) return { label: "높음", col: C.ok };
  if (up >= 5) return { label: "보통", col: C.warn };
  return { label: "낮음", col: C.bad };
}
function _level(kind, v) {
  if (v == null) return null;
  if (kind === "quant") return v >= 60 ? "높음" : v < 40 ? "낮음" : "보통";
  if (kind === "cons") return v >= 20 ? "높음" : v < 5 ? "낮음" : "보통";
  return v >= 4 ? "높음" : v <= 2 ? "낮음" : "보통";  // my (attractiveness)
}

// 신규-A2: 등급 근거 한 줄(퀀트·컨센서스·내 판단의 강/중/약). gradeBasis.axes 사용.
const GRADE_AXIS_KO = { quant: "퀀트", consensus: "컨센서스", judgment: "내 판단" };
function gradeAxisSummary(basis) {
  const axes = (basis && basis.axes) || {};
  return Object.entries(axes).filter(([, v]) => v).map(([k, v]) => `${GRADE_AXIS_KO[k] || k} ${v}`).join(" · ");
}

function AxesCard({ s }) {
  const [note, setNote] = useState(s.note || { horizon: null, attractiveness: null, thesis: "" });
  const [history, setHistory] = useState(s.noteHistory || []);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => { setNote(s.note || { horizon: null, attractiveness: null, thesis: "" }); setHistory(s.noteHistory || []); setSaved(false); setConfirmDel(false); }, [s.t, s.note, s.noteHistory]);
  useEffect(() => {
    fetch(`${API}/api/notes/${s.t}`).then((r) => r.json()).then((d) => {
      if (d) { setNote({ horizon: d.horizon, attractiveness: d.attractiveness, thesis: "" }); setHistory(d.history || []); }
    }).catch(() => {});
  }, [s.t]);

  const saveNote = async () => {
    if (!(note.thesis || "").trim()) return;
    setSaving(true);
    try {
      const response = await fetch(`${API}/api/notes/${s.t}`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ horizon: note.horizon, attractiveness: note.attractiveness, thesis: note.thesis }) });
      if (!response.ok) throw new Error();
      const data = await response.json();
      setHistory(data.history || []);
      setNote((current) => ({ ...current, thesis: "" }));
      setSaved(true); setTimeout(() => setSaved(false), 1800);
    } catch (_) {}
    setSaving(false);
  };

  const deleteNote = async () => {
    setDeleting(true);
    try {
      const res = await fetch(`${API}/api/notes/${s.t}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      setNote({ horizon: null, attractiveness: null, thesis: "" });
      setHistory([]);
      setConfirmDel(false);
    } catch (_) {}
    setDeleting(false);
  };

  const hasCons = s.tp != null || s.up != null || s.rating;
  const ug = _upsideGrade(s.up);
  const qLevel = _level("quant", s.comp);
  const cLevel = hasCons ? _level("cons", s.up) : null;
  const mLevel = note.attractiveness != null ? _level("my", note.attractiveness) : null;

  // 축 간 괴리(확인편향 방지): 한 축 '높음' & 다른 축 '낮음'이면 표시
  const pairs = [[qLevel, cLevel, "퀀트", "컨센서스"], [qLevel, mLevel, "퀀트", "내 판단"], [cLevel, mLevel, "컨센서스", "내 판단"]];
  const diverge = pairs.filter(([a, b]) => a && b && ((a === "높음" && b === "낮음") || (a === "낮음" && b === "높음")))
    .map(([a, b, an, bn]) => `${an}(${a}) vs ${bn}(${b})`);

  const AxisHead = ({ label, src, col }) => (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 12.5, fontWeight: 800, color: col || C.ink }}>{label}</div>
      <MonoCaps style={{ fontSize: 8.5 }} color={C.ink3}>{src}</MonoCaps>
    </div>
  );
  const colStyle = { flex: 1, minWidth: 0, padding: "16px 16px", borderRight: `1px solid ${C.line}` };

  const hasNote = history.length > 0 || note.attractiveness != null;

  return (
    <Panel title="매력도 — 3축 비교" sub="합산하지 않음 · 축 간 괴리를 그대로 표시 (확인편향 방지)"
      right={
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {saved && <MonoCaps style={{ fontSize: 9.5 }} color={C.ok}>✓ 저장됨</MonoCaps>}
          {saving && <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>저장 중…</MonoCaps>}
          {hasNote && !confirmDel && (
            <button onClick={() => setConfirmDel(true)}
              style={{ border: `1px solid ${C.line2}`, borderRadius: 6, padding: "3px 9px", fontSize: 11, color: C.ink3, background: "none", cursor: "pointer" }}>
              내 판단 삭제
            </button>
          )}
          {confirmDel && (
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <span style={{ fontSize: 11, color: C.bad }}>이력 포함 삭제?</span>
              <button onClick={deleteNote} disabled={deleting}
                style={{ border: "none", borderRadius: 6, padding: "3px 9px", fontSize: 11, color: "#fff", background: C.bad, cursor: "pointer", opacity: deleting ? 0.5 : 1 }}>
                {deleting ? "삭제 중…" : "삭제"}
              </button>
              <button onClick={() => setConfirmDel(false)}
                style={{ border: `1px solid ${C.line2}`, borderRadius: 6, padding: "3px 9px", fontSize: 11, color: C.ink2, background: "none", cursor: "pointer" }}>
                취소
              </button>
            </div>
          )}
        </div>
      }>
      <div style={{ display: "flex", flexWrap: "wrap" }}>
        {/* 축 1: 퀀트 */}
        <div style={colStyle}>
          <AxisHead label="퀀트" src="데이터 기반 · 종합" col={C.acc} />
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <Num size={30} weight={800} color={compColor(s.comp ?? 0)}>{s.comp ?? "—"}</Num>
            <span style={{ fontSize: 11, color: C.ink3 }}>/100</span>
            {qLevel && <span style={{ fontSize: 11, fontWeight: 700, color: qLevel === "높음" ? C.ok : qLevel === "낮음" ? C.bad : C.ink2 }}>{qLevel}</span>}
          </div>
          <div style={{ display: "flex", gap: 4, marginTop: 12, flexWrap: "wrap" }}>
            {[["모멘텀", s.f.m], ["가치", s.f.v], ["우량성", s.f.q], ["성장", s.f.g], ["심리", s.f.s]].map(([k, v]) => (
              <span key={k} style={{ fontSize: 10.5, color: C.ink2, background: C.surface2, border: `1px solid ${C.line}`, borderRadius: 5, padding: "3px 6px" }}>{k} <b style={{ color: C.ink }}>{v}</b></span>
            ))}
          </div>
          {/* 횡단면 신호(display_signals) — 퀀트 축 내부 상대 위치. 등급(결론)과 구분. */}
          {isCompleteSignal(s.signal) && (
            <div style={{ marginTop: 10, fontSize: 10.5, color: C.ink3, lineHeight: 1.5 }}>
              횡단면 위치 <b style={{ color: s.signal.label === "매수" ? C.ok : s.signal.label === "축소" ? C.bad : C.ink2 }}>{s.signal.label}</b>
              <span style={{ color: C.ink3 }}> · {s.signal.reason}</span>
            </div>
          )}
          {/* 신규-A1: 시장 민감도(베타·상관) — 별도 보조 지표, composite와 합산하지 않음 */}
          <div style={{ marginTop: 10, fontSize: 11, color: C.ink3, lineHeight: 1.5 }}>
            시장 민감도{" "}
            {s.beta != null
              ? <span style={{ color: C.ink2 }}>베타 <b style={{ color: C.ink }}>{s.beta}</b>{s.marketCorr != null && <> · 상관 <b style={{ color: C.ink }}>{s.marketCorr}</b></>} <span style={{ color: C.ink3 }}>({s.betaBenchmark || "자국 지수"}, 1년)</span></span>
              : <span style={{ color: C.ink3 }}>미산출(데이터 부족)</span>}
          </div>
          {/* Wave 5-B: 시장 점수 → 베타 경로 관찰(사실+영향, 매매 단정 아님). composite 미반영 */}
          {!!s.marketBetaNote && (
            <div style={{ marginTop: 6, fontSize: 10.5, color: C.ink3, lineHeight: 1.5, fontStyle: "italic" }}>{s.marketBetaNote}</div>
          )}
        </div>

        {/* 축 2: 컨센서스 */}
        <div style={colStyle}>
          <AxisHead label="컨센서스" src="전문가 목표가 기반" col={C.warn} />
          {hasCons ? (
            <>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <Num size={30} weight={800} color={ug ? ug.col : C.ink2}>{s.up != null ? `${s.up >= 0 ? "+" : ""}${s.up}%` : "—"}</Num>
                {ug && <span style={{ fontSize: 11, fontWeight: 700, color: ug.col }}>{ug.label}</span>}
              </div>
              <div style={{ height: 6, borderRadius: 3, background: C.line, marginTop: 10, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${Math.max(0, Math.min(100, ((s.up ?? 0) + 10) / 60 * 100))}%`, background: ug ? ug.col : C.ink3 }} />
              </div>
              <div style={{ marginTop: 12, fontSize: 11.5, color: C.ink2, lineHeight: 1.7 }}>
                {s.tp != null && <div>목표가 <b style={{ color: C.ink }}>{s.cur}{Math.round(s.tp).toLocaleString()}</b></div>}
                {s.rating && <div>투자의견 <b style={{ color: C.ink }}>{s.rating}</b></div>}
              </div>
            </>
          ) : (
            <div style={{ padding: "18px 0", color: C.ink3, fontSize: 12.5 }}>컨센서스 없음<div style={{ fontSize: 10.5, marginTop: 4 }}>애널리스트 목표가 데이터가 없습니다.</div></div>
          )}
        </div>

        {/* 축 3: 내 판단 (인라인 편집) */}
        <div style={{ ...colStyle, borderRight: "none" }}>
          <AxisHead label="내 판단" src="내 주관 · 직접 입력" col={C.ink} />
          {/* horizon */}
          <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
            {["short", "long", "watch"].map((h) => (
              <button key={h} onClick={() => setNote((current) => ({ ...current, horizon: current.horizon === h ? null : h }))}
                style={{ border: `1px solid ${note.horizon === h ? (h === "short" ? C.acc : h === "long" ? C.ok : C.ink3) : C.line2}`,
                  background: note.horizon === h ? (h === "short" ? C.accTint : h === "long" ? C.okBg : C.surface2) : C.surface,
                  color: note.horizon === h ? (h === "short" ? C.acc : h === "long" ? C.ok : C.ink3) : C.ink2,
                  borderRadius: 6, padding: "5px 10px", fontSize: 11.5, fontWeight: 600, cursor: "pointer" }}>
                {HORIZON_LABEL[h].replace(" 트레이딩", "").replace(" 보유", "")}
              </button>
            ))}
          </div>
          {/* attractiveness (별점) */}
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            {[1, 2, 3, 4, 5].map((n) => (
              <button key={n} onClick={() => setNote((current) => ({ ...current, attractiveness: current.attractiveness === n ? null : n }))}
                style={{ border: "none", background: "none", cursor: "pointer", padding: 0, fontSize: 22, lineHeight: 1, color: (note.attractiveness || 0) >= n ? "#F59E0B" : C.line2 }}>★</button>
            ))}
            <span style={{ fontSize: 11, color: C.ink3, marginLeft: 4 }}>{note.attractiveness != null ? `${note.attractiveness}/5` : "내 판단 미입력"}</span>
          </div>
          {/* thesis */}
          <textarea value={note.thesis || ""} onChange={(e) => setNote((n) => ({ ...n, thesis: e.target.value }))}
            placeholder="현재 판단과 근거를 여러 줄로 기록하세요…"
            style={{ width: "100%", minHeight: 110, marginTop: 10, border: `1px solid ${C.line2}`, borderRadius: 7, padding: "9px 10px", fontSize: 12.5, fontFamily: "var(--sans)", lineHeight: 1.55, color: C.ink, resize: "vertical", outline: "none", boxSizing: "border-box" }} />
          <button onClick={saveNote} disabled={saving || !(note.thesis || "").trim()}
            style={{ marginTop: 8, width: "100%", border: "none", borderRadius: 7, padding: "8px 10px", background: C.ink, color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer", opacity: saving || !(note.thesis || "").trim() ? 0.45 : 1 }}>
            {saving ? "저장 중…" : "판단 추가"}
          </button>
        </div>
      </div>

      {history.length > 0 && (
        <div style={{ borderTop: `1px solid ${C.line}`, padding: "12px 16px" }}>
          <MonoCaps style={{ fontSize: 9 }} color={C.ink3}>판단 이력 · 최신순</MonoCaps>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
            {history.map((item) => (
              <div key={item.id} style={{ padding: "9px 11px", border: `1px solid ${C.line}`, borderRadius: 7, background: C.surface2 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 5 }}>
                  <span style={{ fontSize: 10.5, fontWeight: 700, color: C.ink2 }}>{item.horizon ? HORIZON_LABEL[item.horizon] : "기간 미지정"}</span>
                  <span style={{ fontSize: 10.5, color: C.warn }}>{item.attractiveness ? `★ ${item.attractiveness}/5` : "별점 없음"}</span>
                  <span className="mono" style={{ marginLeft: "auto", fontSize: 9.5, color: C.ink3 }}>{new Date(item.created_at).toLocaleString("ko-KR")}</span>
                </div>
                <div style={{ whiteSpace: "pre-wrap", fontSize: 12, lineHeight: 1.55, color: C.ink }}>{item.thesis}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 축 간 괴리 코멘트 */}
      {diverge.length > 0 && (
        <div style={{ padding: "10px 16px", borderTop: `1px solid ${C.line}`, background: C.warnBg, display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13 }}>⚠️</span>
          <span style={{ fontSize: 12, color: C.warn, fontWeight: 600 }}>축이 엇갈립니다 — {diverge.join(" · ")}. 확인 필요(한 축만 보고 판단하지 마세요).</span>
        </div>
      )}
    </Panel>
  );
}

function ManualAiPerspectiveCard({ entry }) {
  const [showRaw, setShowRaw] = useState(false);
  if (!entry) {
    return (
      <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, background: C.surface2, padding: "12px 14px", fontSize: 12.5, color: C.ink3 }}>
        직접 입력한 외부 자료 분석 없음
      </div>
    );
  }
  return (
    <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, background: C.surface2, padding: "12px 14px" }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        <span style={{ fontSize: 10.5, fontWeight: 700, color: C.acc, background: C.accTint, border: `1px solid ${C.acc}33`, borderRadius: 999, padding: "3px 8px" }}>직접입력</span>
        {(entry.horizons || []).map((item) => (
          <span key={item.horizon} style={{ fontSize: 10.5, color: C.ink2, background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 999, padding: "3px 8px" }}>
            {item.horizon === "short" ? "단기" : item.horizon === "mid" ? "중기" : "장기"} · {item.attractivenessLabel}
          </span>
        ))}
      </div>
      <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <div style={{ border: `1px solid ${C.ok}22`, borderRadius: 7, padding: "9px 10px", background: C.ok + "0E", fontSize: 12, color: C.ink2 }}>
          강세 {(entry.bull || []).length}건
        </div>
        <div style={{ border: `1px solid ${C.bad}22`, borderRadius: 7, padding: "9px 10px", background: C.bad + "0E", fontSize: 12, color: C.ink2 }}>
          약세 {(entry.bear || []).length}건
        </div>
      </div>
      {(entry.horizons || []).length > 0 && (
        <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
          {entry.horizons.map((item) => (
            <div key={item.horizon} style={{ fontSize: 12, color: C.ink2, lineHeight: 1.55 }}>
              <b style={{ color: C.ink }}>{item.horizon === "short" ? "단기" : item.horizon === "mid" ? "중기" : "장기"}</b> · {cleanDisplayText(item.rationale)}
            </div>
          ))}
        </div>
      )}
      <div style={{ marginTop: 10 }}>
        <button onClick={() => setShowRaw((v) => !v)} style={{ ...btnGhost, fontSize: 11.5 }}>
          {showRaw ? "원문 숨기기" : "원문 보기"}
        </button>
      </div>
      {showRaw && (
        <div style={{ marginTop: 10, whiteSpace: "pre-wrap", fontSize: 12, lineHeight: 1.6, color: C.ink2, background: C.surface, border: `1px solid ${C.line}`, borderRadius: 8, padding: "10px 12px" }}>
          {entry.rawText}
        </div>
      )}
    </div>
  );
}

function AutoCollectionPerspectiveCard({ s }) {
  const bull = s.analystViews?.bull || [];
  const bear = s.analystViews?.bear || [];
  const insights = s.insightHistory || [];
  return (
    <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, background: C.surface2, padding: "12px 14px" }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        <span style={{ fontSize: 10.5, fontWeight: 700, color: C.ok, background: C.okBg, border: `1px solid ${C.ok}33`, borderRadius: 999, padding: "3px 8px" }}>자동수집</span>
        <span style={{ fontSize: 10.5, color: C.ink2 }}>강세 {bull.length} · 약세 {bear.length}</span>
        {s.consensus?.ratingLabel && <span style={{ fontSize: 10.5, color: C.ink2 }}>의견 {s.consensus.ratingLabel}</span>}
      </div>
      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
        {bull.slice(0, 2).map((item, idx) => (
          <div key={`bull-${idx}`} style={{ fontSize: 12, color: C.ink2, lineHeight: 1.55 }}>
            <b style={{ color: C.ok }}>강세</b> · {cleanDisplayText(item.point)}
          </div>
        ))}
        {bear.slice(0, 2).map((item, idx) => (
          <div key={`bear-${idx}`} style={{ fontSize: 12, color: C.ink2, lineHeight: 1.55 }}>
            <b style={{ color: C.bad }}>약세</b> · {cleanDisplayText(item.point)}
          </div>
        ))}
        {insights.slice(0, 2).map((item) => (
          <div key={item.id} style={{ fontSize: 12, color: C.ink2, lineHeight: 1.55 }}>
            <b style={{ color: C.ink }}>인사이트</b> · {cleanDisplayText(item.content)}
          </div>
        ))}
        {bull.length === 0 && bear.length === 0 && insights.length === 0 && (
          <div style={{ fontSize: 12.5, color: C.ink3 }}>자동 수집 근거 없음</div>
        )}
      </div>
    </div>
  );
}

function PerspectiveComparisonCard({ s, manualEntry }) {
  return (
    <Panel title="세 출처 비교" sub="합산하지 않음 · 관점의 일치와 괴리를 직접 읽기">
      <div style={{ padding: "14px 16px", display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 12 }}>
        <div>
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 12.5, fontWeight: 800, color: C.ink }}>내 판단</div>
            <MonoCaps style={{ fontSize: 8.5 }} color={C.ink3}>나 · 직접 입력</MonoCaps>
          </div>
          <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, background: C.surface2, padding: "12px 14px", minHeight: 140 }}>
            {s.note?.thesis ? (
              <>
                <div style={{ fontSize: 11.5, color: C.ink3 }}>
                  {s.note.horizon ? HORIZON_LABEL[s.note.horizon] : "기간 미지정"} · {s.note.attractiveness != null ? `★ ${s.note.attractiveness}/5` : "별점 없음"}
                </div>
                <div style={{ marginTop: 8, whiteSpace: "pre-wrap", fontSize: 12, lineHeight: 1.6, color: C.ink2 }}>{s.note.thesis}</div>
              </>
            ) : (
              <div style={{ fontSize: 12.5, color: C.ink3 }}>직접 입력한 판단 없음</div>
            )}
          </div>
        </div>
        <div>
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 12.5, fontWeight: 800, color: C.acc }}>AI 분해 분석</div>
            <MonoCaps style={{ fontSize: 8.5 }} color={C.ink3}>외부 자료 · 구조화</MonoCaps>
          </div>
          <ManualAiPerspectiveCard entry={manualEntry} />
        </div>
        <div>
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 12.5, fontWeight: 800, color: C.ok }}>자동 수집 근거</div>
            <MonoCaps style={{ fontSize: 8.5 }} color={C.ink3}>뉴스 · 컨센서스</MonoCaps>
          </div>
          <AutoCollectionPerspectiveCard s={s} />
        </div>
      </div>
    </Panel>
  );
}

const HOLD_CHARACTER_TONE = { "장기보유": "acc", "모멘텀": "ok", "단기": "warn", "정보부족": "ink3" };

function ActionAdviceCard({ advice, history = [] }) {
  const [showHistory, setShowHistory] = useState(false);
  const character = advice?.holdCharacter || "정보부족";
  const tone = C[HOLD_CHARACTER_TONE[character] || "ink3"];

  return (
    <Panel
      title="등급 · 종목 성격 · 액션"
      sub="3축 종합 등급(결론) + 보유성격 + 관찰 · 표시 전용(비중 강요 아님)"
      right={<button onClick={() => setShowHistory((v) => !v)} style={{ ...btnGhost, fontSize: 11.5 }}>{showHistory ? "이력 접기 −" : "과거 제언 +"}</button>}
    >
      {!advice ? (
        <div style={{ padding: "24px 18px", fontSize: 12.5, color: C.ink3 }}>최신 종목 성격 판단이 없습니다.</div>
      ) : (
        <div style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 12 }}>
          {/* 신규-A2: 등급 = 상위 결론(헤드라인). 3축 정렬 근거 + 신뢰도. */}
          {advice.grade && (
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", paddingBottom: 10, borderBottom: `1px solid ${C.line}` }}>
              <span style={{ fontSize: 9.5, fontWeight: 700, color: C.ink3, letterSpacing: ".04em" }}>등급</span>
              <GradeBadge grade={advice.grade} confidence={advice.gradeConfidence} />
              {gradeAxisSummary(advice.gradeBasis) && <span style={{ fontSize: 11.5, color: C.ink2 }}>3축 정렬: {gradeAxisSummary(advice.gradeBasis)}</span>}
              <span style={{ fontSize: 10, color: C.ink3 }}>합산 아님 · 매매 신호일 뿐 자동 집행 아님</span>
            </div>
          )}
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 9.5, fontWeight: 700, color: C.ink3, letterSpacing: ".04em" }}>보유성격</span>
            <span style={{ fontSize: 12.5, fontWeight: 800, color: tone, background: tone + "14", border: `1px solid ${tone}33`, borderRadius: 999, padding: "5px 10px" }}>{character}</span>
            {(advice.holdCharacterSecondary || []).map((t) => (
              <span key={t} style={{ fontSize: 10.5, fontWeight: 600, color: C.ink2, background: C.surface2, border: `1px solid ${C.line2}`, borderRadius: 999, padding: "3px 8px" }}>+{t}</span>
            ))}
            <span style={{ fontSize: 11.5, color: C.ink2, marginLeft: 4 }}>신뢰도 {advice.confidence}</span>
            <span className="mono" style={{ fontSize: 10.5, color: C.ink3 }}>{advice.asof}</span>
          </div>
          {(advice.holdCharacterBasis || []).length > 0 && (
            <div style={{ fontSize: 11.5, color: C.ink3, lineHeight: 1.5 }}>
              {advice.holdCharacterBasis.map((b) => `${b.source} ${b.value}`).join(" · ")}
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, background: C.surface2, padding: "10px 12px" }}>
              <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>진입 구간</MonoCaps>
              <div style={{ marginTop: 6, fontSize: 12.5, color: C.ink2, lineHeight: 1.55 }}>{advice.entryZone || "근거 부족으로 미제시"}</div>
            </div>
            <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, background: C.surface2, padding: "10px 12px" }}>
              <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>이탈 구간</MonoCaps>
              <div style={{ marginTop: 6, fontSize: 12.5, color: C.ink2, lineHeight: 1.55 }}>{advice.exitZone || "근거 부족으로 미제시"}</div>
            </div>
          </div>
          <div style={{ fontSize: 12.5, color: C.ink2, lineHeight: 1.65 }}>{cleanDisplayText(advice.rationale || "")}</div>
          {!!advice.divergenceNote && (
            <div style={{ border: `1px solid ${C.warn}33`, background: C.warnBg, borderRadius: 8, padding: "10px 12px", fontSize: 12, color: C.warn, lineHeight: 1.55 }}>
              {cleanDisplayText(advice.divergenceNote)}
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div style={{ border: `1px solid ${C.ok}22`, borderRadius: 8, background: C.ok + "0E", padding: "10px 12px" }}>
              <MonoCaps style={{ fontSize: 9.5 }} color={C.ok}>지지 재료</MonoCaps>
              <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
                {(advice.supportingFactors || []).length ? advice.supportingFactors.map((item, idx) => (
                  <div key={`support-${idx}`} style={{ fontSize: 12, color: C.ink2, lineHeight: 1.5 }}>
                    <b style={{ color: C.ink }}>{item.source}</b> · {cleanDisplayText(item.value || "")}
                  </div>
                )) : <div style={{ fontSize: 12, color: C.ink3 }}>지지 재료 없음</div>}
              </div>
            </div>
            <div style={{ border: `1px solid ${C.bad}22`, borderRadius: 8, background: C.bad + "0E", padding: "10px 12px" }}>
              <MonoCaps style={{ fontSize: 9.5 }} color={C.bad}>반대 재료</MonoCaps>
              <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
                {(advice.opposingFactors || []).length ? advice.opposingFactors.map((item, idx) => (
                  <div key={`oppose-${idx}`} style={{ fontSize: 12, color: C.ink2, lineHeight: 1.5 }}>
                    <b style={{ color: C.ink }}>{item.source}</b> · {cleanDisplayText(item.value || "")}
                  </div>
                )) : <div style={{ fontSize: 12, color: C.ink3 }}>반대 재료 없음</div>}
              </div>
            </div>
          </div>
          {!!advice.concentrationNote && (
            <div style={{ border: `1px solid ${C.line2}`, background: C.surface2, borderRadius: 8, padding: "10px 12px" }}>
              <MonoCaps style={{ fontSize: 9 }} color={C.ink3}>관찰 · 집중 리스크</MonoCaps>
              <div style={{ marginTop: 6, fontSize: 12, color: C.ink2, lineHeight: 1.6 }}>{cleanDisplayText(advice.concentrationNote)}</div>
            </div>
          )}
        </div>
      )}

      {showHistory && (
        <div style={{ borderTop: `1px solid ${C.line}`, padding: "12px 16px", display: "flex", flexDirection: "column", gap: 8 }}>
          {(history || []).length ? history.map((item, idx) => (
            <div key={`${item.asof}-${idx}`} style={{ border: `1px solid ${C.line}`, borderRadius: 8, background: C.surface2, padding: "10px 12px" }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                {item.grade && <GradeBadge grade={item.grade} confidence={item.gradeConfidence} compact />}
                <span style={{ fontSize: 11, color: C.ink2 }}>{item.holdCharacter || item.direction}</span>
                <span className="mono" style={{ marginLeft: "auto", fontSize: 10, color: C.ink3 }}>{item.asof}</span>
              </div>
            </div>
          )) : (
            <div style={{ fontSize: 12, color: C.ink3 }}>과거 제언 이력이 없습니다.</div>
          )}
        </div>
      )}
    </Panel>
  );
}

// E-1: 트레이딩 관점 카드 (투자 등급과 별도 레이어 — 덮어쓰지 않음)
function TradingSignalCard({ s }) {
  const ts = s?.tradingSignal;
  const ti = s?.tradingIndicators;
  if (!ts || (!ts.label && !ti)) return null;

  const label = ts?.label || "중립";
  const basis = ts?.basis || [];
  const volNote = ts?.volNote;

  const labelColor = label === "단기매수우호" ? C.ok : label === "단기회피" ? C.bad : C.ink2;
  const labelBg    = label === "단기매수우호" ? C.okBg : label === "단기회피" ? C.badBg : C.surface2;

  const rows = [
    ti?.macdHist != null && { name: "MACD 히스토그램", val: ti.macdHist.toFixed(3), note: ti.macdHist > 0 ? "양(0선 위)" : "음(0선 아래)" },
    ti?.bbPct    != null && { name: "볼린저 %B",        val: ti.bbPct.toFixed(2),    note: ti.bbPct < 0.2 ? "하단 접근" : ti.bbPct > 0.8 ? "상단 접근" : "중단" },
    ti?.stochK   != null && { name: "스토캐스틱 %K",   val: ti.stochK.toFixed(1),   note: ti.stochK < 20 ? "과매도" : ti.stochK > 80 ? "과매수" : "" },
    ti?.volRatio20 != null && { name: "거래량 비율",    val: ti.volRatio20.toFixed(2) + "x", note: ti.volRatio20 >= 2 ? "급증" : "" },
    ti?.atr14    != null && { name: "ATR(14)",          val: ti.atr14.toFixed(2),    note: "일변동폭 기준" },
  ].filter(Boolean);

  return (
    <Panel
      title="트레이딩 관점"
      sub="단기 기술적 신호 · 투자 등급과 독립 레이어"
    >
      {/* 신호 레이블 */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
        <div style={{
          padding: "6px 14px", borderRadius: 8, fontSize: 14, fontWeight: 700,
          background: labelBg, color: labelColor, border: `1px solid ${labelColor}44`,
        }}>
          {label}
        </div>
        {basis.length > 0 && (
          <div style={{ fontSize: 11.5, color: C.ink2 }}>
            {basis.map((b, i) => (
              <span key={i}>{i > 0 && " · "}<b>{b.source}</b> {b.value}</span>
            ))}
          </div>
        )}
      </div>

      {/* 투자 등급 divergence 힌트 */}
      {s?.actionAdviceLatest?.grade && label !== "중립" && (
        (() => {
          const grade = s.actionAdviceLatest.grade;
          const conflict = (grade === "매수" && label === "단기회피") || (grade === "축소" && label === "단기매수우호");
          if (!conflict) return null;
          return (
            <div style={{ fontSize: 11.5, color: C.ink2, background: C.surface2, borderRadius: 6, padding: "8px 12px", marginBottom: 12 }}>
              투자 등급 <b>{grade}</b> ↔ 트레이딩 <b>{label}</b> 충돌 — 단기 타이밍과 펀더멘털 방향이 다릅니다. 양쪽 근거를 직접 확인하세요.
            </div>
          );
        })()
      )}

      {volNote && (
        <div style={{ fontSize: 11.5, color: C.acc, marginBottom: 10 }}>{volNote}</div>
      )}

      {/* 지표 테이블 */}
      {rows.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 8 }}>
          {rows.map((r) => (
            <div key={r.name} style={{ background: C.surface2, borderRadius: 6, padding: "8px 12px" }}>
              <MonoCaps style={{ fontSize: 9.5 }}>{r.name}</MonoCaps>
              <div style={{ fontSize: 13, fontWeight: 600, marginTop: 4 }}>{r.val}</div>
              {r.note && <div style={{ fontSize: 10.5, color: C.ink2, marginTop: 2 }}>{r.note}</div>}
            </div>
          ))}
        </div>
      )}

      <div style={{ fontSize: 10.5, color: C.ink3, marginTop: 12 }}>
        §F7 참고: 기술적 지표는 과거 가격 기반이며 자기실현·과최적화 위험이 있습니다. 단정 금지 — 투자 판단은 3축 등급과 함께 종합적으로 판단하세요.
      </div>
    </Panel>
  );
}


// E-2: 투자자 수급 신호 카드 (KR 전용, 기술신호와 독립 레이어)
function InvestorFlowCard({ s }) {
  // US 종목 또는 수급 데이터 없음 → 명시적 처리
  if (s?.mk !== "KR") {
    return (
      <Panel title="투자자 수급" sub="KR 전용 · E-2">
        <div style={{ fontSize: 12, color: C.ink2 }}>
          수급 데이터 없음 — KR 종목 전용 (미국 주식은 KRX 수급 구조 부재)
        </div>
      </Panel>
    );
  }

  const flow = s?.investorFlow;
  if (!flow) {
    return (
      <Panel title="투자자 수급" sub="KR 전용 · E-2">
        <div style={{ fontSize: 12, color: C.ink2 }}>
          수급 데이터 수집 중 — 다음 업데이트 후 표시됩니다.
        </div>
      </Panel>
    );
  }

  const combined = flow.combinedSignal || "중립";
  const foreign  = flow.foreignSignal  || "중립";
  const instit   = flow.institutionSignal || "중립";

  const combColor = combined === "수급_강세" ? C.ok
    : combined === "수급_약세" ? C.bad
    : combined === "수급_혼조" ? C.acc
    : C.ink2;
  const combBg = combined === "수급_강세" ? C.okBg
    : combined === "수급_약세" ? C.badBg
    : combined === "수급_혼조" ? "#FFF3E0"
    : C.surface2;

  // 억원 단위 포맷 (소수점 1자리)
  const fmt억 = (v) => {
    if (v == null) return "—";
    const 억 = v / 1e8;
    return (억 >= 0 ? "+" : "") + 억.toFixed(1) + "억";
  };

  const sigColor = (sig) =>
    sig === "매수우호" ? C.ok : sig === "매도우세" ? C.bad : C.ink2;

  // E-1↔E-2 divergence: 기술신호와 수급신호 충돌 감지
  const techLabel = s?.tradingSignal?.label;
  const diverge =
    (techLabel === "단기매수우호" && combined === "수급_약세") ||
    (techLabel === "단기회피"   && combined === "수급_강세");

  return (
    <Panel title="투자자 수급" sub="최근 3거래일 외국인·기관 순매수 · KR 전용">
      {/* 복합 수급 라벨 */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
        <div style={{
          padding: "6px 14px", borderRadius: 8, fontSize: 14, fontWeight: 700,
          background: combBg, color: combColor, border: `1px solid ${combColor}44`,
        }}>
          {combined}
        </div>
        <div style={{ fontSize: 11.5, color: C.ink2 }}>
          외국인 <b style={{ color: sigColor(foreign) }}>{foreign}</b>
          {" · "}
          기관 <b style={{ color: sigColor(instit) }}>{instit}</b>
        </div>
      </div>

      {/* E-1↔E-2 divergence 경고 */}
      {diverge && (
        <div style={{
          fontSize: 11.5, color: C.ink2, background: C.surface2,
          borderRadius: 6, padding: "8px 12px", marginBottom: 12,
        }}>
          기술신호 <b>{techLabel}</b> ↔ 수급신호 <b>{combined}</b> 충돌 — 방향이 엇갈립니다. 양쪽 근거를 직접 확인하세요.
        </div>
      )}

      {/* 3일 순매수 수치 */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginBottom: 10 }}>
        {[
          { label: "외국인 3일 합계", val: fmt억(flow.foreignNet3d), sig: foreign },
          { label: "기관 3일 합계",   val: fmt억(flow.institutionNet3d), sig: instit },
          { label: "기준일", val: flow.asof || "—", sig: null },
        ].map((item) => (
          <div key={item.label} style={{ background: C.surface2, borderRadius: 6, padding: "8px 12px" }}>
            <MonoCaps style={{ fontSize: 9.5 }}>{item.label}</MonoCaps>
            <div style={{
              fontSize: 13, fontWeight: 600, marginTop: 4,
              color: item.sig ? sigColor(item.sig) : C.ink,
            }}>
              {item.val}
            </div>
          </div>
        ))}
      </div>

      <div style={{ fontSize: 10.5, color: C.ink3 }}>
        §F7: 수급 데이터는 T+0 과거 기준이며 미래 방향을 보장하지 않습니다. 투자 자문 아님 / 원금 손실 가능.
      </div>
    </Panel>
  );
}

export function InsightHistoryCard({ items }) {
  const [typeFilter, setTypeFilter] = useState("all");
  const types = useMemo(() => {
    const seen = new Map();
    for (const item of items || []) {
      if (!seen.has(item.type)) seen.set(item.type, item.typeLabel || item.type);
    }
    return Array.from(seen.entries());
  }, [items]);

  const filtered = useMemo(() => {
    const base = items || [];
    if (typeFilter === "all") return base;
    return base.filter((item) => item.type === typeFilter);
  }, [items, typeFilter]);

  return (
    <Panel
      title="누적 인사이트"
      sub="최근 30일 · 최신순"
      right={(
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
          <button
            onClick={() => setTypeFilter("all")}
            style={{
              border: `1px solid ${typeFilter === "all" ? C.acc : C.line2}`,
              background: typeFilter === "all" ? C.accTint : C.surface,
              color: typeFilter === "all" ? C.acc : C.ink2,
              borderRadius: 999,
              padding: "4px 10px",
              fontSize: 11,
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            전체
          </button>
          {types.map(([type, label]) => (
            <button
              key={type}
              onClick={() => setTypeFilter(type)}
              style={{
                border: `1px solid ${typeFilter === type ? C.acc : C.line2}`,
                background: typeFilter === type ? C.accTint : C.surface,
                color: typeFilter === type ? C.acc : C.ink2,
                borderRadius: 999,
                padding: "4px 10px",
                fontSize: 11,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              {label}
            </button>
          ))}
        </div>
      )}
    >
      {filtered.length === 0 ? (
        <div style={{ padding: "24px 18px", color: C.ink3, fontSize: 12.5 }}>
          최근 30일 누적 인사이트가 없습니다.
        </div>
      ) : (
        <div style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
          {filtered.map((item) => (
            <div key={item.id} style={{ border: `1px solid ${C.line}`, borderRadius: 8, background: C.surface2, padding: "10px 12px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
                <span style={{ fontSize: 10.5, fontWeight: 700, color: C.acc, background: C.accTint, borderRadius: 999, padding: "3px 8px" }}>
                  {item.typeLabel || item.type}
                </span>
                <span className="mono" style={{ fontSize: 10, color: C.ink3 }}>{item.validFrom}</span>
                {item.source && <span style={{ fontSize: 10.5, color: C.ink3 }}>{item.source}</span>}
              </div>
              <div style={{ whiteSpace: "pre-wrap", fontSize: 12.5, color: C.ink, lineHeight: 1.6 }}>{item.content}</div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

// PR-2: 중요 뉴스 방향 색상 (호재 초록 / 악재 빨강 / 중립 회색)
export const dirColor = (d) => d === "호재" ? C.ok : d === "악재" ? C.bad : C.ink3;

// PR-2: 종목상세 중요 뉴스 카드
export function CuratedNews({ items }) {
  const list = items || [];
  return (
    <Panel title="중요 뉴스" sub="Gemini 큐레이션 · 영향도순"
      right={<MonoCaps style={{ fontSize: 9 }} color={C.ink3}>영향도순</MonoCaps>}>
      {list.length === 0 ? (
        <div style={{ padding: "22px 18px", textAlign: "center", color: C.ink3, fontSize: 12.5 }}>
          주목할 만한 중요 뉴스가 없습니다.
        </div>
      ) : (
        <div>
          {list.map((c, i) => {
            const col = dirColor(c.direction);
            return (
              <div key={i} style={{ padding: "12px 16px", borderBottom: i < list.length - 1 ? `1px solid ${C.line}` : "none", borderLeft: `3px solid ${col}` }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 4, background: col + "18", color: col, border: `1px solid ${col}33` }}>{c.direction}</span>
                  <span style={{ fontSize: 10.5, fontWeight: 600, color: C.ink2, background: C.surface2, border: `1px solid ${C.line}`, borderRadius: 4, padding: "2px 7px" }}>{c.category}</span>
                  <span className="mono" style={{ fontSize: 10.5, fontWeight: 700, color: col }}>영향도 {c.impact_score}</span>
                  <span className="mono" style={{ fontSize: 9.5, color: C.ink3, marginLeft: "auto" }}>{c.source} · {c.published_at}</span>
                </div>
                {c.url ? (
                  <a href={c.url} target="_blank" rel="noopener noreferrer" style={{ display: "block", fontSize: 13, fontWeight: 700, color: C.ink, textDecoration: "none", marginTop: 6 }}>{c.title} ↗</a>
                ) : (
                  <div style={{ fontSize: 13, fontWeight: 700, color: C.ink, marginTop: 6 }}>{c.title}</div>
                )}
                {c.insight && <div style={{ fontSize: 12, color: C.ink2, lineHeight: 1.55, marginTop: 4 }}>{c.insight}</div>}
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}

export function StockDetail({ D, ticker, nav }) {
  const [stockQuery, setStockQuery] = useState("");
  const [marketFilter, setMarketFilter] = useState("all");
  const [sectorFilter, setSectorFilter] = useState("all");
  const [manualEntry, setManualEntry] = useState(null);
  const sorted = useMemo(() => [...D.stocks].sort((a, b) => (b.comp ?? 0) - (a.comp ?? 0)), [D.stocks]);
  const s = D.stocks.find((x) => x.t === ticker) || D.stocks[0];
  const sectors = useMemo(
    () => [...new Set(D.stocks.map((stock) => stock.sec).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ko")),
    [D.stocks],
  );
  const filteredStocks = useMemo(
    () => filterStocks(sorted, { query: stockQuery, market: marketFilter, sector: sectorFilter }),
    [sorted, stockQuery, marketFilter, sectorFilter],
  );

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

  useEffect(() => {
    let active = true;
    setManualEntry(s.manualResearchLatest || null);
    fetch(`${API}/api/manual-research/${s.t}`)
      .then((response) => response.ok ? response.json() : null)
      .then((payload) => {
        if (!active || !payload) return;
        setManualEntry(payload.latest || null);
      })
      .catch(() => {});
    return () => { active = false; };
  }, [s.t, s.manualResearchLatest]);

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
  const fb = s.factorFallback || {};  // PR-6: 팩터별 중립폴백 여부

  // PR-6: 데이터 없는 종목 — 빈 박스 대신 명확한 empty state
  if (s.hasData === false) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10, padding: "18px 22px", display: "flex", alignItems: "center", gap: 14 }}>
          <button onClick={() => nav(null, "overview")} style={{ ...btnGhost, fontSize: 18, color: C.ink3 }}>←</button>
          <div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
              <span style={{ fontSize: 24, fontWeight: 800, color: C.ink }}>{s.name}</span>
              <span className="mono" style={{ fontSize: 13, color: C.ink3 }}>{s.t} · {s.mk}</span>
            </div>
          </div>
        </div>
        <div style={{ background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10, padding: "56px 24px", textAlign: "center" }}>
          <div style={{ fontSize: 30, marginBottom: 12 }}>⏳</div>
          <div style={{ fontSize: 15, fontWeight: 700, color: C.ink, marginBottom: 6 }}>데이터 수집 중입니다</div>
          <div style={{ fontSize: 12.5, color: C.ink3, lineHeight: 1.6 }}>
            최근 추가된 종목이라 가격·지표·재무가 아직 준비되지 않았습니다.<br />다음 갱신 후 다시 확인해 주세요.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", padding: "10px 12px", background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10 }}>
        <input value={stockQuery} onChange={(event) => setStockQuery(event.target.value)} placeholder="티커·종목명 검색"
          style={{ minWidth: 220, flex: 1, border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", fontSize: 12.5, color: C.ink, outline: "none" }} />
        <select value={marketFilter} onChange={(event) => setMarketFilter(event.target.value)}
          style={{ border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", background: C.surface, color: C.ink }}>
          <option value="all">전체 시장</option><option value="KR">한국</option><option value="US">미국</option>
        </select>
        <select value={sectorFilter} onChange={(event) => setSectorFilter(event.target.value)}
          style={{ border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", background: C.surface, color: C.ink }}>
          <option value="all">전체 섹터</option>{sectors.map((sector) => <option key={sector} value={sector}>{sector}</option>)}
        </select>
        <select value="" onChange={(event) => event.target.value && nav(event.target.value)} disabled={filteredStocks.length === 0}
          style={{ minWidth: 190, border: `1px solid ${C.line2}`, borderRadius: 7, padding: "8px 10px", background: C.surface, color: C.ink }}>
          <option value="">{filteredStocks.length ? `${filteredStocks.length}개 결과에서 선택` : "검색 결과 없음"}</option>
          {filteredStocks.map((stock) => <option key={stock.t} value={stock.t}>{stock.name} · {stock.t}</option>)}
        </select>
      </div>
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
              {s.move && (
                <span title={s.move.reason || ""}>
                  <Pill tone={s.move.class === "이유 불명" ? "warn" : (s.move.direction === "급등" ? "ok" : "bad")} active>
                    {s.move.direction === "급등" ? "▲" : "▼"} {s.move.ret > 0 ? "+" : ""}{s.move.ret}% · {s.move.class}
                  </Pill>
                </span>
              )}
            </div>
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <Num size={32} weight={800}>{fmtPrice(s)}</Num>
          <div style={{ marginTop: 3 }}><ChangePct v={s.chg} size={16} /></div>
        </div>
      </div>

      {/* 신규-A2: 매력도 3축 종합 등급 — 상위 결론(횡단면 신호는 퀀트 축 안으로 이동) */}
      {(() => {
        const aa = s.actionAdviceLatest;
        const grade = aa?.grade || s.grade;
        if (!grade) return <SignalCard signal={s.signal} />;
        const tone = grade === "매수" ? C.ok : grade === "축소" ? C.bad : C.ink2;
        const summary = gradeAxisSummary(aa?.gradeBasis);
        return (
          <div style={{ padding: "10px 12px", border: `1px solid ${tone}33`, borderRadius: 8, background: grade === "매수" ? C.okBg : grade === "축소" ? C.badBg : C.surface2 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <GradeBadge grade={grade} confidence={aa?.gradeConfidence || s.gradeConfidence} />
              <span style={{ fontSize: 10.5, color: C.ink3 }}>3축 종합 결론 · 합산 아님</span>
            </div>
            {summary && <div style={{ marginTop: 6, fontSize: 11.5, color: C.ink2 }}>3축 정렬: {summary}</div>}
          </div>
        );
      })()}

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
                <span style={{ color: sentMeta(s.sent).c, fontWeight: 800, flexShrink: 0 }}>—</span><span>{cleanDisplayText(b)}</span>
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
              <MonoCaps style={{ fontSize: 9 }}>종합</MonoCaps>
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
            {factors.filter(([k]) => D.factorMeta[k].group === "timing").map(([k, v]) => <FactorBar key={k} label={D.factorMeta[k].ko} value={v} group="timing" fallback={fb[k]} />)}
            <div style={{ height: 1, background: C.line, margin: "8px 0" }}></div>
            <MonoCaps style={{ fontSize: 9 }}>미스프라이싱 그룹 — 장기 보유 판단</MonoCaps>
            {factors.filter(([k]) => D.factorMeta[k].group === "mispricing").map(([k, v]) => <FactorBar key={k} label={D.factorMeta[k].ko} value={v} group="mispricing" fallback={fb[k]} />)}
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

      {/* PR-1+3: 매력도 3축 카드 (퀀트·컨센서스·내 판단 나란히, 단일점수 금지) */}
      <AxesCard s={s} />

      <PerspectiveComparisonCard s={s} manualEntry={manualEntry} />

      <ActionAdviceCard advice={s.actionAdviceLatest} history={s.actionAdviceHistory || []} />

      {/* E-1: 트레이딩 관점 (투자 등급과 별도 레이어) */}
      <TradingSignalCard s={s} />

      {/* E-2: 투자자 수급 신호 (KR 전용, E-1과 독립 레이어) */}
      <InvestorFlowCard s={s} />

      {/* PR-2: 재무 추이 (매출·영업이익·순이익·OCF·FCF + 추세 + 컨센서스) */}
      <FinancialsCard s={s} />

      <StockDriversSection s={s} />

      {/* PR-2: 리서치 (전문가 보고서·내 조사자료, 종목상세 통합 + 빠른추가) */}
      <StockResearchSection s={s} />

      {/* PR-2: 내 보유 정보 카드 (is_holding=true 종목만) */}
      {s.holding && (
        <Panel title="내 보유 정보" sub="보유 수량·평가 손익">
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
        <Panel title="주요 동인과 뉴스" sub="Gemini 심리 분석" right={<SentBadge label={s.sent} score={s.sscore} />}>
          <div style={{ padding: "14px 18px" }}>
            {(s.cat || []).length > 0 ? (
              <>
                <MonoCaps style={{ fontSize: 9 }}>주요 동인</MonoCaps>
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
              <span style={{ fontSize: 12.5, color: C.ink3 }}>주요 동인 정보 없음</span>
            )}
          </div>
        </Panel>

        <Panel title="점수 히스토리" sub="최근 16주 추이">
          <div style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 16 }}>
            {[["종합", s.compHist, C.acc, s.comp], ["모멘텀", s.momHist, C.ok, s.f.m]].filter(([, data]) => data).map(([lbl, data, col, cur]) => {
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

      {/* 중요 뉴스 큐레이션 (Gemini 2단계: 영향도 스코어링 → 인사이트) */}
      <CuratedNews items={s.curatedNews} />

      {/* Wave 2-C: 누적 인사이트 */}
      <InsightHistoryCard items={s.insightHistory || []} />

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
  const [sortMode, setSortMode] = useState("recent");  // PR-2: recent | impact(중요도순)

  // PR-2: 중요도순 피드(큐레이션) — 종목/시장 필터 적용
  const curatedView = useMemo(() => {
    let f = [...(D.curatedFeed || [])];
    if (filterTicker) f = f.filter((n) => n.t === filterTicker);
    if (mkt !== "all") f = f.filter((n) => { const st = D.stocks.find((s) => s.t === n.t); return mkt === "hold" ? st && st.hold : st && st.mk === mkt; });
    if (q) f = f.filter((n) => { const st = D.stocks.find((s) => s.t === n.t); return (st && st.name.includes(q)) || n.t.includes(q) || (n.title || "").includes(q); });
    return f;
  }, [filterTicker, mkt, q, D]);

  const sentCounts = useMemo(() => {
    return D.stocks.map((s) => {
      const seed = s.t.length + (s.comp ?? 50);
      const pos = s.sent === "긍정" ? 5 + (seed % 3) : s.sent === "중립" ? 2 + (seed % 2) : 1;
      const neg = s.sent === "부정" ? 5 + (seed % 3) : s.sent === "중립" ? 2 : 1;
      const neu = 2 + (seed % 3);
      return { s, pos, neu, neg, total: pos + neu + neg };
    });
    return sortStocksBySentiment(rows);
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
          <FilterTabs value={sortMode} onChange={setSortMode} options={[{ k: "recent", label: "최신순" }, { k: "impact", label: "중요도순" }]} />
          {sortMode === "recent" && <FilterTabs value={sent} onChange={setSent} options={[{ k: "all", label: "전체" }, { k: "긍정", label: "긍정" }, { k: "중립", label: "중립" }, { k: "부정", label: "부정" }]} />}
        </div>
        {/* PR-2: 중요도순 = 큐레이션 피드 */}
        {sortMode === "impact" ? (
          <div style={{ maxHeight: 620, overflowY: "auto" }}>
            {curatedView.length === 0 ? (
              <div style={{ padding: "30px 18px", textAlign: "center", color: C.ink3, fontSize: 12.5 }}>중요 뉴스가 아직 없습니다.</div>
            ) : curatedView.map((c, i) => {
              const st = D.stocks.find((s) => s.t === c.t);
              const col = dirColor(c.direction);
              return (
                <div key={i} style={{ padding: "13px 16px", borderBottom: `1px solid ${C.line}`, borderLeft: `3px solid ${col}` }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
                    <button onClick={() => nav(c.t)} className="chip-hover" style={{ border: `1px solid ${C.line2}`, background: C.surface, borderRadius: 999, padding: "2px 9px", fontSize: 11, fontWeight: 700, color: C.ink, cursor: "pointer", display: "flex", gap: 5, alignItems: "center" }}>
                      <HoldDot on={st && st.hold} />{st ? st.name : c.t}
                    </button>
                    <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 4, background: col + "18", color: col, border: `1px solid ${col}33` }}>{c.direction}</span>
                    <span style={{ fontSize: 10.5, fontWeight: 600, color: C.ink2, background: C.surface2, border: `1px solid ${C.line}`, borderRadius: 4, padding: "2px 7px" }}>{c.category}</span>
                    <span className="mono" style={{ fontSize: 10.5, fontWeight: 700, color: col }}>영향도 {c.impact_score}</span>
                    <span className="mono" style={{ fontSize: 9.5, color: C.ink3, marginLeft: "auto" }}>{c.source} · {c.published_at}</span>
                  </div>
                  {c.url ? (
                    <a href={c.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 14, fontWeight: 700, color: C.ink, textDecoration: "none", display: "block", lineHeight: 1.4 }}>{c.title} <span style={{ fontSize: 11, color: C.acc }}>↗</span></a>
                  ) : (
                    <div style={{ fontSize: 14, fontWeight: 700, color: C.ink, lineHeight: 1.4 }}>{c.title}</div>
                  )}
                  {c.insight && <div style={{ fontSize: 12.5, color: C.ink2, lineHeight: 1.55, marginTop: 5 }}>{c.insight}</div>}
                </div>
              );
            })}
          </div>
        ) : (
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
        )}
      </Panel>

      <Panel title="종목별 심리" sub="최근 7일 · 클릭 시 필터">
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
