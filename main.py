import os
import json
import time
import warnings
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np
import yfinance as yf
import pandas_ta as ta
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# 덕덕고 검색 라이브러리
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

# 시스템 경고 숨기기
warnings.filterwarnings('ignore')

print("🚀 주식 분석 자동화 파이프라인 시작...\n")

# ==========================================
# 1. 환경 변수 및 API 설정 (GitHub Secrets 연동)
# ==========================================
gemini_api_key = os.environ.get('GEMINI_API_KEY')
gcp_json_str = os.environ.get('GCP_SERVICE_ACCOUNT')

if not gemini_api_key or not gcp_json_str:
    raise ValueError("❌ 환경 변수(API 키 또는 GCP JSON)가 설정되지 않았습니다. GitHub Secrets를 확인하세요.")

genai.configure(api_key=gemini_api_key)

try:
    available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    target_model = next((m for m in available_models if '3.1-flash-lite' in m.lower()),
                        next((m for m in available_models if '1.5-flash' in m.lower()), available_models[0]))
    model = genai.GenerativeModel(target_model, generation_config={"response_mime_type": "application/json"})
    print(f"✅ AI 모델 세팅 완료: {target_model}")
except Exception as e:
    print(f"❌ AI 모델 설정 오류: {e}")

# ==========================================
# 2. 분석 대상 종목 세팅
# ==========================================
tickers = [
    'AAPL', 'MSFT', 'NVDA', 'TSM', 'ALB', 'XOM', 'SLB','CELH', 'BBW', 'SMR', 'ASML', 'HSY', 'RCL', 'GOOG', 'WM', 'VRT', 'CRDO', 'META', 'TSLA', 'LITE', 'BE',
    '035420.KS', '021240.KS', '033780.KS', '213420.KS', '034220.KS', '059090.KS', '338220.KS', 'BA', 'FUTU', 'ELV', '373220.KS'
]

ticker_to_name = {
    'AAPL': '애플', 'MSFT': '마이크로소프트', 'NVDA': '엔비디아', 'TSM': 'TSMC', 'ALB': '앨버말',
    'XOM': '엑슨모빌', 'SLB': '슐럼버거', 'CELH': '셀시어스', 'BBW': '빌드어베어', 'SMR': '뉴스케일파워',
    'ASML': 'ASML', 'HSY': '허쉬', 'RCL': '로열캐리비안', 'GOOG': '알파벳(구글)', 'WM': '웨이스트매니지먼트',
    'VRT': '버티브', 'CRDO': '크레도테크', 'META': '메타', 'TSLA': '테슬라', 'LITE': '루멘텀', 'BE': '블룸에너지',
    '035420.KS': '네이버', '021240.KS': '코웨이', '033780.KS': 'KT&G',
    '213420.KS': '덕산네오룩스', '034220.KS': 'LG디스플레이', '059090.KS': '미코', '338220.KS': '뷰노', 'BA' : '보잉', 'FUTU' : '푸투', 'ELV' : '앤섬', '373220.KS' : 'LG에너지솔루션'
}

# ==========================================
# 3. 데이터 수집 함수들
# ==========================================

def get_momentum_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y")
        if df.empty: return None

        df['SMA_20'] = ta.sma(df['Close'], length=20)
        df['SMA_50'] = ta.sma(df['Close'], length=50)
        df['SMA_200'] = ta.sma(df['Close'], length=200)
        df['RSI_14'] = ta.rsi(df['Close'], length=14)

        latest = df.iloc[-1]
        current_price = latest['Close']
        sma20, sma50, sma200, rsi14 = latest['SMA_20'], latest['SMA_50'], latest['SMA_200'], latest['RSI_14']

        disparity = (current_price / sma20) * 100 if pd.notna(sma20) and sma20 != 0 else np.nan
        is_aligned = 'O' if pd.notna(sma50) and pd.notna(sma200) and (sma50 > sma200) else 'X'
        is_rsi_good = 'O' if pd.notna(rsi14) and (50 <= rsi14 <= 70) else 'X'

        return {
            'Ticker': ticker,
            '현재가($)': round(current_price, 2),
            '50일 이평선': round(sma50, 2) if pd.notna(sma50) else np.nan,
            '200일 이평선': round(sma200, 2) if pd.notna(sma200) else np.nan,
            'RSI (14일)': round(rsi14, 2) if pd.notna(rsi14) else np.nan,
            '이격도(%)': round(disparity, 2) if pd.notna(disparity) else np.nan,
            '정배열 (50>200)': is_aligned,
            'RSI 모멘텀 (50~70)': is_rsi_good
        }
    except Exception as e:
        print(f"[{ticker}] 모멘텀 수집 오류: {e}")
        return None

