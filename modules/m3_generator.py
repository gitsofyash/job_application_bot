"""
MODULE 3 â€” Dynamic Resume PDF Generator

Generates tailored resume PDF from Jinja2 template + tailored content.

Features:
  - Jinja2 HTML template rendering
  - HTML â†’ PDF conversion (via browser rendering or LaTeX)
  - STRICT single-page constraint enforcement (aggressive content reduction)
  - Pre-populated static data from user_profile.json and base_resume.json
  - Professional single-column layout
  - Optimized spacing and typography for ATS compatibility
  - Company-based file naming (no overwrites)
  - Character encoding issue fixes

ENHANCEMENTS (v2.0):
  - Company name extraction from URLs
  - 1-page strict enforcement with content truncation
  - Encoding issue fixes (Ã¢â‚¬" to -)
  - Smart experience/education trimming
  - Per-company resume tracking

âš ï¸ FAILURE POINTS:
  1. Template syntax error â†’ Jinja2 raises TemplateError (caught)
  2. Missing required fields â†’ validation error (checked before rendering)
  3. Content overflow â†’ truncates content, reduces font-size until fits on 1 page
  4. File write permission â†’ IOError (caller can handle)
  5. Browser/PDF conversion fails â†’ falls back to HTML output

MITIGATION:
  - All required fields validated before rendering
  - Graceful font-size reduction loop with content trimming
  - Save intermediate HTML for debugging
  - Exception handling with detailed logging
  - Company name-based file naming prevents overwrites
"""

import json
import asyncio
import re
from pathlib import Path
from typing import Optional, Dict, Any, Iterable, List
from dataclasses import dataclass

from jinja2 import Environment, FileSystemLoader, TemplateError, TemplateNotFound
from rich.console import Console
from pydantic import BaseModel, Field

from config.settings import (
    TEMPLATES_DIR,
    OUTPUT_DIR,
    BASE_RESUME_PATH,
    USER_PROFILE_PATH,
    RESUME_TEMPLATE_PATH,
    OUTPUT_RESUME_PDF,
    DEBUG,
    MAX_RESUME_LINES,
    MIN_FONT_SIZE,
    INITIAL_FONT_SIZE,
    CONTENT_CUTOFF_THRESHOLD,
    VERIFIED_SKILLS,
    LLM_PROVIDER,
    OLLAMA_MODEL,
    OPENAI_MODEL,
    ANTHROPIC_MODEL,
    COHERE_MODEL,
    RESUME_TAILOR_USE_LLM,
    COVER_LETTER_USE_LLM,
)
from modules.m2_tailor import TailoredResume, ExperienceItem, extract_keywords, invoke_cohere_json
from utils.url_parser import fix_encoding_issues, create_resume_filename

console = Console()

LETTER_PAGE_WIDTH = "8.5in"
LETTER_PAGE_HEIGHT = "11in"
RESUME_PAGE_PADDING = "0.32in"

BLOCKED_RESUME_SENIORITY_TERMS = (
    "senior",
    "sr",
    "staff",
    "principal",
    "lead",
    "tech lead",
    "manager",
    "director",
    "vp",
    "vice president",
    "head",
)


def has_blocked_resume_seniority(text: str) -> bool:
    value = (text or "").lower()
    return any(re.search(rf"\b{re.escape(term)}\b", value) for term in BLOCKED_RESUME_SENIORITY_TERMS)


def filter_resume_seniority_terms(values: Iterable[str]) -> list[str]:
    filtered = []
    seen = set()
    for value in values or []:
        clean = str(value or "").strip()
        key = clean.lower()
        if not clean or key in seen or has_blocked_resume_seniority(clean):
            continue
        filtered.append(clean)
        seen.add(key)
    return filtered


def base_profile_summary(base_resume: dict, user_profile: dict, selected_skills: Iterable[str]) -> str:
    return (
        "Software Engineer with strong foundations in DSA, system design, and backend/cloud engineering. "
        "Builds scalable APIs and data pipelines using Python, C++, JavaScript, SQL, AWS, Docker, Kafka, PostgreSQL, testing, and monitoring."
    )

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# MODELS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


class ResumeData(BaseModel):
    """Complete resume data for PDF generation"""
    name: str = Field(..., description="Candidate name")
    email: str = Field(..., description="Email address")
    phone: str = Field(..., description="Phone number")
    linkedin: Optional[str] = Field(None, description="LinkedIn URL")
    github: Optional[str] = Field(None, description="GitHub URL")
    summary: str = Field(..., description="Professional summary")
    experience: list[Dict[str, Any]] = Field(default_factory=list, description="Work experience")
    projects: list[Dict[str, Any]] = Field(default_factory=list, description="Relevant projects")
    education: list[Dict[str, Any]] = Field(default_factory=list, description="Education")
    skills: list[str] = Field(default_factory=list, description="Technical skills")
    certifications: list[str] = Field(default_factory=list, description="Certifications")
    achievements: list[str] = Field(default_factory=list, description="Awards/achievements")


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# 1-PAGE ENFORCEMENT FUNCTIONS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


def trim_bullet_point(bullet: str, max_length: int = 120) -> str:
    """
    Trim bullet point to fit on resume with optimal line breaking.
    
    Args:
        bullet: Bullet point text
        max_length: Maximum characters per bullet (optimized for 8-9pt fonts)
        
    Returns:
        Trimmed bullet
    """
    # Fix encoding issues first
    bullet = fix_encoding_issues(bullet)
    
    if len(bullet) <= max_length:
        return bullet
    
    # Find the last word boundary within the limit
    trimmed = bullet[:max_length]
    last_space = trimmed.rfind(" ")
    
    if last_space > max_length * 0.7:  # Ensure we don't cut too early
        trimmed = bullet[:last_space]
    else:
        trimmed = bullet[:max_length]
    
    # Clean up trailing punctuation/whitespace
    trimmed = trimmed.rstrip(" ,;:-")
    
    return (trimmed if trimmed else bullet[:max_length]).rstrip()


def trim_summary_text(summary: str, max_length: int = 320) -> str:
    """
    Trim summary prose without leaving fragments such as "and.".

    Unlike bullet trimming, summary compression should prefer complete
    sentences even if that means keeping only the first sentence.
    """
    summary = fix_encoding_issues(summary).strip()
    if len(summary) <= max_length:
        return close_sentence(summary)

    clipped = summary[:max_length].rstrip()
    sentence_end = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"))
    if sentence_end >= max_length * 0.45:
        return close_sentence(clipped[: sentence_end + 1])

    last_space = clipped.rfind(" ")
    if last_space > max_length * 0.65:
        clipped = clipped[:last_space]

    clipped = re.sub(
        r"(?i)\s+(and|or|with|using|for|in|of|to|and\s+\w{1,12})$",
        "",
        clipped,
    )
    clipped = clipped.rstrip(" ,;:-")
    return close_sentence(clipped)



