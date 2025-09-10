# Repository Guidelines

This guide helps contributors work effectively in Evidence‑Grade Contacts (EGC).

## Project Structure & Module Organization
- `src/` – core library (pipeline, evidence, fetchers, exporters). Example: `src/pipeline/fetchers/static.py`.
- `egc/` – CLI entry (`python -m egc.run`).
- `tests/` – unit and integration tests (e.g., `tests/unit/test_extractors.py`).
- `scripts/` – utilities (e.g., `scripts/smtp_probe.py`).
- `config/` – configuration templates (`config/example.yaml`).
- `data/`, `out/`, `evidence/` – artifacts and outputs (gitignored).

## Build, Test, and Development Commands
- Setup
  - `python -m venv .venv && source .venv/bin/activate`
  - `pip install -r requirements.txt`
  - `python -m playwright install` (for headless tests)
  - `pre-commit install`
- Run pipeline (local)
  - `python -m egc.run --input input_urls.txt --config config/example.yaml --out ./out`
- Tests
  - Unit: `python -m pytest tests/unit/ -v`
  - Coverage: `python -m pytest --cov=src tests/unit/ -v`
  - Integration: `python -m pytest tests/integration/ -v` (add `--browser chromium` if needed)

## Coding Style & Naming Conventions
- Formatting: Black (line length 88) + isort (profile=black).
- Linting: flake8 (ignore E203/W503), mypy (type hints required on new/changed code).
- Python naming: `snake_case` for functions/vars, `PascalCase` for classes, modules under `src/` use short, descriptive names.
- Keep functions small and testable; avoid network calls in unit tests.

## Testing Guidelines
- Framework: pytest (+ pytest-playwright for browser paths).
- Place unit tests in `tests/unit/` named `test_*.py`; prefer offline fixtures for determinism.
- Validate evidence completeness where applicable; see `docs/testing.md` for structure and commands.
- Aim to cover new/modified code; add regression tests when touching extraction/evidence logic.

## Commit & Pull Request Guidelines
- Commits: prefer Conventional Commits (e.g., `feat(extractor): …`, `fix(models): …`, `docs: …`). Keep subjects imperative and ≤72 chars; include rationale in the body.
- Before opening a PR: run `pre-commit run -a` and the test suite. Describe scope, linked issues, and impacts (e.g., extraction accuracy/ECR, performance). Include sample CLI output paths (CSV/JSON) or screenshots if UI-like artifacts.
- Update README/docs when changing behavior, config, or CLI flags.

## Security & Configuration Tips
- Respect robots.txt and ToS; scope targets via `config/example.yaml` (`scope.include_paths`).
- Do not commit datasets, evidence, screenshots, or secrets (see `.gitignore`).
- SMTP probe: defaults skip free domains; override via `EGC_SKIP_FREE=0`. Timeouts via `SMTP_TIMEOUT`. MX/email caching lives in `.egc_cache.db`.
- Keep headless usage minimal; quotas in config (`renderer.headless.max_pct_per_domain`).

