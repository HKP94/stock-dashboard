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

print("ጃ2 ᄀ주ᄒ식 ᄇ분ᄉ석 ᄉ자ᄃ동ᄒ화 ᄑ파ᄋ이ᄑ프ᄅ라ᄋ인 ᄉ시ᄌ작...\n")

# ==========================================
# 1. 환경 변수 및 API 설정 (Standard Environment Variables)
# ==========================================
gemini_api_key = os.environ.get('GEMINI_API_KEY')
gcp_json_str = os.environ.get('GCP_SERVICE_ACCOUNT')

if not gemini_api_key:
    raise ValueError("❌ GEMINI_API_KEY가 환경 변수 또는 GitHub Secrets에 설정되지 않았습니다. 해당 키를 설정해주세요.")
if not gcp_json_str:
    raise ValueError("❌ GCP_SERVICE_ACCOUNT가 환경 변수 또는 GitHub Secrets에 설정되지 않았습니다. 서비스 계정 JSON 문자열을 설정해주세요.")


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
    'NVDA', 'XOM', '373220.KS'
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
# 3. 데이터 수집 헬퍼 함수 정의
# ==========================================

def get_momentum_data(ticker):
    """모멘텀 지표 (SMA, RSI, 이격도)를 계산합니다."""
    print(f"  -> [{ticker}] 모멘텀 데이터 수집 중...")
    stock = yf.Ticker(ticker)
    df = stock.history(period="1y")

    if df.empty:
        print(f"    -> [{ticker}] 모멘텀 데이터를 불러오지 못했습니다.")
        return {'Ticker': ticker, '현재가($)': np.nan, '50일 이평선': np.nan, '200일 이평선': np.nan, 'RSI (14일)': np.nan, '이격도(%)': np.nan, '정배열 (50>200)': 'N/A', 'RSI 모멘텀 (50~70)': 'N/A'}

    df.ta.sma(length=20, append=True)
    df.ta.sma(length=50, append=True)
    df.ta.sma(length=200, append=True)
    df.ta.rsi(length=14, append=True)

    latest = df.iloc[-1]
    current_price = latest['Close']
    sma20 = latest['SMA_20']
    sma50 = latest['SMA_50']
    sma200 = latest['SMA_200']
    rsi14 = latest['RSI_14']

    disparity = (current_price / sma20) * 100 if pd.notnull(sma20) and sma20 != 0 else np.nan

    is_aligned = 'O' if pd.notnull(sma50) and pd.notnull(sma200) and sma50 > sma200 else 'X'
    is_rsi_good = 'O' if pd.notnull(rsi14) and 50 <= rsi14 <= 70 else 'X'

    return {
        'Ticker': ticker,
        '현재가($)': round(current_price, 2) if pd.notnull(current_price) else np.nan,
        '50일 이평선': round(sma50, 2) if pd.notnull(sma50) else np.nan,
        '200일 이평선': round(sma200, 2) if pd.notnull(sma200) else np.nan,
        'RSI (14일)': round(rsi14, 2) if pd.notnull(rsi14) else np.nan,
        '이격도(%)': round(disparity, 2) if pd.notnull(disparity) else np.nan,
        '정배열 (50>200)': is_aligned,
        'RSI 모멘텀 (50~70)': is_rsi_good
    }

def get_val(info, key, multiplier=1, decimal=2, suffix=''):
    """재무 지표를 안전하게 추출하고 포맷팅합니다."""
    val = info.get(key)
    if val is not None and not isinstance(val, (list, dict)) and not isinstance(val, bool): # Added bool check
        return f"{round(val * multiplier, decimal)}{suffix}"
    return "N/A"

