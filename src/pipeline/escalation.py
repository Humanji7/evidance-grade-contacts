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

# Additional JS/dynamic markers that should trigger escalation regardless of page size
JS_MARKERS = [
    r"data-cfemail",
    r"cf_email",
    r"javascript:.*mailto",
    r"data-email\s*=",
    r"data-phone\s*=",
    r"data-reactroot",
    r"ng-app",
    # Hidden email triggers (text/buttons) that suggest JS-reveal behavior
    r"show\s*(e-?mail|email)",
    r"reveal\s*(e-?mail|email)",
    r"display\s*(e-?mail|email)",
    r"показать\s*(e-?mail|email|почт\w+)",
    r"открыть\s*(e-?mail|email|почт\w+)",
]

TARGET_CARD_CLASS_RE = re.compile(r'class\s*=\s*"[^"]*(team|member|profile|person)[^"]*"', re.IGNORECASE)
H3_H4_RE = re.compile(r"<h[34][^>]*>", re.IGNORECASE)


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


def detect_js_markers(html: str | None) -> list[str]:
    reasons: list[str] = []
    if not html:
        return reasons
    for pat in JS_MARKERS:
        if re.search(pat, html, flags=re.IGNORECASE):
            reasons.append(f"js:{pat}")
    return reasons


def detect_cards_without_contacts(html: str | None) -> bool:
    """Heuristic: many repeating 'team/member/profile/person' blocks or many h3/h4 that look like cards,
    but no obvious mailto/tel anchors.
    """
    if not html:
        return False
    low = html.lower()
    # Count mailto/tel anchors
    has_mailto_or_tel = ("href=\"mailto:" in low) or ("href=\"tel:" in low)
    if has_mailto_or_tel:
        return False
    # Count repeating card-like classes
    cards = len(TARGET_CARD_CLASS_RE.findall(html))
    if cards >= 3:
        return True
    # Fallback: many headings (h3/h4) that often mark people cards
    headings = len(H3_H4_RE.findall(html))
    return headings >= 8  # a rough threshold


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
    # JS markers (independent of page size)
    js_reasons = detect_js_markers(fetch.html)
    reasons.extend(js_reasons)
    # Cards heuristic (cards present but no contacts anchors)
    if detect_cards_without_contacts(fetch.html):
        reasons.append("cards_present_but_no_mailto_tel")
    return EscalationDecision(escalate=len(reasons) > 0, reasons=reasons)
