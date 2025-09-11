Evidence-Grade Contacts — PoC
Description
Evidence-Grade Contacts (EGC) is a proof-of-concept system that extracts people (name, title) and business contacts (email/phone/links) from public pages of corporate websites (e.g., /about, /team, /leadership, /contacts, /imprint, sometimes /news|/press) with a mandatory “mini evidence package” for every fact. Rendering is static-first, with targeted escalation to Playwright when needed. Any record without a complete evidence package is marked UNVERIFIED and excluded from exports.
Goals & Key Principles
Produce auditable contact data with reproducible traceability (“receipt” per fact).


Minimize cost: inexpensive static parsing for most pages, targeted headless only by heuristics.


Strict compliance gate (robots.txt/ToS) and data minimization — business contacts only.


PoC Scope
Included:
Sections: /about, /team, /leadership|/management, /contacts, /imprint, optionally /news|/press.


Targeted headless rendering in Playwright based on heuristics (see below).


Email validation via non-sending SMTP probe (no email delivery), MX/RCPT cache 7–30 days; disabled for free providers.


Excluded:
Bypassing anti-bot/Cloudflare, CAPTCHA-solving services, residential proxies.


WORM/immutability stores; full HTML snapshots/HTTP metadata.


Advanced scoring/canary releases; enterprise observability; data lakes.


Formal DPIA/LIA (moved to pre-prod).


Social networks/LinkedIn — out of scope for the PoC.


Success Criteria
**✅ ACHIEVED:** Evidence Completeness Rate (ECR) = 100% — all 20 gold dataset records have complete mini-packages.

**✅ ACHIEVED:** Gold dataset with 20 records across 3 law firms (target: 20-50 pages across 2-3 companies).

**✅ ACHIEVED:** 100% success rate on gold dataset extraction (309 total contacts extracted).

**✅ ACHIEVED:** Complete Evidence Package system with 35 unit tests passing.

**✅ ACHIEVED:** Full pipeline integration with static-first approach and Playwright escalation.

**✅ ACHIEVED:** Export Pipeline with CSV/JSON output and VERIFIED contacts filtering.

If ECR < 95%, the record is marked UNVERIFIED and excluded.


Mini Evidence Package (required)
Seven fields are stored for each verified record:
 source_url, selector_or_xpath, verbatim_quote, dom_node_screenshot, timestamp (ISO-8601), parser_version, content_hash (SHA-256). Extended artifacts (html_ref, HTTP metadata, etc.) are out of PoC.
Example JSON Artifact
{
  "company": "Example Inc.",
  "person_name": "Jane Doe",
  "role_title": "Head of Marketing",
  "contact_type": "email",
  "contact_value": "jane.doe@example.com",
  "evidence": {
    "source_url": "https://example.com/company/leadership",
    "selector_or_xpath": "div.card:has(h3:contains('Jane Doe'))",
    "verbatim_quote": "Jane Doe — Head of Marketing",
    "dom_node_screenshot": "evidence/example_jane_doe.png",
    "timestamp": "2025-09-04T10:15:00Z",
    "parser_version": "0.1.0-poc",
    "content_hash": "a1b2c3d4e5f6..."
  },
  "captured_at": "2025-09-04T10:15:05Z",
  "verification_status": "VERIFIED"
}

Execution & Escalation Architecture
Static-first: fetch via httpx + Trafilatura/Selectolax without executing JS.
 Escalate to Playwright if any of the following holds:
selector_hits == 0 for target blocks and content_length < 5 KiB;


MIME ≠ text/html due to redirect into SPA/JS app;


dynamic/anti-bot markers detected.
 In headless: wait_for_selector, take node screenshot, return HTML to the shared pipeline.


Limits/Quotas (defaults)
max_headless_pct_per_domain ≤ 0.2


budget_ms_per_url = 12000


burst_rps_static = 1, burst_rps_headless = 0.2


cooldown_on_403: 5m → 15m → 60m


Pipeline
Input normalization: domain, redirects, robots/ToS decision (GO/NO-GO logged).


Crawl plan: generate candidate paths (see scope), enqueue.


Fetching: static → headless if necessary (in container).


Extraction: rules/selectors (name/title/contacts); when present — extruct for JSON-LD/Microdata.


