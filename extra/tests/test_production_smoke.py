#!/usr/bin/env python3
"""Production smoke checks for the job application bot."""

import json
import io
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.m1_extractor import clean_job_description_text
from modules.m2_tailor import (
    ExperienceItem,
    TailoredResume,
    build_rule_based_tailored_resume,
    improve_tailored_resume_for_ats,
    should_generate_gap_project,
)
from modules.m3_generator import merge_resume_data, render_html_resume
from modules.m3_generator import trim_summary_text
from modules.m3_generator import trim_bullet_point, close_sentence
from modules.m3_generator import DENSITY_PROFILES
from modules.m5_coverletter import format_resume_context
from modules.m9_profile_qa import answer_profile_question
from job_application_bot import APP_NAME, APP_VERSION
from job_application_bot.cli import run
from job_application_bot.orchestrator import orchestrate_application as package_orchestrate_application
from job_application_bot.profile_qa import answer_profile_question as package_answer_profile_question
from job_application_bot.web import _result_payload, parse_args as parse_web_args
from main import (
    assess_jd_quality,
    extract_company_name_from_jd,
    prompt_for_company_name_if_uncertain,
)
from utils.console import SafeConsole
from utils.url_parser import (
    create_cover_letter_filename,
    create_resume_filename,
    extract_company_name,
    fix_encoding_issues,
)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_json(path: str) -> dict:
    return json.loads((PROJECT_ROOT / path).read_text(encoding="utf-8"))


def test_env_example_is_clean() -> None:
    content = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    for marker in ("<<<<<<<", "=======", ">>>>>>>"):
        assert_true(marker not in content, f".env.example contains conflict marker {marker}")
    assert_true("ATS_MIN_SCORE=90" in content, "ATS score policy missing from .env.example")
    assert_true("PYTHONDONTWRITEBYTECODE=1" in content, "bytecode setting missing from .env.example")


def test_package_entrypoint_is_importable() -> None:
    assert_true(APP_NAME == "job-application-bot", "package app name changed")
    assert_true(bool(APP_VERSION), "package app version is empty")
    assert_true(callable(run), "package CLI run function is not importable")
    assert_true(callable(package_orchestrate_application), "package orchestrator facade is not importable")
    assert_true(callable(package_answer_profile_question), "package profile Q&A facade is not importable")
    assert_true(parse_web_args(["--port", "9999"]).port == 9999, "web server args are not parsed")


def test_web_result_payload_maps_artifacts() -> None:
    class DummyResult:
        job_url = "https://jobs.example.com/role"
        error = None
        output_dir = str(PROJECT_ROOT / "output" / "example_20260604_111111")
        resume_path = str(PROJECT_ROOT / "output" / "example_20260604_111111" / "resume.pdf")
        markdown_resume_path = None
        cover_letter_path = None
        jd_text_path = None
        ats_score = 91.5
        duration_seconds = 12.25

    payload = _result_payload(DummyResult())
    assert_true(payload["success"], "web payload did not mark successful result")
    assert_true(payload["company"] == "example", "web payload company extraction failed")
    assert_true(payload["artifacts"][0]["url"].startswith("/artifacts/"), "artifact URL was not exposed")


def test_jd_cleaner_removes_noise() -> None:
    raw = """
    Skip to main content
    Career Search
    REQ ID: 123
    Full Stack Developer I
    Description
    Build scalable APIs and collaborate with engineers.
    Knowledge, Skills and Abilities
    Analytical Skills
    Similar Jobs
    Apply Now
    Cookie Consent
    """
    cleaned = clean_job_description_text(raw)
    assert_true("Skip to main content" not in cleaned, "navigation noise was not removed")
    assert_true("Similar Jobs" not in cleaned, "similar jobs noise was not removed")
    assert_true("Build scalable APIs" in cleaned, "job content was removed incorrectly")


