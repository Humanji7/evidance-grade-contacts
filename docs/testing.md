# Testing Strategy - Evidence-Grade Contacts (EGC) PoC

This document outlines how we test the EGC PoC. It focuses on evidence completeness, static-first processing, and PoC guardrails.

Goals (quality gates)
- Evidence Completeness Rate (ECR) ≥ 0.95
- Precision ≥ 0.90, Recall ≥ 0.80 on a small gold set
- UNVERIFIED share < 5%
- Headless escalation share ≤ 20% per domain

Key principles
- Static-first; escalate to Playwright only by rules
- Mini Evidence Package: 7 required fields per verified record
- Compliance-first (robots.txt/ToS)

## Directory structure

```
tests/
  unit/
    test_schemas.py            # Pydantic models (exists)
    test_config.py             # Config parsing & defaults (planned)
    test_utils.py              # Deterministic helpers (planned)
  integration/
    test_static_extract.py     # Static fetch + parse + evidence build (planned)
    test_headless_escalation.py# Playwright escalation (planned)
  regression/
    test_gold_set.py           # Compare against gold datasets (planned)
  e2e/
    test_pipeline.py           # Full pipeline, slow (planned)
  fixtures/
    html/                      # Frozen HTML snapshots for offline tests
    screenshots/               # PNG node screenshots used by fixtures
```

Create missing folders as you implement tests. Prefer offline fixtures to keep tests deterministic.

## Test types

### 1) Unit tests (fast feedback)
Scope
- Data models (Contact, Evidence) and validators
- Config parsing (config/example.yaml) and guardrails
- Small, deterministic helpers

Run
```bash
python -m pytest tests/unit/ -v
```

Coverage
```bash
python -m pytest --cov=src tests/unit/ -v
```

Notes
- Use small synthetic inputs
- No network, no Playwright

### 2) Integration tests
Scope
- Static fetch → parse → build evidence (without full pipeline)
- Escalation to Playwright for specific pages when static fails

Run
```bash
# Static-first scenarios
python -m pytest tests/integration/ -v

# With browser (Playwright)
python -m pytest tests/integration/ --browser chromium -v
python -m pytest tests/integration/ --browser firefox -v
```

Notes
- Keep pages and selectors in fixtures/ to allow offline replay when possible
- Mark tests that require network or headless appropriately (xfail/skip if missing)
- If you see "browser not found" errors, install the required browser in your active venv, e.g.: `python -m playwright install firefox`

### 3) Regression tests (gold datasets)
Scope
- Validate quality on a curated set (20–50 pages across 2–3 companies)
- Track Precision/Recall and ECR across changes

Data layout (example)
```
data/gold_datasets/
  company_a/
    urls.txt
    contacts_expected.json     # Ground truth
  company_b/
    urls.txt
    contacts_expected.json
```

Run (example)
```bash
python -m pytest tests/regression/ -v
# Optionally add custom flags when helper scripts are available
```

Notes
- Gold data should be minimal and public
- Do not include sensitive data; respect robots/ToS

### 4) End-to-end (E2E) tests
Scope
- From input URLs to CSV/JSON outputs with evidence artifacts
- Long-running; used in CI nightly or before releases

Run
```bash
python -m pytest tests/e2e/ --slow -v
```

Notes
- Use small input set and tight timeouts to keep runtime reasonable

## Fixtures & offline reproducibility

Principles
- Prefer frozen HTML snapshots over live network calls for most tests
- Store node screenshots used by tests in tests/fixtures/screenshots/
- When network is essential, mark the test and keep it minimal

Guidelines
- Normalize timestamps in fixtures
- Use deterministic content_hash values (fixed inputs) in unit tests
- Keep fixture size small

## New unit tests (added)

- URL normalization (CLI): ensures removal of query/fragment, host lowercasing, trailing slash rules
- Phone validation (text fallback): rejects date-like numbers and enforces markers + 10–15 digits
- Role stop-list: maps junk roles ("email", "areas of focus:", "coming soon", "open seat") to "Unknown"
- Export-layer dedupe & paths: collapses duplicates by (company, person, type, value); CSV/JSON contain normalized `source_url`

## Commands (cheat sheet)

Unit
```bash
python -m pytest tests/unit/ -v
python -m pytest --cov=src tests/unit/ -v
```

Integration
```bash
python -m pytest tests/integration/ -v
python -m pytest tests/integration/ --browser chromium -v
python -m pytest tests/integration/ --browser firefox -v
```

Regression
```bash
python -m pytest tests/regression/ -v
```

E2E
```bash
python -m pytest tests/e2e/ --slow -v
```

## CI/CD outline (proposed)

- PR pipeline
  - Run unit + integration (static-first only)
  - Fail if unit/integration tests fail
- Nightly/regression
  - Run regression on gold datasets
  - Enforce ECR ≥ 0.95 and report metrics (when helper scripts are available)
- Release gate
  - Run E2E with limited scope

## Data & compliance policy for tests

- Only public pages; respect robots.txt and ToS
- No real personal emails/phones in fixtures; use synthetic examples
- Do not commit sensitive data; keep evidence images minimal

## Acceptance checks (quick)

- No duplicates in exported CSV/JSON by key (company_norm, person_norm, contact_type, contact_value_norm)
- All exported `source_url` values are normalized (no query/fragment, host without `www.`, no trailing slash unless root)
- All rows remain VERIFIED; Evidence remains unchanged and complete

## References

- Project rules: WARP.md (CLI standards, data schema standards)
- User guide: docs/cli.md (commands and options)
- Config defaults: config/example.yaml
- Data models: src/schemas.py
- JSON Schemas: schemas/*.schema.json

