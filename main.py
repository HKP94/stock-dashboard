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
# 1. 환경 변수 및 API 설정
# ==========================================
gemini_api_key = os.environ.get('GEMINI_API_KEY')
gcp_json_str = os.environ.get('GCP_SERVICE_ACCOUNT')

if not gemini_api_key or not gcp_json_str:
    raise ValueError("❌ 환경 변수가 설정되지 않았습니다.")

genai.configure(api_key=gemini_api_key)

try:
    available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    target_model = next((m for m in available_models if '1.5-flash' in m.lower()), available_models[0])
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
# 3. 데이터 수집 함수 정의
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
            '현재가($)': round(current_price, 2),
            '50일 이평선': round(sma50, 2) if pd.notna(sma50) else np.nan,
            '200일 이평선': round(sma200, 2) if pd.notna(sma200) else np.nan,
            'RSI (14일)': round(rsi14, 2) if pd.notna(rsi14) else np.nan,
            '이격도(%)': round(disparity, 2) if pd.notna(disparity) else np.nan,
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
                    data[f'최근 {i+1}년 매출($B)'] = round(rev / 1e9, 2) if pd.notnull(rev) else None
                    data[f'최근 {i+1}년 영업이익률(%)'] = round(margin, 2) if pd.notnull(margin) else None
        return data
    except Exception: return {}

def get_valuation_data(ticker):
    try:
        info = yf.Ticker(ticker).info
        return {
            'Trailing PER': round(info.get('trailingPE', 0), 2) if info.get('trailingPE') else 'N/A',
            'Forward PER': round(info.get('forwardPE', 0), 2) if info.get('forwardPE') else 'N/A',
            'PBR': round(info.get('priceToBook', 0), 2) if info.get('priceToBook') else 'N/A',
            'ROE': f"{round(info.get('returnOnEquity', 0)*100, 2)}%" if info.get('returnOnEquity') else 'N/A'
        }
    except Exception: return {}

def get_news_analysis(ticker, company_name):
    combined_news_texts = []
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
                        combined_news_texts.append(f"[야후/핵심팩트] {content.get('title')} - {content.get('summary')}")
                except ValueError: pass
    except Exception: pass

    try:
        ddgs = DDGS()
        kw = f"{company_name} 주식" if '.KS' in ticker else f"{ticker} stock"
        for news in ddgs.news(keywords=kw, timelimit='w', max_results=10) or []:
            if news.get('title'):
                combined_news_texts.append(f"[외부/시장트렌드] {news.get('title')} - {news.get('body')}")
    except Exception: pass

    if not combined_news_texts:
        return {'시장센티멘트': '중립', 'AI 심층 분석': '최근 10일간 뉴스 없음'}

    news_text = "\n".join(combined_news_texts)
    
    prompt = f"""
    너는 월스트리트의 수석 주식 애널리스트이야.
    아래 제공된 [{company_name}({ticker})]에 관한 최근 10일간의 뉴스 데이터 {len(combined_news_texts)}건을 모두 읽고 심층 분석해줘.

    제공된 데이터는 두 종류야:
    - [야후/핵심팩트]: 주가에 직접적인 영향을 미치는 주요 언론의 핵심 뉴스야. 가장 큰 가중치를 두어 분석해.
    - [외부/시장트렌드]: 최근 10일간 시장 참여자들 사이에서 논의된 전반적인 이슈와 심리 흐름이야.

    모든 기사의 맥락을 파악하여 최종적인 시장 심리를 결정하고,
    주가 흐름에 영향을 줄 핵심 내용들을 '개괄식(bullet point)'으로 아주 상세하게 정리해.

    특히 가장 최근 날짜의 뉴스에 더 큰 가중치를 두어 시장 심리를 해석해.

    다음 JSON 스키마에 맞춰서 답변해.
    {{
        "sentiment": "긍정/중립/부정 중 택1",
        "detailed_summary": "- 핵심내용1\\n- 핵심내용2\\n- 향후전망 등 상세 작성"
    }}

    [분석할 뉴스 헤드라인 및 요약본 리스트]
    {news_text}
    """
    
    try:
        res = model.generate_content(prompt)
        # JSON 부분만 추출
        json_str = res.text.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        data = json.loads(json_str)
        time.sleep(1.5)
        return {
            '분석뉴스건수': len(combined_news_texts),
            '시장센티멘트': data.get('sentiment', '중립'),
            'AI 심층 분석': data.get('detailed_summary', '')
        }
    except Exception as e:
        print(f"[{ticker}] AI 뉴스 분석 오류: {e}")
        return {'시장센티멘트': '오류', 'AI 심층 분석': '분석 실패'}

# ==========================================
# 4. 메인 실행 루프
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
    row.update(get_news_analysis(ticker, name))
    
    results.append(row)

master_df = pd.DataFrame(results)
master_df_cleaned = master_df.replace([np.inf, -np.inf], np.nan).fillna('N/A')

# ==========================================
# 5. 구글 시트 업로드
# ==========================================
print("\n☁️ 구글 시트 업로드 중...")
try:
    gcp_credentials = json.loads(gcp_json_str)
    scope = ['[https://spreadsheets.google.com/feeds](https://spreadsheets.google.com/feeds)', '[https://www.googleapis.com/auth/drive](https://www.googleapis.com/auth/drive)']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(gcp_credentials, scope)
    gc = gspread.authorize(creds)

    sh = gc.open("주식_실시간데이터")
    try:
        worksheet = sh.worksheet("주식 데이터")
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sh.add_worksheet(title="주식 데이터", rows="100", cols="50")

    worksheet.clear()
    upload_data = [master_df_cleaned.columns.values.tolist()] + master_df_cleaned.values.tolist()
    worksheet.update(range_name='A1', values=upload_data)
    print("🎉 구글 시트 업데이트 성공!")

except Exception as e:
    print(f"❌ 시트 업로드 실패: {e}")

print("\n✅ 모든 작업이 완료되었습니다.")
