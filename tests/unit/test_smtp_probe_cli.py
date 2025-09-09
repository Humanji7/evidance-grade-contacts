import json
import os
import sys
from pathlib import Path
from subprocess import run, PIPE

import pytest

SCRIPT = str(Path(__file__).resolve().parents[2] / "scripts" / "smtp_probe.py")


def run_cli(args, env=None):
    e = os.environ.copy()
    if env:
        e.update(env)
    return run([sys.executable, SCRIPT] + args, stdout=PIPE, stderr=PIPE, env=e, text=True)


def test_cli_no_input_exit2():
    r = run_cli([])
    assert r.returncode == 2


def test_cli_email_no_mx_outputs_json(tmp_path):
    out = tmp_path / "probe.json"
    r = run_cli(["--email", "user@example.com", "--out", str(out)])
    assert r.returncode == 0
    data = json.loads(out.read_text())
    assert isinstance(data, list) and len(data) == 1
    assert data[0]["email"] == "user@example.com"
    assert "mx_found" in data[0]


def test_cli_skip_free_default_policy(tmp_path):
    out = tmp_path / "probe.json"
    r = run_cli(["--email", "user@gmail.com", "--out", str(out)])
    assert r.returncode == 0
    data = json.loads(out.read_text())
    assert data[0]["error_category"] == "policy"
    assert data[0]["accepts_rcpt"] is False

