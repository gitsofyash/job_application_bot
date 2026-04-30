"""
Utility functions for parsing job URLs and extracting company information.
"""

import re
from urllib.parse import urlparse


def extract_company_name(url: str) -> str:
    """
    Extract a company-ish slug from a job posting URL for output filenames.
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        path = parsed.path.lower()

        if "myworkdayjobs.com" in domain:
            return sanitize_filename(domain.split(".")[0])

        if "linkedin.com" in domain and "/jobs/view" in path:
            return "linkedin-job"

        if "linkedin.com" in domain:
            if domain.startswith("careers."):
                return sanitize_filename(domain.replace("careers.", "").replace(".linkedin.com", ""))
            parts = domain.split(".")
            if parts and parts[0] not in {"www", "linkedin"}:
                return sanitize_filename(parts[0])

        if "greenhouse.io" in domain:
            company = domain.split(".greenhouse.io")[0]
            if company and company not in {"www", "greenhouse", "boards"}:
                return sanitize_filename(company)

        if "lever.co" in domain or "greenhouse.io" in domain:
            parts = path.split("/")
            for i, part in enumerate(parts):
                if part in {"careers", "boards"} and i + 1 < len(parts):
                    company = parts[i + 1]
                    if company and company not in {"jobs", "positions"}:
                        return sanitize_filename(company)

        if "careers" in domain:
            company = domain.split(".")[0]
            if company and company != "www":
                return sanitize_filename(company)

        parts = [part for part in domain.split(".") if part and part != "www"]
        if len(parts) >= 2 and parts[0] in {"jobs", "careers"}:
            return sanitize_filename(parts[1])
        if parts and len(parts[0]) > 2:
            return sanitize_filename(parts[0])

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

    return text


def create_resume_filename(company_name: str, extension: str = "pdf") -> str:
    """
    Create resume filename with company name.
    """
    return f"resume_{sanitize_filename(company_name)}.{extension}"


def create_cover_letter_filename(company_name: str, extension: str = "txt") -> str:
    """
    Create cover letter filename with company name.
    """
    return f"cover_letter_{sanitize_filename(company_name)}.{extension}"
