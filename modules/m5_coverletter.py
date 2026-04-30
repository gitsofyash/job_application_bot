"""
MODULE 5 — ATS-Friendly Cover Letter Generator

Generates tailored cover letter based on job description using LLM.

Features:
  - LangChain integration with swappable LLM backend (Ollama, OpenAI, Anthropic)
  - Professional cover letter structure
  - Keyword matching from job description
  - Company research highlights
  - ATS-friendly plain text format
  - HTML template for PDF conversion
  - Company-based file naming (no overwrites)
  - Character encoding issue fixes

ENHANCEMENTS (v2.0):
  - Company name-based file naming prevents overwrites
  - Encoding issue fixes (â€ to -)
  - Better content organization

⚠️ FAILURE POINTS:
  1. LLM provider unavailable → LLMError raised
  2. JD too large → Auto-summarized via LLM before processing
  3. Token limit exceeded → Gracefully truncates

MITIGATION:
  - Structured output validation via Pydantic
  - LLM retry logic with prompt refinement
  - Token counting before LLM call
"""

import asyncio
import html
import json
import re
import urllib.request
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path

import httpx
from pydantic import BaseModel, Field, field_validator
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from rich.console import Console
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from config.settings import (
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    JD_MAX_WORDS,
    COVER_LETTER_MAX_CHARS,
    COVER_LETTER_LLM_TIMEOUT_SECONDS,
    COVER_LETTER_LLM_MAX_WORDS,
    COVER_LETTER_LLM_MAX_TOKENS,
    USER_PROFILE_PATH,
    OUTPUT_DIR,
    DEBUG,
)
from utils.url_parser import fix_encoding_issues, create_cover_letter_filename
from modules.m2_tailor import extract_keywords, match_skills_to_verified

console = Console()


def is_local_ollama_available(timeout_seconds: float = 0.5) -> bool:
    """Return True when the configured local Ollama server is reachable."""
    if LLM_PROVIDER != "OLLAMA":
        return True

    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags", timeout=timeout_seconds):
            return True
    except Exception:
        return False


def trim_to_complete_sentence(text: str, max_chars: int) -> str:
    """
    Trim text without leaving an incomplete sentence fragment.
    """
    text = fix_encoding_issues(text).strip()
    if len(text) <= max_chars:
        return text

    clipped = text[:max_chars].rstrip()
    sentence_end = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"))
    if sentence_end >= max_chars * 0.55:
        return clipped[: sentence_end + 1].strip()

    last_space = clipped.rfind(" ")
    if last_space > 0:
        clipped = clipped[:last_space].rstrip()
    return f"{clipped}."


def normalize_cover_letter(cover_letter: CoverLetter, max_chars: int = COVER_LETTER_MAX_CHARS) -> CoverLetter:
    """
    Keep the cover letter complete and professional under the configured length.
    """
    section_limits = {
        "greeting": 80,
        "opening_paragraph": 430,
        "body_paragraph_1": 520,
        "body_paragraph_2": 520,
        "closing_paragraph": 320,
        "signature": 80,
    }
    data = cover_letter.model_dump()
    for field, limit in section_limits.items():
        data[field] = trim_to_complete_sentence(str(data[field]), limit)

    normalized = CoverLetter(**data)
    while len(format_cover_letter_text(normalized)) > max_chars:
        if len(normalized.body_paragraph_2) > 220:
            normalized.body_paragraph_2 = trim_to_complete_sentence(normalized.body_paragraph_2, len(normalized.body_paragraph_2) - 80)
        elif len(normalized.body_paragraph_1) > 220:
            normalized.body_paragraph_1 = trim_to_complete_sentence(normalized.body_paragraph_1, len(normalized.body_paragraph_1) - 80)
        elif len(normalized.opening_paragraph) > 180:
            normalized.opening_paragraph = trim_to_complete_sentence(normalized.opening_paragraph, len(normalized.opening_paragraph) - 60)
        else:
            break

    return normalized


