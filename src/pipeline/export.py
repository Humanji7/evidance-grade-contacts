"""
Export Pipeline - CSV/JSON Output with Evidence Packages

Exports VERIFIED contacts only (excludes UNVERIFIED records per PoC specification).
Supports both flat CSV format and nested JSON format with complete evidence packages.

Key Features:
- VERIFIED contacts filtering (UNVERIFIED automatically excluded)
- Complete Mini Evidence Package export (all 7 fields)
- Multiple output formats: CSV, JSON, or both
- Data validation and integrity checking
- Proper error handling and logging
"""

import csv
import json
import re
from pathlib import Path
from typing import List, Optional, Union
from datetime import datetime as dt, datetime
from urllib.parse import urlsplit, urlunsplit

from ..schemas import Contact, ContactExport, VerificationStatus


def normalize_url_for_report(u: str) -> str:
    """Normalize URLs for reporting purposes only (does not change Evidence):
    - host -> lower and strip leading 'www.'
    - drop query and fragment
    - trim trailing '/' except for root
    """
    try:
        sp = urlsplit(u)
        netloc = (sp.netloc or '').lower()
        if netloc.startswith('www.'):
            netloc = netloc[4:]
        path = sp.path or ''
        if path.endswith('/') and path != '/':
            path = path.rstrip('/')
        sp2 = sp._replace(netloc=netloc, path=path, query='', fragment='')
        return urlunsplit(sp2)
    except Exception:
        return u or ''


def normalize_person_name(s: str) -> str:
    """Normalize person name for grouping keys (unicode-safe).
    - lowercased, trimmed
    - collapse whitespace
    - strip commas and periods (dots) so that variants like "J. W. Alberstadt, Jr." and
      "J. W.Alberstadt, Jr." normalize the same.
    - keep other unicode letters intact
    """
    if not s:
        return ""
    # Lowercase and replace commas/dots with space, then collapse whitespace
    s2 = s.lower()
    s2 = s2.replace(',', ' ').replace('.', ' ')
    s2 = re.sub(r"\s+", " ", s2).strip()
    return s2


def _norm_key(company: str, person_name: str, contact_type: str, contact_value: str) -> tuple:
    company_norm = (company or '').strip().lower()
    person_norm = normalize_person_name(person_name or '')
    if contact_type == 'email':
        value_norm = (contact_value or '').strip().lower()
    elif contact_type == 'phone':
        value_norm = re.sub(r"\D", "", (contact_value or ''))
    else:
        value_norm = (contact_value or '').strip().lower()
    return (company_norm, person_norm, contact_type, value_norm)


def _quality_tuple(c: Contact) -> tuple:
    """Return a tuple for comparing two contacts with the same dedup key.
    Higher tuple compares greater.
    Priority:
      1) Anchor > text (selector contains a[href*='mailto:'] or a[href*='tel:'])
      2) Semantic URL (contains /leadership|/our-team|/team)
      3) Role != Unknown
      4) Canon URL length (shorter is better)
      5) Fresher captured_at
    """
    sel = (c.evidence.selector_or_xpath or '').lower() if c.evidence else ''
    anchor = 1 if ("a[href*='mailto:']" in sel or "a[href*='tel:']" in sel) else 0

    surl = (c.evidence.source_url or '').lower() if c.evidence else ''
    semantic = 1 if any(k in surl for k in ('/leadership', '/our-team', '/team')) else 0

    role_good = 1 if (c.role_title and c.role_title.strip().lower() != 'unknown') else 0

    canon = normalize_url_for_report(c.evidence.source_url if c.evidence else '')
    canon_len = len(canon)

    freshness = c.captured_at or datetime.min

    # We want: anchor desc, semantic desc, role_good desc, canon_len asc, captured_at desc
    return (anchor, semantic, role_good, -canon_len, freshness)


def dedupe_contacts_for_export(contacts: List[Contact]) -> List[Contact]:
    """Global dedupe for export layer by (company, person, type, value) with quality tie-breaks.
    Does not mutate models; only filters which instances to emit.
    """
    if not contacts:
        return []
    best: dict[tuple, Contact] = {}
    for c in contacts:
        key = _norm_key(c.company, c.person_name, c.contact_type.value, c.contact_value)
        prev = best.get(key)
        if prev is None or _quality_tuple(c) > _quality_tuple(prev):
            best[key] = c
    kept = list(best.values())
    removed = len(contacts) - len(kept)
    if removed > 0:
        print(f"🧹 Dedupe: kept {len(kept)} of {len(contacts)}")
    return kept


