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
    JD_MAX_WORDS,
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

    return CoverLetter(
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


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type((ValueError, Exception)),
)
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
    
    # Format resume context for prompt
    resume_context = format_resume_context(resume_data) if resume_data else ""
    
    # Truncate JD if too long
    if len(job_description.split()) > JD_MAX_WORDS:
        console.log(
            f"[yellow]JD exceeds {JD_MAX_WORDS} words, summarizing...[/yellow]"
        )
        job_description = await summarize_jd(job_description)
    
    # Initialize LLM
    llm = get_llm_chain()
    
    # Create prompt
    parser = PydanticOutputParser(pydantic_object=CoverLetter)
    
    prompt_template = PromptTemplate(
        template="""You are an expert cover letter writer. Generate a professional, ATS-friendly cover letter that directly references the candidate's actual resume content and experience.

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
1. Opening paragraph (3-4 sentences): Express enthusiasm for the role and company, mention specific role title if known
2. First body paragraph (3-4 sentences): Reference ACTUAL experience from the resume that matches job requirements
3. Second body paragraph (3-4 sentences): Highlight specific skills and achievements from resume that solve job's key challenges
4. Closing paragraph (2-3 sentences): Include call to action and availability
5. Professional greeting and closing

ATS OPTIMIZATION RULES:
- Use clear, simple language (no jargon)
- Include specific keywords from the job description naturally
- Keep paragraphs concise and scannable
- Use action verbs and QUANTIFIABLE achievements from resume
- Maintain professional tone throughout
- Reference specific technologies and methodologies from resume
- Match timing and context: if cover letter mentions experience, use exact timeframe from resume

{format_instructions}

Generate the cover letter now:""",
        input_variables=[
            "name",
            "email", 
            "phone",
            "linkedin",
            "github",
            "resume_context",
            "job_description",
            "format_instructions",
        ],
        partial_variables={
            "format_instructions": parser.get_format_instructions()
        },
    )
    
    # Generate cover letter
    console.log("[cyan]Generating cover letter with LLM and resume context...[/cyan]")
    
    try:
        chain = prompt_template | llm | parser
        
        cover_letter = await asyncio.to_thread(
            chain.invoke,
            {
                "name": user_profile.get("name", "Yash Gupta"),
                "email": user_profile.get("email", "2004yggupta@gmail.com"),
                "phone": user_profile.get("phone", "+91 9351951828"),
                "linkedin": user_profile.get("linkedin", "linkedin/yash-gupta"),
                "github": user_profile.get("github", "github/gitsofyash"),
                "resume_context": resume_context,
                "job_description": job_description,
            },
        )
        
        console.log("[green]✓ Cover letter generated successfully[/green]")
        return cover_letter
    
    except Exception as e:
        console.log(f"[red]Error generating cover letter: {e}[/red]")
        raise ValueError(f"Cover letter generation failed: {e}") from e


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
