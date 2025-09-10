import json
import os
from pathlib import Path
from subprocess import run, PIPE
from unittest.mock import patch

SCRIPT = str(Path(__file__).resolve().parents[2] / "scripts" / "smtp_probe.py")


def run_cli(args, env=None):
    e = os.environ.copy()
    if env:
        e.update(env)
    r = run([os.environ.get("PYTHON", "python3"), SCRIPT] + args, stdout=PIPE, stderr=PIPE, text=True, env=e)
    return r


def test_domain_quota_enforced(tmp_path, monkeypatch):
    out = tmp_path / "out.json"

    # Prepare an emails file with 3 addresses on same domain
    emails_file = tmp_path / "emails.csv"
    emails_file.write_text("user1@example.com\nuser2@example.com\nuser3@example.com\n")

    # Load module in-process to allow patching
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("smtp_probe", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    # Point cache to tmp and preload MX to avoid DNS
    cache_file = tmp_path / ".egc_cache.db"
    monkeypatch.setattr(mod, "_cache_path", lambda: str(cache_file))
    mod._init_cache(str(cache_file))
    mod._save_mx(str(cache_file), "example.com", ["mx.example.com"])  # so resolve_mx is not needed

    # Mock probe_rcpt and call main() directly (no subprocess)
    with patch("smtp_probe.probe_rcpt") as mock_probe:
        mock_probe.return_value = {"accepts_rcpt": True, "smtp_code": 250, "error_category": "ok", "mx_used": "mx.example.com"}
        rc = mod.main(["--emails-file", str(emails_file), "--out", str(out), "--max-per-domain", "2"])  # limit = 2
        assert rc == 0
        data = json.loads(out.read_text())
        assert len(data) == 3
        # First two probed, third blocked by policy
        assert data[2]["error_category"] == "policy"
        assert "quota" in data[2]["smtp_message"]


def test_email_cache_hit_skips_probe(tmp_path, monkeypatch):
    out1 = tmp_path / "out1.json"
    out2 = tmp_path / "out2.json"

    # Load module and point cache to tmp
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("smtp_probe", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    cache_file = tmp_path / ".egc_cache.db"
    monkeypatch.setattr(mod, "_cache_path", lambda: str(cache_file))

    # Prime cache by running once with a mocked probe
    with patch("smtp_probe.probe_rcpt") as mock_probe:
        mock_probe.return_value = {"accepts_rcpt": True, "smtp_code": 250, "error_category": "ok", "mx_used": "mx.example.com"}
        # Also ensure MX is available without resolve
        mod._init_cache(str(cache_file))
        mod._save_mx(str(cache_file), "example.com", ["mx.example.com"])
        r1 = run_cli(["--email", "user@example.com", "--out", str(out1)])
        assert r1.returncode == 0

    # Second run should be served from email cache; fail test if probe is called
    with patch("smtp_probe.probe_rcpt", side_effect=AssertionError("probe should not be called when email cache is fresh")):
        r2 = run_cli(["--email", "user@example.com", "--out", str(out2)])
        assert r2.returncode == 0
        data = json.loads(out2.read_text())
        assert data[0]["email"] == "user@example.com"
        assert "smtp_code" in data[0]

