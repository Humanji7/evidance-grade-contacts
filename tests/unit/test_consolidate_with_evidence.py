import pytest
from datetime import datetime, timezone

from src.pipeline.export import consolidate_per_person_with_evidence
from src.pipeline.roles import DecisionLevel
from src.schemas import Contact, ContactType, Evidence


def make_evidence(url: str, selector: str, verb: str) -> Evidence:
    return Evidence(
        source_url=url,
        selector_or_xpath=selector,
        verbatim_quote=verb,
        dom_node_screenshot="evidence/node.png",
        timestamp=datetime.now(timezone.utc),
        parser_version="0.1.0-test",
        content_hash=("a" * 64),
    )


def make_email(company: str, person: str, role: str, email: str, url: str) -> Contact:
    return Contact(
        company=company,
        person_name=person,
        role_title=role,
        contact_type=ContactType.EMAIL,
        contact_value=email,
        evidence=make_evidence(url, "div a[href*='mailto:']", email),
        captured_at=datetime.now(timezone.utc),
    )


from typing import Optional

def make_phone(company: str, person: str, role: str, phone: str, url: str, verb: Optional[str] = None) -> Contact:
    return Contact(
        company=company,
        person_name=person,
        role_title=role,
        contact_type=ContactType.PHONE,
        contact_value=phone,
        evidence=make_evidence(url, "div a[href*='tel:']", verb or phone),
        captured_at=datetime.now(timezone.utc),
    )


# Case A: VERIFIED per-person record with full evidence on email+phone

def test_case_a_verified_with_full_evidence():
    company = "Example Inc."
    person = "Jane Doe"
    role = "President; Managing Director"

    c_email = make_email(company, person, role, "jane.doe@example.com", "https://example.com/team")
    c_phone = make_phone(company, person, role, "5551234567", "https://example.com/leadership", "+1 555 123 4567")

    rows = consolidate_per_person_with_evidence([c_email, c_phone])
    assert len(rows) == 1
    row = rows[0]

    # Required fields presence
    expected_keys = {
        'company','person_name','role_title','decision_level','decision_reasons',
        'email','phone','vcard','evidence_email','evidence_phone','evidence_vcard',
        'evidence_complete','verification_status'
    }
    assert set(row.keys()) == expected_keys

    assert row['company'] == company
    assert row['person_name'] == person
    assert row['role_title'] == role
    assert row['decision_level'] == 'C_SUITE'
    # Reasons contain one of the positive C_SUITE markers
    assert any(r in row['decision_reasons'] for r in ("title:president", "title:managing director"))

    # Evidence dicts for email and phone with 7 keys
    for ev_key in ('evidence_email', 'evidence_phone'):
        ev = row[ev_key]
        assert isinstance(ev, dict)
        assert set(ev.keys()) == {
            'source_url','selector_or_xpath','verbatim_quote','dom_node_screenshot','timestamp','parser_version','content_hash'
        }
    # vcard absent
    assert row['evidence_vcard'] is None

    # Evidence completeness and verification
    assert row['evidence_complete'] is True
    assert row['verification_status'] == 'VERIFIED'


# Case B: Threshold filter keeps only VP_PLUS and above

def test_case_b_threshold_filter_vp_plus():
    company = "Firm"
    a = make_email(company, "Alice A.", "Associate", "alice@firm.com", "https://firm.com/team")
    b = make_email(company, "Bob B.", "Shareholder", "bob@firm.com", "https://firm.com/our-team")

    rows = consolidate_per_person_with_evidence([a, b], min_level=DecisionLevel.VP_PLUS)
    assert len(rows) == 1
    row = rows[0]
    assert row['person_name'] == "Bob B."
    assert row['decision_level'] in ("VP_PLUS", "C_SUITE")


# Case C: Structural hint bumps Director to >= VP_PLUS

def test_case_c_structural_hint_from_url():
    company = "Example Co"
    person = "Charlie"
    role = "Director"
    email = make_email(company, person, role, "charlie@example.com", "https://example.com/company/leadership")

    rows = consolidate_per_person_with_evidence([email])
    assert len(rows) == 1
    row = rows[0]
    # Bumped by structural hint
    assert row['decision_level'] in ("VP_PLUS", "C_SUITE")
    assert any(r == "struct:leadership" for r in row['decision_reasons'])

