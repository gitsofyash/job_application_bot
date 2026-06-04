"""
Utility modules for job application bot.
"""

from .url_parser import (
    extract_company_name,
    sanitize_filename,
    fix_encoding_issues,
    create_resume_filename,
    create_cover_letter_filename,
)
from .console import SafeConsole

__all__ = [
    "extract_company_name",
    "sanitize_filename",
    "fix_encoding_issues",
    "create_resume_filename",
    "create_cover_letter_filename",
    "SafeConsole",
]