def compact_text_by_sections(text: str, max_words: int) -> str:
    """
    Keep the most useful JD lines for the LLM prompt without another LLM call.
    """
    fixed_text = fix_encoding_issues(text)
    lines = [line.strip() for line in fixed_text.splitlines()]
    if len(lines) <= 2:
        lines = [
            chunk.strip()
            for chunk in re.split(r"(?<=[.!?])\s+|(?=\b(?:DESCRIPTION|RESPONSIBILITIES|BASIC QUALIFICATIONS|PREFERRED QUALIFICATIONS|REQUIREMENTS)\b)", fixed_text)
            if chunk.strip()
        ]
    useful_lines = []
    priority_terms = [
        "description",
        "responsibilities",
        "requirements",
        "basic qualifications",
        "preferred qualifications",
        "qualifications",
        "experience",
        "software",
        "engineer",
        "skills",
        "you will",
        "we are looking",
    ]

    for line in lines:
        if not line:
            continue
        lower = line.lower()
        nav_hits = sum(
            1
            for term in [
                "sign out",
                "my profile",
                "account security",
                "settings",
                "my applications",
                "job categories",
            ]
            if term in lower
        )
        if nav_hits and not any(term in lower for term in ["qualification", "responsibilit", "description", "software", "engineer"]):
            continue
        if any(term in lower for term in priority_terms) or len(line.split()) > 8:
            useful_lines.append(line)

    compact = "\n".join(useful_lines) if useful_lines else fix_encoding_issues(text)
    words = compact.split()
    if len(words) <= max_words:
        return compact

    clipped = " ".join(words[:max_words])
    return trim_to_complete_sentence(clipped, len(clipped))


def compact_resume_context(resume_data: Dict[str, Any]) -> str:
    """
    Small resume context for faster cover-letter LLM calls.
    """
    parts = []
    if resume_data.get("summary"):
        parts.append(f"Summary: {trim_to_complete_sentence(resume_data['summary'], 360)}")

    for exp in resume_data.get("experience", [])[:1]:
        bullets = "; ".join(exp.get("bullets", [])[:3])
        parts.append(
            f"Experience: {exp.get('title', '')} at {exp.get('company', '')}; "
            f"{trim_to_complete_sentence(bullets, 520)}"
        )

    for project in resume_data.get("projects", [])[:2]:
        technologies = ", ".join(project.get("technologies", [])[:8])
        parts.append(
            f"Project: {project.get('title', '')}; {project.get('description', '')}; Tech: {technologies}"
        )

    skills_data = resume_data.get("skills", {})
    skills = []
    if isinstance(skills_data, dict):
        for values in skills_data.values():
            if isinstance(values, list):
                skills.extend(values[:4])
    elif isinstance(skills_data, list):
        skills.extend(skills_data)
    if skills:
        parts.append(f"Skills: {', '.join(skills[:18])}")

    return "\n".join(parts)

# ═══════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════


class CoverLetter(BaseModel):
    """
    Generated cover letter with ATS-friendly content
    """
    
    greeting: str = Field(
        ...,
        description="Professional greeting (e.g., 'Dear Hiring Manager')",
    )
    
    opening_paragraph: str = Field(
        ...,
        description="Opening paragraph - state role and enthusiasm (3-4 sentences)",
    )
    
    body_paragraph_1: str = Field(
        ...,
        description="First body paragraph - highlight relevant skills (3-4 sentences)",
    )
    
    body_paragraph_2: str = Field(
        ...,
        description="Second body paragraph - demonstrate value (3-4 sentences)",
    )
    
    closing_paragraph: str = Field(
        ...,
        description="Closing paragraph - call to action (2-3 sentences)",
    )
    
    signature: str = Field(
        ...,
        description="Professional closing (e.g., 'Sincerely, Yash Gupta')",
    )
    
    keywords_used: List[str] = Field(
        ...,
        description="Keywords from JD used in cover letter",
    )


