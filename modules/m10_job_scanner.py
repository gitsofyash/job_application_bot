"""Job scanner that feeds a reusable pipeline for the resume bot."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from utils.console import SafeConsole as Console
from rich.table import Table

from config.settings import DATA_DIR, PROJECT_ROOT
from modules.m8_job_search import search_jobs_via_rss
from utils.job_dedupe import is_duplicate_job, normalize_url

console = Console()

JOB_SOURCES_PATH = PROJECT_ROOT / "config" / "job_sources.json"
PIPELINE_PATH = DATA_DIR / "job_pipeline.json"
SCAN_HISTORY_PATH = DATA_DIR / "scan_history.json"
APPLICATIONS_PATH = DATA_DIR / "applications.json"

PIPELINE_STATUSES = {"Pending", "Processed", "Skipped", "Failed"}


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_pipeline() -> list[dict[str, Any]]:
    data = _read_json(PIPELINE_PATH, [])
    return data if isinstance(data, list) else []


def save_pipeline(jobs: list[dict[str, Any]]) -> None:
    _write_json(PIPELINE_PATH, jobs)


def load_scan_history() -> list[dict[str, Any]]:
    data = _read_json(SCAN_HISTORY_PATH, [])
    return data if isinstance(data, list) else []


def load_job_sources() -> dict[str, Any]:
    data = _read_json(JOB_SOURCES_PATH, {})
    if not data:
        return {
            "title_filter": {
                "positive": ["python", "backend", "software engineer", "cloud", "developer"],
                "negative": ["senior", "staff", "principal", "manager", "director", "intern"],
            },
            "location_filter": {
                "preferred": ["remote", "india", "gurugram", "bengaluru", "hyderabad", "pune"],
                "blocked": ["us only", "canada only", "uk only", "security clearance"],
            },
            "rss_search": {"enabled": True, "max_results": 30, "max_age_hours": 24},
            "companies": [],
        }
    return data


def _next_pipeline_id(jobs: list[dict[str, Any]]) -> int:
    ids = [int(job.get("id", 0)) for job in jobs if str(job.get("id", "")).isdigit()]
    return max(ids, default=0) + 1


def _platform_api(company: dict[str, Any]) -> tuple[str, str] | None:
    platform = str(company.get("platform") or "").lower()
    url = str(company.get("url") or company.get("careers_url") or "")
    if company.get("api_url"):
        return platform or "custom", str(company["api_url"])

    if "greenhouse" in platform or "greenhouse.io" in url:
        match = re.search(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/([^/?#]+)", url)
        if match:
            return "greenhouse", f"https://boards-api.greenhouse.io/v1/boards/{match.group(1)}/jobs"

    if "lever" in platform or "jobs.lever.co" in url:
        match = re.search(r"jobs\.lever\.co/([^/?#]+)", url)
        if match:
            return "lever", f"https://api.lever.co/v0/postings/{match.group(1)}"

    if "ashby" in platform or "jobs.ashbyhq.com" in url:
        match = re.search(r"jobs\.ashbyhq\.com/([^/?#]+)", url)
        if match:
            return "ashby", f"https://api.ashbyhq.com/posting-api/job-board/{match.group(1)}?includeCompensation=true"

    if "recruitee" in platform or "recruitee.com" in url:
        match = re.search(r"https?://([^./]+)\.recruitee\.com", url)
        if match:
            return "recruitee", f"https://{match.group(1)}.recruitee.com/api/offers/"

    if "smartrecruiters" in platform or "smartrecruiters.com" in url:
        identifier = str(company.get("identifier") or "").strip()
        if not identifier:
            match = re.search(r"smartrecruiters\.com/([^/?#]+)", url)
            if match:
                identifier = match.group(1)
        if identifier:
            return "smartrecruiters", f"https://api.smartrecruiters.com/v1/companies/{identifier}/postings?limit=100"

    if "workable" in platform or "apply.workable.com" in url:
        if platform == "workable_xml" or url.endswith(".xml"):
            return "workable_xml", url
        account = str(company.get("account") or company.get("identifier") or "").strip()
        if not account:
            match = re.search(r"apply\.workable\.com/([^/?#]+)", url)
            if match:
                account = match.group(1)
        if account:
            return "workable", f"https://apply.workable.com/api/v1/widget/accounts/{account}"

    return None


def _parse_greenhouse(data: dict[str, Any], company: str) -> list[dict[str, Any]]:
    return [
        {
            "company": company,
            "title": job.get("title", ""),
            "location": (job.get("location") or {}).get("name", ""),
            "url": job.get("absolute_url", ""),
            "source": "greenhouse",
        }
        for job in data.get("jobs", [])
    ]


def _parse_lever(data: Any, company: str) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        return []
    return [
        {
            "company": company,
            "title": job.get("text", ""),
            "location": (job.get("categories") or {}).get("location", ""),
            "url": job.get("hostedUrl", ""),
            "source": "lever",
        }
        for job in data
    ]


def _parse_ashby(data: dict[str, Any], company: str) -> list[dict[str, Any]]:
    return [
        {
            "company": company,
            "title": job.get("title", ""),
            "location": job.get("location", ""),
            "url": job.get("jobUrl", ""),
            "source": "ashby",
        }
        for job in data.get("jobs", [])
    ]


def _parse_recruitee(data: Any, company: str) -> list[dict[str, Any]]:
    offers = data.get("offers", data) if isinstance(data, dict) else data
    if not isinstance(offers, list):
        return []
    jobs: list[dict[str, Any]] = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        location = offer.get("location") or offer.get("city") or offer.get("country") or ""
        if isinstance(location, dict):
            location = location.get("name") or location.get("city") or location.get("country") or ""
        jobs.append({
            "company": company,
            "title": offer.get("title", ""),
            "location": location,
            "url": offer.get("careers_apply_url") or offer.get("careers_url") or offer.get("url") or "",
            "source": "recruitee",
            "snippet": offer.get("description") or offer.get("requirements") or "",
        })
    return jobs


def _parse_smartrecruiters(data: Any, company: str) -> list[dict[str, Any]]:
    postings = data.get("content", data.get("postings", data)) if isinstance(data, dict) else data
    if not isinstance(postings, list):
        return []
    jobs: list[dict[str, Any]] = []
    for posting in postings:
        if not isinstance(posting, dict):
            continue
        location = posting.get("location") or {}
        if isinstance(location, dict):
            location_text = ", ".join(
                str(location.get(key) or "")
                for key in ("city", "region", "country")
                if location.get(key)
            )
        else:
            location_text = str(location or "")
        apply_url = posting.get("ref") or posting.get("applyUrl") or posting.get("jobAd") or ""
        if isinstance(apply_url, dict):
            apply_url = apply_url.get("applyUrl") or apply_url.get("url") or ""
        jobs.append({
            "company": company,
            "title": posting.get("name") or posting.get("title") or "",
            "location": location_text,
            "url": apply_url,
            "source": "smartrecruiters",
            "snippet": posting.get("description") or "",
        })
    return jobs


def _parse_workable(data: Any, company: str) -> list[dict[str, Any]]:
    jobs_data = []
    if isinstance(data, dict):
        jobs_data = data.get("jobs") or data.get("positions") or data.get("results") or []
    elif isinstance(data, list):
        jobs_data = data
    if not isinstance(jobs_data, list):
        return []

    jobs: list[dict[str, Any]] = []
    for item in jobs_data:
        if not isinstance(item, dict):
            continue
        location = item.get("location") or item.get("locations") or ""
        if isinstance(location, list):
            location = ", ".join(str(part) for part in location)
        if isinstance(location, dict):
            location = location.get("city") or location.get("country") or location.get("name") or ""
        shortcode = item.get("shortcode") or item.get("id") or ""
        url = item.get("url") or item.get("application_url") or item.get("apply_url") or ""
        if not url and shortcode:
            url = f"https://apply.workable.com/{company.lower().replace(' ', '-')}/j/{shortcode}/"
        jobs.append({
            "company": company,
            "title": item.get("title") or item.get("full_title") or "",
            "location": location,
            "url": url,
            "source": "workable",
            "snippet": item.get("description") or item.get("full_description") or "",
        })
    return jobs


def _strip_xml_html(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value or "").strip()


def _clean_rss_company(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    noisy = {"unknown", "base_resume.json"}
    if text.lower() in noisy:
        return ""
    return text


def _derive_company_from_title(title: str) -> tuple[str, str]:
    """Split common feed titles such as 'Role at Company' or 'Role - Company'."""
    raw = str(title or "").strip()
    patterns = [
        r"^(?P<title>.+?)\s+at\s+(?P<company>[A-Z][A-Za-z0-9&.,'() \-]{2,80})$",
        r"^(?P<title>.+?)\s+@\s+(?P<company>[A-Z][A-Za-z0-9&.,'() \-]{2,80})$",
        r"^(?P<title>.+?)\s+\|\s+(?P<company>[A-Z][A-Za-z0-9&.,'() \-]{2,80})$",
    ]
    for pattern in patterns:
        match = re.match(pattern, raw)
        if match:
            return match.group("title").strip(), match.group("company").strip()
    return raw, ""


def _derive_location_from_text(job: dict[str, Any]) -> str:
    text = " ".join(
        str(job.get(field) or "")
        for field in ("title", "snippet", "source", "location")
    )
    known_locations = [
        "Remote",
        "India",
        "Gurugram",
        "Gurgaon",
        "Bengaluru",
        "Bangalore",
        "Hyderabad",
        "Pune",
        "Noida",
        "Delhi",
        "Mumbai",
        "Chennai",
        "APAC",
        "Worldwide",
        "Global",
    ]
    found = []
    lower = text.lower()
    for location in known_locations:
        if location.lower() in lower:
            found.append(location)
    return ", ".join(dict.fromkeys(found))


def _parse_workable_xml(xml_text: str, company_filter: str | None = None) -> list[dict[str, Any]]:
    """Parse Workable's all-company XML feed when configured as platform=workable_xml."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    jobs: list[dict[str, Any]] = []
    for item in root.findall(".//job") + root.findall(".//item"):
        def text(tag: str) -> str:
            el = item.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""

        company = text("company") or text("company_name") or text("hiringOrganization")
        if company_filter and company_filter.lower() not in company.lower():
            continue
        jobs.append({
            "company": company or "Workable",
            "title": text("title"),
            "location": text("location") or text("city") or text("country"),
            "url": text("url") or text("link") or text("apply_url"),
            "source": "workable_xml",
            "snippet": _strip_xml_html(text("description")),
        })
    return jobs


