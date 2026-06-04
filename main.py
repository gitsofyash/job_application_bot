#!/usr/bin/env python3
"""
JOB APPLICATION AUTOMATION BOT — MAIN ORCHESTRATOR

End-to-end automation for job applications:
  Module 1: Extract job description from posting
  Module 2: Tailor resume to JD using LLM
  Module 3: Generate tailored resume PDF (company-specific)
  Module 4: COMMENTED OUT - Auto-fill and submit application form
  Module 5: Generate ATS-friendly cover letter (company-specific)

ENHANCEMENTS (v2.0):
  - Company name extraction from URLs
  - 1-page strict resume enforcement
  - Character encoding fixes
  - Company-based file naming (no overwrites)

Usage:
    python main.py --url "https://jobs.example.com/job/123" [--dry-run]

Environment Variables:
    DEBUG=true            Verbose logging
    LLM_PROVIDER=COHERE   LLM backend (COHERE, OLLAMA, OPENAI, ANTHROPIC)
    HEADLESS=false        Show browser window
"""

import asyncio
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

from rich.markup import escape
from utils.console import SafeConsole as Console
from rich.table import Table
from rich.traceback import install

from config.settings import (
    PROJECT_ROOT,
    OUTPUT_DIR,
    DRY_RUN,
    DEBUG,
    BASE_RESUME_PATH,
    RESUME_TAILOR_USE_LLM,
    COVER_LETTER_USE_LLM,
    ENABLE_GEMINI_POLISH,
    GEMINI_POLISH_MIN_SCORE,
    ATS_MIN_SCORE,
    ATS_TARGET_SCORE,
    ATS_MAX_IMPROVEMENT_PASSES,
)

from modules.m1_extractor import (
    extract_job_description,
    ExtractionResult,
    LoginWallError,
    PlatformDetectionError,
    Platform,
)
from modules.m2_tailor import (
    tailor_resume,
    TailoredResume,
    build_rule_based_tailored_resume,
    improve_tailored_resume_for_ats,
    should_generate_gap_project,
)
from modules.m2_5_gap_filler import generate_gap_project
from modules.m3_generator import generate_resume_pdf
from modules.m5_coverletter import (
    generate_cover_letter,
    save_cover_letter,
    build_rule_based_cover_letter,
    is_local_ollama_available,
)
from modules.m6_gemini_polish import (
    polish_cover_letter_with_gemini,
    polish_resume_with_gemini,
)
from modules.m10_job_scanner import (
    clean_pipeline,
    get_pipeline_job,
    print_pipeline,
    print_scan_summary,
    scan_jobs,
    update_pipeline_status,
)
from modules.m11_application_tracker import (
    print_tracker,
    print_tracker_stats,
    print_tracker_verification,
    record_pipeline_result,
    update_application_status,
)
from modules.m9_profile_qa import answer_profile_question
from utils.ats_scorer import ATSScorer
from utils.url_parser import extract_company_name, fix_encoding_issues, sanitize_filename
# COMMENTED OUT: Auto-apply feature
# from modules.m4_apply import apply_to_job, ApplyResult

# Configure rich error display
install()

console = Console()

# ═══════════════════════════════════════════════════════════════
# ORCHESTRATION LOGIC
# ═══════════════════════════════════════════════════════════════


@dataclass
class PipelineResult:
    """Complete pipeline execution result"""
    job_url: str
    extraction: Optional[ExtractionResult] = None
    tailoring: Optional[TailoredResume] = None
    jd_text_path: Optional[str] = None
    output_dir: Optional[str] = None
    resume_path: Optional[str] = None
    markdown_resume_path: Optional[str] = None
    cover_letter_path: Optional[str] = None
    ats_score: Optional[float] = None
    # application: Optional[ApplyResult] = None  # COMMENTED OUT
    error: Optional[str] = None
    duration_seconds: float = 0.0


@dataclass
class JDQualityReport:
    """Heuristic confidence report for fetched job-description text."""
    word_count: int
    signal_count: int
    noise_count: int
    is_acceptable: bool
    issues: list[str]


def _manual_extraction_result(
    jd_text: str,
    source: str = "manual",
    screenshot_path: Optional[str] = None,
) -> ExtractionResult:
    """Create a normal extraction result from manually supplied JD text."""
    cleaned_text = fix_encoding_issues(jd_text).strip()
    return ExtractionResult(
        url=source,
        raw_text=cleaned_text,
        platform=Platform.UNKNOWN,
        word_count=len(cleaned_text.split()),
        success=bool(cleaned_text),
        error=None if cleaned_text else "Manual job description is empty",
        screenshot_path=screenshot_path,
    )


def prompt_for_manual_jd() -> Optional[str]:
    """Prompt for pasted JD text when CLI extraction fails and stdin is interactive."""
    if not sys.stdin.isatty():
        return None

    console.print(
        "[yellow]Paste the job description now. Finish with a blank line.[/yellow]"
    )
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip() and lines:
            break
        lines.append(line)

    manual_text = "\n".join(lines).strip()
    return manual_text or None


def prompt_enable_llm_tailoring(prompt_text: str, default: bool = False) -> bool:
    """
    Ask whether to use LLM-backed resume and cover-letter tailoring.

    Returns:
        Clean boolean for downstream pipeline logic.
    """
    if not sys.stdin.isatty():
        return default

    default_hint = "Y/n" if default else "y/N"
    valid_yes = {"y", "yes"}
    valid_no = {"n", "no"}

    while True:
        try:
            raw_response = input(f"{prompt_text} [{default_hint}] ")
        except EOFError:
            return default

        response = raw_response.strip().lower()
        if not response:
            return default
        if response in valid_yes:
            return True
        if response in valid_no:
            return False

        print("Please enter 'y' or 'n'.")


def prompt_yes_no(prompt_text: str, default: bool = False) -> bool:
    """Ask a yes/no question in interactive CLI sessions."""
    if not sys.stdin.isatty():
        return default

    default_hint = "Y/n" if default else "y/N"
    while True:
        try:
            raw_response = input(f"{prompt_text} [{default_hint}] ")
        except EOFError:
            return default
        response = raw_response.strip().lower()
        if not response:
            return default
        if response in {"y", "yes"}:
            return True
        if response in {"n", "no"}:
            return False
        print("Please enter 'y' or 'n'.")


def assess_jd_quality(jd_text: str) -> JDQualityReport:
    """Score whether the fetched text looks like a complete, useful JD."""
    text = fix_encoding_issues(jd_text or "").strip()
    lower = text.lower()
    word_count = len(text.split())
    signal_terms = (
        "responsibilities",
        "requirements",
        "qualifications",
        "minimum qualifications",
        "basic qualifications",
        "preferred qualifications",
        "what you'll do",
        "what you will do",
        "about the role",
        "job description",
        "job summary",
        "experience",
        "skills",
        "software",
        "engineer",
    )
    noise_terms = (
        "similar jobs",
        "job alert",
        "create alert",
        "privacy policy",
        "cookie",
        "terms of use",
        "sign in",
        "share job",
        "back to top",
    )
    signal_count = sum(1 for term in signal_terms if term in lower)
    noise_count = sum(1 for term in noise_terms if term in lower)
    issues = []

    if word_count < 120:
        issues.append(f"too short ({word_count} words)")
    if signal_count < 3:
        issues.append("missing role/responsibility/qualification signals")
    if noise_count >= 3:
        issues.append("contains too much navigation or career-site noise")
    if re.search(r"(?i)\b(apply now|share job|similar jobs)\b", text) and word_count < 220:
        issues.append("looks like a listing shell instead of the full JD")

    return JDQualityReport(
        word_count=word_count,
        signal_count=signal_count,
        noise_count=noise_count,
        is_acceptable=not issues,
        issues=issues,
    )