def test_jd_quality_rejects_incomplete_fetches() -> None:
    weak = "Apply now\nShare job\nSimilar Jobs\nSoftware Engineer"
    strong = """
    Company: Stripe
    Software Engineer
    Job Description
    Responsibilities include designing backend services, REST APIs, distributed systems,
    data pipelines, monitoring, testing, and collaborating with product teams.
    Requirements include Python, JavaScript, SQL, cloud systems, Docker, CI/CD,
    system design, production debugging, and experience building scalable services.
    Preferred qualifications include microservices, observability, performance tuning,
    reliability engineering, and secure software development practices.
    """
    strong = " ".join(strong.split() * 4)
    weak_report = assess_jd_quality(weak)
    strong_report = assess_jd_quality(strong)
    assert_true(not weak_report.is_acceptable, "weak JD fetch should be rejected")
    assert_true(strong_report.is_acceptable, "complete JD should pass quality gate")


def test_company_name_extraction_from_ats_and_jd() -> None:
    cases = {
        "https://jobs.lever.co/openai/abc123": "openai",
        "https://boards.greenhouse.io/stripe/jobs/789": "stripe",
        "https://jobs.ashbyhq.com/anthropic/role-id": "anthropic",
        "https://apply.workable.com/canonical/j/123": "canonical",
    }
    for url, expected in cases.items():
        assert_true(extract_company_name(url) == expected, f"company parse failed for {url}")

    jd_company = extract_company_name_from_jd(
        "Company: Microsoft\nSoftware Engineer\nJob Description\nBuild distributed systems.",
        fallback="linkedin-job",
    )
    assert_true(jd_company == "microsoft", "JD company extraction did not override fallback")
    assert_true(
        prompt_for_company_name_if_uncertain("linkedin-job") == "linkedin-job",
        "non-interactive generic company fallback should remain stable",
    )
    assert_true(
        prompt_for_company_name_if_uncertain("Stripe") == "stripe",
        "identified company name should be sanitized and kept",
    )


def test_output_filenames_are_stable_for_sharing() -> None:
    assert_true(create_resume_filename("Google") == "Yash_Gupta_Resume.pdf", "resume filename changed")
    assert_true(
        create_cover_letter_filename("Google") == "Yash_Gupta_Cover_Letter.txt",
        "cover-letter filename changed",
    )


def test_mojibake_is_normalized_before_output_or_prompts() -> None:
    fixed = fix_encoding_issues("âœ“ generated â†’ saved â€¢ item âš ï¸ warning")
    assert_true("â" not in fixed and "Ã" not in fixed, "mojibake was not removed")
    assert_true("OK generated -> saved - item WARN warning" == fixed, "unexpected mojibake normalization")

    console = SafeConsole(record=True, width=100, file=io.StringIO())
    console.print("[green]âœ“ Console status[/green]")
    rendered = console.export_text()
    assert_true("OK Console status" in rendered, "console did not sanitize status text")
    assert_true("âœ“" not in rendered, "console leaked mojibake")

    context = format_resume_context(
        {
            "experience": [
                {
                    "title": "Software Engineer",
                    "company": "Example",
                    "duration": "2026",
                    "bullets": ["Built APIs"],
                }
            ],
            "projects": [{"title": "Cloud API", "description": "Built services"}],
        }
    )
    assert_true("â€¢" not in context, "cover-letter context leaked mojibake bullets")
    assert_true("- Software Engineer at Example" in context, "cover-letter context lost bullet content")


def test_ats_soft_skills_survive_as_skills() -> None:
    tailored = TailoredResume(
        summary="Software Engineer building backend systems.",
        experience=[],
        skills=["Python", "C++", "Microservices"],
        keywords_matched=[],
        keywords_missing=["communication", "leadership", "mentoring"],
    )
    improved, added, skipped = improve_tailored_resume_for_ats(
        tailored,
        ["communication", "leadership", "mentoring"],
    )
    assert_true(not skipped, f"soft skills were skipped: {skipped}")
    assert_true(set(added) == {"communication", "leadership", "mentoring"}, "soft skills not added")
    assert_true("Communication" in improved.skills, "Communication missing from skills")
    assert_true("Leadership" in improved.skills, "Leadership missing from skills")
    assert_true("Mentoring" in improved.skills, "Mentoring missing from skills")


