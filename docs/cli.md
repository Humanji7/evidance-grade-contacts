# CLI Contract - Evidence-Grade Contacts PoC

Complete command-line interface specification for the EGC proof-of-concept system.

## Overview

EGC provides a suite of CLI tools for extracting, validating, and exporting business contact information from corporate websites with evidence-grade traceability.

**Core principle**: Static-first approach with targeted Playwright escalation, Mini Evidence Package (7 fields) for each verified record.

## Quick Start

```bash
# 1. Prepare input file
echo "https://example.com" > input_urls.txt

# 2. Run the pipeline
python -m egc.run --input input_urls.txt --config config/example.yaml --out ./output

# 3. Check results
ls output/
# contacts.csv  contacts.json  evidence/
```

## Commands

### Main Pipeline: `egc.run`

Extract contacts from corporate websites with evidence packages.

**Syntax:**
```bash
python -m egc.run --input <urls_file> --config <config_file> --out <output_dir> [OPTIONS]
```

**Required Arguments:**
- `--input` / `-i`: Path to file containing URLs (one per line)
- `--config` / `-c`: Configuration file (YAML format)
- `--out` / `-o`: Output directory for results

**Optional Arguments:**
|- `--verbose` / `-v`: Enable verbose logging
|- `--dry-run`: Validate configuration without processing
|- `--no-discovery`: Disable adaptive link discovery; use only include_paths expansion
|- `--exact-input-only`: Process only URLs provided in `--input` (disables discovery and `include_paths` expansion), also skips prefilter (HEAD) and preserves trailing slash in URLs
|- `--no-prefilter`: Disable pre-filter HTTP checks
|- `--no-headless`: Disable Playwright escalation (static-only)
|- `--static-timeout` SECONDS: Static fetch timeout (default 12.0)
|- `--prefilter-timeout` SECONDS: Prefilter HEAD timeout (default 5.0)
|- `--aggressive-static`: Enable aggressive static heuristics (name, email de-obfuscation, text phones with markers, VCF, table extractor first, role stop-list→Unknown)
|- `--max-pages-per-domain` N: Limit number of candidate pages per domain after normalization (default 10)
|- `--include-all`: Export UNVERIFIED as well (default: VERIFIED only)

**Examples:**
```bash
# Default Smart mode
python -m egc.run \
  --input input_urls.txt \
  --config config/example.yaml \
  --out ./output \
  --verbose

# Exact-only: process only URLs from input (no discovery, no include_paths expansion)
python -m egc.run \
  --input input_urls.txt \
  --config config/example.yaml \
  --out ./output \
  --exact-input-only

# No discovery but keep include_paths expansion from config
python -m egc.run \
  --input input_urls.txt \
  --config config/example.yaml \
  --out ./output \
  --no-discovery
```

**Output Structure:**
```
output/
├── contacts.csv          # Flattened export with evidence fields (source_url normalized for report)
├── contacts.json         # Full Contact records with nested evidence (evidence.source_url normalized for report)
└── evidence/             # DOM node screenshots
    ├── screenshot_001.png
    └── screenshot_002.png
```

**Exit Codes:**
- `0`: Success
- `1`: Configuration error
- `2`: Input validation error
- `3`: Processing error (see logs)

---

### Debug Selectors: `egc.debug.selectors`

Debug CSS/XPath selectors on specific pages.

**Syntax:**
```bash
python scripts/debug_selectors.py --url <target_url> --selector <css_selector> [OPTIONS]
```

**Required Arguments:**
- `--url`: Target webpage URL
- `--selector`: CSS selector or XPath to test

**Optional Arguments:**
- `--headless`: Force Playwright mode (default: static first)
- `--screenshot`: Save screenshot of matched elements

**Example:**
```bash
python scripts/debug_selectors.py \
  --url https://example.com/team \
  --selector "div.person-card" \
  --screenshot
```

**Exit Codes:**
- `0`: Selector matched elements
- `1`: No matches found
- `2`: Page load error

---

### ECR Compliance Check: `egc.check.ecr`

Validate Evidence Completeness Rate for processed records.

**Syntax:**
```bash
python scripts/check_ecr.py --threshold <rate> [OPTIONS]
```

**Required Arguments:**
- `--threshold`: Minimum ECR threshold (0.0-1.0, e.g., 0.95 for 95%)

**Optional Arguments:**
- `--input-dir`: Directory containing contacts.json (default: ./output)
- `--report`: Generate detailed compliance report

**Example:**
```bash
python scripts/check_ecr.py --threshold 0.95 --input-dir ./output --report
```

