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


def _norm_key(company: str, person_name: str, contact_type: str, contact_value: str) -> tuple:
    company_norm = (company or '').strip().lower()
    person_norm = (person_name or '').strip().lower()
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