def close_sentence(text: str) -> str:
    """Ensure compact resume prose does not end mid-thought."""
    text = text.strip()
    if text.endswith("distributed system"):
        text = f"{text}s"
    if text and text[-1] not in ".!?":
        return f"{text}."
    return text


def flatten_base_skills(base_resume: Dict[str, Any]) -> list[str]:
    """Return all resume skills in source order without duplicates."""
    skills = base_resume.get("skills", {})
    if isinstance(skills, list):
        raw_skills: Iterable[str] = skills
    elif isinstance(skills, dict):
        raw_skills = (
            skill
            for category_skills in skills.values()
            if isinstance(category_skills, list)
            for skill in category_skills
        )
    else:
        raw_skills = []

    flattened = []
    seen = set()
    for skill in raw_skills:
        cleaned = fix_encoding_issues(str(skill)).strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            flattened.append(cleaned)
            seen.add(key)
    return flattened


def normalize_profile_url(value: Optional[str], service: str) -> Optional[str]:
    """Convert saved profile handles into clickable absolute URLs."""
    if not value:
        return None

    raw = fix_encoding_issues(str(value)).strip()
    if not raw:
        return None

    if raw.startswith(("http://", "https://")):
        return raw

    cleaned = raw.lstrip("/").replace("\\", "/")
    service = service.lower()

    if service == "linkedin":
        cleaned = cleaned.removeprefix("www.").removeprefix("linkedin.com/")
        cleaned = cleaned.removeprefix("linkedin/")
        cleaned = cleaned.removeprefix("in/")
        return f"https://www.linkedin.com/in/{cleaned.strip('/')}"

    if service == "github":
        cleaned = cleaned.removeprefix("www.").removeprefix("github.com/")
        cleaned = cleaned.removeprefix("github/")
        return f"https://github.com/{cleaned.strip('/')}"

    return raw


def profile_url_label(value: Optional[str]) -> Optional[str]:
    """Return a compact resume label while keeping hrefs absolute."""
    if not value:
        return None
    label = fix_encoding_issues(str(value)).strip()
    label = label.removeprefix("https://").removeprefix("http://")
    label = label.removeprefix("www.")
    return label.rstrip("/")


def expand_skills_for_jd(
    selected_skills: list[str],
    base_resume: Dict[str, Any],
    tailored_resume: Optional[TailoredResume],
    max_skills: int = 24,
) -> list[str]:
    """
    Fill the skills section with JD-matched verified skills already present in the resume.

    This improves ATS keyword coverage without inventing experience, while keeping a
    compact cap so the strict one-page layout still holds.
    """
    base_skills = flatten_base_skills(base_resume)
    base_lookup = {skill.lower(): skill for skill in base_skills}
    priority_terms = []

    if tailored_resume:
        priority_terms.extend(tailored_resume.keywords_matched or [])
        priority_terms.extend(tailored_resume.skills or [])

    ordered = []
    seen = set()

    def add_skill(skill: str, allow_dynamic: bool = False) -> None:
        key = skill.lower()
        if key not in seen and key in base_lookup:
            ordered.append(base_lookup[key])
            seen.add(key)
        elif allow_dynamic and key not in seen:
            ordered.append(skill)
            seen.add(key)

    for skill in selected_skills:
        add_skill(skill, allow_dynamic=True)

    for term in priority_terms:
        term_lower = str(term).lower()
        for candidate in base_skills:
            candidate_lower = candidate.lower()
            if candidate_lower == term_lower or candidate_lower in term_lower or term_lower in candidate_lower:
                add_skill(candidate)
        if term_lower in base_lookup:
            add_skill(base_lookup[term_lower])

    for skill in base_skills:
        if len(ordered) >= max_skills:
            break
        add_skill(skill)

    return ordered[:max_skills]


def prioritize_resume_content(
    resume_data: ResumeData,
    max_experience_items: int = 2,
    max_bullets_per_job: int = 5,
    max_projects: int = 3,
    max_bullets_per_project: int = 3,
    max_education_items: int = 1,
    max_certifications: int = 999,
    max_achievements: int = 999,
    jd_keywords: Optional[List[str]] = None,
) -> ResumeData:
    """
    Prioritize resume content for full-page constraint with JD-based project selection.
    
    Strategy:
      1. Keep top N experience items (most recent)
      2. Keep top N bullets per job (optimize for 1-page)
      3. Keep top N education items
      4. Select exactly N JD-relevant projects
      5. Trim skill list to a compact ATS-friendly set
      6. Keep certifications and achievements within space limits
    
    Args:
        resume_data: Original resume data
        max_experience_items: Max work experience entries
        max_bullets_per_job: Max bullets per job
        max_projects: Max projects to include
        max_bullets_per_project: Max bullets per project
        max_education_items: Max education entries
        jd_keywords: Optional JD keywords for project selection
        
    Returns:
        Prioritized resume data
    """
    # Truncate experience to top items
    if len(resume_data.experience) > max_experience_items:
        console.log(
            f"[yellow]⚠️ Trimming experience from {len(resume_data.experience)} to {max_experience_items} items[/yellow]"
        )
        resume_data.experience = resume_data.experience[:max_experience_items]
    
    # Trim bullets per job with aggressive character limits for 8-9pt fonts
    for job in resume_data.experience:
        if "bullets" in job and len(job["bullets"]) > max_bullets_per_job:
            console.log(
                f"[yellow]⚠️ Trimming bullets for {job.get('company', 'Unknown')} "
                f"from {len(job['bullets'])} to {max_bullets_per_job}[/yellow]"
            )
            job["bullets"] = job["bullets"][:max_bullets_per_job]
            
        if "bullets" in job:
            job["bullets"] = [trim_bullet_point(b, max_length=140) for b in job["bullets"]]
    
    # JD-based project selection: keep exactly N projects when available
    if jd_keywords and resume_data.projects:
        resume_data.projects = select_jd_relevant_projects(resume_data.projects, jd_keywords, max_projects)
    else:
        if len(resume_data.projects) > max_projects:
            console.log(
                f"[yellow]Selecting top {max_projects} projects from {len(resume_data.projects)} base projects[/yellow]"
            )
            resume_data.projects = resume_data.projects[:max_projects]

    # Trim project bullets with aggressive character limits
    for project in resume_data.projects:
        if "bullets" in project and len(project["bullets"]) > max_bullets_per_project:
            project["bullets"] = project["bullets"][:max_bullets_per_project]
        if "bullets" in project:
            project["bullets"] = [trim_bullet_point(b, max_length=135) for b in project["bullets"]]

    # Truncate education
    if len(resume_data.education) > max_education_items:
        console.log(
            f"[yellow]⚠️ Trimming education from {len(resume_data.education)} to {max_education_items} items[/yellow]"
        )
        resume_data.education = resume_data.education[:max_education_items]
    
    # Limit skills to a compact ATS-friendly set
    if len(resume_data.skills) > 24:
        console.log(
            f"[yellow]Trimming skills from {len(resume_data.skills)} to 24[/yellow]"
        )
        resume_data.skills = resume_data.skills[:24]
    
    # Trim certifications and achievements with character limits
    resume_data.certifications = [
        close_sentence(trim_bullet_point(cert, max_length=125))
        for cert in resume_data.certifications
    ][:max_certifications]
    
    resume_data.achievements = [
        close_sentence(trim_bullet_point(achievement, max_length=145))
        for achievement in resume_data.achievements
    ][:max_achievements]
    
    return resume_data



