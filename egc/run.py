"""
Minimal CLI runner (stub) for EGC PoC.

Usage (dry-run):
  python -m egc.run --input input_urls.txt --config config/example.yaml --out ./out --dry-run

Exit codes:
  0 - success (dry-run OK)
  1 - config error (file missing or invalid YAML)
  2 - input error (input file missing)
  3 - processing error (not implemented)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # Fallback if PyYAML is not installed


def validate_input(input_path: Path) -> None:
    if not input_path.exists() or not input_path.is_file():
        print(f"Input error: file not found: {input_path}", file=sys.stderr)
        sys.exit(2)


def validate_config(config_path: Path) -> None:
    if not config_path.exists() or not config_path.is_file():
        print(f"Config error: file not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    if yaml is None:
        # PyYAML not installed; for PoC we still allow dry-run to proceed
        return
    try:
        with config_path.open("r", encoding="utf-8") as f:
            yaml.safe_load(f)
    except Exception as e:  # invalid YAML
        print(f"Config error: invalid YAML in {config_path}: {e}", file=sys.stderr)
        sys.exit(1)


def ensure_out_dir(out_dir: Path) -> None:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        # sanity check: can we write here?
        test_file = out_dir / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
    except Exception as e:
        print(f"Output error: cannot write to {out_dir}: {e}", file=sys.stderr)
        sys.exit(3)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="egc.run", description="EGC PoC pipeline runner (stub)")
    parser.add_argument("--input", "-i", required=True, help="Path to URLs file (one per line)")
    parser.add_argument("--config", "-c", required=True, help="Path to YAML config file")
    parser.add_argument("--out", "-o", required=True, help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs/config and exit")
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    config_path = Path(args.config)
    out_dir = Path(args.out)

    # Basic validations
    validate_input(input_path)
    validate_config(config_path)
    ensure_out_dir(out_dir)

    if args.dry_run:
        print("✅ Dry-run validation passed")
        print(f" - Input file: {input_path}")
        print(f" - Config: {config_path}")
        print(f" - Output dir: {out_dir}")
        print("ℹ️  Processing not implemented yet (stub)")
        return 0

    print("Processing not implemented yet. Use --dry-run to validate setup.", file=sys.stderr)
    return 3


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

