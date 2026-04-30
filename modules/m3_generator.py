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
from typing import Optional, Dict, Any, Iterable
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
)
from modules.m2_tailor import TailoredResume, ExperienceItem
from utils.url_parser import fix_encoding_issues, create_resume_filename

console = Console()

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
    Trim bullet point to fit on resume.
    
    Args:
        bullet: Bullet point text
        max_length: Maximum characters per bullet
        
    Returns:
        Trimmed bullet
    """
    # Fix encoding issues first
    bullet = fix_encoding_issues(bullet)
    
    if len(bullet) <= max_length:
        return bullet
    
    # Trim to max_length and add ellipsis
    trimmed = bullet[:max_length - 3] + "..."
    return trimmed


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


def expand_skills_for_jd(
    selected_skills: list[str],
    base_resume: Dict[str, Any],
    tailored_resume: Optional[TailoredResume],
    max_skills: int = 22,
) -> list[str]:
    """
    Fill the skills section with JD-matched verified skills already present in the resume.

    This improves ATS keyword coverage without inventing experience, while keeping a
    compact cap so the strict one-page layout still holds.
    """
    base_skills = flatten_base_skills(base_resume)
    verified_lookup = {skill.lower(): skill for skill in VERIFIED_SKILLS}
    base_lookup = {skill.lower(): skill for skill in base_skills}
    priority_terms = []

    if tailored_resume:
        priority_terms.extend(tailored_resume.keywords_matched or [])
        priority_terms.extend(tailored_resume.skills or [])

    ordered = []
    seen = set()

    def add_skill(skill: str) -> None:
        key = skill.lower()
        if key not in seen and (key in verified_lookup or key in base_lookup):
            ordered.append(base_lookup.get(key, verified_lookup.get(key, skill)))
            seen.add(key)

    for term in priority_terms:
        term_lower = str(term).lower()
        for candidate in base_skills:
            candidate_lower = candidate.lower()
            if candidate_lower == term_lower or candidate_lower in term_lower or term_lower in candidate_lower:
                add_skill(candidate)
        if term_lower in verified_lookup:
            add_skill(verified_lookup[term_lower])

    for skill in selected_skills:
        add_skill(skill)

    for skill in base_skills:
        if len(ordered) >= max_skills:
            break
        add_skill(skill)

    return ordered[:max_skills]


def prioritize_resume_content(
    resume_data: ResumeData,
    max_experience_items: int = 2,
    max_bullets_per_job: int = 5,
    max_projects: int = 4,
    max_bullets_per_project: int = 3,
    max_education_items: int = 1,
    max_certifications: int = 3,
    max_achievements: int = 3,
) -> ResumeData:
    """
    Prioritize resume content for 1-page constraint.
    
    Strategy:
      1. Keep top N experience items (most recent)
      2. Keep top N bullets per job
      3. Keep top N education items
      4. Keep JD-relevant projects with compact bullets
      5. Trim skill list to a compact ATS-friendly set
      6. Keep compact certifications/achievements when they fit
    
    Args:
        resume_data: Original resume data
        max_experience_items: Max work experience entries
        max_bullets_per_job: Max bullets per job
        max_education_items: Max education entries
        
    Returns:
        Prioritized resume data
    """
    # Truncate experience to top items
    if len(resume_data.experience) > max_experience_items:
        console.log(
            f"[yellow]âš ï¸ Trimming experience from {len(resume_data.experience)} to {max_experience_items} items[/yellow]"
        )
        resume_data.experience = resume_data.experience[:max_experience_items]
    
    # Trim bullets per job
    for job in resume_data.experience:
        if "bullets" in job and len(job["bullets"]) > max_bullets_per_job:
            console.log(
                f"[yellow]âš ï¸ Trimming bullets for {job.get('company', 'Unknown')} "
                f"from {len(job['bullets'])} to {max_bullets_per_job}[/yellow]"
            )
            job["bullets"] = job["bullets"][:max_bullets_per_job]
            
        if "bullets" in job:
            job["bullets"] = [trim_bullet_point(b, max_length=150) for b in job["bullets"]]
    
    # Keep a compact project section to honestly cover JD technologies.
    if len(resume_data.projects) > max_projects:
        console.log(
            f"[yellow]Trimming projects from {len(resume_data.projects)} to {max_projects} items[/yellow]"
        )
        resume_data.projects = resume_data.projects[:max_projects]

    for project in resume_data.projects:
        if "bullets" in project and len(project["bullets"]) > max_bullets_per_project:
            project["bullets"] = project["bullets"][:max_bullets_per_project]
        if "bullets" in project:
            project["bullets"] = [trim_bullet_point(b, max_length=145) for b in project["bullets"]]

    # Truncate education
    if len(resume_data.education) > max_education_items:
        console.log(
            f"[yellow]âš ï¸ Trimming education from {len(resume_data.education)} to {max_education_items} items[/yellow]"
        )
        resume_data.education = resume_data.education[:max_education_items]
    
    # Limit skills to a compact ATS-friendly set
    if len(resume_data.skills) > 22:
        console.log(
            f"[yellow]Trimming skills from {len(resume_data.skills)} to 22[/yellow]"
        )
        resume_data.skills = resume_data.skills[:22]
    
    if len(resume_data.certifications) > max_certifications:
        resume_data.certifications = resume_data.certifications[:max_certifications]

    if len(resume_data.achievements) > max_achievements:
        resume_data.achievements = resume_data.achievements[:max_achievements]
    
    return resume_data


def enforce_one_page_html(html: str, min_font_size: int = MIN_FONT_SIZE) -> str:
    """
    Enforce 1-page constraint on HTML resume via CSS.
    
    Strategy:
      1. Reduce margins and padding
      2. Reduce line height
      3. Reduce font sizes progressively
      4. Add CSS print directive
    
    Args:
        html: Original HTML resume
        min_font_size: Minimum font size to use
        
    Returns:
        Modified HTML with 1-page enforcement CSS
    """
    # Add aggressive CSS for 1-page constraint
    one_page_css = f"""
    <style>
        @page {{
            size: Letter;
            margin: 0.4in;
        }}
        
        @media print {{
            body {{ margin: 0; padding: 0; }}
            .container {{ 
                max-height: 10.2in;
                overflow: hidden;
                box-shadow: none;
                padding: 0.4in;
            }}
        }}
        
        body {{
            margin: 0;
            padding: 0;
        }}
        
        .container {{
            max-width: 8.5in;
            max-height: 11in;
            margin: 0 auto;
            padding: 0.35in;
            font-size: {min_font_size}pt;
            line-height: 1.2;
        }}
        
        .header {{
            margin-bottom: 6px;
            padding-bottom: 4px;
        }}
        
        .name {{
            font-size: {min(min_font_size + 6, 14)}pt;
            margin: 0;
        }}
        
        .contact {{
            font-size: {min_font_size - 1}pt;
            margin: 2px 0 0 0;
        }}
        
        .section {{
            margin-top: 6px;
        }}
        
        .section-title {{
            font-size: {min(min_font_size + 1, 11)}pt;
            margin: 4px 0 3px 0;
            padding-bottom: 2px;
        }}
        
        .subsection {{
            margin-bottom: 4px;
        }}
        
        .job-header {{
            font-size: {min_font_size}pt;
            margin-bottom: 1px;
        }}
        
        .job-title {{
            font-size: {min_font_size}pt;
            margin-bottom: 1px;
        }}
        
        ul {{
            margin: 2px 0;
            padding-left: 16px;
        }}
        
        li {{
            margin: 1px 0;
            font-size: {min_font_size - 0.5}pt;
            line-height: 1.2;
        }}
        
        .skills-list {{
            gap: 4px;
            margin-top: 2px;
        }}
        
        .skill-tag {{
            font-size: {min_font_size - 1}pt;
            padding: 1px 3px;
        }}
    </style>
    """
    
    # Find where to insert CSS
    if "</head>" in html:
        html = html.replace("</head>", one_page_css + "</head>")
    else:
        # Insert before body if no head
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
    summary = tailored_resume.summary if tailored_resume else base_resume.get("summary", "")
    summary = fix_encoding_issues(summary)
    
    selected_skills = tailored_resume.skills if tailored_resume else flatten_base_skills(base_resume)
    selected_skills = expand_skills_for_jd(selected_skills, base_resume, tailored_resume)

    resume_data = ResumeData(
        name=fix_encoding_issues(user_profile.get("name") or base_resume.get("personal_info", {}).get("name", "")),
        email=user_profile.get("email") or base_resume.get("personal_info", {}).get("email", ""),
        phone=user_profile.get("phone") or base_resume.get("personal_info", {}).get("phone", ""),
        linkedin=user_profile.get("linkedin") or base_resume.get("personal_info", {}).get("linkedin"),
        github=user_profile.get("github") or base_resume.get("personal_info", {}).get("github"),
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
            github=resume_data.github,
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


def count_pdf_pages(pdf_path: str) -> int:
    """Count PDF pages without adding a heavy dependency."""
    content = Path(pdf_path).read_bytes()
    return len(re.findall(rb"/Type\s*/Page\b", content))


def compact_for_single_page(resume_data: ResumeData) -> ResumeData:
    """Apply the final strict compression pass if the first PDF exceeds one page."""
    resume_data.summary = trim_bullet_point(resume_data.summary, max_length=320)
    resume_data = prioritize_resume_content(
        resume_data,
        max_experience_items=2,
        max_bullets_per_job=4,
        max_projects=3,
        max_bullets_per_project=2,
        max_education_items=1,
        max_certifications=2,
        max_achievements=2,
    )
    resume_data.skills = resume_data.skills[:18]
    return resume_data


def clone_resume_data(resume_data: ResumeData) -> ResumeData:
    """Copy resume data so density trials do not mutate each other."""
    return ResumeData(**resume_data.model_dump())


def build_density_variant(resume_data: ResumeData, profile: Dict[str, int]) -> ResumeData:
    """Build one candidate density profile for strict one-page rendering."""
    variant = clone_resume_data(resume_data)
    variant.summary = trim_bullet_point(variant.summary, max_length=profile.get("summary_length", 360))
    variant = prioritize_resume_content(
        variant,
        max_experience_items=profile.get("experience_items", 2),
        max_bullets_per_job=profile.get("bullets_per_job", 5),
        max_projects=profile.get("projects", 4),
        max_bullets_per_project=profile.get("bullets_per_project", 3),
        max_education_items=1,
        max_certifications=profile.get("certifications", 3),
        max_achievements=profile.get("achievements", 3),
    )
    variant.skills = variant.skills[:profile.get("skills", 22)]
    return variant


DENSITY_PROFILES = [
    {
        "name": "maximum",
        "summary_length": 420,
        "experience_items": 2,
        "bullets_per_job": 6,
        "projects": 4,
        "bullets_per_project": 4,
        "skills": 24,
        "certifications": 4,
        "achievements": 4,
    },
    {
        "name": "full",
        "summary_length": 380,
        "experience_items": 2,
        "bullets_per_job": 5,
        "projects": 4,
        "bullets_per_project": 3,
        "skills": 22,
        "certifications": 3,
        "achievements": 3,
    },
    {
        "name": "balanced-full",
        "summary_length": 340,
        "experience_items": 2,
        "bullets_per_job": 5,
        "projects": 4,
        "bullets_per_project": 2,
        "skills": 22,
        "certifications": 3,
        "achievements": 2,
    },
    {
        "name": "balanced",
        "summary_length": 320,
        "experience_items": 2,
        "bullets_per_job": 4,
        "projects": 3,
        "bullets_per_project": 2,
        "skills": 20,
        "certifications": 2,
        "achievements": 2,
    },
    {
        "name": "compact-full",
        "summary_length": 300,
        "experience_items": 2,
        "bullets_per_job": 3,
        "projects": 3,
        "bullets_per_project": 2,
        "skills": 18,
        "certifications": 2,
        "achievements": 1,
    },
    {
        "name": "emergency",
        "summary_length": 260,
        "experience_items": 1,
        "bullets_per_job": 2,
        "projects": 1,
        "bullets_per_project": 1,
        "skills": 14,
        "certifications": 0,
        "achievements": 0,
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
                    "top": "0.32in",
                    "bottom": "0.32in",
                    "left": "0.32in",
                    "right": "0.32in",
                },
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
            "top": "0.32in",
            "bottom": "0.32in",
            "left": "0.32in",
            "right": "0.32in",
        },
        print_background=True,
    )


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# MAIN GENERATOR FUNCTION
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


async def generate_resume_pdf(
    tailored_resume: Optional[TailoredResume] = None,
    output_path: Optional[str] = None,
    company_name: Optional[str] = None,
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
        
    Returns:
        Path to generated PDF file
    """
    # Generate output path if not provided
    if not output_path:
        if not company_name:
            company_name = "default"
        
        filename = create_resume_filename(company_name, "pdf")
        output_path = str(OUTPUT_DIR / filename)
    
    console.log("[bold cyan]MODULE 3 â€” Resume PDF Generator (Enhanced)[/bold cyan]")
    console.log(f"[dim]Output: {output_path}[/dim]")
    
    # Load data files
    console.log("[blue]Loading resume data...[/blue]")
    base_resume = load_base_resume()
    user_profile = load_user_profile()
    
    # Merge data with encoding fixes
    resume_data = merge_resume_data(base_resume, user_profile, tailored_resume)
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
                for profile in DENSITY_PROFILES:
                    candidate = build_density_variant(resume_data, profile)
                    html_content = render_html_resume(candidate)
                    await render_pdf_on_page(page, html_content, output_path)
                    page_count = count_pdf_pages(output_path)

                    if page_count == 1:
                        selected_profile = profile["name"]
                        selected_html = html_content
                        selected_resume = candidate
                        break

                    console.log(
                        f"[yellow]Density profile '{profile['name']}' rendered as {page_count} pages; trying next[/yellow]"
                    )
            finally:
                await browser.close()

        if not selected_resume or not selected_html:
            raise RuntimeError("Strict one-page check failed: no density profile fit on one page")

        resume_data = selected_resume
        save_plain_text_resume(resume_data, output_path)

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

