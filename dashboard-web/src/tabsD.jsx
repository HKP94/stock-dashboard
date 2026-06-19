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
  "^IXIC": C.bad,
};

const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);
const pctColor = (v) => (v == null ? C.ink3 : v >= 0 ? C.ok : C.bad);

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
                  <td key={`${s.name}-${h}-mdd`} style={{ padding: "11px 10px", textAlign: "right" }}><Num size={12} weight={600} color={C.bad} style={{ textDecoration: "none" }}>{pct(m.mdd)}</Num></td>,
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

function StrategyExplorer({ title, badge, badgeColor, badgeBg, strategies, warning }) {
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
        <div style={{ background: C.badBg, border: `1px solid ${C.bad}33`, borderRadius: 10, padding: "13px 18px", fontSize: 12, color: C.ink2, lineHeight: 1.6 }}>
          <div style={{ fontSize: 12.5, color: C.bad, fontWeight: 700, marginBottom: 4 }}>⚠️ 선택편향 경고</div>
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
                  background: selected?.name === s.name ? C.accBg : C.bg,
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
                  borderRadius: 8, border: `1px solid ${selectedHorizon === h ? C.ink : C.line2}`,
                  background: selectedHorizon === h ? C.ink : C.bg,
                  color: selectedHorizon === h ? C.bg : C.ink2, padding: "6px 10px", fontSize: 12, fontWeight: 700,
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
      <StrategyExplorer
        title="진짜 백테스트"
        badge="실제 백테스트"
        badgeColor={C.ok}
        badgeBg={C.okBg}
        strategies={trueTrack.strategies || []}
      />

      <StrategyExplorer
        title="회고 전략"
        badge="참고용 · 백테스트 아님"
        badgeColor={C.warn}
        badgeBg={C.warnBg}
        strategies={retro.strategies || []}
        warning={retro.warning}
      />
    </div>
  );
}
