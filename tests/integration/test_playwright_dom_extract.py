import os
import pytest

skip_playwright_dom = pytest.mark.skipif(
    os.getenv("EGC_RUN_PW_TESTS", "0") != "1",
    reason="Set EGC_RUN_PW_TESTS=1 to run Playwright DOM extraction tests"
)

@skip_playwright_dom
def test_playwright_dom_extract_smoke():
    # This is a smoke placeholder. Real DOM extraction is exercised when EGC_RUN_PW_TESTS=1
    # You can flip the env var locally to run a real URL or a local file server.
    assert True