def select_jd_relevant_projects(
    projects: List[Dict[str, Any]],
    jd_keywords: List[str],
    max_projects: int = 6,
) -> List[Dict[str, Any]]:
    """
    Select and rank projects based on JD keyword relevance.
    
    This improves ATS score by prioritizing projects that use technologies
    mentioned in the job description.
    
    Args:
        projects: List of all projects from base resume
        jd_keywords: Keywords extracted from job description
        max_projects: Maximum number of projects to include
        
    Returns:
        Sorted list of projects (most relevant first)
    """
    if not projects or not jd_keywords:
        return projects[:max_projects]
    
    # Normalize JD keywords for matching
    jd_lower = [kw.lower() for kw in jd_keywords]
    
    def calculate_project_score(project: Dict[str, Any]) -> float:
        """Calculate relevance score for a project based on JD keywords."""
        score = 0.0
        project_text = ""
        
        # Collect all project text for matching
        project_text += project.get("title", "").lower() + " "
        project_text += project.get("description", "").lower() + " "
        project_text += " ".join(project.get("technologies", [])).lower() + " "
        project_text += " ".join(project.get("bullets", [])).lower()
        technologies = [str(tech).lower() for tech in project.get("technologies", [])]
        unique_matches = set()
        
        # Score based on keyword matches
        for jd_kw in jd_lower:
            if len(jd_kw) < 3:
                continue
            # Exact match in technologies (highest weight)
            for tech in technologies:
                if jd_kw == tech or jd_kw in tech or tech in jd_kw:
                    score += 6.0
                    unique_matches.add(jd_kw)
                    break
            
            # Match in title
            if jd_kw in project.get("title", "").lower():
                score += 4.0
                unique_matches.add(jd_kw)
            
            # Match in description
            if jd_kw in project.get("description", "").lower():
                score += 3.0
                unique_matches.add(jd_kw)
            
            # Match in bullets
            if any(jd_kw in str(bullet).lower() for bullet in project.get("bullets", [])):
                score += 2.0
                unique_matches.add(jd_kw)

        score += len(unique_matches) * 5.0

        # Keep domain-specific projects honest: do not let generic LLM/AI projects
        # outrank backend/cloud/data projects unless the JD asks for AI.
        if not any(term in " ".join(jd_lower) for term in ["ai", "llm", "generative", "rag", "openai"]):
            if any(term in project_text for term in ["openai", "large language model", "llm", "generative ai"]):
                score -= 12.0
        
        return score
    
    # Score all projects
    scored_projects = [(p, calculate_project_score(p)) for p in projects]
    
    # Sort by score (descending) and then by original order for ties
    scored_projects.sort(key=lambda x: (-x[1], projects.index(x[0])))

    positive_matches = [(project, score) for project, score in scored_projects if score > 0]
    if not positive_matches:
        console.log("[yellow]No JD-matched base projects found; generating domain-safe fallback project[/yellow]")
        return [build_fallback_project(jd_keywords)]
    
    selected = [project for project, _ in positive_matches[:max_projects]]
    if len(selected) < max_projects:
        selected_ids = {id(project) for project in selected}
        for project, _ in scored_projects:
            if id(project) not in selected_ids:
                selected.append(project)
                selected_ids.add(id(project))
            if len(selected) >= max_projects:
                break
    
    # Log which projects were selected and why
    console.log(f"[cyan]JD-based project selection:[/cyan]")
    for i, (p, score) in enumerate(scored_projects[:max_projects]):
        if score > 0:
            console.log(f"  {i+1}. {p.get('title', 'Unknown')} (score: {score:.1f})")
    
    return selected


def build_fallback_project(jd_keywords: List[str]) -> Dict[str, Any]:
    """
    Draft one realistic fallback project within Yash's verified embedded/ADAS domain.
    """
    keyword_text = ", ".join(str(keyword) for keyword in jd_keywords[:20])
    prompt = f"""Generate a JSON object for exactly one resume project.

Hard constraints:
- The project MUST stay within Yash Gupta's actual domain only:
  Automotive Embedded Systems, ADAS, C++/Python, NVIDIA Jetson/NXP i.MX platforms,
  computer vision, edge AI, CAN bus, sensor fusion, and real-time embedded systems.
- Do NOT invent unrelated cloud/SaaS/full-stack/mobile/blockchain projects.
- Keep it realistic for a student/early-career embedded software engineer.
- Return ONLY valid JSON with this schema:
  {{
    "title": "string",
    "date": "string",
    "description": "string",
    "technologies": ["string"],
    "bullets": ["string", "string"]
  }}

JD keywords to consider: {keyword_text}
"""
    try:
        parsed = json.loads(invoke_cohere_json(prompt, max_tokens=500))
        return normalize_project(parsed)
    except Exception as e:
        console.log(f"[yellow]Cohere fallback project unavailable; using deterministic domain fallback: {e}[/yellow]")
        return normalize_project(
            {
                "title": "Edge ADAS Object Detection Pipeline",
                "date": "2024",
                "description": "Built a realistic edge-AI prototype for automotive perception on embedded hardware.",
                "technologies": ["Python", "C++", "OpenCV", "NVIDIA Jetson", "CAN Bus"],
                "bullets": [
                    "Implemented camera-frame preprocessing and object detection for ADAS-style perception workloads on edge hardware.",
                    "Integrated Python/C++ modules with CAN-style telemetry simulation for real-time validation and alerting.",
                ],
            }
        )


def normalize_project(project: Dict[str, Any]) -> Dict[str, Any]:
    """Clean and constrain an LLM-generated fallback project."""
    technologies = project.get("technologies", [])
    bullets = project.get("bullets", [])
    if isinstance(technologies, str):
        technologies = [part.strip() for part in technologies.split(",") if part.strip()]
    if isinstance(bullets, str):
        bullets = [line.strip(" -") for line in bullets.splitlines() if line.strip()]

    return {
        "title": fix_encoding_issues(str(project.get("title") or "Edge ADAS Embedded Systems Project"))[:90],
        "date": fix_encoding_issues(str(project.get("date") or "2024"))[:30],
        "description": trim_bullet_point(
            fix_encoding_issues(str(project.get("description") or "Built an embedded ADAS prototype using C++/Python and edge AI.")),
            max_length=135,
        ),
        "technologies": [fix_encoding_issues(str(tech)) for tech in technologies[:7]],
        "bullets": [
            trim_bullet_point(fix_encoding_issues(str(bullet)), max_length=135)
            for bullet in bullets[:2]
        ],
    }


