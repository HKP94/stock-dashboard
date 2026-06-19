// ATLAS — shared UI primitives + SVG charts
import { factorLabel, regimeLabel } from './display.js';

export const C = {
  ink: "#0F1419", ink2: "#4A5568", ink3: "#94A3B8",
  line: "#ECEEF1", line2: "#DDE1E6", lineStrong: "#C7CCD3",
  acc: "#2A5BFF", accHover: "#1A48EA", accTint: "#E8EEFF", accSoft: "rgba(42,91,255,0.08)",
  ok: "#15803D", warn: "#B45309", bad: "#B91C1C",
  okBg: "#F0FDF4", warnBg: "#FFFBEB", badBg: "#FEF2F2",
  surface: "#FFFFFF", surface2: "#F4F6F8", canvas: "#FAFBFC", tint: "#EEF0F3",
};

export const fmtPrice = (s) => {
  if (s.price == null) return "—";  // PR-1: 데이터 없는 종목은 ₩0 대신 —
  if (s.cur === "₩") return "₩" + Math.round(s.price).toLocaleString("ko-KR");
  return "$" + s.price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};
export const fmtNum = (n, d = 0) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
export const compColor = (c) => (c >= 70 ? C.ok : c >= 55 ? C.warn : C.ink3);
export const compBg = (c) => (c >= 70 ? C.okBg : c >= 55 ? C.warnBg : C.surface2);
export const sentMeta = (label) =>
  label === "긍정" ? { c: C.ok, bg: C.okBg, t: "긍정" }
    : label === "부정" ? { c: C.bad, bg: C.badBg, t: "부정" }
      : { c: C.ink2, bg: C.surface2, t: "중립" };
export const flagTone = (f) => {
  if (/과열|과매도|데드크로스|약세|경계|하회|신고가 -1|신고가 -2/.test(f)) return C.bad;
  if (/임박|급증|매력|유지|저변동/.test(f)) return C.warn;
  if (/강세|골든크로스 발생|수혜|모멘텀|신고가 -3/.test(f)) return C.ok;
  return C.ink2;
};

export function MonoCaps({ children, style, color }) {
  return <span className="mono" style={{ fontSize: 10.5, letterSpacing: "0.08em", textTransform: "uppercase", fontWeight: 500, color: color || C.ink2, ...style }}>{children}</span>;
}
export function Num({ children, size = 15, weight = 600, color = C.ink, style }) {
  return <span className="tnum" style={{ fontSize: size, fontWeight: weight, color, letterSpacing: "-0.01em", ...style }}>{children}</span>;
}
export function ChangePct({ v, inv, size = 13.5, weight = 600 }) {
  if (v == null) {
    return <span className="tnum" style={{ fontSize: size, fontWeight: weight, color: C.ink3, letterSpacing: "-0.01em" }}>—</span>;
  }
  const up = inv ? v < 0 : v > 0;
  const flat = v === 0;
  const col = flat ? C.ink3 : up ? C.ok : C.bad;
  const arrow = flat ? "·" : v > 0 ? "▲" : "▼";
  return <span className="tnum" style={{ fontSize: size, fontWeight: weight, color: col, letterSpacing: "-0.01em", whiteSpace: "nowrap" }}>
    <span style={{ fontSize: size * 0.72, marginRight: 3 }}>{arrow}</span>{v > 0 ? "+" : ""}{v.toFixed(2)}%
  </span>;
}
export function Pill({ children, tone, solid, style, onClick, active }) {
  const map = { ok: C.ok, bad: C.bad, warn: C.warn, acc: C.acc, neutral: C.ink2 };
  const col = map[tone] || C.ink2;
  const bgMap = { ok: C.okBg, bad: C.badBg, warn: C.warnBg, acc: C.accTint, neutral: C.surface2 };
  return <span onClick={onClick} style={{
    display: "inline-flex", alignItems: "center", gap: 4, whiteSpace: "nowrap",
    fontSize: 11.5, fontWeight: 600, letterSpacing: "-0.005em", padding: "3px 9px", borderRadius: 999,
    border: `1px solid ${solid ? col : tone === "acc" ? "rgba(42,91,255,0.3)" : C.line2}`,
    color: solid ? "#fff" : col, background: solid ? col : (active ? bgMap[tone] : C.surface),
    cursor: onClick ? "pointer" : "default", ...style,
  }}>{children}</span>;
}
export function SentBadge({ label, score, sm }) {
  const m = sentMeta(label);
  return <span style={{
    display: "inline-flex", alignItems: "center", gap: 5, padding: sm ? "2px 7px" : "3px 9px",
    borderRadius: 5, background: m.bg, border: `1px solid ${m.c}22`,
    fontSize: sm ? 11 : 11.5, fontWeight: 700, color: m.c, whiteSpace: "nowrap",
  }}>
    <span style={{ width: 6, height: 6, borderRadius: 999, background: m.c, display: "inline-block" }}></span>
    {m.t}{score != null && <span className="tnum" style={{ fontWeight: 600, opacity: 0.85 }}>{score}</span>}
  </span>;
}
export function HoldDot({ on }) {
  return <span title={on ? "보유" : "미보유"} style={{
    width: 7, height: 7, borderRadius: 999, display: "inline-block",
    background: on ? C.acc : "transparent", border: on ? "none" : `1.5px solid ${C.line2}`,
  }}></span>;
}
export function AlignBadge({ on }) {
  return <span style={{ fontSize: 11, fontWeight: 700, color: on ? C.ok : C.ink3, whiteSpace: "nowrap" }}>{on ? "정배열" : "—"}</span>;
}

