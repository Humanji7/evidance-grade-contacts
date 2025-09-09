from __future__ import annotations

from urllib.parse import urlparse

import httpx

from src.pipeline.fetchers.static import StaticFetcher


class _MockTransport(httpx.BaseTransport):
    def __init__(self, routes: dict[str, tuple[int, dict[str, str], bytes]]):
        self.routes = routes

    def handle_request(self, request: httpx.Request) -> httpx.Response:  # type: ignore[override]
        url = str(request.url)
        status, headers, body = self.routes.get(url, (404, {"Content-Type": "text/plain"}, b"Not Found"))
        return httpx.Response(status, headers=headers, content=body, request=request)


def test_static_fetch_allows_when_no_robots(monkeypatch):
    robots = (404, {"Content-Type": "text/plain"}, b"")
    page = (200, {"Content-Type": "text/html; charset=utf-8"}, b"<html>OK</html>")
    routes = {
        "https://example.com/robots.txt": robots,
        "https://example.com/": page,
    }
    transport = _MockTransport(routes)

    fetcher = StaticFetcher(respect_robots=True)
    # Patch client to use mock transport
    fetcher._client = httpx.Client(transport=transport)

    res = fetcher.fetch("https://example.com/")
    assert res.blocked_by_robots is False
    assert res.status_code == 200
    assert res.mime == "text/html"
    assert res.html is not None


def test_static_fetch_blocks_when_robots_disallow(monkeypatch):
    robots_body = b"User-agent: *\nDisallow: /secret\n"
    robots = (200, {"Content-Type": "text/plain"}, robots_body)
    routes = {
        "https://example.com/robots.txt": robots,
    }
    transport = _MockTransport(routes)

    fetcher = StaticFetcher(respect_robots=True, user_agent="EGC-StaticFetcher/0.1")
    fetcher._client = httpx.Client(transport=transport)

    res = fetcher.fetch("https://example.com/secret")
    assert res.blocked_by_robots is True
    assert res.html is None
    assert res.status_code == 0