**Exit Codes:**
- `0`: ECR meets threshold
- `1`: ECR below threshold
- `2`: Invalid input data

---

### SMTP Probe: `egc.smtp.probe`

Non-sending RCPT TO check with MX lookup, caching, and policy guardrails.

**Syntax:**
```bash
python scripts/smtp_probe.py [--email <addr> | --emails-file <path>] [OPTIONS]
```

**Inputs (one of):**
- `--email` — одиночный адрес
- `--emails-file` — путь к txt/csv (любой столбец с email попадёт в список)

**Key Options:**
- `--out` PATH — вывод в JSON (по умолчанию stdout) или CSV (если *.csv)
- `--timeout` SEC — таймаут SMTP (по умолчанию из env SMTP_TIMEOUT или 10)
- `--mx-ttl-days` N — TTL кэша MX и RCPT (по умолчанию из env SMTP_MX_TTL_DAYS или 7)
- `--max-per-domain` N — лимит попыток RCPT на домен за запуск (по умолчанию 5)
- `--skip-free` / `--no-skip-free` — пропускать бесплатные домены (дефолт: включено; можно отключить)
- `--mx` HOST — явный MX для отладки (обычно не нужен; скрипт сам делает lookup)
- `--verbose` — подробные сообщения в stderr

**Environment overrides:**
- `SMTP_TIMEOUT` — таймаут SMTP в секундах
- `SMTP_MX_TTL_DAYS` — TTL кэша для MX и email результатов
- `EGC_SKIP_FREE=1|0` — включить/отключить политику пропуска бесплатных доменов

**Behavior:**
- Кэш: .egc_cache.db (таблицы mx_cache, email_cache) в корне репозитория
- MX lookup: сначала свежий кэш → иначе DNS → запись в кэш
- RCPT probe: по порядку MX до первого успеха; 4xx → in-memory backoff в рамках запуска
- Политики: пропуск бесплатных доменов (если включено), лимит попыток на домен

**Output record (JSON/CSV):**
```
{
  "email": "user@example.com",
  "domain": "example.com",
  "mx_found": true,
  "mx_used": "mx.example.com",
  "accepts_rcpt": false,
  "smtp_code": 550,
  "smtp_message": "No such user",
  "error_category": "perm",
  "rtt_ms": 42,
  "checked_at": "<epoch or omitted>"
}
```

**Exit Codes:**
- `0` — успех (скрипт отработал корректно, даже если есть недоставляемые адреса)
- `2` — ошибка входных данных (нет валидных emails)
- `3` — системная ошибка (DNS/сеть/SQLite недоступны)

**Examples:**
```bash
# Оффлайн проверка (без сети): JSON в файл
python scripts/smtp_probe.py --email user@example.com --out test_out/probe.json

# Политика бесплатных доменов отключена
EGC_SKIP_FREE=0 python scripts/smtp_probe.py --email user@gmail.com --out test_out/probe_gmail.json

# Пакетная проверка и CSV-вывод
python scripts/smtp_probe.py --emails-file output/contacts.csv --out test_out/probe.csv
```

---

### Decision Filter: `egc.decision.filter`

Post-process people-level outputs to keep only decision-makers at or above a chosen threshold. Also normalizes certain fields and can optionally enrich Unknown titles from .vcf (vCard) files under a strict budget.

**Syntax:**
```bash
python scripts/decision_filter.py --input <people.json [people2.json ...]> \
  [--out-dir <dir>] [--min-level {C_SUITE,VP_PLUS,MGMT}] [--dry-run] \
  [--fetch-vcard] [--vcard-budget N] [--timeout-s SEC] \
  [--max-vcard-bytes BYTES] [--site-allow host1 host2 ...]
```

**Inputs:**
- `--input` (one or more): people JSON files (each must be a JSON list of objects)

**Options:**
- `--out-dir` PATH: Output directory (default: `out/`)
- `--min-level` {`C_SUITE`,`VP_PLUS`,`MGMT`}: Minimum decision-maker threshold (default: `VP_PLUS`)
- `--dry-run`: Only print summary; do not write outputs
- `--fetch-vcard`: Attempt to fetch `.vcf` links for records with `role_title == "Unknown"` to extract TITLE/ROLE; controlled by budget and allowlist
- `--vcard-budget` N: Max number of vCards to fetch per run (default: 50)
- `--timeout-s` SEC: HTTP timeout for vCard requests (default: 2.5)
- `--max-vcard-bytes` BYTES: Maximum vCard size (default: 65536)
- `--site-allow` HOST [HOST...]: Only fetch vCards for these hostnames (skip others)

