# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

Evidence-Grade Contacts (EGC) is a proof-of-concept system that extracts people (name, title) and business contacts (email/phone/links) from public pages of corporate websites (e.g., /about, /team, /leadership, /contacts, /imprint, sometimes /news|/press) with a mandatory "mini evidence package" for every fact. Rendering is static-first, with targeted escalation to Playwright when needed. Any record without a complete evidence package is marked UNVERIFIED and excluded from exports.

**Key Philosophy**: Every contact field is backed by a Mini Evidence Package (source_url + selector_or_xpath + verbatim_quote + dom_node_screenshot + timestamp + parser_version + content_hash).

### Scope & Audience

**Sources**: Public company websites and other permitted public sources only. We do not access platforms that explicitly forbid automated access in their ToS/robots.txt (e.g., LinkedIn, X/Twitter, Meta products).

**Primary users**: Data stewards/analysts, sales & rev-ops, and engineering teams.

**Outputs**: Evidence-grade contact records where each field is backed by a complete Mini Evidence Package with traceability.

### Performance & Cost Considerations

**Static-First Approach**: Start with static HTML fetching and escalate to headless browser only on demand to reduce costs.

**Scaling Strategy**: For the PoC, a single process/simple worker/local queue (e.g., Redis/RQ) is sufficient, no DLQ/sharding.

**Operational Guardrails**: Per-domain headless budget and quotas to control costs and respect rate limits.

## Project Structure

```
evidence-grade-contacts/
├── src/
│   ├── pipeline/           # ETL/ELT stages (ingest, normalize, validate, export)
│   ├── validation/         # Rules, schemas, SMTP policy & probe, confidence index
│   ├── evidence/           # Proof builders, hashing, screenshots storage
│   ├── orchestration/      # Simple worker (RQ/Redis), task definitions
│   ├── schemas/            # Pydantic models (Contact, Evidence, API I/O)
│   └── api/                # HTTP API endpoints & services (optional for PoC)
├── data/                   # (gitignored)
│   ├── raw/                # Raw snapshots
│   ├── processed/          # Normalized & validated records
│   └── gold_datasets/      # Ground truth for regression tests
├── docs/
│   ├── examples/           # Minimal spiders & Playwright snippets
│   ├── glossary.md         # Factory metaphors → system terms
│   └── api.md              # Extended API description
├── tests/                  # Unit/integration/regression tests
├── config/                 # Config templates, selector & escalation guidelines
├── scripts/                # CLI utilities (crawl, validate, export)
├── infra/                  # Docker/IaC, deployment manifests
└── output/                 # Generated reports & exports (JSON/CSV)
```

## Core Architecture

### Mini Evidence Package

**Mini Evidence Package** = Seven fields required for each verified record:
- `source_url`: Source page URL
- `selector_or_xpath`: CSS/XPath used for extraction
- `verbatim_quote`: Verbatim innerText content
- `dom_node_screenshot`: Node screenshot reference
- `timestamp`: ISO 8601 extraction time
- `parser_version`: Tool version for reproducibility
- `content_hash`: SHA-256 of normalized node text

Records missing any required field are marked UNVERIFIED and excluded from exports.

### Data Processing Pipeline
1. **Input normalization**: domain, redirects, robots/ToS decision (GO/NO-GO logged).
2. **Crawl plan**: generate candidate paths (from scope), enqueue.
3. **Fetching**: Static fetch first (httpx + Trafilatura/Selectolax) → headless if necessary.
4. **Escalation (if needed)**: Promote to Playwright only if:
   - selector_hits == 0 for target blocks and content_length < 5 KiB, or
   - MIME ≠ text/html due to redirect into SPA/JS app, or
   - dynamic/anti-bot markers detected.
5. **Extraction**: rules/selectors (name/title/contacts); when present — extruct for JSON-LD/Microdata.
6. **Contacts**: mailto/phone/social links; compute email patterns by domain + non-sending SMTP probe (exclude free providers).
7. **Evidence package**: collect the 7 required fields only.
8. **Export**: CSV/JSON; UNVERIFIED are excluded.

### Escalation Rules (Guardrails)

Static → headless per the conditions above. Enforce:
- **max_headless_pct_per_domain** (≤ 0.2 recommended)
- **burst_rps_static** (1.0) / **burst_rps_headless** (0.2)
- **budget_ms_per_url** (12000)
- **cooldown_on_403** (5m → 15m → 60m)


### Technology Stack

**Core Technologies:**
- Python 3.11+ (primary language)
- httpx, Trafilatura/Selectolax (static-first web fetching)
- Playwright (headless browser automation, escalation only)
- Pydantic (data modeling and validation)
- extruct (optional for structured data)

