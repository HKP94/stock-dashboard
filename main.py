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

# 덕덕고 라이브러리 (버전 호환성)
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

# Gemini 모델 설정
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
# 분석할 티커 리스트 (한국 주식은 .KS 접미사 추가)
tickers = [
    'AAPL', 'MSFT', 'NVDA', 'TSM', 'ALB', 'XOM', 'SLB','CELH', 'BBW', 'SMR', 'ASML', 'HSY', 'RCL', 'GOOG', 'WM', 'VRT', 'CRDO', 'META', 'TSLA', 'LITE', 'BE',
    '035420.KS', '021240.KS', '033780.KS', '213420.KS', '034220.KS', '059090.KS', '338220.KS', 'BA', 'FUTU', 'ELV', '373220.KS'
]

# 티커를 기업 이름으로 변환하기 위한 매핑 사전
ticker_to_name = {
    'AAPL': '애플', 'MSFT': '마이크로소프트', 'NVDA': '엔비디아', 'TSM': 'TSMC', 'ALB': '앨버말',
    'XOM': '엑슨모빌', 'SLB': '슐럼버거', 'CELH': '셀시어스', 'BBW': '빌드어베어', 'SMR': '뉴스케일파워',
    'ASML': 'ASML', 'HSY': '허쉬', 'RCL': '로열캐리비안', 'GOOG': '알파벳(구글)', 'WM': '웨이스트매니지먼트',
    'VRT': '버티브', 'CRDO': '크레도테크', 'META': '메타', 'TSLA': '테슬라', 'LITE': '루멘텀', 'BE': '블룸에너지',
    '035420.KS': '네이버', '021240.KS': '코웨이', '033780.KS': 'KT&G',
    '213420.KS': '덕산네오룩스', '034220.KS': 'LG디스플레이', '059090.KS': '미코', '338220.KS': '뷰노', 'BA' : '보잉', 'FUTU' : '푸투', 'ELV' : '앤섬', '373220.KS' : 'LG에너지솔루션'
}

# ==========================================
# 3. 파트 A: 기술적 분석 및 모멘텀 지표 (final_df)
# ==========================================
print("\n📊 [1단계] 모멘텀 및 기술적 지표 추출 중...")
momentum_results = []

for ticker in tickers:
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y")
        if df.empty:
            continue
            
        df['SMA_20'] = ta.sma(df['Close'], length=20)
        df['SMA_50'] = ta.sma(df['Close'], length=50)
        df['SMA_200'] = ta.sma(df['Close'], length=200)
        df['RSI_14'] = ta.rsi(df['Close'], length=14)
        
        latest = df.iloc[-1]
        current_price = latest['Close']
        sma20 = latest['SMA_20']
        sma50 = latest['SMA_50']
        sma200 = latest['SMA_200']
        rsi14 = latest['RSI_14']
        
        disparity = (current_price / sma20) * 100 if pd.notna(sma20) and sma20 != 0 else np.nan
        is_aligned = 'O' if pd.notna(sma50) and pd.notna(sma200) and (sma50 > sma200) else 'X'
        is_rsi_good = 'O' if pd.notna(rsi14) and (50 <= rsi14 <= 70) else 'X'
        
        momentum_results.append({
            'Ticker': ticker,
            '현재가': round(current_price, 2),
            '50일 이평선': round(sma50, 2) if pd.notna(sma50) else np.nan,
            '200일 이평선': round(sma200, 2) if pd.notna(sma200) else np.nan,
            'RSI (14일)': round(rsi14, 2) if pd.notna(rsi14) else np.nan,
            '이격도(%)': round(disparity, 2) if pd.notna(disparity) else np.nan,
            '정배열 (50>200)': is_aligned,
            'RSI 모멘텀 (50~70)': is_rsi_good
        })
    except Exception as e:
        print(f"[{ticker}] 모멘텀 분석 오류: {e}")

final_df = pd.DataFrame(momentum_results)

