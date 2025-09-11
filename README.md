# Evidence‑Grade Contacts (EGC)

Extract people and business contacts from public pages of corporate websites — with a Mini Evidence Package (URL + selector/XPath + verbatim quote + node screenshot + timestamp + parser_version + content_hash) for every fact. Static‑first, with guarded headless escalation only when needed.

• Static‑first parsing (httpx + Trafilatura/Selectolax)
• Guarded Playwright escalation with per‑domain/global budgets
• Evidence‑first design: only VERIFIED records (complete packages) are exported
• Compliance‑aware: robots.txt/ToS gates, business contacts only

## Quickstart

Prereqs: Python 3.11+, macOS/Linux, network access; Playwright browsers installed.

```bash
# Clone
git clone https://github.com/Humanji7/evidance-grade-contacts.git
cd evidence-grade-contacts

# Env
python -m venv .venv
source .venv/bin/activate
pip install httpx trafilatura selectolax playwright pydantic extruct
python -m playwright install chromium  # + firefox if needed

# Config
cp config/example.yaml config.yaml
echo "https://example.com" > input_urls.txt

# Run (Smart mode by default)
python -m egc.run --input input_urls.txt --config config.yaml --out ./out
```

Outputs:
- out/contacts_*.{csv,json} — VERIFIED-only
- out/contacts_people_*.{csv,json} — people-level consolidation
- out/evidence/ — node screenshots

Tip: Enable Aggressive Static mode for tougher sites: add --aggressive-static.

## Why “Evidence‑Grade”

Every exported contact field carries a Mini Evidence Package:
- source_url, selector_or_xpath, verbatim_quote, dom_node_screenshot, timestamp (ISO 8601), parser_version, content_hash (SHA‑256).

A record is VERIFIED only if all 7 fields are present and valid; otherwise it’s UNVERIFIED and excluded by default.

Example:
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

## How it works

1) Normalize input → decide robots/ToS (GO/NO‑GO)
2) Discover target‑like pages (team/leadership/contacts) when needed
3) Static fetch & parse first
4) Guarded headless (Playwright) only on clear triggers (SPA mime, tiny pages with 0 hits, anti‑bot markers, “cards present, no contacts”) with budgets (per‑domain/global caps)
5) Extract names/titles/emails/phones (+ vCard when allowed)
6) Build Mini Evidence Packages → export VERIFIED-only CSV/JSON

## Decision Filter (optional)

Post‑processing to keep VP+ / C‑Suite only, normalize emails/phones, optional vCard enrichment (budgeted).

```bash
python3 scripts/decision_filter.py \
  --input output/contacts_people_*.json \
  --out-dir output/decision \
  --min-level VP_PLUS
```

See more flags in docs/cli.md.

## Documentation

- CLI reference: docs/cli.md  
- Testing strategy: docs/testing.md  
- Architecture: docs/architecture.md  
- Operations & budgets: docs/operations.md  
- Gold dataset: docs/gold_dataset.md  
- Config template: config/example.yaml  
- Security & compliance: SECURITY.md

## Compliance (PoC)

- Respect robots.txt and ToS; red‑flag sources (LinkedIn/X/Meta) are out of scope  
- Data minimization: business contacts only  
- Headless budgets to limit cost and load; no CAPTCHA solving or bypass tooling  
- Requests are HTTPS‑only

## Development

```bash
# Run tests
python -m pytest tests/ -v

# Lint/format (recommended)
black src/ tests/
flake8 src/ tests/
mypy src/
```

## Roadmap

- Extended artifacts (optional HTML/HTTP metadata)
- Observability & CI metrics
- Queue scaling & distributed workers

## Contributing

Issues and PRs are welcome. Please run tests and linters before submitting.

## License

MIT
