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
from typing import Optional, Dict, Any

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


if __name__ == "__main__":
    # Minimal manual check runner (not the full CLI, sufficient for PoC quick run)
    import argparse, json, sys

    ap = argparse.ArgumentParser(description="PoC SMTP RCPT probe (minimal)")
    ap.add_argument("email", nargs="?", help="email to probe")
    ap.add_argument("mx", nargs="?", help="MX host (e.g., mx.example.com)")
    ap.add_argument("--timeout", type=int, default=10)
    args = ap.parse_args()

    if not args.email or not args.mx:
        ap.print_usage(sys.stderr)
        sys.exit(2)

    res = probe_rcpt(args.mx, args.email, timeout=args.timeout)
    print(json.dumps(res, ensure_ascii=False))
