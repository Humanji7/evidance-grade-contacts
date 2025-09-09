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
    
    def __init__(self, evidence_builder: Optional[EvidenceBuilder] = None):
        """
        Initialize Contact Extractor.
        
        Args:
            evidence_builder: EvidenceBuilder instance for creating evidence packages
        """
        self.evidence_builder = evidence_builder or EvidenceBuilder()
        
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
        
        # If no structured person containers were found at all, try fallback extraction
        # Disable global fallback to avoid cross-card noise in PoC
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
        contacts = []
        
        # Extract person name and title (within this root only)
        name_node = self._find_name_node_static(person_node)
        person_name = self._text_from_name_node(name_node) if name_node else None
        # Try to get role near name inside same paragraph with <br>
        person_title = self._extract_role_near_name_static(person_node, name_node) or self._extract_person_title_static(person_node)
        
        # Require both name and title for PoC to avoid generic site contacts
        if not person_name or not person_title:
            return contacts
        
        # Email domain filter
        site_domain = urlparse(source_url).netloc.lower().replace('www.', '')
        free_domains = {'gmail.com','yahoo.com','outlook.com','hotmail.com','aol.com','icloud.com'}
        
        # Select nearest email within root
        email_link = self._nearest_link(person_node, name_node, "a[href*='mailto:']") if name_node else None
        # If not found, search anchors with visible text 'email'
        if not email_link:
            for a in person_node.css('a'):
                t = (a.text() or '').strip().lower()
                if 'email' in t:
                    email_link = a
                    break
        email = None
        if email_link:
            href = (email_link.attrs.get('href','') or '').strip()
            href_lower = href.lower()
            if href_lower.startswith('mailto:'):
                email = href[7:]
            elif href_lower.startswith('mailt:') or href_lower.startswith('mailton:') or href_lower.startswith('maiito:'):
                # fix common typos
                email = href.split(':',1)[-1]
            elif '@' in href:
                email = href
            else:
                # sometimes email is in the link text
                txt = (email_link.text() or '').strip()
                if '@' in txt:
                    email = txt
        allow_free = '/leadership' in urlparse(source_url).path.lower()
        if email:
            email_domain = email.split('@')[-1].lower() if '@' in email else ''
            domain_ok = (email_domain.endswith(site_domain)) or (allow_free and email_domain not in {'example.com'})
            if domain_ok and self.email_pattern.match(email):
                evidence = self.evidence_builder.create_evidence_static(
                    source_url=source_url,
                    selector=f"{base_selector} a[href*='mailto:']",
                    node=email_link,
                    verbatim_text=email_link.text() or email
                )
                contacts.append(Contact(
                    company=company_name,
                    person_name=person_name,
                    role_title=person_title,
                    contact_type=ContactType.EMAIL,
                    contact_value=email,
                    evidence=evidence,
                    captured_at=evidence.timestamp
                ))
        
        # Select nearest phone within root
        phone_link = self._nearest_link(person_node, name_node, "a[href*='tel:']") if name_node else None
        if phone_link:
            href = phone_link.attrs.get('href','')
            phone = href[4:] if href.startswith('tel:') else href
            normalized_phone = re.sub(r"\D", "", phone)
            evidence = self.evidence_builder.create_evidence_static(
                source_url=source_url,
                selector=f"{base_selector} a[href*='tel:']",
                node=phone_link,
                verbatim_text=phone_link.text() or phone
            )
            try:
                contacts.append(Contact(
                    company=company_name,
                    person_name=person_name,
                    role_title=person_title,
                    contact_type=ContactType.PHONE,
                    contact_value=normalized_phone,
                    evidence=evidence,
                    captured_at=evidence.timestamp
                ))
            except Exception:
                pass
        
        # If no contacts in card root, try bio page if there is a name link
        if not contacts and name_node is not None:
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

    # -------------------------
    # Validation & Dedup helpers
    # -------------------------
    def _is_valid_person_name(self, name: str) -> bool:
        if not name or len(name) < 4:
            return False
        # Exclude generic section headers
        if re.search(r"^(Our Team|Team|People|Staff|Contact|Contacts|News|Press)$", name, re.IGNORECASE):
            return False
        # Require at least two words with letters
        parts = [p for p in re.split(r"\s+", name) if p]
        if len(parts) < 2:
            return False
        # Basic: starts with letter and has vowels/consonants
        return bool(re.match(r"^[A-Za-z]", parts[0]))

    def _is_valid_role_title(self, title: str) -> bool:
        if not title or len(title) < 3:
            return False
        # Leadership/decision-maker leaning allowlist and admin blacklist
        blacklist = [
            'paralegal', 'legal administrator', 'legal administrative', 'assistant', 'accountant',
            'marketing', 'retired', 'intern', 'receptionist'
        ]
        if any(b in title.lower() for b in blacklist):
            return False
        return True

    def _postprocess_and_dedup(self, contacts: List[Contact]) -> List[Contact]:
        if not contacts:
            return []
        # Collapse duplicates and limit per person
        by_person: Dict[tuple, Dict[str, set]] = {}
        unique_contacts: List[Contact] = []
        seen_keys = set()
        for c in contacts:
            key_person = (c.company.strip().lower(), c.person_name.strip().lower(), c.role_title.strip().lower())
            if key_person not in by_person:
                by_person[key_person] = {'email': set(), 'phone': set(), 'link': set()}
            # Limit: keep at most 1 email and 1 phone per person for PoC
            type_key = c.contact_type.value
            if type_key in ('email', 'phone'):
                if by_person[key_person][type_key] and c.contact_value in by_person[key_person][type_key]:
                    continue
                if len(by_person[key_person][type_key]) >= 1:
                    continue
                by_person[key_person][type_key].add(c.contact_value)
            else:
                # Links: dedupe exact value
                if c.contact_value in by_person[key_person]['link']:
                    continue
                by_person[key_person]['link'].add(c.contact_value)
            # Global dedupe key
            dk = (key_person, type_key, c.contact_value)
            if dk in seen_keys:
                continue
            seen_keys.add(dk)
            unique_contacts.append(c)
        return unique_contacts
    
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