Contacts: mailto/phone/social links; compute email patterns by domain + non-sending SMTP probe (exclude free providers).


Evidence package: collect the 7 required fields only.


Export: CSV/JSON; UNVERIFIED are excluded. For PoC, a single process/simple worker/local queue (e.g., Redis/RQ) is sufficient, no DLQ/sharding.


Data Format (minimum)
contacts.csv|json:
 company, person_name, role_title, contact_type (email/phone/link), contact_value, evidence (nested object with 7 fields), captured_at, verification_status (VERIFIED|UNVERIFIED).
 Normalization/dedup key (PoC): sha1(normalize(name) + '@' + org_domain).
Example CSV (fragment)
company,person_name,role_title,contact_type,contact_value,captured_at,verification_status
Example Inc.,Jane Doe,Head of Marketing,email,jane.doe@example.com,2025-09-04T10:15:05Z,VERIFIED

## Current Implementation (✅ Status)

### Core Components Completed
- **StaticFetcher**: robots.txt compliant HTTP fetching with httpx
- **PlaywrightFetcher**: Secure headless browser with sandbox isolation
- **EscalationDecider**: Anti-bot detection and escalation logic
- **EvidenceBuilder**: Complete Mini Evidence Package creation (7 fields)
- **ContactExtractor**: Semantic selectors for names, titles, emails, phones
- **IngestPipeline**: Full orchestration with domain tracking and quotas
- **ContactExporter**: CSV/JSON export with VERIFIED filtering and evidence validation

### Test Coverage
- **49 unit tests** passing with complete evidence validation
- **Evidence Builder**: 11 tests covering SHA-256 hashing, screenshots, validation
- **Contact Extractor**: 11 tests for extraction patterns and evidence creation
- **Pipeline Integration**: 7 tests for static-first → escalation → extraction flow
- **Export Pipeline**: 14 tests for CSV/JSON export with VERIFIED filtering
- **Static Fetcher**: 2 tests for robots.txt compliance
- **Escalation Logic**: 4 tests for anti-bot detection

### Security & Compliance
- **HTTPS-only**: All external requests enforce SSL/TLS
- **Rate limiting**: Static 1.0 RPS, headless 0.2 RPS per domain
- **Sandbox isolation**: Playwright runs with OS-level sandboxing
- **Evidence integrity**: SHA-256 content hashing for all extracted data
- **Input validation**: Pydantic model enforcement for all data structures

## Ops & Scalability (PoC)

This PoC scales horizontally by running multiple worker processes that each execute the static‑first pipeline with guarded headless escalation. Guardrails keep runs predictable:
- Concurrency: run N workers (or threads) with per‑domain headless budget (≤2 pages) and global headless cap (≤10 pages per run).
- Time budgets: static fetch ~6–8s; fast HEAD prefilter ~2s; DOM sweep ≤6–8s per page; optional deep pass ≤2–3s.
- Depth: D=1 profile follow‑ups limited to ≤5 per listing page.

Observability: the runner prints human‑readable progress (“Processing…”, “via playwright…”) and can emit structured OPS logs (JSON lines) with phase timings (fetch/extract/render), method used (static|playwright), contact counts, and headless reasons. Enable with `EGC_OPS_JSON=1` when running.

## Economy & Budgets

Headless (Playwright) is significantly more expensive than static HTML fetch/parse (seconds vs. sub‑second on typical pages). To keep cost/time bounded, the pipeline:
- Prioritizes static extraction; escalates only on target pages when static finds 0 contacts or when hard signals exist (anti‑bot/tiny/SPA mime).
- Enforces budgets: per‑domain headless ≤ 2 pages and global ≤ 10 per run; skips non‑target paths (/about, /news) even with JS markers.
- Logs headless share and per‑page timings (when `EGC_OPS_JSON=1`) to inform future SLOs.

## Policies (High‑level)

- Respect robots.txt and ToS; do not bypass CAPTCHA or anti‑bot protections.
- Evidence is mandatory for all exported records (7 fields, including node screenshot ref).
- Headless is used sparingly and only on target pages; no automated clicks or form submissions in the PoC.

Features
Extraction of names, roles, and business contacts from corporate pages.


Evidence package per record (URL + selector + quote + node screenshot + metadata).