**Optional Dependencies:**
- Redis/RQ (simple queue)
- SQLite (optional for demo queries)

**Architecture Approach:**
- **Static-First Processing**: Always attempt static HTML parsing before Playwright escalation
- **Cost-Efficient Escalation**: Promote to headless browser only when static fetching fails specific conditions
- **Evidence Package**: Every extraction must generate a complete mini package

## Development Workflow

### Recent Enhancements (Updated)
- Aggressive Static Mode (CLI: `--aggressive-static`):
  - Relaxed name validation (≥2 tokens with at least one letter each, Unicode-aware)
  - Email de-obfuscation (at/dot patterns, HTML entities, simple JS concatenations)
  - Phone extraction from text (only with markers like "phone|tel|тел|telefon" and normalized 10–15 digits)
  - vCard links detection (.vcf or text contains "vcard")
  - Table extractor prioritized before generic fallback; repeating cards used only if tables absent
  - Role stop-list normalized to "Unknown" (e.g., "email", "areas of focus:", "coming soon", "open seat")
- URL Normalization and Candidate Limiting:
  - CLI normalizes and deduplicates candidate URLs (host lowercased, drop query/fragment, trim trailing slash) and limits per-domain pages (`--max-pages-per-domain`, default 10)
  - Discovery filters facet links (skips `?` and `#`) and normalizes in-domain links
- Export-layer Dedupe and Normalized Source URLs:
  - Global dedupe by (company_norm, person_norm, contact_type, contact_value_norm) with quality tie-breaks: anchor>text, semantic URL (/leadership|/our-team|/team), role!=Unknown, shorter canonical URL, fresher captured_at
  - Normalized source_url in CSV/JSON outputs (report-only; Evidence models remain unchanged)
  - Log line: "🧹 Dedupe: kept X of Y"
- Decision Filter (post-processing CLI):
  - DecisionLevel classification with thresholding: C_SUITE > VP_PLUS > MGMT > NON_DM > UNKNOWN (default min-level: VP_PLUS)
  - Signals: positive title patterns (President, Managing Director, General Counsel, VP, Head of ...), negative guards (Associate, Counsel, Paralegal, Intern), structural uplift (leadership/management paths), generic inbox flag (info@, support@)
  - Normalization: email de-obfuscation and phone normalization to E.164-like format (+1 default when no country code)
  - Optional vCard enrichment: guarded by budget/timeout/max-bytes and `--site-allow` hostname allowlist; non-fatal errors recorded in decision_reasons
  - Outputs per input: decision_<basename>.json/.csv and a summary line (total/kept/dropped, level counts, top drop reasons)

### Smart mode (default)

Smart mode is the default run profile. It executes:
- Static++ first → escalate to Playwright only when needed (guarded) → always produce people-level exports in addition to base CSV/JSON.
- On-demand discovery: if the input URL is already a target page (path contains team|our-team|people|leadership|management|contacts|imprint|impressum), skip discovery; otherwise, discover in-domain target-like links (limit 4 per domain) with a fast HEAD prefilter (~2s).
- Headless budgets on top of the existing 20% per-domain quota:
  - Per-domain headless cap: ≤ 2 pages per run
  - Global headless cap: ≤ 10 pages per run
  - When caps are exceeded, escalation is skipped and the log prints: "headless budget exhausted".
- Exports: perform global dedupe and always write contacts_people_*.{csv,json} alongside the base contacts files.

Escalation triggers considered in Smart mode (superset):
- MIME ≠ text/html (redirect into SPA/JS app)
- selector_hits == 0 and tiny page (< 5 KiB)
- Anti-bot/challenge markers (e.g., Cloudflare "Just a moment…")
- JS markers (escalate regardless of size): data-cfemail, cf_email, javascript:.*mailto, data-email=, data-phone=, data-reactroot, ng-app
- "Cards present, no contacts": ≥3 repeating blocks with class containing team|member|profile|person or many h3/h4 headings AND no mailto/tel anchors
- Target URL with 0 contacts after static extraction

Operational logs:
- At start of run: "Smart mode: discovery=auto, headless=guarded, budgets: domain=2, global=10"
- On escalation: "via playwright: reasons=[…]"
- On exhausted budgets: "headless budget exhausted"

