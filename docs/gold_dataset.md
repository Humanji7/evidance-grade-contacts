# Gold Dataset

High‑quality gold dataset for testing and regression validation.

## Summary
- 20 verified records across 3 law firms (Seyfarth Shaw, Jackson Lewis, Frost Brown Todd)
- 309 total contacts (77 emails, 232 phones)
- Evidence Completeness Rate: 100%
- Difficulty mix: static pages, Cloudflare bypass, bulk leadership pages

## Validate
```bash
python3 scripts/validate_gold_dataset.py
```

## Extract New Gold Records
```bash
python3 scripts/gold_extractor.py "https://example.com/people/john-doe"
```

## Notes
- Exports are VERIFIED‑only by default.
- Evidence Package fields must be complete; otherwise records become UNVERIFIED and are excluded.
- See docs/operations.md for budgets and compliance.