**Behavior:**
- Classification levels: `C_SUITE` > `VP_PLUS` > `MGMT` > `NON_DM` > `UNKNOWN`
- Signals:
  - Title patterns for positives (e.g., President, Managing Director, General Counsel, VP, Head of ...)
  - Negative guard (e.g., Associate, Counsel, Paralegal, Intern)
  - Structural uplift if any source URL path contains leadership/management-like segments
  - Email heuristic flags generic inboxes (e.g., info@, support@)
- Normalization:
  - Email: basic de-obfuscation and lowercase (e.g., "[name](at)example(dot)com" → "name@example.com")
  - Phone: digits-only normalized to E.164-like format, default +1 if no country code (heuristic)
- Outputs per input file (unless `--dry-run`):
  - `decision_<basename>.json` and `decision_<basename>.csv` written to `--out-dir`
- Summary line printed to stdout:
  - `total=<n> kept=<n> dropped=<n> levels={C_SUITE:x, MGMT:y, ...} drop_reasons=[reason1:cnt, reason2:cnt, ...]`

**Exit Codes:**
- `0`: Success
- `1`: Configuration error (e.g., invalid `--min-level`)
- `2`: Input data error (malformed JSON or wrong shape)
- `3`: Runtime error (per-file processing failure)

**Examples:**
```bash
# Filter single file at default threshold (VP_PLUS), write to ./output/decision/
python scripts/decision_filter.py \
  --input output/contacts_people_20250911_*.json \
  --out-dir output/decision

# Strict threshold: keep only C-Suite
python scripts/decision_filter.py \
  --input output/contacts_people_*.json \
  --out-dir output/decision \
  --min-level C_SUITE

# Enrich Unknown titles via vCard for allowed hosts only (budget=10)
python scripts/decision_filter.py \
  --input output/contacts_people_lawfirms.json \
  --out-dir output/decision \
  --fetch-vcard --vcard-budget 10 --site-allow example.com lawfirm.com

# Dry-run over multiple inputs (no files written; summary only)
python scripts/decision_filter.py \
  --input output/contacts_people_a.json output/contacts_people_b.json \
  --min-level MGMT --dry-run
```

**Notes:**
- Inputs must exist; globs should be expanded by the shell beforehand
- vCard fetching uses simple stdlib HTTP (HEAD/GET) with size/time guards and will skip hosts not in `--site-allow` if provided
- Non-fatal errors during enrichment are recorded in `decision_reasons` and do not abort processing

---

### Schema Export: `egc.schemas.export`

Generate JSON Schema files from Pydantic models.

**Syntax:**
```bash
python scripts/export_json_schema.py
```

**No arguments required** - reads from `src/schemas.py`, outputs to `schemas/`.

**Output:**
```
schemas/
├── contact.schema.json        # Contact model schema
├── evidence.schema.json       # Evidence model schema
├── contact_export.schema.json # Export model schema
└── README.md                  # Usage documentation
```

**Exit Codes:**
- `0`: Schema generation successful
- `1`: Model import error

---

## Global Configuration

### Config File Precedence

1. Command-line `--config` argument
2. Environment variable: `EGC_CONFIG_FILE`
3. Default: `config/example.yaml`

### Environment Variables

**Required for secrets:**
```bash
export SMTP_PROBE_SENDER={{YOUR_EMAIL}}        # SMTP probe sender address
export PROXY_URL={{PROXY_URL}}                 # Optional proxy (format: http://host:port)
```

**Optional overrides:**
```bash
export EGC_LOG_LEVEL=DEBUG                     # Override logging level
export EGC_MAX_WORKERS=4                       # Override worker count
export EGC_HEADLESS_BUDGET=10000              # Override headless timeout (ms)
```

### Security Rules

- ✅ **All secrets via environment variables only**
- ✅ **Never hardcode credentials in commands**
- ✅ **Use non-paginated output**: `git --no-pager`, avoid interactive prompts
- ❌ **Never commit data files** (covered by .gitignore)

## Exit Codes Summary

| Code | Meaning |
|------|---------|
| 0    | Success |
| 1    | Configuration/validation error |
| 2    | Input data error |
| 3    | Processing/runtime error |
| 4    | Network/connectivity error |

## Examples

### Behavior Notes