def _registrable_domain(host: str) -> str:
    parts = (host or '').lower().split('.')
    if len(parts) >= 3 and parts[-2] in {'co','com','org','net','gov','ac','edu'} and len(parts[-1]) <= 3:
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:]) if len(parts) >= 2 else host.lower()


def _email_domain_score(email: str, source_url: str) -> int:
    """Return 1 if email domain matches page domain (registrable), else 0."""
    try:
        from urllib.parse import urlsplit
        host = (urlsplit(source_url).netloc or '').lower()
    except Exception:
        host = ''
    edom = (email.split('@')[-1] or '').lower()
    return 1 if (_registrable_domain(edom) == _registrable_domain(host)) else 0


def _is_generic_localpart(email: str) -> int:
    local = (email.split('@')[0] or '').lower()
    generics = {'info', 'hr', 'contact', 'office'}
    return 1 if (local not in generics) else 0


def _is_semantic_url(u: str) -> int:
    low = (u or '').lower()
    return 1 if any(k in low for k in ('/leadership', '/our-team', '/team')) else 0


def _is_anchor_selector(sel: str, want: str) -> int:
    low = (sel or '').lower()
    return 1 if (want in low) else 0


def _is_toll_free(num: str) -> int:
    d = re.sub(r"\D", "", num or '')
    return 0 if d.startswith(('800', '888', '877', '866')) else 1


def _best_role_for_person(contacts: List[Contact]) -> str:
    # Prefer non-Unknown and longer titles as "more informative"
    best = 'Unknown'
    best_score = (-1, 0)
    for c in contacts:
        rt = (c.role_title or '').strip()
        is_known = 1 if rt and rt.lower() != 'unknown' else 0
        score = (is_known, len(rt))
        if score > best_score:
            best_score = score
            best = rt or 'Unknown'
    return best or 'Unknown'


