"""
Minimal SMTP probe utility (PoC).

This module exposes small, easily testable functions used by unit tests:
- validate_email(email: str) -> bool
- parse_domain(email: str) -> str
- should_skip_domain(domain: str) -> bool
- probe_rcpt(mx_host: str, email: str, timeout: int = 10) -> dict

The probe performs a lightweight SMTP dialogue without sending data.
"""
from __future__ import annotations

import re
import time
import smtplib
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List, Tuple

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# A small set is sufficient for PoC; can be extended later
FREE_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "yahoo.com",
    "yandex.ru",
    "mail.ru",
}


def validate_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email or ""))


def parse_domain(email: str) -> str:
    if "@" not in email:
        raise ValueError("Invalid email: missing @")
    local, domain = email.rsplit("@", 1)
    if not local or not domain:
        raise ValueError("Invalid email format")
    return domain.lower()


def should_skip_domain(domain: str) -> bool:
    return domain.lower() in FREE_DOMAINS


@dataclass
class ProbeResult:
    email: str
    domain: str
    mx_used: Optional[str]
    accepts_rcpt: bool
    smtp_code: Optional[int]
    smtp_message: Optional[str]
    error_category: Optional[str]  # ok|temp|perm|network|policy|None
    rtt_ms: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _classify(code: Optional[int], exc: Optional[BaseException] = None) -> str:
    if code is not None:
        if 200 <= code < 300:
            return "ok"
        if 400 <= code < 500:
            return "temp"
        if 500 <= code < 600:
            return "perm"
    if exc is not None:
        return "network"
    return "unknown"


def resolve_mx(domain: str) -> List[str]:
    """Resolve MX records for a domain and return a list of hosts ordered by preference.
    Tries dnspython if available; otherwise returns an empty list (PoC fallback).
    """
    # Try dnspython if present
    try:
        import dns.resolver  # type: ignore
    except Exception:
        return []

    try:
        answers = dns.resolver.resolve(domain, 'MX')  # type: ignore[attr-defined]
        pairs: List[Tuple[int, str]] = []
        for rdata in answers:
            # rdata.preference, rdata.exchange.to_text()
            try:
                pref = int(getattr(rdata, 'preference', 10))
                exch = getattr(rdata, 'exchange')
                host = exch.to_text(omit_final_dot=True) if hasattr(exch, 'to_text') else str(exch).rstrip('.')
            except Exception:
                continue
            pairs.append((pref, host))
        pairs.sort(key=lambda x: x[0])
        return [h for _, h in pairs]
    except Exception:
        return []


def probe_rcpt(mx_host: str, email: str, timeout: int = 10) -> Dict[str, Any]:
    """Probe an SMTP MX for RCPT acceptance without sending DATA.

    Returns a dict compatible with tests with keys:
    - accepts_rcpt: bool
    - smtp_code: int|None
    - error_category: str
    - mx_used: str|None
    - rtt_ms: int|None
    """
    domain = parse_domain(email)

    start_ts = time.time()
    smtp_code: Optional[int] = None
    smtp_msg: Optional[str] = None
    accepts = False
    category: Optional[str] = None

    try:
        with smtplib.SMTP(mx_host, 25, timeout=timeout) as smtp:
            # Greet
            code, _ = smtp.ehlo()
            # STARTTLS if available
            try:
                if hasattr(smtp, "has_extn") and smtp.has_extn("starttls"):
                    smtp.starttls()
                    smtp.ehlo()
            except Exception:
                # If STARTTLS fails, continue without it in PoC
                pass

            # Envelope without DATA
            smtp.mail("<probe@%s>" % domain)
            smtp_code, msg = smtp.rcpt(f"<{email}>")
            smtp_msg = msg.decode("utf-8", errors="ignore") if isinstance(msg, (bytes, bytearray)) else str(msg)
            accepts = 200 <= (smtp_code or 0) < 300
            category = _classify(smtp_code)
    except Exception as e:  # network errors/timeouts
        category = _classify(None, e)

    rtt_ms = int((time.time() - start_ts) * 1000)
    result = ProbeResult(
        email=email,
        domain=domain,
        mx_used=mx_host,
        accepts_rcpt=accepts,
        smtp_code=smtp_code,
        smtp_message=smtp_msg,
        error_category=category,
        rtt_ms=rtt_ms,
    )
    return result.to_dict()


def _env_bool(name: str, default: bool) -> bool:
    import os
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip() in ("1", "true", "TRUE", "yes", "on")


