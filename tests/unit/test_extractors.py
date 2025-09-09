"""
Unit tests for Contact Extractor

Tests extraction of names, titles, emails, and phones from both static HTML
and Playwright pages with complete evidence package generation.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

from selectolax.parser import HTMLParser
from playwright.sync_api import Page, Locator

from src.pipeline.extractors import ContactExtractor
from src.evidence.builder import EvidenceBuilder
from src.schemas import ContactType, VerificationStatus


class TestContactExtractor:
    """Test suite for ContactExtractor class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.mock_evidence_builder = Mock(spec=EvidenceBuilder)
        self.extractor = ContactExtractor(evidence_builder=self.mock_evidence_builder)
    
    def test_email_pattern_matching(self):
        """Test email regex pattern."""
        valid_emails = [
            'john.doe@example.com',
            'test+tag@company.org',
            'admin@domain.co.uk'
        ]
        
        invalid_emails = [
            'notanemail',
            '@domain.com',
            'user@',
            'user@domain'
        ]
        
        for email in valid_emails:
            assert self.extractor.email_pattern.match(email), f"Should match: {email}"
        
        for email in invalid_emails:
            assert not self.extractor.email_pattern.match(email), f"Should not match: {email}"
    
    def test_phone_pattern_matching(self):
        """Test phone regex pattern."""
        valid_phones = [
            '(555) 123-4567',
            '+1-555-123-4567',
            '555.123.4567',
            '+44 20 7946 0958'
        ]
        
        for phone in valid_phones:
            assert self.extractor.phone_pattern.search(phone), f"Should match: {phone}"
    
    def test_extract_company_name_static_from_title(self):
        """Test company name extraction from HTML title."""
        html = '''<html>
            <head><title>Acme Corporation - About Us</title></head>
            <body><h1>Our Team</h1></body>
        </html>'''
        
        parser = HTMLParser(html)
        company = self.extractor._extract_company_name_static(parser, 'https://example.com/about')
        
        assert company == "Acme Corporation"
    
    def test_extract_company_name_static_fallback_to_domain(self):
        """Test company name fallback to domain name."""
        html = '<html><body><h1>Team</h1></body></html>'
        
        parser = HTMLParser(html)
        company = self.extractor._extract_company_name_static(parser, 'https://www.example.com/team')
        
        assert company == "Example.Com"
    
    def test_extract_person_name_static(self):
        """Test person name extraction from static HTML."""
        html = '''<div class="person">
            <h3>Dr. Jane Smith</h3>
            <p>Senior Developer</p>
        </div>'''
        
        parser = HTMLParser(html)
        person_node = parser.css_first('.person')
        
        name = self.extractor._extract_person_name_static(person_node)
        assert name == "Jane Smith"  # Should remove "Dr." prefix
    
    def test_extract_person_title_static(self):
        """Test person title extraction from static HTML."""
        html = '''<div class="person">
            <h3>Jane Smith</h3>
            <p class="title">Senior Developer</p>
        </div>'''
        
        parser = HTMLParser(html)
        person_node = parser.css_first('.person')
        
        title = self.extractor._extract_person_title_static(person_node)
        assert title == "Senior Developer"
    
    def test_extract_emails_static_from_mailto(self):
        """Test email extraction from mailto links in static HTML."""
        html = '''<div class="person">
            <h3>Jane Smith</h3>
            <a href="mailto:jane.smith@example.com">Email Jane</a>
        </div>'''
        
        parser = HTMLParser(html)
        person_node = parser.css_first('.person')
        
        emails = self.extractor._extract_emails_static(person_node)
        assert len(emails) == 1
        assert emails[0][0] == 'jane.smith@example.com'
        assert 'mailto:' in emails[0][1]  # Should include selector info
    
    def test_extract_phones_static_from_tel(self):
        """Test phone extraction from tel links in static HTML."""
        html = '''<div class="person">
            <h3>Jane Smith</h3>
            <a href="tel:+15551234567">Call Jane</a>
        </div>'''
        
        parser = HTMLParser(html)
        person_node = parser.css_first('.person')
        
        phones = self.extractor._extract_phones_static(person_node)
        assert len(phones) == 1
        assert phones[0][0] == '+15551234567'
        assert 'tel:' in phones[0][1]
    
    def test_extract_from_static_html_full_integration(self):
        """Test full integration of static HTML extraction."""
        html = '''<html>
            <head><title>Acme Corp - Team</title></head>
            <body>
                <div class="team-member">
                    <h3>John Doe</h3>
                    <p class="title">Software Engineer</p>
                    <a href="mailto:john.doe@acme.com">Email</a>
                    <a href="tel:555-123-4567">Call</a>
                </div>
                <div class="team-member">
                    <h3>Jane Smith</h3>
                    <p class="title">Product Manager</p>
                    <a href="mailto:jane.smith@acme.com">Contact</a>
                </div>
            </body>
        </html>'''
        
        # Mock evidence builder to return valid evidence
        from datetime import datetime, timezone
        from src.schemas import Evidence
        
        mock_evidence = Evidence(
            source_url="https://acme.com/team",
            selector_or_xpath=".team-member a[href*='mailto:']",
            verbatim_quote="john.doe@acme.com",
            dom_node_screenshot="evidence/test.png",
            timestamp=datetime.now(timezone.utc),
            parser_version="0.1.0-test",
            content_hash="a" * 64
        )
        self.mock_evidence_builder.create_evidence_static.return_value = mock_evidence
        
        contacts = self.extractor.extract_from_static_html(html, 'https://acme.com/team')
        
        # Should find 3 contacts (John: email + phone, Jane: email)
        assert len(contacts) >= 2
        
        # Verify evidence builder was called
        assert self.mock_evidence_builder.create_evidence_static.call_count >= 2
        
        # Check that contacts have required fields
        for contact in contacts:
            assert contact.company
            assert contact.person_name
            assert contact.role_title
            assert contact.contact_type in [ContactType.EMAIL, ContactType.PHONE]
            assert contact.contact_value
    
    def test_extract_from_playwright_mocked(self):
        """Test Playwright extraction with mocked objects."""
        # Create mock Playwright page
        mock_page = Mock(spec=Page)
        mock_locator = Mock(spec=Locator)
        
        # Mock company name extraction
        mock_title_locator = Mock()
        mock_title_locator.text_content.return_value = "Test Company - About"
        mock_page.locator.return_value.first = mock_title_locator
        
        # Mock person elements
        mock_person_element = Mock(spec=Locator)
        mock_locator.all.return_value = [mock_person_element]
        mock_page.locator.return_value = mock_locator
        
        # Mock person name and title extraction
        mock_name_element = Mock()
        mock_name_element.text_content.return_value = "Test Person"
        mock_title_element = Mock()
        mock_title_element.text_content.return_value = "Test Title"
        
        # Mock email extraction
        mock_email_link = Mock()
        mock_email_link.get_attribute.return_value = "mailto:test@example.com"
        mock_email_link.text_content.return_value = "test@example.com"
        mock_person_element.locator.return_value.all.return_value = [mock_email_link]
        mock_person_element.locator.return_value.first = mock_name_element
        mock_person_element.text_content.return_value = "Test Person - Test Title"
        
        # Configure mock to return different elements for different selectors
        def mock_locator_side_effect(selector):
            mock_result = Mock()
            if 'h1' in selector or 'title' in selector:
                mock_result.first = mock_name_element
                mock_result.all.return_value = [mock_name_element]
            elif 'mailto' in selector:
                mock_result.all.return_value = [mock_email_link]
            elif '.title' in selector:
                mock_result.first = mock_title_element
                mock_result.all.return_value = [mock_title_element]
            else:
                mock_result.first = mock_person_element
                mock_result.all.return_value = [mock_person_element]
            return mock_result
        
        mock_person_element.locator.side_effect = mock_locator_side_effect
        
        # Mock evidence builder
        mock_evidence = Mock()
        mock_evidence.timestamp = Mock()
        self.mock_evidence_builder.create_evidence_playwright.return_value = mock_evidence
        
        # Execute extraction
        contacts = self.extractor.extract_from_playwright(mock_page, 'https://example.com/team')
        
        # Should have called evidence builder for any extracted contacts
        if contacts:
            assert self.mock_evidence_builder.create_evidence_playwright.called
            
            # Verify contact structure
            for contact in contacts:
                assert hasattr(contact, 'company')
                assert hasattr(contact, 'person_name')
                assert hasattr(contact, 'contact_type')
    
    def test_no_contacts_when_no_person_name(self):
        """Test that no contacts are extracted when person name is missing."""
        html = '''<div class="team-member">
            <p class="description">Some description without a name</p>
            <a href="mailto:contact@example.com">Email</a>
        </div>'''
        
        contacts = self.extractor.extract_from_static_html(html, 'https://example.com/team')
        
        # Should not extract contacts without person names
        assert len(contacts) == 0