def _title_allowed(title: str, config: dict[str, Any]) -> bool:
    filters = config.get("title_filter") or {}
    positive = [str(v).lower() for v in filters.get("positive", [])]
    negative = [str(v).lower() for v in filters.get("negative", [])]
    lower = title.lower()
    return (not positive or any(term in lower for term in positive)) and not any(term in lower for term in negative)


def _location_allowed(location: str, config: dict[str, Any]) -> bool:
    filters = config.get("location_filter") or {}
    blocked = [str(v).lower() for v in filters.get("blocked", [])]
    lower = location.lower()
    if any(term in lower for term in blocked):
        return False
    return True


def _india_remote_or_sponsored(job: dict[str, Any]) -> tuple[bool, str]:
    """Allow India roles, global remote roles, or foreign roles with sponsorship."""
    text = " ".join(
        str(job.get(field) or "")
        for field in ("title", "location", "snippet", "source")
    ).lower()

    if not text.strip():
        return True, "no location data"

    india_terms = [
        "india",
        "gurugram",
        "gurgaon",
        "bengaluru",
        "bangalore",
        "hyderabad",
        "pune",
        "noida",
        "delhi",
        "mumbai",
        "chennai",
    ]
    if any(term in text for term in india_terms):
        return True, "India-compatible"

    restricted_remote = [
        "us only",
        "u.s. only",
        "usa only",
        "united states only",
        "canada only",
        "uk only",
        "europe only",
        "eu only",
        "australia only",
        "must be based in the us",
        "must be located in the us",
        "authorized to work in the us",
        "security clearance",
        "green card",
        "u.s. citizen",
        "us citizen",
    ]
    if any(term in text for term in restricted_remote):
        return False, "country/work-authorization restricted"

    remote_terms = [
        "remote",
        "remote worldwide",
        "worldwide",
        "work from anywhere",
        "anywhere",
        "global remote",
        "distributed",
    ]
    if any(term in text for term in remote_terms):
        return True, "remote/global-compatible"

    sponsorship_terms = [
        "visa sponsorship",
        "sponsorship available",
        "will sponsor",
        "work visa",
        "relocation support",
        "relocation assistance",
        "sponsor visa",
    ]
    if any(term in text for term in sponsorship_terms):
        return True, "foreign role with sponsorship/relocation signal"

    foreign_location_terms = [
        "united states",
        "usa",
        "u.s.",
        "canada",
        "united kingdom",
        "uk",
        "europe",
        "germany",
        "france",
        "netherlands",
        "australia",
        "singapore",
        "dubai",
        "uae",
    ]
    if any(term in text for term in foreign_location_terms):
        return False, "outside India without remote/sponsorship signal"

    return True, "no foreign restriction found"


