#!/usr/bin/env python3
"""
Export JSON Schema files from Pydantic models for EGC PoC.
- Draft: 2020-12
- Sources: src/schemas.py (Contact, Evidence, ContactExport)
- Outputs: schemas/*.schema.json
"""
import json
import os
from datetime import datetime
from pathlib import Path

# Ensure project root execution
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCHEMAS_DIR = ROOT / "schemas"
SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)

import sys
sys.path.insert(0, str(ROOT))

from src.schemas import Contact, Evidence, ContactExport  # type: ignore

SCHEMA_VERSION = "https://json-schema.org/draft/2020-12/schema"


from typing import Optional, Dict, Any

def add_common_headers(schema: Dict[str, Any], title: str, description: str, example: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    schema.setdefault("$schema", SCHEMA_VERSION)
    schema.setdefault("title", title)
    schema.setdefault("description", description)
    if example is not None:
        schema.setdefault("examples", [example])
    return schema


def contact_example() -> dict:
    return {
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
            "content_hash": "a1b2c3d4e5f67890123456789012345678901234567890123456789012345678",
        },
        "captured_at": "2025-09-04T10:15:05Z",
        "verification_status": "VERIFIED",
    }


def evidence_example() -> dict:
    ex = contact_example()["evidence"].copy()
    return ex


def contact_export_example() -> dict:
    c = contact_example()
    e = c.pop("evidence")
    c_export = {
        **c,
        "source_url": e["source_url"],
        "selector_or_xpath": e["selector_or_xpath"],
        "verbatim_quote": e["verbatim_quote"],
        "dom_node_screenshot": e["dom_node_screenshot"],
        "timestamp": e["timestamp"],
        "parser_version": e["parser_version"],
        "content_hash": e["content_hash"],
    }
    return c_export


def save_schema(model, path: Path, title: str, description: str, example: dict):
    schema = model.model_json_schema()  # pydantic v2
    schema = add_common_headers(schema, title, description, example)
    path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {path.relative_to(ROOT)}")


def main():
    save_schema(
        Evidence,
        SCHEMAS_DIR / "evidence.schema.json",
        "Evidence (Mini Evidence Package)",
        "Seven required fields backing each verified record.",
        evidence_example(),
    )
    save_schema(
        Contact,
        SCHEMAS_DIR / "contact.schema.json",
        "Contact",
        "Materialized contact record with nested Evidence.",
        contact_example(),
    )
    save_schema(
        ContactExport,
        SCHEMAS_DIR / "contact_export.schema.json",
        "ContactExport",
        "Flattened representation of Contact for CSV/JSON exports.",
        contact_export_example(),
    )


if __name__ == "__main__":
    main()

