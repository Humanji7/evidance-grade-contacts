import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.pipeline.export import consolidate_per_person, ContactExporter
from src.schemas import Contact, ContactType, Evidence


def make_evidence(source_url: str, selector: str, verb: str) -> Evidence:
    return Evidence(
        source_url=source_url,
        selector_or_xpath=selector,
        verbatim_quote=verb,
        dom_node_screenshot="evidence/test.png",
        timestamp=datetime.now(timezone.utc),
        parser_version="0.1.0-test",
        content_hash=("a" * 64),
    )


def test_consolidation_picks_best_email_phone_vcard(tmp_path: Path):
    company = "Example Inc."
    person = "Jane Doe"
    role = "Head of Marketing"

    t0 = datetime.now(timezone.utc)
    t1 = t0 + timedelta(seconds=10)
    t2 = t1 + timedelta(seconds=10)

    # Email candidates
    c_email_corp = Contact(
        company=company,
        person_name=person,
        role_title=role,
        contact_type=ContactType.EMAIL,
        contact_value="jane.doe@example.com",
        evidence=make_evidence("https://example.com/team", "div.card a[href*='mailto:']", "jane.doe@example.com"),
        captured_at=t2,
    )
    c_email_generic = Contact(
        company=company,
        person_name=person,
        role_title=role,
        contact_type=ContactType.EMAIL,
        contact_value="info@example.com",
        evidence=make_evidence("https://example.com/contact", "div.card a[href*='mailto:']", "info@example.com"),
        captured_at=t1,
    )

    # Phone candidates (prefer non-toll-free and anchor)
    c_phone_tf = Contact(
        company=company,
        person_name=person,
        role_title=role,
        contact_type=ContactType.PHONE,
        contact_value="8001234567",
        evidence=make_evidence("https://example.com/team", "div.card a[href*='tel:']", "800-123-4567"),
        captured_at=t1,
    )
    c_phone_local = Contact(
        company=company,
        person_name=person,
        role_title=role,
        contact_type=ContactType.PHONE,
        contact_value="5551234567",
        evidence=make_evidence("https://example.com/team", "div.card a[href*='tel:']", "+1 555 123 4567"),
        captured_at=t2,
    )

    # vCard (already attributed by extractor)
    c_vcard = Contact(
        company=company,
        person_name=person,
        role_title=role,
        contact_type=ContactType.LINK,
        contact_value="https://example.com/people/jane-doe.vcf",
        evidence=make_evidence("https://example.com/team", "div.card a[href$='.vcf']", "Download vCard"),
        captured_at=t0,
    )

    consolidated = consolidate_per_person([c_email_generic, c_email_corp, c_phone_tf, c_phone_local, c_vcard])
    assert len(consolidated) == 1
    row = consolidated[0]

    assert row["company"] == company
    assert row["person_name"] == person
    assert row["role_title"] == role

    # Best email should be corporate non-generic
    assert row["email"] == "jane.doe@example.com"
    # Best phone should be non toll-free
    assert row["phone"] == "5551234567"
    # vCard kept
    assert row["vcard"].endswith(".vcf")

    # Source URLs should be present
    assert "/team" in row["source_url_email"].lower()
    assert "/team" in row["source_url_phone"].lower()
    assert "/team" in row["source_url_vcard"].lower()

    # Write files
    exporter = ContactExporter(output_dir=tmp_path)
    csv_path = exporter.to_people_csv(consolidated)
    json_path = exporter.to_people_json(consolidated)

    assert csv_path.exists()
    assert json_path.exists()

    # CSV has one row
    with open(csv_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1

    # JSON has one object
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list) and len(data) == 1


def test_consolidation_prefers_corporate_over_generic_email():
    company = "Acme Corp"
    person = "Bob Builder"
    role = "Manager"
    base_ev = make_evidence("https://acme.com/team", "div a[href*='mailto:']", "bob@acme.com")

    corp = Contact(
        company=company, person_name=person, role_title=role,
        contact_type=ContactType.EMAIL, contact_value="bob.builder@acme.com",
        evidence=base_ev, captured_at=datetime.now(timezone.utc),
    )
    generic = Contact(
        company=company, person_name=person, role_title=role,
        contact_type=ContactType.EMAIL, contact_value="info@acme.com",
        evidence=base_ev, captured_at=datetime.now(timezone.utc),
    )

    row = consolidate_per_person([generic, corp])[0]
    assert row["email"] == "bob.builder@acme.com"


