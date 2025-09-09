from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .fetchers.static import StaticFetcher, FetchResult  
from .fetchers.playwright import PlaywrightFetcher, PlaywrightResult
from .escalation import decide_escalation, EscalationDecision


@dataclass
class IngestResult:
    """Result of ingestion pipeline with method tracking."""
    url: str
    method: str  # "static" or "playwright"
    success: bool
    html: str | None
    status_code: int
    escalation_decision: Optional[EscalationDecision] = None
    error: Optional[str] = None


class DomainTracker:
    """Tracks per-domain headless usage for guardrails."""
    
    def __init__(self, max_headless_pct: float = 0.2):
        self.max_headless_pct = max_headless_pct
        self._domain_stats: Dict[str, Dict[str, int]] = {}  # domain -> {static: N, headless: N}
    
    def record_fetch(self, domain: str, method: str) -> None:
        """Record a fetch for domain statistics."""
        if domain not in self._domain_stats:
            self._domain_stats[domain] = {"static": 0, "headless": 0}
        
        if method == "playwright":
            self._domain_stats[domain]["headless"] += 1
        else:
            self._domain_stats[domain]["static"] += 1
    
    def can_use_headless(self, domain: str) -> bool:
        """Check if headless usage is within guardrails."""
        stats = self._domain_stats.get(domain, {"static": 0, "headless": 0})
        total = stats["static"] + stats["headless"]
        
        if total == 0:
            return True
        
        current_pct = stats["headless"] / total
        return current_pct < self.max_headless_pct


class IngestPipeline:
    """Main ingestion pipeline: static-first with escalation to Playwright.
    
    Implements guardrails from WARP.md:
    - max_headless_pct_per_domain ≤ 0.2
    - Static-first approach
    - Escalation only on specific conditions
    """
    
    def __init__(
        self,
        *,
        static_fetcher: Optional[StaticFetcher] = None,
        playwright_fetcher: Optional[PlaywrightFetcher] = None,
        domain_tracker: Optional[DomainTracker] = None,
    ):
        self.static_fetcher = static_fetcher or StaticFetcher()
        self.playwright_fetcher = playwright_fetcher or PlaywrightFetcher()
        self.domain_tracker = domain_tracker or DomainTracker()
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL for tracking."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc.lower()
    
    def _count_selector_hits(self, html: str | None) -> int:
        """Count hits for target selectors (people/team pages).
        
        This is a simplified version - real implementation would use
        proper CSS selectors for team/leadership/people sections.
        """
        if not html:
            return 0
        
        # Simple heuristic: count common team/leadership indicators
        target_terms = ["team", "leadership", "management", "people", "staff", "executives"]
        html_lower = html.lower()
        hits = sum(1 for term in target_terms if term in html_lower)
        return hits
    
    def ingest(self, url: str) -> IngestResult:
        """Main ingestion method: static-first with escalation."""
        domain = self._extract_domain(url)
        
        try:
            # Step 1: Always try static first
            static_result = self.static_fetcher.fetch(url)
            self.domain_tracker.record_fetch(domain, "static")
            
            if static_result.blocked_by_robots:
                return IngestResult(
                    url=url,
                    method="static",
                    success=False,
                    html=None,
                    status_code=0,
                    error="Blocked by robots.txt"
                )
            
            if static_result.status_code >= 400:
                return IngestResult(
                    url=url,
                    method="static", 
                    success=False,
                    html=static_result.html,
                    status_code=static_result.status_code,
                    error=f"HTTP {static_result.status_code}"
                )
            
            # Step 2: Check escalation conditions
            selector_hits = self._count_selector_hits(static_result.html)
            escalation = decide_escalation(static_result, selector_hits)
            
            if not escalation.escalate:
                # Static success - no escalation needed
                return IngestResult(
                    url=url,
                    method="static",
                    success=True,
                    html=static_result.html,
                    status_code=static_result.status_code,
                    escalation_decision=escalation
                )
            
            # Step 3: Escalation needed - check guardrails
            if not self.domain_tracker.can_use_headless(domain):
                return IngestResult(
                    url=url,
                    method="static",
                    success=False,
                    html=static_result.html,
                    status_code=static_result.status_code,
                    escalation_decision=escalation,
                    error=f"Headless quota exceeded for {domain}"
                )
            
            # Step 4: Escalate to Playwright
            playwright_result = self.playwright_fetcher.fetch(url)
            self.domain_tracker.record_fetch(domain, "playwright")
            
            if playwright_result.error:
                return IngestResult(
                    url=url,
                    method="playwright",
                    success=False,
                    html=playwright_result.html,
                    status_code=playwright_result.status_code,
                    escalation_decision=escalation,
                    error=playwright_result.error
                )
            
            return IngestResult(
                url=url,
                method="playwright",
                success=True,
                html=playwright_result.html,
                status_code=playwright_result.status_code,
                escalation_decision=escalation
            )
        
        except Exception as e:
            return IngestResult(
                url=url,
                method="unknown",
                success=False, 
                html=None,
                status_code=0,
                error=f"Pipeline error: {str(e)}"
            )
    
    def close(self) -> None:
        """Clean up resources."""
        self.static_fetcher.close()
