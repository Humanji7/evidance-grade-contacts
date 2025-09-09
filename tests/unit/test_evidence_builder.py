"""
Unit tests for Evidence Package Builder

Tests Mini Evidence Package creation with all 7 required fields
for both static HTML and Playwright extraction methods.
"""

import tempfile
import pytest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

from selectolax.parser import HTMLParser, Node
from playwright.sync_api import Page, ElementHandle, Locator

from src.evidence.builder import EvidenceBuilder
from src.schemas import Evidence


class TestEvidenceBuilder:
    """Test suite for EvidenceBuilder class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Use temporary directory for screenshots
        self.temp_dir = tempfile.mkdtemp()
        self.builder = EvidenceBuilder(
            parser_version="0.1.0-test",
            screenshot_dir=self.temp_dir
        )
    
    def test_init_creates_screenshot_directory(self):
        """Test that initialization creates screenshot directory."""
        assert self.builder.screenshot_dir.exists()
        assert self.builder.parser_version == "0.1.0-test"
    
    def test_compute_content_hash(self):
        """Test SHA-256 content hash computation."""
        text = "Jane Doe — Head of Marketing"
        hash_result = self.builder._compute_content_hash(text)
        
        # Should be 64-character hex string
        assert len(hash_result) == 64
        assert all(c in '0123456789abcdef' for c in hash_result)
        
        # Should normalize text (same result for different whitespace)
        text_normalized = "  jane doe — head of marketing  "
        hash_normalized = self.builder._compute_content_hash(text_normalized)
        assert hash_result == hash_normalized
    
    def test_generate_screenshot_path(self):
        """Test screenshot path generation."""
        url = "https://example.com/team"
        selector = "div.person-card"
        
        path = self.builder._generate_screenshot_path("static", url, selector)
        
        # Should be in screenshot directory
        assert path.parent == self.builder.screenshot_dir
        
        # Should contain mode, hashes, and timestamp
        filename = path.name
        assert filename.startswith("static_")
        assert filename.endswith(".png")
    
    def test_create_evidence_static(self):
        """Test evidence creation for static HTML extraction."""
        # Create mock selectolax node
        html = '<div class="person">Jane Doe — Head of Marketing</div>'
        parser = HTMLParser(html)
        node = parser.css_first("div.person")
        
        url = "https://example.com/team"
        selector = "div.person"
        verbatim_text = "Jane Doe — Head of Marketing"
        
        evidence = self.builder.create_evidence_static(
            source_url=url,
            selector=selector,
            node=node,
            verbatim_text=verbatim_text
        )
        
        # Validate all 7 required fields
        assert evidence.source_url == url
        assert evidence.selector_or_xpath == selector
        assert evidence.verbatim_quote == verbatim_text
        assert evidence.dom_node_screenshot  # Should have screenshot path
        assert isinstance(evidence.timestamp, datetime)
        assert evidence.parser_version == "0.1.0-test"
        assert len(evidence.content_hash) == 64
        
        # Screenshot path should be in our temp directory
        assert self.temp_dir in evidence.dom_node_screenshot
    
    def test_create_evidence_playwright(self):
        """Test evidence creation for Playwright extraction."""
        # Create mock Playwright objects
        mock_page = Mock(spec=Page)
        mock_element = Mock(spec=Locator)
        mock_element.screenshot = Mock()
        
        url = "https://example.com/team"  
        selector = "div.person"
        verbatim_text = "Jane Doe — Head of Marketing"
        
        evidence = self.builder.create_evidence_playwright(
            source_url=url,
            selector=selector,
            page=mock_page,
            element=mock_element,
            verbatim_text=verbatim_text
        )
        
        # Validate all 7 required fields
        assert evidence.source_url == url
        assert evidence.selector_or_xpath == selector
        assert evidence.verbatim_quote == verbatim_text
        assert evidence.dom_node_screenshot  # Should have screenshot path
        assert isinstance(evidence.timestamp, datetime)
        assert evidence.parser_version == "0.1.0-test"
        assert len(evidence.content_hash) == 64
        
        # Should have called screenshot method
        mock_element.screenshot.assert_called_once()
    
    def test_capture_element_screenshot_locator(self):
        """Test element screenshot capture with Locator object."""
        mock_page = Mock(spec=Page)
        mock_locator = Mock(spec=Locator)
        mock_locator.screenshot = Mock()
        
        url = "https://example.com/test"
        selector = "div.test"
        
        screenshot_path = self.builder._capture_element_screenshot(
            mock_page, mock_locator, url, selector
        )
        
        # Should call screenshot method with path
        mock_locator.screenshot.assert_called_once()
        call_args = mock_locator.screenshot.call_args
        assert 'path' in call_args.kwargs
        
        # Should return valid path
        assert isinstance(screenshot_path, Path)
        assert screenshot_path.suffix == '.png'
    
    def test_capture_element_screenshot_element_handle(self):
        """Test element screenshot capture with ElementHandle object."""
        mock_page = Mock(spec=Page)
        mock_element = Mock(spec=ElementHandle)
        mock_element.screenshot = Mock()
        # Remove 'screenshot' from hasattr check to test ElementHandle path
        type(mock_element).screenshot = Mock()
        
        url = "https://example.com/test"
        selector = "div.test"
        
        with patch('builtins.hasattr', return_value=False):
            screenshot_path = self.builder._capture_element_screenshot(
                mock_page, mock_element, url, selector
            )
        
        # Should call screenshot method
        mock_element.screenshot.assert_called_once()
        
        # Should return valid path
        assert isinstance(screenshot_path, Path)
        assert screenshot_path.suffix == '.png'
    
    def test_capture_element_screenshot_failure(self):
        """Test screenshot capture failure handling."""
        mock_page = Mock(spec=Page)
        mock_element = Mock(spec=Locator)
        mock_element.screenshot = Mock(side_effect=Exception("Screenshot failed"))
        
        url = "https://example.com/test"
        selector = "div.test"
        
        screenshot_path = self.builder._capture_element_screenshot(
            mock_page, mock_element, url, selector
        )
        
        # Should return placeholder path on failure
        assert isinstance(screenshot_path, Path)
        assert "failed_" in screenshot_path.name
        
        # Should create placeholder file with error message
        assert screenshot_path.exists()
        content = screenshot_path.read_text()
        assert "Screenshot failed" in content
    
    def test_validate_evidence_completeness_valid(self):
        """Test evidence completeness validation for valid evidence."""
        # Create real evidence with screenshot file
        html = '<div class="person">Jane Doe</div>'
        parser = HTMLParser(html)
        node = parser.css_first("div.person")
        
        evidence = self.builder.create_evidence_static(
            source_url="https://example.com/test",
            selector="div.person",
            node=node,
            verbatim_text="Jane Doe"
        )
        
        # Create screenshot file (static mode creates placeholder)
        screenshot_path = Path(evidence.dom_node_screenshot)
        if not screenshot_path.exists():
            screenshot_path = self.builder.screenshot_dir / evidence.dom_node_screenshot
            screenshot_path.touch()
        
        # Should be valid
        assert self.builder.validate_evidence_completeness(evidence)
    
    def test_validate_evidence_completeness_missing_screenshot(self):
        """Test evidence validation with missing screenshot file."""
        evidence = Evidence(
            source_url="https://example.com/test",
            selector_or_xpath="div.person",
            verbatim_quote="Jane Doe",
            dom_node_screenshot="nonexistent.png",
            timestamp=datetime.now(timezone.utc),
            parser_version="0.1.0-test",
            content_hash="a" * 64
        )
        
        # Should be invalid due to missing screenshot
        assert not self.builder.validate_evidence_completeness(evidence)
    
    def test_validate_evidence_completeness_invalid_hash(self):
        """Test that Pydantic prevents creation of Evidence with invalid hash."""
        # Pydantic should prevent creating Evidence with invalid hash
        with pytest.raises(Exception):  # ValidationError from pydantic
            Evidence(
                source_url="https://example.com/test",
                selector_or_xpath="div.person",
                verbatim_quote="Jane Doe",
                dom_node_screenshot="test.png",
                timestamp=datetime.now(timezone.utc),
                parser_version="0.1.0-test",
                content_hash="invalid-hash"  # Should be 64 hex chars
            )
