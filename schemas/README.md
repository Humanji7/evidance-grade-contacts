# JSON Schemas for EGC PoC

This directory contains JSON Schema artifacts exported from Pydantic models in src/schemas.py.

- Draft: 2020-12
- Purpose: external validation, API contracts, interoperability
- Sources: Contact, Evidence (Mini Evidence Package), ContactExport

## Files
- contact.schema.json — materialized contact with nested evidence
- evidence.schema.json — 7-field Mini Evidence Package
- contact_export.schema.json — flattened export-friendly model

## Usage

Validate a JSON file using ajv (Node.js):

```bash
# Install once
npm install -g ajv-cli

# Validate example payload against Contact schema
ajv validate -s contact.schema.json -d example.json --spec=draft2020
```

Validate using Python (jsonschema):

```python
from jsonschema import validate
import json

schema = json.load(open('schemas/contact.schema.json'))
payload = json.load(open('example.json'))
validate(instance=payload, schema=schema)
```

## Notes
- JSON Schema reflects static structure. Some runtime validations (e.g. phone format depending on contact_type) are enforced by application logic and may not be fully expressed in JSON Schema.
- Evidence Completeness policy (7 required fields) is represented structurally in evidence.schema.json but ultimate VERIFIED/UNVERIFIED status is determined by the application.

