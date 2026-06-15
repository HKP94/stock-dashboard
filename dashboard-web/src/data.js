// ATLAS — data loader
// data.json이 있으면 그걸 쓰고, 없으면 원본 mock 데이터를 fallback으로 사용한다.
// export_dashboard_data.py가 dashboard-web/src/data.json 을 생성한다.

// data.json이 있으면 import, 없으면 아래 mock fallback 사용
let atlasData = null;
try {
  // Vite는 JSON import를 기본 지원 (assert 구문 불필요)
  const { default: jsonData } = await import('./data.json');
  if (jsonData && jsonData.stocks && jsonData.stocks.length > 0) {
    atlasData = jsonData;
  }
} catch (_) {
  atlasData = null;
}

if (!atlasData) {
  // ---- seeded RNG for deterministic-ish price series ----
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function genSeries(seed, last, drift, vol) {
    const rnd = mulberry32(seed);
    const n = 130;
    const arr = new Array(n);
    let p = last;
    for (let i = n - 1; i >= 0; i--) {
      arr[i] = p;
      const shock = (rnd() - 0.5) * 2 * vol;
      p = p / (1 + drift + shock);
    }
    const k = last / arr[n - 1];
    for (let i = 0; i < n; i++) arr[i] = +(arr[i] * k).toFixed(arr[i] > 1000 ? 0 : 2);
    return arr;
  }
  function spark(seed, base, swing) {
    const rnd = mulberry32(seed);
    const out = [];
    let v = base;
    for (let i = 0; i < 16; i++) { v += (rnd() - 0.45) * swing; v = Math.max(0, Math.min(100, v)); out.push(+v.toFixed(0)); }
    return out;
  }

  const base = [
    { t: "NVDA", name: "엔비디아", mk: "US", sec: "반도체", hold: true, price: 1284.50, chg: 3.42, cur: "$",
      comp: 91, f: { m: 96, v: 38, q: 88, g: 97, s: 86 }, rsi: 71.4, align: true,
      flags: ["RSI 과열", "정배열 강세"], rank: [3, 480],
      per: 38.2, pbr: 21.4, roe: 91.3, rev: 122.4, fscore: 8, tp: 1450, up: 12.9, rating: "Strong Buy",
      sent: "긍정", sscore: 88,
      sum: ["데이터센터 매출 전분기 대비 28% 증가, 컨센서스 상회", "Blackwell 양산 가속 — 공급 부족 지속 전망", "주요 클라우드 4사 CapEx 가이던스 상향"],
      cat: [["06.12", "차세대 GB300 로드맵 공개 예정"], ["06.25", "분기 실적 발표"]] },
    { t: "CRDO", name: "크레도 테크", mk: "US", sec: "반도체", hold: true, price: 71.28, chg: 6.81, cur: "$",
      comp: 84, f: { m: 93, v: 31, q: 64, g: 95, s: 79 }, rsi: 68.2, align: true,
      flags: ["골든크로스 임박", "거래량 급증"], rank: [19, 480],
      per: 64.5, pbr: 12.8, roe: 18.2, rev: 154.0, fscore: 7, tp: 85, up: 19.2, rating: "Buy",
      sent: "긍정", sscore: 81,
      sum: ["AEC 하이퍼스케일러 채택 확대", "분기 가이던스 큰 폭 상향", "신규 대형 고객 1곳 추가 확인"],
      cat: [["06.18", "테크 컨퍼런스 발표"], ["07.02", "분기 실적 발표"]] },
    { t: "035420", name: "NAVER", mk: "KR", sec: "인터넷", hold: true, price: 218500, chg: -1.24, cur: "₩",
      comp: 67, f: { m: 58, v: 71, q: 76, g: 54, s: 49 }, rsi: 47.8, align: false,
      flags: ["52주 신고가 -18%"], rank: [4, 38],
      per: 18.6, pbr: 1.12, roe: 8.4, rev: 11.2, fscore: 7, tp: 260000, up: 19.0, rating: "Buy",
      sent: "중립", sscore: 52, sum: ["커머스 광고 회복 신호", "AI 검색 '큐:' 트래픽 점진 확대"],
      cat: [["06.20", "AI 데이터센터 각산 가동"], ["07.10", "2분기 잠정실적"]] },
    { t: "MSFT", name: "마이크로소프트", mk: "US", sec: "소프트웨어", hold: true, price: 478.90, chg: 0.88, cur: "$",
      comp: 79, f: { m: 64, v: 52, q: 94, g: 71, s: 73 }, rsi: 56.1, align: true,
      flags: ["정배열 유지"], rank: [6, 312],
      per: 34.1, pbr: 12.0, roe: 38.9, rev: 17.6, fscore: 9, tp: 540, up: 12.8, rating: "Strong Buy",
      sent: "긍정", sscore: 74, sum: ["Azure 성장률 재가속", "Copilot 기업 좌석 수 견조"], cat: [] },
    { t: "TSLA", name: "테슬라", mk: "US", sec: "자동차", hold: false, price: 246.30, chg: -4.12, cur: "$",
      comp: 48, f: { m: 34, v: 22, q: 58, g: 61, s: 31 }, rsi: 38.4, align: false,
      flags: ["데드크로스 발생", "RSI 과매도 근접"], rank: [188, 412],
      per: 71.2, pbr: 9.4, roe: 14.1, rev: -3.2, fscore: 5, tp: 230, up: -6.6, rating: "Hold",
      sent: "부정", sscore: 28, sum: ["인도량 컨센서스 하회", "로보택시 일정 지연"], cat: [] },
    { t: "033780", name: "KT&G", mk: "KR", sec: "필수소비재", hold: true, price: 128900, chg: 0.55, cur: "₩",
      comp: 72, f: { m: 49, v: 88, q: 84, g: 41, s: 58 }, rsi: 53.0, align: true,
      flags: ["배당 매력 상위", "저변동성"], rank: [2, 21],
      per: 11.2, pbr: 1.28, roe: 11.6, rev: 6.8, fscore: 8, tp: 145000, up: 12.5, rating: "Buy",
      sent: "중립", sscore: 60, sum: ["해외 궐련 수출 호조", "배당성향 상향"], cat: [] },
  ];

  const stocks = base.map((s, i) => {
    const drift = (s.comp - 50) / 9000;
    const vol = s.mk === "KR" ? 0.018 : 0.022;
    const series = genSeries(1000 + i * 37, s.price, drift, vol);
    const sma = (arr, w, idx) => { const start = Math.max(0, idx - w + 1); const slc = arr.slice(start, idx + 1); return slc.reduce((a, b) => a + b, 0) / slc.length; };
    const last = series.length - 1;
    return { ...s, series,
      sma20: +sma(series, 20, last).toFixed(s.price > 1000 ? 0 : 2),
      sma50: +sma(series, 50, last).toFixed(s.price > 1000 ? 0 : 2),
      sma200: +sma(series, 130, last).toFixed(s.price > 1000 ? 0 : 2),
      disparity: +((s.price / sma(series, 20, last)) * 100).toFixed(1),
      compHist: spark(7000 + i * 13, s.comp - 6, 5),
      momHist: spark(9000 + i * 17, s.f.m - 8, 6),
      slope: +(((series[last] - series[last - 20]) / series[last - 20]) * 100).toFixed(1),
    };
  });

  const news = [
    { t: "NVDA", sent: "긍정", time: "18분 전", src: "Reuters", high: "엔비디아, 데이터센터 매출 전분기比 28% 급증", body: "Blackwell 양산이 본격화되며 공급이 수요를 따라가지 못하는 상황이 지속되고 있다.", hot: true },
    { t: "CRDO", sent: "긍정", time: "1시간 전", src: "Bloomberg", high: "크레도, 분기 가이던스 대폭 상향", body: "AEC 제품의 하이퍼스케일러 채택이 빠르게 확대되며 신규 대형 고객이 추가됐다.", hot: true },
    { t: "TSLA", sent: "부정", time: "1시간 전", src: "CNBC", high: "테슬라 인도량 컨센서스 하회", body: "가격 경쟁 심화로 마진 압박이 이어지고 있다.", hot: true },
    { t: "035420", sent: "중립", time: "2시간 전", src: "전자신문", high: "네이버, AI 검색 '큐:' 트래픽 점진 확대", body: "커머스 광고가 회복 신호를 보이고 있으나 성장 둔화 우려가 잔존한다.", hot: false },
    { t: "MSFT", sent: "긍정", time: "3시간 전", src: "The Verge", high: "Azure 성장률 재가속", body: "Copilot 기업 좌석 수가 견조하게 늘며 클라우드 매출 성장을 견인하고 있다.", hot: false },
    { t: "033780", sent: "중립", time: "6시간 전", src: "한국경제", high: "KT&G, 배당성향 상향 + 자사주 소각 발표", body: "해외 궐련 수출 호조로 안정적 현금흐름을 바탕으로 주주환원을 강화한다.", hot: false },
  ];

  const market = {
    overall: "neutral",
    indices: [
      { k: "KOSPI", v: "2,742.18", chg: 0.62, mk: "KR" },
      { k: "KOSDAQ", v: "847.36", chg: -0.38, mk: "KR" },
      { k: "S&P 500", v: "5,431.60", chg: 0.74, mk: "US" },
      { k: "NASDAQ", v: "17,688.88", chg: 1.05, mk: "US" },
      { k: "VIX", v: "13.42", chg: -3.21, mk: "US", inv: true },
      { k: "USD/KRW", v: "1,374.50", chg: 0.28, mk: "KR", inv: true },
    ],
    kr: {
      regime: "neutral",
      idx: [{ k: "KOSPI", v: "2,742.18", chg: 0.62 }, { k: "KOSDAQ", v: "847.36", chg: -0.38 }],
      gauges: [
        { label: "200일선 위 종목 비율", v: 54, unit: "%", tone: "warn" },
        { label: "52주 신고가 비율", v: 18, unit: "%", tone: "warn" },
        { label: "KOSPI RSI(14)", v: 52, unit: "", tone: "neutral" },
      ],
      summary: "코스피는 외국인 순매수 전환과 반도체 업황 회복 기대에 완만한 상승 흐름을 보이고 있으나 코스닥은 부진하다.",
      regimeBasis: "KOSPI 200일선 위, VIX 안정 → 중립 레짐, 모멘텀 가중 35%",
    },
    us: {
      regime: "bull",
      idx: [{ k: "S&P 500", v: "5,431.60", chg: 0.74 }, { k: "NASDAQ", v: "17,688.88", chg: 1.05 }],
      gauges: [
        { label: "200일선 위 종목 비율", v: 71, unit: "%", tone: "ok" },
        { label: "52주 신고가 비율", v: 34, unit: "%", tone: "ok" },
        { label: "VIX (변동성)", v: 13.4, unit: "", tone: "ok", inv: true },
      ],
      summary: "미국 증시는 AI 자본지출 사이클과 견조한 고용·소비를 바탕으로 강세 국면을 유지하고 있다.",
      regimeBasis: "S&P500/NASDAQ 200일선 위, VIX 13.4(안정) → 강세 레짐, 모멘텀 가중 45%",
    },
  };

  const regimes = {
    bull: { label: "강세", color: "acc", w: { m: 45, v: 20, q: 20, g: 10, s: 5 } },
    neutral: { label: "중립", color: "warn", w: { m: 35, v: 25, q: 25, g: 10, s: 5 } },
    bear: { label: "약세", color: "bad", w: { m: 10, v: 35, q: 45, g: 5, s: 5 } },
  };

  const factorMeta = {
    m: { key: "momentum", ko: "모멘텀", group: "timing" },
    v: { key: "value", ko: "가치", group: "mispricing" },
    q: { key: "quality", ko: "퀄리티", group: "mispricing" },
    g: { key: "growth", ko: "성장", group: "mispricing" },
    s: { key: "sentiment", ko: "감성", group: "timing" },
  };

  const research = {
    files: {
      NVDA: [
        { name: "NVDA_DataCenter_Deep_Dive.pdf", date: "2026.06.10", type: "pdf" },
        { name: "Blackwell_supply_notes.md", date: "2026.06.04", type: "md" },
      ],
    },
    notes: { NVDA: "데이터센터 매출 모멘텀은 강력하나 밸류에이션이 높은 구간." },
    tags: ["매수후보", "관망", "리스크주의", "장기보유", "분할매수", "비중축소"],
    activeTags: { NVDA: ["비중축소", "리스크주의"] },
  };

  const now = new Date();
  atlasData = {
    stocks, news, market, regimes, factorMeta, research,
    today: now.toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric", weekday: "short" }),
    updated: now.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }) + " KST",
    rulesCount: stocks.reduce((n, s) => n + s.flags.length, 0),
  };
}

export default atlasData;
