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
Evidence Completeness Rate (ECR) ≥ 95% — each record must have a full mini-package.


Precision ≥ 90%, Recall ≥ 80% on a small “gold” set (20–50 pages across 2–3 companies).


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

Features
Extraction of names, roles, and business contacts from corporate pages.


Evidence package per record (URL + selector + quote + node screenshot + metadata).


Targeted headless escalation by heuristics and per-domain/URL quotas.


SMTP validation of emails without sending messages (with MX/RCPT cache).


Requirements
[Insert OS and Python/Node/Docker version details if applicable…]


Network access for page fetching and DNS lookups (SMTP probe).


(Optional) Local Redis/RQ for a simple queue.


[Insert memory/CPU requirements for headless…]


Installation
# Clone
git clone [Insert_repository_URL]
cd evidence-grade-contacts

# Virtual env (Python example)
python -m venv .venv
source .venv/bin/activate

# PoC dependencies
pip install httpx trafilatura selectolax playwright pydantic extruct [and_others]
python -m playwright install

# (Optional) queue
pip install rq redis

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
python -m egc.run --input input_urls.txt --config config.yaml --out ./out --dry-run

Note: Currently implemented as stub (use --dry-run for validation).
See docs/cli.md for complete command reference and examples.
3) Results
out/contacts.json and/or out/contacts.csv.


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
- Regenerate: python3 scripts/export_json_schema.py

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

