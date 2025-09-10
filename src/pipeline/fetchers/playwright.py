from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page


@dataclass(frozen=True)
class PlaywrightResult:
    url: str
    status_code: int
    html: str | None
    page_title: str | None
    error: str | None = None


class PlaywrightFetcher:
    """Headless browser fetcher for JavaScript-heavy pages and anti-bot bypass.
    
    Uses Playwright with security-first settings:
    - Sandbox enabled (no --no-sandbox)
    - Extensions and plugins disabled  
    - Headless mode only
    """

    def __init__(
        self,
        *,
        timeout_ms: int = 20000,
        user_agent: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ) -> None:
        self.timeout_ms = timeout_ms
        self.user_agent = user_agent

    def fetch(self, url: str) -> PlaywrightResult:
        """Fetch page using Playwright headless browser."""
        try:
            with sync_playwright() as p:
                # Launch browser with security-first settings (from gold_extractor.py)
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-dev-shm-usage',     # Prevent /dev/shm issues in containers
                        '--disable-gpu',                # Disable GPU for headless
                        '--disable-extensions',         # No browser extensions
                        '--disable-plugins',            # No plugins
                        '--no-first-run',               # Skip first run setup
                        '--disable-default-apps',       # No default apps
                        '--disable-background-timer-throttling',  # Consistent timing
                    ]  # Note: --no-sandbox REMOVED for security (sandbox enabled)
                )
                
                context = browser.new_context(user_agent=self.user_agent)
                page = context.new_page()
                
                # Navigate with timeout
                response = page.goto(url, wait_until="load", timeout=self.timeout_ms)
                
                if not response:
                    browser.close()
                    return PlaywrightResult(url=url, status_code=0, html=None, page_title=None, error="No response received")
                
                status_code = response.status
                
                # Wait for likely team/member sections to render, then a micro pause for lazy content
                try:
                    page.wait_for_selector("section, .team, [class*=team], [class*=member], article", timeout=2000)
                except Exception:
                    pass
                page.wait_for_timeout(200)
                
                # Extract content
                html = page.content()
                title = page.title()
                
                browser.close()
                
                return PlaywrightResult(
                    url=url,
                    status_code=status_code, 
                    html=html,
                    page_title=title,
                    error=None
                )
                
        except Exception as e:
            return PlaywrightResult(
                url=url,
                status_code=0,
                html=None, 
                page_title=None,
                error=str(e)
            )