- Candidate URL normalization: host lowercased, drop query/fragment; trim trailing slash except when running with `--exact-input-only` (where trailing slash is preserved). Discovery skips facet links (?/#)
- Per-domain limit: `--max-pages-per-domain` caps candidates after normalization
- Export-layer dedupe: removes duplicates by (company_norm, person_norm, contact_type, contact_value_norm); logs "🧹 Dedupe: kept X of Y"
- Reporting-only normalization: `source_url` is normalized in exported files; Evidence models remain unchanged

### Complete Workflow

```bash
# Step 1: Prepare configuration
cp config/example.yaml config/production.yaml
# Edit config/production.yaml as needed

# Step 2: Set environment variables
export SMTP_PROBE_SENDER={{YOUR_EMAIL}}

# Step 3: Prepare input
cat > input_urls.txt << EOF
https://atlassian.com
https://stripe.com
https://shopify.com
EOF

# Step 4: Run extraction
python -m egc.run \
  --input input_urls.txt \
  --config config/production.yaml \
  --out ./results \
  --verbose

# Step 5: Validate quality
python scripts/check_ecr.py --threshold 0.95 --input-dir ./results

# Step 6: SMTP validation
python scripts/smtp_probe.py --emails-file results/contacts.csv

# Step 7: Update schemas (if models changed)
python scripts/export_json_schema.py
```

### Testing Individual Sites

```bash
# Test selector on specific page
python scripts/debug_selectors.py \
  --url https://example.com/about \
  --selector "div.team-member" \
  --screenshot

# Check specific email
python scripts/debug_smtp.py --email ceo@example.com
```

### CI/CD Integration

```bash
#!/bin/bash
# ci-pipeline.sh

set -e  # Exit on error

# Validate configuration
python -m egc.run --dry-run --config config/ci.yaml --input test_urls.txt --out /tmp/test

# Run on test dataset
python -m egc.run --input test_urls.txt --config config/ci.yaml --out ./test_output

# Quality gates
python scripts/check_ecr.py --threshold 0.95 --input-dir ./test_output
if [ $? -ne 0 ]; then
  echo "ECR below threshold - failing build"
  exit 1
fi

echo "Pipeline passed"
```

## Configuration Reference

Key sections from `config/example.yaml` that affect CLI behavior:

```yaml
# Static-first rendering
renderer:
  mode: "static-first"
  static:
    burst_rps: 1.0
  headless:
    enabled: true
    max_pct_per_domain: 0.2
    burst_rps: 0.2

# Evidence requirements
evidence_pack:
  required_fields:
    - "source_url"
    - "selector_or_xpath"
    - "verbatim_quote"
    - "dom_node_screenshot"
    - "timestamp"
    - "parser_version" 
    - "content_hash"

# SMTP probe settings
smtp_probe:
  enabled: true
  free_providers_blocklist: true
  cache_ttl_days: 7

# Output configuration
exports:
  formats: ["csv", "json"]
  exclude_unverified: true
```

## Troubleshooting

### Common Issues

**"No matches found" with selectors:**
```bash
# Debug the selector
python scripts/debug_selectors.py --url <url> --selector <selector> --headless
# Try escalation to headless mode
```

**ECR below threshold:**
```bash
# Generate detailed report
python scripts/check_ecr.py --threshold 0.95 --report
# Review failed records and update selectors
```

**SMTP probe failures:**
```bash
# Check individual email
python scripts/debug_smtp.py --email problem@domain.com
# Verify DNS resolution and MX records
```

**Configuration errors:**
```bash
# Validate config syntax
python -c "import yaml; yaml.safe_load(open('config/example.yaml'))"
# Run dry-run to catch config issues
python -m egc.run --dry-run --config config/example.yaml --input test.txt --out /tmp
```

**Playwright "browser not found":**
```bash
# Install the required browser in your active virtualenv
python -m playwright install firefox
# (Chromium example)
# python -m playwright install chromium
```

### Log Analysis

Logs follow structured format with correlation IDs:

```bash
# Filter by component
grep "component=crawler" egc.log

# Filter by domain
grep "domain=example.com" egc.log  

# Find escalation events
grep "escalation=true" egc.log
```

### Performance Optimization

**High memory usage:**
- Reduce `max_workers` in config
- Lower `max_pct_per_domain` for headless

**Slow processing:**
- Increase `max_workers` if CPU available
- Check `budget_ms_per_url` setting
- Monitor escalation percentage per domain

**Rate limiting:**
- Adjust `burst_rps_static` and `burst_rps_headless`
- Implement `cooldown_on_403` backoff

---

## Related Files

- Configuration: `config/example.yaml`
- Schemas: `schemas/*.schema.json`
- Schema generator: `scripts/export_json_schema.py` 
- Data models: `src/schemas.py`
- Test data: `data/gold_datasets/`
