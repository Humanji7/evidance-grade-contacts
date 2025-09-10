from __future__ import annotations

"""
Lightweight link discovery for people/leadership/contact pages.

Given a base URL, fetch the page (static) and extract in-domain links whose
href or anchor text suggests team/leadership/people/contacts sections.
This avoids hardcoding per-site paths and works across EN/RU/DE variants.
"""

from typing import List, Set
from urllib.parse import urlparse, urljoin, urlunparse

from selectolax.parser import HTMLParser

from .fetchers.static import StaticFetcher


KEYWORDS = [
    # English
    "team", "leadership", "management", "people", "staff", "executives", "board",
    "about", "contacts", "contact",
    # Russian
    "команда", "руководство", "менеджмент", "дирек", "о компании", "контакты", "совет директоров",
    # German
    "team", "leitung", "management", "über uns", "ueber uns", "kontakt", "impressum",
    "mitarbeiter", "vorstand", "geschäftsführung", "geschaeftsfuehrung",
]


def _same_domain(base: str, href: str) -> bool:
    try:
        b = urlparse(base)
        h = urlparse(href)
        if not h.netloc:
            return True
        return h.netloc.lower().lstrip("www.") == b.netloc.lower().lstrip("www.")
    except Exception:
        return False


def _is_candidate_link(text: str, href: str) -> bool:
    t = (text or "").lower()
    h = (href or "").lower()
    return any(k in t or k in h for k in KEYWORDS)


def _normalize_url(u: str) -> str:
    try:
        p = urlparse(u)
        netloc = (p.netloc or '').lower()
        path = p.path or ''
        if path.endswith('/') and path != '/':
            path = path.rstrip('/')
        p2 = p._replace(netloc=netloc, path=path, query='', fragment='')
        return urlunparse(p2)
    except Exception:
        return u


def discover_links(base_url: str, html: str, max_links: int = 20) -> List[str]:
    parser = HTMLParser(html)
    out: List[str] = []
    seen: Set[str] = set()
    for a in parser.css("a"):
        href = a.attrs.get("href") if a.attrs else None
        if not href:
            continue
        # Skip queries/fragments (facet pages)
        if '?' in href or '#' in href:
            continue
        text = (a.text() or "").strip()
        if not _is_candidate_link(text, href):
            continue
        abs_url = urljoin(base_url, href)
        if not _same_domain(base_url, abs_url):
            continue
        nu = _normalize_url(abs_url)
        if nu not in seen:
            seen.add(nu)
            out.append(nu)
        if len(out) >= max_links:
            break
    return out


def discover_from_root(base_url: str, *, timeout_s: float = 8.0) -> List[str]:
    sf = StaticFetcher(timeout_s=timeout_s)
    try:
        res = sf.fetch(base_url)
        if res.blocked_by_robots or res.status_code >= 400 or not res.html:
            return []
        return discover_links(res.url, res.html)
    except Exception:
        return []
    finally:
        sf.close()

