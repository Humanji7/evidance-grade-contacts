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
- `--verbose` / `-v`: Enable verbose logging
- `--dry-run`: Validate configuration without processing
- `--no-discovery`: Disable adaptive link discovery; use only include_paths expansion
- `--no-prefilter`: Disable pre-filter HTTP checks
- `--no-headless`: Disable Playwright escalation (static-only)
- `--static-timeout` SECONDS: Static fetch timeout (default 12.0)
- `--prefilter-timeout` SECONDS: Prefilter HEAD timeout (default 5.0)
- `--aggressive-static`: Enable aggressive static heuristics (name, email de-obfuscation, text phones with markers, VCF, table extractor first, role stop-list→Unknown)
- `--max-pages-per-domain` N: Limit number of candidate pages per domain after normalization (default 10)
- `--include-all`: Export UNVERIFIED as well (default: VERIFIED only)

**Example:**
```bash
python -m egc.run \
  --input input_urls.txt \
  --config config/example.yaml \
  --out ./output \
  --verbose
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

- Candidate URL normalization: host lowercased, drop query/fragment, trim trailing slash; discovery skips facet links (?/#)
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