def _normalize_job(job: dict[str, Any]) -> dict[str, Any]:
    url = job.get("url") or job.get("apply_link") or job.get("detail_link") or ""
    title, title_company = _derive_company_from_title(str(job.get("title") or ""))
    company = _clean_rss_company(job.get("company")) or title_company or "Unknown"
    location = job.get("location") or _derive_location_from_text(job)
    return {
        "company": company,
        "title": title,
        "location": location,
        "url": url,
        "source": job.get("source") or "unknown",
        "snippet": job.get("snippet") or "",
        "date_found": _today(),
        "last_seen": _now(),
        "status": "Pending",
    }


async def _scan_company_apis(config: dict[str, Any], company_filter: str | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    offers: list[dict[str, Any]] = []
    errors: list[str] = []
    companies = config.get("companies") or []

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for company in companies:
            if company.get("enabled") is False:
                continue
            name = str(company.get("name") or "Unknown")
            if company_filter and company_filter.lower() not in name.lower():
                continue
            api = _platform_api(company)
            if not api:
                errors.append(f"{name}: no supported API detected")
                continue
            platform, url = api
            try:
                headers = {}
                if company.get("api_key_env"):
                    import os
                    api_key = os.getenv(str(company["api_key_env"]), "")
                    if api_key:
                        headers["X-SmartToken"] = api_key
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                if platform == "workable_xml":
                    jobs = _parse_workable_xml(response.text, company_filter)
                    offers.extend(_normalize_job(job) for job in jobs)
                    continue
                payload = response.json()
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                continue

            if platform == "greenhouse":
                jobs = _parse_greenhouse(payload, name)
            elif platform == "lever":
                jobs = _parse_lever(payload, name)
            elif platform == "ashby":
                jobs = _parse_ashby(payload, name)
            elif platform == "recruitee":
                jobs = _parse_recruitee(payload, name)
            elif platform == "smartrecruiters":
                jobs = _parse_smartrecruiters(payload, name)
            elif platform == "workable":
                jobs = _parse_workable(payload, name)
            else:
                jobs = []
            offers.extend(_normalize_job(job) for job in jobs)

    return offers, errors


async def scan_jobs(
    dry_run: bool = False,
    company_filter: str | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    """Scan configured sources and append new matching jobs to pipeline."""
    config = load_job_sources()
    existing_pipeline = load_pipeline()
    scan_history = load_scan_history()
    applications = _read_json(APPLICATIONS_PATH, [])
    existing = existing_pipeline + scan_history + (applications if isinstance(applications, list) else [])

    found, errors = await _scan_company_apis(config, company_filter)

    rss_config = config.get("rss_search") or {}
    if rss_config.get("enabled", True) and not company_filter:
        rss_jobs = await search_jobs_via_rss(
            max_results=int(rss_config.get("max_results", max_results or 30)),
            max_age_hours=int(rss_config.get("max_age_hours", 24)),
        )
        found.extend(_normalize_job(job) for job in rss_jobs)

    filtered_title = 0
    filtered_location = 0
    duplicates = 0
    new_jobs: list[dict[str, Any]] = []
    history_updates: list[dict[str, Any]] = []

    for job in found:
        status = "seen"
        if not _title_allowed(str(job.get("title") or ""), config):
            filtered_title += 1
            status = "skipped_title"
        else:
            eligible, eligibility_reason = _india_remote_or_sponsored(job)
            job["eligibility_reason"] = eligibility_reason
        if status == "seen" and not _location_allowed(str(job.get("location") or ""), config):
            filtered_location += 1
            status = "skipped_location"
        elif status == "seen" and not eligible:
            filtered_location += 1
            status = "skipped_location"
        elif status == "seen" and str(job.get("company") or "").lower() == "unknown":
            filtered_location += 1
            status = "skipped_unknown_company"
        elif status == "seen" and is_duplicate_job(job, existing + new_jobs):
            duplicates += 1
            status = "skipped_duplicate"
        elif status == "seen":
            new_jobs.append(job)
            status = "added"

        history_item = dict(job)
        history_item["scan_status"] = status
        history_updates.append(history_item)

    if max_results is not None:
        new_jobs = new_jobs[:max_results]

    if not dry_run:
        if new_jobs:
            next_id = _next_pipeline_id(existing_pipeline)
            for job in new_jobs:
                job["id"] = next_id
                next_id += 1
            save_pipeline(existing_pipeline + new_jobs)
        if history_updates:
            _write_json(SCAN_HISTORY_PATH, scan_history + history_updates)

    return {
        "found": len(found),
        "filtered_title": filtered_title,
        "filtered_location": filtered_location,
        "duplicates": duplicates,
        "new_jobs": new_jobs,
        "errors": errors,
        "dry_run": dry_run,
    }


def get_pipeline_job(job_id: int) -> dict[str, Any]:
    for job in load_pipeline():
        if int(job.get("id", -1)) == job_id:
            return job
    raise ValueError(f"No pipeline job found with id {job_id}")


def update_pipeline_status(job_id: int, status: str) -> dict[str, Any]:
    if status not in PIPELINE_STATUSES:
        raise ValueError(f"Invalid pipeline status '{status}'")
    jobs = load_pipeline()
    for job in jobs:
        if int(job.get("id", -1)) == job_id:
            job["status"] = status
            job["last_updated"] = _now()
            save_pipeline(jobs)
            return job
    raise ValueError(f"No pipeline job found with id {job_id}")


def clean_pipeline(remove_unknown: bool = True) -> dict[str, int]:
    """Remove low-quality pipeline rows and compact ids."""
    jobs = load_pipeline()
    kept: list[dict[str, Any]] = []
    removed_unknown = 0
    removed_duplicates = 0

    for job in jobs:
        if remove_unknown and str(job.get("company") or "").strip().lower() in {"", "unknown"}:
            removed_unknown += 1
            continue
        if is_duplicate_job(job, kept):
            removed_duplicates += 1
            continue
        kept.append(job)

    for index, job in enumerate(kept, start=1):
        job["id"] = index
    save_pipeline(kept)
    return {
        "kept": len(kept),
        "removed_unknown": removed_unknown,
        "removed_duplicates": removed_duplicates,
    }


def print_pipeline(status_filter: str | None = None) -> None:
    jobs = load_pipeline()
    if status_filter:
        jobs = [job for job in jobs if str(job.get("status", "")).lower() == status_filter.lower()]

    table = Table(title="Job Pipeline", show_header=True, header_style="bold cyan")
    table.add_column("ID", justify="right")
    table.add_column("Date")
    table.add_column("Company")
    table.add_column("Role")
    table.add_column("Location")
    table.add_column("Status")
    table.add_column("Source")
    for job in jobs:
        table.add_row(
            str(job.get("id", "")),
            str(job.get("date_found", "")),
            str(job.get("company", ""))[:22],
            str(job.get("title", ""))[:36],
            str(job.get("location", ""))[:22],
            str(job.get("status", "")),
            str(job.get("source", ""))[:18],
        )
    console.print(table)


def print_scan_summary(summary: dict[str, Any]) -> None:
    console.print("[bold cyan]Job Scan Summary[/bold cyan]")
    console.print(f"Found: {summary['found']}")
    console.print(f"Filtered by title: {summary['filtered_title']}")
    console.print(f"Filtered by location: {summary['filtered_location']}")
    console.print(f"Duplicates: {summary['duplicates']}")
    console.print(f"New jobs: {len(summary['new_jobs'])}")
    if summary["dry_run"]:
        console.print("[yellow]Dry run: no files were updated.[/yellow]")
    if summary["errors"]:
        console.print("[yellow]Errors:[/yellow]")
        for error in summary["errors"]:
            console.print(f"  - {error}")
    if summary["new_jobs"]:
        table = Table(title="New Jobs", show_header=True, header_style="bold cyan")
        table.add_column("Company")
        table.add_column("Role")
        table.add_column("Location")
        table.add_column("Source")
        for job in summary["new_jobs"][:20]:
            table.add_row(
                str(job.get("company", ""))[:24],
                str(job.get("title", ""))[:42],
                str(job.get("location", ""))[:24],
                str(job.get("source", ""))[:18],
            )
        console.print(table)
