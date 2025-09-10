from __future__ import annotations

from unittest.mock import Mock

from src.pipeline.ingest import IngestPipeline
from src.pipeline.fetchers.static import FetchResult
from src.pipeline.fetchers.playwright import PlaywrightResult
from src.schemas import Contact, Evidence, ContactType
from datetime import datetime, timezone


def test_ingest_escalates_on_target_url_with_zero_contacts_and_within_budget():
    url = "https://example.com/team"

    # Static fetch returns a team-like page but no mailto/tel and no extracted contacts
    static_fetcher = Mock()
    static_fetcher.fetch.return_value = FetchResult(
        url=url,
        status_code=200,
        mime="text/html",
        content_length=50_000,
        html="""
        <html><body>
            <h1>Our Team</h1>
            <div class="team member card">John Doe</div>
            <div class="team member card">Jane Roe</div>
            <div class="team member card">Alan Poe</div>
        </body></html>
        """,
        headers={},
        blocked_by_robots=False,
    )

    # Playwright fetch returns richer HTML
    playwright_fetcher = Mock()
    pw_html = """
    <html><body>
        <h1>Our Team</h1>
        <div class="team member card">
            <h3>John Doe</h3>
            <a href="mailto:john@example.com">Email</a>
        </div>
    </body></html>
    """
    playwright_fetcher.fetch.return_value = PlaywrightResult(
        url=url,
        status_code=200,
        html=pw_html,
        page_title="Team - Example",
        error=None,
    )

    # Contact extractor returns [] for static HTML and one contact for PW HTML
    ev = Evidence(
        source_url=url,
        selector_or_xpath=".team a[href*='mailto:']",
        verbatim_quote="john@example.com",
        dom_node_screenshot="evidence/test.png",
        timestamp=datetime.now(timezone.utc),
        parser_version="0.1.0-test",
        content_hash="a" * 64,
    )
    contact = Contact(
        company="Example Inc.",
        person_name="John Doe",
        role_title="CEO",
        contact_type=ContactType.EMAIL,
        contact_value="john@example.com",
        evidence=ev,
        captured_at=datetime.now(timezone.utc),
    )
    contact_extractor = Mock()
    # Cards heuristic likely escalates immediately → expect a single call for Playwright HTML returning contact
    contact_extractor.extract_from_static_html.side_effect = [[contact]]

    pipeline = IngestPipeline(
        static_fetcher=static_fetcher,
        playwright_fetcher=playwright_fetcher,
        contact_extractor=contact_extractor,
        enable_headless=True,
    )

    res = pipeline.ingest(url)

    assert res.success is True
    assert res.method == "playwright"
    assert res.contacts and res.contacts[0].contact_value == "john@example.com"
    assert res.escalation_decision and res.escalation_decision.escalate is True
    # Smart reason should include target-url no contacts or cards heuristic
    assert any("target_url_no_contacts" in r or "cards_present_but_no_mailto_tel" in r for r in res.escalation_decision.reasons)