def test_name_normalization_groups_variants():
    company = "Law Firm"
    name1 = "J. W. Alberstadt, Jr."
    name2 = "J. W.Alberstadt, Jr."
    ev = make_evidence("https://lawfirm.com/our-team", "div a[href*='mailto:']", "jw@lawfirm.com")

    a = Contact(
        company=company, person_name=name1, role_title="Partner",
        contact_type=ContactType.EMAIL, contact_value="jw@lawfirm.com",
        evidence=ev, captured_at=datetime.now(timezone.utc),
    )
    b = Contact(
        company=company, person_name=name2, role_title="Partner",
        contact_type=ContactType.PHONE, contact_value="5551234567",
        evidence=make_evidence("https://lawfirm.com/our-team", "div a[href*='tel:']", "555-123-4567"),
        captured_at=datetime.now(timezone.utc),
    )

    consolidated = consolidate_per_person([a, b])
    assert len(consolidated) == 1


def test_non_person_rows_excluded_from_people():
    company = "Bank"
    ev = make_evidence("https://bank.com/contact", "div", "Contact Us")
    a = Contact(
        company=company, person_name="Mailing Address", role_title="Unknown",
        contact_type=ContactType.EMAIL, contact_value="info@bank.com",
        evidence=ev, captured_at=datetime.now(timezone.utc),
    )
    b = Contact(
        company=company, person_name="Click here for support", role_title="Unknown",
        contact_type=ContactType.PHONE, contact_value="8001234567",
        evidence=ev, captured_at=datetime.now(timezone.utc),
    )
    consolidated = consolidate_per_person([a, b])
    assert consolidated == []


def test_email_matching_local_part_against_name_tokens():
    company = "Acme"
    person = "Ethan Bevan"
    # One matching email and one non-matching local-part
    ev_team = make_evidence("https://acme.com/our-team", "div a[href*='mailto:']", "ethan.bevan@acme.com")
    ev_other = make_evidence("https://acme.com/contact", "div a[href*='mailto:']", "bchurchill@acme.com")

    good = Contact(
        company=company, person_name=person, role_title="Engineer",
        contact_type=ContactType.EMAIL, contact_value="ethan.bevan@acme.com",
        evidence=ev_team, captured_at=datetime.now(timezone.utc),
    )
    bad = Contact(
        company=company, person_name=person, role_title="Engineer",
        contact_type=ContactType.EMAIL, contact_value="bchurchill@acme.com",
        evidence=ev_other, captured_at=datetime.now(timezone.utc),
    )

    row = consolidate_per_person([bad, good])[0]
    assert row["email"] == "ethan.bevan@acme.com"


def test_phone_prefers_href_and_rejects_date_like_text():
    company = "Law Firm"
    person = "Joseph Dorfler"

    # Href phone (should be chosen and normalized to digits)
    phone_href = Contact(
        company=company, person_name=person, role_title="Attorney",
        contact_type=ContactType.PHONE, contact_value="(617) 556-3867",
        evidence=make_evidence("https://richmaylaw.com/our-team", "a[href*='tel:']", "tel:+1 (617) 556-3867"),
        captured_at=datetime.now(timezone.utc),
    )
    # Text-only phone (should not be chosen when href exists)
    phone_text = Contact(
        company=company, person_name=person, role_title="Attorney",
        contact_type=ContactType.PHONE, contact_value="617 555 0000",
        evidence=make_evidence("https://richmaylaw.com/our-team", "span.phone", "617 555 0000"),
        captured_at=datetime.now(timezone.utc),
    )

    row = consolidate_per_person([phone_text, phone_href])[0]
    assert row["phone"] == "6175563867"

    # If only a text phone that looks like a date, do not pick any phone
    only_date_like = Contact(
        company=company, person_name=person, role_title="Attorney",
        contact_type=ContactType.PHONE, contact_value="2023101000",  # 10 digits starting with 20...
        evidence=make_evidence("https://richmaylaw.com/our-team", "span.phone", "2023-10-10 00"),
        captured_at=datetime.now(timezone.utc),
    )
    row2 = consolidate_per_person([only_date_like])[0]
    assert row2["phone"] == ""
