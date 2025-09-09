from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from .fetchers.static import FetchResult


ANTI_BOT_MARKERS = [
    r"Just a moment\s*\.\.\.",
    r"Enable JavaScript and cookies to continue",
    r"__cf_chl_",  # Cloudflare challenge scripts
]


@dataclass(frozen=True)
class EscalationDecision:
    escalate: bool
    reasons: List[str]


def detect_anti_bot(html: str | None) -> bool:
    if not html:
        return False
    for pat in ANTI_BOT_MARKERS:
        if re.search(pat, html, flags=re.IGNORECASE):
            return True
    return False


def decide_escalation(fetch: FetchResult, selector_hits: int) -> EscalationDecision:
    reasons: List[str] = []
    # MIME redirect into SPA/JS app
    if fetch.mime is not None and fetch.mime != "text/html":
        reasons.append(f"mime!=text/html ({fetch.mime})")
    # No target selectors and page is tiny
    if selector_hits == 0 and fetch.content_length < 5 * 1024:
        reasons.append("selector_hits==0 && content_length<5KiB")
    # Anti-bot/dynamic markers
    if detect_anti_bot(fetch.html):
        reasons.append("anti-bot markers detected")
    return EscalationDecision(escalate=len(reasons) > 0, reasons=reasons)