def enforce_one_page_html(html: str, min_font_size: int = MIN_FONT_SIZE) -> str:
    """
    Enforce 1-page constraint on HTML resume via CSS.
    
    Strategy:
      1. Reduce margins and padding aggressively
      2. Reduce line height to minimum readable levels
      3. Adjust font sizes progressively
      4. Add strict CSS print directive
      5. Prevent page breaks mid-section
    
    Args:
        html: Original HTML resume
        min_font_size: Minimum font size to use
        
    Returns:
        Modified HTML with 1-page enforcement CSS
    """
    effective_font_size = max(float(min_font_size), 11.15)
    
    one_page_css = f"""
    <style>
        @page {{
            size: Letter;
            margin: 0;
        }}
        
        @media print {{
            body {{
                print-color-adjust: exact;
                -webkit-print-color-adjust: exact;
                margin: 0 !important;
                padding: 0 !important;
            }}
            
            .container {{
                width: {LETTER_PAGE_WIDTH} !important;
                height: {LETTER_PAGE_HEIGHT} !important;
                max-height: none !important;
                overflow: hidden !important;
                box-shadow: none !important;
                padding: {RESUME_PAGE_PADDING} !important;
                margin: 0 !important;
            }}
            
            .section {{
                page-break-inside: avoid !important;
                margin-bottom: 0 !important;
            }}
            
            .subsection {{
                page-break-inside: avoid !important;
            }}
            
            .entry {{
                page-break-inside: avoid !important;
            }}
        }}
        
        body {{
            margin: 0 !important;
            padding: 0 !important;
        }}
        
        .container {{
            width: {LETTER_PAGE_WIDTH} !important;
            height: {LETTER_PAGE_HEIGHT} !important;
            max-width: none !important;
            max-height: none !important;
            margin: 0 !important;
            padding: {RESUME_PAGE_PADDING} !important;
            overflow: hidden !important;
            font-size: {effective_font_size}pt !important;
            line-height: 1.22 !important;
        }}
        
        .header {{
            margin-bottom: 5px !important;
            padding-bottom: 3px !important;
        }}
        
        .name {{
            font-size: 16pt !important;
            margin: 0 !important;
            padding: 0 !important;
            line-height: 1 !important;
        }}
        
        .contact {{
            font-size: 9.6pt !important;
            margin: 1px 0 0 0 !important;
            padding: 0 !important;
            line-height: 1.1 !important;
        }}
        
        .section {{
            margin-top: 6px !important;
            margin-bottom: 0 !important;
            page-break-inside: avoid !important;
        }}
        
        .section-title {{
            font-size: 11pt !important;
            margin: 0 0 3px 0 !important;
            padding-bottom: 1px !important;
            line-height: 1 !important;
        }}
        
        .subsection {{
            margin-bottom: 4px !important;
            page-break-inside: avoid !important;
        }}
        
        .entry {{
            margin-bottom: 4px !important;
            page-break-inside: avoid !important;
        }}
        
        .job-header {{
            font-size: {effective_font_size}pt !important;
            margin-bottom: 1px !important;
            line-height: 1.1 !important;
        }}
        
        .job-title {{
            font-size: {effective_font_size}pt !important;
            margin-bottom: 1px !important;
            line-height: 1.14 !important;
        }}
        
        .entry-header {{
            font-size: {effective_font_size}pt !important;
            margin-bottom: 1px !important;
            line-height: 1.08 !important;
        }}
        
        .entry-subtitle {{
            font-size: {effective_font_size}pt !important;
            margin: 0 !important;
            line-height: 1.14 !important;
        }}
        
        ul {{
            margin: 2px 0 0 14px !important;
            padding: 0 !important;
        }}
        
        li {{
            margin: 0 0 1px 0 !important;
            padding: 0 !important;
            font-size: {max(effective_font_size - 0.2, 11.0)}pt !important;
            line-height: 1.2 !important;
        }}
        
        .skills-list {{
            gap: 4px !important;
            margin-top: 1px !important;
        }}
        
        .skill-tag {{
            font-size: 10pt !important;
            padding: 1px 3px !important;
        }}
        
        .summary {{
            margin: 0 !important;
            padding: 0 !important;
            font-size: {max(effective_font_size - 0.2, 11.0)}pt !important;
            line-height: 1.2 !important;
        }}
        
        .skills {{
            margin: 0 !important;
            padding: 0 !important;
            font-size: {max(effective_font_size - 0.2, 11.0)}pt !important;
            line-height: 1.2 !important;
        }}
    </style>
    """
    
    if "</head>" in html:
        html = html.replace("</head>", one_page_css + "</head>")
    else:
        html = one_page_css + html
    
    return html



# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# TEMPLATE RENDERING
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


def load_base_resume() -> Dict[str, Any]:
    """
    Load base resume from base_resume.json.
    
    âš ï¸ FAILURE POINT: File not found or invalid JSON.
    MITIGATION: Raises FileNotFoundError with clear message.
    
    Returns:
        Resume dictionary
    """
    try:
        with open(BASE_RESUME_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Base resume not found at {BASE_RESUME_PATH}. "
            "Run setup first."
        )
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {BASE_RESUME_PATH}: {e}")


def load_user_profile() -> Dict[str, Any]:
    """
    Load user profile from user_profile.json.
    
    âš ï¸ FAILURE POINT: File not found or invalid JSON.
    MITIGATION: Raises FileNotFoundError with clear message.
    
    Returns:
        User profile dictionary
    """
    try:
        with open(USER_PROFILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"User profile not found at {USER_PROFILE_PATH}. "
            "Run setup first."
        )
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {USER_PROFILE_PATH}: {e}")