def test_gap_project_only_for_large_resume_gap() -> None:
    normal_gap = TailoredResume(
        summary="Software Engineer building backend systems.",
        experience=[],
        skills=["Python", "AWS Lambda", "PostgreSQL"],
        keywords_matched=["Python", "AWS Lambda", "PostgreSQL", "REST APIs"],
        keywords_missing=["Kubernetes", "Terraform", "Jenkins"],
    )
    large_gap = TailoredResume(
        summary="Software Engineer building backend systems.",
        experience=[],
        skills=["Python"],
        keywords_matched=["Python"],
        keywords_missing=[
            "Swift",
            "iOS",
            "UIKit",
            "Core Data",
            "Xcode",
            "Combine",
            "App Store",
            "Mobile CI",
        ],
    )
    assert_true(
        not should_generate_gap_project(normal_gap),
        "gap project should not run for ordinary ATS gaps",
    )
    assert_true(
        should_generate_gap_project(large_gap),
        "gap project should run for a large JD/base-resume mismatch",
    )


def test_summary_generation_stays_general_and_jd_aligned() -> None:
    jd = """
    Senior Principal Engineering Manager
    Requirements: Python, AWS Lambda, PostgreSQL, REST APIs, leadership, mentoring
    Responsibilities: lead architecture reviews and manage platform strategy.
    """
    tailored = build_rule_based_tailored_resume(jd)
    summary_lower = tailored.summary.lower()
    for blocked in ("senior", "principal", "manager", "director", "vp", "lead "):
        assert_true(blocked not in summary_lower, f"summary included seniority term: {blocked}")
    for personal_detail in ("early-career", "under 1 year", "intern", "nippon"):
        assert_true(personal_detail not in summary_lower, f"summary exposed profile detail: {personal_detail}")
    for expected in ("dsa", "system design", "backend/cloud"):
        assert_true(expected in summary_lower, f"summary missing top-MNC positioning: {expected}")
    assert_true("python" in summary_lower, "summary did not include core programming keyword")

    ai_jd = """
    AI Backend Engineer
    Requirements: Python, FastAPI, OpenAI API, LangChain, RAG, Vector Database,
    REST APIs, PostgreSQL, Docker.
    Responsibilities: build AI workflows, retrieval services, and backend APIs.
    """
    ai_tailored = build_rule_based_tailored_resume(ai_jd)
    ai_summary_lower = ai_tailored.summary.lower()
    assert_true(ai_tailored.summary != tailored.summary, "AI JD summary did not change from backend summary")
    assert_true("ai" in ai_summary_lower, "AI JD summary did not include AI focus")
    assert_true("rag" in ai_summary_lower, "AI JD summary did not include RAG keyword")
    assert_true("openai api" in ai_summary_lower, "AI JD summary did not include OpenAI API keyword")


def test_summary_trimming_never_leaves_dangling_fragment() -> None:
    summary = (
        "Software Engineer with strong foundations in DSA, system design, and backend/cloud engineering. "
        "Builds scalable APIs and data pipelines using Python, C++, JavaScript, SQL, AWS, Docker, Kafka, PostgreSQL, testing, and monitoring."
    )
    trimmed = trim_summary_text(summary, max_length=185)
    assert_true(not trimmed.lower().endswith("and."), "summary ended with dangling 'and.'")
    assert_true(not trimmed.lower().endswith("and"), "summary ended with dangling 'and'")
    assert_true(trimmed[-1] in ".!?", "summary does not end cleanly")
    full_summary = trim_summary_text(summary, max_length=260)
    assert_true(
        "system design" in full_summary.lower(),
        "summary lost dense one-page content at normal lengths",
    )
    assert_true(
        "builds scalable apis" in full_summary.lower(),
        "summary lost second sentence at normal lengths",
    )


