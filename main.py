import os
import json
import time
import warnings
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np
import yfinance as yf
import pandas_ta as ta
from google import genai
from google.genai import types
import gspread
from google.oauth2.service_account import Credentials
from ddgs import DDGS

# 시스템 경고 숨기기
warnings.filterwarnings('ignore')

print("🚀 주식 분석 자동화 파이프라인 시작 (추세 기울기 포함 정배열 로직 적용)...\n")

# ==========================================
# 1. 환경 변수 및 API 설정
# ==========================================
gemini_api_key = os.environ.get('GEMINI_API_KEY')
gcp_json_str = os.environ.get('GCP_SERVICE_ACCOUNT')

if not gemini_api_key or not gcp_json_str:
    raise ValueError("❌ 환경 변수(GEMINI_API_KEY 또는 GCP_SERVICE_ACCOUNT)가 설정되지 않았습니다.")

client = genai.Client(api_key=gemini_api_key)
target_model = 'gemini-3.1-flash-lite'

print(f"✅ AI 모델 세팅 완료: {target_model}")

# ==========================================
# 2. 분석 대상 종목 세팅
# ==========================================
tickers = [
    'AAPL', 'MSFT', 'NVDA', 'TSM', 'ALB', 'XOM', 'SLB','CELH', 'BBW', 'SMR', 'ASML', 'HSY', 'RCL', 'GOOG', 'WM', 'VRT', 'CRDO', 'META', 'TSLA', 'LITE', 'BE',
    '035420.KS', '021240.KS', '033780.KS', '213420.KS', '034220.KS', '059090.KS', '338220.KS', 'BA', 'FUTU', 'ELV', '373220.KS', 'SPCE', '047050.KS' 
]

ticker_to_name = {
    'AAPL': '애플', 'MSFT': '마이크로소프트', 'NVDA': '엔비디아', 'TSM': 'TSMC', 'ALB': '앨버말',
    'XOM': '엑슨모빌', 'SLB': '슐럼버거', 'CELH': '셀시어스', 'BBW': '빌드어베어', 'SMR': '뉴스케일파워',
    'ASML': 'ASML', 'HSY': '허쉬', 'RCL': '로열캐리비안', 'GOOG': '알파벳(구글)', 'WM': '웨이스트매니지먼트',
    'VRT': '버티브', 'CRDO': '크레도테크', 'META': '메타', 'TSLA': '테슬라', 'LITE': '루멘텀', 'BE': '블룸에너지',
    '035420.KS': '네이버', '021240.KS': '코웨이', '033780.KS': 'KT&G',
    '213420.KS': '덕산네오룩스', '034220.KS': 'LG디스플레이', '059090.KS': '미코', '338220.KS': '뷰노',
    'BA': '보잉', 'FUTU': '푸투', 'ELV': '앤섬', '373220.KS': 'LG에너지솔루션', 'SPCE' : '버진갤럭틱', '047050.KS' : '포스코인터네셔널'
}

# ==========================================
# 3. 데이터 수집 함수들
# ==========================================

def get_momentum_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="2y")
        if df.empty or len(df) < 205: return {}

        df['SMA_20'] = ta.sma(df['Close'], length=20)
        df['SMA_50'] = ta.sma(df['Close'], length=50)
        df['SMA_200'] = ta.sma(df['Close'], length=200)
        df['RSI_14'] = ta.rsi(df['Close'], length=14)

        latest = df.iloc[-1]
        prev_5d = df.iloc[-6]

        current_price = latest['Close']
        sma20 = latest['SMA_20']
        sma50 = latest['SMA_50']
        sma200 = latest['SMA_200']
        rsi14 = latest['RSI_14']

        is_50_up = (sma50 > prev_5d['SMA_50'])
        is_200_up = (sma200 > prev_5d['SMA_200'])
        is_aligned = 'O' if (pd.notna(sma50) and pd.notna(sma200) and sma50 > sma200 and is_50_up and is_200_up) else 'X'

        disparity = (current_price / sma20) * 100 if pd.notna(sma20) and sma20 != 0 else np.nan
        is_rsi_good = 'O' if pd.notna(rsi14) and (50 <= rsi14 <= 70) else 'X'

        return {
            '현재가($)': round(current_price, 2),
            '50일 이평선': round(sma50, 2) if pd.notna(sma50) else 'N/A',
            '200일 이평선': round(sma200, 2) if pd.notna(sma200) else 'N/A',
            'RSI (14일)': round(rsi14, 2) if pd.notna(rsi14) else 'N/A',
            '이격도(%)': round(disparity, 2) if pd.notna(disparity) else 'N/A',
            '정배열 (50>200)': is_aligned,
            'RSI 모멘텀 (50~70)': is_rsi_good
        }
    except Exception: return {}

