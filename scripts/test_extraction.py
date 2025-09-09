#!/usr/bin/env python3
"""
Manual Testing Tool for Evidence-Grade Contacts

Extracts contacts from a single URL and displays results with evidence packages.
Perfect for manual testing and validation of the pipeline.

Usage:
    python3 scripts/test_extraction.py "https://example.com/team"
    python3 scripts/test_extraction.py "https://example.com/about" --verbose
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

# Add src to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pipeline.ingest import IngestPipeline
from schemas import VerificationStatus


def print_header(title):
    """Print a formatted header."""
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")


def print_section(title):
    """Print a formatted section header."""
    print(f"\n{'-'*40}")
    print(f" {title}")
    print(f"{'-'*40}")


def format_contact(contact, index):
    """Format a single contact for display."""
    print(f"\n📧 Contact #{index + 1}")
    print(f"   Company: {contact.company}")
    print(f"   Person: {contact.person_name}")
    print(f"   Title: {contact.role_title}")
    print(f"   Type: {contact.contact_type.value}")
    print(f"   Value: {contact.contact_value}")
    print(f"   Status: {'✅ VERIFIED' if contact.verification_status == VerificationStatus.VERIFIED else '❌ UNVERIFIED'}")
    
    if contact.evidence:
        print(f"\n   📋 Evidence Package:")
        print(f"      Source: {contact.evidence.source_url}")
        print(f"      Selector: {contact.evidence.selector_or_xpath}")
        print(f"      Quote: \"{contact.evidence.verbatim_quote}\"")
        print(f"      Screenshot: {contact.evidence.dom_node_screenshot}")
        print(f"      Hash: {contact.evidence.content_hash[:16]}...")
        print(f"      Version: {contact.evidence.parser_version}")
        print(f"      Timestamp: {contact.evidence.timestamp}")


def format_pipeline_result(result):
    """Format pipeline result for display."""
    print_section("Pipeline Result")
    print(f"URL: {result.url}")
    print(f"Method: {result.method}")
    print(f"Success: {'✅' if result.success else '❌'} {result.success}")
    print(f"Status Code: {result.status_code}")
    print(f"HTML Length: {len(result.html) if result.html else 0} characters")
    
    if result.error:
        print(f"❌ Error: {result.error}")
    
    if result.escalation_decision:
        print(f"\n🔄 Escalation Decision:")
        print(f"   Escalated: {'✅' if result.escalation_decision.escalate else '❌'}")
        if result.escalation_decision.reasons:
            print(f"   Reasons: {', '.join(result.escalation_decision.reasons)}")


def export_to_json(contacts, output_file):
    """Export contacts to JSON file."""
    export_data = []
    for contact in contacts:
        # Convert to dict for JSON serialization
        contact_dict = {
            "company": contact.company,
            "person_name": contact.person_name,
            "role_title": contact.role_title,
            "contact_type": contact.contact_type.value,
            "contact_value": contact.contact_value,
            "verification_status": contact.verification_status.value,
            "captured_at": contact.captured_at.isoformat(),
            "evidence": {
                "source_url": contact.evidence.source_url,
                "selector_or_xpath": contact.evidence.selector_or_xpath,
                "verbatim_quote": contact.evidence.verbatim_quote,
                "dom_node_screenshot": contact.evidence.dom_node_screenshot,
                "timestamp": contact.evidence.timestamp.isoformat(),
                "parser_version": contact.evidence.parser_version,
                "content_hash": contact.evidence.content_hash
            } if contact.evidence else None
        }
        export_data.append(contact_dict)
    
    with open(output_file, 'w') as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Results exported to: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Test contact extraction pipeline on a single URL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python3 scripts/test_extraction.py "https://www.jacksonlewis.com/people/evan-d-beecher"
    python3 scripts/test_extraction.py "https://www.seyfarth.com/people/s/smith-john.html" --verbose
    python3 scripts/test_extraction.py "https://frostbrowntodd.com/people/john-doe/" --export results.json
        """
    )
    
    parser.add_argument(
        "url", 
        help="URL to extract contacts from"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output including HTML snippets"
    )
    parser.add_argument(
        "--export", "-e",
        help="Export results to JSON file"
    )
    parser.add_argument(
        "--evidence-dir",
        default="evidence",
        help="Directory for storing evidence screenshots (default: evidence)"
    )
    
    args = parser.parse_args()
    
    print_header("Evidence-Grade Contacts - Manual Testing")
    print(f"Testing URL: {args.url}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    
    try:
        # Initialize pipeline
        print("\n🔧 Initializing pipeline...")
        pipeline = IngestPipeline()
        
        # Run extraction
        print("🚀 Starting extraction...")
        result = pipeline.ingest(args.url)
        
        # Display pipeline result
        format_pipeline_result(result)
        
        # Display contacts
        print_section("Extracted Contacts")
        
        if not result.contacts:
            print("❌ No contacts found")
            return
        
        verified_contacts = [c for c in result.contacts if c.verification_status == VerificationStatus.VERIFIED]
        unverified_contacts = [c for c in result.contacts if c.verification_status == VerificationStatus.UNVERIFIED]
        
        print(f"📊 Summary:")
        print(f"   Total contacts: {len(result.contacts)}")
        print(f"   ✅ VERIFIED: {len(verified_contacts)}")
        print(f"   ❌ UNVERIFIED: {len(unverified_contacts)}")
        
        if verified_contacts:
            print(f"\n✅ VERIFIED CONTACTS ({len(verified_contacts)}):")
            for i, contact in enumerate(verified_contacts):
                format_contact(contact, i)
        
        if unverified_contacts and args.verbose:
            print(f"\n❌ UNVERIFIED CONTACTS ({len(unverified_contacts)}):")
            for i, contact in enumerate(unverified_contacts):
                format_contact(contact, i)
        
        # Show HTML snippet if verbose
        if args.verbose and result.html:
            print_section("HTML Sample")
            html_sample = result.html[:500] + "..." if len(result.html) > 500 else result.html
            print(html_sample)
        
        # Export if requested
        if args.export:
            export_to_json(verified_contacts, args.export)
        
        # Success summary
        print_header("Test Completed Successfully")
        print(f"✅ Pipeline method: {result.method}")
        print(f"✅ Verified contacts: {len(verified_contacts)}")
        print(f"✅ Evidence packages: {sum(1 for c in verified_contacts if c.evidence)}")
        
        if verified_contacts and all(c.evidence for c in verified_contacts):
            print("🏆 100% Evidence Completeness Rate achieved!")
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    finally:
        # Clean up pipeline resources
        try:
            pipeline.close()
        except:
            pass


if __name__ == "__main__":
    main()
