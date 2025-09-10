"""
Evidence-Grade Contacts PoC - CLI Runner

Usage:
  python -m egc.run \
    --input input_urls.txt \
    --config config/example.yaml \
    --out ./out

Dry run (validate only):
  python -m egc.run --input input_urls.txt --config config/example.yaml --out ./out --dry-run

Exit codes:
  0 - success
  1 - config error (file missing or invalid YAML)
  2 - input error (input file missing)
  3 - processing error (runtime failures)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List
from urllib.parse import urljoin, urlparse, urlunparse

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # Fallback if PyYAML is not installed

# Pipeline imports
from src.pipeline.ingest import IngestPipeline
from src.pipeline.discovery import discover_from_root, discover_links
from src.pipeline.export import ContactExporter


def validate_input(input_path: Path) -> None:
    if not input_path.exists() or not input_path.is_file():
        print(f"Input error: file not found: {input_path}", file=sys.stderr)
        sys.exit(2)


def validate_config(config_path: Path) -> dict:
    if not config_path.exists() or not config_path.is_file():
        print(f"Config error: file not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    if yaml is None:
        # PyYAML not installed; still allow run, but cannot use config params
        return {}
    try:
        with config_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
            return cfg
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


def read_input_urls(input_path: Path) -> List[str]:
    urls: List[str] = []
    for line in input_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # Heuristic normalization:
        # - if starts with http(s), accept as-is
        # - if looks like a domain (has a dot), prefix https://
        # - otherwise, treat as-is (could be a full URL path later)
        if s.startswith("http://") or s.startswith("https://"):
            urls.append(s)
        elif "." in s:
            urls.append(f"https://{s}")
        else:
            # Keep raw; downstream expansion will handle
            urls.append(s)
    return urls


def normalize_url(u: str) -> str:
    """Canonicalize a URL: lowercase host, drop query/fragment, trim trailing slash (except root)."""
    try:
        p = urlparse(u)
        if not p.scheme:
            return u  # not a URL; leave untouched
        netloc = (p.netloc or '').lower()
        path = p.path or ''
        # trim trailing slash except root
        if path.endswith('/') and path != '/':
            path = path.rstrip('/')
        newp = p._replace(netloc=netloc, path=path, query='', fragment='')
        return urlunparse(newp)
    except Exception:
        return u


def expand_candidate_urls(base: str, include_paths: List[str]) -> List[str]:
    # If base is not a URL yet, skip expansion
    if not (base.startswith("http://") or base.startswith("https://")):
        return [base]
    candidates = [base.rstrip("/")]
    for p in include_paths:
        # ensure each include path starts with '/'
        path = p if p.startswith("/") else f"/{p}"
        candidates.append(urljoin(base, path))
    # Dedupe while preserving order
    seen = set()
    uniq = []
    for u in candidates:
        if u not in seen:
            uniq.append(u)
            seen.add(u)
    return uniq


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="egc.run", description="EGC PoC pipeline runner")
    parser.add_argument("--input", "-i", required=True, help="Path to URLs file (one per line)")
    parser.add_argument("--config", "-c", required=True, help="Path to YAML config file")
    parser.add_argument("--out", "-o", required=True, help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs/config and exit")
    parser.add_argument("--include-all", action="store_true", help="Export UNVERIFIED contacts as well (default: VERIFIED only)")
    parser.add_argument("--db", choices=["sqlite", "none"], default="sqlite", help="DB integration: sqlite or none (default: sqlite)")
    parser.add_argument("--db-path", default=None, help="Path to SQLite DB file (default: <out>/egc.sqlite)")
    # Performance/behavior knobs
    parser.add_argument("--no-discovery", action="store_true", help="Disable adaptive link discovery; use only include_paths expansion")
    parser.add_argument("--no-prefilter", action="store_true", help="Disable pre-filter HTTP checks for candidate pages")
    parser.add_argument("--no-headless", action="store_true", help="Disable Playwright escalation (static-only)")
    parser.add_argument("--static-timeout", type=float, default=12.0, help="Static fetch timeout seconds (default 12.0)")
    parser.add_argument("--prefilter-timeout", type=float, default=5.0, help="Prefilter check timeout seconds (default 5.0)")
    parser.add_argument("--aggressive-static", action="store_true", help="Enable static++ heuristics")
    parser.add_argument("--max-pages-per-domain", type=int, default=10, help="Limit number of candidate pages per domain (default 10)")
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    config_path = Path(args.config)
    out_dir = Path(args.out)

    # Basic validations
    validate_input(input_path)
    cfg = validate_config(config_path)
    ensure_out_dir(out_dir)

    urls = read_input_urls(input_path)

    if args.dry_run:
        print("✅ Dry-run validation passed")
        print(f" - Input file: {input_path}")
        print(f" - Config: {config_path}")
        print(f" - Output dir: {out_dir}")
        print(f" - URLs to process: {len(urls)}")
        return 0

    # Determine include paths from config
    include_paths = cfg.get("scope", {}).get("include_paths", [
        "/about", "/team", "/leadership", "/management", "/contacts", "/contact", "/imprint", "/impressum"
    ])

    # Initialize pipeline and exporter
    pipeline = IngestPipeline(enable_headless=(not args.no_headless), static_timeout_s=float(args.static_timeout), aggressive_static=bool(args.aggressive_static))
    exporter = ContactExporter(output_dir=out_dir)

    # Resolve DB path if enabled
    db_path = None
    if args.db == "sqlite":
        db_path = args.db_path or str(out_dir / "egc.sqlite")

    # Optional quick URL existence/MIME pre-check
    def _quick_url_ok(u: str) -> bool:
        try:
            import httpx
            with httpx.Client(timeout=float(args.prefilter_timeout), follow_redirects=True, headers={"User-Agent": "EGC-CLI/0.1"}) as c:
                r = c.head(u)
                if r.status_code >= 400:
                    return False
                ct = r.headers.get('Content-Type', '').lower()
                return ct.startswith('text/html')
        except Exception:
            return True  # Fail-open for PoC

    all_contacts = []
    total_pages = 0
    try:
        for base in urls:
            # If base is a domain root, try adaptive discovery first, then include_paths fallback
            discovered: list[str] = []
            if (not args.no_discovery) and (base.startswith("http://") or base.startswith("https://")):
                try:
                    discovered = discover_from_root(base)
                except Exception:
                    discovered = []
            candidates = (discovered or []) + expand_candidate_urls(base, include_paths)
            # Normalize and dedupe candidates
            norm_seen = set()
            norm_candidates: list[str] = []
            for u in candidates:
                nu = normalize_url(u)
                if nu and nu.startswith(('http://','https://')) and nu not in norm_seen:
                    norm_seen.add(nu)
                    norm_candidates.append(nu)
            # Pre-filter candidates quickly
            prefiltered = norm_candidates if args.no_prefilter else [u for u in norm_candidates if _quick_url_ok(u)]
            # Enforce per-domain limit
            max_per_domain = int(getattr(args, 'max_pages_per_domain', 10) or 10)
            limited = prefiltered[:max_per_domain]
            for url in limited:
                total_pages += 1
                print(f"➡️  Processing: {url}")
                result = pipeline.ingest(url)
                if not result.success:
                    reason = result.error or "unknown error"
                    print(f"  ⚠️  Skipped: {url} — {reason}")
                    continue
                if result.contacts:
                    print(f"  ✅ Extracted {len(result.contacts)} contacts via {result.method}")
                    all_contacts.extend(result.contacts)
                else:
                    print(f"  ℹ️  No contacts found on {url} ({result.method})")
    finally:
        # Ensure resources are closed
        try:
            pipeline.close()
        except Exception:
            pass

    if not all_contacts:
        print("No contacts extracted from any page.", file=sys.stderr)
        return 3

    # Decide which contacts to persist (VERIFIED-only by default)
    try:
        contacts_for_export = all_contacts if args.include_all else exporter.filter_verified_contacts(all_contacts)
    except Exception as e:
        print(f"Filtering error: {e}", file=sys.stderr)
        return 3

    # Export to files (bypass internal filtering by setting include_all=True, we already filtered)
    try:
        base_name = None  # let exporter generate timestamped names
        csv_path = exporter.to_csv(contacts_for_export, filename=None, include_all=True)
        json_path = exporter.to_json(contacts_for_export, filename=None, include_all=True)
        print(f"💾 CSV: {csv_path}")
        print(f"💾 JSON: {json_path}")
    except Exception as e:
        print(f"Export error: {e}", file=sys.stderr)
        return 3

    # Export to SQLite if enabled (use the same filtered set)
    if db_path:
        try:
            from src.db.sqlite_exporter import export_contacts_to_sqlite
            written = export_contacts_to_sqlite(db_path, contacts_for_export)
            print(f"💽 SQLite: wrote {written} rows to {db_path}")
        except Exception as e:
            print(f"SQLite export error: {e}", file=sys.stderr)
            return 3

    print("🏁 Done.")
    print(f"   Processed pages: {total_pages}")
    print(f"   Total contacts: {len(all_contacts)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
