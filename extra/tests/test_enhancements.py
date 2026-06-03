#!/usr/bin/env python3
"""Test enhanced functionality"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.url_parser import extract_company_name, fix_encoding_issues, create_resume_filename, create_cover_letter_filename

# Test company name extraction
test_urls = [
    "https://lever.co/careers/google/job/123",
    "https://jobs.lever.co/openai/abc123",
    "https://amazon.greenhouse.io/boards/engineering/jobs/789",
    "https://boards.greenhouse.io/stripe/jobs/789",
    "https://jobs.ashbyhq.com/anthropic/role-id",
    "https://apply.workable.com/canonical/j/123",
    "https://linkedin.com/jobs/view/123456",
    "https://jobs.apple.com/en-us/details/123",
]

print("=" * 70)
print("COMPANY NAME EXTRACTION TESTS")
print("=" * 70)
for url in test_urls:
    company = extract_company_name(url)
    print(f"\n  URL: {url}")
    print(f"  -> Company: {company}")

# Test encoding fixes
print("\n" + "=" * 70)
print("ENCODING FIX TESTS")
print("=" * 70)
test_text = "Em-dash \u2014 and quote \u201ctest\u201d"
fixed = fix_encoding_issues(test_text)
print(f"\n  Original: {test_text}")
print(f"  Fixed: {fixed}")

# Test filename generation
print("\n" + "=" * 70)
print("FILENAME GENERATION TESTS")
print("=" * 70)
companies = ["Google", "Amazon", "Microsoft"]
for company in companies:
    resume_fn = create_resume_filename(company)
    letter_fn = create_cover_letter_filename(company)
    assert resume_fn == "Yash_Gupta_Resume.pdf"
    assert letter_fn == "Yash_Gupta_Cover_Letter.txt"
    print(f"\n  Company: {company}")
    print(f"    Resume: {resume_fn}")
    print(f"    Letter: {letter_fn}")

print("\n" + "=" * 70)
print("All tests completed successfully")
print("=" * 70)