def consolidate_per_person(contacts: List[Contact]) -> List[dict]:
    """Aggregate contacts per person into a single row per person.

    - Key: (company_norm, person_name_norm)
    - For each person choose best email/phone/vcard based on ranking rules.
    Returns list of dict rows with fields:
      company, person_name, role_title, email, phone, vcard,
      source_url_email, source_url_phone, source_url_vcard
    """
    if not contacts:
        return []

    # 1) Filter out obvious non-persons BEFORE grouping
    NON_PERSON_PHRASES = {
        'mailing address', 'click here', 'branch hours', 'business services team',
        'executive team', 'support', 'department', 'services', 'contact us', 'resources'
    }

    filtered: list[Contact] = []
    for c in contacts:
        pname = (c.person_name or '').strip().lower()
        if any(phrase in pname for phrase in NON_PERSON_PHRASES):
            continue  # exclude from consolidation
        filtered.append(c)

    if not filtered:
        print(f"👤 Consolidation: persons=0, from_contacts={len(contacts)}")
        return []

    # 2) Group by (company, person)
    by_person: dict[tuple, list[Contact]] = {}
    for c in filtered:
        key = ((c.company or '').strip().lower(), normalize_person_name(c.person_name or ''))
        by_person.setdefault(key, []).append(c)

    def _name_tokens_latin(name: str) -> list[str]:
        low = (name or '').lower()
        return re.findall(r"[a-z]{3,}", low)

    def _local_matches_name(local: str, tokens: list[str]) -> int:
        loc = (local or '').lower()
        return 1 if any(tok in loc for tok in tokens) else 0

    def _digits_only(s: str) -> str:
        return re.sub(r"\D", "", s or '')

    def _looks_like_date_number(digits: str) -> bool:
        # r'^(19|20)\d{6,8}$' on the normalized digits
        return bool(re.match(r"^(19|20)\d{6,8}$", digits or ''))

    rows: list[dict] = []
    for (company_norm, person_norm), clist in by_person.items():
        # Stable display values from any contact in group
        company_disp = clist[0].company
        person_disp = clist[0].person_name

        # Prepare name tokens for email local-part matching
        tokens = _name_tokens_latin(person_disp)

        # Rank email candidates per spec
        email_best: Optional[Contact] = None
        email_score_best: Optional[tuple] = None
        for c in clist:
            if c.contact_type.value != 'email':
                continue
            sel = (c.evidence.selector_or_xpath or '') if c.evidence else ''
            surl = (c.evidence.source_url or '') if c.evidence else ''
            local = (c.contact_value or '').split('@')[0].lower()
            name_match = _local_matches_name(local, tokens)
            score = (
                _is_anchor_selector(sel.lower(), "a[href*='mailto:']"),  # 1) anchor
                _is_semantic_url(surl),                                   # 2) semantic URL
                name_match,                                               # 3) local-part matches name
                c.captured_at or datetime.min,                            # 4) recency
            )
            if (email_best is None) or (score > email_score_best):
                email_best = c
                email_score_best = score

        # Rank phone candidates per spec
        phone_best: Optional[Contact] = None
        phone_score_best: Optional[tuple] = None
        phone_candidates_anchor: list[Contact] = []
        phone_candidates_text: list[Contact] = []
        for c in clist:
            if c.contact_type.value != 'phone':
                continue
            sel = (c.evidence.selector_or_xpath or '') if c.evidence else ''
            if _is_anchor_selector(sel.lower(), "a[href*='tel:']"):
                phone_candidates_anchor.append(c)
            else:
                phone_candidates_text.append(c)

        def _score_phone(c: Contact) -> tuple:
            sel = (c.evidence.selector_or_xpath or '') if c.evidence else ''
            surl = (c.evidence.source_url or '') if c.evidence else ''
            return (
                _is_anchor_selector(sel.lower(), "a[href*='tel:']"),  # anchor first
                _is_semantic_url(surl),                                # semantic URL
                _is_toll_free(c.contact_value),                        # prefer non toll-free
                c.captured_at or datetime.min,                         # fresher
            )

        if phone_candidates_anchor:
            for c in phone_candidates_anchor:
                score = _score_phone(c)
                if (phone_best is None) or (score > phone_score_best):
                    phone_best = c
                    phone_score_best = score
        else:
            # No anchor phones; consider text-only phones with validation
            valid_texts: list[Contact] = []
            for c in phone_candidates_text:
                digits = _digits_only(c.contact_value)
                if 10 <= len(digits) <= 15 and not _looks_like_date_number(digits):
                    valid_texts.append(c)
            for c in valid_texts:
                score = _score_phone(c)
                if (phone_best is None) or (score > phone_score_best):
                    phone_best = c
                    phone_score_best = score

        # vCard: trust extractor attribution; pick best by semantic URL then recency
        vcard_best = None
        vcard_score_best = None
        for c in clist:
            if c.contact_type.value != 'link':
                continue
            if not (c.contact_value or '').lower().endswith('.vcf'):
                continue
            surl = (c.evidence.source_url or '') if c.evidence else ''
            score = (
                _is_semantic_url(surl),
                c.captured_at or datetime.min,
            )
            if (vcard_best is None) or (score > vcard_score_best):
                vcard_best = c
                vcard_score_best = score

        role_final = _best_role_for_person(clist)

        # Output: one best email and one best phone (phone normalized to digits if present)
        out_phone = ''
        if phone_best is not None:
            # Prefer digits from verbatim when anchor is present; fallback to contact_value
            sel_best = (phone_best.evidence.selector_or_xpath or '') if phone_best.evidence else ''
            if _is_anchor_selector(sel_best.lower(), "a[href*='tel:']"):
                # Try to parse digits from verbatim (often mirrors the href or the displayed number)
                verb = (phone_best.evidence.verbatim_quote or '') if phone_best.evidence else ''
                digits_from_verb = _digits_only(verb)
                candidate = digits_from_verb if (10 <= len(digits_from_verb) <= 15 and not _looks_like_date_number(digits_from_verb)) else _digits_only(phone_best.contact_value)
            else:
                candidate = _digits_only(phone_best.contact_value)
            # Normalize to strip leading US country code '1' if present (11-digit NANP)
            if len(candidate) == 11 and candidate.startswith('1'):
                candidate = candidate[1:]
            out_phone = candidate

        row = {
            'company': company_disp,
            'person_name': person_disp,
            'role_title': role_final or 'Unknown',
            'email': email_best.contact_value if email_best else '',
            'phone': out_phone,
            'vcard': vcard_best.contact_value if vcard_best else '',
            'source_url_email': normalize_url_for_report(email_best.evidence.source_url) if email_best and email_best.evidence else '',
            'source_url_phone': normalize_url_for_report(phone_best.evidence.source_url) if phone_best and phone_best.evidence else '',
            'source_url_vcard': normalize_url_for_report(vcard_best.evidence.source_url) if vcard_best and vcard_best.evidence else '',
        }
        rows.append(row)

    print(f"👤 Consolidation: persons={len(rows)}, from_contacts={len(contacts)}")
    return rows


