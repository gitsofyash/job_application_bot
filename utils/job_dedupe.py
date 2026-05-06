"""Deduplication helpers for scanned jobs and tracked applications."""

from __future__ import annotations

import re
from typing import Iterable, Mapping


def normalize_text(value: object) -> str:
    """Normalize human text for fuzzy identity comparisons."""
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_url(value: object) -> str:
    """Normalize URLs enough to catch obvious duplicates."""
    url = str(value or "").strip()
    url = re.sub(r"[?#].*$", "", url)
    return url.rstrip("/").lower()


def job_identity(job: Mapping[str, object]) -> tuple[str, str]:
    """Return the normalized company/title identity for a job."""
    company = normalize_text(job.get("company"))
    title = normalize_text(job.get("title") or job.get("role"))
    return company, title


def is_duplicate_job(job: Mapping[str, object], existing: Iterable[Mapping[str, object]]) -> bool:
    """Check whether a job already exists by URL or company/title."""
    job_url = normalize_url(job.get("url") or job.get("apply_link") or job.get("detail_link"))
    job_company, job_title = job_identity(job)

    for item in existing:
        item_url = normalize_url(item.get("url") or item.get("apply_link") or item.get("detail_link"))
        if job_url and item_url and job_url == item_url:
            return True

        item_company, item_title = job_identity(item)
        if job_company and job_title and job_company == item_company and job_title == item_title:
            return True

    return False
