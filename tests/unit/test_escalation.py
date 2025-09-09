from __future__ import annotations

from src.pipeline.escalation import decide_escalation, detect_anti_bot
from src.pipeline.fetchers.static import FetchResult


def _fr(**kw):
    defaults = dict(url="https://example.com", status_code=200, mime="text/html", content_length=8000, html="<html><body>Hello</body></html>", headers={})
    defaults.update(kw)
    return FetchResult(**defaults)


def test_no_escalation_when_html_ok_and_hits_positive():
    dec = decide_escalation(_fr(), selector_hits=3)
    assert dec.escalate is False
    assert dec.reasons == []


def test_escalate_on_non_html_mime():
    dec = decide_escalation(_fr(mime="application/json"), selector_hits=3)
    assert dec.escalate is True
    assert any("mime!=text/html" in r for r in dec.reasons)


def test_escalate_on_zero_hits_and_small_page():
    dec = decide_escalation(_fr(content_length=1024), selector_hits=0)
    assert dec.escalate is True
    assert any("content_length<5KiB" in r for r in dec.reasons)


def test_detect_anti_bot():
    html = "<title>Just a moment...</title><div>Enable JavaScript and cookies to continue</div>"
    assert detect_anti_bot(html) is True
    dec = decide_escalation(_fr(html=html, content_length=4096), selector_hits=5)
    assert dec.escalate is True
    assert any("anti-bot" in r for r in dec.reasons)