def get_fundamental_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        ann_fin = stock.financials
        qtr_fin = stock.quarterly_financials
        data = {}
        if not ann_fin.empty:
            rev_label = next((idx for idx in ann_fin.index if idx in ['Total Revenue', 'Operating Revenue']), None)
            op_inc_label = next((idx for idx in ann_fin.index if 'Operating Income' in idx), None)
            for i in range(3):
                if i < len(ann_fin.columns):
                    rev = ann_fin.iloc[ann_fin.index.get_loc(rev_label), i] if rev_label else np.nan
                    op_inc = ann_fin.iloc[ann_fin.index.get_loc(op_inc_label), i] if op_inc_label else np.nan
                    margin = (op_inc / rev) * 100 if pd.notnull(rev) and rev != 0 else np.nan
                    data[f'최근 {i+1}년 매출($B)'] = round(rev / 1e9, 2) if pd.notnull(rev) else 'N/A'
                    data[f'최근 {i+1}년 영업이익률(%)'] = round(margin, 2) if pd.notnull(margin) else 'N/A'
        if not qtr_fin.empty:
            rev_label_q = next((idx for idx in qtr_fin.index if idx in ['Total Revenue', 'Operating Revenue']), None)
            op_inc_label_q = next((idx for idx in qtr_fin.index if 'Operating Income' in idx), None)
            for i in range(3):
                if i < len(qtr_fin.columns):
                    rev = qtr_fin.iloc[qtr_fin.index.get_loc(rev_label_q), i] if rev_label_q else np.nan
                    op_inc = qtr_fin.iloc[qtr_fin.index.get_loc(op_inc_label_q), i] if op_inc_label_q else np.nan
                    margin = (op_inc / rev) * 100 if pd.notnull(rev) and rev != 0 else np.nan
                    data[f'최근 {i+1}분기 매출($B)'] = round(rev / 1e9, 2) if pd.notnull(rev) else 'N/A'
                    data[f'최근 {i+1}분기 영업이익률(%)'] = round(margin, 2) if pd.notnull(margin) else 'N/A'
        return data
    except Exception: return {}

def get_valuation_data(ticker):
    try:
        info = yf.Ticker(ticker).info
        def fmt(key, mult=1, suffix=''):
            val = info.get(key)
            if val is None or val == 'N/A': return 'N/A'
            return f"{round(val * mult, 2)}{suffix}"
        return {
            'Trailing PER': fmt('trailingPE'),
            'Forward PER': fmt('forwardPE'),
            'PBR': fmt('priceToBook'),
            'EV/EBITDA': fmt('enterpriseToEbitda'),
            'ROE': fmt('returnOnEquity', 100, '%'),
            'ROA': fmt('returnOnAssets', 100, '%'),
            '영업이익률': fmt('operatingMargins', 100, '%'),
            '부채비율': fmt('debtToEquity', 1, '%'),
            '매출성장률': fmt('revenueGrowth', 100, '%')
        }
    except Exception: return {}

def get_analyst_data(ticker):
    try:
        info = yf.Ticker(ticker).info
        curr = info.get('currentPrice')
        target = info.get('targetMeanPrice')
        upside = round(((target / curr) - 1) * 100, 2) if curr and target else "N/A"
        return {
            '의견': str(info.get('recommendationKey', 'N/A')).upper(),
            '목표가($)': target if target else 'N/A',
            '상승여력(%)': upside
        }
    except Exception: return {}

# ==========================================
# ✅ 수정된 함수: get_news_analysis
# ==========================================
def _ddg_search(kw, timelimit, max_results=10):
    """DuckDuckGo 뉴스 검색 (재시도 포함). 성공 시 결과 리스트 반환."""
    for attempt in range(3):
        try:
            with DDGS() as ddgs:
                results = ddgs.news(keywords=kw, timelimit=timelimit, max_results=max_results) or []
            print(f"  ℹ️ DDG 검색 완료: {len(results)}건 (키워드: '{kw}', 기간: {timelimit})")
            return results
        except Exception as e:
            print(f"  ⚠️ DDG 오류 (시도 {attempt+1}/3): {type(e).__name__}: {e}")
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
    return []