def test_resume_bullets_and_skills_are_clean_after_tailoring() -> None:
    base_resume = load_json("data/base_resume.json")
    user_profile = load_json("data/user_profile.json")
    tailored = TailoredResume(
        summary="Software Engineer focused on AI-enabled backend systems. Builds backend APIs using Python.",
        experience=[
            ExperienceItem(
                original="Develop backend services",
                tailored="Develop backend services with REST API design using Python, Flask, and FastAPI, integrating",
            ),
            ExperienceItem(
                original="Design containerized microservices",
                tailored="Design containerized microservices using Docker and ensure scalability through",
            ),
        ],
        skills=["Python", "REST APIs", "REST API", "Logging", "AWS", "AWS EC2"],
        keywords_matched=["Python", "REST API", "Logging"],
        keywords_missing=[],
    )
    resume_data = merge_resume_data(base_resume, user_profile, tailored)
    bullets = [
        bullet
        for job in resume_data.experience
        for bullet in job.get("bullets", [])
    ]
    for bullet in bullets:
        assert_true(
            not bullet.lower().rstrip(".").endswith(("through", "integrating", "ensuring", "using", "with")),
            f"bullet ended with dangling fragment: {bullet}",
        )
        assert_true(bullet[-1] in ".!?", f"bullet is not sentence-complete: {bullet}")
    assert_true("REST API" not in resume_data.skills, "REST API alias was not normalized")
    assert_true("Logging" not in resume_data.skills, "Logging alias was not normalized")
    assert_true(resume_data.skills.count("REST APIs") == 1, "REST APIs appeared more than once")

    trimmed = close_sentence(trim_bullet_point("Built scalable backend services for AI APIs through", 80))
    assert_true(trimmed == "Built scalable backend services for AI APIs.", "dangling trim cleanup failed")


def test_emergency_density_profile_is_actually_compact() -> None:
    emergency = DENSITY_PROFILES[-1]
    assert_true(emergency["name"] == "emergency", "last density profile should be emergency")
    assert_true(emergency["projects"] <= 1, "emergency profile keeps too many projects")
    assert_true(emergency["bullets_per_job"] <= 3, "emergency profile keeps too many experience bullets")
    assert_true(emergency["certifications"] <= 2, "emergency profile keeps too many certifications")
    assert_true(emergency["achievements"] <= 2, "emergency profile keeps too many achievements")


def test_profile_links_render_clickable_and_compact() -> None:
    base_resume = load_json("data/base_resume.json")
    user_profile = load_json("data/user_profile.json")
    resume_data = merge_resume_data(base_resume, user_profile)
    html = render_html_resume(resume_data)
    assert_true(
        'href="https://www.linkedin.com/in/yash-gupta2601"' in html,
        "LinkedIn href is not absolute/clickable",
    )
    assert_true(
        ">linkedin.com/in/yash-gupta2601<" in html,
        "LinkedIn label is not compact",
    )
    assert_true(
        'href="https://github.com/gitsofyash"' in html,
        "GitHub href is not absolute/clickable",
    )
    assert_true(
        ">github.com/gitsofyash<" in html,
        "GitHub label is not compact",
    )


def test_profile_qa_grounded_answer() -> None:
    answer = answer_profile_question("What is my current company?")
    assert_true("Nippon Audiotronix" in answer.answer, "Profile Q&A did not find current company")
    assert_true(answer.confidence >= 0.9, "Profile Q&A confidence unexpectedly low")

    internship = answer_profile_question("Where did I work as intern?")
    assert_true("Nippon Audiotronix" in internship.answer, "Profile Q&A did not find internship company")


def main() -> None:
    checks = [
        test_env_example_is_clean,
        test_package_entrypoint_is_importable,
        test_web_result_payload_maps_artifacts,
        test_jd_cleaner_removes_noise,
        test_jd_quality_rejects_incomplete_fetches,
        test_company_name_extraction_from_ats_and_jd,
        test_output_filenames_are_stable_for_sharing,
        test_mojibake_is_normalized_before_output_or_prompts,
        test_ats_soft_skills_survive_as_skills,
        test_gap_project_only_for_large_resume_gap,
        test_summary_generation_stays_general_and_jd_aligned,
        test_summary_trimming_never_leaves_dangling_fragment,
        test_resume_bullets_and_skills_are_clean_after_tailoring,
        test_emergency_density_profile_is_actually_compact,
        test_profile_links_render_clickable_and_compact,
        test_profile_qa_grounded_answer,
    ]
    for check in checks:
        check()
        print(f"PASS {check.__name__}")
    print("Production smoke checks passed")


if __name__ == "__main__":
    main()
