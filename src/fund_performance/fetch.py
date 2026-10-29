""" Fetches the approved pages in config/sources.yaml (spec Section 8.2). Plain code, no AI: the URLs come from
the config only, and the page text is what the Search Agent summarises.

A page that fails (HTTP error, no connection) or comes back nearly empty (JavaScript-only or blocked) is
reported with its reason, so the caller can flag it and run a web search instead.
"""
import asyncio
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable
import requests
from fund_performance.config import ApprovedSource, FetchSettings

GetFn = Callable[[str, FetchSettings], tuple[int, str]]       # url, settings -> (HTTP status, HTML)
SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "head"}
BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table"}


@dataclass
class FetchedPage:
    source: ApprovedSource
    text: str = ""
    title: str = ""
    problem: str | None = None           # why the page cannot be used; None when it can

    @property
    def ok(self) -> bool:
        return self.problem is None


class _TextParser(HTMLParser):
    """ Visible text only: scripts, styles and the head are dropped; the title is kept on its own """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag in SKIP_TAGS:
            self._skip += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """ (title, visible text), with runs of spaces and blank lines collapsed """
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return " ".join(parser.title.split()), "\n".join(line for line in lines if line)


def http_get(url: str, settings: FetchSettings) -> tuple[int, str]:
    response = requests.get(url, timeout=settings.timeout_seconds, headers={"User-Agent": settings.user_agent})
    return response.status_code, response.text


def fetch_page(source: ApprovedSource, settings: FetchSettings, get: GetFn = http_get) -> FetchedPage:
    try:
        status, html = get(source.url, settings)
    except Exception as e:                                   # no connection, timeout, TLS: the page is blocked
        return FetchedPage(source, problem=f"could not be fetched ({type(e).__name__})")
    if status != 200:
        return FetchedPage(source, problem=f"could not be fetched (HTTP {status})")
    title, text = html_to_text(html)
    if len(text) < settings.min_page_chars:
        return FetchedPage(source, title=title, problem=f"nearly empty ({len(text)} characters of text; "
                                                        "likely JavaScript-only or blocked)")
    return FetchedPage(source, text=text[: settings.max_page_chars], title=title)


async def fetch_pages(sources: list[ApprovedSource], settings: FetchSettings, get: GetFn = http_get) -> list[FetchedPage]:
    """ All approved pages, fetched in parallel, in config order """
    return list(await asyncio.gather(*(asyncio.to_thread(fetch_page, s, settings, get) for s in sources)))