class ContactExporter:
    """
    Exports contact data with evidence packages to CSV/JSON formats.
    
    Automatically filters to include only VERIFIED contacts with complete
    Mini Evidence Packages per PoC specification.
    """
    
    def __init__(self, output_dir: Union[str, Path] = "output"):
        """
        Initialize Contact Exporter.
        
        Args:
            output_dir: Directory for output files (created if doesn't exist)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def filter_verified_contacts(self, contacts: List[Contact]) -> List[Contact]:
        """
        Filter contacts to include only VERIFIED records.
        
        Args:
            contacts: List of Contact objects
            
        Returns:
            List of VERIFIED contacts only
        """
        verified = [c for c in contacts if c.verification_status == VerificationStatus.VERIFIED]
        
        # Log filtering statistics
        total = len(contacts)
        verified_count = len(verified)
        unverified_count = total - verified_count
        
        print(f"📊 Export filtering: {verified_count} VERIFIED, {unverified_count} UNVERIFIED (excluded)")
        
        return verified
    
    def to_csv(
        self, 
        contacts: List[Contact], 
        filename: Optional[str] = None,
        include_all: bool = False
    ) -> Path:
        """
        Export contacts to CSV format with flattened evidence fields.
        
        Args:
            contacts: List of Contact objects
            filename: Output filename (auto-generated if None)
            include_all: If False (default), only VERIFIED contacts exported
            
        Returns:
            Path to created CSV file
        """
        # Filter to VERIFIED only unless explicitly requested otherwise
        if not include_all:
            contacts = self.filter_verified_contacts(contacts)
        
        if not contacts:
            raise ValueError("No VERIFIED contacts to export")
        
        # Generate filename if not provided
        if filename is None:
            timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
            filename = f"contacts_{timestamp}.csv"
        
        csv_path = self.output_dir / filename
        
        # Dedupe before export (export-layer only)
        contacts = dedupe_contacts_for_export(contacts)

        # Convert to export format (flattened)
        export_contacts = [ContactExport.from_contact(contact) for contact in contacts]
        
        # Write CSV
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            if export_contacts:
                # Get field names from first contact
                fieldnames = export_contacts[0].model_dump().keys()
                
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for contact in export_contacts:
                    # Convert to dict and handle datetime serialization
                    row_data = contact.model_dump()

                    # Normalize source_url for report (do not mutate model)
                    if 'source_url' in row_data:
                        row_data['source_url'] = normalize_url_for_report(row_data['source_url'])
                    
                    # Convert datetime objects to ISO format strings
                    for key, value in list(row_data.items()):
                        if isinstance(value, datetime):
                            row_data[key] = value.isoformat()
                    
                    writer.writerow(row_data)
        
        print(f"💾 CSV exported: {csv_path} ({len(export_contacts)} contacts)")
        return csv_path
    
    def to_json(
        self, 
        contacts: List[Contact], 
        filename: Optional[str] = None,
        include_all: bool = False,
        pretty: bool = True
    ) -> Path:
        """
        Export contacts to JSON format with nested evidence packages.
        
        Args:
            contacts: List of Contact objects
            filename: Output filename (auto-generated if None)
            include_all: If False (default), only VERIFIED contacts exported
            pretty: Pretty-print JSON with indentation
            
        Returns:
            Path to created JSON file
        """
        # Filter to VERIFIED only unless explicitly requested otherwise
        if not include_all:
            contacts = self.filter_verified_contacts(contacts)
        
        if not contacts:
            raise ValueError("No VERIFIED contacts to export")
        
        # Generate filename if not provided
        if filename is None:
            timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
            filename = f"contacts_{timestamp}.json"
        
        json_path = self.output_dir / filename
        
        # Dedupe before export (export-layer only)
        contacts = dedupe_contacts_for_export(contacts)

        # Convert to serializable format
        export_data = []
        for contact in contacts:
            contact_dict = {
                "company": contact.company,
                "person_name": contact.person_name,
                "role_title": contact.role_title,
                "contact_type": contact.contact_type.value,
                "contact_value": contact.contact_value,
                "verification_status": contact.verification_status.value,
                "captured_at": contact.captured_at.isoformat(),
                "evidence": {
                    # Normalize only for report output
                    "source_url": normalize_url_for_report(contact.evidence.source_url),
                    "selector_or_xpath": contact.evidence.selector_or_xpath,
                    "verbatim_quote": contact.evidence.verbatim_quote,
                    "dom_node_screenshot": contact.evidence.dom_node_screenshot,
                    "timestamp": contact.evidence.timestamp.isoformat(),
                    "parser_version": contact.evidence.parser_version,
                    "content_hash": contact.evidence.content_hash
                } if contact.evidence else None
            }
            export_data.append(contact_dict)
        
        # Write JSON
        with open(json_path, 'w', encoding='utf-8') as jsonfile:
            if pretty:
                json.dump(export_data, jsonfile, indent=2, ensure_ascii=False)
            else:
                json.dump(export_data, jsonfile, ensure_ascii=False)
        
        print(f"💾 JSON exported: {json_path} ({len(export_data)} contacts)")
        return json_path
    
    def to_both(
        self, 
        contacts: List[Contact], 
        base_filename: Optional[str] = None,
        include_all: bool = False
    ) -> tuple[Path, Path]:
        """
        Export contacts to both CSV and JSON formats.
        
        Args:
            contacts: List of Contact objects
            base_filename: Base filename (extensions added automatically)
            include_all: If False (default), only VERIFIED contacts exported
            
        Returns:
            Tuple of (csv_path, json_path)
        """
        # Generate base filename if not provided
        if base_filename is None:
            timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
            base_filename = f"contacts_{timestamp}"
        
        # Remove extension if provided
        base_name = Path(base_filename).stem
        
        # Export both formats
        csv_path = self.to_csv(contacts, f"{base_name}.csv", include_all=include_all)
        json_path = self.to_json(contacts, f"{base_name}.json", include_all=include_all)
        
        return csv_path, json_path
    
    def validate_export_integrity(self, contacts: List[Contact], export_path: Path) -> bool:
        """
        Validate exported file integrity against source contacts.
        
        Args:
            contacts: Original contact list
            export_path: Path to exported file
            
        Returns:
            True if validation passes
        """
        if not export_path.exists():
            return False
        
        # Count VERIFIED contacts in source
        verified_count = len(self.filter_verified_contacts(contacts))
        
        if export_path.suffix == '.csv':
            # Count CSV rows (excluding header)
            with open(export_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader)  # Skip header
                row_count = sum(1 for row in reader)
            
            return row_count == verified_count
        
        elif export_path.suffix == '.json':
            # Count JSON objects
            with open(export_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return len(data) == verified_count
        
        return False
    
    def get_export_stats(self, contacts: List[Contact]) -> dict:
        """
        Get export statistics for given contacts.
        
        Args:
            contacts: List of Contact objects
            
        Returns:
            Dictionary with export statistics
        """
        verified = self.filter_verified_contacts(contacts)
        
        # Contact type breakdown
        type_counts = {}
        for contact in verified:
            contact_type = contact.contact_type.value
            type_counts[contact_type] = type_counts.get(contact_type, 0) + 1
        
        # Evidence completeness check
        complete_evidence = sum(1 for c in verified if c.evidence is not None)
        evidence_rate = (complete_evidence / len(verified)) * 100 if verified else 0
        
        return {
            "total_contacts": len(contacts),
            "verified_contacts": len(verified),
            "unverified_contacts": len(contacts) - len(verified),
            "contact_types": type_counts,
            "evidence_completeness_rate": evidence_rate,
            "ready_for_export": len(verified) > 0
        }

    # -------------------------
    # People-level export
    # -------------------------
    def to_people_csv(self, consolidated: List[dict], filename: Optional[str] = None) -> Path:
        """Write consolidated per-person rows to CSV.
        Filename pattern: contacts_people_{timestamp}.csv if not provided.
        """
        if filename is None:
            timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
            filename = f"contacts_people_{timestamp}.csv"
        path = self.output_dir / filename
        if not consolidated:
            # Still create the file with header for consistency
            consolidated = []
        # Determine columns
        columns = [
            'company', 'person_name', 'role_title', 'email', 'phone', 'vcard',
            'source_url_email', 'source_url_phone', 'source_url_vcard'
        ]
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=columns)
            w.writeheader()
            for row in consolidated:
                # Ensure only known columns
                out_row = {k: row.get(k, '') for k in columns}
                w.writerow(out_row)
        print(f"💾 People CSV exported: {path} ({len(consolidated)} persons)")
        return path

    def to_people_json(self, consolidated: List[dict], filename: Optional[str] = None, pretty: bool = True) -> Path:
        """Write consolidated per-person rows to JSON.
        Filename pattern: contacts_people_{timestamp}.json if not provided.
        """
        if filename is None:
            timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
            filename = f"contacts_people_{timestamp}.json"
        path = self.output_dir / filename
        with open(path, 'w', encoding='utf-8') as f:
            if pretty:
                json.dump(consolidated or [], f, indent=2, ensure_ascii=False)
            else:
                json.dump(consolidated or [], f, ensure_ascii=False)
        print(f"💾 People JSON exported: {path} ({len(consolidated or [])} persons)")
        return path
