"""
Utility functions for parsing job URLs and extracting company information.
"""

import re
from urllib.parse import urlparse


FIXED_RESUME_BASENAME = "Yash_Gupta_Resume"
FIXED_COVER_LETTER_BASENAME = "Yash_Gupta_Cover_Letter"


def extract_company_name(url: str) -> str:
    """
    Extract a company-ish slug from a job posting URL for output filenames.
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        raw_path_parts = [part for part in parsed.path.split("/") if part]
        path_parts = [part.lower() for part in raw_path_parts]
        host_parts = [part for part in domain.split(".") if part and part != "www"]

        if "myworkdayjobs.com" in domain:
            company = host_parts[0] if host_parts else ""
            if company not in {"wd1", "wd2", "www", "myworkdayjobs"}:
                return sanitize_filename(company)

        if "boards.greenhouse.io" in domain and raw_path_parts:
            return sanitize_filename(raw_path_parts[0])

        if "greenhouse.io" in domain:
            company = domain.split(".greenhouse.io")[0]
            if company and company not in {"www", "greenhouse", "boards"}:
                return sanitize_filename(company)
            if raw_path_parts:
                return sanitize_filename(raw_path_parts[0])

        if "jobs.lever.co" in domain and raw_path_parts:
            return sanitize_filename(raw_path_parts[0])

        if "lever.co" in domain and raw_path_parts:
            for i, part in enumerate(path_parts):
                if part in {"careers", "jobs", "positions"} and i + 1 < len(raw_path_parts):
                    return sanitize_filename(raw_path_parts[i + 1])

        if "jobs.ashbyhq.com" in domain and raw_path_parts:
            return sanitize_filename(raw_path_parts[0])

        if "apply.workable.com" in domain and raw_path_parts:
            return sanitize_filename(raw_path_parts[0])

        if "smartrecruiters.com" in domain and raw_path_parts:
            return sanitize_filename(raw_path_parts[0])

        if "recruitee.com" in domain and host_parts:
            return sanitize_filename(host_parts[0])

        if "teamtailor.com" in domain and host_parts:
            return sanitize_filename(host_parts[0])

        if "linkedin.com" in domain and "/jobs/view" in parsed.path.lower():
            return "linkedin-job"

        if "linkedin.com" in domain:
            if domain.startswith("careers."):
                return sanitize_filename(domain.replace("careers.", "").replace(".linkedin.com", ""))
            if host_parts and host_parts[0] not in {"linkedin"}:
                return sanitize_filename(host_parts[0])

        if "careers" in domain:
            company = domain.split(".")[0]
            if company and company != "www":
                return sanitize_filename(company)

        if len(host_parts) >= 2 and host_parts[0] in {"jobs", "careers"}:
            return sanitize_filename(host_parts[1])
        if host_parts and len(host_parts[0]) > 2:
            return sanitize_filename(host_parts[0])

    except Exception:
        pass

    return "job-posting"


def sanitize_filename(name: str) -> str:
    """
    Sanitize string for use in filenames.
    """
    name = fix_encoding_issues(name)
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_]+", "-", name)
    name = re.sub(r"-+", "-", name)
    name = name.lower().strip("-")[:50]
    return name if name else "company"


def fix_encoding_issues(text: str) -> str:
    """
    Fix common smart punctuation and mojibake artifacts in scraped/resume text.
    """
    if not text:
        return text

    replacements = {
        "\ufeff": "",
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\u2013": "-",
        "\u2014": "-",
        "\u2022": "-",
        "\u00e2\u0080\u0093": "-",
        "\u00e2\u0080\u0094": "-",
        "\u00e2\u0080\u0099": "'",
        "\u00e2\u0080\u009c": '"',
        "\u00e2\u0080\u009d": '"',
        "\u00e2\u0153\u201c": "OK",
        "\u00e2\u0153\u2014": "ERROR",
        "\u00e2\u2020\u2019": "->",
        "\u00e2\u20ac\u00a2": "-",
        "\u00e2\u0161\u00a0\u00ef\u00b8\u008f": "WARN",
        "\u00e2\u0161\u00a0": "WARN",
        "\u00f0\u0178\u2019\u00a1": "Tip",
        "â€“": "-",
        "â€”": "-",
        "â€˜": "'",
        "â€™": "'",
        "â€œ": '"',
        "â€�": '"',
        "â€¢": "-",
        "ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“": "-",
        "ÃƒÂ¢Ã¢â€šÂ¬\"": "-",
        "ÃƒÂ¢Ã¢â€šÂ¬ ": "- ",
        "ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â": "-",
        "ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢": "'",
        "ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œ": '"',
        "ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â": '"',
        "ÃƒÂ¢Ã¢â€šÂ¬": "-",
        "Ã¢â‚¬â€œ": "-",
        "Ã¢â‚¬â€": "-",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)

    extra_replacements = {
        "â€“": "-",
        "â€”": "-",
        "â€˜": "'",
        "â€™": "'",
        "â€œ": '"',
        "â€�": '"',
        "â€¢": "-",
        "â†’": "->",
        "âœ“": "OK",
        "âœ—": "ERROR",
        "âš ï¸": "WARN",
        "âš ": "WARN",
        "âŠ˜": "-",
        "â—†": "*",
        "ðŸ’¡": "Tip",
        "\u00e2\u0153\"": "OK",
        "\u00e2\u2020'": "->",
        "Ã¢Å“â€œ": "OK",
        "Ã¢Å“â€”": "ERROR",
        "Ã¢Å¡Â Ã¯Â¸Â": "WARN",
        "Ã¢â‚¬Â¢": "-",
        "Ã¢â€ â€™": "->",
    }
    for bad, good in extra_replacements.items():
        text = text.replace(bad, good)

    text = re.sub(r"(?:â•|Ã¢â€¢Â)+", "=", text)
    text = text.replace("â•”", "+").replace("â•—", "+")
    text = text.replace("â•š", "+").replace("â•", "+")
    text = text.replace("â•‘", "|")

    return text


def create_resume_filename(company_name: str, extension: str = "pdf") -> str:
    """
    Create a stable resume filename for sharing and applicant tracking.
    """
    return f"{FIXED_RESUME_BASENAME}.{extension}"


def create_cover_letter_filename(company_name: str, extension: str = "txt") -> str:
    """
    Create a stable cover-letter filename for sharing and applicant tracking.
    """
    return f"{FIXED_COVER_LETTER_BASENAME}.{extension}"
