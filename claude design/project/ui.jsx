// ATLAS — shared UI + SVG charts. Exposes globals via window.
const C = {
  ink: "#0F1419", ink2: "#4A5568", ink3: "#94A3B8",
  line: "#ECEEF1", line2: "#DDE1E6", lineStrong: "#C7CCD3",
  acc: "#2A5BFF", accHover: "#1A48EA", accTint: "#E8EEFF", accSoft: "rgba(42,91,255,0.08)",
  ok: "#15803D", warn: "#B45309", bad: "#B91C1C",
  okBg: "#F0FDF4", warnBg: "#FFFBEB", badBg: "#FEF2F2",
  surface: "#FFFFFF", surface2: "#F4F6F8", canvas: "#FAFBFC", tint: "#EEF0F3",
};

const fmtPrice = (s) => {
  if (s.cur === "₩") return "₩" + Math.round(s.price).toLocaleString("ko-KR");
  return "$" + s.price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};
const fmtNum = (n, d = 0) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const compColor = (c) => (c >= 70 ? C.ok : c >= 55 ? C.warn : C.ink3);
const compBg = (c) => (c >= 70 ? C.okBg : c >= 55 ? C.warnBg : C.surface2);
const sentMeta = (label) =>
  label === "긍정" ? { c: C.ok, bg: C.okBg, t: "긍정" }
    : label === "부정" ? { c: C.bad, bg: C.badBg, t: "부정" }
      : { c: C.ink2, bg: C.surface2, t: "중립" };
const flagTone = (f) => {
  if (/과열|과매도|데드크로스|약세|경계|하회|신고가 -1|신고가 -2/.test(f)) return C.bad;
  if (/임박|급증|매력|유지|저변동/.test(f)) return C.warn;
  if (/강세|골든크로스 발생|수혜|모멘텀|신고가 -3/.test(f)) return C.ok;
  return C.ink2;
};

// ---------- atoms ----------
function MonoCaps({ children, style, color }) {
  return <span className="mono" style={{ fontSize: 10.5, letterSpacing: "0.08em", textTransform: "uppercase", fontWeight: 500, color: color || C.ink2, ...style }}>{children}</span>;
}
function Num({ children, size = 15, weight = 600, color = C.ink, style }) {
  return <span className="tnum" style={{ fontSize: size, fontWeight: weight, color, letterSpacing: "-0.01em", ...style }}>{children}</span>;
}
function ChangePct({ v, inv, size = 13.5, weight = 600 }) {
  const up = inv ? v < 0 : v > 0;
  const flat = v === 0;
  const col = flat ? C.ink3 : up ? C.ok : C.bad;
  const arrow = flat ? "·" : v > 0 ? "▲" : "▼";
  return <span className="tnum" style={{ fontSize: size, fontWeight: weight, color: col, letterSpacing: "-0.01em", whiteSpace: "nowrap" }}>
    <span style={{ fontSize: size * 0.72, marginRight: 3 }}>{arrow}</span>{v > 0 ? "+" : ""}{v.toFixed(2)}%
  </span>;
}
function Pill({ children, tone, solid, style, onClick, active }) {
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
function SentBadge({ label, score, sm }) {
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
function HoldDot({ on }) {
  return <span title={on ? "보유" : "미보유"} style={{
    width: 7, height: 7, borderRadius: 999, display: "inline-block",
    background: on ? C.acc : "transparent", border: on ? "none" : `1.5px solid ${C.line2}`,
  }}></span>;
}
function AlignBadge({ on }) {
  return <span style={{ fontSize: 11, fontWeight: 700, color: on ? C.ok : C.ink3 }}>{on ? "정배열" : "—"}</span>;
}

// ---------- composite gauge cell ----------
function CompositeCell({ value, width = 110 }) {
  const col = compColor(value);
  return <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
    <Num size={17} weight={700} color={col} style={{ width: 26, textAlign: "right" }}>{value}</Num>
    <div style={{ flex: 1, height: 6, background: C.surface2, borderRadius: 999, overflow: "hidden", minWidth: width * 0.5 }}>
      <div style={{ width: value + "%", height: "100%", background: col, borderRadius: 999 }}></div>
    </div>
  </div>;
}

// ---------- 5 factor mini bars ----------
function MiniBars({ f, h = 26 }) {
  const order = [["m", "M"], ["v", "V"], ["q", "Q"], ["g", "G"], ["s", "S"]];
  const groupCol = { m: C.ink, v: C.ink2, q: C.ink2, g: C.ink2, s: C.ink };
  return <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: h }}>
    {order.map(([k, lbl]) => {
      const v = f[k];
      const col = v >= 70 ? C.ok : v >= 45 ? C.ink2 : C.ink3;
      return <div key={k} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }} title={lbl + " " + v}>
        <div style={{ width: 7, height: h - 10, background: C.surface2, borderRadius: 2, display: "flex", alignItems: "flex-end", overflow: "hidden" }}>
          <div style={{ width: "100%", height: (v / 100) * (h - 10), background: col, borderRadius: 2 }}></div>
        </div>
        <span className="mono" style={{ fontSize: 8, color: C.ink3, fontWeight: 600 }}>{lbl}</span>
      </div>;
    })}
  </div>;
}

