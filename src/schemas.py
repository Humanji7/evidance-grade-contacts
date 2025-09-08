"""
Evidence-Grade Contacts PoC - Pydantic Data Schemas

Core data models for Contact and Evidence with validation based on
Mini Evidence Package specification from README.md and WARP.md.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
import re

from pydantic import BaseModel, Field, field_validator, EmailStr


class ContactType(str, Enum):
    """Types of contact information we extract."""
    EMAIL = "email"
    PHONE = "phone"
    LINK = "link"


class VerificationStatus(str, Enum):
    """Status of record verification based on Evidence Completeness Rate."""
    VERIFIED = "VERIFIED"      # All 7 evidence fields present
    UNVERIFIED = "UNVERIFIED"  # Missing one or more evidence fields


class ContentHashAlgorithm(str, Enum):
    """Supported content hashing algorithms."""
    SHA256 = "sha256"


class Evidence(BaseModel):
    """
    Mini Evidence Package - 7 required fields for each verified record.
    
    Records missing any required field are marked UNVERIFIED and excluded 
    from exports per PoC specification.
    """
    source_url: str = Field(
        ..., 
        description="Source page URL where data was extracted"
    )
    
    selector_or_xpath: str = Field(
        ..., 
        description="CSS selector or XPath used for extraction"
    )
    
    verbatim_quote: str = Field(
        ..., 
        description="Verbatim innerText content from the DOM node"
    )
    
    dom_node_screenshot: str = Field(
        ..., 
        description="Path/reference to DOM node screenshot"
    )
    
    timestamp: datetime = Field(
        ..., 
        description="ISO 8601 extraction timestamp"
    )
    
    parser_version: str = Field(
        ..., 
        description="Tool version for reproducibility (e.g., '0.1.0-poc')"
    )
    
    content_hash: str = Field(
        ..., 
        description="SHA-256 hash of normalized node text"
    )

    @field_validator('source_url')
    @classmethod
    def validate_source_url(cls, v):
        """Validate URL format."""
        if not v.startswith(('http://', 'https://')):
            raise ValueError('source_url must be a valid HTTP/HTTPS URL')
        return v

    @field_validator('content_hash')
    @classmethod
    def validate_content_hash(cls, v):
        """Validate SHA-256 hash format."""
        if not re.match(r'^[a-f0-9]{64}$', v.lower()):
            raise ValueError('content_hash must be a valid SHA-256 hash (64 hex chars)')
        return v.lower()

    @field_validator('parser_version')
    @classmethod
    def validate_parser_version(cls, v):
        """Validate parser version follows semantic versioning pattern."""
        if not re.match(r'^\d+\.\d+\.\d+(-[a-zA-Z0-9]+)?$', v):
            raise ValueError('parser_version must follow semantic versioning (e.g., "0.1.0-poc")')
        return v


class Contact(BaseModel):
    """
    Main contact record with nested Evidence package.
    
    Based on JSON example from README.md with full traceability support.
    """
    company: str = Field(
        ..., 
        description="Company name extracted from source"
    )
    
    person_name: str = Field(
        ..., 
        description="Person's full name"
    )
    
    role_title: str = Field(
        ..., 
        description="Person's role or job title"
    )
    
    contact_type: ContactType = Field(
        ..., 
        description="Type of contact information"
    )
    
    contact_value: str = Field(
        ..., 
        description="The actual contact value (email/phone/link)"
    )
    
    evidence: Evidence = Field(
        ..., 
        description="Complete Mini Evidence Package for this contact"
    )
    
    captured_at: datetime = Field(
        ..., 
        description="Timestamp when this contact record was created"
    )
    
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.UNVERIFIED,
        description="Verification status based on Evidence Completeness Rate"
    )

    @field_validator('person_name', 'company')
    @classmethod
    def validate_non_empty_strings(cls, v):
        """Ensure critical string fields are not empty."""
        if not v or not v.strip():
            raise ValueError('Field cannot be empty')
        return v.strip()

    def model_post_init(self, __context) -> None:
        """Post-initialization validation and status setting."""
        # Validate contact_value based on contact_type
        if self.contact_type == ContactType.EMAIL:
            if not re.match(r'^[^@]+@[^@]+\.[^@]+$', self.contact_value):
                raise ValueError('Invalid email format')
        elif self.contact_type == ContactType.PHONE:
            clean_phone = re.sub(r'[\s\-\(\)\+\.]', '', self.contact_value)
            if not re.match(r'^\d{7,15}$', clean_phone):
                raise ValueError('Invalid phone format')
        elif self.contact_type == ContactType.LINK:
            if not self.contact_value.startswith(('http://', 'https://')):
                raise ValueError('Links must start with http:// or https://')
        
        # Set verification status based on evidence completeness
        if self.evidence:
            self.verification_status = VerificationStatus.VERIFIED
        else:
            self.verification_status = VerificationStatus.UNVERIFIED

    class ConfigDict:
        """Pydantic v2 configuration."""
        # Use enum values in serialization
        use_enum_values = True
        # Validate assignments
        validate_assignment = True


class ContactExport(BaseModel):
    """
    Simplified model for CSV/JSON exports.
    
    Flattens nested Evidence for easier consumption while maintaining
    all required fields from the Mini Evidence Package.
    """
    company: str
    person_name: str
    role_title: str
    contact_type: str
    contact_value: str
    captured_at: datetime
    verification_status: str
    
    # Flattened evidence fields
    source_url: str
    selector_or_xpath: str
    verbatim_quote: str
    dom_node_screenshot: str
    timestamp: datetime
    parser_version: str
    content_hash: str

    @classmethod
    def from_contact(cls, contact: Contact) -> 'ContactExport':
        """Create export model from full Contact model."""
        return cls(
            company=contact.company,
            person_name=contact.person_name,
            role_title=contact.role_title,
            contact_type=contact.contact_type.value,
            contact_value=contact.contact_value,
            captured_at=contact.captured_at,
            verification_status=contact.verification_status.value,
            source_url=contact.evidence.source_url,
            selector_or_xpath=contact.evidence.selector_or_xpath,
            verbatim_quote=contact.evidence.verbatim_quote,
            dom_node_screenshot=contact.evidence.dom_node_screenshot,
            timestamp=contact.evidence.timestamp,
            parser_version=contact.evidence.parser_version,
            content_hash=contact.evidence.content_hash,
        )

    class ConfigDict:
        """Pydantic v2 configuration for export model."""
        pass


# Example usage and validation
if __name__ == "__main__":
    from datetime import datetime
    
    # Example from README.md
    example_evidence = Evidence(
        source_url="https://example.com/company/leadership",
        selector_or_xpath="div.card:has(h3:contains('Jane Doe'))",
        verbatim_quote="Jane Doe — Head of Marketing",
        dom_node_screenshot="evidence/example_jane_doe.png",
        timestamp=datetime.fromisoformat("2025-09-04T10:15:00+00:00"),
        parser_version="0.1.0-poc",
        content_hash="a1b2c3d4e5f67890123456789012345678901234567890123456789012345678"
    )
    
    example_contact = Contact(
        company="Example Inc.",
        person_name="Jane Doe",
        role_title="Head of Marketing",
        contact_type=ContactType.EMAIL,
        contact_value="jane.doe@example.com",
        evidence=example_evidence,
        captured_at=datetime.fromisoformat("2025-09-04T10:15:05+00:00")
    )
    
    print("✅ Contact validation successful!")
    print(f"Status: {example_contact.verification_status}")
    print(f"JSON: {example_contact.model_dump_json(indent=2)}")
    
    # Test export model
    export_model = ContactExport.from_contact(example_contact)
    print("✅ Export model creation successful!")
