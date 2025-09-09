import json
from pathlib import Path
from unittest.mock import patch

import pytest

# Paths
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "smtp_probe.py"

smtp_mod = None


def _load():
    global smtp_mod
    if smtp_mod is None:
        import importlib.util, sys
        spec = importlib.util.spec_from_file_location("smtp_probe", str(SCRIPT))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod  # required for dataclasses on Py3.9
        spec.loader.exec_module(mod)  # type: ignore
        smtp_mod = mod
    return smtp_mod


def test_cache_roundtrip_and_main_uses_cached_hosts(tmp_path, monkeypatch):
    sp = _load()

    cache_file = tmp_path / ".egc_cache.db"
    monkeypatch.setattr(sp, "_cache_path", lambda: str(cache_file))

    # Init cache and save MX for example.com
    sp._init_cache(str(cache_file))
    sp._save_mx(str(cache_file), "example.com", ["mx1.example.com", "mx2.example.com"])

    # Mock probe to ensure it is invoked using cached MX
    with patch("smtp_probe.probe_rcpt") as mock_probe:
        mock_probe.return_value = {"accepts_rcpt": True, "smtp_code": 250, "error_category": "ok", "mx_used": "mx1.example.com"}
        rc = sp.main(["--email", "user@example.com", "--out", str(tmp_path / "out.json"), "--timeout", "3"])
        assert rc == 0
        data = json.loads((tmp_path / "out.json").read_text())
        assert "accepts_rcpt" in data[0]
        assert mock_probe.call_count >= 1


@patch("smtp_probe.resolve_mx")
def test_main_no_mx_found(mock_resolve, tmp_path, monkeypatch):
    sp = _load()

    mock_resolve.return_value = []
    cache_file = tmp_path / ".egc_cache.db"
    monkeypatch.setattr(sp, "_cache_path", lambda: str(cache_file))

    rc = sp.main(["--email", "user@example.com", "--out", str(tmp_path / "out.json")])
    assert rc == 0
    data = json.loads((tmp_path / "out.json").read_text())
    assert data[0]["mx_found"] is False
    assert data[0]["error_category"] == "network"

