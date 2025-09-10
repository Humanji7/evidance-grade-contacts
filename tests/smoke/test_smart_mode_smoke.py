import pytest
from pathlib import Path

@pytest.mark.skip(reason="Smoke test requires network and real targets; run manually")
def test_smart_mode_smoke_placeholder(tmp_path: Path):
    # Placeholder: run CLI without flags on input_urls.txt and verify outputs/logs.
    # Manual steps:
    #  - python3 -m egc.run --input input_urls.txt --config config/example.yaml --out ./out
    #  - Ensure logs contain 'via playwright' for some URLs
    #  - Ensure contacts_* and contacts_people_* files are created
    #  - Ensure headless pages do not exceed budgets (domain<=2, global<=10)
    pass

