import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.pipeline.export import (
    consolidate_per_person_with_evidence,
    ContactExporter,
)
from src.pipeline.roles import DecisionLevel
from src.schemas import Contact, ContactType, Evidence


def make_ev(url: str, sel: str, verb: str) -> Evidence:
    return Evidence(
        source_url=url,
        selector_or_xpath=sel,
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
        evidence=make_ev(url, "div a[href*='mailto:']", email),
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
        evidence=make_ev(url, "div a[href*='tel:']", verb or phone),
        captured_at=datetime.now(timezone.utc),
    )


@pytest.fixture()
def sample_people():
    # Persona A: C_SUITE with full evidence
    A_email = make_email(
        "Example Inc.", "Alice Alpha", "President; Managing Director", "alice@example.com", "https://example.com/team"
    )
    A_phone = make_phone(
        "Example Inc.", "Alice Alpha", "President; Managing Director", "5551234567", "https://example.com/leadership", "+1 555 123 4567"
    )
    # Persona B: Associate (should be filtered below VP_PLUS)
    B_email = make_email(
        "Example Inc.", "Bob Beta", "Associate", "bob@example.com", "https://example.com/team"
    )
    # Persona C: Director but with leadership URL (structural bump)
    C_email = make_email(
        "Example Inc.", "Carol Gamma", "Director", "carol@example.com", "https://example.com/company/leadership"
    )
    return [A_email, A_phone, B_email, C_email]


def test_consolidation_with_min_level_filters_below_vp_plus(sample_people):
    rows = consolidate_per_person_with_evidence(sample_people, min_level=DecisionLevel.VP_PLUS)
    # Expect only A and C
    assert len(rows) == 2
    names = {r["person_name"] for r in rows}
    assert names == {"Alice Alpha", "Carol Gamma"}
    # Check structural reason on C
    c_row = [r for r in rows if r["person_name"] == "Carol Gamma"][0]
    assert any(r == "struct:leadership" for r in c_row["decision_reasons"]) 


def test_exporter_writes_decision_people_json_and_csv(tmp_path: Path, sample_people):
    exporter = ContactExporter(output_dir=tmp_path)

    rows = consolidate_per_person_with_evidence(sample_people, min_level=DecisionLevel.VP_PLUS)

    # JSON
    json_path = exporter.to_decision_people_json(rows)
    jp = Path(json_path)
    assert jp.exists()
    data = json.loads(jp.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 2
    # Ensure keys present in record
    keys = set(data[0].keys())
    assert {"decision_level", "decision_reasons", "evidence_email", "evidence_phone", "evidence_vcard"}.issubset(keys)

    # CSV
    csv_path = exporter.to_decision_people_csv(rows)
    cp = Path(csv_path)
    assert cp.exists()
    with cp.open("r", encoding="utf-8") as f:
        rows_csv = list(csv.DictReader(f))
    assert len(rows_csv) == 2
    # Required columns
    req_cols = {
        "decision_level",
        "has_evidence_email",
        "has_evidence_phone",
        "has_evidence_vcard",
        "verification_status",
    }
    assert req_cols.issubset(set(rows_csv[0].keys()))

