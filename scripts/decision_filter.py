#!/usr/bin/env python3
"""
Universal post-filter skeleton (no filtering logic yet).

- CLI:
  --input PATH [PATH ...]
  --out-dir PATH (default: out/)
  --min-level {C_SUITE,VP_PLUS,MGMT} (default: VP_PLUS)
  --dry-run

- Reads people JSON (list of objects), currently passes through records as-is
- Writes decision_{basename}.json and decision_{basename}.csv into out-dir
- Prints summary: total, kept, dropped (kept = total for now)

- Prepared structure: DecisionLevel enum and classify(record) stub

Constraints: stdlib only (argparse, json, csv, pathlib)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


class DecisionLevel(str, Enum):
    C_SUITE = "C_SUITE"
    VP_PLUS = "VP_PLUS"
    MGMT = "MGMT"
    NON_DM = "NON_DM"
    UNKNOWN = "UNKNOWN"


# Optional: define an ordering if/when filtering is implemented
_LEVEL_ORDER = {
    DecisionLevel.C_SUITE: 4,
    DecisionLevel.VP_PLUS: 3,
    DecisionLevel.MGMT: 2,
    DecisionLevel.NON_DM: 1,
    DecisionLevel.UNKNOWN: 0,
}


GENERIC_INBOX_RE = re.compile(r"^(info|contact|office|support|help|hr|jobs|careers|sales|billing|hello|team)@", re.I)

# Title patterns
_POS_C_SUITE = [
    re.compile(r"\bgeneral\s+counsel\b", re.I),
    re.compile(r"\bchief\s+[a-z]+\s+officer\b", re.I),
    re.compile(r"\bceo\b", re.I),
    re.compile(r"\bcfo\b", re.I),
    re.compile(r"\bcoo\b", re.I),
    re.compile(r"\bcto\b", re.I),
    re.compile(r"\bcmo\b", re.I),
    re.compile(r"\bcio\b", re.I),
    re.compile(r"\bpresident\b", re.I),
    re.compile(r"\bmanaging\s+director\b", re.I),
    re.compile(r"\bmanaging\s+partner\b", re.I),
    re.compile(r"\bexecutive\s+director\b", re.I),
    re.compile(r"\bco-?chair\b", re.I),
    re.compile(r"\bgroup\s+chair\b", re.I),
    re.compile(r"\bchair\b", re.I),
]

_POS_VP_PLUS = [
    re.compile(r"\bshareholder\b", re.I),
    re.compile(r"\bprincipal\b", re.I),
    re.compile(r"\bpartner\b", re.I),
    re.compile(r"\bsenior\s+director\b", re.I),
    re.compile(r"\bhead\s+of\b", re.I),
    re.compile(r"\bvice\s+president\b", re.I),
    re.compile(r"\bsvp\b", re.I),
    re.compile(r"\bevp\b", re.I),
    re.compile(r"\bvp\b", re.I),
]

_POS_MGMT = [
    re.compile(r"\bdirector\b", re.I),
    re.compile(r"\blead\b", re.I),
    re.compile(r"\bmanager\b", re.I),
]

_NEG = re.compile(
    r"\b(of\s+counsel|counsel|associate|assistant|junior|coordinator|specialist|analyst|intern|trainee|staff|support|paralegal)\b",
    re.I,
)

_STRUCT_HINTS = re.compile(r"/(leadership|executive|management|board|partners|shareholders|principals)(/|$)", re.I)


def _uplift(level: DecisionLevel) -> DecisionLevel:
    order = _LEVEL_ORDER[level]
    for k, v in _LEVEL_ORDER.items():
        if v == min(order + 1, _LEVEL_ORDER[DecisionLevel.C_SUITE]):
            return k
    return level


def _extract_title(record: Dict[str, Any]) -> str:
    for key in ("role_title", "title", "position", "role"):
        v = record.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def _find_source_urls(record: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    for k, v in record.items():
        if isinstance(k, str) and k.startswith("source_url") and isinstance(v, str):
            urls.append(v)
    ev = record.get("evidence")
    if isinstance(ev, dict):
        su = ev.get("source_url")
        if isinstance(su, str):
            urls.append(su)
    return urls


def normalize_email(s: str) -> str:
    if not isinstance(s, str):
        return s
    x = s.strip()
    # Replace (at)/[at]/{at} with @
    x = re.sub(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", "@", x, flags=re.I)
    # Replace (dot)/[dot]/{dot} with .
    x = re.sub(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", ".", x, flags=re.I)
    # Remove any remaining brackets
    x = re.sub(r"[\[\]\(\)\{\}]", "", x)
    # Remove spaces around @ and .
    x = re.sub(r"\s+@\s+", "@", x)
    x = re.sub(r"\s*\.\s*", ".", x)
    x = x.replace(" ", "")
    x = x.lower()
    return x


def normalize_phone(s: str) -> str:
    if not isinstance(s, str):
        return s
    raw = s.strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    if raw.startswith("+"):
        return "+" + digits
    return "+1" + digits


def classify(record: Dict[str, Any]) -> Tuple[DecisionLevel, List[str]]:
    """
    Decision-maker classifier. Returns (DecisionLevel, reasons)
    reasons examples: title:president, neg:associate, struct:leadership, email:generic
    """
    reasons: List[str] = []

    # Email signal: generic inbox
    email = record.get("email")
    if isinstance(email, str):
        em = normalize_email(email)
        if GENERIC_INBOX_RE.match(em):
            reasons.append("email:generic")

    title = _extract_title(record)
    level: DecisionLevel = DecisionLevel.UNKNOWN

    # Positive: C-SUITE
    for rx in _POS_C_SUITE:
        if rx.search(title):
            level = DecisionLevel.C_SUITE
            reasons.append(f"title:{rx.pattern}")
            break

    if level is DecisionLevel.UNKNOWN:
        # Negative guard (special-case: general counsel already handled)
        if _NEG.search(title) and not re.search(r"\bgeneral\s+counsel\b", title, flags=re.I):
            level = DecisionLevel.NON_DM
            m = _NEG.search(title)
            if m:
                reasons.append(f"neg:{m.group(1).lower()}")
        else:
            # VP_PLUS
            for rx in _POS_VP_PLUS:
                if rx.search(title):
                    level = DecisionLevel.VP_PLUS
                    reasons.append(f"title:{rx.pattern}")
                    break
            if level is DecisionLevel.UNKNOWN:
                # MGMT
                for rx in _POS_MGMT:
                    if rx.search(title):
                        level = DecisionLevel.MGMT
                        reasons.append(f"title:{rx.pattern}")
                        break

    # Structural hints uplift for UNKNOWN/MGMT
    urls = _find_source_urls(record)
    hinted = any(_STRUCT_HINTS.search(urlparse(u).path or "") for u in urls)
    if hinted and level in (DecisionLevel.UNKNOWN, DecisionLevel.MGMT):
        level = _uplift(level)
        reasons.append("struct:leadership")

    return level, reasons


def load_people_json(path: Path) -> List[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON from {path}: {e}", file=sys.stderr)
        raise SystemExit(2)
    if not isinstance(data, list):
        print(f"Input file must be a JSON list of objects: {path}", file=sys.stderr)
        raise SystemExit(2)
    # Best effort validation: ensure elements are dicts
    for i, rec in enumerate(data):
        if not isinstance(rec, dict):
            print(f"Record #{i} in {path} is not an object; got {type(rec).__name__}", file=sys.stderr)
            raise SystemExit(2)
    return data


def write_json(path: Path, records: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def _collect_fieldnames(records: Iterable[Dict[str, Any]]) -> List[str]:
    keys = set()
    for rec in records:
        for k in rec.keys():
            if isinstance(k, str):
                keys.add(k)
            else:
                keys.add(str(k))
    return sorted(keys)


def write_csv(path: Path, records: List[Dict[str, Any]]) -> None:
    if not records:
        # Create empty file
        path.touch()
        return
    fieldnames = _collect_fieldnames(records)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            writer.writerow({k: rec.get(k, "") for k in fieldnames})


def _http_head(url: str, timeout_s: float) -> Tuple[int, Dict[str, str]]:
    req = Request(url, method="HEAD")
    with urlopen(req, timeout=timeout_s) as resp:
        status = getattr(resp, "status", None) or resp.getcode()
        headers = {k.lower(): v for k, v in resp.headers.items()}
        return int(status), headers


def _http_get(url: str, timeout_s: float, max_bytes: int) -> Tuple[int, bytes]:
    req = Request(url, method="GET")
    with urlopen(req, timeout=timeout_s) as resp:
        status = getattr(resp, "status", None) or resp.getcode()
        # Read up to max_bytes + 1 to detect overflow
        data = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("vcard too large")
        return int(status), data


def process_records(
    records: List[Dict[str, Any]],
    min_level: DecisionLevel,
    fetch_vcard: bool,
    vcard_budget: int,
    timeout_s: float,
    max_vcard_bytes: int,
    site_allow: List[str] | None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int], Dict[str, int]]:
    kept_records: List[Dict[str, Any]] = []
    counts_by_level: Dict[str, int] = {lvl.value: 0 for lvl in DecisionLevel}
    drop_reasons: Dict[str, int] = {}

    allow_hosts = set(h.lower() for h in (site_allow or []))
    budget_left = vcard_budget

    for rec in records:
        rec_out = dict(rec)

        # Normalize email/phone in-place if present
        if isinstance(rec_out.get("email"), str):
            rec_out["email"] = normalize_email(rec_out["email"])  # type: ignore[index]
        if isinstance(rec_out.get("phone"), str):
            rec_out["phone"] = normalize_phone(rec_out["phone"])  # type: ignore[index]

        # Optional vCard enrichment for Unknown titles
        try:
            if fetch_vcard and budget_left > 0:
                vcard_url = rec_out.get("vcard")
                role_title = rec_out.get("role_title")
                if isinstance(vcard_url, str) and vcard_url.lower().endswith(".vcf") and role_title == "Unknown":
                    host = urlparse(vcard_url).hostname or ""
                    if (not allow_hosts) or (host.lower() in allow_hosts):
                        try:
                            status, headers = _http_head(vcard_url, timeout_s)
                            if status == 200:
                                cl = headers.get("content-length")
                                size_ok = True
                                if cl is not None:
                                    try:
                                        size_ok = int(cl) <= max_vcard_bytes
                                    except ValueError:
                                        size_ok = True
                                if size_ok and budget_left > 0:
                                    status2, body = _http_get(vcard_url, timeout_s, max_vcard_bytes)
                                    if status2 == 200:
                                        text = body.decode("utf-8", errors="ignore")
                                        title_val = None
                                        for line in text.splitlines():
                                            if line.upper().startswith("TITLE:") or line.upper().startswith("ROLE:"):
                                                title_val = line.split(":", 1)[1].strip()
                                                break
                                        if title_val is None:
                                            for line in text.splitlines():
                                                if line.upper().startswith("ORG:"):
                                                    title_val = line.split(":", 1)[1].strip()
                                                    break
                                        if title_val:
                                            rec_out["role_title"] = title_val
                                            budget_left -= 1
                        except Exception:
                            # Non-fatal
                            rec_out.setdefault("decision_reasons", [])
                            if isinstance(rec_out["decision_reasons"], list):
                                rec_out["decision_reasons"].append("vcard_fetch_error")
        except Exception:
            # Defensive: never fail the record due to enrichment logic
            rec_out.setdefault("decision_reasons", [])
            if isinstance(rec_out["decision_reasons"], list):
                rec_out["decision_reasons"].append("vcard_fetch_error")

        level, reasons = classify(rec_out)
        rec_out["decision_level"] = level.value
        # Merge any pre-added reasons
        prev_reasons = rec_out.get("decision_reasons")
        if isinstance(prev_reasons, list):
            reasons = list(prev_reasons) + reasons
        rec_out["decision_reasons"] = reasons

        counts_by_level[level.value] = counts_by_level.get(level.value, 0) + 1

        if _LEVEL_ORDER[level] >= _LEVEL_ORDER[min_level]:
            kept_records.append(rec_out)
        else:
            # Track drop reasons
            drop_reasons["below_min_level"] = drop_reasons.get("below_min_level", 0) + 1
            for r in reasons:
                drop_reasons[r] = drop_reasons.get(r, 0) + 1

    return kept_records, counts_by_level, drop_reasons


def process_file(input_path: Path, out_dir: Path, min_level: DecisionLevel, dry_run: bool,
                 fetch_vcard: bool = False, vcard_budget: int = 50, timeout_s: float = 2.5,
                 max_vcard_bytes: int = 65536, site_allow: List[str] | None = None) -> Tuple[int, int, int, Path, Path]:
    # Load
    records = load_people_json(input_path)

    kept_records, counts_by_level, drop_reasons = process_records(
        records=records,
        min_level=min_level,
        fetch_vcard=fetch_vcard,
        vcard_budget=vcard_budget,
        timeout_s=timeout_s,
        max_vcard_bytes=max_vcard_bytes,
        site_allow=site_allow,
    )

    total = len(records)
    kept = len(kept_records)
    dropped = total - kept

    basename = input_path.stem
    out_json = out_dir / f"decision_{basename}.json"
    out_csv = out_dir / f"decision_{basename}.csv"

    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        write_json(out_json, kept_records)
        write_csv(out_csv, kept_records)

    # Print summary
    levels_summary = "{" + ", ".join(f"{k}:{v}" for k, v in sorted(counts_by_level.items())) + "}"
    # Top 3 drop reasons
    top_reasons = sorted(drop_reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    top_reasons_str = ", ".join(f"{k}:{v}" for k, v in top_reasons)
    print(f"total={total} kept={kept} dropped={dropped} levels={levels_summary} drop_reasons=[{top_reasons_str}]")
    return total, kept, dropped, out_json, out_csv


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Universal post-filter (skeleton)")
    parser.add_argument(
        "--input",
        dest="inputs",
        nargs="+",
        required=True,
        type=Path,
        help="Input people JSON files (each is a list of objects)",
    )
    parser.add_argument(
        "--out-dir",
        dest="out_dir",
        type=Path,
        default=Path("out"),
        help="Output directory (default: out/)",
    )
    parser.add_argument(
        "--min-level",
        dest="min_level",
        choices=[lvl.value for lvl in (DecisionLevel.C_SUITE, DecisionLevel.VP_PLUS, DecisionLevel.MGMT)],
        default=DecisionLevel.VP_PLUS.value,
        help="Minimum decision-maker level (default: VP_PLUS)",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Only print summary; do not write outputs",
    )
    # Optional vCard enrichment flags
    parser.add_argument("--fetch-vcard", dest="fetch_vcard", action="store_true", help="Fetch .vcf to enrich Unknown titles")
    parser.add_argument("--vcard-budget", dest="vcard_budget", type=int, default=50, help="Max number of vCards to fetch (default 50)")
    parser.add_argument("--timeout-s", dest="timeout_s", type=float, default=2.5, help="HTTP timeout in seconds (default 2.5)")
    parser.add_argument(
        "--max-vcard-bytes",
        dest="max_vcard_bytes",
        type=int,
        default=65536,
        help="Maximum vCard size in bytes (default 65536)",
    )
    parser.add_argument(
        "--site-allow",
        dest="site_allow",
        nargs="*",
        help="If provided, only fetch vCards for these hostnames",
    )
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)

    try:
        min_level = DecisionLevel(args.min_level)
    except ValueError:
        print(f"Invalid --min-level: {args.min_level}", file=sys.stderr)
        return 1

    exit_code = 0
    for input_path in args.inputs:
        try:
            process_file(
                input_path=input_path,
                out_dir=args.out_dir,
                min_level=min_level,
                dry_run=args.dry_run,
                fetch_vcard=args.fetch_vcard,
                vcard_budget=args.vcard_budget,
                timeout_s=args.timeout_s,
                max_vcard_bytes=args.max_vcard_bytes,
                site_allow=args.site_allow,
            )
        except SystemExit as e:
            # load_people_json may raise SystemExit with code 2
            exit_code = max(exit_code, int(e.code) if isinstance(e.code, int) else 1)
        except Exception as e:  # noqa: BLE001 - stdlib only, be robust in CLI
            print(f"Error processing {input_path}: {e}", file=sys.stderr)
            exit_code = max(exit_code, 3)
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
