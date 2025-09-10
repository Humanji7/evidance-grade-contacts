import os
from pathlib import Path
from typing import List, Union

import pytest

from src.pipeline.extractors import ContactExtractor
from src.evidence.builder import EvidenceBuilder
from src.schemas import ContactType


class DummyEvidenceBuilder(EvidenceBuilder):
    def _capture_element_screenshot(self, page, element, url, selector):  # type: ignore[override]
        p = Path("evidence/test_fast_sweep.png")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"png")
        return p


class StubHeading:
    def __init__(self, text: str):
        self._text = text

    def text_content(self):
        return self._text


class StubContainer:
    def __init__(self, heading_text: str = ""):
        self.heading_text = heading_text

    def query_selector(self, selector: str):
        selector = selector or ""
        if any(tok in selector for tok in ["h2", "h3", "h4", ".list-item-content__title"]):
            return StubHeading(self.heading_text)
        # no titles in this simple stub
        return None


class StubAnchor:
    def __init__(self, href: str, text: str = "", container: Union[StubContainer, None] = None, prev_heading: Union[str, None] = None):
        self._href = href
        self._text = text
        self._container = container
        self._prev_heading = prev_heading

    def get_attribute(self, name: str):
        if name == "href":
            return self._href
        return None

    def text_content(self):
        return self._text

    def query_selector(self, selector: str):
        # ancestor li[list-item]
        if selector.startswith("xpath=ancestor::li"):
            return self._container
        # preceding heading
        if selector.startswith("xpath=preceding::h2") and self._prev_heading:
            return StubHeading(self._prev_heading)
        if selector.startswith("xpath=preceding::h3") and self._prev_heading:
            return StubHeading(self._prev_heading)
        if selector.startswith("xpath=preceding::h4") and self._prev_heading:
            return StubHeading(self._prev_heading)
        return None


class StubPage:
    def __init__(self, email_anchors: List[StubAnchor], phone_anchors: List[StubAnchor]):
        self._emails = email_anchors
        self._phones = phone_anchors

    def query_selector_all(self, selector: str):
        if "mailto" in selector:
            return self._emails
        if "tel" in selector:
            return self._phones
        return []

    # Company name extractor uses page.locator('title').first.text_content(); simplify by returning None
    # The extractor falls back to hostname from URL.


def test_playwright_fast_sweep_email_and_phone():
    # Arrange
    builder = DummyEvidenceBuilder()
    extractor = ContactExtractor(evidence_builder=builder)

    container = StubContainer(heading_text="John Doe")
    email_a = StubAnchor(href="mailto:John.Doe@Example.COM?subject=Hi", text="Email John", container=container)
    phone_a = StubAnchor(href="tel:+1 (555) 123-4567", text="Call John", container=container)

    page = StubPage(email_anchors=[email_a], phone_anchors=[phone_a])

    url = "https://acme.com/our-team"

    # Act
    contacts = extractor._fast_sweep_test_hook(page, url)

    # Assert
    assert contacts, "Expected contacts extracted from fast sweep"

    emails = [c for c in contacts if c.contact_type == ContactType.EMAIL]
    phones = [c for c in contacts if c.contact_type == ContactType.PHONE]

    assert len(emails) == 1
    assert emails[0].contact_value == "john.doe@example.com"  # lowercased
    assert emails[0].person_name == "John Doe"
    assert emails[0].role_title == "Unknown"  # listing URL without explicit role
    assert "a[href*='mailto:']" in (emails[0].evidence.selector_or_xpath or "")

    assert len(phones) == 1
    assert phones[0].contact_value == "5551234567"  # NANP normalized (strip leading 1)
    assert phones[0].person_name == "John Doe"
    assert phones[0].role_title == "Unknown"
    assert "a[href*='tel:']" in (phones[0].evidence.selector_or_xpath or "")