export function CompositeCell({ value, width = 110 }) {
  const col = compColor(value);
  return <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
    <Num size={17} weight={700} color={col} style={{ width: 26, textAlign: "right" }}>{value ?? "—"}</Num>
    <div style={{ flex: 1, height: 6, background: C.surface2, borderRadius: 999, overflow: "hidden", minWidth: width * 0.5 }}>
      <div style={{ width: (value ?? 0) + "%", height: "100%", background: col, borderRadius: 999 }}></div>
    </div>
  </div>;
}

export function MiniBars({ f, h = 26 }) {
  const order = [["m", "모", factorLabel("m")], ["v", "가", factorLabel("v")], ["q", "우", factorLabel("q")], ["g", "성", factorLabel("g")], ["s", "심", factorLabel("s")]];
  return <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: h }}>
    {order.map(([k, lbl, ko]) => {
      const v = f[k];
      const col = v >= 70 ? C.ok : v >= 45 ? C.ink2 : C.ink3;
      return <div key={k} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, cursor: "help" }} title={`${ko} ${v}`}>
        <div style={{ width: 7, height: h - 10, background: C.surface2, borderRadius: 2, display: "flex", alignItems: "flex-end", overflow: "hidden" }}>
          <div style={{ width: "100%", height: (v / 100) * (h - 10), background: col, borderRadius: 2 }}></div>
        </div>
        <span className="mono" style={{ fontSize: 8, color: C.ink3, fontWeight: 600 }}>{lbl}</span>
      </div>;
    })}
  </div>;
}

export function FactorBar({ label, value, group, fallback }) {
  // PR-6: 중립 폴백(데이터 없음→50)은 옅은 색 + "데이터 없음" 표기로 실제 점수와 구분
  const col = fallback ? C.line2 : value >= 70 ? C.ok : value >= 50 ? C.warn : C.ink3;
  const groupLabel = group === "timing" ? "타이밍" : group === "mispricing" ? "미스프라이싱" : null;
  return <div style={{ display: "grid", gridTemplateColumns: "92px 1fr 56px", alignItems: "center", gap: 12, padding: "9px 0" }}>
    <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
      <span style={{ fontSize: 13, fontWeight: 600, color: fallback ? C.ink3 : C.ink }}>{label}</span>
      {groupLabel && <MonoCaps style={{ fontSize: 9 }} color={group === "timing" ? C.acc : C.ink3}>{groupLabel}</MonoCaps>}
    </div>
    <div style={{ height: 9, background: C.surface2, borderRadius: 999, overflow: "hidden" }}>
      <div style={{ width: value + "%", height: "100%", background: col, borderRadius: 999, transition: "width .5s", opacity: fallback ? 0.5 : 1 }}></div>
    </div>
    {fallback
      ? <span style={{ fontSize: 9, color: C.ink3, textAlign: "right", whiteSpace: "nowrap" }} title="데이터가 없어 중립(50)으로 처리됨">데이터 없음</span>
      : <Num size={15} weight={700} color={col} style={{ textAlign: "right" }}>{value}</Num>}
  </div>;
}