# ==========================================
# 4. 파트 B: AI 하이브리드 뉴스 분석 (news_df)
# ==========================================
print("\n🧠 [2단계] 하이브리드 AI 뉴스 심층 분석 중...")
news_results = []
ten_days_ago = datetime.now(timezone.utc) - timedelta(days=10)

for ticker in tickers:
    company_name = ticker_to_name.get(ticker, ticker)
    combined_news_texts = []
    
    # 야후 파이낸스
    try:
        stock = yf.Ticker(ticker)
        news_list = stock.news
        if news_list:
            for news in news_list:
                content = news.get('content', news)
                pub_date_str = content.get('pubDate')
                if pub_date_str:
                    try:
                        pub_date = datetime.fromisoformat(pub_date_str.replace('Z', '+00:00'))
                        if pub_date >= ten_days_ago:
                            title = content.get('title', '제목 없음')
                            summary = content.get('summary', '요약 없음')
                            date_only = pub_date.strftime('%Y-%m-%d')
                            combined_news_texts.append(f"[야후/핵심팩트] {date_only} | {title} - {summary}")
                    except ValueError:
                        pass
    except Exception:
        pass

    # 덕덕고 검색
    try:
        ddgs = DDGS()
        search_keyword = f"{company_name} 주식" if '.KS' in ticker else f"{ticker} stock"
        ddg_results = ddgs.news(keywords=search_keyword, timelimit='w', max_results=15)
        if ddg_results:
            for news in ddg_results:
                title = news.get('title', '')
                summary = news.get('body', '요약 없음')
                date_str = news.get('date', '')[:10]
                if title:
                    combined_news_texts.append(f"[외부/시장트렌드] {date_str} | {title} - {summary}")
    except Exception:
        pass

    if not combined_news_texts:
        continue

    # Gemini API 호출
    news_text = "\n".join(combined_news_texts)
    prompt = f"""
    월스트리트 수석 주식 애널리스트로서 [{company_name}({ticker})]에 관한 최근 뉴스 {len(combined_news_texts)}건을 심층 분석해.
    - [야후/핵심팩트]: 주가에 직접적인 영향을 미치는 주요 언론의 핵심 뉴스 (가중치 높음)
    - [외부/시장트렌드]: 시장 참여자들의 전반적인 심리 흐름
    다음 JSON 스키마에 맞춰 답변해:
    {{
        "sentiment": "긍정/중립/부정 중 택1",
        "detailed_summary": "- 핵심내용1\\n- 핵심내용2\\n- 향후전망"
    }}
    [뉴스 데이터]
    {news_text}
    """
    
    try:
        response = model.generate_content(prompt)
        ai_analysis = json.loads(response.text)
        news_results.append({
            'Ticker': ticker,
            '분석된 뉴스(건)': len(combined_news_texts),
            '시장 센티멘탈': ai_analysis.get('sentiment', '중립'),
            'AI 심층 분석': ai_analysis.get('detailed_summary', '요약 불가')
        })
        time.sleep(2) # Rate limit 방지
    except Exception as e:
        print(f"[{ticker}] AI 오류: {e}")

news_df = pd.DataFrame(news_results)

# ==========================================
# 5. 파트 C: 데이터 병합 및 정제
# ==========================================
print("\n🔗 [3단계] 데이터 병합 및 정제 중...")
master_df = final_df.copy()

if not news_df.empty:
    master_df = master_df.merge(news_df, on='Ticker', how='left')

# 종목명 삽입
master_df.insert(0, '종목명', master_df['Ticker'].map(ticker_to_name).fillna(master_df['Ticker']))

# 결측치 정제 (구글 시트 에러 방지)
master_df_cleaned = master_df.replace([np.inf, -np.inf], np.nan).fillna('')
master_df_cleaned.columns = [str(col).replace('\n', ' ').strip() for col in master_df_cleaned.columns]

# ==========================================
# 6. 파트 D: 구글 시트 무인(자동) 업로드
# ==========================================
print("\n☁️ [4단계] 구글 시트 업로드 중...")
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