def _parse_args(argv=None):
    import argparse
    import os

    # Env defaults
    env_timeout = int(os.getenv("SMTP_TIMEOUT", "10"))
    env_ttl = int(os.getenv("SMTP_MX_TTL_DAYS", "7"))
    env_skip_free = _env_bool("EGC_SKIP_FREE", True)

    ap = argparse.ArgumentParser(description="SMTP RCPT probe (PoC CLI)")
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument("--email", help="single email to probe")
    g.add_argument("--emails-file", help="path to file with emails (txt/csv)")

    ap.add_argument("--mx", help="explicit MX host (temporary until MX lookup block)")
    ap.add_argument("--out", help="output file (.json or .csv); default stdout JSON")
    ap.add_argument("--timeout", type=int, default=env_timeout, help=f"timeout seconds (env SMTP_TIMEOUT, default {env_timeout})")
    ap.add_argument("--mx-ttl-days", type=int, default=env_ttl, help=f"Cache TTL in days for MX and email results (env SMTP_MX_TTL_DAYS, default {env_ttl})")
    ap.add_argument("--max-per-domain", type=int, default=5, help="max RCPT probes per domain in a single run")
    ap.add_argument("--skip-free", dest="skip_free", action="store_true", default=env_skip_free, help="skip free email domains (env EGC_SKIP_FREE=1)")
    ap.add_argument("--no-skip-free", dest="skip_free", action="store_false", help="do not skip free domains")
    ap.add_argument("--verbose", action="store_true")
    return ap.parse_args(argv)


def _read_emails(path: str | None, single: str | None) -> list[str]:
    emails: list[str] = []
    if single:
        emails.append(single)
    if path:
        import csv
        from pathlib import Path
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(str(p))
        text = p.read_text(errors="ignore")
        # Try CSV first
        try:
            reader = csv.reader(text.splitlines())
            for row in reader:
                for cell in row:
                    if "@" in cell:
                        emails.extend([e.strip() for e in cell.replace(";", ",").split(",") if "@" in e])
        except Exception:
            pass
        # Fallback split by whitespace
        for token in text.replace(",", " ").split():
            if "@" in token:
                emails.append(token.strip())
    # Dedup & keep order
    seen = set()
    unique = []
    for e in emails:
        if e not in seen:
            seen.add(e)
            unique.append(e)
    return unique


def _write_output(rows: list[dict], out_path: Optional[str]):
    import sys, json, csv
    if not out_path:
        print(json.dumps(rows, ensure_ascii=False))
        return
    if out_path.lower().endswith(".csv"):
        # flatten headers
        headers = sorted({k for r in rows for k in r.keys()})
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            for r in rows:
                w.writerow(r)
    else:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)


# --- Simple SQLite cache for MX and (future) email results ---

def _cache_path() -> str:
    # Place cache at repo root next to scripts/.egc_cache.db
    from pathlib import Path
    return str((Path(__file__).resolve().parents[1] / ".egc_cache.db"))


def _init_cache(db_path: str):
    import sqlite3
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS mx_cache (domain TEXT PRIMARY KEY, hosts_json TEXT NOT NULL, checked_at INTEGER NOT NULL)")
        cur.execute("CREATE TABLE IF NOT EXISTS email_cache (email TEXT PRIMARY KEY, result_json TEXT NOT NULL, checked_at INTEGER NOT NULL)")
        con.commit()
    finally:
        con.close()


def _load_mx(db_path: str, domain: str):
    import sqlite3, json
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("SELECT hosts_json, checked_at FROM mx_cache WHERE domain=?", (domain,))
        row = cur.fetchone()
        if not row:
            return None
        hosts = json.loads(row[0])
        return {"hosts": hosts, "checked_at": int(row[1])}
    finally:
        con.close()


def _save_mx(db_path: str, domain: str, hosts: List[str]):
    import sqlite3, json, time
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("REPLACE INTO mx_cache(domain, hosts_json, checked_at) VALUES(?,?,?)", (domain, json.dumps(hosts), int(time.time())))
        con.commit()
    finally:
        con.close()


def _is_fresh(checked_at: int, ttl_days: int) -> bool:
    now = int(time.time())
    return (now - checked_at) < (ttl_days * 24 * 3600)


