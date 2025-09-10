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
from typing import List, Dict, Optional, Union, Tuple
from urllib.parse import urljoin, urlparse

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
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
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

        # Name is mandatory; role is mandatory unless aggressive_static with other evidence
        if not person_name:
            return contacts

        # In non-aggressive mode, title is also required.
        if not self.aggressive_static and not person_title:
            return contacts

        # Email/Phone/VCF collection containers
        found_any_contact = False

        # Email domain filter inputs
        site_domain = urlparse(source_url).netloc.lower().replace('www.', '')
        allow_free_env = os.getenv('EGC_ALLOW_FREE_EMAIL', '0') == '1'

        # 1) Emails: nearest mailto, fall back to text scan when aggressive
        email_link = self._nearest_link(person_node, name_node, "a[href*='mailto:']") if name_node else None
        candidate_emails: List[tuple[str, Optional[Node], str]] = []  # (email, node, selector)
        if email_link:
            href = (email_link.attrs.get('href','') or '').strip()
            href_lower = href.lower()
            email_val = None
            if href_lower.startswith('mailto:'):
                email_val = href[7:]
            elif '@' in href:
                email_val = href
            else:
                txt = (email_link.text() or '').strip()
                if '@' in txt:
                    email_val = txt
            if not email_val and self.aggressive_static:
                # try deobfuscation on href/text
                email_val = self._deobfuscate_email(href) or self._deobfuscate_email(email_link.text() or '')
            if email_val and self.email_pattern.match(email_val):
                candidate_emails.append((email_val, email_link, f"{base_selector} a[href*='mailto:']"))

        if self.aggressive_static and not candidate_emails:
            # Extract from text within the person card
            for em in self._emails_from_text(person_node):
                candidate_emails.append((em, person_node, f"{base_selector} :contains('@')"))

        # Filter and add emails by domain policy
        for email_val, node_for_ev, sel in candidate_emails:
            email_domain = email_val.split('@')[-1].lower() if '@' in email_val else ''
            same_domain = email_domain.endswith(site_domain)
            domain_ok = same_domain or (self.aggressive_static and self._email_domain_matches_site(email_domain, site_domain)) or (allow_free_env and (email_domain in self.free_email_domains))
            if domain_ok:
                evidence = self.evidence_builder.create_evidence_static(
                    source_url=source_url,
                    selector=sel,
                    node=node_for_ev or person_node,
                    verbatim_text=(node_for_ev.text() if (node_for_ev and hasattr(node_for_ev, 'text')) else None) or email_val
                )
                contacts.append(Contact(
                    company=company_name,
                    person_name=person_name,
                    role_title=person_title or ("Unknown" if self.aggressive_static else None),
                    contact_type=ContactType.EMAIL,
                    contact_value=email_val,
                    evidence=evidence,
                    captured_at=evidence.timestamp
                ))
                found_any_contact = True

        # 2) Phones: tel links; if none and aggressive, scan text
        phone_link = self._nearest_link(person_node, name_node, "a[href*='tel:']") if name_node else None
        phones_added = False
        if phone_link:
            href = phone_link.attrs.get('href','') or ''
            phone_raw = href[4:] if href.startswith('tel:') else href
            normalized_phone = re.sub(r"\D", "", phone_raw)
            evidence = self.evidence_builder.create_evidence_static(
                source_url=source_url,
                selector=f"{base_selector} a[href*='tel:']",
                node=phone_link,
                verbatim_text=phone_link.text() or phone_raw
            )
            try:
                contacts.append(Contact(
                    company=company_name,
                    person_name=person_name,
                    role_title=person_title or ("Unknown" if self.aggressive_static else None),
                    contact_type=ContactType.PHONE,
                    contact_value=normalized_phone,
                    evidence=evidence,
                    captured_at=evidence.timestamp
                ))
                found_any_contact = True
                phones_added = True
            except Exception:
                pass
        if self.aggressive_static and not phones_added:
            text_block = person_node.text() or ''
            text_lower = text_block.lower()
            markers = ('phone', 'tel', 'тел', 'telefon')
            has_marker = any(k in text_lower for k in markers)
            for m in self.phone_pattern.findall(text_block):
                raw = m if isinstance(m, str) else ''.join(m)
                num = re.sub(r"\D", "", raw)
                # Strict validation for text-detected phones
                if not num or len(num) < 10 or len(num) > 15:
                    continue
                # filter date-like patterns (YYYYMMDD or similar)
                if re.match(r'^(19|20)\d{6,8}$', num):
                    continue
                if not has_marker:
                    continue
                evidence = self.evidence_builder.create_evidence_static(
                    source_url=source_url,
                    selector=f"{base_selector} :text-phone",
                    node=person_node,
                    verbatim_text=raw
                )
                try:
                    contacts.append(Contact(
                        company=company_name,
                        person_name=person_name,
                        role_title=person_title or ("Unknown" if self.aggressive_static else None),
                        contact_type=ContactType.PHONE,
                        contact_value=num,
                        evidence=evidence,
                        captured_at=evidence.timestamp
                    ))
                    found_any_contact = True
                    break  # keep at most one phone per person
                except Exception:
                    continue

        # 3) vCard links (.vcf) if present in card
        for a in person_node.css('a'):
            href = (a.attrs.get('href','') or '').strip()
            text_lower = (a.text() or '').strip().lower()
            if href.lower().endswith('.vcf') or 'vcard' in text_lower:
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
                        role_title=person_title or ("Unknown" if self.aggressive_static else None),
                        contact_type=ContactType.LINK,
                        contact_value=vcf_url,
                        evidence=evidence,
                        captured_at=evidence.timestamp
                    ))
                    found_any_contact = True
                except Exception:
                    pass

        # If still no contacts in card root, try bio page if there is a name link
        if not found_any_contact and name_node is not None:
            a = name_node.parent if name_node and name_node.parent and name_node.parent.tag == 'a' else name_node.css_first('a')
            href = a.attrs.get('href') if a and a.attrs else None
            if href and href.startswith('http'):
                try:
                    with httpx.Client(timeout=10.0, follow_redirects=True) as c:
                        r = c.get(href)
                        if r.status_code < 400 and 'text/html' in (r.headers.get('Content-Type','').lower()):
                            bio_contacts = self.extract_from_static_html(r.text, href)
                            # choose the first matching by name
                            for bc in bio_contacts:
                                if bc.person_name.lower() == person_name.lower():
                                    contacts.append(bc)
                                    break
                except Exception:
                    pass

        return contacts
    
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
        
        # Extract emails
        emails = self._extract_emails_playwright(person_element)
        for email, email_element in emails:
            # Get verbatim text from the email element
            verbatim_text = email_element.text_content() or email
            
            evidence = self.evidence_builder.create_evidence_playwright(
                source_url=source_url,
                selector=f"{base_selector} a[href*='mailto:']",  # Generic email selector
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