def get_news_analysis(ticker, company_name):
    ten_days_ago = datetime.now(timezone.utc) - timedelta(days=10)
    is_korean = '.KS' in ticker

    recent_news_texts = []   # 최근 10일 이내 뉴스
    yahoo_old_texts = []     # 야후에서 수집한 10일 이전 뉴스 (폴백용)

    # ── 1. 야후 파이낸스 뉴스 ──────────────────────────
    try:
        stock = yf.Ticker(ticker)
        yahoo_count = 0
        for news in stock.news or []:
            content = news.get('content', news)
            pub_date_str = content.get('pubDate')
            if pub_date_str:
                try:
                    pub_date = datetime.fromisoformat(pub_date_str.replace('Z', '+00:00'))
                    entry = (
                        f"[야후/핵심팩트] {pub_date.strftime('%Y-%m-%d')} | "
                        f"{content.get('title')} - {content.get('summary')}"
                    )
                    if pub_date >= ten_days_ago:
                        recent_news_texts.append(entry)
                        yahoo_count += 1
                    else:
                        yahoo_old_texts.append((pub_date, entry))
                except Exception as e:
                    print(f"  ⚠️ [{ticker}] 야후 날짜 파싱 오류: {e}")
        print(f"  ℹ️ [{ticker}] 야후 최근 뉴스: {yahoo_count}건 / 이전 뉴스 백업: {len(yahoo_old_texts)}건")
    except Exception as e:
        print(f"  ⚠️ [{ticker}] 야후 뉴스 수집 실패: {type(e).__name__}: {e}")

    # ── 2. DuckDuckGo 뉴스 (최근) ─────────────────────
    # 한국 종목: 복수 검색어로 넓게 검색
    if is_korean:
        ddg_queries = [
            f"{company_name} 주가 뉴스",
            f"{company_name} 실적 공시",
            f"{company_name} 주식",
        ]
        timelimit = 'm'  # 최근 1개월 (한국 뉴스 인덱싱이 느려서 범위 확장)
    else:
        ddg_queries = [f"{ticker} {company_name} stock news"]
        timelimit = 'w'  # 최근 1주일

    seen_titles = set()
    for kw in ddg_queries:
        if len(recent_news_texts) >= 15:
            break
        for news in _ddg_search(kw, timelimit):
            title = news.get('title')
            if title and title not in seen_titles:
                seen_titles.add(title)
                date_str = news.get('date', '')[:10]
                recent_news_texts.append(
                    f"[외부/시장트렌드] {date_str} | {title} - {news.get('body')}"
                )

    # ── 3. 최근 뉴스가 없으면 폴백: 이전 주요 이슈 수집 ──
    has_recent_news = bool(recent_news_texts)
    combined_news_texts = list(recent_news_texts)

    if not has_recent_news:
        print(f"  ⚠️ [{ticker}] 최근 뉴스 없음 — 이전 주요 이슈 검색 중...")

        # 야후 이전 뉴스: 최신순 최대 5건
        if yahoo_old_texts:
            yahoo_old_texts.sort(key=lambda x: x[0], reverse=True)
            for _, entry in yahoo_old_texts[:5]:
                combined_news_texts.append(entry)

        # DDG 폴백: timelimit 없이(또는 1년) 더 광범위하게 검색
        if is_korean:
            fallback_queries = [
                f"{company_name} 주요 이슈",
                f"{company_name} 실적 전망",
            ]
        else:
            fallback_queries = [f"{ticker} {company_name} major news issues"]

        fallback_seen = seen_titles.copy()
        for kw in fallback_queries:
            if len(combined_news_texts) >= 8:
                break
            for news in _ddg_search(kw, timelimit='y', max_results=8):
                title = news.get('title')
                if title and title not in fallback_seen:
                    fallback_seen.add(title)
                    date_str = news.get('date', '')[:10]
                    combined_news_texts.append(
                        f"[이전이슈/참고] {date_str} | {title} - {news.get('body')}"
                    )

    if not combined_news_texts:
        print(f"  ❌ [{ticker}] 최종 뉴스 0건 — AI 분석 스킵")
        return {'시장센티멘트': '중립', 'AI 심층 분석': '수집된 뉴스 없음', '분석뉴스건수': 0}

    # ── 4. Gemini AI 분석 ─────────────────────────────
    news_text = "\n".join(combined_news_texts)
    period_note = (
        "최근 10일 이내 뉴스 기반"
        if has_recent_news
        else "최근 10일 내 뉴스 없음 — 이전 주요 이슈 기반 분석 (참고용)"
    )

    prompt = f"""
    너는 월스트리트의 수석 주식 애널리스트야.
    아래 제공된 [{company_name}({ticker})]에 관한 뉴스 데이터 {len(combined_news_texts)}건을 모두 읽고 심층 분석해줘.
    (분석 기간 기준: {period_note})

    제공된 데이터는 세 종류야:
    - [야후/핵심팩트]: 주가에 직접적인 영향을 미치는 주요 언론의 핵심 뉴스야. 가장 큰 가중치를 두어 분석해.
    - [외부/시장트렌드]: 최근 시장 참여자들 사이에서 논의된 전반적인 이슈와 심리 흐름이야.
    - [이전이슈/참고]: 최근 10일 이내 뉴스가 없어 이전 중요 이슈를 참고용으로 제공함. 현재 상황에 여전히 유효할 수 있는 핵심 이슈를 파악해.

    모든 기사의 맥락을 파악하여 최종적인 시장 심리를 결정하고,
    주가 흐름에 영향을 줄 핵심 내용들을 '개괄식(bullet point)'으로 아주 상세하게 정리해.

    특히 가장 최근 날짜의 뉴스에 더 큰 가중치를 두어 시장 심리를 해석해.
    주가에 핵심 영향을 주는 뉴스라면 [핵심]이라고 표시하고 해당 날짜도 적어줘.
    만약 [이전이슈/참고] 기반 분석이라면 sentiment 앞에 "(과거기준)"을 붙여줘.

    다음 JSON 스키마에 맞춰서 답변해.
    {{
        "sentiment": "긍정/중립/부정 중 택1",
        "detailed_summary": "- 핵심내용1\\n- 핵심내용2\\n- 향후전망 등 상세 작성"
    }}

    [분석할 뉴스 헤드라인 및 요약본 리스트]
    {news_text}
    """

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=target_model,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type='application/json')
            )
            data = json.loads(response.text)
            time.sleep(1.5)
            return {
                '분석뉴스건수': len(combined_news_texts),
                '시장센티멘트': data.get('sentiment', '중립'),
                'AI 심층 분석': data.get('detailed_summary', '')
            }
        except Exception as e:
            print(f"  ⚠️ [{ticker}] Gemini 분석 오류 (시도 {attempt+1}/3): {type(e).__name__}: {e}")
            if attempt < 2:
                time.sleep(5)

    return {'시장센티멘트': '오류', 'AI 심층 분석': '분석 실패', '분석뉴스건수': len(combined_news_texts)}