export function Sparkline({ data, color = C.acc, w = 86, h = 26, fill }) {
  const min = Math.min(...data), max = Math.max(...data);
  const rng = max - min || 1;
  const pts = data.map((d, i) => [(i / (data.length - 1)) * w, h - 3 - ((d - min) / rng) * (h - 6)]);
  const line = pts.map((p) => p.join(",")).join(" ");
  const area = `${pts[0][0]},${h} ` + line + ` ${pts[pts.length - 1][0]},${h}`;
  return <svg width={w} height={h} style={{ display: "block", overflow: "visible" }}>
    {fill && <polygon points={area} fill={color} opacity={0.08} />}
    <polyline points={line} fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="2.1" fill={color} />
  </svg>;
}

// PR-4: 가격차트 + 거래량 바 + SMA60/120 토글
// showSMAs: { sma20: bool, sma60: bool, sma120: bool }
export function PriceChart({ stock, w = 520, h = 240, showSMAs = { sma20: true, sma60: false, sma120: false } }) {
  const data = stock.series;
  if (!data || data.length === 0) return null;

  // 가격 영역 70%, 거래량 영역 30% (하단)
  const volH = 50;
  const priceH = h - volH - 6;
  const pad = { l: 8, r: 52, t: 14, b: 22 };
  const iw = w - pad.l - pad.r;
  const pih = priceH - pad.t;  // price inner height

  const n = data.length;
  const xPos = (i) => pad.l + (n > 1 ? (i / (n - 1)) * iw : 0);

  // 가격 영역 y 매핑
  const pmin = Math.min(...data), pmax = Math.max(...data);
  const prng = pmax - pmin || 1;
  const yPrice = (v) => pad.t + pih - ((v - pmin) / prng) * pih;

  const up = data[n - 1] >= data[0];
  const col = up ? C.ok : C.bad;
  const priceLine = data.map((d, i) => `${xPos(i)},${yPrice(d)}`).join(" ");
  const priceArea = `${xPos(0)},${pad.t + pih} ${priceLine} ${xPos(n - 1)},${pad.t + pih}`;

  // SMA 시리즈 (서버 계산값 사용, 없으면 런타임 계산)
  const calcSma = (w) => data.map((_, i) => {
    const slc = data.slice(Math.max(0, i - w + 1), i + 1);
    return slc.reduce((a, b) => a + b, 0) / slc.length;
  });
  const sma20arr = calcSma(20);
  const sma60arr  = stock.sma60Series?.length  ? stock.sma60Series  : calcSma(60);
  const sma120arr = stock.sma120Series?.length ? stock.sma120Series : calcSma(120);

  const smaToLine = (arr) => arr
    .map((v, i) => (v != null ? `${xPos(i)},${yPrice(v)}` : null))
    .filter(Boolean).join(" ");

  // 거래량 영역
  const volTop = pad.t + pih + 6;
  const volInnerH = volH - pad.b - 2;
  const vols = stock.volumeSeries || [];
  const vmax = vols.length ? Math.max(...vols.filter(Boolean), 1) : 1;
  const barW = n > 1 ? Math.max(1, (iw / n) - 1) : iw;

  const gid = "g" + stock.t;
  const priceTicks = [pmax, (pmax + pmin) / 2, pmin];
  const months = ["1월", "2월", "3월", "4월", "5월", "6월"];

  return (
    <svg
      width={w}
      height={h}
      style={{ display: "block", width: "100%" }}
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={col} stopOpacity="0.12" />
          <stop offset="100%" stopColor={col} stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* 가격 그리드 */}
      {priceTicks.map((tk, i) => (
        <g key={i}>
          <line x1={pad.l} x2={pad.l + iw} y1={yPrice(tk)} y2={yPrice(tk)} stroke={C.line} strokeWidth="1" strokeDasharray={i === 2 ? "" : "3 3"} />
          <text x={pad.l + iw + 6} y={yPrice(tk) + 3} fontSize="10" fill={C.ink3} className="tnum" fontFamily="var(--mono)">
            {tk > 1000 ? Math.round(tk).toLocaleString() : tk.toFixed(1)}
          </text>
        </g>
      ))}

      {/* 가격 면적 + 선 */}
      <polygon points={priceArea} fill={`url(#${gid})`} />
      {showSMAs.sma20  && <polyline points={smaToLine(sma20arr)}  fill="none" stroke={C.acc}  strokeWidth="1.4" strokeDasharray="4 3" opacity="0.9" />}
      {showSMAs.sma60  && <polyline points={smaToLine(sma60arr)}  fill="none" stroke={C.warn} strokeWidth="1.3" strokeDasharray="4 3" opacity="0.85" />}
      {showSMAs.sma120 && <polyline points={smaToLine(sma120arr)} fill="none" stroke={C.ink3} strokeWidth="1.2" strokeDasharray="4 3" opacity="0.8" />}
      <polyline points={priceLine} fill="none" stroke={col} strokeWidth="2" strokeLinejoin="round" />
      <circle cx={xPos(n - 1)} cy={yPrice(data[n - 1])} r="3" fill={col} />

      {/* 거래량 구분선 */}
      <line x1={pad.l} x2={pad.l + iw} y1={volTop - 2} y2={volTop - 2} stroke={C.line2} strokeWidth="0.5" />

      {/* 거래량 바 */}
      {vols.map((v, i) => {
        if (!v) return null;
        const bh = (v / vmax) * volInnerH;
        return (
          <rect
            key={i}
            x={xPos(i) - barW / 2}
            y={volTop + volInnerH - bh}
            width={barW}
            height={bh}
            fill={C.ink3}
            opacity="0.3"
          />
        );
      })}

      {/* x축 월 라벨 */}
      {months.map((m, i) => (
        <text key={m} x={pad.l + (i / 5) * iw} y={h - 5} fontSize="9.5" fill={C.ink3} textAnchor="middle" fontFamily="var(--mono)">{m}</text>
      ))}
    </svg>
  );
}