def _load_email(db_path: str, email: str):
    import sqlite3, json
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("SELECT result_json, checked_at FROM email_cache WHERE email=?", (email,))
        row = cur.fetchone()
        if not row:
            return None
        result = json.loads(row[0])
        return {"result": result, "checked_at": int(row[1])}
    finally:
        con.close()


def _save_email(db_path: str, email: str, result: Dict[str, Any]):
    import sqlite3, json, time
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("REPLACE INTO email_cache(email, result_json, checked_at) VALUES(?,?,?)", (email, json.dumps(result), int(time.time())))
        con.commit()
    finally:
        con.close()


def main(argv=None) -> int:
    import sys

    args = _parse_args(argv)
    emails = _read_emails(args.emails_file, args.email)
    if not emails:
        # input error
        return 2

    results: list[dict] = []

    db_path = _cache_path()
    _init_cache(db_path)

    domain_counts: Dict[str, int] = {}
    domain_backoff_until: Dict[str, float] = {}

    for email in emails:
        try:
            domain = parse_domain(email)
        except ValueError:
            results.append({
                "email": email,
                "domain": None,
                "mx_used": None,
                "accepts_rcpt": False,
                "smtp_code": None,
                "smtp_message": "invalid email",
                "error_category": "input",
                "rtt_ms": None,
                "mx_found": False,
            })
            continue

        if args.skip_free and should_skip_domain(domain):
            results.append({
                "email": email,
                "domain": domain,
                "mx_used": None,
                "accepts_rcpt": False,
                "smtp_code": None,
                "smtp_message": "skipped free domain",
                "error_category": "policy",
                "rtt_ms": None,
                "mx_found": False,
            })
            continue

        # Enforce per-domain quota
        cnt = domain_counts.get(domain, 0)
        if cnt >= int(args.max_per_domain):
            results.append({
                "email": email,
                "domain": domain,
                "mx_used": None,
                "accepts_rcpt": False,
                "smtp_code": None,
                "smtp_message": "domain quota exceeded",
                "error_category": "policy",
                "rtt_ms": None,
                "mx_found": False,
            })
            continue

        # Check domain backoff
        now = time.time()
        until = domain_backoff_until.get(domain, 0)
        if now < until:
            results.append({
                "email": email,
                "domain": domain,
                "mx_used": None,
                "accepts_rcpt": False,
                "smtp_code": None,
                "smtp_message": "backoff active",
                "error_category": "policy",
                "rtt_ms": None,
                "mx_found": False,
            })
            continue

        # Email-level cache
        e_entry = _load_email(db_path, email)
        if e_entry and _is_fresh(int(e_entry["checked_at"]), int(args.mx_ttl_days)):
            results.append(e_entry["result"])
            continue

        domain_counts[domain] = cnt + 1

        if not args.mx:
            # Try cache first
            mx_entry = _load_mx(db_path, domain)
            hosts: List[str] = []
            if mx_entry and _is_fresh(int(mx_entry["checked_at"]), int(args.mx_ttl_days)):
                hosts = list(mx_entry["hosts"]) or []
            else:
                hosts = resolve_mx(domain)
                if hosts:
                    _save_mx(db_path, domain, hosts)

            if not hosts:
                results.append({
                    "email": email,
                    "domain": domain,
                    "mx_used": None,
                    "accepts_rcpt": False,
                    "smtp_code": None,
                    "smtp_message": "no MX records found",
                    "error_category": "network",
                    "rtt_ms": None,
                    "mx_found": False,
                })
                continue

            # Probe first available MX, simple PoC iteration until success/last
            probe_result = None
            for host in hosts:
                pr = probe_rcpt(host, email, timeout=args.timeout)
                pr.setdefault("mx_found", True)
                probe_result = pr
                # Simple backoff handling on temp errors
                if pr.get("error_category") == "temp":
                    # backoff grows with attempts on this domain in this run
                    backoff_seconds = min(60, 2 ** max(1, domain_counts.get(domain, 1)))
                    domain_backoff_until[domain] = time.time() + backoff_seconds
                # Stop at first 2xx accept
                if pr.get("accepts_rcpt"):
                    break
            if probe_result is not None:
                _save_email(db_path, email, probe_result)
            results.append(probe_result)
            continue

        # Real probe path using explicit MX
        res = probe_rcpt(args.mx, email, timeout=args.timeout)
        # Ensure mx_found flag present for output consistency
        res.setdefault("mx_found", True)
        _save_email(db_path, email, res)
        results.append(res)

    _write_output(results, args.out)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