### Initial Setup
```bash
# Clone
git clone [repository_URL]
cd evidence-grade-contacts

# Python environment (3.11+ required)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# PoC dependencies (✅ Tested)
pip install httpx trafilatura selectolax playwright pydantic extruct

# Install Playwright browsers in the active venv (install per browser)
python -m playwright install chromium
python -m playwright install firefox
# (optional)
# python -m playwright install webkit

# (Optional) queue
pip install rq redis

# Environment configuration
cp config/example.yaml config.yaml
# Edit config.yaml with required settings:
```

### Core Development Commands

#### Data Processing Pipeline
```bash
# Prepare input
echo "https://example.com" > input_urls.txt

# Run the pipeline (default Smart mode, no flags required)
python -m egc.run --input input_urls.txt --config config.yaml --out ./out
```

Expected outputs:
- Base exports: contacts_*.csv and contacts_*.json (VERIFIED-only by default)
- People consolidation: contacts_people_*.csv and contacts_people_*.json

#### Testing & Quality Assurance
```bash
# Run full test suite
python -m pytest tests/

# Run with coverage
python -m pytest --cov=src tests/

# Regression tests against gold datasets
python -m pytest tests/regression/ --gold-data=data/gold_datasets/
```

#### SMTP Validation
```bash
# SMTP deliverability check
python scripts/smtp_probe.py --emails-file output/contacts.csv
```

#### Decision Filter (post-processing)
```bash
# Keep VP+ and C-Suite only, write outputs next to ./output/decision
python3 scripts/decision_filter.py \
  --input output/contacts_people_*.json \
  --out-dir output/decision \
  --min-level VP_PLUS

# Strict: only C-Suite
python3 scripts/decision_filter.py \
  --input output/contacts_people_*.json \
  --out-dir output/decision \
  --min-level C_SUITE

# Enrich Unknown titles via vCard for allowed hosts (budget=10)
python3 scripts/decision_filter.py \
  --input output/contacts_people.json \
  --out-dir output/decision \
  --fetch-vcard --vcard-budget 10 --site-allow example.com lawfirm.com

# Dry-run (summary only; no files written)
python3 scripts/decision_filter.py \
  --input output/contacts_people_a.json output/contacts_people_b.json \
  --min-level MGMT --dry-run
```

See docs/cli.md for full CLI contract and exit codes.

### Mini-check: SMTP Probe (≤ 1 minute)
Use when you need to verify the module quickly without thinking.

```bash
# 1) Run only smtp_probe unit tests (no network)
python3 -m pytest -q tests/unit/test_smtp_probe*.py

# 2) Offline CLI proof (no network): writes JSON
python3 scripts/smtp_probe.py --email user@example.com --out test_out/probe.json

# 3) Disable free-domain policy (env override) and probe a free domain
EGC_SKIP_FREE=0 python3 scripts/smtp_probe.py --email user@gmail.com --out test_out/probe_gmail.json
```
Expected:
- Tests: all passed
- probe.json exists; JSON with fields email, domain, mx_found, error_category
- probe_gmail.json exists; policy off → you get smtp_code/error_category from live RCPT attempt (depending on network)

## API Documentation

For the PoC, API is optional. If implemented, basic endpoints would be:

**GET /contacts?domain=example.com&limit=…**
Returns a list of materialized contact records.

### Record Schema
```json
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
```

## Validation Details

### Schema enforcement
Pydantic for strict types; email/phone validators.

### SMTP probe
Non-sending verification with policy:
- Cache MX/RCPT results for SMTP_MX_TTL_DAYS (default 7 days)
- No probing of free providers (gmail/outlook etc.) by default
- Per-domain backoff

### Evidence Completeness
Every record must have all 7 required evidence fields to be VERIFIED.

## Quality Metrics & SLOs

The system maintains quality standards for the PoC:

| Metric | Target | Definition |
|--------|--------|------------|
| Precision | ≥ 90% | True-positive share among predicted positives |
| Recall | ≥ 80% | True-positive share among actual positives |
| Evidence Completeness Rate (ECR) | ≥ 95% | Share of fields with all mandatory evidence elements |
| UNVERIFIED Share | < 5% | Records lacking mandatory evidence fields |

## Compliance & Legal Framework

### Decision tree (simplified)
- robots.txt disallows target paths → NO-GO
- ToS forbids scraping → NO-GO
- Ambiguity → legal review before access

### Red-flag sources (NO-GO)
- LinkedIn · X/Twitter · Facebook/Meta properties

### Data subject rights (DSR)
- Manual processing of deletion/update requests
- Data minimization: business contacts only

## Known Limitations