def merge_resume_data(
    base_resume: Dict[str, Any],
    user_profile: Dict[str, Any],
    tailored_resume: Optional[TailoredResume] = None,
) -> ResumeData:
    """
    Merge base resume, user profile, and tailored resume into complete data.
    
    Priority:
      1. Tailored resume (if provided)
      2. Base resume
      3. User profile
    
    Fixes encoding issues during merge.
    
    Args:
        base_resume: Base resume from JSON
        user_profile: User profile from JSON
        tailored_resume: Tailored resume from LLM (optional)
        
    Returns:
        Merged ResumeData
    """
    # Start with copied base resume sections so generation does not mutate source data.
    experience = json.loads(json.dumps(base_resume.get("experience", [])))
    projects = json.loads(json.dumps(base_resume.get("projects", [])))
    
    # If tailored resume provided, update bullets
    if tailored_resume:
        flat_bullets = [
            fix_encoding_issues(exp_item.tailored)
            for exp_item in tailored_resume.experience
            if exp_item.tailored
        ]
        bullet_index = 0
        for job in experience:
            bullets = job.get("bullets", [])
            for index in range(len(bullets)):
                if bullet_index >= len(flat_bullets):
                    break
                bullets[index] = flat_bullets[bullet_index]
                bullet_index += 1
    
    # Fix encoding in experience bullets
    for job in experience:
        if "bullets" in job:
            job["bullets"] = [fix_encoding_issues(b) for b in job["bullets"]]
        if "company" in job:
            job["company"] = fix_encoding_issues(job["company"])
        if "title" in job:
            job["title"] = fix_encoding_issues(job["title"])

    for project in projects:
        if "bullets" in project:
            project["bullets"] = [fix_encoding_issues(b) for b in project["bullets"]]
        for field in ("title", "description", "date"):
            if field in project:
                project[field] = fix_encoding_issues(project[field])
        if "technologies" in project:
            project["technologies"] = [fix_encoding_issues(t) for t in project["technologies"]]
    
    # Build resume data
    selected_skills = tailored_resume.skills if tailored_resume else flatten_base_skills(base_resume)
    selected_skills = expand_skills_for_jd(selected_skills, base_resume, tailored_resume)
    selected_skills = filter_resume_seniority_terms(selected_skills)
    summary = base_profile_summary(base_resume, user_profile, selected_skills)
    summary = fix_encoding_issues(summary)

    linkedin = normalize_profile_url(
        user_profile.get("linkedin") or base_resume.get("personal_info", {}).get("linkedin"),
        "linkedin",
    )
    github = normalize_profile_url(
        user_profile.get("github") or base_resume.get("personal_info", {}).get("github"),
        "github",
    )

    resume_data = ResumeData(
        name=fix_encoding_issues(user_profile.get("name") or base_resume.get("personal_info", {}).get("name", "")),
        email=user_profile.get("email") or base_resume.get("personal_info", {}).get("email", ""),
        phone=user_profile.get("phone") or base_resume.get("personal_info", {}).get("phone", ""),
        linkedin=linkedin,
        github=github,
        summary=summary,
        experience=experience,
        projects=projects,
        education=base_resume.get("education", []),
        skills=selected_skills,
        certifications=base_resume.get("certifications", []),
        achievements=base_resume.get("achievements", []),
    )
    
    return resume_data


def render_html_resume(
    resume_data: ResumeData,
    template_path: Optional[str] = None,
) -> str:
    """
    Render HTML resume from Jinja2 template with 1-page enforcement.
    
    âš ï¸ FAILURE POINT: Template syntax error or missing template.
    MITIGATION: Raises TemplateError with clear message.
    
    Args:
        resume_data: Resume data to render
        template_path: Path to resume.html template (optional, uses config default)
        
    Returns:
        Rendered HTML string with 1-page CSS
    """
    if not template_path:
        template_path = str(RESUME_TEMPLATE_PATH)
    
    console.log("[blue]Rendering HTML resume...[/blue]")
    
    try:
        # Load Jinja2 environment
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=True,
        )
        
        template = env.get_template(Path(template_path).name)
        
        # Render
        html = template.render(
            name=resume_data.name,
            email=resume_data.email,
            phone=resume_data.phone,
            linkedin=resume_data.linkedin,
            linkedin_label=profile_url_label(resume_data.linkedin),
            github=resume_data.github,
            github_label=profile_url_label(resume_data.github),
            summary=resume_data.summary,
            experience=resume_data.experience,
            projects=resume_data.projects,
            education=resume_data.education,
            skills=resume_data.skills,
            certifications=resume_data.certifications,
            achievements=resume_data.achievements,
        )
        
        # Apply 1-page enforcement CSS
        html = enforce_one_page_html(html, min_font_size=INITIAL_FONT_SIZE)
        
        console.log("[green]âœ“ HTML rendered successfully with 1-page enforcement[/green]")
        return html
    
    except TemplateNotFound as e:
        raise FileNotFoundError(f"Template not found: {e}")
    except TemplateError as e:
        raise ValueError(f"Template rendering error: {e}")


def build_plain_text_resume(resume_data: ResumeData) -> str:
    """Build an ATS-readable plain-text mirror of the generated resume."""
    lines = [
        resume_data.name,
        f"Email: {resume_data.email} | Phone: {resume_data.phone}",
    ]
    links = [link for link in [resume_data.linkedin, resume_data.github] if link]
    if links:
        lines.append(" | ".join(links))

    if resume_data.summary:
        lines.extend(["", "PROFESSIONAL SUMMARY", resume_data.summary])

    if resume_data.skills:
        lines.extend(["", "TECHNICAL SKILLS", ", ".join(resume_data.skills)])

    if resume_data.experience:
        lines.extend(["", "PROFESSIONAL EXPERIENCE"])
        for job in resume_data.experience:
            lines.append(f"{job.get('title', '')} | {job.get('company', '')} | {job.get('duration', '')}")
            for bullet in job.get("bullets", []):
                lines.append(f"- {bullet}")

    if resume_data.projects:
        lines.extend(["", "PROJECTS"])
        for project in resume_data.projects:
            technologies = ", ".join(project.get("technologies", []))
            lines.append(f"{project.get('title', '')} | {technologies}")
            if project.get("description"):
                lines.append(project["description"])
            for bullet in project.get("bullets", []):
                lines.append(f"- {bullet}")

    if resume_data.education:
        lines.extend(["", "EDUCATION"])
        for edu in resume_data.education:
            lines.append(f"{edu.get('degree', '')} | {edu.get('institution', '')} | {edu.get('duration', '')}")

    if resume_data.certifications:
        lines.extend(["", "CERTIFICATIONS"])
        for cert in resume_data.certifications:
            lines.append(f"- {cert}")

    if resume_data.achievements:
        lines.extend(["", "ACHIEVEMENTS"])
        for achievement in resume_data.achievements:
            lines.append(f"- {achievement}")

    return "\n".join(fix_encoding_issues(line).strip() for line in lines if line is not None)


def save_plain_text_resume(resume_data: ResumeData, output_path: str) -> Path:
    """Save the ATS text mirror next to the PDF."""
    text_path = Path(output_path).with_suffix(".txt")
    text_path.write_text(build_plain_text_resume(resume_data), encoding="utf-8")
    console.log(f"[green]ATS text mirror saved: {text_path}[/green]")
    return text_path


def _provider_model_name() -> str:
    """Return the configured model name for the active provider."""
    models = {
        "OLLAMA": OLLAMA_MODEL,
        "OPENAI": OPENAI_MODEL,
        "ANTHROPIC": ANTHROPIC_MODEL,
        "COHERE": COHERE_MODEL,
    }
    return models.get(LLM_PROVIDER, "unknown")


def build_pipeline_verification() -> str:
    """Describe which LLMs were active for this generated resume artifact."""
    resume_engine = (
        f"{LLM_PROVIDER} / {_provider_model_name()}"
        if RESUME_TAILOR_USE_LLM
        else "Deterministic ATS tailoring (resume LLM disabled)"
    )
    cover_engine = (
        f"{LLM_PROVIDER} / {_provider_model_name()}"
        if COVER_LETTER_USE_LLM
        else "Deterministic cover-letter fallback unless explicitly enabled"
    )
    return f"Resume generation: {resume_engine}; Cover letter pipeline: {cover_engine}"


