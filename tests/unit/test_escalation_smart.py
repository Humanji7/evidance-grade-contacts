from __future__ import annotations

import pytest

from src.pipeline.escalation import decide_escalation
from src.pipeline.fetchers.static import FetchResult


def _mk_fetch(mime: str | None, html: str | None, content_length: int) -> FetchResult:
    return FetchResult(
        url="https://example.com/x",
        status_code=200,
        mime=mime,
        content_length=content_length,
        html=html,
        headers={},
        blocked_by_robots=False,
    )


def test_escalation_triggers_on_non_html_mime():
    fetch = _mk_fetch(mime="application/json", html=None, content_length=100)
    dec = decide_escalation(fetch, selector_hits=0)
    assert dec.escalate is True
    assert any("mime!=text/html" in r for r in dec.reasons)


def test_escalation_triggers_on_js_markers():
    html = '<div data-cfemail="abcd">protected</div>'
    fetch = _mk_fetch(mime="text/html", html=html, content_length=10_000)
    dec = decide_escalation(fetch, selector_hits=5)
    assert dec.escalate is True
    assert any(r.startswith("js:") for r in dec.reasons)


def test_escalation_triggers_on_tiny_page_no_selectors():
    html = "<html><body>no team</body></html>"
    fetch = _mk_fetch(mime="text/html", html=html, content_length=1024)
    dec = decide_escalation(fetch, selector_hits=0)
    assert dec.escalate is True
    assert any("selector_hits==0" in r for r in dec.reasons)

