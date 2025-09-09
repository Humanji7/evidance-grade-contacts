#!/usr/bin/env python3
"""
Gold Dataset Extractor for Evidence-Grade Contacts

This script uses Playwright to extract contact information from web pages
and create gold dataset entries for testing the main EGC pipeline.
"""

import json
import sys
import hashlib
from datetime import datetime
from playwright.sync_api import sync_playwright
from urllib.parse import urlparse


def extract_contacts(url, max_wait=10000):
    """Extract contact information from a web page using Playwright."""
    
    result = {
        "source_url": url,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "extraction_method": "playwright",
        "status": "unknown",
        "contacts": [],
        "errors": []
    }
    
    try:
        with sync_playwright() as p:
            # Launch browser with security-first settings
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-dev-shm-usage',     # Prevent /dev/shm issues in containers
                    '--disable-gpu',                # Disable GPU for headless
                    '--disable-extensions',         # No browser extensions
                    '--disable-plugins',            # No plugins
                    '--no-first-run',               # Skip first run setup
                    '--disable-default-apps',       # No default apps
                    '--disable-background-timer-throttling',  # Consistent timing
                ]  # Note: --no-sandbox REMOVED for security
            )
            
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
            )
            
            page = context.new_page()
            
            print(f"Loading {url}...")
            
            # Navigate to page with timeout
            response = page.goto(url, wait_until="load", timeout=max_wait*2)
            
            if not response:
                result["status"] = "failed"
                result["errors"].append("No response received")
                return result
                
            if response.status >= 400:
                result["status"] = "failed" 
                result["errors"].append(f"HTTP {response.status}")
                return result
            
            # Wait for content to load
            page.wait_for_timeout(2000)
            
            # Extract page info
            title = page.title()
            result["page_title"] = title
            
            # Look for person name (common patterns)
            person_name = None
            name_selectors = [
                "h1",
                "h1.person-name", 
                ".name h1",
                ".profile-name",
                ".attorney-name",
                "[data-name]",
                ".person-title h1"
            ]
            
            for selector in name_selectors:
                try:
                    element = page.query_selector(selector)
                    if element:
                        text = element.inner_text().strip()
                        if text and len(text.split()) >= 2:  # Likely a full name
                            person_name = text
                            break
                except Exception:
                    continue
            
            # If no name found, extract from title or URL
            if not person_name:
                if title and title not in ["Just a moment...", "Loading..."]:
                    # Extract name from title (e.g., "John Smith - Company")
                    parts = title.split(" - ")
                    if len(parts) > 0:
                        candidate = parts[0].strip()
                        if len(candidate.split()) >= 2:
                            person_name = candidate
                
                # Last resort: extract from URL
                if not person_name:
                    url_path = urlparse(url).path
                    if "/people/" in url_path:
                        name_part = url_path.split("/people/")[-1].replace(".html", "").replace("-", " ")
                        person_name = name_part.title()
            
            # Look for role/title
            role_title = None
            title_selectors = [
                ".title",
                ".job-title", 
                ".role",
                ".position",
                ".attorney-title",
                "h2",
                ".subtitle"
            ]
            
            for selector in title_selectors:
                try:
                    element = page.query_selector(selector)
                    if element:
                        text = element.inner_text().strip()
                        if text and not text.lower() in ["attorney", "lawyer"]:
                            role_title = text
                            break
                except Exception:
                    continue
            
            # Look for contact information
            contacts = []
            
            # Email extraction
            email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
            page_text = page.content()
            
            import re
            emails = re.findall(email_pattern, page_text)
            for email in set(emails):  # Remove duplicates
                if not email.endswith(('.png', '.jpg', '.gif')):  # Skip image URLs
                    contacts.append({
                        "contact_type": "email",
                        "contact_value": email,
                        "extraction_method": "regex_content"
                    })
            
            # Phone extraction  
            phone_selectors = [
                "[href^='tel:']",
                ".phone",
                ".telephone"
            ]
            
            for selector in phone_selectors:
                try:
                    elements = page.query_selector_all(selector)
                    for element in elements:
                        if selector.startswith("[href"):
                            phone = element.get_attribute("href").replace("tel:", "")
                        else:
                            phone = element.inner_text().strip()
                        
                        if phone:
                            contacts.append({
                                "contact_type": "phone",
                                "contact_value": phone,
                                "extraction_method": f"selector_{selector}"
                            })
                except Exception:
                    continue
            
            # Create content hash
            content_hash = hashlib.sha256(
                f"{person_name}{role_title}{str(contacts)}".encode()
            ).hexdigest()[:16]
            
            # Build result
            if person_name:
                result["status"] = "success"
                result["person_name"] = person_name
                result["role_title"] = role_title
                result["contacts"] = contacts
                result["content_hash"] = content_hash
                
                # Determine company from URL or page
                domain = urlparse(url).netloc
                company = domain.replace("www.", "").replace(".com", "").title()
                result["company"] = company
                
            else:
                result["status"] = "partial"
                result["errors"].append("No person name found")
            
            browser.close()
            
    except Exception as e:
        result["status"] = "failed"
        result["errors"].append(str(e))
    
    return result


def save_gold_entry(data, filename=None):
    """Save extracted data as gold dataset entry."""
    
    if not filename:
        domain = urlparse(data["source_url"]).netloc.replace("www.", "")
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"data/gold_datasets/gold_{domain}_{timestamp}.json"
    
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"✅ Saved gold dataset entry: {filename}")
    return filename


def main():
    """Main execution function."""
    
    if len(sys.argv) < 2:
        print("Usage: python3 gold_extractor.py <url1> [url2] ...")
        print("Example: python3 gold_extractor.py https://example.com/people/john-smith")
        sys.exit(1)
    
    urls = sys.argv[1:]
    results = []
    
    print(f"🚀 Starting gold dataset extraction for {len(urls)} URLs...")
    
    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}] Processing: {url}")
        
        try:
            result = extract_contacts(url)
            results.append(result)
            
            if result["status"] == "success":
                print(f"✅ Success: {result.get('person_name', 'Unknown')} - {result.get('role_title', 'No title')}")
                print(f"   Contacts: {len(result.get('contacts', []))}")
                save_gold_entry(result)
                
            elif result["status"] == "partial":
                print(f"⚠️  Partial: Some data extracted")
                print(f"   Errors: {', '.join(result.get('errors', []))}")
                save_gold_entry(result)
                
            else:
                print(f"❌ Failed: {', '.join(result.get('errors', []))}")
                
        except Exception as e:
            print(f"❌ Exception processing {url}: {e}")
            results.append({
                "source_url": url,
                "status": "exception", 
                "errors": [str(e)]
            })
    
    # Summary
    successful = sum(1 for r in results if r["status"] == "success")
    partial = sum(1 for r in results if r["status"] == "partial")
    failed = len(results) - successful - partial
    
    print(f"\n📊 Summary:")
    print(f"   ✅ Successful: {successful}")
    print(f"   ⚠️  Partial: {partial}")
    print(f"   ❌ Failed: {failed}")
    print(f"   📁 Files saved in: data/gold_datasets/")


if __name__ == "__main__":
    main()
