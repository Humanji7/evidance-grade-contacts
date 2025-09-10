import pytest
from unittest.mock import patch, MagicMock

from src.pipeline.fetchers.playwright import PlaywrightFetcher, PlaywrightResult

@patch('src.pipeline.fetchers.playwright.sync_playwright')
def test_playwright_fetcher_success(mock_sync_playwright):
    # Arrange
    mock_page = MagicMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_page.goto.return_value = mock_response
    mock_page.content.return_value = "<html><body>Test</body></html>"
    mock_page.title.return_value = "Test Page"

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page

    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context

    mock_playwright = MagicMock()
    mock_playwright.chromium.launch.return_value = mock_browser

    mock_sync_playwright.return_value.__enter__.return_value = mock_playwright

    fetcher = PlaywrightFetcher()
    url = "http://example.com"

    # Act
    result = fetcher.fetch(url)

    # Assert
    assert result.status_code == 200
    assert result.html == "<html><body>Test</body></html>"
    assert result.page_title == "Test Page"
    assert result.error is None
    mock_page.goto.assert_called_once_with(url, wait_until="load", timeout=20000)
    mock_page.wait_for_selector.assert_called_once()
    mock_browser.close.assert_called_once()


@patch('src.pipeline.fetchers.playwright.sync_playwright')
def test_playwright_fetcher_no_response(mock_sync_playwright):
    # Arrange
    mock_page = MagicMock()
    mock_page.goto.return_value = None  # Simulate no response

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page
    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_playwright = MagicMock()
    mock_playwright.chromium.launch.return_value = mock_browser
    mock_sync_playwright.return_value.__enter__.return_value = mock_playwright

    fetcher = PlaywrightFetcher()
    url = "http://example.com"

    # Act
    result = fetcher.fetch(url)

    # Assert
    assert result.status_code == 0
    assert result.html is None
    assert "No response received" in result.error
    mock_browser.close.assert_called_once()


@patch('src.pipeline.fetchers.playwright.sync_playwright')
def test_playwright_fetcher_wait_for_selector_timeout(mock_sync_playwright):
    # Arrange
    mock_page = MagicMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_page.goto.return_value = mock_response
    mock_page.content.return_value = "<html></html>"
    mock_page.title.return_value = "Title"
    # Simulate a timeout on wait_for_selector
    mock_page.wait_for_selector.side_effect = Exception("Timeout")

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page
    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_playwright = MagicMock()
    mock_playwright.chromium.launch.return_value = mock_browser
    mock_sync_playwright.return_value.__enter__.return_value = mock_playwright

    fetcher = PlaywrightFetcher()

    # Act
    result = fetcher.fetch("http://example.com")

    # Assert
    # Should still succeed, as the exception is caught
    assert result.status_code == 200
    assert result.html == "<html></html>"
    assert result.error is None
    mock_browser.close.assert_called_once()


@patch('src.pipeline.fetchers.playwright.sync_playwright')
def test_playwright_fetcher_general_exception(mock_sync_playwright):
    # Arrange
    # Simulate an exception during browser launch
    mock_playwright = MagicMock()
    mock_playwright.chromium.launch.side_effect = Exception("Launch failed")
    mock_sync_playwright.return_value.__enter__.return_value = mock_playwright

    fetcher = PlaywrightFetcher()
    url = "http://example.com"

    # Act
    result = fetcher.fetch(url)

    # Assert
    assert result.status_code == 0
    assert result.html is None
    assert "Launch failed" in result.error
