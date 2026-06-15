# ATLAS 대시보드 (Streamlit) — 레거시

> ⚠️ **메인 대시보드는 `dashboard-web/` (React/Vite)** 입니다.
> `dashboard/app.py`는 레거시로, 유지보수하지 않습니다.

> 투자 자문 아님 / 원금 손실 가능

## 관리 도구: watchlist_admin.py

SQL 없이 watchlist 테이블을 관리하는 **별도 관리 도구** (메인 React 대시보드와 독립 실행).

```bash
# 리포 루트에서 실행 (필요할 때만)
streamlit run dashboard/watchlist_admin.py
```

기능:
- 현재 watchlist 표시 (ticker/name/market/sector/is_holding/active)
- 종목 추가 폼 (ticker·name·market·sector 입력 → INSERT)
- `active` 토글 — 삭제 대신 비활성화 (이력 보존)
- `is_holding` 토글

접속 정보는 `.streamlit/secrets.toml` 또는 환경변수 `DB_*`를 사용합니다 (아래 참고).

## 화면 구성
- **상단**: ATLAS 타이틀 + 날짜 + 레짐 배지(bull/neutral/bear) + 면책
- **시장 스트립**: KOSPI/KOSDAQ/S&P500/NASDAQ/VIX/USD-KRW 카드
- **관심종목 표**: composite 내림차순, 시장·보유 필터, 팩터(M/V/Q/G/S)·RSI·플래그
  - composite 색상: ≥70 초록 / 55–69 노랑 / <55 회색 / 사전필터 대상은 "필터제외"
- **드릴다운**: 종목 선택 → 6개월 가격 차트, 밸류에이션·재무·컨센서스 표, 뉴스 요약, 팩터 레이더

## 로컬 실행

```bash
# 1) 의존성 설치 (리포 루트에서)
pip install -r requirements.txt

# 2) DB 접속 정보 제공 — 방법 A 또는 B 중 하나

# 방법 A) 환경변수
export DB_HOST=aws-1-ap-northeast-2.pooler.supabase.com
export DB_PORT=6543
export DB_USER=postgres.<project_ref>
export DB_PASSWORD=<your_password>
export DB_NAME=postgres

# 3) 실행 (리포 루트에서)
streamlit run dashboard/app.py
```

### 방법 B) `.streamlit/secrets.toml`
리포 루트(또는 `dashboard/`)에 `.streamlit/secrets.toml` 생성:

```toml
DB_HOST = "aws-1-ap-northeast-2.pooler.supabase.com"
DB_PORT = "6543"
DB_USER = "postgres.<project_ref>"
DB_PASSWORD = "<your_password>"
DB_NAME = "postgres"
```

> `secrets.toml`은 비밀이다 — **반드시 `.gitignore`에 포함**하고 커밋하지 말 것.
> 앱은 secrets의 `DB_*` 키를 환경변수로 옮긴 뒤 `src.db.get_conn()`으로 접속한다.

## 데이터가 비어 보일 때
- 종목 표가 비면: 일일 파이프라인(`python -m src.run_pipeline`) 또는
  백필(`python -m src.backfill`)을 먼저 실행해 `prices_daily`/`quant_scores`를 채운다.
- 레짐 배지가 "미상"이면: yfinance 시장 지수 조회 실패(네트워크/레이트리밋). 잠시 후 새로고침.

## 캐시
DB 조회는 `@st.cache_data(ttl=600)`로 10분 캐시된다. 최신 데이터를 보려면
브라우저에서 **"Rerun"** 또는 우상단 메뉴 → **"Clear cache"**.

## 비고
- **로컬 실행 우선**. 클라우드 배포는 추후 다룬다(공개 배포 시 DB 비밀번호·종목 보유정보 노출 주의).
- 개인정보: 보유여부(⭐)는 개인 포트폴리오 정보이므로 화면 공유·스크린샷 시 유의.
