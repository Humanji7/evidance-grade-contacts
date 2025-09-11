# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [0.2.0] - 2025-09-11
### Added
- GitHub‑optimized README with Quickstart, Evidence concept, and links to docs.
- New deep‑dive docs: docs/architecture.md, docs/operations.md, docs/gold_dataset.md.
- This CHANGELOG file.

### Changed
- Moved internal status sections (implementation details, budgets, ops notes, gold dataset stats) from README into dedicated docs.

## [0.1.0] - 2025-09-04
### Added
- Initial PoC with static‑first pipeline and guarded Playwright escalation.
- Evidence Package system (7 required fields) with node screenshots and content hashing.
- Contact extraction (names, titles, emails, phones) and CSV/JSON exports (VERIFIED‑only by default).
- Pydantic models and JSON Schema export.
- Basic test suite (unit + integration) and gold dataset (20 records, 309 contacts).

## Recent Enhancements (from project notes)
- Aggressive Static Mode: relaxed name validation, email de‑obfuscation, phone extraction with markers, vCard detection, table‑first extractor, normalized role stop‑list.
- URL normalization & candidate limiting: host lowercasing, drop query/fragment, trim slash; per‑domain max pages; discovery facet filters.
- Export‑layer dedupe with normalized source_url and tie‑break rules; global dedupe by normalized keys.
- Decision Filter CLI: classification by decision level (C_SUITE > VP_PLUS > MGMT > NON_DM > UNKNOWN), normalization, optional vCard enrichment with budgets.
- Smart mode defaults: on‑demand discovery, guarded headless with per‑domain and global caps, people‑level exports.
- Escalation triggers: SPA MIME, tiny pages with 0 hits, anti‑bot markers, JS markers, cards‑present‑no‑contacts, target URL with 0 contacts.

