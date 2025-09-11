import pytest
from egc.run import normalize_url

def test_normalize_url_removes_query_and_fragment():
    assert normalize_url('https://Example.com/About/?q=1#x') == 'https://example.com/About'

def test_normalize_url_trailing_slash():
    assert normalize_url('https://example.com/team/') == 'https://example.com/team'
    assert normalize_url('https://example.com/') == 'https://example.com/'

def test_normalize_url_keeps_scheme_and_path_case():
    assert normalize_url('https://EXAMPLE.com/Team') == 'https://example.com/Team'

def test_normalize_url_preserves_trailing_slash_when_flag_true():
    assert normalize_url('https://example.com/team/', keep_trailing_slash=True) == 'https://example.com/team/'
    # Root path behavior remains unchanged
    assert normalize_url('https://example.com/', keep_trailing_slash=True) == 'https://example.com/'

