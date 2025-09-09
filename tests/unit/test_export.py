"""
Unit tests for Export Pipeline

Tests CSV/JSON export functionality including VERIFIED/UNVERIFIED filtering,
evidence package integrity, and file validation.
"""

import csv
import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

from src.pipeline.export import ContactExporter
from src.schemas import Contact, ContactType, VerificationStatus, Evidence


class TestContactExporter:
    """Test suite for ContactExporter class."""
    
    def setup_method(self):
        """Set up test fixtures with temporary output directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.exporter = ContactExporter(output_dir=self.temp_dir)
        
        # Create sample contacts for testing
        self.sample_evidence = Evidence(
            source_url="https://example.com/team",
            selector_or_xpath=".team-member",
            verbatim_quote="John Doe - CEO",
            dom_node_screenshot="evidence/john_doe.png",
            timestamp=datetime.now(timezone.utc),
            parser_version="0.1.0-test",
            content_hash="a" * 64
        )
        
        # VERIFIED contact with complete evidence
        self.verified_contact = Contact(
            company="Example Inc.",
            person_name="John Doe",
            role_title="CEO",
            contact_type=ContactType.EMAIL,
            contact_value="john@example.com",
            evidence=self.sample_evidence,
            captured_at=datetime.now(timezone.utc)
        )
        
        # UNVERIFIED contact for testing: we override status explicitly
        # Note: The data model sets VERIFIED when evidence exists. For testing
        # filtering behavior, we simulate an UNVERIFIED record by overriding
        # the status after creation.
        self.unverified_contact = Contact(
            company="Test Corp",
            person_name="Jane Smith",
            role_title="CTO",
            contact_type=ContactType.EMAIL,
            contact_value="jane@test.com",
            evidence=self.sample_evidence,
            captured_at=datetime.now(timezone.utc)
        )
        # Override verification status to simulate UNVERIFIED record
        self.unverified_contact.verification_status = VerificationStatus.UNVERIFIED
    
    def test_exporter_initialization(self):
        """Test ContactExporter initialization creates output directory."""
        assert self.exporter.output_dir.exists()
        assert self.exporter.output_dir.is_dir()
    
    def test_filter_verified_contacts(self):
        """Test filtering to include only VERIFIED contacts."""
        contacts = [self.verified_contact, self.unverified_contact]
        
        # Mock print to capture output
        with patch('builtins.print') as mock_print:
            verified = self.exporter.filter_verified_contacts(contacts)
        
        # Should only return VERIFIED contact
        assert len(verified) == 1
        assert verified[0] == self.verified_contact
        assert verified[0].verification_status == VerificationStatus.VERIFIED
        
        # Should log filtering stats
        mock_print.assert_called_once()
        call_args = mock_print.call_args[0][0]
        assert "1 VERIFIED" in call_args
        assert "1 UNVERIFIED" in call_args
    
    def test_csv_export_verified_only(self):
        """Test CSV export includes only VERIFIED contacts."""
        contacts = [self.verified_contact, self.unverified_contact]
        
        csv_path = self.exporter.to_csv(contacts, "test_contacts.csv")
        
        # Verify file exists
        assert csv_path.exists()
        assert csv_path.name == "test_contacts.csv"
        
        # Read and validate CSV content
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        # Should only have 1 row (VERIFIED contact)
        assert len(rows) == 1
        
        # Validate row content
        row = rows[0]
        assert row['company'] == "Example Inc."
        assert row['person_name'] == "John Doe"
        assert row['contact_type'] == "email"
        assert row['contact_value'] == "john@example.com"
        assert row['verification_status'] == "VERIFIED"
        
        # Check evidence fields are present
        assert row['source_url'] == "https://example.com/team"
        assert row['selector_or_xpath'] == ".team-member"
        assert row['verbatim_quote'] == "John Doe - CEO"
        assert len(row['content_hash']) == 64
    
    def test_json_export_verified_only(self):
        """Test JSON export includes only VERIFIED contacts with nested evidence."""
        contacts = [self.verified_contact, self.unverified_contact]
        
        json_path = self.exporter.to_json(contacts, "test_contacts.json")
        
        # Verify file exists
        assert json_path.exists()
        assert json_path.name == "test_contacts.json"
        
        # Read and validate JSON content
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Should only have 1 contact (VERIFIED)
        assert len(data) == 1
        
        # Validate contact structure
        contact = data[0]
        assert contact['company'] == "Example Inc."
        assert contact['person_name'] == "John Doe"
        assert contact['contact_type'] == "email"
        assert contact['verification_status'] == "VERIFIED"
        
        # Check nested evidence structure
        evidence = contact['evidence']
        assert evidence is not None
        assert evidence['source_url'] == "https://example.com/team"
        assert evidence['selector_or_xpath'] == ".team-member"
        assert evidence['verbatim_quote'] == "John Doe - CEO"
        assert len(evidence['content_hash']) == 64
        assert evidence['parser_version'] == "0.1.0-test"
    
    def test_export_both_formats(self):
        """Test exporting to both CSV and JSON formats."""
        contacts = [self.verified_contact]
        
        csv_path, json_path = self.exporter.to_both(contacts, "test_export")
        
        # Both files should exist
        assert csv_path.exists()
        assert json_path.exists()
        assert csv_path.name == "test_export.csv"
        assert json_path.name == "test_export.json"
        
        # Both should have same contact count
        with open(csv_path, 'r', encoding='utf-8') as f:
            csv_rows = len(list(csv.DictReader(f)))
        
        with open(json_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        
        assert csv_rows == len(json_data) == 1
    
    def test_export_empty_contacts_raises_error(self):
        """Test that exporting empty contact list raises appropriate error."""
        empty_contacts = []
        
        with pytest.raises(ValueError, match="No VERIFIED contacts to export"):
            self.exporter.to_csv(empty_contacts)
        
        with pytest.raises(ValueError, match="No VERIFIED contacts to export"):
            self.exporter.to_json(empty_contacts)
    
    def test_export_only_unverified_raises_error(self):
        """Test that exporting only UNVERIFIED contacts raises error."""
        unverified_only = [self.unverified_contact]
        
        with pytest.raises(ValueError, match="No VERIFIED contacts to export"):
            self.exporter.to_csv(unverified_only)
        
        with pytest.raises(ValueError, match="No VERIFIED contacts to export"):
            self.exporter.to_json(unverified_only)
    
    def test_include_all_flag(self):
        """Test include_all flag includes UNVERIFIED contacts."""
        contacts = [self.verified_contact, self.unverified_contact]
        
        # Export with include_all=True
        csv_path = self.exporter.to_csv(contacts, "all_contacts.csv", include_all=True)
        
        # Read CSV content
        with open(csv_path, 'r', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        
        # Should have both contacts
        assert len(rows) == 2
        
        # Verify both statuses present
        statuses = [row['verification_status'] for row in rows]
        assert "VERIFIED" in statuses
        assert "UNVERIFIED" in statuses
    
    def test_auto_filename_generation(self):
        """Test automatic filename generation with timestamp."""
        contacts = [self.verified_contact]
        
        with patch('src.pipeline.export.dt') as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "20250909_120000"
            
            csv_path = self.exporter.to_csv(contacts)  # No filename provided
            
            assert csv_path.name == "contacts_20250909_120000.csv"
    
    def test_validate_export_integrity_csv(self):
        """Test export integrity validation for CSV files."""
        contacts = [self.verified_contact, self.unverified_contact]
        
        csv_path = self.exporter.to_csv(contacts, "integrity_test.csv")
        
        # Validation should pass (1 VERIFIED contact in source = 1 row in CSV)
        assert self.exporter.validate_export_integrity(contacts, csv_path) is True
    
    def test_validate_export_integrity_json(self):
        """Test export integrity validation for JSON files."""
        contacts = [self.verified_contact, self.unverified_contact]
        
        json_path = self.exporter.to_json(contacts, "integrity_test.json")
        
        # Validation should pass (1 VERIFIED contact = 1 JSON object)
        assert self.exporter.validate_export_integrity(contacts, json_path) is True
    
    def test_validate_export_integrity_nonexistent_file(self):
        """Test validation fails for nonexistent file."""
        contacts = [self.verified_contact]
        nonexistent_path = Path(self.temp_dir) / "nonexistent.csv"
        
        assert self.exporter.validate_export_integrity(contacts, nonexistent_path) is False
    
    def test_get_export_stats(self):
        """Test export statistics generation."""
        # Create additional contacts for better stats
        phone_contact = Contact(
            company="Example Inc.",
            person_name="Bob Wilson",
            role_title="Manager", 
            contact_type=ContactType.PHONE,
            contact_value="+1-555-123-4567",
            evidence=self.sample_evidence,
            captured_at=datetime.now(timezone.utc)
        )
        
        contacts = [self.verified_contact, phone_contact, self.unverified_contact]
        
        # Mock print to avoid output during test
        with patch('builtins.print'):
            stats = self.exporter.get_export_stats(contacts)
        
        # Validate statistics
        assert stats['total_contacts'] == 3
        assert stats['verified_contacts'] == 2
        assert stats['unverified_contacts'] == 1
        assert stats['contact_types']['email'] == 1
        assert stats['contact_types']['phone'] == 1
        assert stats['evidence_completeness_rate'] == 100.0  # All VERIFIED have evidence
        assert stats['ready_for_export'] is True
    
    def test_multiple_contact_types_export(self):
        """Test export with multiple contact types."""
        # Create phone contact
        phone_contact = Contact(
            company="Example Inc.",
            person_name="Alice Johnson",
            role_title="Developer",
            contact_type=ContactType.PHONE,
            contact_value="+1-555-987-6543",
            evidence=self.sample_evidence,
            captured_at=datetime.now(timezone.utc)
        )
        
        contacts = [self.verified_contact, phone_contact]
        
        json_path = self.exporter.to_json(contacts, "multi_type.json")
        
        # Read and validate
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        assert len(data) == 2
        
        # Check different contact types
        contact_types = [contact['contact_type'] for contact in data]
        assert 'email' in contact_types
        assert 'phone' in contact_types
