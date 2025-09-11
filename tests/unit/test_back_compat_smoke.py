from datetime import datetime, timezone

from src.pipeline.export import consolidate_per_person
from src.schemas import Contact, ContactType, Evidence


def make_ev(url: str, selector: str, verb: str) -> Evidence:
    return Evidence(
        source_url=url,
        selector_or_xpath=selector,
        verbatim_quote=verb,
        dom_node_screenshot="evidence/node.png",
        timestamp=datetime.now(timezone.utc),
        parser_version="0.1.0-test",
        content_hash=("a" * 64),
    )


def test_back_compat_people_consolidation_smoke():
    company = "Acme Corp"

    # Build a few contacts for one person with full evidence
    c_email = Contact(
        company=company,
        person_name="Jane Doe",
        role_title="Manager",
        contact_type=ContactType.EMAIL,
        contact_value="jane.doe@acme.com",
        evidence=make_ev("https://acme.com/our-team", "div a[href*='mailto:']", "jane.doe@acme.com"),
        captured_at=datetime.now(timezone.utc),
    )
    c_phone_href = Contact(
        company=company,
        person_name="Jane Doe",
        role_title="Manager",
        contact_type=ContactType.PHONE,
        contact_value="5551234567",
        evidence=make_ev("https://acme.com/our-team", "div a[href*='tel:']", "+1 555 123 4567"),
        captured_at=datetime.now(timezone.utc),
    )
    c_vcard = Contact(
        company=company,
        person_name="Jane Doe",
        role_title="Manager",
        contact_type=ContactType.LINK,
        contact_value="https://acme.com/people/jane-doe.vcf",
        evidence=make_ev("https://acme.com/our-team", "div a[href$='.vcf']", "Download vCard"),
        captured_at=datetime.now(timezone.utc),
    )

    rows = consolidate_per_person([c_email, c_phone_href, c_vcard])

    # Smoke: returns non-empty list with old keys present and no exceptions
    assert isinstance(rows, list) and len(rows) >= 1
    row = rows[0]
    base_keys = {
        "company",
        "person_name",
        "role_title",
        "email",
        "phone",
        "vcard",
        "source_url_email",
        "source_url_phone",
        "source_url_vcard",
    }
    assert base_keys.issubset(set(row.keys()))

