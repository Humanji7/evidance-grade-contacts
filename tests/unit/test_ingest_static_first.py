from __future__ import annotations

from unittest.mock import Mock
from datetime import datetime, timezone

from src.pipeline.ingest import IngestPipeline
from src.pipeline.fetchers.static import FetchResult
from src.pipeline.escalation import EscalationDecision
from src.schemas import Evidence, Contact, ContactType


def _mk_contact(url: str, person: str = "John Doe", role: str = "CEO", value: str = "john@example.com", ctype: ContactType = ContactType.EMAIL) -> Contact:
    ev = Evidence(
        source_url=url,
        selector_or_xpath=".team a[href*='mailto:']",
        verbatim_quote=value,
        dom_node_screenshot="evidence/test.png",
        timestamp=datetime.now(timezone.utc),
        parser_version="0.1.0-test",
        content_hash="a" * 64,
    )
    return Contact(
        company="Example Inc.",
        person_name=person,
        role_title=role,
        contact_type=ctype,
        contact_value=value,
        evidence=ev,
        captured_at=datetime.now(timezone.utc),
    )


def test_static_contacts_plus_js_markers_do_not_escalate():
    url = "https://example.com/people"

    static_fetcher = Mock()
    static_fetcher.fetch.return_value = FetchResult(
        url=url,
        status_code=200,
        mime="text/html",
        content_length=12000,
        # has js marker data-reactroot; but static will return contacts
        html="""
        <html><body>
            <div id="root" data-reactroot="">
                <h1>People</h1>
                <div class="team-member">
                    <h3>John Doe</h3>
                    <a href="mailto:john@example.com">Email</a>
                </div>
            </div>
        </body></html>
        """,
        headers={},
        blocked_by_robots=False,
    )

    contact_extractor = Mock()
    contact_extractor.extract_from_static_html.return_value = [_mk_contact(url)]

    pipeline = IngestPipeline(static_fetcher=static_fetcher, contact_extractor=contact_extractor, enable_headless=True)
    res = pipeline.ingest(url)

    assert res.method == "static"
    assert res.success is True
    assert res.escalation_decision is not None
    assert res.escalation_decision.escalate is False


def test_target_zero_static_contacts_escalate_then_fallback_when_pw_zero():
    url = "https://example.com/team"

    static_fetcher = Mock()
    static_fetcher.fetch.return_value = FetchResult(
        url=url,
        status_code=200,
        mime="text/html",
        content_length=16000,
        html="""
        <html><body>
            <h1>Our Team</h1>
            <div class="team member card">No anchors here</div>
        </body></html>
        """,
        headers={},
        blocked_by_robots=False,
    )

    # Static extraction returns no contacts
    contact_extractor = Mock()
    contact_extractor.extract_from_static_html.return_value = []
    # Playwright DOM path returns 0 contacts
    contact_extractor.extract_with_playwright.return_value = []

    pipeline = IngestPipeline(static_fetcher=static_fetcher, contact_extractor=contact_extractor, enable_headless=True)

    res = pipeline.ingest(url)

    # Fallback to static results
    assert res.method == "static"
    assert res.success is True
    assert res.contacts == []