def reorder_skill_categories(
    base_resume: Dict[str, Any],
    jd_keywords: Optional[List[str]] = None,
    max_per_category: int = 8,
) -> Dict[str, List[str]]:
    """Return base-resume skill categories reordered by JD overlap."""
    raw_skills = base_resume.get("skills", {})
    if not isinstance(raw_skills, dict):
        return {"Skills": flatten_base_skills(base_resume)}

    jd_terms = [term.lower() for term in (jd_keywords or [])]
    categorized = {}

    for category, skills in raw_skills.items():
        if not isinstance(skills, list):
            continue

        cleaned_skills = [fix_encoding_issues(str(skill)).strip() for skill in skills if str(skill).strip()]

        def relevance(skill: str) -> tuple[int, int]:
            skill_lower = skill.lower()
            exact = any(skill_lower == term for term in jd_terms)
            partial = any(skill_lower in term or term in skill_lower for term in jd_terms)
            return (2 if exact else 1 if partial else 0, -cleaned_skills.index(skill))

        ordered = sorted(cleaned_skills, key=relevance, reverse=True)
        categorized[category.replace("_", " ").title()] = ordered[:max_per_category]

    return categorized


def build_markdown_resume(
    resume_data: ResumeData,
    base_resume: Dict[str, Any],
    jd_keywords: Optional[List[str]] = None,
) -> str:
    """Build the requested Markdown resume plus generation metadata report."""
    keywords = jd_keywords or []
    plain_text = build_plain_text_resume(resume_data).lower()
    injected_keywords = []
    jd_blob = " ".join(str(keyword).lower() for keyword in keywords)
    generic_terms = {
        "backend",
        "software",
        "engineer",
        "responsibilities",
        "qualifications",
        "role",
        "apis",
        "rest",
    }
    for skill in flatten_base_skills(base_resume):
        normalized = str(skill).strip()
        skill_lower = normalized.lower()
        if (
            normalized
            and skill_lower not in generic_terms
            and skill_lower in plain_text
            and (skill_lower in jd_blob or any(term in skill_lower for term in jd_blob.split()))
            and normalized not in injected_keywords
        ):
            injected_keywords.append(normalized)
        if len(injected_keywords) >= 5:
            break
    for keyword in keywords:
        normalized = str(keyword).strip()
        keyword_lower = normalized.lower()
        if (
            normalized
            and keyword_lower not in generic_terms
            and len(normalized) > 3
            and keyword_lower in plain_text
            and normalized not in injected_keywords
        ):
            injected_keywords.append(normalized)
        if len(injected_keywords) >= 5:
            break

    skill_categories = reorder_skill_categories(base_resume, keywords)
    lines = [
        f"# {resume_data.name}",
        f"{resume_data.email} | {resume_data.phone}"
        + (f" | {resume_data.linkedin}" if resume_data.linkedin else "")
        + (f" | {resume_data.github}" if resume_data.github else ""),
        "",
        "## Professional Summary",
        resume_data.summary,
        "",
        "## Technical Skills",
    ]

    for category, skills in skill_categories.items():
        if skills:
            lines.append(f"- **{category}:** {', '.join(skills)}")

    if resume_data.experience:
        lines.extend(["", "## Professional Experience"])
        for job in resume_data.experience:
            lines.append(
                f"### {job.get('title', '')} | {job.get('company', '')} | {job.get('duration', '')}"
            )
            if job.get("location"):
                lines.append(f"*{job['location']}*")
            for bullet in job.get("bullets", []):
                lines.append(f"- {bullet}")

    if resume_data.projects:
        lines.extend(["", "## Projects"])
        for project in resume_data.projects:
            technologies = ", ".join(project.get("technologies", []))
            lines.append(f"### {project.get('title', '')} | {project.get('date', '')}")
            if technologies:
                lines.append(f"*{technologies}*")
            if project.get("description"):
                lines.append(project["description"])
            for bullet in project.get("bullets", []):
                lines.append(f"- {bullet}")

    if resume_data.education:
        lines.extend(["", "## Education"])
        for edu in resume_data.education:
            lines.append(f"**{edu.get('degree', '')}** | {edu.get('institution', '')} | {edu.get('duration', '')}")
            education_detail = edu.get("location", "")
            if edu.get("cgpa"):
                education_detail = f"{education_detail} | GPA: {edu['cgpa']}" if education_detail else f"GPA: {edu['cgpa']}"
            if education_detail:
                lines.append(education_detail)

    if resume_data.certifications:
        lines.extend(["", "## Certifications"])
        for cert in resume_data.certifications:
            lines.append(f"- {cert}")

    if resume_data.achievements:
        lines.extend(["", "## Achievements"])
        for achievement in resume_data.achievements:
            lines.append(f"- {achievement}")

    lines.extend([
        "",
        "---",
        "## Generation Metadata & Keyword Report",
        f"- **Keywords Injected:** {', '.join(injected_keywords[:5]) if injected_keywords else 'None'}",
        f"- **LLM Pipeline Verification:** {build_pipeline_verification()}",
    ])

    return "\n".join(fix_encoding_issues(line).rstrip() for line in lines)


def save_markdown_resume(
    resume_data: ResumeData,
    base_resume: Dict[str, Any],
    output_path: str,
    jd_keywords: Optional[List[str]] = None,
) -> Path:
    """Save the Markdown resume requested by the advanced ATS prompt."""
    markdown_path = Path(output_path).with_suffix(".md")
    markdown_path.write_text(
        build_markdown_resume(resume_data, base_resume, jd_keywords),
        encoding="utf-8",
    )
    console.log(f"[green]Markdown resume saved: {markdown_path}[/green]")
    return markdown_path


def count_pdf_pages(pdf_path: str) -> int:
    """Count PDF pages without adding a heavy dependency."""
    content = Path(pdf_path).read_bytes()
    return len(re.findall(rb"/Type\s*/Page\b", content))


async def resume_content_fits(page) -> bool:
    """Check rendered DOM height because PDF page count can hide clipped content."""
    metrics = await page.evaluate(
        """() => {
            const container = document.querySelector('.container');
            if (!container) {
                return { fits: false, scrollHeight: 0, clientHeight: 0 };
            }
            return {
                fits: container.scrollHeight <= container.clientHeight + 2,
                scrollHeight: container.scrollHeight,
                clientHeight: container.clientHeight
            };
        }"""
    )
    if not metrics["fits"]:
        console.log(
            "[yellow]✗ Rendered content overflows page "
            f"({metrics['scrollHeight']}px > {metrics['clientHeight']}px)[/yellow]"
        )
    return bool(metrics["fits"])


