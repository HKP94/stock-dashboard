# ATLAS 대시보드 (React/Vite)

ATLAS 관심종목·시장·포트폴리오·전략을 한 화면에서 보는 메인 대시보드.
DB 데이터는 `src/export_dashboard_data.py`가 `src/data.json`으로 내보내고, React가 빌드타임에 import 한다.
포트폴리오·투자판단 쓰기는 로컬 API(FastAPI, 127.0.0.1:8765)를 통한다.

> 표시 신호는 근거·신뢰도를 포함하며 자동 주문을 실행하지 않습니다. 과거 성과는 미래를 보장하지 않습니다.

## 실행 (두 프로세스)

```bash
# 0) (최초 1회) 데이터 생성 — DB 접속정보는 .env 또는 .streamlit/secrets.toml
python -m src.export_dashboard_data

# ── 터미널 1: 로컬 쓰기 API (포트폴리오·투자판단 저장용) ──
python -m src.local_api          # http://127.0.0.1:8765

# ── 터미널 2: React dev 서버 ──
cd dashboard-web && npm install && npm run dev   # http://localhost:5173
```

### 한 번에 띄우기 (선택)
```bash
npx concurrently -n api,web -c blue,green \
  "python -m src.local_api" \
  "cd dashboard-web && npm run dev"
```

접속: **http://localhost:5173**

## 탭
오버뷰 · 종목 상세 · 뉴스 · 스크리너 · 시장 전망 · 리서치 노트 · 포트폴리오 · **전략 비교**

- **전략 비교**: ① 모멘텀 백테스트(실제 — recharts 누적수익 차트 + 메트릭) ② 팩터별 회고(참고용 · 백테스트 아님 — 선정시점편향 경고). 데이터는 `python -m src.backtest` → `python -m src.export_dashboard_data` 순으로 생성.

## 데이터 갱신 순서
```bash
python -m src.run_pipeline          # 전체 (수집→연산→LLM→포트폴리오→백테스트)
# 또는 부분:
python -m src.ingest_news           # 뉴스(+Google News RSS, _MARKET_* 시황뉴스)
python -m src.enrich_gemini         # 뉴스요약 + KR/US 분리 시황 (GEMINI_API_KEY 필요)
python -m src.backtest              # 백테스트 + 회고 → backtest_results
python -m src.export_dashboard_data # → data.json (Vite HMR로 반영)
```

DB 접속: `DB_*` 환경변수 또는 `.streamlit/secrets.toml`. 시크릿은 절대 커밋 금지.