def get_fundamental_and_valuation_data(ticker):
    """재무 지표 (매출, 영업이익률) 및 가치 평가 지표를 수집합니다."""
    print(f"  -> [{ticker}] 펀더멘털 및 가치평가 데이터 수집 중...")
    stock = yf.Ticker(ticker)
    info = stock.info
    ann_fin = stock.financials
    qtr_fin = stock.quarterly_financials

    fund_val_data = {'Ticker': ticker}

    # [A] 연간(Annual) 데이터 추출 (최근 3개년)
    if not ann_fin.empty and ann_fin.columns.size > 0:
        rev_label = next((idx for idx in ann_fin.index if idx in ['Total Revenue', 'Operating Revenue']), None)
        op_inc_label = next((idx for idx in ann_fin.index if 'Operating Income' in idx), None)
        for i in range(min(3, len(ann_fin.columns))):
            current_year_data = ann_fin.iloc[:, i] # Get data for current year column
            rev = current_year_data.get(rev_label) if rev_label else np.nan
            op_inc = current_year_data.get(op_inc_label) if op_inc_label else np.nan

            margin = (op_inc / rev) * 100 if pd.notnull(rev) and rev != 0 else np.nan
            fund_val_data[f'최근 {i+1}년 매출($B)'] = round(rev / 1e9, 2) if pd.notnull(rev) else 'N/A'
            fund_val_data[f'최근 {i+1}년 영업이익률(%)'] = round(margin, 2) if pd.notnull(margin) else 'N/A'
    else:
        for i in range(3):
            fund_val_data[f'최근 {i+1}년 매출($B)'] = 'N/A'
            fund_val_data[f'최근 {i+1}년 영업이익률(%)'] = 'N/A'

    # [B] 분기별(Quarterly) 데이터 추출 (최근 3개 분기)
    if not qtr_fin.empty and qtr_fin.columns.size > 0:
        rev_label_q = next((idx for idx in qtr_fin.index if idx in ['Total Revenue', 'Operating Revenue']), None)
        op_inc_label_q = next((idx for idx in qtr_fin.index if 'Operating Income' in idx), None)
        for i in range(min(3, len(qtr_fin.columns))):
            current_quarter_data = qtr_fin.iloc[:, i] # Get data for current quarter column
            rev = current_quarter_data.get(rev_label_q) if rev_label_q else np.nan
            op_inc = current_quarter_data.get(op_inc_label_q) if op_inc_label_q else np.nan

            margin = (op_inc / rev) * 100 if pd.notnull(rev) and rev != 0 else np.nan
            fund_val_data[f'최근 {i+1}분기 매출($B)'] = round(rev / 1e9, 2) if pd.notnull(rev) else 'N/A'
            fund_val_data[f'최근 {i+1}분기 영업이익률(%)'] = round(margin, 2) if pd.notnull(margin) else 'N/A'
    else:
        for i in range(3):
            fund_val_data[f'최근 {i+1}분기 매출($B)'] = 'N/A'
            fund_val_data[f'최근 {i+1}분기 영업이익률(%)'] = 'N/A'

    # [C] 가치 평가 및 건전성 지표
    fund_val_data.update({
        'Trailing PER (현재)': get_val(info, 'trailingPE'),
        'Forward PER (예상)': get_val(info, 'forwardPE'),
        'PBR (주가순자산비율)': get_val(info, 'priceToBook'),
        'EV/EBITDA': get_val(info, 'enterpriseToEbitda'),
        'ROE (자기자본이익률)': get_val(info, 'returnOnEquity', 100, 2, '%'),
        'ROA (총자산이익률)': get_val(info, 'returnOnAssets', 100, 2, '%'),
        '영업이익률_info': get_val(info, 'operatingMargins', 100, 2, '%'), # 기존과 컬럼명 충돌 방지
        '부채비율 (Debt/Equity)': get_val(info, 'debtToEquity', 1, 2, '%'),
        '유동비율 (Current Ratio)': get_val(info, 'currentRatio'),
        '매출성장률 (YoY)': get_val(info, 'revenueGrowth', 100, 2, '%'),
        '배당수익률': get_val(info, 'dividendYield', 100, 2, '%')
    })

    return fund_val_data

def get_analyst_data(ticker):
    """애널리스트 투자의견 및 목표가를 수집합니다."""
    print(f"  -> [{ticker}] 애널리스트 데이터 수집 중...")
    stock = yf.Ticker(ticker)
    info = stock.info

    current_price = info.get('currentPrice')
    target_mean = info.get('targetMeanPrice')

    upside = "N/A"
    if current_price and target_mean and current_price != 0:
        upside = round(((target_mean / current_price) - 1) * 100, 2)

    return {
        'Ticker': ticker,
        '애널리스트 종합 의견': str(info.get('recommendationKey', 'N/A')).upper(),
        '참여 애널리스트(명)': info.get('numberOfAnalystOpinions', 'N/A'),
        '현재가($)_analyst': current_price if current_price else 'N/A',
        '평균 목표가($)': target_mean if target_mean else 'N/A',
        '최고 목표가($)': info.get('targetHighPrice', 'N/A'),
        '상승 여력(%)': upside
    }

