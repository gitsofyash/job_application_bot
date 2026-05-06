#!/usr/bin/env python3
"""Production smoke checks for the job application bot."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.m1_extractor import clean_job_description_text
from modules.m2_tailor import TailoredResume, improve_tailored_resume_for_ats
from modules.m3_generator import merge_resume_data, render_html_resume
from modules.m9_profile_qa import answer_profile_question


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


def main() -> None:
    checks = [
        test_env_example_is_clean,
        test_jd_cleaner_removes_noise,
        test_ats_soft_skills_survive_as_skills,
        test_profile_links_render_clickable_and_compact,
        test_profile_qa_grounded_answer,
    ]
    for check in checks:
        check()
        print(f"PASS {check.__name__}")
    print("Production smoke checks passed")


if __name__ == "__main__":
    main()
