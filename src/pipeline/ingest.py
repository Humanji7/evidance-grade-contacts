from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, List

from .fetchers.static import StaticFetcher, FetchResult  
from .fetchers.playwright import PlaywrightFetcher, PlaywrightResult
from .escalation import decide_escalation, EscalationDecision
from .extractors import ContactExtractor
from src.schemas import Contact
from src.evidence import EvidenceBuilder


@dataclass
class IngestResult:
    """Result of ingestion pipeline with method tracking and extracted contacts."""
    url: str
    method: str  # "static" or "playwright"
    success: bool
    html: str | None
    status_code: int
    contacts: List[Contact] = None  # Extracted contacts with evidence packages
    escalation_decision: Optional[EscalationDecision] = None
    error: Optional[str] = None
    
    def __post_init__(self):
        if self.contacts is None:
            self.contacts = []


class DomainTracker:
    """Tracks per-domain headless usage for guardrails (percentage-based)."""
    
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
        """Check if headless usage is within guardrails (percentage)."""
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
    
    class HeadlessBudget:
        """Global headless budget with per-domain and global caps."""
        def __init__(self, domain_cap: int = 2, global_cap: int = 10):
            self.domain_cap = int(domain_cap)
            self.global_cap = int(global_cap)
            self._per_domain: Dict[str, int] = {}
            self._global_used = 0
        
        def can_spend(self, domain: str) -> bool:
            if self._global_used >= self.global_cap:
                return False
            used = self._per_domain.get(domain, 0)
            return used < self.domain_cap
        
        def spend(self, domain: str) -> None:
            self._global_used += 1
            self._per_domain[domain] = self._per_domain.get(domain, 0) + 1
        
        def remaining(self, domain: str) -> tuple[int, int]:
            return (max(0, self.domain_cap - self._per_domain.get(domain, 0)), max(0, self.global_cap - self._global_used))

    def __init__(
        self,
        *,
        static_fetcher: Optional[StaticFetcher] = None,
        playwright_fetcher: Optional[PlaywrightFetcher] = None,
        domain_tracker: Optional[DomainTracker] = None,
        contact_extractor: Optional[ContactExtractor] = None,
        evidence_builder: Optional[EvidenceBuilder] = None,
        enable_headless: bool = True,
        static_timeout_s: float | None = None,
        aggressive_static: bool = False,
        headless_budget: Optional[HeadlessBudget] = None,
    ):
        # Allow overriding static timeout for faster demos/runs
        if static_fetcher is None:
            self.static_fetcher = StaticFetcher(timeout_s=float(static_timeout_s or 12.0))
        else:
            self.static_fetcher = static_fetcher
        self.playwright_fetcher = playwright_fetcher or PlaywrightFetcher()
        self.domain_tracker = domain_tracker or DomainTracker()
        
        # Initialize evidence and extraction components
        self.evidence_builder = evidence_builder or EvidenceBuilder()
        self.aggressive_static = bool(aggressive_static)
        self.contact_extractor = contact_extractor or ContactExtractor(self.evidence_builder, aggressive_static=self.aggressive_static)
        self.enable_headless = bool(enable_headless)
        # New guarded budgets
        self.headless_budget = headless_budget or IngestPipeline.HeadlessBudget()
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL for tracking."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc.lower()
    
    def _is_target_url(self, url: str) -> bool:
        from urllib.parse import urlparse
        import re
        p = urlparse(url)
        path = (p.path or '').lower()
        # Target-only paths for headless prioritization
        # /(our-)?team|people|leadership|management
        return re.search(r'/(our-)?team|people|leadership|management', path, re.IGNORECASE) is not None
    
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
                    contacts=[],
                    error="Blocked by robots.txt"
                )
            
            if static_result.status_code >= 400:
                return IngestResult(
                    url=url,
                    method="static", 
                    success=False,
                    html=static_result.html,
                    status_code=static_result.status_code,
                    contacts=[],
                    error=f"HTTP {static_result.status_code}"
                )
            # Step 2: Decide escalation first
            is_target = self._is_target_url(url)
            selector_hits = self._count_selector_hits(static_result.html)
            escalation = decide_escalation(static_result, selector_hits)

            contacts_static: List[Contact] | None = None
            # Only extract contacts from static HTML when we are not already escalating
            if not escalation.escalate:
                if static_result.mime == "text/html" and static_result.html:
                    contacts_static = self.contact_extractor.extract_from_static_html(
                        static_result.html, url
                    )
                else:
                    contacts_static = []
                # Smart escalation rule — target URL with 0 contacts
                if self.enable_headless and is_target and len(contacts_static) == 0:
                    escalation = EscalationDecision(escalate=True, reasons=(escalation.reasons + ["target_url_no_contacts"]))
            else:
                # Escalation planned: apply soft rule to JS-only markers if static already yields ≥1
                js_only = all(str(r).startswith("js:") for r in escalation.reasons)
                if js_only and static_result.mime == "text/html" and static_result.html:
                    tmp_contacts = self.contact_extractor.extract_from_static_html(static_result.html, url)
                    if tmp_contacts and selector_hits > 0:
                        contacts_static = tmp_contacts
                        escalation = EscalationDecision(escalate=False, reasons=escalation.reasons)

            # Hard guard: do not escalate non-target paths (preserve headless budget)
            if not is_target:
                escalation = EscalationDecision(escalate=False, reasons=escalation.reasons)

            # Step 3: If no escalation or headless disabled → return static success
            if (not escalation.escalate) or (not self.enable_headless):
                final_contacts = contacts_static if contacts_static is not None else []
                return IngestResult(
                    url=url,
                    method="static",
                    success=True,
                    html=static_result.html,
                    status_code=static_result.status_code,
                    contacts=final_contacts,
                    escalation_decision=escalation,
                )
            
            # Step 4: Escalation needed - check guardrails (percentage + hard budgets)
            if not self.domain_tracker.can_use_headless(domain):
                print("headless budget exhausted")
                return IngestResult(
                    url=url,
                    method="static",
                    success=False,
                    html=static_result.html,
                    status_code=static_result.status_code,
                    contacts=contacts_static,
                    escalation_decision=escalation,
                    error=f"Headless quota exceeded for {domain}"
                )
            if not self.headless_budget.can_spend(domain):
                print("headless budget exhausted")
                return IngestResult(
                    url=url,
                    method="static",
                    success=False,
                    html=static_result.html,
                    status_code=static_result.status_code,
                    contacts=contacts_static,
                    escalation_decision=escalation,
                    error=f"Headless budget exhausted (domain={domain})"
                )
            
            # Step 5: Escalate to Playwright
            print(f"via playwright: reasons={escalation.reasons}")
            # Record headless usage before invoking DOM extractor
            self.domain_tracker.record_fetch(domain, "playwright")
            self.headless_budget.spend(domain)

            try:
                dom_method = getattr(self.contact_extractor, 'extract_with_playwright', None)
                if callable(dom_method):
                    contacts = dom_method(url)
                    if not isinstance(contacts, list):
                        raise TypeError("extract_with_playwright did not return a list")
                else:
                    raise AttributeError("No extract_with_playwright method")
            except Exception:
                # Fallback: use fetcher HTML and static extractor (for backward-compatible tests)
                pw = self.playwright_fetcher.fetch(url)
                if pw.error:
                    # Fall back to static results (do not return empty on PW error)
                    print("playwright returned error; falling back to static extraction")
                    return IngestResult(
                        url=url,
                        method="static",
                        success=True,
                        html=static_result.html,
                        status_code=static_result.status_code,
                        contacts=contacts_static,
                        escalation_decision=escalation,
                    )
                contacts = self.contact_extractor.extract_from_static_html(pw.html or "", url)
                # Keep method=playwright for this HTML-based fallback to satisfy existing tests
                return IngestResult(
                    url=url,
                    method="playwright",
                    success=True,
                    html=pw.html,
                    status_code=pw.status_code,
                    contacts=contacts,
                    escalation_decision=escalation
                )

            # If DOM extractor returned results, return them; otherwise fallback to static results
            if len(contacts) > 0:
                return IngestResult(
                    url=url,
                    method="playwright",
                    success=True,
                    html=None,
                    status_code=200,
                    contacts=contacts,
                    escalation_decision=escalation
                )
            else:
                print("playwright returned 0; falling back to static extraction")
                return IngestResult(
                    url=url,
                    method="static",
                    success=True,
                    html=static_result.html,
                    status_code=static_result.status_code,
                    contacts=contacts_static,
                    escalation_decision=escalation
                )
        
        except Exception as e:
            return IngestResult(
                url=url,
                method="unknown",
                success=False, 
                html=None,
                status_code=0,
                contacts=[],
                error=f"Pipeline error: {str(e)}"
            )
    
    def close(self) -> None:
        """Clean up resources."""
        self.static_fetcher.close()
