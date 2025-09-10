from datetime import datetime, timezone

from selectolax.parser import HTMLParser

from src.pipeline.extractors import ContactExtractor
from src.evidence.builder import EvidenceBuilder
from src.schemas import ContactType


def test_vcard_requires_name_tokens():
    html = '''<html><body>
    <div class="team-member">
      <h3>Diana Alsabe</h3>
      <p class="title">Attorney</p>
      <a href="/files/john-doe.vcf">vCard</a>
    </div>
    </body></html>'''

    eb = EvidenceBuilder(parser_version="0.1.0-test")
    extractor = ContactExtractor(evidence_builder=eb, aggressive_static=True)

    contacts = extractor.extract_from_static_html(html, "https://example.com/our-team")

    # No LINK .vcf should be attributed because filename doesn't include tokens from name
    assert all(c.contact_type != ContactType.LINK for c in contacts), "vCard with foreign name should be skipped"


def test_no_global_contains_at_email_outside_card():
    # One person card without mailto, with email only in footer outside card; one person with in-card text email
    html = '''<html><body>
    <div class="team-member">
      <h3>Jane Smith</h3>
      <p class="title">Engineer</p>
    </div>
    <div class="team-member">
      <h3>John Doe</h3>
      <p>Contact: john.doe@example.com</p>
    </div>
    <footer>
      <p>Write us: hello@outside.com</p>
    </footer>
    </body></html>'''

    eb = EvidenceBuilder(parser_version="0.1.0-test")
    extractor = ContactExtractor(evidence_builder=eb, aggressive_static=True)

    contacts = extractor.extract_from_static_html(html, "https://example.com/team")

    # Should find only one email contact (for John Doe inside his card), none from footer
    emails = [c for c in contacts if c.contact_type == ContactType.EMAIL]
    assert len(emails) == 1
    assert emails[0].person_name == "John Doe"
    assert emails[0].contact_value.endswith("@example.com")


def test_non_person_names_filtered():
    html = '''<html><body>
    <div class="team-member">
      <h3>Mailing Address</h3>
      <a href="mailto:contact@example.com">Email</a>
    </div>
    <div class="team-member">
      <h3>Real Person</h3>
      <p class="title">Manager</p>
      <a href="mailto:real.person@example.com">Email</a>
    </div>
    </body></html>'''

    eb = EvidenceBuilder(parser_version="0.1.0-test")
    extractor = ContactExtractor(evidence_builder=eb, aggressive_static=False)

    contacts = extractor.extract_from_static_html(html, "https://example.com/team")
    names = {c.person_name for c in contacts}

    # Ensure non-person card ignored
    assert "Mailing Address" not in names
    assert "Real Person" in names