def confirm_or_replace_jd(extraction: ExtractionResult, quality: JDQualityReport) -> Optional[ExtractionResult]:
    """Let an interactive user confirm a fetched JD preview or paste the correct JD."""
    if not sys.stdin.isatty():
        return extraction if quality.is_acceptable else None

    console.print(
        f"[cyan]JD quality check:[/cyan] {quality.word_count} words, "
        f"{quality.signal_count} JD signals, {quality.noise_count} noise signals"
    )
    if quality.issues:
        console.print(f"[yellow]Potential issue: {', '.join(quality.issues)}[/yellow]")

    preview = extraction.raw_text[:900].strip()
    console.print("[bold]Fetched JD preview:[/bold]")
    console.print(f"[dim]{escape(preview)}{'...' if len(extraction.raw_text) > 900 else ''}[/dim]\n")

    prompt = "Does this look like the correct complete JD?"
    if quality.is_acceptable and prompt_yes_no(prompt, default=True):
        return extraction

    if not quality.is_acceptable:
        console.print("[yellow]This JD may be incomplete. Please paste the full JD to continue.[/yellow]")
    elif prompt_yes_no("Do you want to paste a corrected JD?", default=False):
        pass
    else:
        return extraction

    manual_text = prompt_for_manual_jd()
    if manual_text:
        return _manual_extraction_result(
            manual_text,
            source=f"manual replacement for {extraction.url}",
            screenshot_path=extraction.screenshot_path,
        )
    return extraction if quality.is_acceptable else None


def prompt_for_company_name_if_uncertain(company_name: str) -> str:
    """Ask for the company name when URL/JD extraction only found a generic fallback."""
    safe_company = sanitize_filename(company_name or "")
    uncertain_names = {
        "company",
        "job",
        "job-posting",
        "manual-jd",
        "linkedin-job",
        "unknown",
        "careers",
        "jobs",
    }
    if safe_company not in uncertain_names or not sys.stdin.isatty():
        return safe_company or "job-posting"

    while True:
        try:
            raw_response = input("Company name could not be identified. Enter company name for this resume run: ")
        except EOFError:
            return safe_company or "job-posting"

        candidate = sanitize_filename(raw_response.strip())
        if candidate and candidate not in uncertain_names:
            return candidate
        print("Please enter the actual company name, for example: Google, Microsoft, Stripe.")


def save_job_description_artifact(
    extraction: ExtractionResult,
    company_name: str,
    output_dir: Path,
) -> Path:
    """Save the exact JD text used by tailoring/scoring next to other outputs."""
    safe_company = sanitize_filename(company_name or "job-posting")
    output_path = output_dir / f"jd_{safe_company}.txt"
    output_path.write_text(extraction.raw_text, encoding="utf-8")
    console.print(f"[green]JD text saved:[/green] {output_path}")
    return output_path


