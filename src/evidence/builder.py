"""
Evidence Package Builder - Mini Evidence Package Creation

Creates complete Mini Evidence Packages with all 7 required fields:
1. source_url - Source page URL
2. selector_or_xpath - CSS/XPath used for extraction  
3. verbatim_quote - Verbatim innerText content
4. dom_node_screenshot - Node screenshot reference
5. timestamp - ISO 8601 extraction time
6. parser_version - Tool version for reproducibility
7. content_hash - SHA-256 of normalized node text

Records missing any field are marked UNVERIFIED per PoC specification.
"""

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from playwright.sync_api import Page, ElementHandle, Locator
from selectolax.parser import HTMLParser, Node

from ..schemas import Evidence


class EvidenceBuilder:
    """
    Creates Mini Evidence Packages for extracted contact data.
    
    Supports both static HTML (selectolax) and dynamic content (Playwright)
    with complete evidence trail generation including screenshots.
    """
    
    def __init__(self, parser_version: str = "0.1.0-poc", screenshot_dir: str = "evidence"):
        """
        Initialize Evidence Builder.
        
        Args:
            parser_version: Semantic version for reproducibility (e.g. "0.1.0-poc")
            screenshot_dir: Directory for storing DOM node screenshots
        """
        self.parser_version = parser_version
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
    
    def create_evidence_static(
        self,
        source_url: str,
        selector: str,
        node: Node,
        verbatim_text: str
    ) -> Evidence:
        """
        Create evidence package for static HTML extraction (selectolax).
        
        Args:
            source_url: URL where data was extracted
            selector: CSS selector used for extraction
            node: selectolax Node object
            verbatim_text: Verbatim text content from node
            
        Returns:
            Complete Evidence object with all 7 fields
        """
        timestamp = datetime.now(timezone.utc)
        content_hash = self._compute_content_hash(verbatim_text)
        
        # Generate screenshot placeholder for static content
        # In static mode we can't take real screenshots, so we use a placeholder
        screenshot_path = self._generate_screenshot_path("static", source_url, selector)
        
        return Evidence(
            source_url=source_url,
            selector_or_xpath=selector,
            verbatim_quote=verbatim_text,
            dom_node_screenshot=str(screenshot_path),
            timestamp=timestamp,
            parser_version=self.parser_version,
            content_hash=content_hash
        )
    
    def create_evidence_playwright(
        self,
        source_url: str,
        selector: str,
        page: Page,
        element: Union[ElementHandle, Locator],
        verbatim_text: str
    ) -> Evidence:
        """
        Create evidence package for dynamic content extraction (Playwright).
        
        Args:
            source_url: URL where data was extracted
            selector: CSS selector or XPath used for extraction
            page: Playwright Page object
            element: Playwright Element/Locator object
            verbatim_text: Verbatim text content from element
            
        Returns:
            Complete Evidence object with all 7 fields including real screenshot
        """
        timestamp = datetime.now(timezone.utc)
        content_hash = self._compute_content_hash(verbatim_text)
        
        # Take real screenshot of the DOM element
        screenshot_path = self._capture_element_screenshot(
            page, element, source_url, selector
        )
        
        return Evidence(
            source_url=source_url,
            selector_or_xpath=selector,
            verbatim_quote=verbatim_text,
            dom_node_screenshot=str(screenshot_path),
            timestamp=timestamp,
            parser_version=self.parser_version,
            content_hash=content_hash
        )
    
    def _compute_content_hash(self, text: str) -> str:
        """
        Compute SHA-256 hash of normalized text content.
        
        Args:
            text: Raw text content
            
        Returns:
            64-character SHA-256 hash (lowercase hex)
        """
        # Normalize text: strip whitespace, convert to lowercase
        normalized = text.strip().lower()
        
        # Compute SHA-256 hash
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    
    def _generate_screenshot_path(self, mode: str, url: str, selector: str) -> Path:
        """
        Generate unique screenshot file path.
        
        Args:
            mode: "static" or "playwright"
            url: Source URL
            selector: CSS selector/XPath
            
        Returns:
            Path object for screenshot file
        """
        # Create safe filename from URL and selector
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        selector_hash = hashlib.md5(selector.encode()).hexdigest()[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        filename = f"{mode}_{url_hash}_{selector_hash}_{timestamp}.png"
        return self.screenshot_dir / filename
    
    def _capture_element_screenshot(
        self,
        page: Page,
        element: Union[ElementHandle, Locator],
        url: str,
        selector: str
    ) -> Path:
        """
        Capture screenshot of specific DOM element using Playwright.
        
        Args:
            page: Playwright Page object
            element: Element or Locator to screenshot
            url: Source URL for filename generation
            selector: Selector for filename generation
            
        Returns:
            Path to saved screenshot file
        """
        screenshot_path = self._generate_screenshot_path("playwright", url, selector)
        
        try:
            # Take element screenshot
            if hasattr(element, 'screenshot'):
                # Locator object
                element.screenshot(path=str(screenshot_path))
            else:
                # ElementHandle object
                element.screenshot(path=str(screenshot_path))
                
            return screenshot_path
            
        except Exception as e:
            # Fallback: create placeholder file if screenshot fails
            placeholder_path = self._generate_screenshot_path("failed", url, selector)
            placeholder_path.write_text(f"Screenshot failed: {str(e)}")
            return placeholder_path
    
    def validate_evidence_completeness(self, evidence: Evidence) -> bool:
        """
        Validate that evidence package has all 7 required fields.
        
        Args:
            evidence: Evidence object to validate
            
        Returns:
            True if all fields present and valid, False otherwise
        """
        try:
            # All fields are required in Pydantic model, so if object
            # was created successfully, all fields are present
            
            # Additional validation: check if screenshot file exists
            if evidence.dom_node_screenshot:
                screenshot_path = Path(evidence.dom_node_screenshot)
                if not screenshot_path.exists() and not screenshot_path.is_absolute():
                    # Try relative to screenshot_dir
                    screenshot_path = self.screenshot_dir / evidence.dom_node_screenshot
                    
                if not screenshot_path.exists():
                    return False
            
            # Check hash format
            if not evidence.content_hash or len(evidence.content_hash) != 64:
                return False
                
            return True
            
        except Exception:
            return False