// ---------- large horizontal factor bar (detail / screener) ----------
function FactorBar({ label, value, group, sub, rank }) {
  const col = value >= 70 ? C.ok : value >= 50 ? C.warn : C.ink3;
  const groupLabel = group === "timing" ? "타이밍" : group === "mispricing" ? "미스프라이싱" : null;
  return <div style={{ display: "grid", gridTemplateColumns: "92px 1fr 40px", alignItems: "center", gap: 12, padding: "9px 0" }}>
    <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
      <span style={{ fontSize: 13, fontWeight: 600, color: C.ink }}>{label}</span>
      {groupLabel && <MonoCaps style={{ fontSize: 9 }} color={group === "timing" ? C.acc : C.ink3}>{groupLabel}</MonoCaps>}
    </div>
    <div style={{ height: 9, background: C.surface2, borderRadius: 999, overflow: "hidden" }}>
      <div style={{ width: value + "%", height: "100%", background: col, borderRadius: 999, transition: "width .5s" }}></div>
    </div>
    <Num size={15} weight={700} color={col} style={{ textAlign: "right" }}>{value}</Num>
  </div>;
}

// ---------- SVG sparkline ----------
function Sparkline({ data, color = C.acc, w = 86, h = 26, fill }) {
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

// ---------- SVG price chart with SMA ----------
function PriceChart({ stock, w = 520, h = 240, showSMA = true }) {
  const data = stock.series;
  const pad = { l: 8, r: 52, t: 14, b: 22 };
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
  const min = Math.min(...data), max = Math.max(...data);
  const rng = max - min || 1;
  const x = (i) => pad.l + (i / (data.length - 1)) * iw;
  const y = (v) => pad.t + ih - ((v - min) / rng) * ih;
  const up = data[data.length - 1] >= data[0];
  const col = up ? C.ok : C.bad;
  const line = data.map((d, i) => `${x(i)},${y(d)}`).join(" ");
  const area = `${x(0)},${pad.t + ih} ${line} ${x(data.length - 1)},${pad.t + ih}`;
  // SMA20 running
  const sma = data.map((_, i) => {
    const s = Math.max(0, i - 19); const slc = data.slice(s, i + 1);
    return slc.reduce((a, b) => a + b, 0) / slc.length;
  });
  const smaLine = sma.map((d, i) => `${x(i)},${y(d)}`).join(" ");
  const gid = "g" + stock.t;
  const last = data[data.length - 1];
  // y axis ticks
  const ticks = [max, (max + min) / 2, min];
  const months = ["1월", "2월", "3월", "4월", "5월", "6월"];
  return <svg width={w} height={h} style={{ display: "block", width: "100%" }} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
    <defs>
      <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={col} stopOpacity="0.14" />
        <stop offset="100%" stopColor={col} stopOpacity="0" />
      </linearGradient>
    </defs>
    {ticks.map((tk, i) => <g key={i}>
      <line x1={pad.l} x2={pad.l + iw} y1={y(tk)} y2={y(tk)} stroke={C.line} strokeWidth="1" strokeDasharray={i === 2 ? "" : "3 3"} />
      <text x={pad.l + iw + 6} y={y(tk) + 3} fontSize="10" fill={C.ink3} className="tnum" fontFamily="var(--mono)">{tk > 1000 ? Math.round(tk).toLocaleString() : tk.toFixed(1)}</text>
    </g>)}
    <polygon points={area} fill={`url(#${gid})`} />
    {showSMA && <polyline points={smaLine} fill="none" stroke={C.acc} strokeWidth="1.4" strokeDasharray="4 3" opacity="0.85" />}
    <polyline points={line} fill="none" stroke={col} strokeWidth="2" strokeLinejoin="round" />
    <circle cx={x(data.length - 1)} cy={y(last)} r="3" fill={col} />
    {months.map((m, i) => <text key={m} x={pad.l + (i / 5) * iw} y={h - 6} fontSize="9.5" fill={C.ink3} textAnchor="middle" fontFamily="var(--mono)">{m}</text>)}
  </svg>;
}

// ---------- gauge bar (market breadth) ----------
function GaugeBar({ value, max = 100, tone, suffix }) {
  const col = tone === "ok" ? C.ok : tone === "bad" ? C.bad : tone === "warn" ? C.warn : C.ink2;
  const pct = Math.min(100, (value / max) * 100);
  return <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
    <div style={{ flex: 1, height: 8, background: C.surface2, borderRadius: 999, overflow: "hidden" }}>
      <div style={{ width: pct + "%", height: "100%", background: col, borderRadius: 999 }}></div>
    </div>
    <Num size={15} weight={700} color={col} style={{ width: 48, textAlign: "right" }}>{value}{suffix || ""}</Num>
  </div>;
}

// ---------- 7-day sentiment stack bar ----------
function SentStack({ pos, neu, neg, w = 130 }) {
  const total = pos + neu + neg || 1;
  const seg = (n, c) => n > 0 ? <div style={{ width: (n / total) * 100 + "%", background: c, height: "100%" }} title={n}></div> : null;
  return <div style={{ display: "flex", height: 8, width: w, borderRadius: 999, overflow: "hidden", background: C.surface2 }}>
    {seg(pos, C.ok)}{seg(neu, C.ink3)}{seg(neg, C.bad)}
  </div>;
}

// ---------- regime badge ----------
function RegimeBadge({ regime, lg }) {
  const D = window.ATLAS_DATA.regimes[regime];
  const col = D.color === "acc" ? C.acc : D.color === "warn" ? C.warn : C.bad;
  const bg = D.color === "acc" ? C.accTint : D.color === "warn" ? C.warnBg : C.badBg;
  return <span style={{
    display: "inline-flex", alignItems: "center", gap: 6, padding: lg ? "6px 13px" : "3px 10px",
    borderRadius: 999, background: bg, border: `1px solid ${col}33`, color: col,
    fontSize: lg ? 13 : 11.5, fontWeight: 700, letterSpacing: "-0.01em",
  }}>
    <span style={{ width: 7, height: 7, borderRadius: 999, background: col }}></span>
    {regime === "bull" ? "강세 (Bull)" : regime === "neutral" ? "중립 (Neutral)" : "약세 (Bear)"}
  </span>;
}

// ---------- factor weight bars (regime → weights) ----------
function WeightBars({ w, horizontal }) {
  const items = [["m", "모멘텀", "timing"], ["v", "가치", "mispricing"], ["q", "퀄리티", "mispricing"], ["g", "성장", "mispricing"], ["s", "감성", "timing"]];
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

Object.assign(window, {
  C, fmtPrice, fmtNum, compColor, compBg, sentMeta, flagTone,
  MonoCaps, Num, ChangePct, Pill, SentBadge, HoldDot, AlignBadge,
  CompositeCell, MiniBars, FactorBar, Sparkline, PriceChart, GaugeBar, SentStack, RegimeBadge, WeightBars,
});