# ==========================================
# 4. 전체 파이프라인 실행 및 컬럼 고정
# ==========================================
results = []
print(f"📊 총 {len(tickers)}개 종목 분석 시작...")

for ticker in tickers:
    print(f"[{ticker}] 진행 중...")
    name = ticker_to_name.get(ticker, ticker)

    row = {'종목명': name, 'Ticker': ticker}
    row.update(get_momentum_data(ticker))
    row.update(get_fundamental_data(ticker))
    row.update(get_valuation_data(ticker))
    row.update(get_analyst_data(ticker))
    row.update(get_news_analysis(ticker, name))

    results.append(row)

master_df = pd.DataFrame(results)

ordered_cols = [
    '종목명', 'Ticker', '현재가($)', '50일 이평선', '200일 이평선', 'RSI (14일)', '이격도(%)',
    '정배열 (50>200)', 'RSI 모멘텀 (50~70)', '최근 1년 매출($B)', '최근 1년 영업이익률(%)',
    '최근 2년 매출($B)', '최근 2년 영업이익률(%)', '최근 3년 매출($B)', '최근 3년 영업이익률(%)',
    '최근 1분기 매출($B)', '최근 1분기 영업이익률(%)', '최근 2분기 매출($B)', '최근 2분기 영업이익률(%)',
    '최근 3분기 매출($B)', '최근 3분기 영업이익률(%)', 'Trailing PER', 'Forward PER', 'PBR',
    'EV/EBITDA', 'ROE', 'ROA', '영업이익률', '부채비율', '매출성장률', '의견', '목표가($)',
    '상승여력(%)', '분석뉴스건수', '시장센티멘트', 'AI 심층 분석'
]

master_df_final = master_df.reindex(columns=ordered_cols).fillna('N/A')

# ==========================================
# 5. 구글 시트 업로드
# ==========================================
print("\n☁️ 구글 시트 업로드 중...")
try:
    service_account_info = json.loads(gcp_json_str)
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open("주식_실시간데이터")
    worksheet = sh.worksheet("주식 데이터")

    worksheet.clear()
    upload_data = [master_df_final.columns.values.tolist()] + master_df_final.values.tolist()
    worksheet.update(range_name='A1', values=upload_data)
    print("🎉 기울기 조건까지 포함된 정밀 정배열 로직이 적용되었습니다!")

except Exception as e:
    print(f"❌ 시트 업로드 실패 원인: {e}")

print("\n✅ 모든 파이프라인이 종료되었습니다.")
