"""Job scanner that feeds a reusable pipeline for the resume bot."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
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


def _title_allowed(title: str, config: dict[str, Any]) -> bool:
    filters = config.get("title_filter") or {}
    positive = [str(v).lower() for v in filters.get("positive", [])]
    negative = [str(v).lower() for v in filters.get("negative", [])]
    lower = title.lower()
    return (not positive or any(term in lower for term in positive)) and not any(term in lower for term in negative)


def _location_allowed(location: str, config: dict[str, Any]) -> bool:
    filters = config.get("location_filter") or {}
    preferred = [str(v).lower() for v in filters.get("preferred", [])]
    blocked = [str(v).lower() for v in filters.get("blocked", [])]
    lower = location.lower()
    if any(term in lower for term in blocked):
        return False
    return not preferred or not lower or any(term in lower for term in preferred)


def _normalize_job(job: dict[str, Any]) -> dict[str, Any]:
    url = job.get("url") or job.get("apply_link") or job.get("detail_link") or ""
    return {
        "company": job.get("company") or "Unknown",
        "title": job.get("title") or "",
        "location": job.get("location") or "",
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
                response = await client.get(url)
                response.raise_for_status()
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
        elif not _location_allowed(str(job.get("location") or ""), config):
            filtered_location += 1
            status = "skipped_location"
        elif is_duplicate_job(job, existing + new_jobs):
            duplicates += 1
            status = "skipped_duplicate"
        else:
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
