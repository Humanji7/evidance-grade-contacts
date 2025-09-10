import pytest
from unittest.mock import Mock
from datetime import datetime, timezone

from src.pipeline.extractors import ContactExtractor
from src.evidence.builder import EvidenceBuilder
from src.schemas import Evidence, ContactType


def make_ev(src, sel, verb):
    return Evidence(
        source_url=src,
        selector_or_xpath=sel,
        verbatim_quote=verb,
        dom_node_screenshot="evidence/test.png",
        timestamp=datetime.now(timezone.utc),
        parser_version="0.1.0-test",
        content_hash="a" * 64,
    )


def test_mailto_with_params_sanitized_lowercase():
    html = '''<div class="team-member">
        <h3>John Doe</h3>
        <a href="mailto:User@Site.COM?subject=Hi">Email</a>
    </div>'''
    mock_builder = Mock(spec=EvidenceBuilder)
    mock_builder.create_evidence_static.side_effect = lambda **kw: make_ev(
        kw.get("source_url"), kw.get("selector"), kw.get("verbatim_text") or ""
    )

    extractor = ContactExtractor(evidence_builder=mock_builder)
    contacts = extractor.extract_from_static_html(html, 'https://site.com/our-team')

    emails = [c for c in contacts if c.contact_type == ContactType.EMAIL]
    assert emails, "Expected an email to be extracted"
    assert emails[0].contact_value == 'user@site.com'


def test_mailto_broken_href_fallback_to_link_text():
    html = '''<div class="team-member">
        <h3>Jane Doe</h3>
        <a href="mailto:broken">jane.doe@site.com</a>
    </div>'''
    mock_builder = Mock(spec=EvidenceBuilder)
    mock_builder.create_evidence_static.side_effect = lambda **kw: make_ev(
        kw.get("source_url"), kw.get("selector"), kw.get("verbatim_text") or ""
    )

    extractor = ContactExtractor(evidence_builder=mock_builder)
    contacts = extractor.extract_from_static_html(html, 'https://site.com/our-team')

    emails = [c for c in contacts if c.contact_type == ContactType.EMAIL]
    assert emails and emails[0].contact_value == 'jane.doe@site.com'

