# Input/Output Formats - Evidence-Grade Contacts PoC

This document specifies data formats for the EGC PoC pipeline, from input URLs to final exports with evidence packages.

## Input Formats

### URLs File (`input_urls.txt`)
Simple text file with base company URLs, one per line.

**Format:**
```
https://example.com
https://company.io
https://startup.co
```

**Rules:**
- HTTP/HTTPS URLs only
- Base domain URLs (system will append paths from scope configuration)
- No trailing slashes
- Comments with `#` ignored

**Example:**
```
# Tech companies for testing
https://atlassian.com
https://stripe.com
https://shopify.com

# Optional: specific paths override scope
https://example.com/about
```

## Output Formats

### 1. Contacts JSON (`contacts.json`)

**Structure:** Full Contact records with nested Evidence objects.

```json
[
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
      "content_hash": "a1b2c3d4e5f67890123456789012345678901234567890123456789012345678"
    },
    "captured_at": "2025-09-04T10:15:05Z",
    "verification_status": "VERIFIED"
  }
]
```

**Field Specifications:**
- `contact_type`: enum ("email" | "phone" | "link")
- `verification_status`: enum ("VERIFIED" | "UNVERIFIED")
- `timestamp`, `captured_at`: ISO 8601 format
- `content_hash`: SHA-256 (64 hex characters)
- `parser_version`: semantic versioning (e.g., "0.1.0-poc")

### 2. Contacts CSV (`contacts.csv`)

**Structure:** Flattened format with evidence fields as columns.

```csv
company,person_name,role_title,contact_type,contact_value,captured_at,verification_status,source_url,selector_or_xpath,verbatim_quote,dom_node_screenshot,timestamp,parser_version,content_hash
Example Inc.,Jane Doe,Head of Marketing,email,jane.doe@example.com,2025-09-04T10:15:05Z,VERIFIED,https://example.com/company/leadership,"div.card:has(h3:contains('Jane Doe'))","Jane Doe — Head of Marketing",evidence/example_jane_doe.png,2025-09-04T10:15:00Z,0.1.0-poc,a1b2c3d4e5f67890123456789012345678901234567890123456789012345678
```

**CSV Rules:**
- UTF-8 encoding
- Comma-separated, quoted strings
- UNVERIFIED records excluded (per PoC policy)
- Header row always included

### 3. Evidence Directory (`evidence/`)

**Structure:**
```
evidence/
├── screenshot_001.png    # DOM node screenshots
├── screenshot_002.png
└── screenshot_003.png
```

**Screenshot Naming:**
- Format: `screenshot_{sequential_number}.png`
- Referenced from `dom_node_screenshot` field
- PNG format, minimal resolution sufficient for verification

## Data Validation Rules

### Contact Fields
- **company**: non-empty string, trimmed
- **person_name**: non-empty string, trimmed  
- **role_title**: non-empty string
- **contact_value**: validated by contact_type
  - email: basic format validation (`user@domain.tld`)
  - phone: digits only after removing separators, 7-15 characters
  - link: must start with `http://` or `https://`

### Evidence Package Completeness
All 7 fields required for VERIFIED status:
1. `source_url` (valid HTTP/HTTPS URL)
2. `selector_or_xpath` (non-empty selector)
3. `verbatim_quote` (exact text from DOM)
4. `dom_node_screenshot` (valid file reference)
5. `timestamp` (ISO 8601)
6. `parser_version` (semantic versioning)
7. `content_hash` (64-char SHA-256)

**Missing any field → UNVERIFIED → excluded from exports**

## Export Configuration

Controlled by `config/example.yaml`:

```yaml
exports:
  out_dir: "./out"
  formats: ["csv", "json"]       # Available: csv, json
  exclude_unverified: true       # PoC policy: only VERIFIED records
```

## Error Handling

### Invalid Input
- Malformed URLs → logged and skipped
- Empty lines → ignored
- Invalid file encoding → UTF-8 fallback attempted

### Incomplete Records
- Records with incomplete evidence → marked UNVERIFIED
- UNVERIFIED records → logged but excluded from final exports
- Evidence artifacts → preserved for debugging

### File System
- Output directory created if missing
- Existing files overwritten (no incremental mode in PoC)
- Evidence directory cleaned on each run

## Integration Examples

### Reading with Python
```python
import json
import csv
from src.schemas import Contact, ContactExport

# Read JSON
with open('output/contacts.json') as f:
    contacts_data = json.load(f)
    contacts = [Contact(**record) for record in contacts_data]

# Read CSV
with open('output/contacts.csv') as f:
    reader = csv.DictReader(f)
    export_records = [ContactExport(**row) for row in reader]
```

### Reading with External Tools
```bash
# Count VERIFIED contacts
jq 'length' output/contacts.json

# Extract emails only
jq -r '.[] | select(.contact_type=="email") | .contact_value' output/contacts.json

# CSV analysis
csvstat output/contacts.csv --count
```

## Quality Metrics Integration

The I/O formats support quality validation:

- **Evidence Completeness Rate (ECR)**: `VERIFIED records / total records`
- **Contact Type Distribution**: count by `contact_type` field  
- **Source Coverage**: unique `source_url` count
- **Evidence Integrity**: validate all `content_hash` values

## Related Files

- Data models: `src/schemas.py`
- JSON Schemas: `schemas/*.schema.json`
- CLI usage: `docs/cli.md`
- Configuration: `config/example.yaml`