### PoC Limitations
- ~~No bypass of active anti-bot/Cloudflare~~ (✅ **IMPLEMENTED**: Playwright with anti-bot detection)
- No enterprise-grade stores/immutability, production observability, or alerts
- Formal DPIA/LIA/DPA — out of PoC
- No full HTML snapshots/HTTP metadata (extended artifacts)
- Simple worker or queue, no horizontal scaling or DLQ/sharding
- ~~No evidence packaging system~~ (✅ **IMPLEMENTED**: Complete Mini Evidence Packages)
- ~~No contact extraction pipeline~~ (✅ **IMPLEMENTED**: Semantic selectors with evidence)

## Development Guidelines

### Code Quality Gates
- **ECR**: No degradation of Evidence Completeness Rate
- **SLO Compliance**: Maintain precision ≥ 90%, recall ≥ 80%
- **Selector Stability**: Prefer semantic selectors over positional
- **Evidence Integrity**: All fields must have complete mini packages

### Pre-commit Requirements
```bash
# Install pre-commit hooks
pre-commit install

# Manual pre-commit check
pre-commit run --all-files

# Lint and format
black src/ tests/
flake8 src/ tests/
mypy src/
```

### Testing Strategy
`docs/testing.md` contains the complete testing strategy and structure.

```bash
# Unit tests (fast feedback)
python -m pytest tests/unit/ -v

# Export pipeline tests
python -m pytest tests/unit/test_export.py -v

# Integration tests (with Playwright)
python -m pytest tests/integration/ --browser chromium
# Firefox example
python -m pytest tests/integration/ --browser firefox

# Regression tests (against gold datasets)
python -m pytest tests/regression/ --compare-gold

# End-to-end pipeline test
python -m pytest tests/e2e/ --slow
```

## Implementation Status (✅ Updated)

### Core Components Completed
- ✅ Aggressive Static Mode (guarded by `--aggressive-static`)
- ✅ URL Normalization & Candidate Limiting (CLI `--max-pages-per-domain`, discovery facet filter)
- ✅ Export-layer Dedupe & Normalized `source_url` (report-only)
- ✅ **Static-First Pipeline**: StaticFetcher with robots.txt compliance
- ✅ **Escalation Logic**: EscalationDecider with anti-bot detection
- ✅ **Playwright Integration**: Secure headless browser with sandboxing
- ✅ **Evidence Package Builder**: Complete Mini Evidence Package system
- ✅ **Contact Extractor**: Semantic selectors for names, titles, emails, phones
- ✅ **Pipeline Orchestration**: IngestPipeline with domain tracking and quotas
- ✅ **Export Pipeline**: ContactExporter with CSV/JSON output and VERIFIED filtering
- ✅ Decision Filter CLI: post-extraction classifier and filter (`--min-level`, normalization, optional vCard enrichment)
- ✅ **Unit Test Coverage**: 52 tests passing with complete evidence validation

### Testing Infrastructure
- ✅ **Evidence Builder Tests**: 11 tests covering all 7 required fields
- ✅ **Contact Extractor Tests**: 11 tests for extraction and validation
- ✅ **Pipeline Integration Tests**: 7 tests for end-to-end orchestration
- ✅ **Export Pipeline Tests**: 14 tests for CSV/JSON export with evidence
- ✅ **Static Fetcher Tests**: 2 tests for robots.txt compliance
- ✅ **Escalation Tests**: 4 tests for anti-bot detection logic
- ✅ **Decision Filter Tests**: 3 tests (CLI invocation, classification rules, vCard enrichment budget)

### Data Quality Metrics
- Duplicate Export Key Rate: < 1% (based on key: company_norm, person_norm, contact_type, contact_value_norm)
- ✅ **Evidence Completeness Rate**: 100% (all 7 fields validated)
- ✅ **Schema Validation**: Automatic Pydantic model enforcement
- ✅ **Content Integrity**: SHA-256 hashing for all extracted content
- ✅ **Security Compliance**: HTTPS-only, rate limiting, sandbox isolation

## Key Development Patterns

1. **Static-First Processing**: Always attempt static HTML parsing before Playwright escalation
2. **Evidence-First Design**: Every extraction must generate a complete mini package
3. **Compliance Checks**: Validate source permissions before any data collection
4. **Quality Metrics**: Focus on maintaining ECR ≥ 95%, Precision ≥ 90%, Recall ≥ 80%

## Gold Dataset (✅ Completed)

The project has a complete gold dataset for testing and regression validation:

### Status
- **20 verified records** across 3 law firms
- **309 total contacts** (77 emails, 232 phones)
- **100% success rate** with complete evidence packages
- **100% Evidence Completeness Rate** (all 7 required fields present)

