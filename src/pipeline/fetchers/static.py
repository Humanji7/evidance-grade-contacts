from __future__ import annotations

import re
import typing as t
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib import robotparser

import httpx


DEFAULT_UA = "EGC-StaticFetcher/0.1 (+https://example.com)"


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    mime: str | None
    content_length: int
    html: str | None
    headers: dict[str, str]
    blocked_by_robots: bool = False


class StaticFetcher:
    """Static-first HTML fetcher with optional robots.txt enforcement.

    - Uses httpx for network IO
    - Parses robots.txt using urllib.robotparser
    - Does NOT execute JavaScript
    """

    def __init__(
        self,
        *,
        timeout_s: float = 12.0,
        user_agent: str = DEFAULT_UA,
        respect_robots: bool = True,
    ) -> None:
        self.timeout_s = timeout_s
        self.user_agent = user_agent
        self.respect_robots = respect_robots
        self._client = httpx.Client(timeout=self.timeout_s, headers={"User-Agent": self.user_agent})

    def close(self) -> None:
        self._client.close()

    def _robots_allows(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            resp = self._client.get(robots_url)
        except Exception:
            # If cannot retrieve robots, default allow in PoC
            return True
        if resp.status_code >= 400:
            return True
        rp = robotparser.RobotFileParser()
        rp.parse(resp.text.splitlines())
        # Try with our UA, else fallback to '*'
        return rp.can_fetch(self.user_agent, url) and rp.can_fetch("*", url)

    def fetch(self, url: str) -> FetchResult:
        if not self._robots_allows(url):
            return FetchResult(
                url=url,
                status_code=0,
                mime=None,
                content_length=0,
                html=None,
                headers={},
                blocked_by_robots=True,
            )
        resp = self._client.get(url, follow_redirects=True)
        mime = resp.headers.get("Content-Type")
        mime_main = None
        if mime:
            mime_main = mime.split(";")[0].strip().lower()
        html_text = None
        if mime_main == "text/html":
            html_text = resp.text
        content_length = len(resp.content or b"")
        # Normalize small anti-bot placeholders: keep text, decision handled upstream
        return FetchResult(
            url=str(resp.request.url),
            status_code=resp.status_code,
            mime=mime_main,
            content_length=content_length,
            html=html_text,
            headers={k: v for k, v in resp.headers.items()},
        )