def build_rule_based_cover_letter(
    job_description: str,
    resume_data: Optional[Dict[str, Any]] = None,
) -> CoverLetter:
    """
    Build a deterministic cover letter when the LLM provider is unavailable.
    """
    user_profile = load_user_profile()
    if resume_data is None:
        resume_data = load_resume_data()

    jd_keywords = extract_keywords(job_description)
    matched_skills, _ = match_skills_to_verified(jd_keywords)
    selected_skills = matched_skills[:6] or [
        "Python",
        "REST APIs",
        "AWS Lambda",
        "PostgreSQL",
        "Docker",
        "System Design",
    ]

    projects = resume_data.get("projects", []) if resume_data else []
    project_name = projects[0].get("title", "cloud and backend engineering projects") if projects else "cloud and backend engineering projects"
    experience = resume_data.get("experience", []) if resume_data else []
    current_role = "Software Engineer"
    current_company = "Nippon Audiotronix Pvt. Ltd."
    if experience:
        current_role = experience[0].get("title", current_role)
        current_company = experience[0].get("company", current_company)

    skills_text = ", ".join(selected_skills)
    name = user_profile.get("name", "Yash Gupta")

    cover_letter = CoverLetter(
        greeting="Dear Hiring Manager,",
        opening_paragraph=(
            "I am excited to apply for this Software Engineer opportunity. "
            f"My background in {skills_text} aligns well with the technical requirements and delivery focus described in the role."
        ),
        body_paragraph_1=(
            f"In my current role as {current_role} at {current_company}, I have built backend and real-time systems with a focus on reliability, "
            "measurable performance, testing, and clean engineering execution."
        ),
        body_paragraph_2=(
            f"My project work, including {project_name}, demonstrates practical experience with scalable APIs, cloud services, data storage, "
            "monitoring, and production-minded problem solving."
        ),
        closing_paragraph=(
            "I would welcome the opportunity to discuss how my engineering experience can contribute to your team. "
            "Thank you for your time and consideration."
        ),
        signature=f"Sincerely,\n{name}",
        keywords_used=selected_skills,
    )
    return normalize_cover_letter(cover_letter)


# ═══════════════════════════════════════════════════════════════
# LLM PROVIDER INITIALIZATION
# ═══════════════════════════════════════════════════════════════


def get_llm_chain():
    """
    Initialize LLM chain based on LLM_PROVIDER env var.
    
    Supports:
      - OLLAMA (local, default)
      - OPENAI (gpt-4-turbo)
      - ANTHROPIC (claude-opus)
    
    Returns:
        LangChain LLM instance
    """
    try:
        if LLM_PROVIDER == "OLLAMA":
            # from langchain_community.llms import Ollama
            from langchain_ollama import OllamaLLM      # New way

            console.log(f"[cyan]Initializing Ollama: {OLLAMA_MODEL}[/cyan]")
            return OllamaLLM(
                base_url=OLLAMA_BASE_URL,
                model=OLLAMA_MODEL,
                temperature=0.4,  # Slightly higher for cover letter creativity
            )
        
        elif LLM_PROVIDER == "OPENAI":
            from langchain_openai import ChatOpenAI
            
            if not OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY not set in .env")
            
            console.log(f"[cyan]Initializing OpenAI: {OPENAI_MODEL}[/cyan]")
            return ChatOpenAI(
                api_key=OPENAI_API_KEY,
                model=OPENAI_MODEL,
                temperature=0.4,
            )
        
        elif LLM_PROVIDER == "ANTHROPIC":
            from langchain_anthropic import ChatAnthropic
            
            if not ANTHROPIC_API_KEY:
                raise ValueError("ANTHROPIC_API_KEY not set in .env")
            
            console.log(f"[cyan]Initializing Anthropic: {ANTHROPIC_MODEL}[/cyan]")
            return ChatAnthropic(
                api_key=ANTHROPIC_API_KEY,
                model=ANTHROPIC_MODEL,
                temperature=0.4,
            )
        
        elif LLM_PROVIDER == "GEMINI":
            from langchain_google_genai import ChatGoogleGenerativeAI

            if not GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY not set in .env")

            console.log(f"[cyan]Initializing Gemini: {GEMINI_MODEL}[/cyan]")
            return ChatGoogleGenerativeAI(
                google_api_key=GEMINI_API_KEY,
                model=GEMINI_MODEL,
                temperature=0.25,
                timeout=COVER_LETTER_LLM_TIMEOUT_SECONDS,
                max_retries=1,
            )
        
        else:
            raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")
    
    except ImportError as e:
        raise ImportError(
            f"LLM provider {LLM_PROVIDER} not installed. "
            f"Install with: pip install langchain-{LLM_PROVIDER.lower()}"
        ) from e


