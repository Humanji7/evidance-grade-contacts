#!/usr/bin/env python3
"""
Gold Dataset Validation Script

This script validates the quality and completeness of our gold dataset.
"""

import json
import glob
import sys
from collections import defaultdict

def validate_gold_dataset():
    """Validate all gold dataset files."""
    
    files = glob.glob("data/gold_datasets/gold_*.json")
    
    print(f"🔍 Validating {len(files)} gold dataset files...")
    
    stats = {
        "total_files": 0,
        "successful": 0,
        "failed": 0,
        "total_contacts": 0,
        "companies": defaultdict(int),
        "contact_types": defaultdict(int),
        "evidence_complete": 0
    }
    
    issues = []
    
    for file_path in sorted(files):
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            stats["total_files"] += 1
            
            # Check status
            status = data.get("status", "unknown")
            if status == "success":
                stats["successful"] += 1
            else:
                stats["failed"] += 1
                issues.append(f"❌ {file_path}: Status = {status}")
                continue
            
            # Check required fields
            required_fields = ["source_url", "timestamp", "person_name", "contacts", "content_hash"]
            missing_fields = [f for f in required_fields if f not in data]
            if missing_fields:
                issues.append(f"⚠️  {file_path}: Missing fields: {missing_fields}")
            
            # Count contacts
            contacts = data.get("contacts", [])
            stats["total_contacts"] += len(contacts)
            
            # Company stats
            company = data.get("company", "Unknown")
            stats["companies"][company] += 1
            
            # Contact types
            for contact in contacts:
                contact_type = contact.get("contact_type", "unknown")
                stats["contact_types"][contact_type] += 1
            
            # Evidence completeness (basic check)
            has_evidence = all([
                data.get("source_url"),
                data.get("timestamp"), 
                data.get("content_hash"),
                data.get("person_name"),
                len(contacts) > 0
            ])
            
            if has_evidence:
                stats["evidence_complete"] += 1
            else:
                issues.append(f"⚠️  {file_path}: Incomplete evidence package")
            
            # Show sample record
            if stats["total_files"] == 1:
                print(f"\n📋 Sample record from {file_path}:")
                print(f"   Person: {data.get('person_name', 'N/A')}")
                print(f"   Company: {data.get('company', 'N/A')}")
                print(f"   Contacts: {len(contacts)}")
                print(f"   URL: {data.get('source_url', 'N/A')}")
                
        except Exception as e:
            issues.append(f"❌ {file_path}: Error reading file - {e}")
    
    # Print results
    print(f"\n📊 Validation Results:")
    print(f"   Total files: {stats['total_files']}")
    print(f"   ✅ Successful: {stats['successful']}")
    print(f"   ❌ Failed: {stats['failed']}")
    print(f"   📞 Total contacts: {stats['total_contacts']}")
    print(f"   🎯 Evidence complete: {stats['evidence_complete']}/{stats['total_files']}")
    
    print(f"\n🏢 Companies:")
    for company, count in sorted(stats['companies'].items()):
        print(f"   {company}: {count} records")
    
    print(f"\n📱 Contact types:")
    for contact_type, count in sorted(stats['contact_types'].items()):
        print(f"   {contact_type}: {count} contacts")
    
    if issues:
        print(f"\n⚠️  Issues found:")
        for issue in issues[:10]:  # Show first 10
            print(f"   {issue}")
        if len(issues) > 10:
            print(f"   ... and {len(issues) - 10} more issues")
    else:
        print(f"\n✅ No issues found!")
    
    # Calculate quality metrics
    if stats['total_files'] > 0:
        success_rate = (stats['successful'] / stats['total_files']) * 100
        evidence_rate = (stats['evidence_complete'] / stats['total_files']) * 100
        avg_contacts = stats['total_contacts'] / stats['successful'] if stats['successful'] > 0 else 0
        
        print(f"\n📈 Quality Metrics:")
        print(f"   Success Rate: {success_rate:.1f}%")
        print(f"   Evidence Completeness Rate: {evidence_rate:.1f}%") 
        print(f"   Average Contacts per Record: {avg_contacts:.1f}")
    
    return len(issues) == 0

if __name__ == "__main__":
    success = validate_gold_dataset()
    sys.exit(0 if success else 1)
