import pytest

from src.pipeline.roles import DecisionLevel, classify_role


@pytest.mark.parametrize(
    "title",
    [
        "President",
        "Managing Director",
        "Executive Director",
        "General Counsel",
        "Chief Marketing Officer",
        "Chair",
        "Shareholder",
        "Partner",
        "Vice President",
        "Head of Engineering",
    ],
)
def test_positives_at_least_vp_plus(title: str):
    level, reasons = classify_role(title)
    assert level >= DecisionLevel.VP_PLUS, (title, level, reasons)


@pytest.mark.parametrize(
    "title",
    [
        "Associate",
        "Of Counsel",
        "Counsel",
        "Paralegal",
        "Specialist",
        "Intern",
    ],
)
def test_negatives_below_vp_plus(title: str):
    level, reasons = classify_role(title)
    assert level < DecisionLevel.VP_PLUS, (title, level, reasons)
    assert any(r.startswith("exclude:") for r in reasons) or title.lower() == "counsel"


def test_structural_hint_bumps_director():
    title = "Director"
    url_ctx = "https://example.com/company/leadership"
    level, reasons = classify_role(title, url_ctx=url_ctx)
    assert level >= DecisionLevel.VP_PLUS
    assert any(r == "struct:leadership" for r in reasons)

