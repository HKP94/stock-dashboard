from src import enrich_gemini as E
from src import ingest_news as N


def test_google_queries_include_risk_variants_for_kr():
    queries = N.build_google_news_queries("005930.KS", "삼성전자")
    assert "삼성전자 리스크" in queries
    assert "삼성전자 하락" in queries
    assert "삼성전자 우려" in queries


def test_google_queries_include_risk_variants_for_us():
    queries = N.build_google_news_queries("AAPL", "Apple")
    assert "AAPL risk" in queries
    assert "AAPL decline" in queries
    assert "AAPL concern" in queries


def test_news_prompt_mentions_negative_risk_news_importance():
    prompt = E._build_news_prompt(
        ticker="AAPL",
        company_name="Apple",
        news_items=[{"source": "yahoo", "published_at": None, "title": "Risk grows", "body": "supply chain concern"}],
    )
    assert "부정·리스크 뉴스도 중요하게 평가하라" in prompt

