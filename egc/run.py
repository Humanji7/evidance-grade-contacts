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
from src.pipeline.export import ContactExporter, dedupe_contacts_for_export, consolidate_per_person


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


def normalize_url(u: str, keep_trailing_slash: bool = False) -> str:
    """Canonicalize a URL: lowercase host, drop query/fragment.

    By default, also trim trailing slash (except for root path). When
    keep_trailing_slash=True, preserve the path exactly as provided.
    """
    try:
        p = urlparse(u)
        if not p.scheme:
            return u  # not a URL; leave untouched
        netloc = (p.netloc or '').lower()
        path = p.path or ''
        # Trim trailing slash except root, unless explicitly preserved
        if (not keep_trailing_slash) and path.endswith('/') and path != '/':
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
    # Python 3.11+ gate (must run before any heavy imports/arg parsing)
    if sys.version_info < (3, 11):
        cur = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        print(
            f"Python 3.11+ required. Current: {cur}. Activate .venv311 or run: python3.11 -m egc.run …",
            file=sys.stderr,
        )
        return 1

    parser = argparse.ArgumentParser(prog="egc.run", description="EGC PoC pipeline runner")
    parser.add_argument("--input", "-i", required=True, help="Path to URLs file (one per line)")
    parser.add_argument("--config", "-c", required=True, help="Path to YAML config file")
    parser.add_argument("--out", "-o", required=True, help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs/config and exit")
    parser.add_argument("--include-all", action="store_true", help="Export UNVERIFIED contacts as well (default: VERIFIED only)")
    parser.add_argument("--db", choices=["sqlite", "none"], default="sqlite", help="DB integration: sqlite or none (default: sqlite)")
    parser.add_argument("--db-path", default=None, help="Path to SQLite DB file (default: <out>/egc.sqlite)")
    # Performance/behavior knobs (service flags retained)
    parser.add_argument("--no-discovery", action="store_true", help="Disable adaptive link discovery; use only include_paths expansion")
    parser.add_argument("--no-prefilter", action="store_true", help="Disable pre-filter HTTP checks for candidate pages")
    parser.add_argument("--no-headless", action="store_true", help="Disable Playwright escalation (static-only)")
    parser.add_argument("--static-timeout", type=float, default=12.0, help="Static fetch timeout seconds (default 12.0)")
    parser.add_argument("--prefilter-timeout", type=float, default=5.0, help="Prefilter check timeout seconds (default 5.0)")
    parser.add_argument("--aggressive-static", action="store_true", help="Enable static++ heuristics (Smart mode enables this by default)")
    parser.add_argument("--max-pages-per-domain", type=int, default=10, help="Limit number of candidate pages per domain (default 10)")
    parser.add_argument("--consolidate-per-person", action="store_true", help="Produce consolidated per-person exports (1 row per person)")
    parser.add_argument("--exact-input-only", action="store_true", help="Process only URLs from --input; disable discovery and include_paths expansion")
    # Decision-only flags (do not change default behavior)
    parser.add_argument("--decision-only", action="store_true", help="Write decision-only people artifacts (filtered by --min-level) without affecting base outputs")
    parser.add_argument("--min-level", choices=["C_SUITE","VP_PLUS","MGMT"], default="VP_PLUS", help="Minimum decision level for decision-only people (default: VP_PLUS)")
    # ECR summary flags (computed from all extracted contacts before export filtering)
    parser.add_argument("--print-ecr-summary", action="store_true", help="Print ECR summary after run (computed on all extracted contacts)")
    parser.add_argument("--ecr-threshold", type=float, default=0.95, help="ECR threshold for OK/FAIL tag in summary (default 0.95)")
    parser.add_argument("--ops-log", default=None, help="Path to ops JSONL log file (default: <out>/ops.log)")
    parser.add_argument("--ops-stdout", action="store_true", help="Also mirror ops JSON to stdout")
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

    # Initialize pipeline and exporter (Smart defaults)
    smart_aggressive_static = True  # Static++ ON by default

    # Ops config passthrough (safe defaults)
    ops_cfg = cfg.get("ops", {}) if isinstance(cfg, dict) else {}
    headless_cfg = ops_cfg.get("headless", {}) if isinstance(ops_cfg, dict) else {}
    timeouts_cfg = ops_cfg.get("timeouts", {}) if isinstance(ops_cfg, dict) else {}
    logging_cfg = ops_cfg.get("logging", {}) if isinstance(ops_cfg, dict) else {}

    headless_domain_cap = int(headless_cfg.get("per_domain_budget", 2) or 2)
    headless_global_cap = int(headless_cfg.get("global_budget", 10) or 10)
    domain_max_share_pct = float(headless_cfg.get("max_share_pct", 0.2) or 0.2)

    static_timeout = float(timeouts_cfg.get("static_fetch_s", args.static_timeout) or args.static_timeout)

    pipeline = IngestPipeline(
        enable_headless=(not args.no_headless),
        static_timeout_s=static_timeout,
        aggressive_static=smart_aggressive_static,
        headless_budget=IngestPipeline.HeadlessBudget(domain_cap=headless_domain_cap, global_cap=headless_global_cap),
    )
    # Configure DomainTracker max share if using default tracker
    try:
        # Recreate domain tracker with configured max_share_pct if default was used
        if isinstance(pipeline.domain_tracker, type(IngestPipeline.DomainTracker if False else object)):
            pass
    except Exception:
        pass
    # Enable OPS JSON logs by config flag (also gated by env EGC_OPS_JSON)
    try:
        pipeline.ops_json_enabled = bool(logging_cfg.get("ops_json", False))
    except Exception:
        pipeline.ops_json_enabled = False

    exporter = ContactExporter(output_dir=out_dir)

    # Setup OpsLogger
    ops_log_path = Path(args.ops_log) if args.ops_log else (out_dir / "ops.log")
    try:
        from src.ops_logger import OpsLogger
        ops_logger = OpsLogger(ops_log_path, also_stdout=bool(getattr(args, "ops_stdout", False)))
    except Exception:
        ops_logger = None

    # Smart mode profile log
    print(f"Smart mode: discovery=auto, headless=guarded, budgets: domain={headless_domain_cap}, global={headless_global_cap}")
    # Print Python version for diagnostics
    print(f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")

    # Resolve DB path if enabled
    db_path = None
    if args.db == "sqlite":
        db_path = args.db_path or str(out_dir / "egc.sqlite")

    # Helper: target URL check (path contains key people pages)
    def _is_target_url(u: str) -> bool:
        try:
            p = urlparse(u)
            path = (p.path or '').lower()
            targets = ("team", "our-team", "people", "leadership", "management", "contacts", "imprint", "impressum")
            return any(t in path for t in targets)
        except Exception:
            return False

    # Optional quick URL existence/MIME pre-check
    def _quick_url_ok(u: str, timeout_s: float) -> bool:
        try:
            import httpx
            with httpx.Client(timeout=float(timeout_s), follow_redirects=True, headers={"User-Agent": "EGC-CLI/0.1"}) as c:
                r = c.head(u)
                if r.status_code >= 400:
                    return False
                ct = r.headers.get('Content-Type', '').lower()
                return ct.startswith('text/html')
        except Exception:
            return True  # Fail-open for PoC
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
    import time as _time
    proc_start = _time.perf_counter()
    try:
        for base in urls:
            # Smart discovery:
            # - If input URL already target → do not run discovery; process only this URL
            # - Otherwise → discover links to target pages (limit 4) with fast HEAD prefilter (2s)
            # Build candidates honoring exact-input-only first
            if getattr(args, "exact_input_only", False):
                candidates = []
                # Preserve trailing slash in exact-input-only mode
                nu = normalize_url(base, keep_trailing_slash=True)
                if nu and nu.startswith(("http://", "https://")):
                    candidates.append(nu)
            else:
                discovered: list[str] = []
                if (not args.no_discovery) and (base.startswith("http://") or base.startswith("https://")) and (not _is_target_url(base)):
                    try:
                        discovered = discover_from_root(base)
                    except Exception:
                        discovered = []
                    # Limit discovery to first 4 target-like pages
                    discovered = discovered[:4]
                # Build candidates
                candidates = ([] if _is_target_url(base) else (discovered or [])) + expand_candidate_urls(base, include_paths)
            # Normalize and dedupe candidates
            norm_seen = set()
            norm_candidates: list[str] = []
            # Preserve trailing slash for exact-input-only normalization to avoid breaking servers
            keep_slash = bool(getattr(args, "exact_input_only", False))
            for u in candidates:
                nu = normalize_url(u, keep_trailing_slash=keep_slash)
                if nu and nu.startswith(('http://','https://')) and nu not in norm_seen:
                    norm_seen.add(nu)
                    norm_candidates.append(nu)
            # Pre-filter candidates quickly (2s for Smart mode)
            # In exact-input-only mode, skip prefilter to avoid false negatives (e.g., HEAD 403/405)
            if args.no_prefilter or args.exact_input_only:
                prefiltered = norm_candidates
            else:
                prefiltered = [u for u in norm_candidates if _quick_url_ok(u, timeout_s=2.0)]
            # Enforce per-domain limit
            max_per_domain = int(getattr(args, 'max_pages_per_domain', 10) or 10)
            limited = prefiltered[:max_per_domain]
            for url in limited:
                total_pages += 1
                print(f"➡️  Processing: {url}")
                result = pipeline.ingest(url)
                # Emit per-URL ops record to file if available
                try:
                    if ops_logger and getattr(pipeline, "_last_ops_record", None):
                        ops_logger.emit(pipeline._last_ops_record)
                except Exception:
                    pass
                # Surface escalation reasons in logs
                if result.escalation_decision and result.escalation_decision.escalate and result.method == 'playwright':
                    print(f"  via playwright: reasons={result.escalation_decision.reasons}")
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

    # Always produce per-person consolidation exports in Smart mode (in addition to base exports)
    try:
        deduped = dedupe_contacts_for_export(contacts_for_export)
        consolidated = consolidate_per_person(deduped)
        people_csv = exporter.to_people_csv(consolidated)
        people_json = exporter.to_people_json(consolidated)
        print(f"👤 People CSV: {people_csv}")
        print(f"👤 People JSON: {people_json}")
    except Exception as e:
        print(f"Consolidation export error: {e}", file=sys.stderr)
        return 3

    # Decision-only people artifacts (optional; default off)
    try:
        from src.pipeline.roles import DecisionLevel
        from src.pipeline.export import consolidate_per_person_with_evidence
        # Build unfiltered decision rows to compute baseline count M
        dm_all_rows = consolidate_per_person_with_evidence(deduped, min_level=None)
        # Apply threshold only when flag is on
        level = DecisionLevel.from_str(args.min_level)
        dm_rows = consolidate_per_person_with_evidence(deduped, min_level=(level if args.decision_only else None))
        if args.decision_only and dm_rows:
            # Write artifacts
            dm_csv = exporter.to_decision_people_csv(dm_rows)
            dm_json = exporter.to_decision_people_json(dm_rows)
            print(f"🧭 Decision CSV: {dm_csv}")
            print(f"🧭 Decision JSON: {dm_json}")
        # Summary line
        try:
            from collections import Counter
            kept = len(dm_rows)
            total = len(dm_all_rows)
            dist = Counter([r.get('decision_level','UNKNOWN') for r in (dm_rows if args.decision_only else dm_all_rows)])
            def _g(k):
                return dist.get(k, 0)
            print(f"Decision-only: kept {kept if args.decision_only else total} of {total} persons | C_SUITE={_g('C_SUITE')} VP_PLUS={_g('VP_PLUS')} MGMT={_g('MGMT')} NON_DM={_g('NON_DM')} UNKNOWN={_g('UNKNOWN')}")
        except Exception:
            pass
    except Exception as e:
        print(f"Decision-only export error: {e}", file=sys.stderr)
        # Do not fail the run due to optional feature

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
    # Emit final summary ops record
    try:
        import os as _os
        import platform as _plat
        import json as _json
        try:
            import psutil as _ps
        except Exception:
            _ps = None
        wall_s = max(0.0, _time.perf_counter() - proc_start)
        cpu_pct = None
        rss_mb = None
        if _ps:
            try:
                p = _ps.Process()
                with p.oneshot():
                    rss_mb = round(p.memory_info().rss / (1024*1024), 1)
                    cpu_pct = round(p.cpu_percent(interval=None), 1)
            except Exception:
                pass
        summary = {
            "egc_ops": 1,
            "summary": True,
            "processed_pages": total_pages,
            "total_contacts": len(all_contacts),
            "durations": {"wall_s": round(wall_s, 2)},
            "resources": {"cpu_pct": cpu_pct, "rss_mb": rss_mb},
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "host": {"platform": _plat.system(), "release": _plat.release(), "machine": _plat.machine()},
        }
        if ops_logger:
            ops_logger.emit(summary)
    except Exception:
        pass
    print(f"   Processed pages: {total_pages}")
    print(f"   Total contacts: {len(all_contacts)}")

    # Optional: print ECR summary computed from all extracted contacts (pre-export)
    if getattr(args, "print_ecr_summary", False):
        try:
            total_records = len(all_contacts)
            verified_records = 0
            for c in all_contacts:
                try:
                    ev = getattr(c, "evidence", None)
                    if ev and callable(getattr(ev, "is_complete", None)) and ev.is_complete():
                        verified_records += 1
                except Exception:
                    # Treat any evidence exception as UNVERIFIED
                    pass
            unverified_records = total_records - verified_records
            ecr_value = (verified_records / total_records) if total_records > 0 else 0.0
            thr = float(getattr(args, "ecr_threshold", 0.95) or 0.95)
            status = "OK" if ecr_value >= thr else f"FAIL@{thr:.2f}"
            print(f"ECR summary: verified={verified_records}, unverified={unverified_records}, ECR={ecr_value:.1%} ({status})")
        except Exception as e:
            print(f"ECR summary: failed to compute ({e})", file=sys.stderr)

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
