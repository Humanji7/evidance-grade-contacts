from src.pipeline.extractors import ContactExtractor
from src.evidence import EvidenceBuilder
from selectolax.parser import HTMLParser

def _run(html, url='https://example.com/team', aggressive=False):
    ex = ContactExtractor(EvidenceBuilder(), aggressive_static=aggressive)
    return ex.extract_from_static_html(html, url)

def test_phone_text_requires_markers_and_length():
    html = '''<html><body>
      <div class="team-member">
        <h3>John Doe</h3>
        <p class="title">Engineer</p>
        <p>20240602</p>
      </div>
      <div class="team-member">
        <h3>Jane Roe</h3>
        <p class="title">Engineer</p>
        <p>Phone: +1 (401) 555-1234</p>
      </div>
    </body></html>'''
    cs = _run(html, aggressive=True)
    # Should only include Jane's valid phone
    phones = [c for c in cs if c.contact_type.value == 'phone']
    assert any('4015551234' in c.contact_value or '14015551234' in c.contact_value for c in phones)
    # No 8-digit date misclassified
    assert all(c.contact_value != '20240602' for c in phones)

def test_role_stoplist_to_unknown():
    html = '''<html><body>
      <div class="team-member">
        <h3>John Doe</h3>
        <p class="title">Areas of Focus:</p>
        <a href="mailto:john@example.com">Email</a>
      </div>
    </body></html>'''
    cs = _run(html, aggressive=True)
    assert any(c.role_title.strip().lower() == 'unknown' for c in cs)

