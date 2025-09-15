"""
Contact Extraction Logic - Extract Names, Titles, Emails, and Phones

Extracts contact information from DOM elements using semantic selectors
and pattern matching. Supports both static HTML (selectolax) and 
dynamic content (Playwright) extraction methods.

Key Features:
- Semantic selectors for person cards and contact info
- Email/phone pattern extraction with validation
- Company name detection from page context
- Works with both static HTML and Playwright page objects
"""

import re
import os
import html
import difflib
import time
from typing import List, Dict, Optional, Union, Tuple
from urllib.parse import urljoin, urlparse
from collections import Counter

from selectolax.parser import HTMLParser, Node
from playwright.sync_api import Page, ElementHandle, Locator
import httpx

from ..schemas import ContactType, Contact, Evidence
from ..evidence import EvidenceBuilder


class ContactExtractor:
    """
    Extracts contact information from web pages with evidence packages.
    
    Supports both static HTML parsing and dynamic Playwright extraction
    with complete Mini Evidence Package generation for each contact.
    """
    
    def __init__(self, evidence_builder: Optional[EvidenceBuilder] = None, aggressive_static: bool = False):
        """
        Initialize Contact Extractor.
        
        Args:
            evidence_builder: EvidenceBuilder instance for creating evidence packages
        """
        self.evidence_builder = evidence_builder or EvidenceBuilder()
        self.aggressive_static = bool(aggressive_static)
        
        # D=1 follow-up budget (reset per top-level extract call)
        self._d1_budget: Optional[int] = None
        
        # Cross-domain acceptance scoring (hardcoded weights and threshold; no new configs)
        self._XDOM_THRESHOLD: int = 5  # moderate threshold
        self._XDOM_W: Dict[str, int] = {
            'in_person_card': 0,  # do not count this unless strict boundary checks are added
            'has_title': 1,
            'mailto': 2,
            'has_phone': 2,
            'has_vcard': 2,
            'show_email_trigger': 1,
            'domain_repeat_2plus': 1,
            'domain_repeat_3plus': 2,
            'domain_in_footer': 2,
            'site_repeat_3plus': 1,
            'site_repeat_5plus': 2,
            'negative_zone': -2,
        }
        # Per-page context caches (reset each extract call)
        self._page_mailto_counts: Counter[str] = Counter()
        self._footer_contact_text: str = ""
        # Site-level domain frequency (reset when site changes)
        self._site_host: Optional[str] = None
        self._site_mailto_counts: Counter[str] = Counter()
        # Trigger patterns for hidden/revealed emails (used as a signal)
        self._show_email_re = re.compile(r"\b(show|reveal|display|показать|открыть)\s*(e-?mail|email|почт\w+|адрес)\b", re.I)
        
        # Common selectors for person information
        self.person_selectors = [
            # Prefer full entry cards first
            '.entry-team-info',
            # Avada cards
            '.fusion-layout-column.bg-green.text-white.text-center',
            # Common person cards
            '.person, .team-member, .employee, .staff-member',
            '.bio, .biography, .profile',
            '.card .person-info, .member-card, .profile-card, .team-card',
            '[data-person], [data-team-member]',
            'article.person, section.team-member, article.profile',
            # WordPress builders (Elementor/Avada/WPBakery)
            '.elementor-team-member, .team-member__content, .elementor-widget-team-member, .our-team, .team-grid article',
            "[class*='team-member']", "[class*='member-card']",
            # Heuristic by class name fragments
            "[class*='team-info']",
            "[class*='team']", "[class*='people']", "[class*='person']",
            "[class*='staff']", "[class*='member']", "[class*='attorney']", "[class*='lawyer']",
        ]
        
        # Selectors for names within person containers
        self.name_selectors = [
            'h1, h2, h3, h4',
            '.name, .person-name, .full-name, .profile-name',
            ".heading, .card-title, .profile-header h2, .profile-header h3",
            'strong:first-child, b:first-child'
        ]
        
        # Selectors for job titles/roles
        self.title_selectors = [
            '.title, .job-title, .position, .role, .position-title',
            '.subtitle, .description:first-of-type, .profile-title, .card-subtitle',
            'em, i, .italic',
            'p:first-of-type, .bio p:first-child',
            # adjacency patterns: title follows name header
            'h3 + p, h4 + p'
        ]
        
        # Email patterns
        self.email_pattern = re.compile(
            r'\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b', re.IGNORECASE
        )
        
        # Phone patterns (international formats)
        self.phone_pattern = re.compile(
            r'(?:\+?1[-\s]?)?\(?\d{3}\)?[-\s]?\d{3}[-\s]?\d{4}|'
            r'\+?\d{1,3}[-\s]?\(?\d{1,4}\)?[-\s]?\d{1,4}[-\s]?\d{1,9}'
        )

        # Free email domains (used for allow_free env)
        self.free_email_domains = {
            'gmail.com','yahoo.com','outlook.com','hotmail.com','aol.com','icloud.com','proton.me','protonmail.com'
        }

    # -------------------------
    # Aggressive-static utilities
    # -------------------------
    def _deobfuscate_email(self, text_or_href: str) -> Optional[str]:
        """Best-effort deobfuscation for emails in text or URLs.
        - Replaces (at)/[at]/ at -> @ and (dot)/[dot]/ dot -> .
        - Unescapes HTML entities
        - If "mailto:" appears with JS concatenation, tries to stitch quoted parts
        Returns a single plausible email if found and valid, else None.
        """
        if not text_or_href:
            return None
        s = str(text_or_href)
        s = html.unescape(s)
        # Remove common wrappers
        s_norm = s.replace('\u200b', '')  # zero-width
        # Normalize spaced tokens around at/dot
        s_norm = re.sub(r"(?i)\s*(?:\(|\[)?at(?:\)|\])\s*", "@", s_norm)
        s_norm = re.sub(r"(?i)\s*(?:\(|\[)?dot(?:\)|\])\s*", ".", s_norm)
        s_norm = s_norm.replace("(at)", "@").replace("[at]", "@").replace(" at ", "@").replace("(dot)", ".").replace("[dot]", ".").replace(" dot ", ".")
        # Strip spaces around @ and .
        s_norm = re.sub(r"\s*@\s*", "@", s_norm)
        s_norm = re.sub(r"\s*\.\s*", ".", s_norm)
        # Remove mailto: prefix if present
        s_norm = re.sub(r"(?i)mailto:\s*", "", s_norm)
        # Direct email match
        m = self.email_pattern.search(s_norm)
        if m:
            return m.group(0)
        # Try to reconstruct from quoted parts after a 'mailto:' style concat
        if 'mailto' in s.lower():
            parts = re.findall(r"[\"']([A-Za-z0-9._%+@-]+)[\"']", s)
            if parts:
                cand = ''.join(parts)
                m2 = self.email_pattern.search(cand)
                if m2:
                    return m2.group(0)
        return None

    def _sanitize_mailto(self, href: str, fallback_text: Optional[str] = None) -> Optional[str]:
        """Sanitize a mailto href and fallback to link text if needed."""
        if not href:
            return None
        s = href.strip()
        raw = s[7:] if s.lower().startswith('mailto:') else s
        email = raw.split('?', 1)[0].split('#', 1)[0].strip().lower()
        if self.email_pattern.match(email):
            return email
        if fallback_text:
            ft = html.unescape(str(fallback_text)).strip()
            m = self.email_pattern.search(ft.lower())
            if m:
                return m.group(0)
        return None

    # -------------------------
    # Cross-domain acceptance helpers (static context)
    # -------------------------
    def _xdom_prepare_context_static(self, parser: HTMLParser, source_url: str) -> None:
        """Compute per-page domain counts and footer/contact text for cross-domain signals.
        Stored in instance fields; reset per extract call.
        """
        counts: Counter[str] = Counter()
        try:
            for a in parser.css("a[href*='mailto:']"):
                try:
                    href = (a.attrs.get('href', '') or '').strip()
                    txt = (a.text() or '').strip()
                    email = self._sanitize_mailto(href, txt) or self._deobfuscate_email(href) or self._deobfuscate_email(txt)
                    if not email or '@' not in email:
                        continue
                    edom = email.split('@')[-1].lower()
                    counts[edom] += 1
                except Exception:
                    continue
        except Exception:
            counts = Counter()
        # Footer/contact blocks text
        parts: List[str] = []
        try:
            for f in (parser.css('footer') or []):
                t = f.text() or ''
                if t:
                    parts.append(t)
        except Exception:
            pass
        try:
            for blk in (parser.css("address, .contact, .contacts, .contact-info, .contact-us, [class*='contact']") or []):
                t = blk.text() or ''
                if t:
                    parts.append(t)
        except Exception:
            pass
        low = '\n'.join(parts).lower()
        self._page_mailto_counts = counts
        self._footer_contact_text = low
        # Update site-level counters
        self._xdom_reset_or_update_site_counts(source_url)

    def _xdom_page_domain_count(self, domain: str) -> int:
        return int(self._page_mailto_counts.get((domain or '').strip().lower(), 0))

    def _xdom_reset_or_update_site_counts(self, source_url: str) -> None:
        try:
            host = urlparse(source_url).netloc.lower().replace('www.', '')
        except Exception:
            host = ''
        if host and host != self._site_host:
            # New site → reset counters
            self._site_host = host
            self._site_mailto_counts = Counter()
        # Accumulate per-page counts into site-level counts
        for dom, cnt in (self._page_mailto_counts or {}).items():
            if dom:
                self._site_mailto_counts[dom] += int(cnt)

    def _xdom_site_domain_count(self, domain: str) -> int:
        return int(self._site_mailto_counts.get((domain or '').strip().lower(), 0))

    def _xdom_min_confirmation(self,
                               *,
                               has_phone: bool,
                               has_vcard: bool,
                               page_repeat: int,
                               in_footer: bool,
                               site_repeat: int) -> tuple[bool, list[str]]:
        """Strong-signal gate: require at least one of the following:
        - phone in same card
        - vCard in same card
        - page-level domain repeat >= 2
        - domain mentioned in footer/contact block
        - site-level domain repeat >= 3
        Returns (ok, missing_signals_list)
        """
        ok = bool(has_phone or has_vcard or page_repeat >= 2 or in_footer or site_repeat >= 3)
        missing: list[str] = []
        if not has_phone:
            missing.append('phone')
        if not has_vcard:
            missing.append('vcard')
        if page_repeat < 2:
            missing.append('page_repeat>=2')
        if not in_footer:
            missing.append('footer_mention')
        if site_repeat < 3:
            missing.append('site_repeat>=3')
        return ok, missing

    def _xdom_log_accept(self, *, email: str, domain: str, source_url: str, score: int, signals: list[str]) -> None:
        try:
            print(f"cross-domain: accepted (email={email}, domain={domain}, score={score}) signals={','.join(signals)} @ {source_url}")
        except Exception:
            pass

    def _xdom_domain_in_footer_or_contacts(self, domain: str) -> bool:
        dom = (domain or '').strip().lower()
        if not dom:
            return False
        txt = self._footer_contact_text or ''
        return (dom in txt) or (('@' + dom) in txt)

    def _is_negative_zone_path(self, source_url: str) -> bool:
        try:
            p = urlparse(source_url).path.lower()
        except Exception:
            p = ''
        NEG = ('/press', '/news', '/media', '/newsroom', '/careers', '/jobs', '/vacancies', '/employment', '/agency')
        return any(seg in p for seg in NEG)

    def _node_has_show_email_trigger(self, node: Node) -> bool:
        try:
            text = (node.text() or '').lower()
            if self._show_email_re.search(text):
                return True
            # Also look at buttons/anchors specifically
            for a in node.css('a, button, span, div'):
                t = (a.text() or '').lower()
                if t and self._show_email_re.search(t):
                    return True
        except Exception:
            pass
        return False

    def _node_has_phone_hint(self, node: Node) -> bool:
        try:
            if node.css_first("a[href*='tel:']") is not None:
                return True
            text = node.text() or ''
            return bool(self.phone_pattern.search(text))
        except Exception:
            return False

    def _node_has_vcf_hint(self, node: Node) -> bool:
        try:
            return node.css_first("a[href$='.vcf']") is not None
        except Exception:
            return False

    def _xdom_score_static(self,
                            email_domain: str,
                            *,
                            in_person_card: bool,
                            has_title: bool,
                            from_mailto: bool,
                            has_phone: bool,
                            has_vcard: bool,
                            has_show_trigger: bool,
                            page_domain_count: int,
                            site_domain_count: int,
                            domain_in_footer: bool,
                            negative_zone: bool) -> tuple[int, List[str]]:
        """Compute cross-domain score and return (score, signal_names)."""
        s = 0
        signals: List[str] = []
        if in_person_card and self._XDOM_W['in_person_card']:
            s += self._XDOM_W['in_person_card']; signals.append('card')
        if has_title:
            s += self._XDOM_W['has_title']; signals.append('title')
        if from_mailto:
            s += self._XDOM_W['mailto']; signals.append('mailto')
        if has_phone:
            s += self._XDOM_W['has_phone']; signals.append('phone')
        if has_vcard:
            s += self._XDOM_W['has_vcard']; signals.append('vcard')
        if has_show_trigger:
            s += self._XDOM_W['show_email_trigger']; signals.append('show-email')
        if page_domain_count >= 3:
            s += self._XDOM_W['domain_repeat_3plus']; signals.append('repeat>=3')
        elif page_domain_count >= 2:
            s += self._XDOM_W['domain_repeat_2plus']; signals.append('repeat>=2')
        if site_domain_count >= 5:
            s += self._XDOM_W['site_repeat_5plus']; signals.append('site>=5')
        elif site_domain_count >= 3:
            s += self._XDOM_W['site_repeat_3plus']; signals.append('site>=3')
        if domain_in_footer:
            s += self._XDOM_W['domain_in_footer']; signals.append('footer')
        if negative_zone:
            s += self._XDOM_W['negative_zone']; signals.append('neg-zone')
        return s, signals

    def _emails_from_text(self, node: Node) -> List[str]:
        """Find emails in raw text within a node, including deobfuscated ones."""
        found: set[str] = set()
        text = (node.text() or '')
        for em in self.email_pattern.findall(text):
            found.add(em)
        # Try deobfuscation on block text
        deob = self._deobfuscate_email(text)
        if deob:
            found.add(deob)
        # Try anchors inside node
        for a in node.css('a'):
            href = a.attrs.get('href', '') if a and a.attrs else ''
            cand = self._deobfuscate_email(href) or self._deobfuscate_email(a.text() or '')
            if cand:
                found.add(cand)
        return list(found)

    def _email_domain_matches_site(self, email_domain: str, site_domain: str) -> bool:
        """Heuristic domain match: registrable part match or high similarity.
        Allows minor differences and subdomain variations.
        """
        if not email_domain or not site_domain:
            return False
        def norm(d: str) -> str:
            d = d.lower().strip()
            if d.startswith('www.'):
                d = d[4:]
            return d
        def registrable(d: str) -> str:
            parts = d.split('.')
            if len(parts) >= 3 and parts[-2] in {'co','com','org','net','gov','ac','edu'} and len(parts[-1]) <= 3:
                return '.'.join(parts[-3:])
            return '.'.join(parts[-2:]) if len(parts) >= 2 else d
        d1 = registrable(norm(email_domain))
        d2 = registrable(norm(site_domain))
        if d1 == d2:
            return True
        ratio = difflib.SequenceMatcher(None, d1, d2).ratio()
        return ratio >= 0.9
    
    def extract_from_static_html(self, html: str, source_url: str) -> List[Contact]:
        """
        Extract contacts from static HTML using selectolax.
        
        Args:
            html: Raw HTML content
            source_url: URL where HTML was fetched
            
        Returns:
            List of Contact objects with complete evidence packages
        """
        parser = HTMLParser(html)
        contacts: List[Contact] = []
        
        # Prepare per-page cross-domain context
        try:
            self._xdom_prepare_context_static(parser, source_url)
        except Exception:
            # Fail-quietly; context signals simply unavailable
            self._page_mailto_counts = Counter()
            self._footer_contact_text = ""
            self._xdom_reset_or_update_site_counts(source_url)
        
        # Top-level call budget reset for D=1 profile follow-ups
        local_reset = False
        if self._d1_budget is None:
            self._d1_budget = 5
            local_reset = True
        
        # Extract company name from page
        company_name = self._extract_company_name_static(parser, source_url)
        
        # Find person containers first
        found_person_containers = False
        seen_roots = set()
        for selector in self.person_selectors:
            person_nodes = parser.css(selector)
            if person_nodes:
                found_person_containers = True
            
            for person_node in person_nodes:
                root = self._choose_card_root_by_repetition(person_node)
                root_id = id(root)
                if root_id in seen_roots:
                    continue
                seen_roots.add(root_id)
                person_contacts = self._extract_person_contacts_static(
                    root, source_url, company_name, selector
                )
                contacts.extend(person_contacts)
        
        # If no structured person containers were found, try table extractor first (aggressive), then generic fallback.
        # scan for repeating sibling blocks that look like cards and extract from them.
        if not found_person_containers:
            used_table = False
            if self.aggressive_static:
                try:
                    table_contacts = self._extract_table_contacts_static(parser, source_url, company_name)
                    if table_contacts:
                        print(f"[AGG] table-extractor: +{len(table_contacts)} contacts from tables @ {source_url}")
                        contacts.extend(table_contacts)
                        used_table = True
                except Exception:
                    # Fail-quietly for PoC
                    pass
            if not used_table:
                fallback_contacts = self._fallback_repeating_cards(parser, source_url, company_name)
                contacts.extend(fallback_contacts)
        # Post-filtering and deduplication
        contacts = self._postprocess_and_dedup(contacts)
        
        # Reset D=1 budget after top-level extraction completes
        if local_reset:
            self._d1_budget = None
        return contacts
    
    def extract_from_playwright(self, page: Page, source_url: str) -> List[Contact]:
        """
        Extract contacts from dynamic page using Playwright.
        
        Args:
            page: Playwright Page object
            source_url: URL of the page
            
        Returns:
            List of Contact objects with complete evidence packages
        """
        contacts = []
        
        # Extract company name from page
        company_name = self._extract_company_name_playwright(page, source_url)
        
        # Prepare per-page cross-domain context (mailto domain counts, footer/contact text)
        try:
            self._xdom_prepare_context_playwright(page, source_url)
        except Exception:
            self._page_mailto_counts = Counter()
            self._footer_contact_text = ""
            self._xdom_reset_or_update_site_counts(source_url)
        
        # Find person containers
        for selector in self.person_selectors:
            try:
                person_elements = page.locator(selector).all()
                
                for person_element in person_elements:
                    person_contacts = self._extract_person_contacts_playwright(
                        person_element, page, source_url, company_name, selector
                    )
                    contacts.extend(person_contacts)
                    
            except Exception:
                # Continue with next selector if this one fails
                continue
        
        return contacts
    
    def _extract_company_name_static(self, parser: HTMLParser, source_url: str) -> str:
        """Extract company name from static HTML page."""
        # Try various approaches to get company name
        company_selectors = [
            'title',
            'h1:first-of-type',
            '.company-name, .organization',
            '[data-company], [data-organization]',
            '.site-title, .brand-title'
        ]
        
        for selector in company_selectors:
            element = parser.css_first(selector)
            if element and element.text():
                company_text = element.text().strip()
                # Clean up common patterns
                company_text = re.sub(r'\s*[-|].*$', '', company_text)  # Remove everything after - or |
                # Drop generic section headers entirely
                if re.search(r'^(Contact|Contacts|News(?:\s*&\s*Insights)?|Press|Team|People|About)\b', company_text, re.IGNORECASE):
                    company_text = ''
                if company_text:
                    return company_text[:100]  # Limit length
        
        # Fallback: extract from URL hostname
        return urlparse(source_url).netloc.replace('www.', '').title()
    
    def _extract_company_name_playwright(self, page: Page, source_url: str) -> str:
        """Extract company name from Playwright page."""
        company_selectors = [
            'title',
            'h1:first-of-type',
            '.company-name, .organization',
            '[data-company], [data-organization]',
            '.site-title, .brand-title'
        ]
        
        for selector in company_selectors:
            try:
                element = page.locator(selector).first
                text_content = element.text_content()
                if text_content:
                    company_text = text_content.strip()
                    # Clean up common patterns
                    company_text = re.sub(r'\s*[-|].*$', '', company_text)
                    company_text = re.sub(r'\s*(Team|People|About).*$', '', company_text, re.IGNORECASE)
                    if company_text:
                        return company_text[:100]
                        
            except Exception:
                continue
        
        # Fallback: extract from URL hostname
        return urlparse(source_url).netloc.replace('www.', '').title()
    
    def _extract_person_contacts_static(
        self, 
        person_node: Node, 
        source_url: str, 
        company_name: str, 
        base_selector: str
    ) -> List[Contact]:
        """Extract all contacts for a single person from static HTML."""
        contacts: List[Contact] = []

        # Extract person name and title (within this root only)
        name_node = self._find_name_node_static(person_node)
        person_name = self._text_from_name_node(name_node) if name_node else None
        # Try to get role near name inside same paragraph with <br>
        person_title = self._extract_role_near_name_static(person_node, name_node) or self._extract_person_title_static(person_node)
        person_title = self._normalize_role_title(person_title) if person_title else person_title

        # Name is mandatory
        if not person_name:
            return contacts

        # Listing URL detection (for role Unknown fallback)
        try:
            path_low = urlparse(source_url).path.lower()
        except Exception:
            path_low = ""
        is_listing_url = any(x in path_low for x in ("/team", "/our-team", "/people", "/leadership", "/management"))

        # Email/Phone/VCF collection containers
        found_any_contact = False
        found_email = False
        found_phone = False

        # Email domain filter inputs
        site_domain = urlparse(source_url).netloc.lower().replace('www.', '')
        allow_free_env = os.getenv('EGC_ALLOW_FREE_EMAIL', '0') == '1'

        # 1) Emails: prefer mailto; if absent, use aria/title/icon or text-only within card root
        candidate_emails: List[tuple[str, Optional[Node], str]] = []  # (email, node, selector)
        
        # Cross-domain signal hints available at card-level
        has_phone_hint = self._node_has_phone_hint(person_node)
        has_vcf_hint = self._node_has_vcf_hint(person_node)
        has_show_trigger = self._node_has_show_email_trigger(person_node)
        negative_zone = self._is_negative_zone_path(source_url)
        # If show-email trigger is present and we didn't capture an email here, leave card as valid via other signals; dynamic path may reveal later.
        email_link = self._nearest_link(person_node, name_node, "a[href*='mailto:']") if name_node else None
        if email_link:
            href = (email_link.attrs.get('href','') or '').strip()
            txt = (email_link.text() or '').strip()
            email_val = self._sanitize_mailto(href, txt) or self._deobfuscate_email(href) or self._deobfuscate_email(txt)
            if email_val:
                email_val = email_val.lower()
            if email_val and self.email_pattern.match(email_val):
                candidate_emails.append((email_val, email_link, f"{base_selector} a[href*='mailto:']"))
        else:
            # a[aria-label*='email' i], a[title*='email' i]
            for a in person_node.css('a'):
                if not a or not a.attrs:
                    continue
                lab = (a.attrs.get('aria-label') or a.attrs.get('title') or '').lower()
                if 'email' in lab:
                    # Try to extract email from card text
                    for em in self._emails_from_text(person_node):
                        candidate_emails.append((em.lower(), a, f"{base_selector} a[aria|title*=email]"))
                        break
            # i[class*='envelope'] → nearest parent-anchor
            for i_node in person_node.css('i'):
                cls = (i_node.attrs.get('class','') or '').lower()
                if 'envelope' in cls:
                    parent = i_node.parent
                    anchor = None
                    while parent is not None:
                        if parent.tag == 'a':
                            anchor = parent
                            break
                        parent = parent.parent
                    if anchor is not None:
                        for em in self._emails_from_text(person_node):
                            candidate_emails.append((em, anchor, f"{base_selector} i[class*='envelope']~a"))
                            break
            # Pure text email within card
            if not candidate_emails:
                for em in self._emails_from_text(person_node):
                    candidate_emails.append((em.lower(), person_node, f"{base_selector} :text-email"))
                    break

        # Filter and add emails by domain policy
        used_emails: set[str] = set()
        for email_val, node_for_ev, sel in candidate_emails:
            if not email_val or email_val in used_emails:
                continue
            email_domain = email_val.split('@')[-1].lower() if '@' in email_val else ''
            same_domain = email_domain.endswith(site_domain)
            brand_match = same_domain or self._email_domain_matches_site(email_domain, site_domain)
            # Free email acceptance remains behind env guard
            free_ok = (allow_free_env and (email_domain in self.free_email_domains))

            accept = False

            if brand_match or free_ok:
                accept = True
            else:
                # Cross-domain scoring path
                from_mailto = ("mailto:" in sel) or (node_for_ev is not None and getattr(node_for_ev, 'attrs', None) and str((node_for_ev.attrs.get('href','') or '')).lower().startswith('mailto:'))
                page_count = self._xdom_page_domain_count(email_domain)
                site_count = self._xdom_site_domain_count(email_domain)
                in_footer = self._xdom_domain_in_footer_or_contacts(email_domain)
                score, sigs = self._xdom_score_static(
                    email_domain,
                    in_person_card=True,
                    has_title=bool(person_title and person_title.strip()),
                    from_mailto=bool(from_mailto),
                    has_phone=bool(has_phone_hint),
                    has_vcard=bool(has_vcf_hint),
                    has_show_trigger=bool(has_show_trigger),
                    page_domain_count=int(page_count),
                    site_domain_count=int(site_count),
                    domain_in_footer=bool(in_footer),
                    negative_zone=bool(negative_zone),
                )
                if score >= self._XDOM_THRESHOLD:
                    # Minimal confirmation strong-signal gate
                    strong_ok, missing = self._xdom_min_confirmation(
                        has_phone=bool(has_phone_hint),
                        has_vcard=bool(has_vcf_hint),
                        page_repeat=int(page_count),
                        in_footer=bool(in_footer),
                        site_repeat=int(site_count),
                    )
                    if strong_ok:
                        accept = True
                        self._xdom_log_accept(email=email_val, domain=email_domain, source_url=source_url, score=score, signals=sigs)
                    else:
                        print(f"cross-domain: недостаточно подтверждающих сигналов (email={email_val}, domain={email_domain}). Нет: {', '.join(missing)}")
                else:
                    print(f"cross-domain: score ниже порога (score={score}, threshold={self._XDOM_THRESHOLD}, domain={email_domain})")

            if accept:
                evidence = self.evidence_builder.create_evidence_static(
                    source_url=source_url,
                    selector=sel,  # keep selector clean; notes go to logs only
                    node=node_for_ev or person_node,
                    verbatim_text=(node_for_ev.text() if (node_for_ev and hasattr(node_for_ev, 'text')) else None) or email_val
                )
                contacts.append(Contact(
                    company=company_name,
                    person_name=person_name,
                    role_title=person_title or "Unknown",
                    contact_type=ContactType.EMAIL,
                    contact_value=email_val,
                    evidence=evidence,
                    captured_at=evidence.timestamp
                ))
                used_emails.add(email_val)
                found_any_contact = True
                found_email = True

        # 2) Phones: tel links; if none, aria/title/icon or text within card
        phones_added = False
        phone_link = self._nearest_link(person_node, name_node, "a[href*='tel:']") if name_node else None
        candidate_phones: List[tuple[str, Optional[Node], str, str]] = []  # (normalized_digits, node, selector, raw_display)
        if phone_link:
            href = phone_link.attrs.get('href','') or ''
            phone_raw = href[4:] if href.startswith('tel:') else href
            normalized_phone = re.sub(r"\D", "", phone_raw)
            candidate_phones.append((normalized_phone, phone_link, f"{base_selector} a[href*='tel:']", phone_raw))
        else:
            # a[aria-label*='phone' i], a[title*='phone' i]
            for a in person_node.css('a'):
                if not a or not a.attrs:
                    continue
                lab = (a.attrs.get('aria-label') or a.attrs.get('title') or '').lower()
                if 'phone' in lab or 'tel' in lab:
                    # extract first phone from card text
                    text_block = person_node.text() or ''
                    for m in self.phone_pattern.findall(text_block):
                        raw = m if isinstance(m, str) else ''.join(m)
                        num = re.sub(r"\D", "", raw)
                        if not num or len(num) < 10 or len(num) > 15:
                            continue
                        if re.match(r'^(19|20)\d{6,8}$', num):
                            continue
                        candidate_phones.append((num, a, f"{base_selector} a[aria|title*=phone]", raw))
                        break
            # icons i[class*='phone'|'tel'] → nearest anchor
            for i_node in person_node.css('i'):
                cls = (i_node.attrs.get('class','') or '').lower()
                if ('phone' in cls) or (re.search(r'\btel\b', cls) is not None):
                    parent = i_node.parent
                    anchor = None
                    while parent is not None:
                        if parent.tag == 'a':
                            anchor = parent
                            break
                        parent = parent.parent
                    if anchor is not None:
                        text_block = person_node.text() or ''
                        for m in self.phone_pattern.findall(text_block):
                            raw = m if isinstance(m, str) else ''.join(m)
                            num = re.sub(r"\D", "", raw)
                            if not num or len(num) < 10 or len(num) > 15:
                                continue
                            if re.match(r'^(19|20)\d{6,8}$', num):
                                continue
                            candidate_phones.append((num, anchor, f"{base_selector} i[class*='phone|tel']~a", raw))
                            break
            # Pure text phone within card
            if not candidate_phones:
                text_block = person_node.text() or ''
                for m in self.phone_pattern.findall(text_block):
                    raw = m if isinstance(m, str) else ''.join(m)
                    num = re.sub(r"\D", "", raw)
                    if not num or len(num) < 10 or len(num) > 15:
                        continue
                    if re.match(r'^(19|20)\d{6,8}$', num):
                        continue
                    candidate_phones.append((num, person_node, f"{base_selector} :text-phone", raw))
                    break
        
        for num, node_for_ev, sel, raw_disp in candidate_phones:
            evidence = self.evidence_builder.create_evidence_static(
                source_url=source_url,
                selector=sel,
                node=node_for_ev or person_node,
                verbatim_text=(node_for_ev.text() if (node_for_ev and hasattr(node_for_ev, 'text')) else None) or raw_disp
            )
            try:
                contacts.append(Contact(
                    company=company_name,
                    person_name=person_name,
                    role_title=person_title or "Unknown",
                    contact_type=ContactType.PHONE,
                    contact_value=num,
                    evidence=evidence,
                    captured_at=evidence.timestamp
                ))
                found_any_contact = True
                found_phone = True
                phones_added = True
            except Exception:
                continue

        # 3) vCard links (.vcf) if present in card — strict attribution
        for a in person_node.css('a'):
            href = (a.attrs.get('href','') or '').strip()
            if not href:
                continue
            href_low = href.lower()
            if not href_low.endswith('.vcf'):
                # Skip non-VCF; do not attribute by generic 'vcard' text
                continue
            # Require filename contains at least one token from the person's name
            try:
                from urllib.parse import urlsplit
                joined = urljoin(source_url, href)
                path = urlsplit(joined).path or ''
            except Exception:
                joined = urljoin(source_url, href)
                path = href_low
            # Normalize tokens from person name (ASCII letters best-effort)
            name_tokens = [t for t in re.split(r"[^a-zA-Z]+", person_name.lower()) if t]
            # Fallback: split on non-alphanumerics if above yields nothing
            if not name_tokens:
                name_tokens = [t for t in re.split(r"[^a-z0-9]+", person_name.lower()) if t]
            path_low = path.lower()
            if not any(tok and tok in path_low for tok in name_tokens):
                # Do not attribute vCard to this person if filename doesn't include their name tokens
                continue
            vcf_url = urljoin(source_url, href)
            evidence = self.evidence_builder.create_evidence_static(
                source_url=source_url,
                selector=f"{base_selector} a[href$='.vcf']",
                node=a,
                verbatim_text=a.text() or href
            )
            try:
                contacts.append(Contact(
                    company=company_name,
                    person_name=person_name,
                    role_title=person_title or "Unknown",
                    contact_type=ContactType.LINK,
                    contact_value=vcf_url,
                    evidence=evidence,
                    captured_at=evidence.timestamp
                ))
                found_any_contact = True
            except Exception:
                pass

        # D=1: If no email or phone in card, follow profile link (limit by budget)
        if (not found_email and not found_phone) and name_node is not None and (self._d1_budget is not None and self._d1_budget > 0):
            # Find profile link: anchor around name or any anchor within card that is not mailto/tel
            a = name_node.parent if name_node and name_node.parent and name_node.parent.tag == 'a' else name_node.css_first('a')
            profile_href = a.attrs.get('href') if a and a.attrs else None
            if not profile_href:
                # fallback: first anchor in card not mailto/tel
                for cand in person_node.css('a'):
                    if not cand or not cand.attrs:
                        continue
                    href = cand.attrs.get('href') or ''
                    if href and (not href.startswith('mailto:')) and (not href.startswith('tel:')):
                        profile_href = href
                        break
            if profile_href:
                try:
                    abs_url = urljoin(source_url, profile_href)
                    self._d1_budget -= 1
                    with httpx.Client(timeout=8.0, follow_redirects=True) as c:
                        r = c.get(abs_url)
                        if r.status_code < 400 and 'text/html' in (r.headers.get('Content-Type','').lower()):
                            bio_contacts = self.extract_from_static_html(r.text, abs_url)
                            # choose the first matching by name
                            for bc in bio_contacts:
                                if bc.person_name.lower() == person_name.lower():
                                    contacts.append(bc)
                                    break
                except Exception:
                    pass

        return contacts

    def extract_with_playwright(self, url: str, timeout_ms: int = 15000) -> List[Contact]:
        """Extract contacts directly from a headless DOM session.
        - Uses the same selectors as static, scoped within card roots
        - Sanitizes mailto parameters and falls back to text
        - Limited D=1 follow-ups to profiles (≤5 per listing)
        """
        out: List[Contact] = []
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                        '--disable-extensions',
                        '--disable-plugins',
                        '--no-first-run',
                        '--disable-default-apps',
                        '--disable-background-timer-throttling',
                    ],
                )
                context = browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
                page = context.new_page()

                # Time budget for fast DOM sweep (includes goto/wait)
                start_t = time.monotonic()
                budget_s = 8.0

                page.goto(url, wait_until='load', timeout=timeout_ms)
                try:
                    page.wait_for_selector("a[href^='mailto'], a[href^='tel']", timeout=2000)
                except Exception:
                    try:
                        page.wait_for_selector("section, .team, [class*=team], [class*=member], article", timeout=2000)
                    except Exception:
                        pass
                page.wait_for_timeout(200)

                company_name = self._extract_company_name_playwright(page, url)
                try:
                    path_low = urlparse(url).path.lower()
                except Exception:
                    path_low = ''
                is_listing_url = any(x in path_low for x in ("/team", "/our-team", "/people", "/leadership", "/management"))
                site_domain = urlparse(url).netloc.lower().replace('www.', '')
                allow_free_env = os.getenv('EGC_ALLOW_FREE_EMAIL', '0') == '1'
                d1_budget = 5

                # -------------------------------
                # Fast sweep: global mailto/tel first
                # -------------------------------
                try:
                    email_anchors = page.query_selector_all("a[href^='mailto']")
                except Exception:
                    email_anchors = []
                try:
                    phone_anchors = page.query_selector_all("a[href^='tel']")
                except Exception:
                    phone_anchors = []

                def _clean_name(txt: Optional[str]) -> Optional[str]:
                    if not txt:
                        return None
                    name = re.sub(r'^(Dr\.|Mr\.|Ms\.|Mrs\.)\s+', '', txt.strip())
                    return name if self._is_valid_person_name(name) else None

                # Emails
                for a in email_anchors:
                    # Budget guard
                    if (time.monotonic() - start_t) > budget_s:
                        break
                    try:
                        href = (a.get_attribute('href') or '').strip()
                        txt = (a.text_content() or '').strip()
                        email = self._sanitize_mailto(href, txt) or self._deobfuscate_email(href) or self._deobfuscate_email(txt)
                        if not email:
                            continue
                        email = email.lower()

                        # Find name near anchor first (to allow cross-domain emails when confidently attributed)
                        name = None
                        role = None
                        container = None
                        try:
                            container = a.query_selector("xpath=ancestor::li[contains(@class, 'list-item')][1]")
                        except Exception:
                            container = None
                        if container:
                            try:
                                name_el = container.query_selector("h2, h3, h4, .list-item-content__title")
                                name = _clean_name(name_el.text_content() if name_el else None)
                            except Exception:
                                name = None
                            # title within container
                            if name:
                                for sel in self.title_selectors:
                                    try:
                                        t_el = container.query_selector(sel)
                                        t_val = (t_el.text_content() or '').strip() if t_el else ''
                                        if t_val:
                                            cand_role = self._normalize_role_title(t_val)
                                            # Guard: ignore role if it duplicates the name (stubbed containers may return heading text)
                                            if cand_role and cand_role.strip().lower() != (name or '').strip().lower():
                                                role = cand_role
                                                break
                                    except Exception:
                                        continue
                        if not name:
                            # Try nearest previous heading
                            prev = None
                            for xp in ("xpath=preceding::h2[1]", "xpath=preceding::h3[1]", "xpath=preceding::h4[1]"):
                                try:
                                    prev = a.query_selector(xp)
                                    if prev:
                                        nm = _clean_name(prev.text_content())
                                        if nm:
                                            name = nm
                                            break
                                except Exception:
                                    continue

                        # Domain policy: accept if domain matches OR we have a valid person name nearby
                        edom = email.split('@')[-1]
                        domain_ok = (
                            edom.endswith(site_domain)
                            or self._email_domain_matches_site(edom, site_domain)
                            or (allow_free_env and (edom in self.free_email_domains))
                            or bool(name)
                        )
                        if not domain_ok:
                            continue

                        if not name:
                            continue
                        if not role and is_listing_url:
                            role = "Unknown"

                        ev = self.evidence_builder.create_evidence_playwright(
                            source_url=url,
                            selector="a[href*='mailto:']",
                            page=page,
                            element=a,
                            verbatim_text=txt or email,
                        )
                        out.append(Contact(company=company_name, person_name=name, role_title=role or 'Unknown', contact_type=ContactType.EMAIL, contact_value=email, evidence=ev, captured_at=ev.timestamp))
                    except Exception:
                        continue

                # Phones
                for a in phone_anchors:
                    if (time.monotonic() - start_t) > budget_s:
                        break
                    try:
                        href = (a.get_attribute('href') or '').strip()
                        raw = href[4:] if href.lower().startswith('tel:') else href
                        digits = re.sub(r"\D", "", raw)
                        if len(digits) == 11 and digits.startswith('1'):
                            digits = digits[1:]
                        if not (10 <= len(digits) <= 15):
                            continue
                        # Find name near anchor
                        name = None
                        role = None
                        container = None
                        try:
                            container = a.query_selector("xpath=ancestor::li[contains(@class, 'list-item')][1]")
                        except Exception:
                            container = None
                        if container:
                            try:
                                name_el = container.query_selector("h2, h3, h4, .list-item-content__title")
                                name = _clean_name(name_el.text_content() if name_el else None)
                            except Exception:
                                name = None
                            if name:
                                for sel in self.title_selectors:
                                    try:
                                        t_el = container.query_selector(sel)
                                        t_val = (t_el.text_content() or '').strip() if t_el else ''
                                        if t_val:
                                            cand_role = self._normalize_role_title(t_val)
                                            if cand_role and cand_role.strip().lower() != (name or '').strip().lower():
                                                role = cand_role
                                                break
                                    except Exception:
                                        continue
                        if not name:
                            prev = None
                            for xp in ("xpath=preceding::h2[1]", "xpath=preceding::h3[1]", "xpath=preceding::h4[1]"):
                                try:
                                    prev = a.query_selector(xp)
                                    if prev:
                                        nm = _clean_name(prev.text_content())
                                        if nm:
                                            name = nm
                                            break
                                except Exception:
                                    continue
                        if not name:
                            continue
                        if not role and is_listing_url:
                            role = "Unknown"

                        ev = self.evidence_builder.create_evidence_playwright(
                            source_url=url,
                            selector="a[href*='tel:']",
                            page=page,
                            element=a,
                            verbatim_text=(a.text_content() or raw),
                        )
                        out.append(Contact(company=company_name, person_name=name, role_title=role or 'Unknown', contact_type=ContactType.PHONE, contact_value=digits, evidence=ev, captured_at=ev.timestamp))
                    except Exception:
                        continue

                # If fast sweep produced results or budget exceeded, finish early
                if out or (time.monotonic() - start_t) > budget_s:
                    browser.close()
                    return self._postprocess_and_dedup(out)

                card_selectors = [
                    '.entry-team-info',
                    '.elementor-team-member', '.team-member', '.team-member__content', '.elementor-widget-team-member',
                    '.our-team', '.team-grid article', "[class*='team-member']", "[class*='member-card']",
                    '.person', '.profile', 'article.profile', 'section.team-member',
                    '.sqs-block-content'
                ]
                for sel in card_selectors:
                    for el in page.locator(sel).all():
                        name = self._extract_person_name_playwright(el)
                        if not name or not self._is_valid_person_name(name):
                            continue
                        title = self._extract_person_title_playwright(el) or ('Unknown' if is_listing_url else None)
                        found_email = False
                        found_phone = False

                        # EMAIL via anchors
                        for a in el.locator("a[href*='mailto:']").all():
                            href = (a.get_attribute('href') or '').strip()
                            txt = (a.text_content() or '').strip()
                            email = self._sanitize_mailto(href, txt) or self._deobfuscate_email(href) or self._deobfuscate_email(txt)
                            if not email:
                                continue
                            email = email.lower()
                            edom = (email.split('@')[-1] or '').lower()
                            brand_match = edom.endswith(site_domain) or self._email_domain_matches_site(edom, site_domain)
                            free_ok = (allow_free_env and (edom in self.free_email_domains))
                            accept = False
                            if brand_match or free_ok:
                                accept = True
                            else:
                                page_count = self._xdom_page_domain_count(edom)
                                site_count = self._xdom_site_domain_count(edom)
                                in_footer = self._xdom_domain_in_footer_or_contacts(edom)
                                score, sigs = self._xdom_score_static(
                                    edom,
                                    in_person_card=True,
                                    has_title=bool(title and title.strip() and (title.lower() != 'unknown')),
                                    from_mailto=True,
                                    has_phone=self._element_has_phone_hint_pw(el),
                                    has_vcard=self._element_has_vcf_hint_pw(el),
                                    has_show_trigger=self._element_has_show_email_trigger_pw(el),
                                    page_domain_count=int(page_count),
                                    site_domain_count=int(site_count),
                                    domain_in_footer=bool(in_footer),
                                    negative_zone=self._is_negative_zone_path(url),
                                )
                                if score >= self._XDOM_THRESHOLD:
                                    strong_ok, missing = self._xdom_min_confirmation(
                                        has_phone=self._element_has_phone_hint_pw(el),
                                        has_vcard=self._element_has_vcf_hint_pw(el),
                                        page_repeat=int(page_count),
                                        in_footer=bool(in_footer),
                                        site_repeat=int(site_count),
                                    )
                                    if strong_ok:
                                        accept = True
                                        self._xdom_log_accept(email=email, domain=edom, source_url=url, score=score, signals=sigs)
                                    else:
                                        print(f"cross-domain: недостаточно подтверждающих сигналов (email={email}, domain={edom}). Нет: {', '.join(missing)}")
                                else:
                                    print(f"cross-domain: score ниже порога (score={score}, threshold={self._XDOM_THRESHOLD}, domain={edom})")
                            if not accept:
                                continue
                            ev = self.evidence_builder.create_evidence_playwright(
                                source_url=url,
                                selector="a[href*='mailto:']",
                                page=page,
                                element=a,
                                verbatim_text=txt or email,
                            )
                            out.append(Contact(company=company_name, person_name=name, role_title=title or 'Unknown', contact_type=ContactType.EMAIL, contact_value=email, evidence=ev, captured_at=ev.timestamp))
                            found_email = True
                            break

                        # EMAIL via aria/title
                        if not found_email:
                            for a in el.locator('a').all():
                                lab = ((a.get_attribute('aria-label') or a.get_attribute('title') or '') or '').lower()
                                if 'email' not in lab:
                                    continue
                                txt = (a.text_content() or '').strip()
                                cand = None
                                if '@' in txt:
                                    m = self.email_pattern.search(txt.lower())
                                    cand = m.group(0) if m else None
                                if not cand:
                                    m2 = self.email_pattern.search((el.text_content() or '').lower())
                                    cand = m2.group(0) if m2 else None
                                if cand:
                                    edom = (cand.split('@')[-1] or '').lower()
                                    brand_match = edom.endswith(site_domain) or self._email_domain_matches_site(edom, site_domain)
                                    free_ok = (allow_free_env and (edom in self.free_email_domains))
                                    accept = False
                                    if brand_match or free_ok:
                                        accept = True
                                    else:
                                        page_count = self._xdom_page_domain_count(edom)
                                        site_count = self._xdom_site_domain_count(edom)
                                        in_footer = self._xdom_domain_in_footer_or_contacts(edom)
                                        score, sigs = self._xdom_score_static(
                                            edom,
                                            in_person_card=True,
                                            has_title=bool(title and title.strip() and (title.lower() != 'unknown')),
                                            from_mailto=False,
                                            has_phone=self._element_has_phone_hint_pw(el),
                                            has_vcard=self._element_has_vcf_hint_pw(el),
                                            has_show_trigger=self._element_has_show_email_trigger_pw(el),
                                            page_domain_count=int(page_count),
                                            site_domain_count=int(site_count),
                                            domain_in_footer=bool(in_footer),
                                            negative_zone=self._is_negative_zone_path(url),
                                        )
                                        if score >= self._XDOM_THRESHOLD:
                                            strong_ok, missing = self._xdom_min_confirmation(
                                                has_phone=self._element_has_phone_hint_pw(el),
                                                has_vcard=self._element_has_vcf_hint_pw(el),
                                                page_repeat=int(page_count),
                                                in_footer=bool(in_footer),
                                                site_repeat=int(site_count),
                                            )
                                            if strong_ok:
                                                accept = True
                                                self._xdom_log_accept(email=cand, domain=edom, source_url=url, score=score, signals=sigs)
                                            else:
                                                print(f"cross-domain: недостаточно подтверждающих сигналов (email={cand}, domain={edom}). Нет: {', '.join(missing)}")
                                        else:
                                            print(f"cross-domain: score ниже порога (score={score}, threshold={self._XDOM_THRESHOLD}, domain={edom})")
                                    if not accept:
                                        continue
                                    ev = self.evidence_builder.create_evidence_playwright(
                                        source_url=url,
                                        selector="a[aria|title*=email]",
                                        page=page,
                                        element=a,
                                        verbatim_text=txt or cand,
                                    )
                                    out.append(Contact(company=company_name, person_name=name, role_title=title or 'Unknown', contact_type=ContactType.EMAIL, contact_value=cand.lower(), evidence=ev, captured_at=ev.timestamp))
                                    found_email = True
                                    break

                        # EMAIL via icon envelope
                        if not found_email:
                            for a in el.locator("a:has(i[class*='envelope'])").all():
                                txt = (a.text_content() or '').strip()
                                m = self.email_pattern.search(txt.lower())
                                if not m:
                                    continue
                                cand = m.group(0)
                                edom = (cand.split('@')[-1] or '').lower()
                                brand_match = edom.endswith(site_domain) or self._email_domain_matches_site(edom, site_domain)
                                free_ok = (allow_free_env and (edom in self.free_email_domains))
                                accept = False
                                if brand_match or free_ok:
                                    accept = True
                                else:
                                    page_count = self._xdom_page_domain_count(edom)
                                    site_count = self._xdom_site_domain_count(edom)
                                    in_footer = self._xdom_domain_in_footer_or_contacts(edom)
                                    score, sigs = self._xdom_score_static(
                                        edom,
                                        in_person_card=True,
                                        has_title=bool(title and title.strip() and (title.lower() != 'unknown')),
                                        from_mailto=False,
                                        has_phone=self._element_has_phone_hint_pw(el),
                                        has_vcard=self._element_has_vcf_hint_pw(el),
                                        has_show_trigger=self._element_has_show_email_trigger_pw(el),
                                        page_domain_count=int(page_count),
                                        site_domain_count=int(site_count),
                                        domain_in_footer=bool(in_footer),
                                        negative_zone=self._is_negative_zone_path(url),
                                    )
                                    if score >= self._XDOM_THRESHOLD:
                                        strong_ok, missing = self._xdom_min_confirmation(
                                            has_phone=self._element_has_phone_hint_pw(el),
                                            has_vcard=self._element_has_vcf_hint_pw(el),
                                            page_repeat=int(page_count),
                                            in_footer=bool(in_footer),
                                            site_repeat=int(site_count),
                                        )
                                        if strong_ok:
                                            accept = True
                                            self._xdom_log_accept(email=cand, domain=edom, source_url=url, score=score, signals=sigs)
                                        else:
                                            print(f"cross-domain: недостаточно подтверждающих сигналов (email={cand}, domain={edom}). Нет: {', '.join(missing)}")
                                    else:
                                        print(f"cross-domain: score ниже порога (score={score}, threshold={self._XDOM_THRESHOLD}, domain={edom})")
                                if not accept:
                                    continue
                                ev = self.evidence_builder.create_evidence_playwright(
                                    source_url=url,
                                    selector="i[class*='envelope']~a",
                                    page=page,
                                    element=a,
                                    verbatim_text=txt or cand,
                                )
                                out.append(Contact(company=company_name, person_name=name, role_title=title or 'Unknown', contact_type=ContactType.EMAIL, contact_value=cand.lower(), evidence=ev, captured_at=ev.timestamp))
                                found_email = True
                                break

                        # EMAIL via text
                        if not found_email:
                            card_text = (el.text_content() or '')
                            m = self.email_pattern.search(card_text.lower())
                            if m:
                                cand = m.group(0)
                                edom = (cand.split('@')[-1] or '').lower()
                                brand_match = edom.endswith(site_domain) or self._email_domain_matches_site(edom, site_domain)
                                free_ok = (allow_free_env and (edom in self.free_email_domains))
                                accept = False
                                if brand_match or free_ok:
                                    accept = True
                                else:
                                    page_count = self._xdom_page_domain_count(edom)
                                    site_count = self._xdom_site_domain_count(edom)
                                    in_footer = self._xdom_domain_in_footer_or_contacts(edom)
                                    score, sigs = self._xdom_score_static(
                                        edom,
                                        in_person_card=True,
                                        has_title=bool(title and title.strip() and (title.lower() != 'unknown')),
                                        from_mailto=False,
                                        has_phone=self._element_has_phone_hint_pw(el),
                                        has_vcard=self._element_has_vcf_hint_pw(el),
                                        has_show_trigger=self._element_has_show_email_trigger_pw(el),
                                        page_domain_count=int(page_count),
                                        site_domain_count=int(site_count),
                                        domain_in_footer=bool(in_footer),
                                        negative_zone=self._is_negative_zone_path(url),
                                    )
                                    if score >= self._XDOM_THRESHOLD:
                                        strong_ok, missing = self._xdom_min_confirmation(
                                            has_phone=self._element_has_phone_hint_pw(el),
                                            has_vcard=self._element_has_vcf_hint_pw(el),
                                            page_repeat=int(page_count),
                                            in_footer=bool(in_footer),
                                            site_repeat=int(site_count),
                                        )
                                        if strong_ok:
                                            accept = True
                                            self._xdom_log_accept(email=cand, domain=edom, source_url=url, score=score, signals=sigs)
                                        else:
                                            print(f"cross-domain: недостаточно подтверждающих сигналов (email={cand}, domain={edom}). Нет: {', '.join(missing)}")
                                    else:
                                        print(f"cross-domain: score ниже порога (score={score}, threshold={self._XDOM_THRESHOLD}, domain={edom})")
                                if not accept:
                                    pass
                                else:
                                    ev = self.evidence_builder.create_evidence_playwright(
                                        source_url=url,
                                        selector=":text-email(card)",
                                        page=page,
                                        element=el,
                                        verbatim_text=(card_text[:200] if card_text else cand),
                                    )
                                    out.append(Contact(company=company_name, person_name=name, role_title=title or 'Unknown', contact_type=ContactType.EMAIL, contact_value=cand.lower(), evidence=ev, captured_at=ev.timestamp))
                                    found_email = True

                        # PHONE via anchors
                        for a in el.locator("a[href*='tel:']").all():
                            href = a.get_attribute('href') or ''
                            raw = href[4:] if href.startswith('tel:') else href
                            digits = re.sub(r"\D", "", raw)
                            if 10 <= len(digits) <= 15:
                                ev = self.evidence_builder.create_evidence_playwright(
                                    source_url=url,
                                    selector="a[href*='tel:']",
                                    page=page,
                                    element=a,
                                    verbatim_text=(a.text_content() or raw),
                                )
                                out.append(Contact(company=company_name, person_name=name, role_title=title or 'Unknown', contact_type=ContactType.PHONE, contact_value=digits, evidence=ev, captured_at=ev.timestamp))
                                found_phone = True
                                break

                        # PHONE via aria/title or icons
                        if not found_phone:
                            for a in el.locator('a').all():
                                lab = ((a.get_attribute('aria-label') or a.get_attribute('title') or '') or '').lower()
                                if 'phone' in lab or 'tel' in lab:
                                    text_block = (el.text_content() or '')
                                    for m in self.phone_pattern.findall(text_block):
                                        raw = m if isinstance(m, str) else ''.join(m)
                                        digits = re.sub(r"\D", "", raw)
                                        if 10 <= len(digits) <= 15 and not re.match(r'^(19|20)\d{6,8}$', digits):
                                            ev = self.evidence_builder.create_evidence_playwright(
                                                source_url=url,
                                                selector="a[aria|title*=phone]",
                                                page=page,
                                                element=a,
                                                verbatim_text=raw,
                                            )
                                            out.append(Contact(company=company_name, person_name=name, role_title=title or 'Unknown', contact_type=ContactType.PHONE, contact_value=digits, evidence=ev, captured_at=ev.timestamp))
                                            found_phone = True
                                            break
                                if found_phone:
                                    break
                        if not found_phone:
                            for a in el.locator("a:has(i[class*='phone']), a:has(i[class*='tel'])").all():
                                text_block = (el.text_content() or '')
                                for m in self.phone_pattern.findall(text_block):
                                    raw = m if isinstance(m, str) else ''.join(m)
                                    digits = re.sub(r"\D", "", raw)
                                    if 10 <= len(digits) <= 15 and not re.match(r'^(19|20)\d{6,8}$', digits):
                                        ev = self.evidence_builder.create_evidence_playwright(
                                            source_url=url,
                                            selector="i[class*='phone|tel']~a",
                                            page=page,
                                            element=a,
                                            verbatim_text=raw,
                                        )
                                        out.append(Contact(company=company_name, person_name=name, role_title=title or 'Unknown', contact_type=ContactType.PHONE, contact_value=digits, evidence=ev, captured_at=ev.timestamp))
                                        found_phone = True
                                        break
                                if found_phone:
                                    break

                        # PHONE via text
                        if not found_phone:
                            text_block = (el.text_content() or '')
                            for m in self.phone_pattern.findall(text_block):
                                raw = m if isinstance(m, str) else ''.join(m)
                                digits = re.sub(r"\D", "", raw)
                                if 10 <= len(digits) <= 15 and not re.match(r'^(19|20)\d{6,8}$', digits):
                                    ev = self.evidence_builder.create_evidence_playwright(
                                        source_url=url,
                                        selector=":text-phone(card)",
                                        page=page,
                                        element=el,
                                        verbatim_text=raw,
                                    )
                                    out.append(Contact(company=company_name, person_name=name, role_title=title or 'Unknown', contact_type=ContactType.PHONE, contact_value=digits, evidence=ev, captured_at=ev.timestamp))
                                    found_phone = True
                                    break

                        # D=1 follow-up when no email/phone
                        if (not found_email and not found_phone) and d1_budget > 0:
                            prof_href = None
                            for a in el.locator('a').all():
                                href = a.get_attribute('href') or ''
                                if not href or href.startswith('mailto:') or href.startswith('tel:'):
                                    continue
                                prof_href = href
                                break
                            if prof_href:
                                try:
                                    abs_url = urljoin(url, prof_href)
                                    d1_budget -= 1
                                    with httpx.Client(timeout=8.0, follow_redirects=True) as c:
                                        r = c.get(abs_url)
                                        if r.status_code < 400 and 'text/html' in (r.headers.get('Content-Type','').lower()):
                                            bio_contacts = self.extract_from_static_html(r.text, abs_url)
                                            for bc in bio_contacts:
                                                if bc.person_name.lower() == name.lower():
                                                    out.append(bc)
                                                    break
                                except Exception:
                                    pass

                browser.close()
        except Exception:
            pass
        return self._postprocess_and_dedup(out)

    # Testing hook: run fast sweep against a provided Page-like object (already loaded)
    def _fast_sweep_test_hook(self, page: Page, url: str) -> List[Contact]:  # pragma: no cover - exercised via unit tests
        out: List[Contact] = []
        try:
            company_name = self._extract_company_name_playwright(page, url)
            try:
                path_low = urlparse(url).path.lower()
            except Exception:
                path_low = ''
            is_listing_url = any(x in path_low for x in ("/team", "/our-team", "/people", "/leadership", "/management"))
            site_domain = urlparse(url).netloc.lower().replace('www.', '')
            allow_free_env = os.getenv('EGC_ALLOW_FREE_EMAIL', '0') == '1'

            try:
                email_anchors = page.query_selector_all("a[href^='mailto']")
            except Exception:
                email_anchors = []
            try:
                phone_anchors = page.query_selector_all("a[href^='tel']")
            except Exception:
                phone_anchors = []

        # Prepare per-page cross-domain context for fast sweep
            try:
                self._xdom_prepare_context_playwright(page, url)
            except Exception:
                self._page_mailto_counts = Counter()
                self._footer_contact_text = ""
                self._xdom_reset_or_update_site_counts(url)

            def _clean_name(txt: Optional[str]) -> Optional[str]:
                if not txt:
                    return None
                name = re.sub(r'^(Dr\.|Mr\.|Ms\.|Mrs\.)\s+', '', txt.strip())
                return name if self._is_valid_person_name(name) else None

            for a in email_anchors:
                try:
                    href = (a.get_attribute('href') or '').strip()
                    txt = (a.text_content() or '').strip()
                    email = self._sanitize_mailto(href, txt) or self._deobfuscate_email(href) or self._deobfuscate_email(txt)
                    if not email:
                        continue
                    email = email.lower()
                    name = None
                    role = None
                    container = None
                    try:
                        container = a.query_selector("xpath=ancestor::li[contains(@class, 'list-item')][1]")
                    except Exception:
                        container = None
                    if container:
                        try:
                            name_el = container.query_selector("h2, h3, h4, .list-item-content__title")
                            name = _clean_name(name_el.text_content() if name_el else None)
                        except Exception:
                            name = None
                        if name:
                            for sel in self.title_selectors:
                                try:
                                    t_el = container.query_selector(sel)
                                    t_val = (t_el.text_content() or '').strip() if t_el else ''
                                    if t_val:
                                        cand_role = self._normalize_role_title(t_val)
                                        if cand_role and cand_role.strip().lower() != (name or '').strip().lower():
                                            role = cand_role
                                            break
                                except Exception:
                                    continue
                    if not name:
                        for xp in ("xpath=preceding::h2[1]", "xpath=preceding::h3[1]", "xpath=preceding::h4[1]"):
                            try:
                                prev = a.query_selector(xp)
                                if prev:
                                    nm = _clean_name(prev.text_content())
                                    if nm:
                                        name = nm
                                        break
                            except Exception:
                                continue
                    # Domain policy: accept brand OR score-based cross-domain
                    edom = (email.split('@')[-1] or '').lower()
                    brand_match = edom.endswith(site_domain) or self._email_domain_matches_site(edom, site_domain)
                    free_ok = (allow_free_env and (edom in self.free_email_domains))
                    accept = False
                    if brand_match or free_ok:
                        accept = True
                    else:
                        # Signals: treat as person card if we found a nearby name
                        page_count = self._xdom_page_domain_count(edom)
                        in_footer = self._xdom_domain_in_footer_or_contacts(edom)
                        has_phone_hint = False
                        has_vcf_hint = False
                        has_show_trigger = False
                        try:
                            container_txt = (container.text_content() or '') if container else ''
                            has_show_trigger = bool(self._show_email_re.search(container_txt.lower())) if container_txt else False
                            if container:
                                try:
                                    has_phone_hint = container.query_selector("a[href*='tel:']") is not None
                                except Exception:
                                    has_phone_hint = False
                                try:
                                    has_vcf_hint = container.query_selector("a[href$='.vcf']") is not None
                                except Exception:
                                    has_vcf_hint = False
                        except Exception:
                            pass
                        score, sigs = self._xdom_score_static(
                            edom,
                            in_person_card=bool(name),
                            has_title=bool(role and role.strip()),
                            from_mailto=True,
                            has_phone=bool(has_phone_hint),
                            has_vcard=bool(has_vcf_hint),
                            has_show_trigger=bool(has_show_trigger),
                            page_domain_count=int(page_count),
                            site_domain_count=int(self._xdom_site_domain_count(edom)),
                            domain_in_footer=bool(in_footer),
                            negative_zone=self._is_negative_zone_path(url),
                        )
                        if score >= self._XDOM_THRESHOLD:
                            strong_ok, missing = self._xdom_min_confirmation(
                                has_phone=bool(has_phone_hint),
                                has_vcard=bool(has_vcf_hint),
                                page_repeat=int(page_count),
                                in_footer=bool(in_footer),
                                site_repeat=int(self._xdom_site_domain_count(edom)),
                            )
                            if strong_ok:
                                accept = True
                                self._xdom_log_accept(email=email, domain=edom, source_url=url, score=score, signals=sigs)
                            else:
                                print(f"cross-domain: недостаточно подтверждающих сигналов (email={email}, domain={edom}). Нет: {', '.join(missing)}")
                        else:
                            print(f"cross-domain: score ниже порога (score={score}, threshold={self._XDOM_THRESHOLD}, domain={edom})")
                    if not accept:
                        continue
                    if not name:
                        continue
                    if not role and is_listing_url:
                        role = "Unknown"
                    ev = self.evidence_builder.create_evidence_playwright(
                        source_url=url,
                        selector="a[href*='mailto:']",
                        page=page,
                        element=a,
                        verbatim_text=txt or email,
                    )
                    out.append(Contact(company=company_name, person_name=name, role_title=role or 'Unknown', contact_type=ContactType.EMAIL, contact_value=email, evidence=ev, captured_at=ev.timestamp))
                except Exception:
                    continue

            for a in phone_anchors:
                try:
                    href = (a.get_attribute('href') or '').strip()
                    raw = href[4:] if href.lower().startswith('tel:') else href
                    digits = re.sub(r"\D", "", raw)
                    if len(digits) == 11 and digits.startswith('1'):
                        digits = digits[1:]
                    if not (10 <= len(digits) <= 15):
                        continue
                    name = None
                    role = None
                    container = None
                    try:
                        container = a.query_selector("xpath=ancestor::li[contains(@class, 'list-item')][1]")
                    except Exception:
                        container = None
                    if container:
                        try:
                            name_el = container.query_selector("h2, h3, h4, .list-item-content__title")
                            name = _clean_name(name_el.text_content() if name_el else None)
                        except Exception:
                            name = None
                        if name:
                            for sel in self.title_selectors:
                                try:
                                    t_el = container.query_selector(sel)
                                    t_val = (t_el.text_content() or '').strip() if t_el else ''
                                    if t_val:
                                        cand_role = self._normalize_role_title(t_val)
                                        if cand_role and cand_role.strip().lower() != (name or '').strip().lower():
                                            role = cand_role
                                            break
                                except Exception:
                                    continue
                    if not name:
                        for xp in ("xpath=preceding::h2[1]", "xpath=preceding::h3[1]", "xpath=preceding::h4[1]"):
                            try:
                                prev = a.query_selector(xp)
                                if prev:
                                    nm = _clean_name(prev.text_content())
                                    if nm:
                                        name = nm
                                        break
                            except Exception:
                                continue
                    if not name:
                        continue
                    if not role and is_listing_url:
                        role = "Unknown"
                    ev = self.evidence_builder.create_evidence_playwright(
                        source_url=url,
                        selector="a[href*='tel:']",
                        page=page,
                        element=a,
                        verbatim_text=(a.text_content() or raw),
                    )
                    out.append(Contact(company=company_name, person_name=name, role_title=role or 'Unknown', contact_type=ContactType.PHONE, contact_value=digits, evidence=ev, captured_at=ev.timestamp))
                except Exception:
                    continue

            return self._postprocess_and_dedup(out)
        except Exception:
            return []

    def _xdom_prepare_context_playwright(self, page: Page, source_url: str) -> None:
        """Populate domain counts and footer/contact text from a Playwright Page."""
        counts: Counter[str] = Counter()
        try:
            anchors = page.query_selector_all("a[href^='mailto']")
        except Exception:
            anchors = []
        for a in anchors or []:
            try:
                href = (a.get_attribute('href') or '').strip()
                txt = (a.text_content() or '').strip()
                email = self._sanitize_mailto(href, txt) or self._deobfuscate_email(href) or self._deobfuscate_email(txt)
                if not email or '@' not in email:
                    continue
                edom = email.split('@')[-1].lower()
                counts[edom] += 1
            except Exception:
                continue
        parts: List[str] = []
        try:
            for sel in ['footer', 'address', '.contact', '.contacts', '.contact-info', '.contact-us', "[class*='contact']"]:
                try:
                    for el in page.locator(sel).all():
                        t = (el.text_content() or '').strip()
                        if t:
                            parts.append(t)
                except Exception:
                    continue
        except Exception:
            pass
        self._page_mailto_counts = counts
        self._footer_contact_text = '\n'.join(parts).lower()
        self._xdom_reset_or_update_site_counts(source_url)

    def _element_has_show_email_trigger_pw(self, el: Locator) -> bool:
        try:
            txt = (el.text_content() or '').lower()
            if self._show_email_re.search(txt):
                return True
            # Also check visible button/anchor descendants
            try:
                nodes = el.locator('a, button, span, div').all()
                for n in nodes:
                    t = (n.text_content() or '').lower()
                    if t and self._show_email_re.search(t):
                        return True
            except Exception:
                pass
        except Exception:
            pass
        return False

    def _element_has_phone_hint_pw(self, el: Locator) -> bool:
        try:
            try:
                if el.locator("a[href*='tel:']").count() > 0:
                    return True
            except Exception:
                pass
            txt = (el.text_content() or '')
            return bool(self.phone_pattern.search(txt))
        except Exception:
            return False

    def _element_has_vcf_hint_pw(self, el: Locator) -> bool:
        try:
            return el.locator("a[href$='.vcf']").count() > 0
        except Exception:
            return False

    def _extract_person_contacts_playwright(
        self,
        person_element: Locator,
        page: Page,
        source_url: str,
        company_name: str,
        base_selector: str
    ) -> List[Contact]:
        """Extract all contacts for a single person from Playwright element."""
        contacts = []
        
        # Extract person name and title
        person_name = self._extract_person_name_playwright(person_element)
        person_title = self._extract_person_title_playwright(person_element)
        
        if not person_name or not person_title:
            return contacts
        
        # Cross-domain signals at card level
        has_phone_hint = self._element_has_phone_hint_pw(person_element)
        has_vcf_hint = self._element_has_vcf_hint_pw(person_element)
        has_show_trigger = self._element_has_show_email_trigger_pw(person_element)
        negative_zone = self._is_negative_zone_path(source_url)
        site_domain = urlparse(source_url).netloc.lower().replace('www.', '')
        allow_free_env = os.getenv('EGC_ALLOW_FREE_EMAIL', '0') == '1'
        
        # Extract emails
        emails = self._extract_emails_playwright(person_element)
        for email, email_element in emails:
            # Get verbatim text from the email element
            verbatim_text = email_element.text_content() or email
            
            # Domain acceptance with cross-domain scoring
            edom = (email.split('@')[-1] or '').lower()
            brand_match = edom.endswith(site_domain) or self._email_domain_matches_site(edom, site_domain)
            free_ok = (allow_free_env and (edom in self.free_email_domains))
            accept = False
            if brand_match or free_ok:
                accept = True
            else:
                page_count = self._xdom_page_domain_count(edom)
                site_count = self._xdom_site_domain_count(edom)
                in_footer = self._xdom_domain_in_footer_or_contacts(edom)
                score, sigs = self._xdom_score_static(
                    edom,
                    in_person_card=True,
                    has_title=bool(person_title and person_title.strip()),
                    from_mailto=True,
                    has_phone=bool(has_phone_hint),
                    has_vcard=bool(has_vcf_hint),
                    has_show_trigger=bool(has_show_trigger),
                    page_domain_count=int(page_count),
                    site_domain_count=int(site_count),
                    domain_in_footer=bool(in_footer),
                    negative_zone=bool(negative_zone),
                )
                if score >= self._XDOM_THRESHOLD:
                    strong_ok, missing = self._xdom_min_confirmation(
                        has_phone=bool(has_phone_hint),
                        has_vcard=bool(has_vcf_hint),
                        page_repeat=int(page_count),
                        in_footer=bool(in_footer),
                        site_repeat=int(site_count),
                    )
                    if strong_ok:
                        accept = True
                        self._xdom_log_accept(email=email, domain=edom, source_url=source_url, score=score, signals=sigs)
                    else:
                        print(f"cross-domain: недостаточно подтверждающих сигналов (email={email}, domain={edom}). Нет: {', '.join(missing)}")
                else:
                    print(f"cross-domain: score ниже порога (score={score}, threshold={self._XDOM_THRESHOLD}, domain={edom})")
            if not accept:
                continue
            
            evidence = self.evidence_builder.create_evidence_playwright(
                source_url=source_url,
                selector=f"{base_selector} a[href*='mailto:']",  # keep selector clean
                page=page,
                element=email_element,
                verbatim_text=verbatim_text
            )
            
            contacts.append(Contact(
                company=company_name,
                person_name=person_name,
                role_title=person_title or "Not specified",
                contact_type=ContactType.EMAIL,
                contact_value=email,
                evidence=evidence,
                captured_at=evidence.timestamp
            ))
        
        # Extract phones
        phones = self._extract_phones_playwright(person_element)
        for phone, phone_element in phones:
            verbatim_text = phone_element.text_content() or phone
            
            evidence = self.evidence_builder.create_evidence_playwright(
                source_url=source_url,
                selector=f"{base_selector} a[href*='tel:']",
                page=page,
                element=phone_element,
                verbatim_text=verbatim_text
            )
            normalized_phone = re.sub(r"\D", "", phone)
            try:
                contacts.append(Contact(
                    company=company_name,
                    person_name=person_name,
                    role_title=person_title or "Not specified",
                    contact_type=ContactType.PHONE,
                    contact_value=normalized_phone,
                    evidence=evidence,
                    captured_at=evidence.timestamp
                ))
            except Exception:
                continue
        
        return contacts
    
    def _extract_person_name_static(self, person_node: Node) -> Optional[str]:
        """Extract person name from static HTML node."""
        for selector in self.name_selectors:
            name_node = person_node.css_first(selector)
            if name_node and name_node.text():
                name = name_node.text().strip()
                # Basic cleaning
                name = re.sub(r'^(Dr\.|Mr\.|Ms\.|Mrs\.)\s+', '', name)
                if self._is_valid_person_name(name):
                    return name[:100]
        return None
    
    def _extract_person_title_static(self, person_node: Node) -> Optional[str]:
        """Extract person title/role from static HTML node."""
        for selector in self.title_selectors:
            title_node = person_node.css_first(selector)
            if title_node and title_node.text():
                title = title_node.text().strip()
                if self._is_valid_role_title(title):
                    return title[:200]
        return None
    
    def _extract_person_name_playwright(self, person_element: Locator) -> Optional[str]:
        """Extract person name from Playwright element."""
        for selector in self.name_selectors:
            try:
                name_element = person_element.locator(selector).first
                name = name_element.text_content()
                if name:
                    name = name.strip()
                    name = re.sub(r'^(Dr\.|Mr\.|Ms\.|Mrs\.)\s+', '', name)
                    if len(name) > 3:
                        return name[:100]
            except Exception:
                continue
        return None
    
    def _extract_person_title_playwright(self, person_element: Locator) -> Optional[str]:
        """Extract person title/role from Playwright element."""
        for selector in self.title_selectors:
            try:
                title_element = person_element.locator(selector).first
                title = title_element.text_content()
                if title:
                    title = title.strip()
                    if self._is_valid_role_title(title):
                        return title[:200]
            except Exception:
                continue
        return None
    
    def _extract_emails_static(self, person_node: Node) -> List[Tuple[str, str]]:
        """Extract emails from static HTML with their selectors (anchors only)."""
        emails = []
        
        # Look for mailto links only (avoid text scanning to reduce noise)
        mailto_links = person_node.css('a[href*="mailto:"]')
        for link in mailto_links:
            href = link.attrs.get('href', '')
            if href.startswith('mailto:'):
                email = href[7:]  # Remove 'mailto:'
                if self.email_pattern.match(email):
                    emails.append((email, 'a[href*="mailto:"]'))
        
        return emails
        return emails

    # -------------------------
    # Card root and proximity helpers
    # -------------------------
    def _get_card_root(self, node: Node) -> Node:
        """Prefer a stable root container for a person card to avoid cross-card leakage."""
        preferred_tokens = [
            'entry-team-info', 'team-info', 'team-card', 'member-card', 'profile', 'profile-card',
            'person', 'team-member', 'attorney', 'lawyer'
        ]
        cur = node
        max_up = 3
        while cur is not None and max_up >= 0:
            cls = (cur.attrs.get('class', '') or '').lower()
            tokens = set(re.split(r"[\s_-]+", cls)) if cls else set()
            if any(tok in tokens for tok in preferred_tokens) or cur.tag in ('article', 'section'):
                return cur
            cur = cur.parent
            max_up -= 1
        return node

    def _choose_card_root_by_repetition(self, node: Node) -> Node:
        """Ascend up to find a parent whose children form repeated, similar blocks.
        Falls back to token-based _get_card_root if no repetition is detected.
        """
        def signature(n: Node) -> str:
            cls = (n.attrs.get('class','') or '').lower()
            tag = n.tag or ''
            tokens = re.split(r"[\s_-]+", cls) if cls else []
            sig = tag + ':' + '|'.join(tokens[:2])
            return sig
        def direct_children(n: Node):
            ch = n.child
            while ch is not None:
                yield ch
                ch = ch.next
        cur = node
        for _ in range(3):
            if cur is None or cur.parent is None:
                break
            parent = cur.parent
            sig_counts: Dict[str, int] = {}
            for ch in direct_children(parent):
                if ch.tag in (None, 'script', 'style'):
                    continue
                s = signature(ch)
                sig_counts[s] = sig_counts.get(s, 0) + 1
            s_cur = signature(cur)
            if sig_counts.get(s_cur, 0) >= 3:
                return cur
            cur = parent
        return self._get_card_root(node)

    def _find_name_node_static(self, root: Node) -> Optional[Node]:
        for selector in self.name_selectors:
            n = root.css_first(selector)
            if n and n.text():
                txt = n.text().strip()
                if self._is_valid_person_name(txt):
                    return n
        return None

    def _text_from_name_node(self, n: Node) -> Optional[str]:
        if not n or not n.text():
            return None
        name = n.text().strip()
        name = re.sub(r'^(Dr\.|Mr\.|Ms\.|Mrs\.)\s+', '', name)
        return name if self._is_valid_person_name(name) else None

    def _ancestors(self, n: Node) -> List[Node]:
        res = []
        cur = n
        while cur is not None:
            res.append(cur)
            cur = cur.parent
        return res

    def _dom_distance(self, a: Node, b: Node) -> int:
        if not a or not b:
            return 1_000_000
        anc_a = self._ancestors(a)
        anc_b = self._ancestors(b)
        set_a = {id(x): i for i, x in enumerate(anc_a)}
        for j, nb in enumerate(anc_b):
            if id(nb) in set_a:
                i = set_a[id(nb)]
                return i + j
        return 1_000_000

    def _nearest_link(self, root: Node, name_node: Node, css_selector: str) -> Optional[Node]:
        links = root.css(css_selector)
        # If none in root, try typical links containers (within close siblings)
        if not links:
            links_container = self._find_links_container(root)
            if links_container is not None:
                links = links_container.css(css_selector)
        best = None
        best_d = 1_000_000
        for ln in links:
            d = self._dom_distance(name_node, ln)
            if d < best_d:
                best_d = d
                best = ln
        # Fallback: if distance metric failed to find a better one, pick the first link in scope
        if best is None and links:
            return links[0]
        return best

    def _extract_role_near_name_static(self, root: Node, name_node: Optional[Node]) -> Optional[str]:
        if name_node is None:
            return None
        # If name is inside a paragraph, try text after <br>
        parent = name_node.parent
        if parent is not None and parent.tag == 'p':
            raw_html = parent.html or ''
            parts = re.split(r'<br\s*/?>', raw_html, flags=re.IGNORECASE)
            if len(parts) >= 2:
                # Take the text after the first <br>
                after = HTMLParser(parts[1]).text().strip()
                if self._is_valid_role_title(after):
                    return after
        # Else try next sibling text within the same fusion-text container
        cont = root.css_first('.fusion-text') or root
        # find first p that contains the name node
        p_nodes = cont.css('p')
        target_idx = None
        for i, p in enumerate(p_nodes):
            if p is parent or (p.html and name_node.html and (name_node.html in p.html)):
                target_idx = i
                break
        if target_idx is not None and target_idx + 1 < len(p_nodes):
            cand = (p_nodes[target_idx + 1].text() or '').strip()
            if self._is_valid_role_title(cand):
                return cand
        return None

    def _find_links_container(self, root: Node) -> Optional[Node]:
        # Search inside root
        candidates = root.css(".eti-links, .links, .contact, .contacts, .actions, .icons, [class*='links']")
        if candidates:
            return candidates[0]
        # Try siblings
        if root.parent is not None:
            sib = root.parent.child
            while sib is not None:
                if sib is not root:
                    cls = (sib.attrs.get('class','') or '').lower()
                    if any(tok in cls for tok in ['eti-links','links','contact','contacts','actions','icons']):
                        return sib
                sib = sib.next
        return None

    def _fallback_repeating_cards(self, parser: HTMLParser, source_url: str, company_name: str) -> List[Contact]:
        contacts: List[Contact] = []
        # Candidate containers to scan
        containers = [
            parser.css_first('main') or parser.body,
            parser.css_first('section'),
            parser.css_first(".content, .container, .row, .grid, .team, .people, .staff"),
        ]
        containers = [c for c in containers if c is not None]
        seen_nodes = set()
        for cont in containers:
            # Collect direct children signatures and group by structure/class
            children = []
            ch = cont.child
            while ch is not None:
                if ch.tag not in (None, 'script', 'style', 'noscript'):
                    children.append(ch)
                ch = ch.next
            if len(children) < 3:
                continue
            def sig(n: Node) -> str:
                cls = (n.attrs.get('class','') or '').lower()
                tokens = re.split(r"[\s_-]+", cls) if cls else []
                return f"{n.tag}:{'|'.join(tokens[:2])}"
            groups: Dict[str, List[Node]] = {}
            for n in children:
                groups.setdefault(sig(n), []).append(n)
            # For any group with >=3 siblings, treat each as a potential card
            for nodes in groups.values():
                if len(nodes) < 3:
                    continue
                for node in nodes:
                    if id(node) in seen_nodes:
                        continue
                    seen_nodes.add(id(node))
                    person_contacts = self._extract_person_contacts_static(
                        node, source_url, company_name, f"fallback[{node.tag}]"
                    )
                    contacts.extend(person_contacts)
        return contacts

    # -------------------------
    # Validation & Dedup helpers
    # -------------------------
    def _is_valid_person_name(self, name: str) -> bool:
        if not name:
            return False
        # Exclude generic section headers
        if re.search(r"^(Our Team|Team|People|Staff|Contact|Contacts|News|Press)$", name, re.IGNORECASE):
            return False
        # Non-person stop-list
        stoplist = {
            'mailing address','branch hours','business services team','executive team',
            'support','department','services','contact us','resources'
        }
        if name.strip().lower() in stoplist:
            return False
        # Require at least two tokens; each must contain at least one letter (Unicode-aware)
        parts = [p for p in re.split(r"\s+", name.strip()) if p]
        if len(parts) < 2:
            return False
        def has_letter(tok: str) -> bool:
            return any(ch.isalpha() for ch in tok)
        if not all(has_letter(tok) for tok in parts[:3]):
            return False
        return True

    def _is_valid_role_title(self, title: str) -> bool:
        if not title or len(title) < 3:
            return False
        # Leadership/decision-maker leaning allowlist and admin blacklist
        blacklist = [
            'paralegal', 'legal administrator', 'legal administrative', 'assistant', 'accountant',
            'marketing', 'retired', 'intern', 'receptionist'
        ]
        low = title.lower().strip()
        # Stop-list of junk roles that should not be treated as meaningful titles
        stoplist = {'email', 'areas of focus:', 'coming soon', 'open seat'}
        if low in stoplist:
            return True  # allow creation but will be normalized to 'Unknown'
        if any(b in low for b in blacklist):
            return False
        return True

    def _normalize_role_title(self, title: Optional[str]) -> Optional[str]:
        if not title:
            return title
        low = title.strip().lower()
        stoplist = {'email', 'areas of focus:', 'coming soon', 'open seat'}
        if low in stoplist:
            return 'Unknown'
        return title

    def _postprocess_and_dedup(self, contacts: List[Contact]) -> List[Contact]:
        if not contacts:
            return []

        def norm_company(s: str) -> str:
            return (s or '').strip().lower()
        def norm_person(s: str) -> str:
            return (s or '').strip().lower()
        def norm_value(c: Contact) -> str:
            if c.contact_type.value == 'email':
                return (c.contact_value or '').strip().lower()
            if c.contact_type.value == 'phone':
                return re.sub(r"\D", "", c.contact_value or '')
            return (c.contact_value or '').strip().lower()
        def quality(c: Contact) -> tuple:
            sel = (c.evidence.selector_or_xpath or '').lower() if c.evidence else ''
            anchor_pref = 1 if ('mailto:' in sel or "a[href*='mailto:']" in sel or 'tel:' in sel or "a[href*='tel:']" in sel) else 0
            role_good = 1 if (c.role_title and c.role_title.strip().lower() != 'unknown') else 0
            return (anchor_pref, role_good)

        # First collapse exact duplicates based on (company, person, type, value)
        best_by_key: Dict[tuple, Contact] = {}
        for c in contacts:
            key = (norm_company(c.company), norm_person(c.person_name), c.contact_type.value, norm_value(c))
            prev = best_by_key.get(key)
            if prev is None or quality(c) > quality(prev):
                best_by_key[key] = c

        # Then enforce at most 1 email and 1 phone per person
        chosen: Dict[tuple, Dict[str, Contact]] = {}
        links_seen: Set[tuple] = set()
        out: List[Contact] = []
        for key, c in best_by_key.items():
            comp, person, ctype, val = key
            if ctype in ('email', 'phone'):
                kp = (comp, person)
                if kp not in chosen:
                    chosen[kp] = {}
                existing = chosen[kp].get(ctype)
                if existing is None or quality(c) > quality(existing):
                    chosen[kp][ctype] = c
            else:
                # links: dedupe exact value
                lkey = (comp, person, val)
                if lkey in links_seen:
                    continue
                links_seen.add(lkey)
                out.append(c)

        # Append the selected email/phone per person
        for kp, d in chosen.items():
            for ctype in ('email', 'phone'):
                if ctype in d:
                    out.append(d[ctype])

        return out
    
    def _extract_phones_static(self, person_node: Node) -> List[Tuple[str, str]]:
        """Extract phone numbers from static HTML with their selectors (anchors only)."""
        phones = []
        
        # Look for tel links only
        tel_links = person_node.css('a[href*="tel:"]')
        for link in tel_links:
            href = link.attrs.get('href', '')
            if href.startswith('tel:'):
                phone = href[4:]  # Remove 'tel:'
                phones.append((phone, 'a[href*="tel:"]'))
        
        return phones
    
    def _extract_emails_playwright(self, person_element: Locator) -> List[Tuple[str, Locator]]:
        """Extract emails from Playwright element with their locators."""
        emails = []
        
        # Look for mailto links
        try:
            mailto_links = person_element.locator('a[href*="mailto:"]').all()
            for link in mailto_links:
                href = link.get_attribute('href') or ''
                if href.startswith('mailto:'):
                    email = href[7:]
                    if self.email_pattern.match(email):
                        emails.append((email, link))
        except Exception:
            pass
        
        # Look for email patterns in text (create locator for text context)
        try:
            text_content = person_element.text_content() or ''
            found_emails = self.email_pattern.findall(text_content)
            for email in found_emails:
                if email not in [e[0] for e in emails]:
                    # Use the person element itself as context
                    emails.append((email, person_element))
        except Exception:
            pass
        
        return emails
    
    def _extract_phones_playwright(self, person_element: Locator) -> List[Tuple[str, Locator]]:
        """Extract phone numbers from Playwright element with their locators."""
        phones = []
        
        # Look for tel links
        try:
            tel_links = person_element.locator('a[href*="tel:"]').all()
            for link in tel_links:
                href = link.get_attribute('href') or ''
                if href.startswith('tel:'):
                    phone = href[4:]
                    phones.append((phone, link))
        except Exception:
            pass
        
        # Look for phone patterns in text
        try:
            text_content = person_element.text_content() or ''
            found_phones = self.phone_pattern.findall(text_content)
            for phone in found_phones:
                if phone not in [p[0] for p in phones]:
                    phones.append((phone, person_element))
        except Exception:
            pass
        
        return phones
    
    def _extract_fallback_contacts_static(
        self, 
        parser: HTMLParser, 
        source_url: str, 
        company_name: str
    ) -> List[Contact]:
        """
        Fallback extraction for pages without clear person containers.
        
        Looks for emails and phones anywhere on the page and tries to associate
        them with names found nearby.
        """
        contacts = []
        
        # Find all mailto links on the page
        mailto_links = parser.css('a[href*="mailto:"]')
        
        for link in mailto_links:
            href = link.attrs.get('href', '')
            if not href.startswith('mailto:'):
                continue
                
            email = href[7:]  # Remove 'mailto:'
            if not self.email_pattern.match(email):
                continue
            
            # Try to find associated name by looking at nearby text
            person_name = self._find_associated_name_static(link, parser)
            person_title = self._find_associated_title_static(link, parser)
            
            # Create evidence package
            evidence = self.evidence_builder.create_evidence_static(
                source_url=source_url,
                selector='a[href*="mailto:"]',
                node=link,
                verbatim_text=link.text() or email
            )
            
            # For PoC, skip fallback email if we cannot confidently attribute to a person with title
            if not person_name or not person_title:
                continue
            contacts.append(Contact(
                company=company_name,
                person_name=person_name,
                role_title=person_title,
                contact_type=ContactType.EMAIL,
                contact_value=email,
                evidence=evidence,
                captured_at=evidence.timestamp
            ))
        
        # Find phone numbers in tel links
        tel_links = parser.css('a[href*="tel:"]')
        
        for link in tel_links:
            href = link.attrs.get('href', '')
            if not href.startswith('tel:'):
                continue
                
            phone = href[4:]  # Remove 'tel:'
            
            # Try to find associated name
            person_name = self._find_associated_name_static(link, parser)
            person_title = self._find_associated_title_static(link, parser)
            
            # Create evidence package
            evidence = self.evidence_builder.create_evidence_static(
                source_url=source_url,
                selector='a[href*="tel:"]',
                node=link,
                verbatim_text=link.text() or phone
            )
            
            if not person_name or not person_title:
                continue
            contacts.append(Contact(
                company=company_name,
                person_name=person_name,
                role_title=person_title,
                contact_type=ContactType.PHONE,
                contact_value=phone,
                evidence=evidence,
                captured_at=evidence.timestamp
            ))
        
        return contacts

    def _extract_table_contacts_static(self, parser: HTMLParser, source_url: str, company_name: str) -> List[Contact]:
        """Extract contacts from well-structured HTML tables with header columns.
        Active only in aggressive-static mode.
        """
        results: List[Contact] = []
        tables = parser.css('table') or []
        if not tables:
            return results
        site_domain = urlparse(source_url).netloc.lower().replace('www.', '')
        allow_free_env = os.getenv('EGC_ALLOW_FREE_EMAIL', '0') == '1'

        def norm_txt(s: Optional[str]) -> str:
            return re.sub(r"\s+", " ", (s or '').strip()).lower()
        # Header classification
        def classify(h: str) -> str | None:
            h = norm_txt(h)
            if re.search(r"\b(full\s*name|name|person|employee|имя|фамилия|surname)\b", h):
                return 'name'
            if re.search(r"\b(first\s*name)\b", h):
                return 'first'
            if re.search(r"\b(last\s*name|surname|фамилия)\b", h):
                return 'last'
            if re.search(r"\b(title|role|position|должность)\b", h):
                return 'title'
            if re.search(r"\b(email|e-mail|mail|почта)\b", h):
                return 'email'
            if re.search(r"\b(phone|telephone|tel|телефон)\b", h):
                return 'phone'
            return None

        for tbl in tables:
            headers = tbl.css('th')
            if not headers:
                continue
            header_texts = [norm_txt(h.text()) for h in headers]
            col_map: Dict[str, int] = {}
            for idx, h in enumerate(header_texts):
                kind = classify(h)
                if kind and kind not in col_map:
                    col_map[kind] = idx
            if not any(k in col_map for k in ('name','first')):
                continue
            # Collect rows
            rows = tbl.css('tr')
            for tr in rows[1:]:  # skip header row
                tds = tr.css('td')
                if not tds:
                    continue
                def get_cell(i: int) -> tuple[str, Optional[Node]]:
                    if i is None or i >= len(tds):
                        return '', None
                    cell = tds[i]
                    return (cell.text() or '').strip(), cell

                # Compose name
                name_val = ''
                if 'name' in col_map:
                    name_val, name_node = get_cell(col_map['name'])
                else:
                    first_val, _ = get_cell(col_map.get('first'))
                    last_val, _ = get_cell(col_map.get('last'))
                    name_val = f"{first_val} {last_val}".strip()
                    name_node = None
                if not name_val or not self._is_valid_person_name(name_val):
                    continue

                # Title
                title_val, title_node = get_cell(col_map.get('title'))

                # Email
                email_val = ''
                email_node = None
                if 'email' in col_map:
                    email_text, email_node = get_cell(col_map['email'])
                    # Prefer mailto in the cell
                    a_mail = email_node.css_first("a[href*='mailto:']") if email_node else None
                    if a_mail:
                        href = a_mail.attrs.get('href','')
                        if href.lower().startswith('mailto:'):
                            email_val = href[7:]
                        elif '@' in href:
                            email_val = href
                    if not email_val:
                        email_val = self._deobfuscate_email(email_text) or ''
                # Phone
                phone_val = ''
                phone_node = None
                if 'phone' in col_map:
                    phone_text, phone_node = get_cell(col_map['phone'])
                    m = self.phone_pattern.search(phone_text or '')
                    if m:
                        phone_val = re.sub(r"\D", "", m.group(0))

                # Domain policy for email
                email_ok = False
                if email_val:
                    email_domain = email_val.split('@')[-1].lower()
                    same_domain = email_domain.endswith(site_domain)
                    email_ok = same_domain or (self.aggressive_static and self._email_domain_matches_site(email_domain, site_domain)) or (allow_free_env and (email_domain in self.free_email_domains))

                # Build contacts
                # Role fallback if aggressive
                role_final = title_val or ("Unknown" if (self.aggressive_static and (email_val or phone_val)) else None)
                if not role_final:
                    continue

                if email_val and email_ok:
                    ev = self.evidence_builder.create_evidence_static(
                        source_url=source_url,
                        selector="table th:contains('email')",
                        node=email_node or tr,
                        verbatim_text=email_val
                    )
                    results.append(Contact(
                        company=company_name,
                        person_name=name_val,
                        role_title=role_final,
                        contact_type=ContactType.EMAIL,
                        contact_value=email_val,
                        evidence=ev,
                        captured_at=ev.timestamp
                    ))
                if phone_val:
                    evp = self.evidence_builder.create_evidence_static(
                        source_url=source_url,
                        selector="table th:contains('phone')",
                        node=phone_node or tr,
                        verbatim_text=phone_node.text() if (phone_node and phone_node.text()) else phone_val
                    )
                    try:
                        results.append(Contact(
                            company=company_name,
                            person_name=name_val,
                            role_title=role_final,
                            contact_type=ContactType.PHONE,
                            contact_value=phone_val,
                            evidence=evp,
                            captured_at=evp.timestamp
                        ))
                    except Exception:
                        pass

                # VCF in row
                a_vcf = tr.css_first("a[href$='.vcf']")
                if a_vcf:
                    vcf_url = urljoin(source_url, a_vcf.attrs.get('href',''))
                    evv = self.evidence_builder.create_evidence_static(
                        source_url=source_url,
                        selector="tr a[href$='.vcf']",
                        node=a_vcf,
                        verbatim_text=a_vcf.text() or vcf_url
                    )
                    try:
                        results.append(Contact(
                            company=company_name,
                            person_name=name_val,
                            role_title=role_final,
                            contact_type=ContactType.LINK,
                            contact_value=vcf_url,
                            evidence=evv,
                            captured_at=evv.timestamp
                        ))
                    except Exception:
                        pass

        return results
    
    def _find_associated_name_static(self, contact_node: Node, parser: HTMLParser) -> Optional[str]:
        """
        Try to find a person name associated with a contact link.
        
        Looks in parent elements and nearby text for name patterns.
        """
        # Check parent elements for names
        parent = contact_node.parent
        while parent and parent.tag != 'body':
            # Look for name patterns in parent text
            parent_text = parent.text() or ''
            
            # Look for patterns like "John Doe Email: john@example.com"
            name_pattern = r'([A-Z][a-z]+ [A-Z][a-z]+(?:,? [A-Z]\.?[A-Z]\.?)?)'
            names = re.findall(name_pattern, parent_text)
            
            for name in names:
                if len(name) > 5 and not any(word in name.lower() for word in 
                    ['email', 'phone', 'contact', 'mailto', 'tel']):
                    return name.strip()
            
            # Look for headers (h1-h4) in the same parent
            for level in range(1, 5):
                header = parent.css_first(f'h{level}')
                if header and header.text():
                    header_text = header.text().strip()
                    # Basic name validation
                    if (len(header_text) > 5 and len(header_text) < 50 and 
                        not any(word in header_text.lower() for word in 
                        ['team', 'about', 'contact', 'email', 'phone'])):
                        return header_text
            
            parent = parent.parent
        
        return None
    
    def _find_associated_title_static(self, contact_node: Node, parser: HTMLParser) -> Optional[str]:
        """
        Try to find a job title associated with a contact link.
        
        Looks for common title patterns near the contact information.
        """
        # Check parent elements for titles
        parent = contact_node.parent
        while parent and parent.tag != 'body':
            parent_text = parent.text() or ''
            
            # Look for title patterns
            title_keywords = [
                'partner', 'associate', 'manager', 'director', 'president', 'ceo', 'cto',
                'engineer', 'architect', 'consultant', 'specialist', 'analyst', 'coordinator'
            ]
            
            for keyword in title_keywords:
                if keyword.lower() in parent_text.lower():
                    # Extract sentence containing the keyword
                    sentences = parent_text.split('.')
                    for sentence in sentences:
                        if keyword.lower() in sentence.lower():
                            # Clean and return the title part
                            title = sentence.strip()
                            if len(title) > 5 and len(title) < 100:
                                return title
            
            parent = parent.parent
        
        return None