export function GaugeBar({ value, max = 100, tone, suffix }) {
  const col = tone === "ok" ? C.ok : tone === "bad" ? C.bad : tone === "warn" ? C.warn : C.ink2;
  const pct = Math.min(100, (value / max) * 100);
  return <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
    <div style={{ flex: 1, height: 8, background: C.surface2, borderRadius: 999, overflow: "hidden" }}>
      <div style={{ width: pct + "%", height: "100%", background: col, borderRadius: 999 }}></div>
    </div>
    <Num size={15} weight={700} color={col} style={{ width: 48, textAlign: "right" }}>{value}{suffix || ""}</Num>
  </div>;
}

export function SentStack({ pos, neu, neg, w = 130 }) {
  const total = pos + neu + neg || 1;
  const seg = (n, c) => n > 0 ? <div style={{ width: (n / total) * 100 + "%", background: c, height: "100%" }} title={n}></div> : null;
  return <div style={{ display: "flex", height: 8, width: w, borderRadius: 999, overflow: "hidden", background: C.surface2 }}>
    {seg(pos, C.ok)}{seg(neu, C.ink3)}{seg(neg, C.bad)}
  </div>;
}

export function RegimeBadge({ regime, lg, regimes }) {
  const D = regimes[regime];
  const col = D.color === "acc" ? C.acc : D.color === "warn" ? C.warn : C.bad;
  const bg = D.color === "acc" ? C.accTint : D.color === "warn" ? C.warnBg : C.badBg;
  return <span style={{
    display: "inline-flex", alignItems: "center", gap: 6, padding: lg ? "6px 13px" : "3px 10px",
    borderRadius: 999, background: bg, border: `1px solid ${col}33`, color: col,
    fontSize: lg ? 13 : 11.5, fontWeight: 700, letterSpacing: "-0.01em",
  }}>
    <span style={{ width: 7, height: 7, borderRadius: 999, background: col }}></span>
    {regimeLabel(regime)}
  </span>;
}

export function WeightBars({ w }) {
  const items = [["m", factorLabel("m"), "timing"], ["v", factorLabel("v"), "mispricing"], ["q", factorLabel("q"), "mispricing"], ["g", factorLabel("g"), "mispricing"], ["s", factorLabel("s"), "timing"]];
  const maxW = Math.max(...items.map(([k]) => w[k]));
  return <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
    {items.map(([k, ko, grp]) => {
      const col = grp === "timing" ? C.acc : C.ink;
      return <div key={k} style={{ display: "grid", gridTemplateColumns: "70px 1fr 44px", alignItems: "center", gap: 12 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: C.ink }}>{ko}</span>
        <div style={{ height: 10, background: C.surface2, borderRadius: 999, overflow: "hidden" }}>
          <div style={{ width: (w[k] / maxW) * 100 + "%", height: "100%", background: col, borderRadius: 999, opacity: grp === "timing" ? 1 : 0.85 }}></div>
        </div>
        <Num size={14} weight={700} color={col} style={{ textAlign: "right" }}>{w[k]}%</Num>
      </div>;
    })}
  </div>;
}

export const btnGhost = { border: "none", background: "transparent", color: C.acc, fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "var(--sans)" };
