from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from typing import List

from datetime import datetime
from src.schemas import Contact

DDL_STATEMENTS = [
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    """
    CREATE TABLE IF NOT EXISTS contacts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      company TEXT NOT NULL,
      person_name TEXT NOT NULL,
      role_title TEXT NOT NULL,
      contact_type TEXT NOT NULL CHECK (contact_type IN ('email','phone','link')),
      contact_value TEXT NOT NULL,
      verification_status TEXT NOT NULL CHECK (verification_status IN ('VERIFIED','UNVERIFIED')),
      captured_at TEXT NOT NULL,
      evidence TEXT NOT NULL,
      norm_key TEXT NOT NULL
    )
    """.strip(),
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_contacts_identity
      ON contacts (norm_key, contact_type, contact_value)
    """.strip(),
    """
    CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts (lower(company))
    """.strip(),
    """
    CREATE INDEX IF NOT EXISTS idx_contacts_status_time ON contacts (verification_status, captured_at DESC)
    """.strip(),
]

UPSERT_SQL = (
    """
    INSERT INTO contacts (
      company, person_name, role_title, contact_type, contact_value,
      verification_status, captured_at, evidence, norm_key
    ) VALUES (
      :company, :person_name, :role_title, :contact_type, :contact_value,
      :verification_status, :captured_at, :evidence, :norm_key
    )
    ON CONFLICT(norm_key, contact_type, contact_value)
    DO UPDATE SET
      role_title = excluded.role_title,
      verification_status = excluded.verification_status,
      captured_at = excluded.captured_at,
      evidence = excluded.evidence
    """
).strip()


def make_norm_key(person_name: str, company: str) -> str:
    name_norm = person_name.strip().lower()
    comp_norm = re.sub(r"\s+", "", company.strip().lower())
    base = name_norm + "@" + comp_norm
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def ensure_schema(conn: sqlite3.Connection) -> None:
    for stmt in DDL_STATEMENTS:
        conn.execute(stmt)


def export_contacts_to_sqlite(db_path: str, contacts: List[Contact]) -> int:
    """Write contacts into a SQLite database with upsert semantics.

    Args:
        db_path: Path to the SQLite database file (will be created if absent)
        contacts: List of Contact models

    Returns:
        Number of rows processed (attempted upserts)
    """
    if not contacts:
        return 0

    conn = sqlite3.connect(db_path)
    try:
        ensure_schema(conn)

        rows = []
        for c in contacts:
            ev = {
                "source_url": c.evidence.source_url,
                "selector_or_xpath": c.evidence.selector_or_xpath,
                "verbatim_quote": c.evidence.verbatim_quote,
                "dom_node_screenshot": c.evidence.dom_node_screenshot,
                "timestamp": c.evidence.timestamp.isoformat(),
                "parser_version": c.evidence.parser_version,
                "content_hash": c.evidence.content_hash,
            }
            rows.append({
                "company": c.company,
                "person_name": c.person_name,
                "role_title": c.role_title,
                "contact_type": c.contact_type.value,
                "contact_value": c.contact_value,
                "verification_status": c.verification_status.value,
                "captured_at": c.captured_at.isoformat(),
                "evidence": json.dumps(ev, ensure_ascii=False),
                "norm_key": make_norm_key(c.person_name, c.company),
            })

        with conn:  # transactional batch
            conn.executemany(UPSERT_SQL, rows)
        return len(rows)
    finally:
        conn.close()