def extract_company_name_from_jd(jd_text: str, fallback: str = "job-posting") -> str:
    """Best-effort company extraction from JD text with URL-derived fallback."""
    text = fix_encoding_issues(jd_text or "")
    lines = [line.strip(" -|") for line in text.splitlines() if line.strip()]
    stopwords = {
        "software engineer",
        "job description",
        "responsibilities",
        "requirements",
        "qualifications",
        "minimum qualifications",
        "basic qualifications",
        "preferred qualifications",
        "about the job",
        "about us",
        "overview",
        "apply now",
    }

    def clean_candidate(candidate: str) -> Optional[str]:
        candidate = re.sub(r"\s+", " ", candidate).strip(" .,-:|")
        candidate = re.sub(r"(?i)\s+(careers|jobs|job posting)$", "", candidate).strip()
        lower = candidate.lower()
        if not candidate or lower in stopwords:
            return None
        if len(candidate) > 70 or len(candidate.split()) > 6:
            return None
        if any(term in lower for term in ("engineer", "developer", "manager", "intern", "remote", "full-time")):
            return None
        if not re.search(r"[A-Za-z]", candidate):
            return None
        return candidate

    patterns = [
        r"(?im)^\s*(?:company|employer|organization)\s*[:\-]\s*([A-Z][A-Za-z0-9&.,' \-]{2,70})\s*$",
        r"(?im)^\s*about\s+([A-Z][A-Za-z0-9&.,' \-]{2,70})\s*$",
        r"(?i)\bjoin\s+([A-Z][A-Za-z0-9&.' \-]{2,50})\b",
        r"(?i)\bat\s+([A-Z][A-Za-z0-9&.' \-]{2,50})\s+(?:we|you|our|is|are)",
        r"(?i)([A-Z][A-Za-z0-9&.' \-]{2,50})\s+is\s+(?:hiring|looking for|seeking|a\b|an\b)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            candidate = clean_candidate(match.group(1))
            if candidate:
                return sanitize_filename(candidate)

    for line in lines[:30]:
        match = re.match(r"(?i)^([A-Z][A-Za-z0-9&.' \-]{2,50})\s+\|\s+.+$", line)
        if match:
            candidate = clean_candidate(match.group(1))
            if candidate:
                return sanitize_filename(candidate)

    return sanitize_filename(fallback)


def create_run_output_dir(company_name: str) -> Path:
    """Create output/{Company_Name}_{YYYYMMDD_HHMMSS}/ for one pipeline run."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = OUTPUT_DIR / f"{sanitize_filename(company_name)}_{timestamp}"
    output_dir = base
    suffix = 1
    while output_dir.exists():
        suffix += 1
        output_dir = Path(f"{base}_{suffix}")
    output_dir.mkdir(parents=True, exist_ok=False)
    return output_dir


def move_artifact_to_output_dir(path_text: Optional[str], output_dir: Path) -> Optional[str]:
    """Move a pre-workspace artifact, such as an extraction screenshot, into the run folder."""
    if not path_text:
        return None
    source = Path(path_text)
    if not source.exists() or source.parent.resolve() == output_dir.resolve():
        return str(source) if source.exists() else path_text
    destination = output_dir / source.name
    source.replace(destination)
    return str(destination)


def add_learning_skills_to_tailoring(
    tailoring: Optional[TailoredResume],
    technologies: list[str],
    covered_keywords: list[str],
) -> Optional[TailoredResume]:
    """Add gap-project technologies as independent-learning skills for the next render."""
    if not tailoring:
        return tailoring

    updated = tailoring.model_copy(deep=True)
    existing_skills = list(updated.skills or [])
    seen_skills = {skill.lower() for skill in existing_skills}

    for technology in technologies:
        key = technology.lower()
        if key not in seen_skills:
            existing_skills.insert(min(6, len(existing_skills)), technology)
            seen_skills.add(key)

    covered_keys = {keyword.lower() for keyword in covered_keywords}
    for keyword in covered_keywords:
        if keyword not in updated.keywords_matched:
            updated.keywords_matched.append(keyword)

    updated.skills = existing_skills[:24]
    updated.keywords_missing = [
        keyword
        for keyword in (updated.keywords_missing or [])
        if keyword.lower() not in covered_keys
    ]
    return updated


def gap_project_covers_keywords(gap_project: dict, missing_keywords: list[str]) -> list[str]:
    """Return missing keywords that are explicitly represented in the gap project."""
    project_text = " ".join(
        [
            str(gap_project.get("title", "")),
            str(gap_project.get("description", "")),
            " ".join(str(tech) for tech in gap_project.get("technologies", [])),
            " ".join(str(bullet) for bullet in gap_project.get("bullets", [])),
        ]
    ).lower()
    covered = []
    for keyword in missing_keywords:
        normalized = str(keyword).strip().lower()
        if len(normalized) >= 3 and normalized in project_text:
            covered.append(keyword)
    return covered


def gap_project_duration() -> str:
    """Use a fixed recent learning-project duration for resume display."""
    return "Jan 2026 - Mar 2026"


def compact_gap_project_text(text: str, max_length: int = 128) -> str:
    """Keep generated gap-project resume text short and sentence-complete."""
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip(" -")
    if not cleaned:
        return ""

    if len(cleaned) > max_length:
        split_match = re.search(
            r"(?i),\s+(?:with|including|and)\s+(?:containerization|multi-cloud|integration|deployment|orchestration)\b",
            cleaned,
        )
        if split_match and split_match.start() > 60:
            cleaned = cleaned[: split_match.start()].rstrip(" ,;:-")

    sentence_match = re.search(r"^(.+?[.!?])(?:\s|$)", cleaned)
    if sentence_match:
        cleaned = sentence_match.group(1).strip()

    if len(cleaned) > max_length:
        clipped = cleaned[:max_length].rstrip()
        last_space = clipped.rfind(" ")
        if last_space > max_length * 0.65:
            clipped = clipped[:last_space]
        cleaned = clipped.rstrip(" ,;:-")

    cleaned = re.sub(
        r"(?i)\s+(with|using|via|for|and|or|to|in|of|by)$",
        "",
        cleaned,
    ).rstrip(" ,;:-")
    if cleaned and cleaned[-1] not in ".!?":
        cleaned = f"{cleaned}."
    return cleaned


def compact_gap_project_bullet(description: str, technologies: list[str]) -> str:
    """Create a non-duplicative, complete bullet for generated gap projects."""
    useful_technologies = [
        tech
        for tech in technologies
        if tech.lower() not in {"python", "aws lambda", "api gateway", "dynamodb"}
    ][:5]
    if useful_technologies:
        return compact_gap_project_text(
            f"Added focused proof-of-concept coverage for {', '.join(useful_technologies)}.",
            max_length=118,
        )
    return compact_gap_project_text(description, max_length=118)


async def add_gap_project_to_resume_data(
    missing_keywords: list[str],
    resume_data_dict: Optional[dict],
) -> tuple[Optional[dict], list[str], list[str], Optional[dict]]:
    """
    Generate and insert an Independent Learning project into resume data.

    Returns updated resume data, project technologies, covered keywords, and raw
    gap project metadata.
    """
    gap_project = await generate_gap_project(missing_keywords)
    if not gap_project:
        return resume_data_dict, [], [], None

    technologies = []
    seen_technologies = set()
    for tech in gap_project.get("technologies", []):
        technology = str(tech).strip()
        key = technology.lower()
        if technology and key not in seen_technologies:
            technologies.append(technology)
            seen_technologies.add(key)

    if resume_data_dict is None:
        with open(BASE_RESUME_PATH, "r", encoding="utf-8") as f:
            updated_resume_data = json.load(f)
    else:
        updated_resume_data = json.loads(json.dumps(resume_data_dict))

    project_title = str(gap_project.get("title", "Gap Bridging Project")).strip()
    if "(Independent Learning)" not in project_title:
        project_title = f"{project_title} (Independent Learning)"

    project_description = compact_gap_project_text(gap_project.get("description", ""))
    if not project_description:
        project_description = compact_gap_project_text(
            f"Built a focused project using {', '.join(technologies[:6])}."
        )

    resume_project = {
        "title": project_title,
        "date": gap_project_duration(),
        "description": project_description,
        "technologies": technologies,
        "bullets": [compact_gap_project_bullet(project_description, technologies)],
    }

    projects = updated_resume_data.setdefault("projects", [])
    existing_titles = {
        str(project.get("title", "")).strip().lower()
        for project in projects
        if isinstance(project, dict)
    }
    if project_title.lower() not in existing_titles:
        projects.insert(0, resume_project)

    covered_keywords = gap_project_covers_keywords(gap_project, missing_keywords)
    return updated_resume_data, technologies, covered_keywords, gap_project


async def orchestrate_application(
    job_url: str,
    manual_jd_text: Optional[str] = None,
    manual_jd_source: Optional[str] = None,
    skip_apply: bool = False,
    dry_run: Optional[bool] = None,
) -> PipelineResult:
    """
    Orchestrate complete job application workflow.
    
    Pipeline:
      1. MODULE 1: Extract job description
      2. MODULE 2: Tailor resume to JD
      3. MODULE 3: Generate resume PDF
      4. MODULE 4: Auto-apply (DISABLED)
      5. MODULE 5: Generate cover letter
    
    Each module's success/failure is tracked and logged.
    
    ⚠️ FAILURE HANDLING:
      - Module 1 fails → stops pipeline, returns error
      - Module 2 fails → continues with base resume
      - Module 3 fails → continues without PDF
      - Module 4 is disabled
      - Module 5 fails → logs error but doesn't block
    
    Args:
        job_url: Job posting URL
        skip_apply: Ignored (auto-apply is disabled)
        dry_run: Ignored (auto-apply is disabled)
        
    Returns:
        PipelineResult with all module outputs
    """
    start_time = asyncio.get_event_loop().time()
    result = PipelineResult(job_url=job_url)
    
    company_name = extract_company_name(job_url) if job_url else "manual-jd"
    output_dir: Optional[Path] = None
    console.log(f"[cyan]Initial company fallback: {company_name}[/cyan]")
    
    # Load resume data early for use in cover letter generation
    try:
        with open(BASE_RESUME_PATH, "r", encoding="utf-8") as f:
            base_resume_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        base_resume_data = {}
    
    try:
        console.print(
            f"\n[bold cyan]═══════════════════════════════════════════════════════════[/bold cyan]"
        )
        console.print(
            f"[bold cyan]JOB APPLICATION AUTOMATION BOT[/bold cyan]"
        )
        console.print(
            f"[bold cyan]═══════════════════════════════════════════════════════════[/bold cyan]"
        )
        console.print(f"[bold]Job URL:[/bold] {job_url or 'manual JD input'}\n")
        
        # ═══════════════════════════════════════════════════════════════
        # MODULE 1: EXTRACT JOB DESCRIPTION
        # ═══════════════════════════════════════════════════════════════
        
        console.print(
            "[bold cyan]╔════════════════════════════════════════╗[/bold cyan]"
        )
        console.print(
            "[bold cyan]║ MODULE 1: Job Description Extraction  ║[/bold cyan]"
        )
        console.print(
            "[bold cyan]╚════════════════════════════════════════╝[/bold cyan]\n"
        )
        
        m1_start = asyncio.get_event_loop().time()
        
        if manual_jd_text:
            console.print("[cyan]Using manually supplied job description[/cyan]\n")
            extraction = _manual_extraction_result(
                manual_jd_text,
                source=manual_jd_source or job_url or "manual",
            )
        else:
            extraction = await extract_job_description(job_url)
        result.extraction = extraction
        
        m1_duration = asyncio.get_event_loop().time() - m1_start
        
        if not extraction.success:
            console.print(
                f"[red]✗ Module 1 Failed: {extraction.error}[/red]"
            )
            fallback_text = prompt_for_manual_jd()
            if fallback_text:
                console.print("[cyan]Continuing with pasted manual JD[/cyan]\n")
                extraction = _manual_extraction_result(
                    fallback_text,
                    source=f"manual fallback for {job_url}",
                    screenshot_path=extraction.screenshot_path,
                )
                result.extraction = extraction
            else:
                result.error = (
                    f"Extraction failed: {extraction.error}. "
                    "Provide --jd-file or --jd-text to continue manually."
                )
                return result

        quality = assess_jd_quality(extraction.raw_text)
        if manual_jd_text:
            console.print(
                f"[cyan]Manual JD quality:[/cyan] {quality.word_count} words, "
                f"{quality.signal_count} JD signals"
            )
            if quality.issues:
                console.print(f"[yellow]Manual JD warning: {', '.join(quality.issues)}[/yellow]")
        else:
            confirmed_extraction = confirm_or_replace_jd(extraction, quality)
            if not confirmed_extraction:
                result.error = (
                    "Fetched JD did not pass quality verification. "
                    "Paste the full JD interactively or provide --jd-file/--jd-text."
                )
                return result
            extraction = confirmed_extraction
            result.extraction = extraction
            quality = assess_jd_quality(extraction.raw_text)

        company_name = extract_company_name_from_jd(extraction.raw_text, fallback=company_name)
        company_name = prompt_for_company_name_if_uncertain(company_name)
        output_dir = create_run_output_dir(company_name)
        result.output_dir = str(output_dir)
        if extraction.screenshot_path:
            extraction.screenshot_path = move_artifact_to_output_dir(
                extraction.screenshot_path,
                output_dir,
            )
        console.print(f"[green]Run workspace:[/green] {output_dir}")

        result.jd_text_path = str(save_job_description_artifact(extraction, company_name, output_dir))
        
        console.print(
            f"[green]✓ Module 1 Complete ({m1_duration:.2f}s)[/green]\n"
        )
        console.print(f"[dim]Platform: {extraction.platform}[/dim]")
        console.print(f"[dim]Words: {extraction.word_count}[/dim]")
        if extraction.screenshot_path:
            console.print(f"[dim]Screenshot: {extraction.screenshot_path}[/dim]")
        console.print(f"[dim]Preview: {extraction.raw_text[:200]}...[/dim]\n")
        
        # ═══════════════════════════════════════════════════════════════
        # MODULE 2: TAILOR RESUME (Optimized for speed)
        # ═══════════════════════════════════════════════════════════════
        
        console.print(
            "[bold cyan]╔════════════════════════════════════════╗[/bold cyan]"
        )
        console.print(
            "[bold cyan]║ MODULE 2: LLM Resume Tailoring        ║[/bold cyan]"
        )
        console.print(
            "[bold cyan]╚════════════════════════════════════════╝[/bold cyan]\n"
        )
        
        m2_start = asyncio.get_event_loop().time()
        resume_llm_enabled = prompt_enable_llm_tailoring(
            "Enable LLM tailoring for RESUME?",
            default=RESUME_TAILOR_USE_LLM,
        )
        
        # Use the fast path for small JDs only when LLM tailoring is disabled.
        jd_word_count = len(extraction.raw_text.split()) if extraction.raw_text else 0
        if jd_word_count < 200 and not resume_llm_enabled:
            console.print(f"[yellow]⚠️ JD too small ({jd_word_count} words), using fast ATS tailoring[/yellow]\n")
            result.tailoring = build_rule_based_tailored_resume(extraction.raw_text)
        elif not resume_llm_enabled:
            console.print("[cyan]Fast ATS resume tailoring enabled (LLM prompt disabled)[/cyan]\n")
            result.tailoring = build_rule_based_tailored_resume(extraction.raw_text)
        else:
            if jd_word_count < 200:
                console.print(
                    f"[cyan]Short JD detected ({jd_word_count} words), but LLM tailoring was enabled; using LLM.[/cyan]\n"
                )
            try:
                tailored = await tailor_resume(extraction.raw_text)
                result.tailoring = tailored
                
                m2_duration = asyncio.get_event_loop().time() - m2_start
                
                console.print(
                    f"[green]✓ Module 2 Complete ({m2_duration:.2f}s)[/green]\n"
                )
                if tailored.summary:
                    summary_preview = tailored.summary[:150] if len(tailored.summary) > 150 else tailored.summary
                    console.print(f"[dim]Summary: {escape(summary_preview)}...[/dim]")
                
                skills_count = len(tailored.skills) if tailored.skills else 0
                matched_count = len(tailored.keywords_matched) if tailored.keywords_matched else 0
                missing_count = len(tailored.keywords_missing) if tailored.keywords_missing else 0
                console.print(f"[dim]Skills: {skills_count} | Matched: {matched_count} | Gap: {missing_count}[/dim]\n")
            
            except Exception as e:
                console.print(f"[yellow]⚠️ Module 2 Warning: {escape(str(e))}[/yellow]")
                console.print(f"[yellow]Continuing with base resume[/yellow]\n")
                result.tailoring = build_rule_based_tailored_resume(extraction.raw_text)
        
        # ═══════════════════════════════════════════════════════════════
        resume_data_dict = None
        gap_project_added = False
        if result.tailoring and result.tailoring.keywords_missing:
            if not should_generate_gap_project(result.tailoring):
                matched_count = len(result.tailoring.keywords_matched or [])
                missing_count = len(result.tailoring.keywords_missing or [])
                console.print(
                    "[dim]Gap project skipped: JD/resume gap is not large enough "
                    f"(matched={matched_count}, missing={missing_count}).[/dim]\n"
                )
            else:
                console.print("[bold cyan]MODULE 2.5: Gap-Bridging Project[/bold cyan]\n")
                console.print(
                    "[yellow]Large JD/resume gap detected. Adding an Independent Learning project "
                    "and listing its technologies as independent-learning skills.[/yellow]\n"
                )
                try:
                    resume_data_dict, technologies, covered_keywords, gap_project = await add_gap_project_to_resume_data(
                        result.tailoring.keywords_missing,
                        resume_data_dict,
                    )
                    if gap_project:
                        gap_project_added = True
                        project_title = str(gap_project.get("title", "Gap Bridging Project")).strip()
                        if "(Independent Learning)" not in project_title:
                            project_title = f"{project_title} (Independent Learning)"
                        base_resume_data = resume_data_dict

                        console.print(f"[green]Gap project added:[/green] {project_title}")
                        console.print(
                            "[dim]Unsupported JD keywords remain visible unless the gap project explicitly covers them.[/dim]"
                        )
                        if technologies:
                            result.tailoring = add_learning_skills_to_tailoring(
                                result.tailoring,
                                technologies,
                                covered_keywords,
                            )
                        if gap_project.get("project_path"):
                            console.print(f"[dim]Code: {gap_project['project_path']}[/dim]\n")
                except Exception as e:
                    console.print(
                        f"[yellow]Module 2.5 warning: {escape(str(e))}. Continuing without gap project.[/yellow]\n"
                    )

        # MODULE 3: GENERATE RESUME PDF
        # ═══════════════════════════════════════════════════════════════
        
        console.print(
            "[bold cyan]╔════════════════════════════════════════╗[/bold cyan]"
        )
        console.print(
            "[bold cyan]║ MODULE 3: Resume PDF Generation       ║[/bold cyan]"
        )
        console.print(
            "[bold cyan]╚════════════════════════════════════════╝[/bold cyan]\n"
        )
        
        m3_start = asyncio.get_event_loop().time()
        
        try:
            resume_path = await generate_resume_pdf(
                result.tailoring,
                company_name=company_name,
                job_description=extraction.raw_text,
                output_dir=output_dir,
                base_resume_data=resume_data_dict,
            )
            result.resume_path = str(resume_path)
            markdown_resume_path = Path(resume_path).with_suffix(".md")
            if markdown_resume_path.exists():
                result.markdown_resume_path = str(markdown_resume_path)
            
            m3_duration = asyncio.get_event_loop().time() - m3_start
            
            console.print(
                f"[green]✓ Module 3 Complete ({m3_duration:.2f}s)[/green]\n"
            )
            console.print(f"[dim]Output: {resume_path}[/dim]")
            console.print(f"[dim]Company: {company_name}[/dim]")

            ats_text_path = Path(resume_path).with_suffix(".txt")
            if ats_text_path.exists():
                scorer = ATSScorer()
                resume_text = ats_text_path.read_text(encoding="utf-8")
                score, ats_report = scorer.score_resume(resume_text, extraction.raw_text, str(ats_text_path))
                result.ats_score = round(score, 2)
                score_color = "green" if result.ats_score >= ATS_MIN_SCORE else "yellow"
                console.print(f"[bold {score_color}]ATS Score: {result.ats_score}/100[/bold {score_color}]")

                if (
                    ENABLE_GEMINI_POLISH
                    and result.tailoring
                    and result.ats_score < GEMINI_POLISH_MIN_SCORE
                    and ats_report.keywords_missing
                ):
                    try:
                        console.print("[cyan]Optional Gemini resume polish enabled[/cyan]")
                        previous_score = result.ats_score
                        result.tailoring = await polish_resume_with_gemini(
                            result.tailoring,
                            ats_report.keywords_missing,
                        )
                        resume_path = await generate_resume_pdf(
                            result.tailoring,
                            company_name=company_name,
                            job_description=extraction.raw_text,
                            output_dir=output_dir,
                            base_resume_data=resume_data_dict,
                        )
                        result.resume_path = str(resume_path)
                        markdown_resume_path = Path(resume_path).with_suffix(".md")
                        if markdown_resume_path.exists():
                            result.markdown_resume_path = str(markdown_resume_path)
                        ats_text_path = Path(resume_path).with_suffix(".txt")
                        resume_text = ats_text_path.read_text(encoding="utf-8")
                        score, ats_report = scorer.score_resume(
                            resume_text,
                            extraction.raw_text,
                            str(ats_text_path),
                        )
                        result.ats_score = round(score, 2)
                        console.print(
                            f"[bold cyan]Gemini polish score: {previous_score}/100 -> {result.ats_score}/100[/bold cyan]"
                        )
                    except Exception as e:
                        console.print(
                            f"[yellow]Gemini resume polish skipped: {escape(str(e))}[/yellow]"
                        )
                
                # RETRY LOOP: Regenerate until the configured ATS policy is met.
                retry_count = 0
                max_retries = ATS_MAX_IMPROVEMENT_PASSES
                
                while (
                    result.ats_score < ATS_TARGET_SCORE
                    and ats_report.keywords_missing
                    and retry_count < max_retries
                ):
                    retry_count += 1
                    console.print(f"[cyan]→ ATS Improvement Pass #{retry_count}/{max_retries}[/cyan]")
                    console.print(f"[yellow]Missing JD keywords: {', '.join(ats_report.keywords_missing[:10])}[/yellow]")
                    
                    improved_tailoring, added_keywords, skipped_keywords = improve_tailored_resume_for_ats(
                        result.tailoring,
                        ats_report.keywords_missing,
                    )
                    
                    if added_keywords:
                        console.print(
                            f"[cyan]  ✓ Adding truthful keywords: {', '.join(added_keywords[:5])}[/cyan]"
                        )
                    
                    if skipped_keywords and retry_count == 1:
                        console.print(
                            f"[dim]  ⊘ Skipped unsupported: {', '.join(skipped_keywords[:5])}[/dim]"
                        )
                    
                    if added_keywords:
                        previous_score = result.ats_score
                        previous_tailoring = result.tailoring
                        previous_resume_path = result.resume_path
                        previous_markdown_resume_path = result.markdown_resume_path
                        result.tailoring = improved_tailoring
                        resume_path = await generate_resume_pdf(
                            result.tailoring,
                            company_name=company_name,
                            job_description=extraction.raw_text,
                            output_dir=output_dir,
                            base_resume_data=resume_data_dict,
                        )
                        result.resume_path = str(resume_path)
                        markdown_resume_path = Path(resume_path).with_suffix(".md")
                        if markdown_resume_path.exists():
                            result.markdown_resume_path = str(markdown_resume_path)
                        ats_text_path = Path(resume_path).with_suffix(".txt")
                        resume_text = ats_text_path.read_text(encoding="utf-8")
                        score, ats_report = scorer.score_resume(resume_text, extraction.raw_text, str(ats_text_path))
                        result.ats_score = round(score, 2)
                        score_color = "green" if result.ats_score >= ATS_MIN_SCORE else "yellow"
                        console.print(f"[bold {score_color}]  → Updated ATS Score: {result.ats_score}/100[/bold {score_color}]")
                        if result.ats_score < previous_score:
                            console.print(
                                "[yellow]  Regenerated resume scored lower; restoring previous best tailoring[/yellow]"
                            )
                            result.tailoring = previous_tailoring
                            restored_resume_path = await generate_resume_pdf(
                                result.tailoring,
                                company_name=company_name,
                                job_description=extraction.raw_text,
                                output_dir=output_dir,
                                base_resume_data=resume_data_dict,
                            )
                            result.resume_path = str(restored_resume_path or previous_resume_path)
                            restored_markdown_path = Path(result.resume_path).with_suffix(".md")
                            result.markdown_resume_path = (
                                str(restored_markdown_path)
                                if restored_markdown_path.exists()
                                else previous_markdown_resume_path
                            )
                            result.ats_score = previous_score
                            break
                        if result.ats_score >= ATS_TARGET_SCORE:
                            console.print(
                                f"[green]  Target ATS score reached: {result.ats_score}/100[/green]"
                            )
                            break
                        if result.ats_score <= previous_score and result.ats_score >= ATS_MIN_SCORE:
                            console.print(
                                "[yellow]  Minimum ATS score is met and no further safe gain was found[/yellow]"
                            )
                            break
                    else:
                        console.print("[yellow]  ⚠️ No more keywords to add[/yellow]")
                        break
                
                if (
                    result.ats_score < ATS_TARGET_SCORE
                    and ats_report.keywords_missing
                    and not gap_project_added
                ):
                    console.print("[bold cyan]MODULE 2.5: Post-Retry Gap Project Fallback[/bold cyan]\n")
                    console.print(
                        "[yellow]ATS is still below the aimed value after retrying. "
                        "Adding an Independent Learning project and its project technologies to the skills line.[/yellow]"
                    )
                    try:
                        previous_score = result.ats_score
                        previous_tailoring = result.tailoring
                        previous_resume_path = result.resume_path
                        previous_markdown_resume_path = result.markdown_resume_path
                        previous_resume_data_dict = (
                            json.loads(json.dumps(resume_data_dict))
                            if resume_data_dict is not None
                            else None
                        )
                        previous_ats_report = ats_report

                        resume_data_dict, technologies, covered_keywords, gap_project = await add_gap_project_to_resume_data(
                            ats_report.keywords_missing,
                            resume_data_dict,
                        )
                        if gap_project:
                            gap_project_added = True
                            project_title = str(gap_project.get("title", "Gap Bridging Project")).strip()
                            if "(Independent Learning)" not in project_title:
                                project_title = f"{project_title} (Independent Learning)"

                            if technologies:
                                result.tailoring = add_learning_skills_to_tailoring(
                                    result.tailoring,
                                    technologies,
                                    covered_keywords,
                                )

                            resume_path = await generate_resume_pdf(
                                result.tailoring,
                                company_name=company_name,
                                job_description=extraction.raw_text,
                                output_dir=output_dir,
                                base_resume_data=resume_data_dict,
                            )
                            result.resume_path = str(resume_path)
                            markdown_resume_path = Path(resume_path).with_suffix(".md")
                            if markdown_resume_path.exists():
                                result.markdown_resume_path = str(markdown_resume_path)
                            ats_text_path = Path(resume_path).with_suffix(".txt")
                            resume_text = ats_text_path.read_text(encoding="utf-8")
                            score, ats_report = scorer.score_resume(
                                resume_text,
                                extraction.raw_text,
                                str(ats_text_path),
                            )
                            result.ats_score = round(score, 2)
                            console.print(
                                f"[bold cyan]  â†’ Gap project score: {previous_score}/100 -> {result.ats_score}/100[/bold cyan]"
                            )

                            if result.ats_score < previous_score:
                                console.print(
                                    "[yellow]  Gap project render scored lower; restoring previous best resume[/yellow]"
                                )
                                result.tailoring = previous_tailoring
                                resume_data_dict = previous_resume_data_dict
                                ats_report = previous_ats_report
                                restored_resume_path = await generate_resume_pdf(
                                    result.tailoring,
                                    company_name=company_name,
                                    job_description=extraction.raw_text,
                                    output_dir=output_dir,
                                    base_resume_data=resume_data_dict,
                                )
                                result.resume_path = str(restored_resume_path or previous_resume_path)
                                restored_markdown_path = Path(result.resume_path).with_suffix(".md")
                                result.markdown_resume_path = (
                                    str(restored_markdown_path)
                                    if restored_markdown_path.exists()
                                    else previous_markdown_resume_path
                                )
                                result.ats_score = previous_score
                            else:
                                console.print(f"[green]Gap project added:[/green] {project_title}")
                                if technologies:
                                    console.print(
                                        f"[cyan]Learning skills added: {', '.join(technologies[:8])}[/cyan]"
                                    )
                                if gap_project.get("project_path"):
                                    console.print(f"[dim]Code: {gap_project['project_path']}[/dim]")
                        else:
                            console.print("[yellow]  Gap project generator returned no project[/yellow]")
                    except Exception as e:
                        console.print(
                            f"[yellow]Post-retry gap project skipped: {escape(str(e))}[/yellow]"
                        )

                if result.ats_score >= ATS_TARGET_SCORE:
                    console.print(f"[green]✓ ATS target reached: {result.ats_score}/100[/green]")
                elif result.ats_score >= ATS_MIN_SCORE:
                    console.print(
                        f"[green]✓ ATS minimum met: {result.ats_score}/100 "
                        f"(target {ATS_TARGET_SCORE}/100)[/green]"
                    )
                elif retry_count >= max_retries:
                    console.print(
                        f"[yellow]⚠️ Max retries reached below minimum. "
                        f"Final ATS Score: {result.ats_score}/100[/yellow]"
                    )
                    if ats_report.keywords_missing:
                        console.print(f"[dim]Still missing: {', '.join(ats_report.keywords_missing[:8])}[/dim]")
            
            console.print()
        
        except Exception as e:
            console.print(f"[red]✗ Module 3 Failed: {escape(str(e))}[/red]\n")
            result.resume_path = None
        
        # ═══════════════════════════════════════════════════════════════
        # MODULE 4: AUTO-APPLY (COMMENTED OUT)
        # ═══════════════════════════════════════════════════════════════
        
        # Auto-apply feature has been disabled
        # if skip_apply:
        #     console.print(
        #         "[yellow]⊘ Skipping Module 4 (--no-apply flag)[/yellow]\n"
        #     )
        # 
        # else:
        #     console.print(
        #         "[bold cyan]╔════════════════════════════════════════╗[/bold cyan]"
        #     )
        #     console.print(
        #         "[bold cyan]║ MODULE 4: Auto-Apply ATS Automation   ║[/bold cyan]"
        #     )
        #     console.print(
        #         "[bold cyan]╚════════════════════════════════════════╝[/bold cyan]\n"
        #     )
        #     
        #     m4_start = asyncio.get_event_loop().time()
        #     
        #     try:
        #         application = await apply_to_job(
        #             job_url,
        #             resume_path=result.resume_path,
        #         )
        #         result.application = application
        #         
        #         m4_duration = asyncio.get_event_loop().time() - m4_start
        #         
        #         if application.success:
        #             console.print(
        #                 f"[green]✓ Module 4 Complete ({m4_duration:.2f}s)[/green]\n"
        #             )
        #             console.print(
        #                 f"[green]✓ Application Submitted Successfully![/green]"
        #             )
        #         else:
        #             console.print(
        #                 f"[yellow]⚠️ Module 4 Complete ({m4_duration:.2f}s)[/yellow]\n"
        #             )
        #             console.print(
        #                 f"[yellow]⚠️ Application status: {application.status}[/yellow]"
        #             )
        #         
        #         if application.screenshot_path:
        #             console.print(
        #                 f"[dim]Screenshot: {application.screenshot_path}[/dim]"
        #             )
        #         console.print()
        #     
        #     except Exception as e:
        #         console.print(f"[red]✗ Module 4 Failed: {e}[/red]\n")
        #         result.application = None
        
        # ═══════════════════════════════════════════════════════════════
        # MODULE 5: GENERATE COVER LETTER
        # ═══════════════════════════════════════════════════════════════
        
        console.print(
            "[bold cyan]╔════════════════════════════════════════╗[/bold cyan]"
        )
        console.print(
            "[bold cyan]║ MODULE 5: Generate Cover Letter       ║[/bold cyan]"
        )
        console.print(
            "[bold cyan]╚════════════════════════════════════════╝[/bold cyan]\n"
        )
        
        m5_start = asyncio.get_event_loop().time()
        cover_letter_llm_enabled = prompt_enable_llm_tailoring(
            "Enable LLM tailoring for COVER LETTER?",
            default=COVER_LETTER_USE_LLM,
        )
        
        try:
            try:
                if not cover_letter_llm_enabled:
                    raise RuntimeError("LLM prompt disabled")
                if not is_local_ollama_available():
                    raise RuntimeError("Ollama is not running at localhost:11434")
                cover_letter = await generate_cover_letter(
                    extraction.raw_text,
                    resume_data=base_resume_data,
                )
            except Exception as llm_error:
                console.print(
                    f"[yellow]LLM cover letter unavailable, using rule-based fallback: {escape(str(llm_error))}[/yellow]"
                )
                cover_letter = build_rule_based_cover_letter(
                    extraction.raw_text,
                    resume_data=base_resume_data,
                )

            if ENABLE_GEMINI_POLISH:
                try:
                    cover_letter = await polish_cover_letter_with_gemini(cover_letter)
                except Exception as e:
                    console.print(
                        f"[yellow]Gemini cover-letter polish skipped: {escape(str(e))}[/yellow]"
                    )
            
            # Save cover letter with company-based naming
            cover_letter_path = await save_cover_letter(
                cover_letter,
                company_name=company_name,
                output_dir=output_dir,
            )
            result.cover_letter_path = str(cover_letter_path)
            
            m5_duration = asyncio.get_event_loop().time() - m5_start
            
            console.print(
                f"[green]✓ Module 5 Complete ({m5_duration:.2f}s)[/green]\n"
            )
            console.print(f"[dim]Output: {cover_letter_path}[/dim]")
            console.print(f"[dim]Company: {company_name}[/dim]\n")
        
        except Exception as e:
            console.print(f"[yellow]⚠️ Module 5 Warning: {escape(str(e))}[/yellow]\n")
            result.cover_letter_path = None
        
        # ═══════════════════════════════════════════════════════════════
        # SUMMARY
        # ═══════════════════════════════════════════════════════════════
        
        duration = asyncio.get_event_loop().time() - start_time
        result.duration_seconds = duration
        
        print_pipeline_summary(result)
        
        return result
    
    except KeyboardInterrupt:
        console.print("\n[red]✗ Interrupted by user[/red]")
        result.error = "Interrupted by user"
        return result
    
    except Exception as e:
        console.print(f"\n[red]✗ Unexpected error: {escape(str(e))}[/red]")
        if DEBUG:
            import traceback
            traceback.print_exc()
        result.error = str(e)
        return result


# ═══════════════════════════════════════════════════════════════
# SUMMARY & REPORTING
# ═══════════════════════════════════════════════════════════════


def print_pipeline_summary(result: PipelineResult) -> None:
    """Print formatted summary table of all modules"""
    
    console.print(
        "\n[bold cyan]═══════════════════════════════════════════════════════════[/bold cyan]"
    )
    console.print("[bold cyan]PIPELINE EXECUTION SUMMARY[/bold cyan]")
    console.print(
        "[bold cyan]═══════════════════════════════════════════════════════════[/bold cyan]\n"
    )
    
    table = Table(title="Module Status", show_header=True, header_style="bold cyan")
    table.add_column("Module", width=30)
    table.add_column("Status", width=20)
    table.add_column("Details", width=40)
    table.add_column("Artifact", width=30)
    
    # Module 1
    if result.extraction:
        m1_status = "[green]✓ SUCCESS[/green]" if result.extraction.success else "[red]✗ FAILED[/red]"
        m1_details = f"{result.extraction.word_count} words"
        m1_artifact = result.extraction.platform
    else:
        m1_status = "[yellow]⊘ SKIPPED[/yellow]"
        m1_details = ""
        m1_artifact = ""
    
    table.add_row("Module 1: Extraction", m1_status, m1_details, m1_artifact)
    
    # Module 2
    if result.tailoring:
        m2_status = "[green]✓ SUCCESS[/green]"
        skills_count = len(result.tailoring.skills) if result.tailoring.skills else 0
        matched_count = len(result.tailoring.keywords_matched) if result.tailoring.keywords_matched else 0
        m2_details = f"{skills_count} skills, {matched_count} matched"
        missing_count = len(result.tailoring.keywords_missing) if result.tailoring.keywords_missing else 0
        m2_artifact = f"Gap: {missing_count} keywords"
    elif result.extraction and result.extraction.success:
        m2_status = "[yellow]⚠️ SKIPPED[/yellow]"
        m2_details = "Using base resume"
        m2_artifact = ""
    else:
        m2_status = "[red]✗ FAILED[/red]"
        m2_details = "No JD extracted"
        m2_artifact = ""
    
    table.add_row("Module 2: Tailoring", m2_status, m2_details, m2_artifact)
    
    # Module 3
    if result.resume_path:
        m3_status = "[green]✓ SUCCESS[/green]"
        score_suffix = f", ATS {result.ats_score}/100" if result.ats_score is not None else ""
        m3_details = f"PDF generated{score_suffix}"
        m3_artifact = Path(result.resume_path).name
    else:
        m3_status = "[yellow]⚠️ SKIPPED[/yellow]"
        m3_details = "No PDF output"
        m3_artifact = ""
    
    table.add_row("Module 3: PDF Generation", m3_status, m3_details, m3_artifact)
    
    # Module 4 - COMMENTED OUT
    # if result.application:
    #     app_status_map = {
    #         "success": "[green]✓ SUCCESS[/green]",
    #         "dry_run_completed": "[cyan]◆ DRY-RUN[/cyan]",
    #         "failed": "[red]✗ FAILED[/red]",
    #         "partial_submission": "[yellow]⚠️ PARTIAL[/yellow]",
    #     }
    #     m4_status = app_status_map.get(result.application.status, "[gray]?[/gray]")
    #     m4_details = f"{result.application.fields_filled}/{result.application.total_fields} fields"
    #     m4_artifact = Path(result.application.screenshot_path).name if result.application.screenshot_path else ""
    # else:
    #     m4_status = "[yellow]⊘ SKIPPED[/yellow]"
    #     m4_details = ""
    #     m4_artifact = ""
    # 
    # table.add_row("Module 4: Auto-Apply", m4_status, m4_details, m4_artifact)
    
    # Module 5
    if result.cover_letter_path:
        m5_status = "[green]✓ SUCCESS[/green]"
        m5_details = "Cover letter generated"
        m5_artifact = Path(result.cover_letter_path).name
    else:
        m5_status = "[yellow]⚠️ SKIPPED[/yellow]"
        m5_details = "No cover letter"
        m5_artifact = ""
    
    table.add_row("Module 5: Cover Letter", m5_status, m5_details, m5_artifact)
    
    # Overall status
    console.print(f"\n[bold]Total Duration:[/bold] {result.duration_seconds:.2f}s")
    
    if result.error:
        console.print(f"[red]Error: {result.error}[/red]")
    else:
        console.print(f"[green]✓ Pipeline completed[/green]")
    
    # Save result to JSON
    result_dir = Path(result.output_dir) if result.output_dir else OUTPUT_DIR
    result_dir.mkdir(parents=True, exist_ok=True)
    result_file = result_dir / "result.json"
    
    result_dict = {
        "job_url": result.job_url,
        "timestamp": datetime.now().isoformat(),
        "duration_seconds": result.duration_seconds,
        "extraction": result.extraction.model_dump() if result.extraction else None,
        "tailoring": result.tailoring.model_dump() if result.tailoring else None,
        "output_dir": result.output_dir,
        "jd_text_path": result.jd_text_path,
        "resume_path": result.resume_path,
        "markdown_resume_path": result.markdown_resume_path,
        "cover_letter_path": result.cover_letter_path,
        "ats_score": result.ats_score,
        # "application": result.application.model_dump() if result.application else None,  # COMMENTED OUT
        "error": result.error,
    }
    
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result_dict, f, indent=2)
    
    console.print(f"\n[dim]Result saved to: {result_file}[/dim]")


# ═══════════════════════════════════════════════════════════════
# CLI ARGUMENT PARSING
# ═══════════════════════════════════════════════════════════════


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description="Job Application Automation Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate ATS-friendly resume and cover letter:
  python main.py --url "https://jobs.example.com/job/123"

  # Ask about your saved resume/profile:
  python main.py --ask "What is my current company?"
  
  # Use OpenAI instead of Ollama:
  LLM_PROVIDER=OPENAI OPENAI_API_KEY=sk-xxx python main.py --url "..."
        """,
    )
    
    parser.add_argument(
        "--url",
        help="Job posting URL to extract JD and generate resume/cover letter",
        type=str,
        default="",
    )

    parser.add_argument(
        "--jd-file",
        help="Path to a text file containing the job description, used instead of URL extraction",
        type=str,
        default="",
    )

    parser.add_argument(
        "--jd-text",
        help="Raw job description text, used instead of URL extraction",
        type=str,
        default="",
    )

    parser.add_argument(
        "--ask",
        help="Ask a question answered only from data/base_resume.json and data/user_profile.json",
        type=str,
        default="",
    )

    parser.add_argument(
        "--scan-jobs",
        help="Scan configured job sources and add matching roles to data/job_pipeline.json",
        action="store_true",
    )

    parser.add_argument(
        "--dry-run",
        help="Preview scan results without updating pipeline/history",
        action="store_true",
    )

    parser.add_argument(
        "--scan-company",
        help="Limit --scan-jobs to one configured company name",
        type=str,
        default="",
    )

    parser.add_argument(
        "--pipeline",
        help="Show the saved job pipeline",
        action="store_true",
    )

    parser.add_argument(
        "--clean-pipeline",
        help="Remove unknown-company and duplicate rows from data/job_pipeline.json",
        action="store_true",
    )

    parser.add_argument(
        "--process-job",
        help="Run the existing resume pipeline for a job id from data/job_pipeline.json",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--tracker",
        help="Show the application tracker",
        action="store_true",
    )

    parser.add_argument(
        "--tracker-status",
        help="Filter --tracker by status",
        type=str,
        default="",
    )

    parser.add_argument(
        "--update-status",
        help="Application id to update in the tracker",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--status",
        help="New application status for --update-status",
        type=str,
        default="",
    )

    parser.add_argument(
        "--notes",
        help="Optional notes for --update-status",
        type=str,
        default="",
    )

    parser.add_argument(
        "--tracker-stats",
        help="Show application tracker statistics",
        action="store_true",
    )

    parser.add_argument(
        "--verify-tracker",
        help="Check tracker statuses, duplicates, and artifact links",
        action="store_true",
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    
    args = parser.parse_args()
    has_tracker_action = (
        args.scan_jobs
        or args.pipeline
        or args.clean_pipeline
        or args.process_job
        or args.tracker
        or args.update_status
        or args.tracker_stats
        or args.verify_tracker
    )
    if not args.url and not args.jd_file and not args.jd_text and not args.ask and not has_tracker_action:
        parser.error(
            "Provide --url, --jd-file, --jd-text, --ask, --scan-jobs, --pipeline, --process-job, or --tracker"
        )
    if args.update_status and not args.status:
        parser.error("--update-status requires --status")
    return args


# ═══════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════


async def main():
    """Main entry point"""
    args = parse_args()

    if args.scan_jobs:
        summary = await scan_jobs(
            dry_run=args.dry_run,
            company_filter=args.scan_company or None,
        )
        print_scan_summary(summary)
        sys.exit(0)

    if args.pipeline:
        print_pipeline()
        sys.exit(0)

    if args.clean_pipeline:
        cleaned = clean_pipeline()
        console.print(
            "[green]Pipeline cleaned:[/green] "
            f"kept={cleaned['kept']}, "
            f"removed_unknown={cleaned['removed_unknown']}, "
            f"removed_duplicates={cleaned['removed_duplicates']}"
        )
        sys.exit(0)

    if args.tracker:
        print_tracker(status_filter=args.tracker_status or None)
        sys.exit(0)

    if args.tracker_stats:
        print_tracker_stats()
        sys.exit(0)

    if args.verify_tracker:
        print_tracker_verification()
        sys.exit(0)

    if args.update_status:
        updated = update_application_status(args.update_status, args.status, args.notes)
        console.print(
            f"[green]Updated application #{updated['id']} to {updated['status']}[/green]"
        )
        sys.exit(0)

    if args.ask:
        response = answer_profile_question(args.ask)
        console.print("[bold cyan]Profile Answer[/bold cyan]")
        console.print(response.answer)
        if response.sources:
            console.print("\n[dim]Sources:[/dim]")
            for source in response.sources:
                console.print(f"[dim]- {source}[/dim]")
        console.print(f"[dim]Confidence: {response.confidence}[/dim]")
        sys.exit(0)

    pipeline_job = None
    if args.process_job:
        pipeline_job = get_pipeline_job(args.process_job)
        args.url = str(pipeline_job.get("url") or "")
        if not args.url:
            console.print(f"[red]Pipeline job #{args.process_job} has no URL.[/red]")
            sys.exit(1)

    manual_jd_text = args.jd_text.strip() if args.jd_text else ""
    manual_jd_source = "manual --jd-text" if manual_jd_text else None
    if args.jd_file:
        jd_file_path = Path(args.jd_file)
        manual_jd_text = jd_file_path.read_text(encoding="utf-8").strip()
        manual_jd_source = str(jd_file_path)
    
    # Run orchestration
    result = await orchestrate_application(
        job_url=args.url,
        manual_jd_text=manual_jd_text or None,
        manual_jd_source=manual_jd_source,
        skip_apply=False,  # Auto-apply is disabled, always skip
        dry_run=None,
    )

    if pipeline_job is not None:
        application, created = record_pipeline_result(pipeline_job, result)
        update_pipeline_status(
            int(pipeline_job["id"]),
            "Processed" if not result.error else "Failed",
        )
        action = "created" if created else "already existed"
        console.print(
            f"[green]Tracker application #{application['id']} {action}; pipeline job #{pipeline_job['id']} updated.[/green]"
        )
    
    # Exit with appropriate code
    if result.error:
        sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
