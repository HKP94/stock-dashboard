import { useMemo, useState } from 'react';
import { MonoCaps, Num, C } from './ui.jsx';
import { Panel } from './tabsA.jsx';
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  BarChart, Bar,
} from 'recharts';

const HORIZONS = ["1y", "3y", "5y"];
const HORIZON_LABEL = { "1y": "1년", "3y": "3년", "5y": "5년" };
const BENCHMARK_LABEL = { "^KS11": "KOSPI", "^GSPC": "S&P500", "^IXIC": "NASDAQ" };
const SERIES_COLOR = {
  strategy: C.acc,
  "^KS11": C.warn,
  "^GSPC": C.ink2,
  "^IXIC": C.neg,
};

const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);
const pctColor = (v) => (v == null ? C.ink3 : v >= 0 ? C.up : C.down);   // 등락축(수익률·MDD)

const DIR_COLOR = { "강세": C.pos, "중립": C.warn, "약세": C.neg };
const AXIS_LABEL = { momentum: "모멘텀", value: "가치", quality: "우량성", growth: "성장", composite: "종합" };
const REGION_LABEL = { kr: "한국 (KR)", us: "미국 (US)" };

function buildLineData(h) {
  if (!h) return [];
  const map = {};
  (h.equityCurve || []).forEach((p) => {
    map[p.date] = { date: p.date, strategy: +(p.value - 100).toFixed(2) };
  });
  Object.entries(h.benchmarks || {}).forEach(([code, curve]) => {
    (curve || []).forEach((p) => {
      map[p.date] = map[p.date] || { date: p.date };
      map[p.date][code] = +(p.value - 100).toFixed(2);
    });
  });
  return Object.values(map).sort((a, b) => a.date.localeCompare(b.date));
}

function buildRegimeData(h) {
  const rr = h?.regimeReturns || {};
  return [
    { regime: "상승", value: rr.bull },
    { regime: "횡보", value: rr.neutral },
    { regime: "하락", value: rr.bear },
  ];
}

// Part 2: 현재 장세(region별 market_score.direction) → regime_returns 최상위 전략 관찰.
function RegimeStrategyPanel({ regimeStrategy }) {
  const regions = ["kr", "us"].filter((k) => regimeStrategy?.[k]);
  if (!regions.length) return null;
  return (
    <Panel title="현재 장세 최적 전략" sub="지금 장세에서 역사적으로 강했던 전략 · 관찰(매매지시 아님)">
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", padding: 16 }}>
        {regions.map((k) => {
          const r = regimeStrategy[k];
          const dirColor = DIR_COLOR[r.direction] || C.ink2;
          return (
            <div key={k} style={{ flex: "1 1 340px", border: `1px solid ${C.line2}`, borderRadius: 10, padding: 14, background: C.surface }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
                <span style={{ fontSize: 14, fontWeight: 800, color: C.ink }}>{REGION_LABEL[k]}</span>
                <span style={{ fontSize: 11, fontWeight: 700, color: dirColor, background: C.surface2, border: `1px solid ${dirColor}33`, borderRadius: 5, padding: "2px 8px" }}>{r.direction} 장세</span>
                {r.score != null ? <span style={{ fontSize: 11, color: C.ink3 }}>점수 {Math.round(r.score)}{r.confidence ? ` · 신뢰도 ${r.confidence}` : ""}</span> : null}
              </div>
              <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>진짜 백테스트 · {r.regimeKo} 구간 수익</MonoCaps>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }}>
                {(r.trueRanked || []).map((s, i) => (
                  <div key={s.name} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 11, color: C.ink3, width: 14 }}>{i + 1}</span>
                    <span style={{ fontSize: 12.5, fontWeight: i === 0 ? 800 : 600, color: i === 0 ? C.acc : C.ink2, flex: 1 }}>{s.label}</span>
                    <span style={{ fontSize: 10, color: C.ink3 }}>{HORIZON_LABEL[s.horizon] || s.horizon}</span>
                    <Num size={12} weight={700} color={pctColor(s.regimeReturn)} style={{ textDecoration: "none" }}>{pct(s.regimeReturn)}</Num>
                  </div>
                ))}
              </div>
              {r.observation ? <div style={{ marginTop: 11, fontSize: 11.5, color: C.ink2, lineHeight: 1.6 }}>{r.observation}</div> : null}
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

// Part 3: 전략별 현재 구성종목 (최신 quant_scores 축 상위 N).
function ConstituentsPanel({ con, strategyName }) {
  if (!con) {
    if (strategyName === "low_vol") {
      return (
        <Panel title="현재 구성종목" sub="저변동성 = 변동성 기준 선택">
          <div style={{ padding: 14, fontSize: 12, color: C.ink2, lineHeight: 1.6 }}>
            저변동성 전략은 quant 팩터가 아니라 실현변동성 기준으로 종목을 고릅니다. 위 "선택 전략 비교"의 백테스트 최근 리밸런싱 바스켓을 참고하세요.
          </div>
        </Panel>
      );
    }
    return null;
  }
  const cap = con.topN || 24;
  const shown = (con.items || []).slice(0, cap);
  const rest = (con.items || []).length - shown.length;
  const sub = con.axis ? `최신 ${AXIS_LABEL[con.axis] || con.axis} 점수 상위 ${con.topN}` : `유니버스 전체 (벤치마크 · ${con.count}종목, 종합순)`;
  return (
    <Panel title="현재 구성종목" sub={sub}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, padding: 14 }}>
        {shown.map((it) => (
          <div key={it.ticker} style={{ display: "flex", alignItems: "center", gap: 7, border: `1px solid ${C.line2}`, borderRadius: 8, padding: "6px 10px", background: C.surface }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: C.ink }}>{it.name || it.ticker}</span>
            {it.score != null ? <span style={{ fontSize: 11, fontWeight: 700, color: C.acc }}>{it.score}</span> : null}
          </div>
        ))}
        {rest > 0 ? <div style={{ display: "flex", alignItems: "center", fontSize: 11, color: C.ink3, padding: "6px 4px" }}>외 {rest}종목</div> : null}
      </div>
    </Panel>
  );
}