def get_fundamental_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        ann_fin = stock.financials
        qtr_fin = stock.quarterly_financials
        data = {'Ticker': ticker}

        if not ann_fin.empty:
            rev_label = next((idx for idx in ann_fin.index if idx in ['Total Revenue', 'Operating Revenue']), None)
            op_inc_label = next((idx for idx in ann_fin.index if 'Operating Income' in idx), None)
            for i in range(3):
                if i < len(ann_fin.columns):
                    rev = ann_fin.iloc[ann_fin.index.get_loc(rev_label), i] if rev_label else np.nan
                    op_inc = ann_fin.iloc[ann_fin.index.get_loc(op_inc_label), i] if op_inc_label else np.nan
                    margin = (op_inc / rev) * 100 if pd.notnull(rev) and rev != 0 else np.nan
                    data[f'최근 {i+1}년 매출($B)'] = round(rev / 1e9, 2) if pd.notnull(rev) else None
                    data[f'최근 {i+1}년 영업이익률(%)'] = round(margin, 2) if pd.notnull(margin) else None

        if not qtr_fin.empty:
            rev_label_q = next((idx for idx in qtr_fin.index if idx in ['Total Revenue', 'Operating Revenue']), None)
            op_inc_label_q = next((idx for idx in qtr_fin.index if 'Operating Income' in idx), None)
            for i in range(3):
                if i < len(qtr_fin.columns):
                    rev = qtr_fin.iloc[qtr_fin.index.get_loc(rev_label_q), i] if rev_label_q else np.nan
                    op_inc = qtr_fin.iloc[qtr_fin.index.get_loc(op_inc_label_q), i] if op_inc_label_q else np.nan
                    margin = (op_inc / rev) * 100 if pd.notnull(rev) and rev != 0 else np.nan
                    data[f'최근 {i+1}분기 매출($B)'] = round(rev / 1e9, 2) if pd.notnull(rev) else None
                    data[f'최근 {i+1}분기 영업이익률(%)'] = round(margin, 2) if pd.notnull(margin) else None
        return data
    except Exception as e:
        print(f"[{ticker}] 펀더멘털 오류: {e}")
        return {'Ticker': ticker}

def get_valuation_data(ticker):
    def get_val(info, key, multiplier=1, decimal=2, suffix=''):
        val = info.get(key)
        return f"{round(val * multiplier, decimal)}{suffix}" if val is not None else "N/A"
    try:
        info = yf.Ticker(ticker).info
        return {
            'Ticker': ticker,
            'Trailing PER': get_val(info, 'trailingPE'),
            'Forward PER': get_val(info, 'forwardPE'),
            'PBR': get_val(info, 'priceToBook'),
            'EV/EBITDA': get_val(info, 'enterpriseToEbitda'),
            'ROE': get_val(info, 'returnOnEquity', 100, 2, '%'),
            '영업이익률': get_val(info, 'operatingMargins', 100, 2, '%'),
            '부채비율': get_val(info, 'debtToEquity', 1, 2, '%'),
            '매출성장률': get_val(info, 'revenueGrowth', 100, 2, '%')
        }
    except Exception as e:
        print(f"[{ticker}] 가치평가 수집 오류: {e}")
        return {'Ticker': ticker}

def get_analyst_data(ticker):
    try:
        info = yf.Ticker(ticker).info
        curr = info.get('currentPrice')
        target = info.get('targetMeanPrice')
        upside = round(((target / curr) - 1) * 100, 2) if curr and target else "N/A"
        return {
            'Ticker': ticker,
            '의견': str(info.get('recommendationKey', 'N/A')).upper(),
            '목표가($)': target if target else 'N/A',
            '상승여력(%)': upside
        }
    except Exception:
        return {'Ticker': ticker}