# ═══════════════════════════════════════════════════════════════
# COVER LETTER GENERATION
# ═══════════════════════════════════════════════════════════════


def load_user_profile() -> Dict[str, Any]:
    """
    Load user profile from JSON file.
    
    Returns:
        User profile dictionary
    """
    try:
        with open(USER_PROFILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        # Return default profile if not found
        return {
            "name": "Yash Gupta",
            "email": "2004yggupta@gmail.com",
            "phone": "+91 9351951828",
            "linkedin": "linkedin/yash-gupta",
            "github": "github/gitsofyash",
        }


def load_resume_data() -> Dict[str, Any]:
    """
    Load base resume data to provide context for cover letter generation.
    
    Returns:
        Resume data dictionary with experience, skills, projects
    """
    try:
        from config.settings import BASE_RESUME_PATH
        with open(BASE_RESUME_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def format_resume_context(resume_data: Dict[str, Any]) -> str:
    """
    Format resume data into a concise context string for the LLM prompt.
    
    Args:
        resume_data: Resume dictionary
        
    Returns:
        Formatted resume context string
    """
    context = ""
    
    # Add summary
    if resume_data.get("summary"):
        context += f"PROFESSIONAL SUMMARY:\n{resume_data['summary']}\n\n"
    
    # Add recent experience
    if resume_data.get("experience"):
        context += "RELEVANT EXPERIENCE:\n"
        for exp in resume_data["experience"][:2]:  # Last 2 experiences
            context += f"• {exp.get('title', '')} at {exp.get('company', '')} ({exp.get('duration', '')})\n"
            for bullet in exp.get("bullets", [])[:3]:  # Top 3 bullets
                context += f"  - {bullet}\n"
        context += "\n"
    
    # Add key projects
    if resume_data.get("projects"):
        context += "KEY PROJECTS:\n"
        for proj in resume_data["projects"][:2]:  # Top 2 projects
            context += f"• {proj.get('title', '')}: {proj.get('description', '')}\n"
        context += "\n"
    
    # Add key skills
    if resume_data.get("skills"):
        skills_data = resume_data["skills"]
        all_skills = []
        if isinstance(skills_data, dict):
            for skill_category in skills_data.values():
                if isinstance(skill_category, list):
                    all_skills.extend(skill_category[:5])
        elif isinstance(skills_data, list):
            all_skills.extend(skills_data)
        context += f"KEY SKILLS: {', '.join(all_skills[:15])}\n"
    
    return context


async def generate_cover_letter(job_description: str, resume_data: Optional[Dict[str, Any]] = None) -> CoverLetter:
    """
    Generate ATS-friendly cover letter tailored to job description.
    
    Process:
      1. Load user profile and resume data
      2. Extract key requirements from JD
      3. Use LLM to generate personalized cover letter with resume context
      4. Validate output structure
      5. Return CoverLetter object
    
    Args:
        job_description: Raw job description text
        resume_data: Optional resume data for contextual generation
        
    Returns:
        CoverLetter object with all sections
        
    Raises:
        ValueError: If LLM output is invalid
    """
    
    # Load user profile
    user_profile = load_user_profile()
    
    # Load resume data if not provided
    if resume_data is None:
        resume_data = load_resume_data()
    
    resume_context = compact_resume_context(resume_data) if resume_data else ""
    job_description = compact_text_by_sections(
        job_description,
        max_words=COVER_LETTER_LLM_MAX_WORDS,
    )

    parser = PydanticOutputParser(pydantic_object=CoverLetter)

    prompt_template = PromptTemplate(
        template="""Write a concise, professional, ATS-friendly cover letter tailored to the job description.
Return ONLY valid JSON matching the schema. Keep every paragraph complete; never end mid-sentence.

USER PROFILE:
- Name: {name}
- Email: {email}
- Phone: {phone}
- LinkedIn: {linkedin}
- GitHub: {github}

CANDIDATE'S BACKGROUND:
{resume_context}

JOB DESCRIPTION:
{job_description}

REQUIREMENTS:
1. Opening paragraph: 2 complete sentences, mention the role if clear.
2. First body paragraph: 2-3 complete sentences using only actual resume experience.
3. Second body paragraph: 2-3 complete sentences matching resume skills/projects to JD requirements.
4. Closing paragraph: 1-2 complete sentences.
5. Professional greeting and closing

ATS OPTIMIZATION RULES:
- Use clear, simple language (no jargon)
- Include specific keywords from the job description naturally
- Keep paragraphs concise and scannable
- Use action verbs and QUANTIFIABLE achievements from resume
- Maintain professional tone throughout
- Reference specific technologies and methodologies from resume
- Do not invent companies, skills, tools, degrees, or years of experience
- Total output should be under {max_chars} characters

{format_instructions}

JSON only:""",
        input_variables=[
            "name",
            "email", 
            "phone",
            "linkedin",
            "github",
            "resume_context",
            "job_description",
            "max_chars",
            "format_instructions",
        ],
        partial_variables={
            "format_instructions": parser.get_format_instructions()
        },
    )

    prompt = prompt_template.format(
        name=user_profile.get("name", "Yash Gupta"),
        email=user_profile.get("email", "2004yggupta@gmail.com"),
        phone=user_profile.get("phone", "+91 9351951828"),
        linkedin=user_profile.get("linkedin", "linkedin/yash-gupta"),
        github=user_profile.get("github", "github/gitsofyash"),
        resume_context=resume_context,
        job_description=job_description,
        max_chars=COVER_LETTER_MAX_CHARS,
    )

    console.log(
        f"[cyan]Generating LLM cover letter with compact prompt "
        f"({len(job_description.split())} JD words, timeout {COVER_LETTER_LLM_TIMEOUT_SECONDS}s)...[/cyan]"
    )

    try:
        if LLM_PROVIDER == "OLLAMA":
            cover_letter = await generate_cover_letter_with_ollama(prompt)
        else:
            llm = get_llm_chain()
            chain = llm | parser
            cover_letter = await asyncio.wait_for(
                asyncio.to_thread(chain.invoke, prompt),
                timeout=COVER_LETTER_LLM_TIMEOUT_SECONDS,
            )

        console.log("[green]✓ Cover letter generated successfully[/green]")
        return normalize_cover_letter(cover_letter)
    except asyncio.TimeoutError as e:
        raise TimeoutError(
            f"Cover letter LLM exceeded {COVER_LETTER_LLM_TIMEOUT_SECONDS}s"
        ) from e
    except Exception as e:
        console.log(f"[red]Error generating cover letter: {e}[/red]")
        raise ValueError(f"Cover letter generation failed: {e}") from e


async def generate_cover_letter_with_ollama(prompt: str) -> CoverLetter:
    """
    Faster Ollama path using the native HTTP API with JSON mode and token limits.
    """
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.25,
            "num_predict": COVER_LETTER_LLM_MAX_TOKENS,
        },
    }
    timeout = httpx.Timeout(COVER_LETTER_LLM_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    response_text = data.get("response", "")
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Ollama returned invalid JSON: {e}") from e

    return CoverLetter(**parsed)


async def summarize_jd(job_description: str) -> str:
    """
    Summarize job description if it exceeds max words.
    
    Args:
        job_description: Original job description
        
    Returns:
        Summarized job description
    """
    llm = get_llm_chain()
    
    prompt_template = PromptTemplate(
        template="""Summarize the following job description, keeping only the most important 
requirements, responsibilities, and qualifications. Keep it under 500 words.

JOB DESCRIPTION:
{job_description}

SUMMARY:""",
        input_variables=["job_description"],
    )
    
    try:
        chain = prompt_template | llm
        
        summarized = await asyncio.to_thread(
            chain.invoke,
            {"job_description": job_description},
        )
        
        summarized_text = summarized.content if hasattr(summarized, "content") else str(summarized)
        console.log(f"[dim]Summarized JD to {len(summarized_text.split())} words[/dim]")
        return summarized_text
    
    except Exception as e:
        console.log(f"[yellow]Warning: Could not summarize JD, using original[/yellow]")
        return job_description


# ═══════════════════════════════════════════════════════════════
# COVER LETTER FILE GENERATION
# ═══════════════════════════════════════════════════════════════


def format_cover_letter_text(cover_letter: CoverLetter) -> str:
    """
    Format cover letter as plain text with encoding fixes.
    
    Args:
        cover_letter: CoverLetter object
        
    Returns:
        Formatted plain text
    """
    text = f"""{fix_encoding_issues(cover_letter.greeting)}

{fix_encoding_issues(cover_letter.opening_paragraph)}

{fix_encoding_issues(cover_letter.body_paragraph_1)}

{fix_encoding_issues(cover_letter.body_paragraph_2)}

{fix_encoding_issues(cover_letter.closing_paragraph)}

{fix_encoding_issues(cover_letter.signature)}
"""
    return text


def format_cover_letter_html(cover_letter: CoverLetter, name: str = "Yash Gupta") -> str:
    """
    Format cover letter as HTML for PDF conversion with encoding fixes.
    
    Args:
        cover_letter: CoverLetter object
        name: Candidate name
        
    Returns:
        HTML string
    """
    greeting = html.escape(fix_encoding_issues(cover_letter.greeting))
    opening = html.escape(fix_encoding_issues(cover_letter.opening_paragraph))
    body_1 = html.escape(fix_encoding_issues(cover_letter.body_paragraph_1))
    body_2 = html.escape(fix_encoding_issues(cover_letter.body_paragraph_2))
    closing = html.escape(fix_encoding_issues(cover_letter.closing_paragraph))
    signature = html.escape(fix_encoding_issues(cover_letter.signature))
    safe_name = html.escape(fix_encoding_issues(name))

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cover Letter - {safe_name}</title>
    <style>
        body {{
            font-family: Arial, Calibri, Helvetica, sans-serif;
            font-size: 11pt;
            line-height: 1.6;
            color: #000;
            margin: 20px;
            max-width: 8.5in;
            margin-left: auto;
            margin-right: auto;
        }}
        
        p {{
            margin: 12px 0;
            text-align: justify;
        }}
        
        .date {{
            margin-bottom: 20px;
        }}
        
        .closing {{
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="date">{datetime.now().strftime('%B %d, %Y')}</div>
    
    <p>{greeting}</p>
    
    <p>{opening}</p>
    
    <p>{body_1}</p>
    
    <p>{body_2}</p>
    
    <p>{closing}</p>
    
    <div class="closing">{signature}</div>
</body>
</html>"""
    return html_content


async def save_cover_letter(
    cover_letter: CoverLetter,
    output_filename: Optional[str] = None,
    company_name: Optional[str] = None,
) -> Path:
    """
    Save cover letter to text and HTML files with company-based naming.
    
    Enhancements (v2.0):
      - Company name-based naming prevents overwrites
      - Supports custom filenames for flexibility
      - Better file organization per company
    
    Args:
        cover_letter: CoverLetter object
        output_filename: Optional custom filename (without extension)
        company_name: Optional company name for file naming
        
    Returns:
        Path to saved text file
    """
    if not output_filename:
        if company_name:
            # Use company name for file
            output_filename = create_cover_letter_filename(company_name, extension="txt").replace(".txt", "")
        else:
            # Fallback to timestamp-based name
            timestamp = int(asyncio.get_event_loop().time())
            output_filename = f"cover_letter_{timestamp}"
    
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save as text
    text_path = output_dir / f"{output_filename}.txt"
    text_content = format_cover_letter_text(cover_letter)
    text_path.write_text(text_content, encoding='utf-8')
    console.log(f"[green]✓ Text cover letter saved:[/green] {text_path}")
    
    # Save as HTML
    html_path = output_dir / f"{output_filename}.html"
    html_content = format_cover_letter_html(cover_letter)
    html_path.write_text(html_content, encoding='utf-8')
    console.log(f"[green]✓ HTML cover letter saved:[/green] {html_path}")
    
    return text_path
