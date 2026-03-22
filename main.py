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
    'NVDA', 'XOM'
]

ticker_to_name = {
    'AAPL': '애플', 'MSFT': '마이크로소프트', 'NVDA': '엔비디아', 'TSM': 'TSMC', 'ALB': '앨버말',
    'XOM': '엑슨모빌', 'SLB': '슐럼버거', 'CELH': '셀시어스', 'BBW': '빌드어베어', 'SMR': '뉴스케일파워',
    'ASML': 'ASML', 'HSY': '허쉬', 'RCL': '로열캐리비안', 'GOOG': '알파벳(구글)', 'WM': '웨이스트매니지먼트',
    'VRT': '버티브', 'CRDO': '크레도테크', 'META': '메타', 'TSLA': '테슬라', 'LITE': '루멘텀', 'BE': '블룸에너지',
    '035420.KS': '네이버', '021240.KS': '코웨이', '033780.KS': 'KT&G',
    '213420.KS': '덕산네오룩스', '034220.KS': 'LG디스플레이', '059090.KS': '미코', '338220.KS': '뷰노', 'BA' : '보잉', 'FUTU' : '푸투', 'ELV' : '앤섬', '373220.KS' : 'LG에너지솔루션'
}

def get_news_analysis(ticker, company_name):
    combined = []
    ten_days_ago = datetime.now(timezone.utc) - timedelta(days=10)
    print(f"  -> [{ticker}] 야후 뉴스 수집 시도...")
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
                            combined.append(f"[야후/핵심팩트] {pub_date.strftime('%Y-%m-%d')} | {content.get('title')} - {content.get('summary')}")
                    except ValueError as ve:
                        print(f"    -> [{ticker}] 야후 뉴스 날짜 파싱 오류: {ve}")
        else:
            print(f"    -> [{ticker}] 야후 파이낸스에서 뉴스를 찾지 못했습니다.")
    except Exception as e:
        print(f"    -> [{ticker}] 야후 뉴스 수집 중 오류 발생: {e}")

    print(f"  -> [{ticker}] 덕덕고 뉴스 수집 시도...")
    try:
        ddgs = DDGS()
        kw = f"{company_name} 주식" if '.KS' in ticker else f"{ticker} stock"
        # max_results를 20으로 늘려 더 많은 뉴스 수집 시도
        ddg_results = ddgs.news(keywords=kw, timelimit='w', max_results=20)
        if ddg_results:
            for news in ddg_results:
                title = news.get('title', '')
                summary = news.get('body', '요약 없음')
                date_str = news.get('date', '')[:10]
                if title and summary: # 제목과 요약이 있는 경우에만 추가
                    combined.append(f"[외부/시장트렌드] {date_str} | {title} - {summary}")
        else:
            print(f"    -> [{ticker}] 덕덕고에서 뉴스를 찾지 못했습니다.")
    except Exception as e:
        print(f"    -> [{ticker}] 덕덕고 뉴스 수집 중 오류 발생: {e}")

    if not combined:
        print(f"  -> [{ticker}] 최근 10일간 뉴스 없음. AI 분석 생략.")
        return {'Ticker': ticker, 'AI 심층 분석': '최근 10일간 뉴스 없음', '분석뉴스건수': 0, '시장센티멘트': '중립'}

    news_text = "\n".join(combined)
    prompt = f"""
    너는 월스트리트의 수석 주식 애널리스트야.
    아래 제공된 [{company_name}({ticker})]에 관한 최근 10일간의 뉴스 데이터 {len(combined)}건을 모두 읽고 심층 분석해줘.

    제공된 데이터는 두 종류야:
    - [야후/핵심팩트]: 주가에 직접적인 영향을 미치는 주요 언론의 핵심 뉴스야. 가장 큰 가중치를 두어 분석해.
    - [외부/시장트렌드]: 최근 10일간 시장 참여자들 사이에서 논의된 전반적인 이슈와 심리 흐름이야.

    모든 기사의 맥락을 파악하여 최종적인 시장 심리를 결정하고,
    주가 흐름에 영향을 줄 핵심 내용들을 '개괄식(bullet point)'으로 아주 상세하게 정리해.

    특히 가장 최근 날짜의 뉴스에 더 큰 가중치를 두어 시장 심리를 해석하고,
    만약 당일 주가에 영향을 주는 중요한 뉴스가 있다면 해당 항목에는 '[당일 핵심 뉴스]'라고 명확히 표시해줘.

    다음 JSON 스키마에 맞춰서 답변해.
    {{
        "sentiment": "긍정/중립/부정 중 택1",
        "detailed_summary": "- 핵심내용1\n- 핵심내용2\n- 향후전망 등 상세 작성"
    }}

    [분석할 뉴스 헤드라인 및 요약본 리스트]
    {news_text}
    """

    # 재시도 로직 포함
    for attempt in range(3):
        try:
            print(f"  -> [{ticker}] AI 분석 시도 (시도 {attempt+1}/3)...")
            res = model.generate_content(prompt)
            data = json.loads(res.text)
            print(f"  -> [{ticker}] AI 분석 성공.")
            return {
                'Ticker': ticker,
                '분석뉴스건수': len(combined),
                '시장센티멘트': data.get('sentiment', '중립'),
                'AI 심층 분석': data.get('detailed_summary', '요약 실패')
            }
        except Exception as e:
            print(f"  -> [{ticker}] AI 분석 중 오류 발생: {e}")
            if attempt < 2:
                time.sleep(5) # 에러 시 대기 시간 증가
                continue
            print(f"  -> [{ticker}] AI 분석 최종 실패.")
            return {'Ticker': ticker, 'AI 심층 분석': f'분석 실패 (에러: {str(e)[:50]})', '분석뉴스건수': len(combined), '시장센티멘트': '중립'}
    return {'Ticker': ticker, 'AI 심층 분석': '분석 실패', '분석뉴스건수': len(combined), '시장센티멘트': '중립'}

# ... (나머지 get_momentum_data, get_fundamental_data 등은 기존과 동일하되 loop 내 sleep 조절) ...

# ==========================================
# 4. 전체 파이프라인 실행
# ==========================================
results = []
print("\n📊 전 종목 데이터 수집 및 분석 시작...")
for ticker in tickers:
    print(f"[{ticker}] 분석 중...")
    c_name = ticker_to_name.get(ticker, ticker)

    # API 호출 간격 조절 (Rate Limit 방지)
    time.sleep(4)

    # ... (데이터 수집 호출 부분 생략, n_data = get_news_analysis(ticker, c_name) 포함) ...
    n_data = get_news_analysis(ticker, c_name)
    # (예시용 병합 코드 생략 - 실제 파일에서는 전체 지표 수집 코드가 들어가야 함)
    results.append({**n_data, '종목명': c_name, 'Ticker': ticker})

# (이후 구글 시트 업로드 로직 유지)