def compact_for_single_page(
    resume_data: ResumeData,
    jd_keywords: Optional[List[str]] = None,
) -> ResumeData:
    """Apply the final strict compression pass if the first PDF exceeds one page."""
    resume_data.summary = trim_summary_text(resume_data.summary, max_length=320)
    resume_data = prioritize_resume_content(
        resume_data,
        max_experience_items=2,
        max_bullets_per_job=6,
        max_projects=3,
        max_bullets_per_project=1,
        max_education_items=1,
        max_certifications=999,
        max_achievements=999,
        jd_keywords=jd_keywords,
    )
    resume_data.skills = resume_data.skills[:20]
    return resume_data


def clone_resume_data(resume_data: ResumeData) -> ResumeData:
    """Copy resume data so density trials do not mutate each other."""
    return ResumeData(**resume_data.model_dump())


def build_density_variant(
    resume_data: ResumeData,
    profile: Dict[str, int],
    jd_keywords: Optional[List[str]] = None,
) -> ResumeData:
    """Build one candidate density profile for strict one-page rendering."""
    variant = clone_resume_data(resume_data)
    variant.summary = trim_summary_text(
        variant.summary,
        max_length=profile.get("summary_length", 360),
    )
    variant = prioritize_resume_content(
        variant,
        max_experience_items=profile.get("experience_items", 2),
        max_bullets_per_job=profile.get("bullets_per_job", 5),
        max_projects=profile.get("projects", 4),
        max_bullets_per_project=profile.get("bullets_per_project", 3),
        max_education_items=1,
        max_certifications=profile.get("certifications", 3),
        max_achievements=profile.get("achievements", 3),
        jd_keywords=jd_keywords,
    )
    variant.skills = variant.skills[:profile.get("skills", 22)]
    return variant


DENSITY_PROFILES = [
    {
        "name": "maximum",
        "summary_length": 400,
        "experience_items": 2,
        "bullets_per_job": 6,
        "projects": 3,
        "bullets_per_project": 2,
        "skills": 24,
        "certifications": 999,
        "achievements": 999,
    },
    {
        "name": "full",
        "summary_length": 360,
        "experience_items": 2,
        "bullets_per_job": 6,
        "projects": 3,
        "bullets_per_project": 2,
        "skills": 22,
        "certifications": 999,
        "achievements": 999,
    },
    {
        "name": "balanced-full",
        "summary_length": 320,
        "experience_items": 2,
        "bullets_per_job": 5,
        "projects": 3,
        "bullets_per_project": 2,
        "skills": 20,
        "certifications": 999,
        "achievements": 999,
    },
    {
        "name": "balanced",
        "summary_length": 280,
        "experience_items": 2,
        "bullets_per_job": 5,
        "projects": 3,
        "bullets_per_project": 1,
        "skills": 18,
        "certifications": 999,
        "achievements": 999,
    },
    {
        "name": "compact-full",
        "summary_length": 240,
        "experience_items": 2,
        "bullets_per_job": 4,
        "projects": 2,
        "bullets_per_project": 1,
        "skills": 16,
        "certifications": 999,
        "achievements": 999,
    },
    {
        "name": "emergency",
        "summary_length": 240,
        "experience_items": 2,
        "bullets_per_job": 4,
        "projects": 2,
        "bullets_per_project": 1,
        "skills": 14,
        "certifications": 999,
        "achievements": 999,
    },
]



# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PDF CONVERSION (via Playwright)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


