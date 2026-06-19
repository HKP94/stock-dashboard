// ATLAS — App shell + router
import { useState } from 'react';
import atlasData from './data.js';
import { C, MonoCaps, Num, RegimeBadge } from './ui.jsx';
import { Overview, StockDetail, NewsTab } from './tabsA.jsx';
import { Screener, Market, Research } from './tabsB.jsx';
import { Portfolio } from './tabsC.jsx';
import { Strategy } from './tabsD.jsx';
import { WatchlistAdmin } from './tabsE.jsx';

const D = atlasData;

export default function App() {
  const [tab, setTab] = useState("overview");
  const [ticker, setTicker] = useState(D.stocks[0].t);
  const [newsFilter, setNewsFilter] = useState(null);

  const nav = (tk, t) => {
    if (tk) { setTicker(tk); setTab(t || "detail"); }
    else if (t) { setTab(t); }
    window.scrollTo({ top: 0, behavior: "instant" });
  };
  const goNews = (tk) => { if (tk) { setNewsFilter(tk); setTicker(tk); } setTab("news"); window.scrollTo({ top: 0 }); };
  // PR-3: 종목 컨텍스트 연속성 — 뉴스에서 종목을 고르면 전역 selectedTicker(ticker)도 갱신,
  //       이후 '종목 상세' 탭으로 가도 그 종목이 유지된다.
  const selectNewsTicker = (tk) => { setNewsFilter(tk); if (tk) setTicker(tk); };

  const tabs = [
    { k: "overview", label: "오버뷰" },
    { k: "detail", label: "종목 상세" },
    { k: "news", label: "뉴스" },
    { k: "screener", label: "스크리너" },
    { k: "market", label: "시장 전망" },
    { k: "research", label: "리서치 노트" },
    { k: "portfolio", label: "포트폴리오" },
    { k: "strategy", label: "전략 비교" },
    { k: "manage", label: "관심종목 관리" },
  ];

  const overall = D.market.overall;
  const w = D.regimes[overall].w;

  // PR-3: 데이터 신선도 — 생성 시각과 현재 시각 차이가 2일+ 이면 경고(스크립트 재실행 권장)
  const genAt = D.generatedAt ? new Date(D.generatedAt) : null;
  const ageHours = genAt && !isNaN(genAt) ? (Date.now() - genAt.getTime()) / 3.6e6 : null;
  const stale = ageHours != null && ageHours >= 48;

  return <div style={{ minHeight: "100vh", paddingBottom: 52 }}>
    {/* sticky chrome */}
    <div style={{ position: "sticky", top: 0, zIndex: 50, background: C.surface, borderBottom: `1px solid ${C.line2}` }}>
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "0 24px" }}>
        {/* brand row */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", height: 60 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
              <span style={{ width: 34, height: 34, borderRadius: 8, background: C.ink, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--serif)", fontStyle: "italic", fontSize: 24, lineHeight: 1 }}>A</span>
              <span style={{ fontSize: 21, fontWeight: 800, letterSpacing: "-0.02em", color: C.ink }}>ATLAS</span>
            </div>
            <span style={{ width: 1, height: 22, background: C.line2 }}></span>
            <span className="mono" style={{ fontSize: 11.5, color: C.ink2, letterSpacing: "0.02em" }}>{D.today}</span>
          </div>

          {/* center: regime + weights */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}
               title="현재 시장 국면에 따라 5개 팩터에 적용되는 가중치(%). 합 100%.">
            <RegimeBadge regime={overall} regimes={D.regimes} />
            <span style={{ width: 1, height: 18, background: C.line2 }}></span>
            <MonoCaps style={{ fontSize: 8.5 }} color={C.ink3}>국면 가중치</MonoCaps>
            <span className="mono" style={{ fontSize: 10.5, color: C.ink2, letterSpacing: "0.02em", whiteSpace: "nowrap" }}>
              모멘텀 <b style={{ color: C.acc }}>{w.m}</b> · 가치 <b style={{ color: C.ink }}>{w.v}</b> · 우량성 <b style={{ color: C.ink }}>{w.q}</b> · 성장 <b style={{ color: C.ink }}>{w.g}</b> · 심리 <b style={{ color: C.acc }}>{w.s}</b>
            </span>
          </div>

          {/* right: 가격 기준일(신선도) + 데이터 생성 시각 */}
          <div style={{ textAlign: "right" }}>
            <MonoCaps style={{ fontSize: 9 }} color={C.ink3} title="대시보드 가격이 기준한 최신 거래일">가격 기준일</MonoCaps>
            <div style={{ display: "flex", alignItems: "center", gap: 6, justifyContent: "flex-end" }}>
              <span style={{ width: 6, height: 6, borderRadius: 999, background: stale ? C.warn : C.ok }}></span>
              <span className="mono tnum" style={{ fontSize: 12, fontWeight: 600, color: C.ink }}>{D.priceAsof || D.updated}</span>
            </div>
            {/* PR-3: 데이터 생성 시각 + 오래됨 경고 */}
            {D.generatedAtLabel && (
              <div className="mono" style={{ fontSize: 9, color: stale ? C.warn : C.ink3, marginTop: 1 }}
                   title="이 화면 데이터가 생성된 시각. 최신화하려면 start_dashboard 스크립트를 다시 실행하세요.">
                데이터 생성: {D.generatedAtLabel}
              </div>
            )}
            {D.priceAsofByMarket && (
              <div className="mono" style={{ fontSize: 9, color: C.ink3, marginTop: 1 }}>
                KR {D.priceAsofByMarket.KR || "—"} · US {D.priceAsofByMarket.US || "—"}
              </div>
            )}
          </div>
        </div>

        {/* tab row */}
        <div style={{ display: "flex", gap: 2 }}>
          {tabs.map((t) => {
            const active = tab === t.k;
            return <button key={t.k} onClick={() => setTab(t.k)} style={{
              border: "none", background: "none", cursor: "pointer", padding: "11px 16px",
              fontSize: 13.5, fontWeight: active ? 700 : 500, color: active ? C.ink : C.ink2,
              borderBottom: `2px solid ${active ? C.acc : "transparent"}`, marginBottom: -1,
              fontFamily: "var(--sans)", letterSpacing: "-0.005em", transition: "color .15s",
            }}>{t.label}</button>;
          })}
        </div>
      </div>
    </div>

    {/* PR-3: 데이터 오래됨 경고(생성 후 2일+) */}
    {stale && (
      <div style={{ background: C.warnBg, borderBottom: `1px solid ${C.warn}33` }}>
        <div style={{ maxWidth: 1280, margin: "0 auto", padding: "8px 24px", display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12 }}>⚠️</span>
          <span style={{ fontSize: 12, color: C.warn }}>
            데이터가 오래되었을 수 있습니다(생성: {D.generatedAtLabel}). 최신 데이터로 보려면 <b>start_dashboard</b> 스크립트를 다시 실행하세요.
          </span>
        </div>
      </div>
    )}

    {/* content */}
    <div style={{ maxWidth: 1280, margin: "0 auto", padding: "20px 24px 32px" }}>
      {tab === "overview" && <Overview D={D} nav={nav} goNews={goNews} />}
      {tab === "detail" && <StockDetail D={D} ticker={ticker} nav={nav} />}
      {tab === "news" && <NewsTab D={D} filterTicker={newsFilter} setFilterTicker={selectNewsTicker} nav={nav} />}
      {tab === "screener" && <Screener D={D} nav={nav} />}
      {tab === "market" && <Market D={D} />}
      {tab === "research" && <Research D={D} nav={nav} />}
      {tab === "portfolio" && <Portfolio D={D} nav={nav} />}
      {tab === "strategy" && <Strategy D={D} />}
      {tab === "manage" && <WatchlistAdmin D={D} />}
    </div>

  </div>;
}