def get_news_analysis(ticker, company_name):
    """최근 뉴스 데이터를 수집하고 AI를 통해 분석합니다."""
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
        ddg_results = ddgs.news(keywords=kw, timelimit='w', max_results=20)
        if ddg_results:
            for news in ddg_results:
                title = news.get('title', '')
                summary = news.get('body', '요약 없음')
                date_str = news.get('date', '')[:10]
                if title and summary:
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
        "detailed_summary": "- 핵심내용1\\n- 핵심내용2\\n- 향후전망 등 상세 작성 (개행문자는 \\n으로 이스케이프)"
    }}

    [분석할 뉴스 헤드라인 및 요약본 리스트]
    {news_text}
    """

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
                time.sleep(5)  # 에러 시 대기 시간 증가
                continue
            print(f"  -> [{ticker}] AI 분석 최종 실패.")
            return {'Ticker': ticker, 'AI 심층 분석': f'분석 실패 (에러: {str(e)[:50]})', '분석뉴스건수': len(combined), '시장센티멘트': '중립'}
    return {'Ticker': ticker, 'AI 심층 분석': '분석 실패', '분석뉴스건수': len(combined), '시장센티멘트': '중립'}

# ==========================================
# 4. 전체 파이프라인 실행
# ==========================================
all_stock_data = []
print("\nጥ3 전 종목 데이터 수집 및 분석 시작...")
for ticker in tickers:
    print(f"\n[{ticker}] 분석 중...")
    company_name = ticker_to_name.get(ticker, ticker)

    try:
        momentum_data = get_momentum_data(ticker)
        time.sleep(1) # API 호출 간격 조절
        fundamental_valuation_data = get_fundamental_and_valuation_data(ticker)
        time.sleep(1) # API 호출 간격 조절
        analyst_data = get_analyst_data(ticker)
        time.sleep(1) # API 호출 간격 조절
        news_analysis_data = get_news_analysis(ticker, company_name)
        time.sleep(3) # AI 모델 호출은 더 긴 간격 조절

        combined_data = {}
        combined_data.update(momentum_data)
        combined_data.update(fundamental_valuation_data)
        combined_data.update(analyst_data)
        combined_data.update(news_analysis_data)
        combined_data['종목명'] = company_name

        all_stock_data.append(combined_data)

    except Exception as e:
        print(f"❌ [{ticker}] 데이터 수집 및 분석 중 치명적인 오류 발생: {e}")
        all_stock_data.append({'Ticker': ticker, '종목명': company_name, '오류': str(e)})

# ==========================================
# 5. 결과 DataFrame 생성 및 정제
# ==========================================
master_df = pd.DataFrame(all_stock_data)

# 'Ticker'와 '현재가($)_analyst'가 중복될 수 있으므로, 최종 병합 시점에 정리
# '현재가($)'가 momentum_data에서 오고, '현재가($)_analyst'가 analyst_data에서 오는 경우
# '현재가($)_analyst'는 삭제하거나 필요에 따라 선택
if '현재가($)_analyst' in master_df.columns:
    # 만약 현재가($)가 NaN이고 현재가($)_analyst가 있으면 이를 사용 (우선순위)
    master_df['현재가($)'] = master_df['현재가($)'].replace('N/A', np.nan)
    master_df['현재가($)_analyst'] = master_df['현재가($)_analyst'].replace('N/A', np.nan)
    master_df['현재가($)'] = master_df['현재가($)'].fillna(master_df['현재가($)_analyst'])
    master_df = master_df.drop(columns=['현재가($)_analyst'])

# '영업이익률'과 '영업이익률_info' 컬럼이 생성될 수 있으므로 병합 처리 (예: info가 우선)
if '영업이익률_info' in master_df.columns:
    master_df['영업이익률'] = master_df['영업이익률_info']
    master_df = master_df.drop(columns=['영업이익률_info'])

# 'Ticker' 컬럼은 제거하고 '종목명'을 맨 앞으로
master_df_final = master_df.drop(columns=['Ticker'])
master_df_final.insert(0, '종목명', master_df['종목명'])

# 결측치 및 특수값 정제
master_df_cleaned = master_df_final.replace([np.inf, -np.inf], np.nan).fillna('N/A')
master_df_cleaned.columns = [str(col).replace('\n', ' ').strip() for col in master_df_cleaned.columns]

print(f"\n데이터 통합 완료: {master_df_cleaned.shape[0]}종목, {master_df_cleaned.shape[1]}개 지표")

# ==========================================
# 6. 구글 시트 인증 및 업로드
# ==========================================
SHEET_NAME = "주식_실시간데이터"
TAB_NAME = "주식 데이터"

try:
    # GCP 서비스 계정 키를 파일로 저장
    gcp_credentials = json.loads(gcp_json_str)
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(gcp_credentials, scope)
    gc = gspread.authorize(creds)

    sh = gc.open(SHEET_NAME)

    try:
        worksheet = sh.worksheet(TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        print(f"알림: '{TAB_NAME}' 탭이 없어 새로 생성합니다.")
        worksheet = sh.add_worksheet(title=TAB_NAME, rows="100", cols="50")

    worksheet.clear()
    data_to_upload = [master_df_cleaned.columns.values.tolist()] + master_df_cleaned.values.tolist()
    worksheet.update(range_name='A1', values=data_to_upload)

    print(f"\n✅ 성공: '{SHEET_NAME}' 시트의 '{TAB_NAME}' 탭으로 최신 데이터 전송이 완료되었습니다!")
    display(master_df_cleaned.head())

except gspread.exceptions.SpreadsheetNotFound:
    print(f"❌ 에러: '{SHEET_NAME}' 시트를 찾을 수 없습니다. 시트 이름 또는 권한을 확인하세요.")
except Exception as e:
    print(f"❌ 구글 시트 업로드 중 기타 오류 발생: {e}")

print("\n파이프라인 실행 완료.")
