// ATLAS — Tabs D: 전략 비교 (백테스트 + 회고)
// PR-8. 과거 성과는 미래를 보장하지 않습니다.
//
// ⚠️ 두 섹션은 성격이 완전히 다르다(혼동 금지):
//   1) 모멘텀 백테스트 = 진짜 백테스트(과거 시점 데이터만, 미래정보 없음)
//   2) 팩터별 회고 = 오늘 상위 종목의 과거 수익률(선정시점편향, 백테스트 아님)

import { MonoCaps, Num, C } from './ui.jsx';
import { Panel } from './tabsA.jsx';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';

const STRAT_META = {
  momentum_top8:          { label: "모멘텀 Top8", color: C.acc },
  equal_weight_benchmark: { label: "동일가중 (벤치마크)", color: C.ink2 },
  buy_hold_benchmark:     { label: "Buy & Hold (벤치마크)", color: C.warn },
};
const FACTOR_LABEL = { momentum: "모멘텀", value: "가치", quality: "우량성", growth: "성장", composite: "종합" };

const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);
const pctColor = (v) => (v == null ? C.ink3 : v >= 0 ? C.ok : C.bad);

// 누적수익률(%) 멀티시리즈 데이터로 변환
function buildChartData(strategies) {
  // 날짜축 = momentum_top8 기준
  const base = strategies.find((s) => s.name === "momentum_top8") || strategies[0];
  if (!base || !base.equityCurve?.length) return [];
  const byDate = {};
  base.equityCurve.forEach((p) => { byDate[p.date] = { date: p.date }; });
  strategies.forEach((s) => {
    (s.equityCurve || []).forEach((p) => {
      if (byDate[p.date]) byDate[p.date][s.name] = +((p.value - 1) * 100).toFixed(2);
    });
  });
  return Object.values(byDate);
}

export function Strategy({ D }) {
  const bt = D.backtest || {};
  const trueBt = bt.trueBacktest || {};
  const strategies = trueBt.strategies || [];
  const window = trueBt.window || {};
  const chartData = buildChartData(strategies);
  const retro = (bt.retrospective || {}).byFactor || [];

  if (strategies.length === 0 && retro.length === 0) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: C.ink3, fontSize: 13, background: C.surface, border: `1px solid ${C.line2}`, borderRadius: 10 }}>