def get_news_analysis(ticker, company_name):
    combined = []
    ten_days_ago = datetime.now(timezone.utc) - timedelta(days=10)
    
    try:
        stock = yf.Ticker(ticker)
        for news in stock.news or []:
            content = news.get('content', news)
            pub_date_str = content.get('pubDate')
            if pub_date_str:
                try:
                    pub_date = datetime.fromisoformat(pub_date_str.replace('Z', '+00:00'))
                    if pub_date >= ten_days_ago:
                        combined.append(f"[야후] {content.get('title')} - {content.get('summary')}")
                except ValueError:
                    pass
    except Exception: pass

    try:
        ddgs = DDGS()
        kw = f"{company_name} 주식" if '.KS' in ticker else f"{ticker} stock"
        for news in ddgs.news(keywords=kw, timelimit='w', max_results=10) or []:
            if news.get('title'):
                combined.append(f"[웹] {news.get('title')} - {news.get('body')}")
    except Exception: pass

    if not combined: return {'Ticker': ticker, 'AI 심층 분석': '뉴스 없음'}

    prompt = f"""
    [{company_name}({ticker})] 최신 뉴스 분석.
    다음 JSON 포맷으로 답해:
    {{"sentiment": "긍정/중립/부정", "detailed_summary": "- 핵심내용 요약"}}
    뉴스:
    {' / '.join(combined)}
    """
    try:
        res = model.generate_content(prompt)
        data = json.loads(res.text)
        time.sleep(2)
        return {
            'Ticker': ticker,
            '분석뉴스건수': len(combined),
            '시장센티멘트': data.get('sentiment', '중립'),
            'AI 심층 분석': data.get('detailed_summary', '')
        }
    except Exception as e:
        return {'Ticker': ticker, 'AI 심층 분석': '분석 실패'}

# ==========================================
# 4. 전체 파이프라인 실행
# ==========================================
results = []
print("\n📊 전 종목 데이터 수집 및 분석 시작...")
for ticker in tickers:
    print(f"[{ticker}] 분석 중...")
    c_name = ticker_to_name.get(ticker, ticker)
    
    # 각 지표 수집
    m_data = get_momentum_data(ticker) or {'Ticker': ticker}
    f_data = get_fundamental_data(ticker)
    v_data = get_valuation_data(ticker)
    a_data = get_analyst_data(ticker)
    n_data = get_news_analysis(ticker, c_name)
    
    # 병합
    merged = {**m_data, **f_data, **v_data, **a_data, **n_data}
    merged['종목명'] = c_name
    results.append(merged)

master_df = pd.DataFrame(results)

# 컬럼 순서 정리 및 결측치 처리
cols = ['종목명', 'Ticker'] + [c for c in master_df.columns if c not in ['종목명', 'Ticker']]
master_df = master_df[cols]
master_df_cleaned = master_df.replace([np.inf, -np.inf], np.nan).fillna('N/A')
master_df_cleaned.columns = [str(col).replace('\n', ' ').strip() for col in master_df_cleaned.columns]

# ==========================================
# 5. 구글 시트 업로드
# ==========================================
print("\n☁️ 구글 시트 업로드 중...")
try:
    gcp_credentials = json.loads(gcp_json_str)
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(gcp_credentials, scope)
    gc = gspread.authorize(creds)

    SHEET_NAME = "주식_실시간데이터"
    TAB_NAME = "주식 데이터"
    sh = gc.open(SHEET_NAME)

    try:
        worksheet = sh.worksheet(TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sh.add_worksheet(title=TAB_NAME, rows="100", cols="50")

    worksheet.clear()
    data_to_upload = [master_df_cleaned.columns.values.tolist()] + master_df_cleaned.values.tolist()
    worksheet.update(range_name='A1', values=data_to_upload)

    print(f"🎉 성공: '{SHEET_NAME}' 시트의 '{TAB_NAME}' 탭으로 데이터 자동 전송 완료!")

except Exception as e:
    print(f"❌ 구글 시트 업로드 실패: {e}")

print("\n✅ 모든 파이프라인이 성공적으로 종료되었습니다.")
