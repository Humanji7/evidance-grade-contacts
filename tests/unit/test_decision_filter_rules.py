import re
from pathlib import Path

from scripts.decision_filter import DecisionLevel, classify, normalize_email


def _rec(title: str, **extra):
    r = {"role_title": title}
    r.update(extra)
    return r


def test_classification_vp_plus_or_higher():
    titles = [
        "President",
        "Managing Director",
        "Executive Director",
        "General Counsel",
        "Chair",
        "Shareholder",
        "Partner",
        "VP",
        "Head of Marketing",
        "Director",
    ]
    for t in titles:
        lvl, _ = classify(_rec(t))
        assert (
            lvl in (DecisionLevel.VP_PLUS, DecisionLevel.C_SUITE)
        ), f"Expected >= VP_PLUS for '{t}', got {lvl}"


def test_classification_negatives_below_vp_plus():
    negatives = [
        "Associate",
        "Of Counsel",
        "Counsel",
        "Paralegal",
        "Specialist",
        "Intern",
    ]
    for t in negatives:
        lvl, _ = classify(_rec(t))
        assert (
            lvl in (DecisionLevel.UNKNOWN, DecisionLevel.NON_DM, DecisionLevel.MGMT)
        ), f"Expected < VP_PLUS for '{t}', got {lvl}"


def test_structural_hint_uplifts_director_to_vp_plus():
    rec = _rec("Director", source_url_leadership="https://example.com/company/leadership")
    lvl, reasons = classify(rec)
    assert lvl in (DecisionLevel.VP_PLUS, DecisionLevel.C_SUITE)
    assert any(r.startswith("struct:") for r in reasons)


def test_email_normalization_and_generic_flag():
    s = "[name](at)example(dot)com"
    assert normalize_email(s) == "name@example.com"

    lvl, reasons = classify(_rec("Director", email="info@example.com"))
    assert any(r == "email:generic" for r in reasons)
