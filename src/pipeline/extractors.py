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
            '.person, .team-member, .employee, .staff-member',
            '.bio, .biography, .profile',
            '.card .person-info, .member-card',
            '[data-person], [data-team-member]',
            'article.person, section.team-member'
        ]
        
        # Selectors for names within person containers
        self.name_selectors = [
            'h1, h2, h3, h4',
            '.name, .person-name, .full-name',
            '.title:first-child, .heading:first-child',
            'strong:first-child, b:first-child'
        ]
        
        # Selectors for job titles/roles
        self.title_selectors = [
            '.title, .job-title, .position, .role',
            '.subtitle, .description:first-of-type',
            'em, i, .italic',
            'p:first-of-type, .bio p:first-child'
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
        contacts = []
        
        # Extract company name from page
        company_name = self._extract_company_name_static(parser, source_url)
        
        # Find person containers first
        for selector in self.person_selectors:
            person_nodes = parser.css(selector)
            
            for person_node in person_nodes:
                person_contacts = self._extract_person_contacts_static(
                    person_node, source_url, company_name, selector
                )
                contacts.extend(person_contacts)
        
        # If no structured person containers found, try fallback extraction
        if not contacts:
            fallback_contacts = self._extract_fallback_contacts_static(
                parser, source_url, company_name
            )
            contacts.extend(fallback_contacts)
        
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
                company_text = re.sub(r'\s*(Team|People|About).*$', '', company_text, re.IGNORECASE)
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
        
        # Extract person name and title
        person_name = self._extract_person_name_static(person_node)
        person_title = self._extract_person_title_static(person_node)
        
        if not person_name:
            return contacts  # Skip if we can't find a name
        
        # Extract emails
        emails = self._extract_emails_static(person_node)
        for email, email_selector in emails:
            evidence = self.evidence_builder.create_evidence_static(
                source_url=source_url,
                selector=f"{base_selector} {email_selector}",
                node=person_node,  # Use person container for context
                verbatim_text=email
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
        phones = self._extract_phones_static(person_node)
        for phone, phone_selector in phones:
            evidence = self.evidence_builder.create_evidence_static(
                source_url=source_url,
                selector=f"{base_selector} {phone_selector}",
                node=person_node,
                verbatim_text=phone
            )
            
            contacts.append(Contact(
                company=company_name,
                person_name=person_name,
                role_title=person_title or "Not specified",
                contact_type=ContactType.PHONE,
                contact_value=phone,
                evidence=evidence,
                captured_at=evidence.timestamp
            ))
        
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
        
        if not person_name:
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
            
            contacts.append(Contact(
                company=company_name,
                person_name=person_name,
                role_title=person_title or "Not specified",
                contact_type=ContactType.PHONE,
                contact_value=phone,
                evidence=evidence,
                captured_at=evidence.timestamp
            ))
        
        return contacts
    
    def _extract_person_name_static(self, person_node: Node) -> Optional[str]:
        """Extract person name from static HTML node."""
        for selector in self.name_selectors:
            name_node = person_node.css_first(selector)
            if name_node and name_node.text():
                name = name_node.text().strip()
                # Basic cleaning
                name = re.sub(r'^(Dr\.|Mr\.|Ms\.|Mrs\.)\s+', '', name)
                if len(name) > 3:  # Basic validation
                    return name[:100]
        return None
    
    def _extract_person_title_static(self, person_node: Node) -> Optional[str]:
        """Extract person title/role from static HTML node."""
        for selector in self.title_selectors:
            title_node = person_node.css_first(selector)
            if title_node and title_node.text():
                title = title_node.text().strip()
                if len(title) > 2:
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
                    if len(title) > 2:
                        return title[:200]
            except Exception:
                continue
        return None
    
    def _extract_emails_static(self, person_node: Node) -> List[Tuple[str, str]]:
        """Extract emails from static HTML with their selectors."""
        emails = []
        
        # Look for mailto links
        mailto_links = person_node.css('a[href*="mailto:"]')
        for link in mailto_links:
            href = link.attrs.get('href', '')
            if href.startswith('mailto:'):
                email = href[7:]  # Remove 'mailto:'
                if self.email_pattern.match(email):
                    emails.append((email, 'a[href*="mailto:"]'))
        
        # Look for email patterns in text
        text_content = person_node.text() or ''
        found_emails = self.email_pattern.findall(text_content)
        for email in found_emails:
            if email not in [e[0] for e in emails]:  # Avoid duplicates
                emails.append((email, 'text()'))
        
        return emails
    
    def _extract_phones_static(self, person_node: Node) -> List[Tuple[str, str]]:
        """Extract phone numbers from static HTML with their selectors."""
        phones = []
        
        # Look for tel links
        tel_links = person_node.css('a[href*="tel:"]')
        for link in tel_links:
            href = link.attrs.get('href', '')
            if href.startswith('tel:'):
                phone = href[4:]  # Remove 'tel:'
                phones.append((phone, 'a[href*="tel:"]'))
        
        # Look for phone patterns in text
        text_content = person_node.text() or ''
        found_phones = self.phone_pattern.findall(text_content)
        for phone in found_phones:
            if phone not in [p[0] for p in phones]:  # Avoid duplicates
                phones.append((phone, 'text()'))
        
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
            
            contacts.append(Contact(
                company=company_name,
                person_name=person_name or "Contact Person",
                role_title=person_title or "Not specified",
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
            
            contacts.append(Contact(
                company=company_name,
                person_name=person_name or "Contact Person",
                role_title=person_title or "Not specified",
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
