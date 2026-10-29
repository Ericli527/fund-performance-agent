""" Approved sources (step 9b): config/sources.yaml and the page fetcher. HTTP is mocked; nothing goes online """
import asyncio
import time
import pytest
from pydantic import ValidationError
from fund_performance.config import ApprovedSource, FetchSettings, SourcesConfig, load_sources
from fund_performance.fetch import fetch_page, fetch_pages, html_to_text

SETTINGS = FetchSettings(timeout_seconds=5, min_page_chars=100, max_page_chars=500, user_agent="test")
FUND_PAGE = ApprovedSource(name="Fund page", url="https://example.com/fund", topic="fund_news")
INDEX_PAGE = ApprovedSource(name="Index page", url="https://example.com/index", topic="market_drivers")
ARTICLE = ("<html><head><title>Sample Fund P Acc</title><style>p{color:red}</style>"
           "<script>var x = 'hidden';</script></head><body><nav>Menu</nav>"
           "<p>Sample World Index Fund P Acc. Ongoing charge 0.10%. As at 30/09/2026.</p>"
           + "<p>More plain text about the fund and its index.</p>" * 12 + "</body></html>")


def test_test1_sources_are_approved_https_pages():
    s = load_sources()
    found = s.for_fund("GB00BJS8SH10", "S&P 500")
    assert [x.topic for x in found] == ["fund_news", "fund_news", "market_drivers"]
    assert all(x.url.startswith("https://") for x in found)
    assert "fidelity.co.uk" in found[0].url and "charges-and-key-documents" in found[1].url
    assert found[2].url == "https://www.spglobal.com/spdji/en/indices/equity/sp-500/"
    assert s.for_fund("GB0000000000", "s&p 500") == found[2:]          # unknown fund: its market's pages only
    assert s.for_fund("GB0000000000", "FTSE 100") == []


def test_sources_config_is_checked():
    with pytest.raises(ValidationError):
        ApprovedSource(name="x", url="http://example.com", topic="fund_news")        # https only
    with pytest.raises(ValidationError):
        ApprovedSource(name="x", url="https://example.com", topic="manager_changes")
    with pytest.raises(ValidationError):
        SourcesConfig.model_validate({"fetch": SETTINGS.model_dump(), "fund": {}})   # misspelt key


def test_html_to_text_keeps_visible_text_only():
    title, text = html_to_text(ARTICLE)
    assert title == "Sample Fund P Acc"
    assert "Sample World Index Fund P Acc. Ongoing charge 0.10%. As at 30/09/2026." in text
    assert "hidden" not in text and "color" not in text and "Menu" in text


def test_a_readable_page_is_cut_to_the_limit():
    page = fetch_page(FUND_PAGE, SETTINGS, get=lambda url, s: (200, ARTICLE))
    assert page.ok and page.title == "Sample Fund P Acc" and len(page.text) == 500


@pytest.mark.parametrize("get, problem", [
    (lambda url, s: (200, "<html><body><div id='root'></div><script>app()</script></body></html>"), "nearly empty"),
    (lambda url, s: (403, "Forbidden"), "could not be fetched (HTTP 403)"),
    (lambda url, s: (_ for _ in ()).throw(ConnectionError("no route")), "could not be fetched (ConnectionError)"),
])
def test_a_blocked_or_empty_page_says_why(get, problem):
    page = fetch_page(FUND_PAGE, SETTINGS, get=get)
    assert not page.ok and problem in page.problem and page.text == ""


def test_pages_are_fetched_in_parallel_in_config_order():
    def slow(url, s):
        time.sleep(0.3)
        return 200, ARTICLE
    started = time.perf_counter()
    pages = asyncio.run(fetch_pages([FUND_PAGE, INDEX_PAGE], SETTINGS, get=slow))
    assert time.perf_counter() - started < 0.55
    assert [p.source.name for p in pages] == ["Fund page", "Index page"]