백테스트 데이터를 준비 중입니다. 잠시 후 다시 확인해 주세요.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* ───── 섹션 1: 진짜 백테스트 ───── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 16, fontWeight: 800, color: C.ink }}>모멘텀 전략 백테스트</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: C.ok, background: C.okBg, border: `1px solid ${C.ok}33`, borderRadius: 5, padding: "2px 8px" }}>실제 백테스트</span>
        </div>

        <Panel title="누적 수익률" sub={window.months ? `최근 ${window.months}개월 · 월별 리밸런싱` : "월별 리밸런싱"}>
          <div style={{ padding: "16px 12px 8px" }}>
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={320}>
                <LineChart data={chartData} margin={{ top: 8, right: 24, left: 0, bottom: 4 }}>
                  <CartesianGrid stroke={C.line} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: C.ink3 }} tickFormatter={(d) => d?.slice(2, 7)} minTickGap={24} />
                  <YAxis tick={{ fontSize: 10, fill: C.ink3 }} tickFormatter={(v) => `${v}%`} width={48} />
                  <Tooltip
                    formatter={(v, name) => [`${v >= 0 ? "+" : ""}${v}%`, STRAT_META[name]?.label || name]}
                    labelStyle={{ fontSize: 11, color: C.ink2 }}
                    contentStyle={{ fontSize: 12, borderRadius: 8, border: `1px solid ${C.line2}` }}
                  />
                  <Legend formatter={(name) => <span style={{ fontSize: 11.5, color: C.ink2 }}>{STRAT_META[name]?.label || name}</span>} />
                  {strategies.map((s) => (
                    <Line key={s.name} type="monotone" dataKey={s.name}
                      stroke={STRAT_META[s.name]?.color || C.ink3}
                      strokeWidth={s.name === "momentum_top8" ? 2.4 : 1.5}
                      dot={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div style={{ padding: 24, textAlign: "center", color: C.ink3 }}>차트 데이터 없음</div>
            )}
          </div>
          {/* 메트릭 표 */}
          <div style={{ borderTop: `1px solid ${C.line}`, overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${C.line2}` }}>
                  {["전략", "누적수익률", "CAGR", "MDD", "변동성", "Sharpe"].map((h, i) => (
                    <th key={i} style={{ textAlign: i === 0 ? "left" : "right", padding: "9px 16px" }}>
                      <MonoCaps style={{ fontSize: 9.5 }} color={C.ink3}>{h}</MonoCaps>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {strategies.map((s) => (
                  <tr key={s.name} style={{ borderBottom: `1px solid ${C.line}` }}>
                    <td style={{ padding: "11px 16px" }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
                        <span style={{ width: 10, height: 3, borderRadius: 2, background: STRAT_META[s.name]?.color || C.ink3 }}></span>
                        <span style={{ fontSize: 13, fontWeight: s.name === "momentum_top8" ? 700 : 600, color: C.ink }}>{STRAT_META[s.name]?.label || s.name}</span>
                      </span>
                    </td>
                    <td style={{ padding: "11px 16px", textAlign: "right" }}><Num size={13} weight={700} color={pctColor(s.cumReturn)} style={{ textDecoration: "none" }}>{pct(s.cumReturn)}</Num></td>
                    <td style={{ padding: "11px 16px", textAlign: "right" }}><Num size={13} weight={600} color={pctColor(s.cagr)} style={{ textDecoration: "none" }}>{pct(s.cagr)}</Num></td>
                    <td style={{ padding: "11px 16px", textAlign: "right" }}><Num size={13} weight={600} color={C.bad} style={{ textDecoration: "none" }}>{pct(s.mdd)}</Num></td>
                    <td style={{ padding: "11px 16px", textAlign: "right" }}><Num size={13} weight={600} color={C.ink2} style={{ textDecoration: "none" }}>{pct(s.vol)}</Num></td>
                    <td style={{ padding: "11px 16px", textAlign: "right" }}><Num size={13} weight={600} color={C.ink} style={{ textDecoration: "none" }}>{s.sharpe == null ? "—" : s.sharpe.toFixed(2)}</Num></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ padding: "10px 16px", background: C.surface2, borderRadius: "0 0 10px 10px", fontSize: 11.5, color: C.ink2, lineHeight: 1.5 }}>
            각 리밸런싱 시점에서 <b>그 시점까지의 데이터만</b>으로 모멘텀(12-1M 가중)을 계산해 상위 종목을 동일가중 보유합니다.
            최근 {window.months || "—"}개월, 월별 리밸런싱, 무위험수익률 0% 가정. <b>과거 성과는 미래를 보장하지 않습니다.</b>
          </div>
        </Panel>
      </div>

      {/* ───── 섹션 2: 회고 (백테스트 아님) ───── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 16, fontWeight: 800, color: C.ink }}>팩터별 상위종목 회고</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: C.warn, background: C.warnBg, border: `1px solid ${C.warn}33`, borderRadius: 5, padding: "2px 8px" }}>참고용 · 백테스트 아님</span>
        </div>

        {/* 경고 박스 */}
        <div style={{ background: C.badBg, border: `1px solid ${C.bad}33`, borderRadius: 10, padding: "13px 18px" }}>
          <div style={{ fontSize: 12.5, color: C.bad, fontWeight: 700, marginBottom: 4 }}>⚠️ 선정시점편향(look-ahead bias) 주의</div>
          <div style={{ fontSize: 12, color: C.ink2, lineHeight: 1.6 }}>
            아래는 <b>오늘 시점의</b> 퀀트 점수 상위 종목을 뽑아 <b>과거 수익률을 되돌아본</b> 것입니다.
            valuation·컨센서스 데이터가 오늘 스냅샷 1건뿐이라 과거 재현이 불가능하므로 <b>백테스트가 아닙니다</b>.
            "이미 오른 종목을 오늘 상위로 뽑은" 편향이 있어 실제 미래 성과와 무관할 수 있습니다.
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {retro.map((f) => (
            <Panel key={f.factor} title={`${FACTOR_LABEL[f.factor] || f.factor} 상위 ${f.topTickers.length}`} sub="회고">
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${C.line2}` }}>
                    {["종목", "1M", "3M", "6M", "12M"].map((h, i) => (
                      <th key={i} style={{ textAlign: i === 0 ? "left" : "right", padding: "7px 12px" }}>
                        <MonoCaps style={{ fontSize: 9 }} color={C.ink3}>{h}</MonoCaps>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {f.topTickers.map((t) => (
                    <tr key={t.ticker} style={{ borderBottom: `1px solid ${C.line}` }}>
                      <td style={{ padding: "8px 12px" }}>
                        <div style={{ display: "flex", flexDirection: "column" }}>
                          <span style={{ fontSize: 12.5, fontWeight: 700, color: C.ink }}>{t.name}</span>
                          <span className="mono" style={{ fontSize: 9, color: C.ink3 }}>{t.ticker}</span>
                        </div>
                      </td>
                      {["ret1m", "ret3m", "ret6m", "ret12m"].map((k) => (
                        <td key={k} style={{ padding: "8px 12px", textAlign: "right" }}>
                          <Num size={12} weight={600} color={pctColor(t[k])} style={{ textDecoration: "none" }}>{pct(t[k])}</Num>
                        </td>
                      ))}
                    </tr>
                  ))}
                  {/* 벤치마크 행 */}
                  <tr style={{ background: C.surface2 }}>
                    <td style={{ padding: "8px 12px" }}><span style={{ fontSize: 11.5, fontWeight: 700, color: C.ink2 }}>벤치마크 (동일가중)</span></td>
                    {["ret1m", "ret3m", "ret6m", "ret12m"].map((k) => (
                      <td key={k} style={{ padding: "8px 12px", textAlign: "right" }}>
                        <Num size={12} weight={600} color={C.ink2} style={{ textDecoration: "none" }}>{pct(f.benchmark?.[k])}</Num>
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </Panel>
          ))}
        </div>
      </div>

    </div>
  );
}
