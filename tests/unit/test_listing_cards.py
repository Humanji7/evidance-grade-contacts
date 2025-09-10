import pytest
from unittest.mock import Mock, patch

from src.pipeline.extractors import ContactExtractor
from src.evidence.builder import EvidenceBuilder
from src.schemas import Evidence, ContactType
from datetime import datetime, timezone


def make_mock_evidence(src: str, selector: str, verbatim: str) -> Evidence:
    return Evidence(
        source_url=src,
        selector_or_xpath=selector,
        verbatim_quote=verbatim,
        dom_node_screenshot="evidence/test.png",
        timestamp=datetime.now(timezone.utc),
        parser_version="0.1.0-test",
        content_hash="a" * 64,
    )


def test_elementor_icons_extract_without_mailto_tel():
    # HTML simulating Elementor team member with icons and aria labels, but no mailto/tel
    html = '''<html>
    <head><title>Acme - Our Team</title></head>
    <body>
        <div class="elementor-team-member">
            <h3>Jane Smith</h3>
            <div class="contact">
                <a aria-label="Email Jane"><i class="fa fa-envelope"></i></a>
                <a aria-label="Phone Jane"><i class="fa fa-phone"></i></a>
                <span class="hidden-email">jane.smith@example.com</span>
                <span class="hidden-phone">+1 (555) 123-4567</span>
            </div>
        </div>
    </body></html>'''

    mock_builder = Mock(spec=EvidenceBuilder)
    mock_builder.create_evidence_static.side_effect = lambda **kw: make_mock_evidence(
        kw.get("source_url"), kw.get("selector"), kw.get("verbatim_text") or ""
    )
    extractor = ContactExtractor(evidence_builder=mock_builder)

    contacts = extractor.extract_from_static_html(html, 'https://example.com/our-team')

    # Expect both email and phone for Jane Smith
    emails = [c for c in contacts if c.contact_type == ContactType.EMAIL]
    phones = [c for c in contacts if c.contact_type == ContactType.PHONE]
    assert any(c.person_name == 'Jane Smith' and c.contact_value == 'jane.smith@example.com' for c in emails)
    # Phone normalized to digits only without punctuation
    assert any(c.person_name == 'Jane Smith' and c.contact_value.endswith('5551234567') for c in phones)
    # Role Unknown allowed on listing URL
    assert all(c.role_title in ("Unknown", None) for c in contacts)


def test_d1_follow_profiles_with_budget_limit():
    # Listing with 6 cards, each with a relative profile link and no contacts in-card
    def slug_and_name(i: int):
        # Use alphabetic suffix to satisfy name validation (letters in tokens)
        names = {1: 'One', 2: 'Two', 3: 'Three', 4: 'Four', 5: 'Five', 6: 'Six'}
        return f"person-{i}", f"Person {names[i]}"

    items = [slug_and_name(i) for i in range(1, 7)]
    cards_html = "".join([
        f"""
        <div class=\"team-member\">
            <h3>{name}</h3>
            <a href=\"/people/{slug}\">View profile</a>
        </div>
        """ for slug, name in items
    ])
    html = f"""
    <html><head><title>Example - Team</title></head>
    <body>{cards_html}</body></html>
    """

    # Mock EvidenceBuilder
    mock_builder = Mock(spec=EvidenceBuilder)
    mock_builder.create_evidence_static.side_effect = lambda **kw: make_mock_evidence(
        kw.get("source_url"), kw.get("selector"), kw.get("verbatim_text") or ""
    )

    extractor = ContactExtractor(evidence_builder=mock_builder)

    # Prepare fake httpx.Client
    class FakeResponse:
        def __init__(self, url: str, name: str):
            self.url = url
            self.status_code = 200
            self._headers = {'Content-Type': 'text/html; charset=utf-8'}
            # Profile page with a mailto and matching name
            self.text = f"""
            <html><body>
              <div class=\"profile\">
                <h3>{name}</h3>
                <a href=\"mailto:{name.lower().replace(' ', '')}@example.com\">Email</a>
              </div>
            </body></html>
            """
        @property
        def headers(self):
            return self._headers

    captured_urls = []
    class FakeClient:
        def __init__(self, *_, **__):
            pass
        def get(self, url):
            captured_urls.append(url)
            # Extract name from URL for response
            slug = url.split('/')[-1]
            # Convert slug like person-one -> Person One
            base = slug.replace('-', ' ').title()
            name = base.replace('Person ', 'Person ')
            return FakeResponse(url, name)
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False

    with patch('src.pipeline.extractors.httpx.Client', FakeClient):
        contacts = extractor.extract_from_static_html(html, 'https://example.com/team')

    # Only 5 profile requests should be performed due to D=1 budget limit
    assert len(captured_urls) == 5


def test_role_unknown_on_listing_when_no_title_but_email():
    html = '''<html>
        <head><title>Corp - Our Team</title></head>
        <body>
            <div class="team-member">
                <h3>John Doe</h3>
                <div class="icons">
                    <a title="Email"><i class="fa fa-envelope"></i></a>
                </div>
                <span>john.doe@example.com</span>
            </div>
        </body>
    </html>'''

    mock_builder = Mock(spec=EvidenceBuilder)
    mock_builder.create_evidence_static.side_effect = lambda **kw: make_mock_evidence(
        kw.get("source_url"), kw.get("selector"), kw.get("verbatim_text") or ""
    )
    extractor = ContactExtractor(evidence_builder=mock_builder)

    contacts = extractor.extract_from_static_html(html, 'https://example.com/our-team')
    assert any(c.person_name == 'John Doe' and c.contact_type == ContactType.EMAIL and c.role_title == 'Unknown' for c in contacts)

