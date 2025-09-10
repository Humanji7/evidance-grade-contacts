import json
from datetime import datetime, timezone, timedelta
from src.pipeline.export import dedupe_contacts_for_export, normalize_url_for_report
from src.schemas import Contact, Evidence, ContactType


def make_contact(company, person, role, ctype, value, url, selector, t=0):
    ev = Evidence(
        source_url=url,
        selector_or_xpath=selector,
        verbatim_quote=value,
        dom_node_screenshot="evidence/test.png",
        timestamp=datetime.now(timezone.utc),
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
        captured_at=datetime.now(timezone.utc) + timedelta(seconds=t),
    )


def test_dedupe_www_vs_nowww_same_key():
    a = make_contact("Our Team", "Executive Team", "Unknown", "email", "mvandemaele@prosatwork.com", "https://www.prosatwork.com/our-team", "a[href*='mailto:']")
    b = make_contact("Our Team", "Executive Team", "Unknown", "email", "mvandemaele@prosatwork.com", "https://prosatwork.com/our-team", "a[href*='mailto:']", t=1)
    out = dedupe_contacts_for_export([a, b])
    assert len(out) == 1


def test_anchor_beats_text():
    text = make_contact("Acme", "John Doe", "Engineer", "email", "john@acme.com", "https://example.com/team", ":contains('@')")
    anchor = make_contact("Acme", "John Doe", "Engineer", "email", "john@acme.com", "https://example.com/team", "a[href*='mailto:']")
    out = dedupe_contacts_for_export([text, anchor])
    assert len(out) == 1
    sel = out[0].evidence.selector_or_xpath
    assert "a[href*='mailto:']" in sel


def test_semantic_url_beats_about():
    about = make_contact("Acme", "Jane Doe", "Engineer", "email", "jane@acme.com", "https://example.com/about", "a[href*='mailto:']")
    team = make_contact("Acme", "Jane Doe", "Engineer", "email", "jane@acme.com", "https://example.com/team", "a[href*='mailto:']")
    out = dedupe_contacts_for_export([about, team])
    assert len(out) == 1
    assert "/team" in out[0].evidence.source_url


def test_normalize_url_for_report():
    u = "https://www.Example.com/team/?x=1#y"
    assert normalize_url_for_report(u) == "https://example.com/team"

