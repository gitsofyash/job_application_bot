"""Application tracker for generated resumes and job pipeline items."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from utils.console import SafeConsole as Console
from rich.table import Table

from config.settings import DATA_DIR
from utils.job_dedupe import is_duplicate_job, normalize_url

console = Console()

APPLICATIONS_PATH = DATA_DIR / "applications.json"

APPLICATION_STATUSES = {
    "Saved",
    "Evaluated",
    "Applied",
    "Responded",
    "Interview",
    "Offer",
    "Rejected",
    "Discarded",
    "Skipped",
}


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_applications(path: Path = APPLICATIONS_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def save_applications(applications: Iterable[dict[str, Any]], path: Path = APPLICATIONS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(list(applications), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def next_application_id(applications: list[dict[str, Any]]) -> int:
    ids = [int(app.get("id", 0)) for app in applications if str(app.get("id", "")).isdigit()]
    return max(ids, default=0) + 1


def add_application(application: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Add an application unless URL or company/title already exists."""
    applications = load_applications()
    if is_duplicate_job(application, applications):
        duplicate = next(
            app for app in applications if is_duplicate_job(application, [app])
        )
        return duplicate, False

    application = dict(application)
    application.setdefault("id", next_application_id(applications))
    application.setdefault("date", _today())
    application.setdefault("status", "Evaluated")
    application.setdefault("last_updated", _now())
    applications.append(application)
    save_applications(applications)
    return application, True


def record_pipeline_result(job: dict[str, Any], result: Any) -> tuple[dict[str, Any], bool]:
    """Create a tracker row from a completed main pipeline result."""
    extraction = getattr(result, "extraction", None)
    tailoring = getattr(result, "tailoring", None)
    matched = len(getattr(tailoring, "keywords_matched", []) or []) if tailoring else 0
    missing = len(getattr(tailoring, "keywords_missing", []) or []) if tailoring else 0
    fit_score = round((matched / max(1, matched + missing)) * 100, 2) if tailoring else None

    notes = "Generated from job pipeline"
    if getattr(result, "error", None):
        notes = f"Pipeline error: {result.error}"

    application = {
        "date": _today(),
        "company": job.get("company") or "",
        "title": job.get("title") or job.get("role") or "",
        "role": job.get("title") or job.get("role") or "",
        "url": job.get("url") or job.get("apply_link") or job.get("detail_link") or getattr(result, "job_url", ""),
        "source": job.get("source") or "",
        "ats_score": getattr(result, "ats_score", None),
        "fit_score": fit_score,
        "status": "Evaluated" if not getattr(result, "error", None) else "Skipped",
        "resume_pdf": getattr(result, "resume_path", None),
        "cover_letter": getattr(result, "cover_letter_path", None),
        "jd_file": getattr(result, "jd_text_path", None),
        "output_dir": getattr(result, "output_dir", None),
        "notes": notes,
        "last_updated": _now(),
    }
    if extraction is not None:
        application["extraction_words"] = getattr(extraction, "word_count", None)

    return add_application(application)


def update_application_status(app_id: int, status: str, notes: str = "") -> dict[str, Any]:
    canonical = status.strip()
    matches = [s for s in APPLICATION_STATUSES if s.lower() == canonical.lower()]
    if not matches:
        raise ValueError(f"Invalid status '{status}'. Use one of: {', '.join(sorted(APPLICATION_STATUSES))}")
    canonical = matches[0]

    applications = load_applications()
    for app in applications:
        if int(app.get("id", -1)) == app_id:
            app["status"] = canonical
            app["last_updated"] = _now()
            if notes:
                existing = str(app.get("notes") or "").strip()
                app["notes"] = f"{existing} | {notes}" if existing else notes
            save_applications(applications)
            return app
    raise ValueError(f"No application found with id {app_id}")


def verify_applications() -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    applications = load_applications()
    seen_urls: set[str] = set()
    seen_identity: set[tuple[str, str]] = set()

    for app in applications:
        app_id = app.get("id", "?")
        status = app.get("status")
        if status not in APPLICATION_STATUSES:
            errors.append(f"#{app_id}: invalid status '{status}'")

        url = normalize_url(app.get("url"))
        if url:
            if url in seen_urls:
                warnings.append(f"#{app_id}: duplicate URL")
            seen_urls.add(url)

        identity = (
            str(app.get("company") or "").strip().lower(),
            str(app.get("title") or app.get("role") or "").strip().lower(),
        )
        if all(identity):
            if identity in seen_identity:
                warnings.append(f"#{app_id}: duplicate company + role")
            seen_identity.add(identity)

        for field in ("resume_pdf", "cover_letter", "jd_file"):
            value = app.get(field)
            if value and not Path(str(value)).exists():
                warnings.append(f"#{app_id}: missing file in {field}: {value}")

    return errors, warnings


def tracker_stats() -> dict[str, Any]:
    applications = load_applications()
    total = len(applications)
    by_status: dict[str, int] = {}
    scores = [
        float(app["ats_score"])
        for app in applications
        if isinstance(app.get("ats_score"), (int, float))
    ]
    for app in applications:
        status = str(app.get("status") or "Unknown")
        by_status[status] = by_status.get(status, 0) + 1

    applied = sum(1 for app in applications if app.get("status") in {"Applied", "Responded", "Interview", "Offer", "Rejected"})
    interviews = sum(1 for app in applications if app.get("status") in {"Interview", "Offer"})
    return {
        "total": total,
        "by_status": by_status,
        "average_ats_score": round(sum(scores) / len(scores), 2) if scores else None,
        "applied_to_interview_rate": round((interviews / applied) * 100, 2) if applied else 0,
    }


def print_tracker(status_filter: str | None = None) -> None:
    applications = load_applications()
    if status_filter:
        applications = [
            app for app in applications
            if str(app.get("status", "")).lower() == status_filter.lower()
        ]

    table = Table(title="Application Tracker", show_header=True, header_style="bold cyan")
    table.add_column("ID", justify="right")
    table.add_column("Date")
    table.add_column("Company")
    table.add_column("Role")
    table.add_column("ATS", justify="right")
    table.add_column("Fit", justify="right")
    table.add_column("Status")
    table.add_column("Notes")
    for app in applications:
        table.add_row(
            str(app.get("id", "")),
            str(app.get("date", "")),
            str(app.get("company", ""))[:24],
            str(app.get("title") or app.get("role") or "")[:36],
            "" if app.get("ats_score") is None else str(app.get("ats_score")),
            "" if app.get("fit_score") is None else str(app.get("fit_score")),
            str(app.get("status", "")),
            str(app.get("notes", ""))[:36],
        )
    console.print(table)


def print_tracker_stats() -> None:
    stats = tracker_stats()
    console.print(f"[bold cyan]Applications:[/bold cyan] {stats['total']}")
    console.print(f"[bold cyan]Average ATS score:[/bold cyan] {stats['average_ats_score']}")
    console.print(f"[bold cyan]Applied -> interview rate:[/bold cyan] {stats['applied_to_interview_rate']}%")
    for status, count in sorted(stats["by_status"].items()):
        console.print(f"  {status}: {count}")


def print_tracker_verification() -> None:
    errors, warnings = verify_applications()
    if not errors and not warnings:
        console.print("[green]Tracker verification passed.[/green]")
        return
    for error in errors:
        console.print(f"[red]ERROR:[/red] {error}")
    for warning in warnings:
        console.print(f"[yellow]WARN:[/yellow] {warning}")