Targeted headless escalation by heuristics and per-domain/URL quotas.


SMTP validation of emails without sending messages (with MX/RCPT cache).


Requirements
Python 3.11+ required. macOS 13+ or newer recommended.


Network access for page fetching and DNS lookups (SMTP probe).


(Optional) Local Redis/RQ for a simple queue.


[Insert memory/CPU requirements for headless…]


## Gold Dataset (✅ Completed)

The project includes a high-quality gold dataset for testing and validation:

- **20 records** from 3 law firms (Seyfarth Shaw, Jackson Lewis, Frost Brown Todd)
- **309 total contacts** extracted (emails, phones)
- **100% success rate** with complete evidence packages
- **Multiple difficulty levels:** static pages, Cloudflare bypass, bulk leadership pages

### Gold Dataset Statistics
- **Companies:** Seyfarth (7 records), Jackson Lewis (5 records), Frost Brown Todd (8 records)
- **Contact Types:** 77 emails, 232 phone numbers
- **Evidence Completeness Rate:** 100%
- **Average Contacts per Record:** 15.4

### Validate Gold Dataset
```bash
python scripts/validate_gold_dataset.py
```

### Extract New Gold Records
```bash
python scripts/gold_extractor.py "https://example.com/people/john-doe"
```

Installation
# Clone
git clone [Insert_repository_URL]
cd evidence-grade-contacts

# Virtual env (Python 3.11)
python3.11 -m venv .venv
source .venv/bin/activate

# PoC dependencies (✅ Tested)
pip install httpx trafilatura selectolax playwright pydantic extruct

# Install Playwright browsers in the active venv (install per browser)
python -m playwright install chromium
python -m playwright install firefox
# (optional) python -m playwright install webkit

# Verify installation
which playwright

# (Optional) queue
pip install rq redis

## Quick Testing

### Run All Unit Tests
```bash
# All 49 unit tests
python -m pytest tests/unit/ -v

# Evidence package tests
python -m pytest tests/unit/test_evidence_builder.py -v

# Contact extraction tests  
python -m pytest tests/unit/test_extractors.py -v

# Pipeline integration tests
python -m pytest tests/unit/test_ingest_pipeline.py -v

# Export pipeline tests
python -m pytest tests/unit/test_export.py -v
```

### Validate Gold Dataset
```bash
# Verify gold dataset integrity
python scripts/validate_gold_dataset.py

# Extract new gold records
python scripts/gold_extractor.py "https://example.com/people/john-doe"
```

[Insert details for supported package managers/alternative installers…]
Configuration
Create config.yaml (example defaults):
renderer:
  mode: static-first
  headless:
    enabled: true
    max_pct_per_domain: 0.2     # ≤ 20%
    burst_rps: 0.2
static:
  burst_rps: 1
timeouts:
  budget_ms_per_url: 12000
backoff:
  cooldown_on_403: ["5m", "15m", "60m"]
evidence_pack:
  required_fields: [source_url, selector_or_xpath, verbatim_quote, dom_node_screenshot, timestamp, parser_version, content_hash]
scope:
  include_paths: ["/about", "/team", "/leadership", "/management", "/contacts", "/imprint", "/news", "/press"]
smtp_probe:
  enabled: true
  free_providers_blocklist: true
  cache_ttl_days: 7
compliance:
  enforce_robots_and_tos: true
  data_minimization: business_contacts_only
  deletion_requests: manual

Values mirror PoC limits/quotas and compliance policy.
Usage
1) Prepare input
input_urls.txt — one base company URL per line.


[Optional] Add extra paths if you need to go beyond the standard list.


2) Run the pipeline (CLI example)
# Example: single process, local export to out/
python -m egc.run --input input_urls.txt --config config.yaml --out ./out

See docs/cli.md for complete command reference and examples.
3) Results
out/contacts_*.json and out/contacts_*.csv
and people consolidation files: out/contacts_people_*.json and out/contacts_people_*.csv.

### Decision‑Only Export

Purpose: decision-maker filtering at export stage (no LLM), per-person with attached evidence.

CLI flags:
- `--decision-only` — enable writing decision-only people artifacts
- `--min-level {C_SUITE,VP_PLUS,MGMT}` — minimum decision level (default: VP_PLUS)

