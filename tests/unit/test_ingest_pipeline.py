from __future__ import annotations

from unittest.mock import Mock

from src.pipeline.ingest import IngestPipeline, DomainTracker
from src.pipeline.fetchers.static import FetchResult
from src.pipeline.fetchers.playwright import PlaywrightResult
from src.pipeline.escalation import EscalationDecision


def test_domain_tracker_allows_first_headless():
    tracker = DomainTracker(max_headless_pct=0.2)
    assert tracker.can_use_headless("example.com") is True


def test_domain_tracker_respects_quota():
    tracker = DomainTracker(max_headless_pct=0.2)
    
    # Record 4 static, should allow 1 headless (20%)
    for _ in range(4):
        tracker.record_fetch("example.com", "static")
    
    assert tracker.can_use_headless("example.com") is True
    
    # Record 1 headless - should still be within quota
    tracker.record_fetch("example.com", "playwright")
    assert tracker.can_use_headless("example.com") is False  # Now at 20%, next would exceed


def test_pipeline_static_success_no_escalation():
    # Mock static fetcher returning good HTML
    static_fetcher = Mock()
    static_fetcher.fetch.return_value = FetchResult(
        url="https://example.com/team",
        status_code=200,
        mime="text/html",
        content_length=8000,
        html="<html><body><h1>Our Team</h1><div>Leadership team...</div></body></html>",
        headers={},
        blocked_by_robots=False
    )
    
    pipeline = IngestPipeline(static_fetcher=static_fetcher)
    result = pipeline.ingest("https://example.com/team")
    
    assert result.success is True
    assert result.method == "static"
    assert result.html is not None
    assert result.escalation_decision is not None
    assert result.escalation_decision.escalate is False  # Has team content, no escalation


def test_pipeline_escalates_on_anti_bot():
    # Mock static fetcher returning Cloudflare challenge
    static_fetcher = Mock()
    static_fetcher.fetch.return_value = FetchResult(
        url="https://example.com/team",
        status_code=200,
        mime="text/html", 
        content_length=2000,
        html="<title>Just a moment...</title><div>Enable JavaScript and cookies to continue</div>",
        headers={},
        blocked_by_robots=False
    )
    
    # Mock playwright fetcher success
    playwright_fetcher = Mock()
    playwright_fetcher.fetch.return_value = PlaywrightResult(
        url="https://example.com/team",
        status_code=200,
        html="<html><body><h1>Our Team</h1><div class='team-members'>Real content</div></body></html>",
        page_title="Team - Example Corp",
        error=None
    )
    
    pipeline = IngestPipeline(
        static_fetcher=static_fetcher,
        playwright_fetcher=playwright_fetcher
    )
    
    result = pipeline.ingest("https://example.com/team")
    
    assert result.success is True
    assert result.method == "playwright"
    assert result.escalation_decision is not None
    assert result.escalation_decision.escalate is True
    assert "anti-bot" in " ".join(result.escalation_decision.reasons)


def test_pipeline_respects_headless_quota():
    # Mock static fetcher that always triggers escalation
    static_fetcher = Mock()
    static_fetcher.fetch.return_value = FetchResult(
        url="https://example.com/team", 
        status_code=200,
        mime="application/json",  # Will trigger escalation
        content_length=1000,
        html=None,
        headers={},
        blocked_by_robots=False
    )
    
    # Mock domain tracker that denies headless
    domain_tracker = Mock()
    domain_tracker.can_use_headless.return_value = False
    
    pipeline = IngestPipeline(
        static_fetcher=static_fetcher,
        domain_tracker=domain_tracker
    )
    
    result = pipeline.ingest("https://example.com/team")
    
    assert result.success is False
    assert result.method == "static"
    assert "quota exceeded" in result.error


def test_pipeline_handles_robots_block():
    static_fetcher = Mock()
    static_fetcher.fetch.return_value = FetchResult(
        url="https://example.com/team",
        status_code=0,
        mime=None,
        content_length=0,
        html=None,
        headers={},
        blocked_by_robots=True
    )
    
    pipeline = IngestPipeline(static_fetcher=static_fetcher)
    result = pipeline.ingest("https://example.com/team")
    
    assert result.success is False
    assert result.method == "static" 
    assert "robots.txt" in result.error
