import csv, json
from datetime import datetime, timezone
from src.pipeline.export import normalize_url_for_report, ContactExporter, dedupe_contacts_for_export
from src.schemas import Contact, Evidence, ContactType
from pathlib import Path

def make_contact(company, person, role, ctype, value, url, selector, ts=None):
    ev = Evidence(
        source_url=url,
        selector_or_xpath=selector,
        verbatim_quote=value,
        dom_node_screenshot="evidence/test.png",
        timestamp=ts or datetime.now(timezone.utc),
        parser_version="0.1.0-poc",
        content_hash="a"*64,
    )
    return Contact(
        company=company,
        person_name=person,
        role_title=role,
        contact_type=ContactType(ctype),
        contact_value=value,
        evidence=ev,
        captured_at=ts or datetime.now(timezone.utc),
    )


def test_to_csv_and_json_use_normalized_source_url(tmp_path: Path):
    exporter = ContactExporter(output_dir=tmp_path)
    contacts = [
        make_contact("Acme","John Doe","Engineer","email","john@acme.com","https://www.Example.com/team/?x=1#y","a[href*='mailto:']"),
    ]
    csv_path = exporter.to_csv(contacts, filename="t.csv", include_all=True)
    json_path = exporter.to_json(contacts, filename="t.json", include_all=True)

    # CSV check
    with open(csv_path, newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        rows = list(r)
        assert rows[0]['source_url'] == "https://example.com/team"

    # JSON check
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        assert data[0]['evidence']['source_url'] == "https://example.com/team"

