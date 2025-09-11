import json
import subprocess
import sys
from pathlib import Path


def test_decision_filter_cli(tmp_path: Path):
    # Prepare temporary input JSON with 2 records
    records = [
        {"person_name": "Alice", "role_title": "VP Marketing", "email": "alice@example.com"},
        {"person_name": "Bob", "role_title": "Head of Sales", "email": "bob@example.com"},
    ]
    input_file = tmp_path / "people.json"
    input_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    out_dir = tmp_path / "out"

    # Run the CLI via subprocess from project root
    project_root = Path(__file__).resolve().parents[2]
    script_path = project_root / "scripts" / "decision_filter.py"

    result = subprocess.run(
        [sys.executable, str(script_path), "--input", str(input_file), "--out-dir", str(out_dir)],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"CLI failed: stdout={result.stdout}\nstderr={result.stderr}"

    basename = input_file.stem
    out_json = out_dir / f"decision_{basename}.json"
    out_csv = out_dir / f"decision_{basename}.csv"

    assert out_json.exists(), f"Missing output JSON: {out_json}"
    assert out_csv.exists(), f"Missing output CSV: {out_csv}"

    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert isinstance(data, list), "Output JSON must be a list"
    assert len(data) == 2, "Output JSON must contain 2 records"
