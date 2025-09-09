import os
import sys
import time
import types
import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "smtp_probe.py"


def load_module_or_skip() -> types.ModuleType:
    if not SCRIPT_PATH.exists():
        pytest.skip("scripts/smtp_probe.py not implemented yet")
    spec = importlib.util.spec_from_file_location("smtp_probe", str(SCRIPT_PATH))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    # Ensure module is visible to dataclasses/type resolution during exec
    sys.modules[spec.name] = module  # type: ignore[index]
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_validate_email_and_parse_domain():
    sp = load_module_or_skip()

    assert sp.validate_email("user@example.com") is True
    assert sp.validate_email("bad@") is False
    assert sp.validate_email("not-an-email") is False

    assert sp.parse_domain("user@example.com") == "example.com"
    with pytest.raises(ValueError):
        sp.parse_domain("no-at-symbol")


def test_should_skip_domain():
    sp = load_module_or_skip()

    assert sp.should_skip_domain("gmail.com") is True
    assert sp.should_skip_domain("outlook.com") is True
    assert sp.should_skip_domain("example.com") is False


def _result_get(res: object, key: str):
    # Helper to read result whether it's a dict or an object with attributes
    if isinstance(res, dict):
        return res.get(key)
    return getattr(res, key)


@patch("smtplib.SMTP")
def test_probe_rcpt_accepts(mock_smtp):
    sp = load_module_or_skip()

    smtp = MagicMock()
    mock_smtp.return_value.__enter__.return_value = smtp
    smtp.has_extn.return_value = False
    smtp.ehlo.return_value = (250, b"OK")
    smtp.mail.return_value = (250, b"OK")
    smtp.rcpt.return_value = (250, b"Accepted")

    res = sp.probe_rcpt("mx.example.com", "user@example.com", timeout=3)
    assert _result_get(res, "accepts_rcpt") is True
    assert _result_get(res, "smtp_code") == 250
    assert _result_get(res, "error_category") in (None, "", "ok")


@patch("smtplib.SMTP")
def test_probe_rcpt_temp_fail_4xx(mock_smtp):
    sp = load_module_or_skip()

    smtp = MagicMock()
    mock_smtp.return_value.__enter__.return_value = smtp
    smtp.has_extn.return_value = False
    smtp.ehlo.return_value = (250, b"OK")
    smtp.mail.return_value = (250, b"OK")
    smtp.rcpt.return_value = (450, b"Mailbox busy")

    res = sp.probe_rcpt("mx.example.com", "user@example.com", timeout=3)
    assert _result_get(res, "accepts_rcpt") is False
    assert _result_get(res, "smtp_code") == 450
    assert _result_get(res, "error_category") == "temp"


@patch("smtplib.SMTP")
def test_probe_rcpt_perm_fail_5xx(mock_smtp):
    sp = load_module_or_skip()

    smtp = MagicMock()
    mock_smtp.return_value.__enter__.return_value = smtp
    smtp.has_extn.return_value = False
    smtp.ehlo.return_value = (250, b"OK")
    smtp.mail.return_value = (250, b"OK")
    smtp.rcpt.return_value = (550, b"No such user")

    res = sp.probe_rcpt("mx.example.com", "nosuch@example.com", timeout=3)
    assert _result_get(res, "accepts_rcpt") is False
    assert _result_get(res, "smtp_code") == 550
    assert _result_get(res, "error_category") == "perm"