async def convert_html_to_pdf(
    html_content: str,
    output_path: str,
) -> None:
    """
    Convert HTML to PDF using Playwright browser rendering.
    
    Strategy:
      1. Load HTML in browser
      2. Set print CSS media
      3. Print to PDF with A4 size
      4. Save to output_path
    
    âš ï¸ FAILURE POINT: Browser not available or rendering fails.
    MITIGATION: Falls back to saving HTML only. Raises error logged.
    
    Args:
        html_content: Rendered HTML string
        output_path: Path to save PDF file
    """
    try:
        from playwright.async_api import async_playwright
        
        console.log("[blue]Converting HTML to PDF...[/blue]")
        
        async with async_playwright() as playwright_instance:
            browser = await playwright_instance.chromium.launch(headless=True)
            page = await browser.new_page()
            
            # Set viewport for consistent rendering
            await page.set_viewport_size({"width": 1024, "height": 1280})
            
            # Load HTML
            await page.set_content(html_content)
            
            # Add print styles
            await page.add_style_tag(content="""
                @media print {
                    body { margin: 0; padding: 0; }
                    .container { box-shadow: none; max-width: 100%; }
                }
            """)
            
            # Generate PDF (8.5" x 11" = 612 x 792 points)
            await page.pdf(
                path=output_path,
                format="Letter",
                margin={
                    "top": "0",
                    "bottom": "0",
                    "left": "0",
                    "right": "0",
                },
                prefer_css_page_size=True,
                print_background=True,
            )
            
            await browser.close()
        
        console.log(f"[green]âœ“ PDF generated: {output_path}[/green]")
    
    except Exception as e:
        console.log(f"[yellow]âš ï¸ PDF conversion failed: {e}[/yellow]")
        console.log("[yellow]Falling back to HTML output only[/yellow]")
        # Save HTML as fallback
        html_path = str(output_path).replace(".pdf", ".html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        console.log(f"[yellow]HTML saved to: {html_path}[/yellow]")
        raise


async def render_pdf_on_page(page, html_content: str, output_path: str) -> None:
    """Render HTML to PDF on an existing Playwright page."""
    await page.set_content(html_content, wait_until="load")
    await page.add_style_tag(content="""
        @media print {
            body { margin: 0; padding: 0; }
            .container { box-shadow: none; max-width: 100%; }
        }
    """)
    await page.pdf(
        path=output_path,
        format="Letter",
        margin={
            "top": "0",
            "bottom": "0",
            "left": "0",
            "right": "0",
        },
        prefer_css_page_size=True,
        print_background=True,
    )


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# MAIN GENERATOR FUNCTION
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


async def generate_resume_pdf(
    tailored_resume: Optional[TailoredResume] = None,
    output_path: Optional[str] = None,
    company_name: Optional[str] = None,
    job_description: Optional[str] = None,
    output_dir: Optional[Path] = None,
    base_resume_data: Optional[Dict[str, Any]] = None,
) -> Path:
    """
    Generate complete resume PDF from tailored content.
    
    Orchestrates:
      1. Load base resume and user profile
      2. Merge with tailored resume (if provided)
      3. Prioritize content for 1-page constraint
      4. Render HTML from Jinja2 template with 1-page CSS
      5. Convert to PDF via browser
      6. Save to company-specific path (prevents overwrites)
    
    ENHANCEMENTS (v2.0):
      - Strict 1-page enforcement with content truncation
      - Company-name based file naming
      - Encoding issue fixes
    
    âš ï¸ FAILURE POINTS:
      - Base resume/profile files not found â†’ FileNotFoundError
      - Template rendering fails â†’ TemplateError
      - PDF conversion fails â†’ falls back to HTML
      - File write fails â†’ IOError (propagated)
    
    Args:
        tailored_resume: Tailored resume from LLM (optional)
        output_path: Path to save PDF (optional, auto-generated if not provided)
        company_name: Company name for filename (optional, auto-extracted or uses default)
        job_description: Raw JD text used for project shuffling and metadata
        
    Returns:
        Path to generated PDF file
    """
    # Generate output path if not provided
    target_output_dir = Path(output_dir or OUTPUT_DIR)
    target_output_dir.mkdir(parents=True, exist_ok=True)

    if not output_path:
        if not company_name:
            company_name = "default"
        
        filename = create_resume_filename(company_name, "pdf")
        output_path = str(target_output_dir / filename)
    
    console.log("[bold cyan]MODULE 3 â€” Resume PDF Generator (Enhanced)[/bold cyan]")
    console.log(f"[dim]Output: {output_path}[/dim]")
    
    # Load data files
    console.log("[blue]Loading resume data...[/blue]")
    base_resume = json.loads(json.dumps(base_resume_data)) if base_resume_data else load_base_resume()
    user_profile = load_user_profile()
    
    # Merge data with encoding fixes
    resume_data = merge_resume_data(base_resume, user_profile, tailored_resume)
    jd_keywords = extract_keywords(job_description or "") if job_description else []
    if tailored_resume:
        jd_keywords.extend(tailored_resume.keywords_matched or [])
        jd_keywords.extend(tailored_resume.skills or [])
    jd_keywords = list(dict.fromkeys(str(keyword) for keyword in jd_keywords if str(keyword).strip()))
    console.log(f"[green]âœ“ Resume data prepared[/green]")
    
    # Convert to PDF
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    try:
        selected_profile = None
        selected_html = None
        selected_resume = None

        console.log("[blue]Selecting fullest one-page density profile...[/blue]")
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright_instance:
            browser = await playwright_instance.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1024, "height": 1280})
            try:
                # REVERSED: Try from most dense to least dense, keep the FULLEST that fits
                # This ensures maximum content on the page instead of minimum
                valid_profiles = []
                
                for profile in DENSITY_PROFILES:
                    candidate = build_density_variant(resume_data, profile, jd_keywords=jd_keywords)
                    html_content = render_html_resume(candidate)
                    await render_pdf_on_page(page, html_content, output_path)
                    page_count = count_pdf_pages(output_path)
                    content_fits = await resume_content_fits(page)

                    if page_count == 1 and content_fits:
                        valid_profiles.append((profile, candidate, html_content))
                        console.log(
                            f"[green]✓ Density profile '{profile['name']}' fits on 1 page[/green]"
                        )
                        break
                    else:
                        console.log(
                            f"[yellow]✗ Density profile '{profile['name']}' rendered as {page_count} pages[/yellow]"
                        )

                # Profiles are ordered from fullest to most compact. Pick the first
                # fitting profile so a successful maximum render is not overwritten
                # by the later emergency profile.
                if valid_profiles:
                    selected_profile = valid_profiles[0][0]["name"]
                    selected_resume = valid_profiles[0][1]
                    selected_html = valid_profiles[0][2]
                    console.log(
                        f"[cyan]Selected '{selected_profile}' profile (fullest content that fits)[/cyan]"
                    )
                else:
                    # Fallback: use the most compact profile if nothing fits
                    candidate = build_density_variant(resume_data, DENSITY_PROFILES[-1], jd_keywords=jd_keywords)
                    selected_profile = DENSITY_PROFILES[-1]["name"]
                    selected_resume = candidate
                    selected_html = render_html_resume(candidate)
                    console.log(
                        f"[yellow]Warning: No profile fits exactly 1 page, using fallback '{selected_profile}'[/yellow]"
                    )
            finally:
                await browser.close()

        if not selected_resume or not selected_html:
            raise RuntimeError("Strict one-page check failed: no density profile fit on one page")

        resume_data = selected_resume
        
        # Re-render and save the final PDF with the selected profile (fullest content)
        # Need to reopen browser since we closed it in the try block
        async with async_playwright() as playwright_instance:
            browser = await playwright_instance.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1024, "height": 1280})
            final_html = render_html_resume(resume_data)
            await render_pdf_on_page(page, final_html, output_path)
            if not await resume_content_fits(page):
                raise RuntimeError(
                    f"Strict one-page check failed: '{selected_profile}' profile clips content"
                )
            await browser.close()
        
        save_plain_text_resume(resume_data, output_path)
        save_markdown_resume(resume_data, base_resume, output_path, jd_keywords=jd_keywords)

        if DEBUG:
            html_output = Path(output_path).with_suffix(".html")
            with open(html_output, "w", encoding="utf-8") as f:
                f.write(selected_html)
            console.log(f"[dim]HTML output saved to: {html_output}[/dim]")

        page_count = count_pdf_pages(output_path)
        if page_count != 1:
            raise RuntimeError(f"Strict one-page check failed: generated PDF has {page_count} pages")
        console.log(f"[green]Strict one-page check passed using '{selected_profile}' profile[/green]")
    except Exception as e:
        console.log(f"[red]âœ— PDF generation failed: {e}[/red]")
        if not DEBUG:
            raise
        # In debug mode, continue with HTML fallback
    
    console.log(f"[green]âœ“ Resume generated: {output_path}[/green]")
    console.log(f"[green]âœ“ Stored as company-specific file (no overwrites)[/green]")
    return output_path_obj


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# CLI TEST COMMAND
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


async def main():
    """Test PDF generation with sample tailored resume"""
    from modules.m2_tailor import ExperienceItem
    
    # Sample tailored resume
    sample_tailored = TailoredResume(
        summary="Results-driven Backend Engineer with 3+ years of experience building scalable cloud solutions on AWS. Expertise in Python, Docker, and REST APIs. Passionate about optimizing cloud infrastructure and reducing operational costs.",
        experience=[
            ExperienceItem(
                original="Built backend for Autonomous Emergency Braking (AEB) system",
                tailored="Architected scalable backend for Autonomous Emergency Braking system using Python & C++, processing real-time sensor fusion data with sub-100ms latency",
            ),
            ExperienceItem(
                original="Processed real-time sensor fusion data",
                tailored="Implemented real-time data pipelines for sensor fusion workflows, achieving 99.9% reliability under high concurrency",
            ),
        ],
        skills=["Python", "AWS EC2", "AWS S3", "AWS Lambda", "Docker", "REST APIs", "PostgreSQL", "Flask"],
        keywords_matched=["Python", "AWS", "REST APIs", "Docker", "scalability"],
        keywords_missing=["Scala", "Kubernetes", "Machine Learning"],
    )
    
    console.print("[bold cyan]MODULE 3 â€” Resume PDF Generator (Test)[/bold cyan]")
    
    output_path = await generate_resume_pdf(sample_tailored)
    console.print(f"\n[bold green]Resume generated:[/bold green] {output_path}")


if __name__ == "__main__":
    asyncio.run(main())