### Companies Covered
- **Seyfarth Shaw LLP** (7 records) - Cloudflare bypass testing
- **Jackson Lewis P.C.** (5 records) - Static-first pages  
- **Frost Brown Todd** (8 records) - New firm, different CMS

### Validation
```bash
# Validate entire gold dataset
python3 scripts/validate_gold_dataset.py

# Extract new gold records
python3 scripts/gold_extractor.py "https://example.com/people/john-doe"
```

## Common Troubleshooting

Operational logs to look for:
- Startup profile: Smart mode profile line appears once at run start.
- Escalation: via playwright lines with reasons — present on 1–2 URLs typically.
- Budgets: headless budget exhausted — printed when domain/global caps prevent escalation.

```bash
# Validate gold dataset quality
python3 scripts/validate_gold_dataset.py

# Debug selector failures  
python scripts/debug_selectors.py --url https://example.com --selector "main .team"

# Check ECR compliance
python scripts/check_ecr.py --threshold 0.95

# Check SMTP probe issues
python scripts/debug_smtp.py --email test@example.com
```

## Configuration Management

### Config Authority
`config/example.yaml` is the canonical configuration specification for EGC PoC.

**When coding:**
- Reference this file for all default values and structure
- Validate config on application startup  
- Support environment variable overrides for secrets
- Update README.md if config schema changes

**Key principles:**
- Static-first approach with targeted escalation
- Mini Evidence Package (7 required fields)
- PoC guardrails (max_headless_pct_per_domain: 0.2)
- Compliance-first (robots.txt/ToS enforcement)

## Data Schema Standards

### Pydantic Models Authority
`src/schemas.py` contains the canonical Contact and Evidence models for EGC PoC.

**When working with data:**
- Use Python 3.11+ with Pydantic v2 for all data schemas
- All contact records MUST use Contact and Evidence models
- Validation is enforced automatically (email/phone/URL formats)
- VERIFIED status requires complete Mini Evidence Package (all 7 fields)
- Use ContactExport model for CSV/JSON exports

**Verification Status Semantics (Authoritative):**
- `verification_status` is computed from Evidence completeness during model initialization; it cannot be trusted from input.
- Any attempt to set `verification_status` manually is ignored; status is derived strictly from the 7-field Mini Evidence Package.
- Evidence completeness = all 7 fields present and non-empty (strings trimmed), with valid types (e.g., timestamp is a datetime).
- Downstream code must not rely on manual overrides of `verification_status`.
- All exports include VERIFIED only by default; UNVERIFIED are excluded per PoC policy.

**Model principles:**
- Evidence-first for contact data: extracted personal info requires complete proof package
- Auto-validation: invalid contact data raises errors immediately  
- Type safety: strict typing with enums where appropriate
- Export ready: built-in conversion to flat formats

### JSON Schema Exports
- Location: schemas/*.schema.json (draft 2020-12)
- Source: generated from src/schemas.py (Pydantic v2)
- Regenerate: python3 scripts/export_json_schema.py
- Use for: external validation, API contracts, interoperability

## CLI Standards

### Command Interface Authority
`docs/cli.md` contains the complete CLI contract for all EGC commands.

**When implementing commands:**
- Follow exit code standards (0=success, 1=config error, 2=input error, 3=runtime error)
- Use environment variables for secrets (never hardcode credentials)
- Implement non-paginated, non-interactive output for CI/CD compatibility
- Support --dry-run for validation without execution
- Reference config/example.yaml for default parameter values
- Start with working stubs (argument parsing, validation, exit codes) before full logic

## I/O Standards

### Data Format Authority
`docs/io.md` contains complete specification of input/output formats.

**When handling data:**
- Input: URLs file format, validation rules, error handling
- Output: JSON (nested), CSV (flat), evidence artifacts structure
- All exports exclude UNVERIFIED records (PoC policy)
- Evidence completeness: all 7 fields required for VERIFIED status

## Security Standards

### Security Policy Authority
`SECURITY.md` contains security policies and practices for EGC PoC.

**When implementing:**
- All secrets via environment variables only (never hardcode)
- Respect robots.txt/ToS compliance (red-flag sources forbidden)
- Data minimization: business contacts only, no personal data
- Rate limiting: static 1.0 RPS, headless 0.2 RPS per domain

## Code Quality Standards

### Pre-commit Requirements
`.pre-commit-config.yaml` configured for automated quality checks.

**Before commits:**
- Run: `pre-commit install` (setup once)
- All commits automatically checked: black, flake8, mypy, isort
- Schema tests run on src/schemas.py changes
- YAML config validation on config changes
