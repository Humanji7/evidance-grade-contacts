# Architecture

This document explains how EGC works under the hood: static‑first fetching, guarded headless escalation, extraction, and the Evidence Package.

## Mini Evidence Package (Authoritative)
Seven required fields per verified record:
- source_url
- selector_or_xpath
- verbatim_quote
- dom_node_screenshot
- timestamp (ISO 8601)
- parser_version
- content_hash (SHA‑256)

A record is VERIFIED only if all seven are present and valid. UNVERIFIED records are excluded from exports by default.

## Data Processing Pipeline
1. Input normalization: domain, redirects, robots/ToS decision (GO/NO‑GO logged).
2. Crawl plan: generate candidate paths from scope, enqueue.
3. Fetching: static HTML first (httpx + Trafilatura/Selectolax) → escalate to Playwright only if needed.
4. Extraction: semantic selectors for names/titles/emails/phones; use extruct for structured data when present.
5. Contacts: mailto/phone/social links; compute email patterns by domain; non‑sending SMTP probe (free providers skipped by policy).
6. Evidence package: collect only the 7 required fields (node screenshot included).
7. Export: CSV/JSON; VERIFIED‑only by default.

## Escalation Rules (Guardrails)
Static → headless only when at least one holds:
- MIME ≠ text/html (redirect into SPA/JS app)
- selector_hits == 0 for target blocks AND tiny page (< 5 KiB)
- Anti‑bot/challenge markers (e.g., Cloudflare “Just a moment…”) or JS markers: data‑cfemail, cf_email, javascript:.*mailto, data‑email=, data‑phone=, data‑reactroot, ng‑app
- “Cards present, no contacts”: ≥3 repeating blocks with team|member|profile|person classes or many h3/h4 headings AND no mailto/tel anchors
- Target URL with 0 contacts after static extraction

## Budgets & Quotas
- max_headless_pct_per_domain ≤ 0.2 (recommended)
- Smart mode caps: per‑domain headless ≤ 2 pages per run; global headless ≤ 10 pages per run
- burst_rps_static = 1.0; burst_rps_headless = 0.2
- budget_ms_per_url = 12000
- cooldown_on_403: 5m → 15m → 60m

## Technology Stack
- Python 3.11+
- httpx, Trafilatura/Selectolax (static HTML)
- Playwright (headless, escalation only)
- Pydantic (schemas)
- extruct (optional structured data)
- Optional: Redis/RQ (simple queue), SQLite (demo queries)

## Models & Schemas
- Canonical Pydantic models live in src/schemas.py (Contact, Evidence, ContactExport)
- JSON Schemas are generated to schemas/*.schema.json
- Regenerate: `python3 scripts/export_json_schema.py`

## Exports
- contacts_*.{json,csv}: VERIFIED contacts only (evidence attached)
- contacts_people_*.{json,csv}: people‑level consolidation

