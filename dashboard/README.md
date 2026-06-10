# ATLAS 대시보드 (Streamlit)

관심종목의 퀀트 점수·시장 상황·뉴스 감성을 한 화면에서 보는 **로컬 우선** 대시보드.
DB(Postgres)에 적재된 데이터를 **읽기만** 한다(쓰기·주문 없음).

> ⚠️ 본 화면은 정보·정량 분석 참고용이며 투자 자문이 아닙니다. 원금 손실이 발생할 수 있습니다.

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
