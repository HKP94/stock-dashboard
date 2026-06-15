// ATLAS — dummy data model. Exposes window.ATLAS_DATA
(function () {
  // ---- seeded RNG for deterministic-ish price series ----
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  // generate ~130 trading days (6 months) ending at `last`
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
    // normalize so the final value is exactly `last`
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

  // base table — rich, hand-tuned for the 6 named + supporting names
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
      sum: ["AEC(액티브 전기 케이블) 하이퍼스케일러 채택 확대", "분기 가이던스 큰 폭 상향 — 어닝 서프라이즈", "신규 대형 고객 1곳 추가 확인"],
      cat: [["06.18", "테크 컨퍼런스 발표"], ["07.02", "분기 실적 발표"]] },

    { t: "035420", name: "NAVER", mk: "KR", sec: "인터넷", hold: true, price: 218500, chg: -1.24, cur: "₩",
      comp: 67, f: { m: 58, v: 71, q: 76, g: 54, s: 49 }, rsi: 47.8, align: false,
      flags: ["52주 신고가 -18%"], rank: [4, 38],
      per: 18.6, pbr: 1.12, roe: 8.4, rev: 11.2, fscore: 7, tp: 260000, up: 19.0, rating: "Buy",
      sent: "중립", sscore: 52,
      sum: ["커머스 광고 회복 신호, 그러나 성장 둔화 우려 상존", "AI 검색 '큐:' 트래픽 점진 확대", "일본 라인야후 지분 이슈 불확실성 잔존"],
      cat: [["06.20", "AI 데이터센터 각산 가동"], ["07.10", "2분기 잠정실적"]] },

    { t: "MSFT", name: "마이크로소프트", mk: "US", sec: "소프트웨어", hold: true, price: 478.90, chg: 0.88, cur: "$",
      comp: 79, f: { m: 64, v: 52, q: 94, g: 71, s: 73 }, rsi: 56.1, align: true,
      flags: ["정배열 유지"], rank: [6, 312],
      per: 34.1, pbr: 12.0, roe: 38.9, rev: 17.6, fscore: 9, tp: 540, up: 12.8, rating: "Strong Buy",
      sent: "긍정", sscore: 74,
      sum: ["Azure 성장률 재가속, AI 기여분 확대", "Copilot 기업 좌석 수 견조한 증가", "자본지출 부담 일부 마진 압박 요인"],
      cat: [["06.16", "Build 후속 기능 공개"], ["07.23", "분기 실적 발표"]] },

    { t: "TSLA", name: "테슬라", mk: "US", sec: "자동차", hold: false, price: 246.30, chg: -4.12, cur: "$",
      comp: 48, f: { m: 34, v: 22, q: 58, g: 61, s: 31 }, rsi: 38.4, align: false,
      flags: ["데드크로스 발생", "RSI 과매도 근접"], rank: [188, 412],
      per: 71.2, pbr: 9.4, roe: 14.1, rev: -3.2, fscore: 5, tp: 230, up: -6.6, rating: "Hold",
      sent: "부정", sscore: 28,
      sum: ["인도량 컨센서스 하회, 가격 경쟁 심화", "로보택시 일정 지연 우려 부각", "에너지 저장 부문은 견조한 성장 지속"],
      cat: [["06.22", "로보택시 데이 (예정)"], ["07.18", "인도량/실적 발표"]] },

    { t: "033780", name: "KT&G", mk: "KR", sec: "필수소비재", hold: true, price: 128900, chg: 0.55, cur: "₩",
      comp: 72, f: { m: 49, v: 88, q: 84, g: 41, s: 58 }, rsi: 53.0, align: true,
      flags: ["배당 매력 상위", "저변동성"], rank: [2, 21],
      per: 11.2, pbr: 1.28, roe: 11.6, rev: 6.8, fscore: 8, tp: 145000, up: 12.5, rating: "Buy",
      sent: "중립", sscore: 60,
      sum: ["해외 궐련 수출 호조, 안정적 현금흐름", "배당성향 상향 + 자사주 소각 발표", "건기식 부문 부진은 지속"],
      cat: [["06.27", "주주환원 정책 업데이트"], ["07.28", "2분기 실적"]] },

    { t: "AAPL", name: "애플", mk: "US", sec: "하드웨어", hold: false, price: 224.10, chg: 0.42, cur: "$",
      comp: 70, f: { m: 55, v: 48, q: 92, g: 44, s: 66 }, rsi: 54.2, align: true,
      flags: ["정배열 유지"], rank: [11, 312],
      per: 30.4, pbr: 48.2, roe: 147.0, rev: 4.9, fscore: 8, tp: 245, up: 9.3, rating: "Buy",
      sent: "중립", sscore: 58,
      sum: ["WWDC AI 기능 시장 반응 엇갈림", "서비스 매출 견조, 하드웨어 성장 둔화", "중국 수요 회복 지연"],
      cat: [["06.14", "신규 OS 베타 배포"], ["08.01", "분기 실적"]] },

    { t: "AMD", name: "AMD", mk: "US", sec: "반도체", hold: true, price: 168.40, chg: 2.91, cur: "$",
      comp: 76, f: { m: 81, v: 41, q: 67, g: 84, s: 70 }, rsi: 62.8, align: true,
      flags: ["골든크로스 발생"], rank: [12, 480],
      per: 42.0, pbr: 4.1, roe: 6.8, rev: 22.1, fscore: 7, tp: 195, up: 15.8, rating: "Buy",
      sent: "긍정", sscore: 72,
      sum: ["MI350 AI 가속기 채택 확대 기대", "데이터센터 부문 점유율 상승", "PC향 수요 회복 신호"],
      cat: [["06.19", "AI 행사 신제품 공개"], ["07.29", "분기 실적"]] },

    { t: "AVGO", name: "브로드컴", mk: "US", sec: "반도체", hold: false, price: 184.70, chg: 1.66, cur: "$",
      comp: 82, f: { m: 79, v: 44, q: 86, g: 77, s: 68 }, rsi: 60.1, align: true,
      flags: ["정배열 강세"], rank: [8, 480],
      per: 36.8, pbr: 9.7, roe: 24.5, rev: 43.0, fscore: 8, tp: 210, up: 13.7, rating: "Strong Buy",
      sent: "긍정", sscore: 71,
      sum: ["커스텀 AI 칩(ASIC) 수주 잔고 증가", "VMware 통합 시너지 가시화", "네트워킹 매출 견조"],
      cat: [["06.13", "분기 실적 발표"], ["07.05", "배당 지급"]] },

    { t: "GOOGL", name: "알파벳", mk: "US", sec: "인터넷", hold: true, price: 178.30, chg: 1.12, cur: "$",
      comp: 74, f: { m: 62, v: 67, q: 88, g: 59, s: 64 }, rsi: 55.4, align: true,
      flags: ["정배열 유지"], rank: [9, 312],
      per: 23.6, pbr: 6.8, roe: 32.1, rev: 13.6, fscore: 9, tp: 205, up: 15.0, rating: "Strong Buy",
      sent: "긍정", sscore: 67,
      sum: ["검색 광고 견조 + Gemini 통합 확대", "클라우드 흑자폭 확대", "반독점 소송 리스크 잔존"],
      cat: [["06.17", "Gemini 신모델 공개"], ["07.24", "분기 실적"]] },

    { t: "AMZN", name: "아마존", mk: "US", sec: "인터넷", hold: false, price: 197.80, chg: -0.74, cur: "$",
      comp: 73, f: { m: 60, v: 46, q: 81, g: 72, s: 69 }, rsi: 51.0, align: true,
      flags: ["정배열 유지"], rank: [14, 312],
      per: 41.2, pbr: 7.2, roe: 21.0, rev: 12.5, fscore: 8, tp: 230, up: 16.3, rating: "Buy",
      sent: "긍정", sscore: 65,
      sum: ["AWS 재가속, AI 워크로드 기여 확대", "리테일 마진 개선 지속", "광고 매출 고성장"],
      cat: [["06.24", "프라임 행사"], ["07.31", "분기 실적"]] },

    { t: "META", name: "메타", mk: "US", sec: "인터넷", hold: false, price: 612.40, chg: 2.18, cur: "$",
      comp: 80, f: { m: 78, v: 55, q: 85, g: 70, s: 75 }, rsi: 63.5, align: true,
      flags: ["정배열 강세", "52주 신고가 -3%"], rank: [5, 312],
      per: 27.4, pbr: 8.9, roe: 35.6, rev: 21.9, fscore: 9, tp: 680, up: 11.0, rating: "Strong Buy",
      sent: "긍정", sscore: 76,
      sum: ["광고 단가 상승 + AI 추천 효율 개선", "Llama 생태계 확장", "리얼리티랩스 적자 지속은 부담"],
      cat: [["06.21", "AI 글래스 공개 행사"], ["07.30", "분기 실적"]] },

    { t: "PLTR", name: "팔란티어", mk: "US", sec: "소프트웨어", hold: false, price: 28.65, chg: -2.34, cur: "$",
      comp: 58, f: { m: 72, v: 14, q: 60, g: 88, s: 47 }, rsi: 58.9, align: true,
      flags: ["고밸류 경계"], rank: [44, 312],
      per: 98.0, pbr: 18.4, roe: 12.7, rev: 30.5, fscore: 6, tp: 26, up: -9.2, rating: "Hold",
      sent: "중립", sscore: 44,
      sum: ["정부·상업 부문 모두 두 자릿수 성장", "밸류에이션 부담 지속 — 변동성 확대", "AIP 부트캠프 전환율 양호"],
      cat: [["06.26", "정부 계약 갱신"], ["08.04", "분기 실적"]] },

    { t: "005930", name: "삼성전자", mk: "KR", sec: "반도체", hold: true, price: 81200, chg: 1.50, cur: "₩",
      comp: 69, f: { m: 57, v: 74, q: 72, g: 51, s: 62 }, rsi: 54.6, align: true,
      flags: ["골든크로스 임박", "HBM 모멘텀"], rank: [1, 38],
      per: 13.8, pbr: 1.42, roe: 9.1, rev: 18.4, fscore: 7, tp: 95000, up: 17.0, rating: "Buy",
      sent: "긍정", sscore: 66,
      sum: ["HBM3E 엔비디아 퀄 통과 기대감 부각", "메모리 업황 회복 사이클 진입", "파운드리 적자 축소 과제"],
      cat: [["06.28", "HBM 공급 계약 발표"], ["07.08", "2분기 잠정실적"]] },

    { t: "000660", name: "SK하이닉스", mk: "KR", sec: "반도체", hold: true, price: 214500, chg: 2.63, cur: "₩",
      comp: 83, f: { m: 90, v: 49, q: 71, g: 86, s: 78 }, rsi: 66.7, align: true,
      flags: ["정배열 강세", "HBM 독점 수혜"], rank: [1, 38],
      per: 11.4, pbr: 2.61, roe: 24.8, rev: 64.2, fscore: 8, tp: 260000, up: 21.2, rating: "Strong Buy",
      sent: "긍정", sscore: 84,
      sum: ["HBM 시장 선도, 내년 물량 완판 임박", "메모리 가격 상승 사이클 수혜 극대화", "고대역폭 메모리 기술 격차 유지"],
      cat: [["06.15", "신규 HBM 라인 증설"], ["07.25", "2분기 실적"]] },

    { t: "035720", name: "카카오", mk: "KR", sec: "인터넷", hold: false, price: 41850, chg: -1.88, cur: "₩",
      comp: 44, f: { m: 31, v: 52, q: 48, g: 39, s: 35 }, rsi: 41.2, align: false,
      flags: ["데드크로스 유지", "추세 약세"], rank: [22, 38],
      per: 36.4, pbr: 1.18, roe: 3.2, rev: 4.1, fscore: 4, tp: 48000, up: 14.7, rating: "Hold",
      sent: "부정", sscore: 33,
      sum: ["본업 광고·커머스 회복 더딤", "사법 리스크 관련 불확실성 지속", "AI 신규 서비스 수익화는 초기 단계"],
      cat: [["06.23", "신규 AI 서비스 출시"], ["08.07", "2분기 실적"]] },

    { t: "051910", name: "LG화학", mk: "KR", sec: "소재", hold: false, price: 312000, chg: -2.95, cur: "₩",
      comp: 41, f: { m: 26, v: 63, q: 55, g: 24, s: 38 }, rsi: 36.8, align: false,
      flags: ["RSI 과매도 근접", "추세 약세"], rank: [29, 38],
      per: 22.1, pbr: 0.92, roe: 4.6, rev: -8.4, fscore: 5, tp: 360000, up: 15.4, rating: "Hold",
      sent: "부정", sscore: 31,
      sum: ["전지소재 수요 둔화, 메탈가 하락 지속", "석유화학 업황 부진 장기화", "양극재 출하 회복은 하반기 기대"],
      cat: [["06.30", "배터리데이 행사"], ["07.26", "2분기 실적"]] },

    { t: "247540", name: "에코프로비엠", mk: "KR", sec: "소재", hold: false, price: 142300, chg: 4.77, cur: "₩",
      comp: 55, f: { m: 68, v: 19, q: 44, g: 72, s: 51 }, rsi: 64.1, align: false,
      flags: ["골든크로스 임박", "거래량 급증"], rank: [12, 38],
      per: 55.6, pbr: 3.8, roe: 7.1, rev: -12.0, fscore: 4, tp: 155000, up: 8.9, rating: "Hold",
      sent: "중립", sscore: 48,
      sum: ["양극재 단가 바닥 통과 기대감 반등", "고객사 재고조정 마무리 국면", "여전히 높은 밸류·실적 변동성"],
      cat: [["06.29", "신규 수주 공시"], ["08.05", "2분기 실적"]] },
  ];

  // derive series + sparklines + sma + 이격도
  const stocks = base.map((s, i) => {
    const drift = (s.comp - 50) / 9000; // higher composite → mild uptrend bias
    const vol = s.mk === "KR" ? 0.018 : 0.022;
    const series = genSeries(1000 + i * 37, s.price, drift, vol);
    const sma = (arr, w, idx) => {
      const start = Math.max(0, idx - w + 1);
      const slc = arr.slice(start, idx + 1);
      return slc.reduce((a, b) => a + b, 0) / slc.length;
    };
    const last = series.length - 1;
    const sma20 = +sma(series, 20, last).toFixed(s.price > 1000 ? 0 : 2);
    const sma50 = +sma(series, 50, last).toFixed(s.price > 1000 ? 0 : 2);
    const sma200 = +sma(series, 130, last).toFixed(s.price > 1000 ? 0 : 2); // proxy w/ available window
    const disparity = +((s.price / sma20) * 100).toFixed(1); // 20일 이격도
    return {
      ...s,
      series,
      sma20, sma50, sma200, disparity,
      compHist: spark(7000 + i * 13, s.comp - 6, 5),
      momHist: spark(9000 + i * 17, s.f.m - 8, 6),
      slope: +(((series[last] - series[last - 20]) / series[last - 20]) * 100).toFixed(1),
    };
  });

  // ---- news feed ----
  const news = [
    { t: "NVDA", sent: "긍정", time: "18분 전", src: "Reuters", high: "엔비디아, 데이터센터 매출 전분기比 28% 급증… 컨센서스 상회", body: "Blackwell 양산이 본격화되며 공급이 수요를 따라가지 못하는 상황이 지속되고 있다. 주요 하이퍼스케일러들이 CapEx 가이던스를 상향했다.", hot: true },
    { t: "000660", sent: "긍정", time: "42분 전", src: "한국경제", high: "SK하이닉스, 내년 HBM 물량 사실상 완판 임박", body: "고대역폭 메모리 시장 선도 지위를 바탕으로 내년 출하 물량 대부분이 선계약된 것으로 파악된다.", hot: true },
    { t: "CRDO", sent: "긍정", time: "1시간 전", src: "Bloomberg", high: "크레도, 분기 가이던스 대폭 상향… 어닝 서프라이즈", body: "AEC 제품의 하이퍼스케일러 채택이 빠르게 확대되며 신규 대형 고객이 추가됐다.", hot: true },
    { t: "TSLA", sent: "부정", time: "1시간 전", src: "CNBC", high: "테슬라 인도량 컨센서스 하회… 로보택시 일정 지연 우려", body: "가격 경쟁 심화로 마진 압박이 이어지는 가운데 로보택시 상용화 일정에 대한 불확실성이 부각됐다.", hot: true },
    { t: "035420", sent: "중립", time: "2시간 전", src: "전자신문", high: "네이버, AI 검색 '큐:' 트래픽 점진 확대… 성장 둔화 우려는 상존", body: "커머스 광고가 회복 신호를 보이고 있으나 전반적 성장 둔화 우려가 주가의 발목을 잡고 있다.", hot: false },
    { t: "005930", sent: "긍정", time: "2시간 전", src: "조선비즈", high: "삼성전자, HBM3E 엔비디아 품질 인증 통과 기대감 부각", body: "메모리 업황 회복 사이클 진입과 맞물려 HBM 모멘텀이 재차 부각되고 있다.", hot: false },
    { t: "MSFT", sent: "긍정", time: "3시간 전", src: "The Verge", high: "마이크로소프트 Azure 성장률 재가속, AI 기여분 확대", body: "Copilot 기업 좌석 수가 견조하게 늘며 클라우드 매출 성장을 견인하고 있다.", hot: false },
    { t: "META", sent: "긍정", time: "3시간 전", src: "Reuters", high: "메타, 광고 단가 상승에 신고가 근접… AI 추천 효율 개선", body: "AI 기반 추천 알고리즘 효율 개선이 광고 실적을 끌어올리고 있다.", hot: false },
    { t: "AMD", sent: "긍정", time: "4시간 전", src: "Tom's Hardware", high: "AMD, MI350 AI 가속기 채택 확대 기대… 골든크로스 발생", body: "데이터센터 부문 점유율 상승과 함께 기술적 반등 신호가 포착됐다.", hot: false },
    { t: "035720", sent: "부정", time: "4시간 전", src: "머니투데이", high: "카카오, 본업 회복 더디고 사법 리스크 지속", body: "광고·커머스 회복이 더딘 가운데 관련 불확실성이 투자심리를 압박하고 있다.", hot: false },
    { t: "GOOGL", sent: "긍정", time: "5시간 전", src: "Bloomberg", high: "알파벳, Gemini 통합 확대… 클라우드 흑자폭 개선", body: "검색 광고가 견조한 가운데 클라우드 부문의 수익성이 빠르게 개선되고 있다.", hot: false },
    { t: "051910", sent: "부정", time: "5시간 전", src: "이데일리", high: "LG화학, 전지소재 수요 둔화·메탈가 하락에 약세 지속", body: "석유화학 업황 부진이 장기화되며 실적 회복이 하반기로 미뤄지고 있다.", hot: false },
    { t: "AAPL", sent: "중립", time: "6시간 전", src: "9to5Mac", high: "애플 WWDC AI 기능에 시장 반응 엇갈려", body: "서비스 매출은 견조하나 하드웨어 성장 둔화와 중국 수요 회복 지연이 부담이다.", hot: false },
    { t: "033780", sent: "중립", time: "6시간 전", src: "한국경제", high: "KT&G, 배당성향 상향 + 자사주 소각 발표", body: "해외 궐련 수출 호조로 안정적 현금흐름을 바탕으로 주주환원을 강화한다.", hot: false },
    { t: "247540", sent: "중립", time: "7시간 전", src: "서울경제", high: "에코프로비엠, 양극재 단가 바닥 통과 기대에 반등", body: "고객사 재고조정이 마무리 국면에 접어들며 거래량이 급증했다.", hot: false },
    { t: "AMZN", sent: "긍정", time: "8시간 전", src: "CNBC", high: "아마존 AWS 재가속, AI 워크로드 기여 확대", body: "리테일 마진 개선과 고성장 광고 매출이 실적을 뒷받침하고 있다.", hot: false },
    { t: "PLTR", sent: "중립", time: "9시간 전", src: "Barron's", high: "팔란티어, 두 자릿수 성장에도 밸류 부담에 변동성 확대", body: "정부·상업 부문 모두 견조하나 높은 밸류에이션이 주가 변동성을 키우고 있다.", hot: false },
    { t: "TSLA", sent: "중립", time: "10시간 전", src: "Electrek", high: "테슬라 에너지 저장 부문은 견조한 성장 지속", body: "차량 부문 부진을 에너지 저장 사업이 일부 상쇄하고 있다.", hot: false },
  ];

  // ---- market ----
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
      summary: "코스피는 외국인 순매수 전환과 반도체 업황 회복 기대에 완만한 상승 흐름을 보이고 있으나, 코스닥은 중소형 성장주 약세로 부진하다. 시장폭은 중립 수준에서 횡보 중이며, 환율 부담이 지수의 상단을 제한하는 국면이다. 반도체(HBM) 중심의 차별화 장세가 이어질 가능성이 높다.",
    },
    us: {
      regime: "bull",
      idx: [{ k: "S&P 500", v: "5,431.60", chg: 0.74 }, { k: "NASDAQ", v: "17,688.88", chg: 1.05 }],
      gauges: [
        { label: "200일선 위 종목 비율", v: 71, unit: "%", tone: "ok" },
        { label: "52주 신고가 비율", v: 34, unit: "%", tone: "ok" },
        { label: "VIX (변동성)", v: 13.4, unit: "", tone: "ok", inv: true },
      ],
      summary: "미국 증시는 AI 자본지출 사이클과 견조한 고용·소비를 바탕으로 강세 국면을 유지하고 있다. 시장폭이 건강하게 확대되고 있으며, VIX가 낮은 수준에 머물러 위험선호가 우세하다. 다만 일부 메가캡 쏠림과 높은 밸류에이션은 변동성 확대 시 되돌림 위험 요인이다.",
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

  // research notes mock
  const research = {
    files: {
      NVDA: [
        { name: "NVDA_DataCenter_Deep_Dive.pdf", date: "2026.06.10", type: "pdf" },
        { name: "Blackwell_supply_notes.md", date: "2026.06.04", type: "md" },
        { name: "valuation_model_v3.pdf", date: "2026.05.22", type: "pdf" },
      ],
      "000660": [
        { name: "HBM_경쟁구도_분석.pdf", date: "2026.06.12", type: "pdf" },
        { name: "메모리_사이클_메모.md", date: "2026.06.01", type: "md" },
      ],
      "035420": [
        { name: "NAVER_커머스_광고_트렌드.pdf", date: "2026.05.30", type: "pdf" },
      ],
    },
    notes: {
      NVDA: "데이터센터 매출 모멘텀은 여전히 강력하나 밸류에이션이 historically 높은 구간. RSI 71로 과열 신호 — 분할 비중 축소 후 조정 시 재매수 전략 유효. Blackwell 공급 부족이 핵심 변수.",
      "000660": "HBM 독점적 지위 + 메모리 업사이클 진입 = 구조적 강세. 밸류 부담 낮고 컨센서스 목표가 상향 여력. 장기 보유 코어 포지션 유지.",
      "035420": "기술적으로는 약세이나 밸류·퀄리티는 양호. 성장 둔화 우려 해소 전까지는 관망. 목표가 26만원.",
    },
    tags: ["매수후보", "관망", "리스크주의", "장기보유", "분할매수", "비중축소"],
    activeTags: {
      NVDA: ["비중축소", "리스크주의"],
      "000660": ["매수후보", "장기보유"],
      "035420": ["관망"],
    },
  };

  window.ATLAS_DATA = { stocks, news, market, regimes, factorMeta, research,
    today: "2026년 6월 14일 (토)", updated: "06:42 KST" };
})();