function MetricsTable({ strategies }) {
  return (
    <div style={{ overflowX: "auto", borderTop: `1px solid ${C.line}` }}>
      <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 980 }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${C.line2}` }}>
            <th style={{ textAlign: "left", padding: "9px 14px" }}><MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>전략</MonoCaps></th>
            {HORIZONS.flatMap((h) => ([
              <th key={`${h}-cum`} style={{ textAlign: "right", padding: "9px 10px" }}><MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{HORIZON_LABEL[h]} 누적</MonoCaps></th>,
              <th key={`${h}-cagr`} style={{ textAlign: "right", padding: "9px 10px" }}><MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{HORIZON_LABEL[h]} CAGR</MonoCaps></th>,
              <th key={`${h}-mdd`} style={{ textAlign: "right", padding: "9px 10px" }}><MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{HORIZON_LABEL[h]} MDD</MonoCaps></th>,
              <th key={`${h}-sharpe`} style={{ textAlign: "right", padding: "9px 10px" }}><MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{HORIZON_LABEL[h]} Sharpe</MonoCaps></th>,
            ]))}
          </tr>
        </thead>
        <tbody>
          {strategies.map((s) => (
            <tr key={s.name} style={{ borderBottom: `1px solid ${C.line}` }}>
              <td style={{ padding: "11px 14px" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: C.ink }}>{s.label}</span>
                  <span style={{ fontSize: 11, color: C.ink3 }}>{s.description}</span>
                </div>
              </td>
              {HORIZONS.flatMap((h) => {
                const m = s.horizons?.[h] || {};
                return [
                  <td key={`${s.name}-${h}-cum`} style={{ padding: "11px 10px", textAlign: "right" }}><Num size={12} weight={700} color={pctColor(m.cumReturn)} style={{ textDecoration: "none" }}>{pct(m.cumReturn)}</Num></td>,
                  <td key={`${s.name}-${h}-cagr`} style={{ padding: "11px 10px", textAlign: "right" }}><Num size={12} weight={600} color={pctColor(m.cagr)} style={{ textDecoration: "none" }}>{pct(m.cagr)}</Num></td>,
                  <td key={`${s.name}-${h}-mdd`} style={{ padding: "11px 10px", textAlign: "right" }}><Num size={12} weight={600} color={C.neg} style={{ textDecoration: "none" }}>{pct(m.mdd)}</Num></td>,
                  <td key={`${s.name}-${h}-sharpe`} style={{ padding: "11px 10px", textAlign: "right" }}><Num size={12} weight={600} color={C.ink} style={{ textDecoration: "none" }}>{m.sharpe == null ? "—" : m.sharpe.toFixed(2)}</Num></td>,
                ];
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StrategyExplorer({ title, badge, badgeColor, badgeBg, strategies, warning, constituents }) {
  const [selectedName, setSelectedName] = useState(strategies[0]?.name || "");
  const [selectedHorizon, setSelectedHorizon] = useState("5y");
  const selected = strategies.find((s) => s.name === selectedName) || strategies[0];
  const horizon = selected?.horizons?.[selectedHorizon] || selected?.horizons?.["5y"] || selected?.horizons?.["3y"] || selected?.horizons?.["1y"];
  const lineData = useMemo(() => buildLineData(horizon), [horizon]);
  const regimeData = useMemo(() => buildRegimeData(horizon), [horizon]);

  if (!strategies.length) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 16, fontWeight: 800, color: C.ink }}>{title}</span>
        <span style={{ fontSize: 11, fontWeight: 700, color: badgeColor, background: badgeBg, border: `1px solid ${badgeColor}33`, borderRadius: 5, padding: "2px 8px" }}>{badge}</span>
      </div>

      {warning ? (
        <div style={{ background: C.negBg, border: `1px solid ${C.neg}33`, borderRadius: 10, padding: "13px 18px", fontSize: 12, color: C.ink2, lineHeight: 1.6 }}>
          <div style={{ fontSize: 12.5, color: C.neg, fontWeight: 700, marginBottom: 4 }}>⚠️ 선택편향 경고</div>
          {warning}
        </div>
      ) : null}

      <Panel title="전략별 1·3·5년 성과" sub="누적수익률 · CAGR · MDD · Sharpe">
        <MetricsTable strategies={strategies} />
      </Panel>

      <Panel title="선택 전략 비교" sub="전략 1개 + KOSPI / S&P500 / NASDAQ (리베이스 100)">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "14px 16px 0", flexWrap: "wrap" }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {strategies.map((s) => (
              <button key={s.name} onClick={() => setSelectedName(s.name)}
                style={{
                  borderRadius: 999, border: `1px solid ${selected?.name === s.name ? C.acc : C.line2}`,
                  background: selected?.name === s.name ? C.accBg : C.surface,
                  color: selected?.name === s.name ? C.acc : C.ink2, padding: "6px 10px", fontSize: 12, fontWeight: 700,
                }}>
                {s.label}
              </button>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {HORIZONS.filter((h) => selected?.horizons?.[h]).map((h) => (
              <button key={h} onClick={() => setSelectedHorizon(h)}
                style={{
                  borderRadius: 8, border: `1px solid ${selectedHorizon === h ? C.acc : C.line2}`,
                  background: selectedHorizon === h ? C.accBg : C.surface,
                  color: selectedHorizon === h ? C.acc : C.ink2, padding: "6px 10px", fontSize: 12, fontWeight: 700,
                }}>
                {HORIZON_LABEL[h]}
              </button>
            ))}
          </div>
        </div>

        {selected?.description ? (
          <div style={{ padding: "10px 16px 0", fontSize: 12, color: C.ink2 }}>{selected.description}</div>
        ) : null}

        {horizon?.selectedTickers?.length ? (
          <div style={{ padding: "10px 16px 0", fontSize: 12, color: C.ink2 }}>
            고정 바스켓: {horizon.selectedTickers.map((t) => t.name || t.ticker || t).join(", ")}
          </div>
        ) : null}

        <div style={{ padding: "12px 12px 4px" }}>
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={lineData} margin={{ top: 8, right: 24, left: 0, bottom: 4 }}>
              <CartesianGrid stroke={C.line} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: C.ink3 }} tickFormatter={(d) => d?.slice(2, 7)} minTickGap={24} />
              <YAxis tick={{ fontSize: 10, fill: C.ink3 }} tickFormatter={(v) => `${v}%`} width={48} />
              <Tooltip
                formatter={(v, name) => [`${v >= 0 ? "+" : ""}${v}%`, name === "strategy" ? selected?.label : BENCHMARK_LABEL[name] || name]}
                labelStyle={{ fontSize: 11, color: C.ink2 }}
                contentStyle={{ fontSize: 12, borderRadius: 8, border: `1px solid ${C.line2}` }}
              />
              <Legend formatter={(name) => <span style={{ fontSize: 11.5, color: C.ink2 }}>{name === "strategy" ? selected?.label : BENCHMARK_LABEL[name] || name}</span>} />
              <Line type="monotone" dataKey="strategy" stroke={SERIES_COLOR.strategy} strokeWidth={2.4} dot={false} />
              {Object.keys(horizon?.benchmarks || {}).map((code) => (
                <Line key={code} type="monotone" dataKey={code} stroke={SERIES_COLOR[code] || C.ink3} strokeWidth={1.5} dot={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <Panel title="국면별 성과" sub="상승 · 횡보 · 하락 구간 누적수익률">
        <div style={{ padding: "12px 12px 4px" }}>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={regimeData}>
              <CartesianGrid stroke={C.line} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="regime" tick={{ fontSize: 11, fill: C.ink3 }} />
              <YAxis tick={{ fontSize: 10, fill: C.ink3 }} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} width={48} />
              <Tooltip formatter={(v) => pct(v)} />
              <Bar dataKey="value" fill={C.acc} radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <ConstituentsPanel con={constituents?.[selected?.name]} strategyName={selected?.name} />
    </div>
  );
}

export function Strategy({ D }) {
  const bt = D.backtest || {};
  const trueTrack = bt.trueTrack || { strategies: [] };
  const retro = bt.retrospective || { strategies: [], warning: "" };

  if (!trueTrack.strategies?.length && !retro.strategies?.length) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: C.ink3, fontSize: 13, background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10 }}>
전략 비교 데이터를 준비 중입니다. 잠시 후 다시 확인해 주세요.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <RegimeStrategyPanel regimeStrategy={bt.regimeStrategy} />

      <StrategyExplorer
        title="진짜 백테스트"
        badge="실제 백테스트"
        badgeColor={C.pos}
        badgeBg={C.posBg}
        strategies={trueTrack.strategies || []}
        constituents={bt.constituents}
      />

      <StrategyExplorer
        title="회고 전략"
        badge="참고용 · 백테스트 아님"
        badgeColor={C.warn}
        badgeBg={C.warnBg}
        strategies={retro.strategies || []}
        warning={retro.warning}
        constituents={bt.constituents}
      />
    </div>
  );
}
