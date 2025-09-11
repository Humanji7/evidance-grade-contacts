# Operations & Budgets

This document covers runtime guardrails, budgets/quotas, logging, and compliance knobs.

## Modes
- Smart mode (default): static++ first; on‑demand discovery; guarded headless; write people‑level exports.
- Aggressive Static (--aggressive-static): relaxed name checks; email de‑obfuscation; phone extraction with markers; vCard detection; table‑first extractor; normalized role stop‑list.

## Budgets & Quotas
- Per‑domain headless cap: ≤ 2 pages per run (Smart mode)
- Global headless cap: ≤ 10 pages per run (Smart mode)
- max_headless_pct_per_domain ≤ 0.2 (recommended)
- burst_rps_static = 1.0; burst_rps_headless = 0.2
- budget_ms_per_url = 12000
- cooldown_on_403 backoff: 5m → 15m → 60m

## Escalation reasons (examples)
- SPA/MIME redirect (MIME ≠ text/html)
- Tiny page with 0 selector hits (< 5 KiB)
- Anti‑bot/challenge markers (e.g., Cloudflare)
- JS markers: data‑cfemail, cf_email, javascript:.*mailto, data‑email=, data‑phone=, data‑reactroot, ng‑app
- Cards present, no contacts
- Target URL yielded 0 contacts after static extraction

## Observability
- Human‑readable logs: “Smart mode: discovery=auto, headless=guarded, budgets: domain=2, global=10”, “via playwright: reasons=[…]”, “headless budget exhausted”.
- Structured logs: set `EGC_OPS_JSON=1` to emit JSON lines with timings, method (static|playwright), contact counts, headless reasons.

## Compliance & Policies
- robots.txt and ToS are enforced; red‑flag sources (LinkedIn, X/Twitter, Meta) are out of scope.
- Data minimization: business contacts only.
- SMTP probe: non‑sending; cache MX/RCPT results for 7 days by default; free domains skipped unless overridden.
- Right to erasure: manual processing; see SECURITY.md.

## Configuration
Use `config/example.yaml` as the authority. Key sections:
- renderer: mode, headless.enabled, headless.max_pct_per_domain, burst_rps
- timeouts: budget_ms_per_url
- backoff: cooldown_on_403
- evidence_pack.required_fields
- scope.include_paths
- smtp_probe: enabled, free_providers_blocklist, cache_ttl_days
- compliance: enforce_robots_and_tos, data_minimization

## Tips
- Prefer static‑first; headless is expensive.
- Keep discovery limited; prioritize leadership/team/contact paths.
- Use people‑level exports for decision workflows; run Decision Filter to keep VP+ or C‑Suite only.

