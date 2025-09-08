"""
Test suite for EGC Pydantic schemas.

Basic validation tests for Contact and Evidence models to ensure
they meet Mini Evidence Package requirements.
"""

import pytest
from datetime import datetime
from src.schemas import Contact, Evidence, ContactType, VerificationStatus, ContactExport


class TestEvidence:
    """Test cases for Evidence model (Mini Evidence Package)."""
    
    def test_valid_evidence_creation(self):
        """Test creating a valid Evidence object with all 7 required fields."""
        evidence = Evidence(
            source_url="https://example.com/team",
            selector_or_xpath="div.person:nth-child(1)",
            verbatim_quote="John Doe - CEO",
            dom_node_screenshot="evidence/john_doe.png",
            timestamp=datetime.now(),
            parser_version="0.1.0-poc",
            content_hash="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        )
        
        assert evidence.source_url == "https://example.com/team"
        assert evidence.parser_version == "0.1.0-poc"
        assert len(evidence.content_hash) == 64
    
    def test_invalid_url_raises_error(self):
        """Test that invalid URLs raise validation errors."""
        with pytest.raises(ValueError, match="source_url must be a valid HTTP/HTTPS URL"):
            Evidence(
                source_url="ftp://example.com",
                selector_or_xpath="div.person",
                verbatim_quote="Test",
                dom_node_screenshot="test.png",
                timestamp=datetime.now(),
                parser_version="0.1.0-poc",
                content_hash="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
            )
    
    def test_invalid_hash_raises_error(self):
        """Test that invalid SHA-256 hashes raise validation errors."""
        with pytest.raises(ValueError, match="content_hash must be a valid SHA-256 hash"):
            Evidence(
                source_url="https://example.com/team",
                selector_or_xpath="div.person",
                verbatim_quote="Test",
                dom_node_screenshot="test.png",
                timestamp=datetime.now(),
                parser_version="0.1.0-poc",
                content_hash="invalid_hash"
            )


class TestContact:
    """Test cases for Contact model."""
    
    @pytest.fixture
    def valid_evidence(self):
        """Fixture providing valid Evidence object."""
        return Evidence(
            source_url="https://example.com/team",
            selector_or_xpath="div.person:nth-child(1)",
            verbatim_quote="Jane Smith - CTO",
            dom_node_screenshot="evidence/jane_smith.png",
            timestamp=datetime.now(),
            parser_version="0.1.0-poc",
            content_hash="abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        )
    
    def test_valid_contact_creation(self, valid_evidence):
        """Test creating a valid Contact with all required fields."""
        contact = Contact(
            company="Tech Corp",
            person_name="Jane Smith",
            role_title="Chief Technology Officer",
            contact_type=ContactType.EMAIL,
            contact_value="jane.smith@techcorp.com",
            evidence=valid_evidence,
            captured_at=datetime.now()
        )
        
        assert contact.company == "Tech Corp"
        assert contact.person_name == "Jane Smith"
        assert contact.contact_type == ContactType.EMAIL
        assert contact.verification_status == VerificationStatus.VERIFIED
    
    def test_email_validation(self, valid_evidence):
        """Test email validation for EMAIL contact type."""
        # Valid email should work
        contact = Contact(
            company="Tech Corp",
            person_name="John Doe",
            role_title="Developer",
            contact_type=ContactType.EMAIL,
            contact_value="john@example.com",
            evidence=valid_evidence,
            captured_at=datetime.now()
        )
        assert contact.contact_value == "john@example.com"
        
        # Invalid email should raise error
        with pytest.raises(ValueError, match="Invalid email format"):
            Contact(
                company="Tech Corp",
                person_name="John Doe",
                role_title="Developer",
                contact_type=ContactType.EMAIL,
                contact_value="invalid-email",
                evidence=valid_evidence,
                captured_at=datetime.now()
            )
    
    def test_phone_validation(self, valid_evidence):
        """Test phone validation for PHONE contact type."""
        # Valid phone formats
        valid_phones = [
            "+1-555-123-4567",
            "555.123.4567",
            "(555) 123-4567",
            "15551234567"
        ]
        
        for phone in valid_phones:
            contact = Contact(
                company="Tech Corp",
                person_name="John Doe",
                role_title="Developer",
                contact_type=ContactType.PHONE,
                contact_value=phone,
                evidence=valid_evidence,
                captured_at=datetime.now()
            )
            assert contact.contact_value == phone
    
    def test_empty_string_validation(self, valid_evidence):
        """Test that empty strings are not allowed for critical fields."""
        with pytest.raises(ValueError, match="Field cannot be empty"):
            Contact(
                company="",  # Empty company name
                person_name="John Doe",
                role_title="Developer",
                contact_type=ContactType.EMAIL,
                contact_value="john@example.com",
                evidence=valid_evidence,
                captured_at=datetime.now()
            )


class TestContactExport:
    """Test cases for ContactExport model."""
    
    def test_export_model_creation(self):
        """Test creating export model from Contact model."""
        evidence = Evidence(
            source_url="https://example.com/about",
            selector_or_xpath="div.founder",
            verbatim_quote="Alice Johnson - Founder & CEO",
            dom_node_screenshot="evidence/alice_johnson.png",
            timestamp=datetime.now(),
            parser_version="0.1.0-poc",
            content_hash="fedcba0987654321fedcba0987654321fedcba0987654321fedcba0987654321"
        )
        
        contact = Contact(
            company="Startup Inc",
            person_name="Alice Johnson",
            role_title="Founder & CEO",
            contact_type=ContactType.EMAIL,
            contact_value="alice@startup.com",
            evidence=evidence,
            captured_at=datetime.now()
        )
        
        export = ContactExport.from_contact(contact)
        
        assert export.company == "Startup Inc"
        assert export.person_name == "Alice Johnson"
        assert export.contact_type == "email"  # Enum value
        assert export.verification_status == "VERIFIED"  # Enum value
        assert export.source_url == evidence.source_url
        assert export.content_hash == evidence.content_hash


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