Artifacts written (when --decision-only is set and rows exist):
- `decision_people_*.json` — list of objects with fields:
  - `company, person_name, role_title, decision_level, decision_reasons, email, phone, vcard, evidence_email, evidence_phone, evidence_vcard, evidence_complete, verification_status`
- `decision_people_*.csv` — flat columns:
  - `company, person_name, role_title, decision_level, has_evidence_email, has_evidence_phone, has_evidence_vcard, verification_status, email, phone, vcard, source_url_email, source_url_phone, source_url_vcard`

VERIFIED criterion: `verification_status == "VERIFIED"` only when `evidence_complete == true` for the selected contact types (email/phone/vcard) in the row.

Examples:
```bash
# Basic
python -m egc.run --input input_urls.txt --config config/example.yaml --out ./out \
  --decision-only --min-level VP_PLUS

# With OPS JSON logs
EGC_OPS_JSON=1 python -m egc.run --input input_urls.txt --config config/example.yaml --out ./out \
  --decision-only --min-level VP_PLUS
```

Backwards compatibility: when run without these flags, behavior is unchanged and no decision_people_* files are created.


DOM node screenshots in out/evidence/.


Records without a full mini package are marked UNVERIFIED and not included in final exports.


Example Scenarios
Static coverage: selectors find people/roles; headless not needed → record VERIFIED when evidence is complete.


Headless escalation: static misses content or SPA markers present → Playwright renders the page, captures node screenshot, HTML flows back into the shared pipeline.


Email: extracted from mailto: or domain pattern; checked via non-sending SMTP probe with MX/RCPT cache.


Quality Metrics (PoC)
Evidence Completeness Rate (ECR) — share of records with a full mini package (target ≥ 95%).


Precision (≥ 90%), Recall (≥ 80%) — on a “gold” sample of 20–50 pages/2–3 companies.


UNVERIFIED Rate — expected < 5% with a healthy pipeline.


Compliance
robots.txt / ToS — strict gate: if disallowed, NO-GO.


Data minimization: business contacts only; no sensitive data.


Right to erasure: PoC provides a contact for requests; processing is manual.

See SECURITY.md for complete security policies and practices.


Known Limitations
No bypass of active anti-bot/Cloudflare; no CAPTCHA solving.


No enterprise-grade stores/immutability, production observability, or alerts.


Formal DPIA/LIA/DPA — out of PoC.


Technologies (PoC)
Fetching/parsing: httpx, Trafilatura/Selectolax.


Dynamic/JS: Playwright (limited, targeted).


Structured data: extruct (optional).


Schemas/validation: Pydantic.


JSON Schemas:
- Location: schemas/*.schema.json (draft 2020-12)
- Source of truth: src/schemas.py (Pydantic models)
- Regenerate: python scripts/export_json_schema.py

Export: CSV/JSON (local), SQLite (optional for demo queries).


Development & Build
See docs/testing.md for testing strategy (unit/integration/regression/e2e) and commands.


For the PoC, a single worker or simple queue (Redis/RQ) is enough. Horizontal scaling and DLQ/sharding are out of scope.


Test Data & Validation
[Insert location of the “gold” set and evaluation rules…]


Minimum target size: 20–50 pages across 2–3 companies to measure Precision/Recall.


FAQ
What happens when selectors “break”?
 — The record fails ECR, is marked UNVERIFIED, and excluded from output; rules need updating.
When is headless enabled?
 — On zero selector hits for target blocks plus small response size, on SPA redirects (MIME ≠ text/html), and/or dynamic/anti-bot markers.
Why not use LinkedIn/social networks?
 — Out of PoC scope and/or disallowed by ToS/robots.txt.
Roadmap (post-PoC)
[Insert: extended artifacts (html_ref/HTTP meta), observability, DLQ/canaries, formal DPIA/LIA, cloud storage & formats (S3/Parquet), queue scaling/sharding…]


Contacts
Email for data-deletion requests and feedback: [Insert address].


Technical inquiries: [Insert contact/repository/issue tracker].


License
[Insert license type and text/link.]

Quick navigation: TL;DR • PoC Scope • Success Criteria • Evidence Package • Compliance • Execution & Escalations • Pipeline • Data Format • Technologies • Limitations.
