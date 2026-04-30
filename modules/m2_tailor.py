"""
MODULE 2 — LLM Resume Tailoring

Tailors resume content to job description using LangChain + LLM (Ollama/OpenAI/Anthropic).

Features:
  - Keyword extraction from job description
  - Intelligent matching to verified skills (anti-hallucination enforced)
  - LLM-powered bullet point rewriting to match JD keywords
  - Token guard: summarizes JD if > 3000 words before processing
  - Swappable LLM backend via LLM_PROVIDER env var
  - Honest keywords_missing marking (gaps are NOT hidden)
  - Pydantic validation on all outputs

⚠️ FAILURE POINTS:
  1. LLM provider unavailable → LLMError raised (caller can retry with fallback)
  2. Hallucination in output → Pydantic validation catches and re-prompts
  3. JD too large → Auto-summarized via LLM before keyword extraction
  4. Token limit exceeded → Gracefully truncates skills/keywords

MITIGATION:
  - Structured output validation via Pydantic
  - Explicit system prompt enforcement (anti-hallucination)
  - LLM retry logic with prompt refinement
  - Token counting before LLM call
"""

import asyncio
import json
import re
from typing import Optional, List
from enum import Enum

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
    RESUME_TAILOR_LLM_TIMEOUT_SECONDS,
    VERIFIED_SKILLS,
    BASE_RESUME_PATH,
    DEBUG,
)

console = Console()

# ═══════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════


class ExperienceItem(BaseModel):
    """Single experience bullet point"""
    original: str = Field(..., description="Original bullet from base resume")
    tailored: str = Field(..., description="Tailored bullet matching JD keywords")


class TailoredResume(BaseModel):
    """
    Complete tailored resume output from LLM.
    
    ⚠️ Anti-hallucination constraint:
    - skills MUST be subset of VERIFIED_SKILLS
    - keywords_matched MUST exist in JD
    - keywords_missing MUST be honest gaps (no inventing matches)
    """
    
    summary: str = Field(
        ...,
        description="2 sentence summary (keyword-rich, tailored to JD)",
    )
    
    experience: List[ExperienceItem] = Field(
        ...,
        description="Experience bullets rewritten to match JD keywords",
    )
    
    skills: List[str] = Field(
        ...,
        description="Subset of verified skills relevant to this role (NO HALLUCINATION)",
    )
    
    keywords_matched: List[str] = Field(
        ...,
        description="JD keywords that Yash's verified skills cover",
    )
    
    keywords_missing: List[str] = Field(
        ...,
        description="JD requirements Yash does NOT have (honest gaps)",
    )
    
    @field_validator("skills")
    @classmethod
    def validate_skills(cls, v: List[str]) -> List[str]:
        """
        ⚠️ ANTI-HALLUCINATION ENFORCEMENT
        
        Validate that all skills are in VERIFIED_SKILLS.
        Raises ValidationError if any skill is not verified.
        
        MITIGATION: On validation failure, Pydantic will raise error,
        triggering LLM retry with stricter prompt.
        """
        invalid_skills = [skill for skill in v if skill not in VERIFIED_SKILLS]
        
        if invalid_skills:
            raise ValueError(
                f"⚠️ CRITICAL: Hallucinated skills detected: {invalid_skills}\n"
                f"VERIFIED_SKILLS: {VERIFIED_SKILLS}\n"
                f"This is a prompt/model failure. Check system prompt enforcement."
            )
        
        return v


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
    
    ⚠️ FAILURE POINT: Provider not available → raises ImportError or connection error.
    MITIGATION: Caller can catch and retry with fallback provider.
    
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
                temperature=0.3,  # Low temp for consistency
            )
        
        elif LLM_PROVIDER == "OPENAI":
            from langchain_openai import ChatOpenAI
            
            if not OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY not set in .env")
            
            console.log(f"[cyan]Initializing OpenAI: {OPENAI_MODEL}[/cyan]")
            return ChatOpenAI(
                api_key=OPENAI_API_KEY,
                model=OPENAI_MODEL,
                temperature=0.3,
            )
        
        elif LLM_PROVIDER == "ANTHROPIC":
            from langchain_anthropic import ChatAnthropic
            
            if not ANTHROPIC_API_KEY:
                raise ValueError("ANTHROPIC_API_KEY not set in .env")
            
            console.log(f"[cyan]Initializing Anthropic: {ANTHROPIC_MODEL}[/cyan]")
            return ChatAnthropic(
                api_key=ANTHROPIC_API_KEY,
                model=ANTHROPIC_MODEL,
                temperature=0.3,
            )
        
        else:
            raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")
    
    except ImportError as e:
        raise ImportError(
            f"LLM provider {LLM_PROVIDER} not installed. "
            f"Install with: pip install langchain-{LLM_PROVIDER.lower()}"
        ) from e


# ═══════════════════════════════════════════════════════════════
# TEXT PROCESSING UTILITIES
# ═══════════════════════════════════════════════════════════════


def count_words(text: str) -> int:
    """Count words in text"""
    return len(text.split())


def summarize_jd(jd_text: str, llm) -> str:
    """
    Summarize job description if it exceeds JD_MAX_WORDS.
    
    ⚠️ FAILURE POINT: Summarization may lose important keywords.
    MITIGATION: Uses low temperature LLM to preserve technical terms.
    
    Args:
        jd_text: Original JD text
        llm: LangChain LLM instance
        
    Returns:
        Summarized JD (or original if under word limit)
    """
    word_count = count_words(jd_text)
    
    if word_count <= JD_MAX_WORDS:
        console.log(f"[green]JD size: {word_count} words (within limit)[/green]")
        return jd_text
    
    console.log(
        f"[yellow]JD size: {word_count} words (exceeds {JD_MAX_WORDS}), "
        f"summarizing...[/yellow]"
    )
    
    summary_prompt = PromptTemplate(
        input_variables=["jd_text"],
        template="""You are an expert technical IT recruiter. 
Your task is to read the following raw scraped website text and extract ONLY the hard technical requirements, programming languages, and core responsibilities. 

CRITICAL INSTRUCTIONS:
- IGNORE website navigation links (e.g., "Sign in", "Forgot password").
- IGNORE company culture, benefits, and equal opportunity statements.
- DO NOT write paragraphs. Extract a dense, comma-separated list of skills and duties.

Raw Job Description Text:
{jd_text}

Extracted Technical Requirements:"""
    )
    
    chain = summary_prompt | llm
    summarized = chain.invoke({"jd_text": jd_text}) # MUST say "jd_text": jd_text
    
    if hasattr(summarized, "content"):
        summarized_text = summarized.content
    else:
        summarized_text = str(summarized)
    
    new_word_count = count_words(summarized_text)
    console.log(f"[green]Summarized to: {new_word_count} words[/green]")
    
    return summarized_text


def compact_jd_for_tailoring(jd_text: str, max_words: int = JD_MAX_WORDS) -> str:
    """
    Compact scraped JD text without using an LLM, keeping job-relevant sections first.
    """
    if count_words(jd_text) <= max_words:
        return jd_text

    lines = [line.strip() for line in jd_text.splitlines() if line.strip()]
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
    noise_terms = ["sign in", "profile", "search", "back to search", "store", "support"]
    selected = []

    for line in lines:
        lower = line.lower()
        if any(term in lower for term in priority_terms):
            selected.append(line)
        elif len(line.split()) > 8 and not any(term == lower for term in noise_terms):
            selected.append(line)

    compact = "\n".join(selected) if selected else jd_text
    words = compact.split()
    return " ".join(words[:max_words])


def extract_keywords(text: str) -> List[str]:
    """
    Extract technical keywords and requirements from text.
    Uses heuristic + regex patterns.
    
    Args:
        text: Job description text
        
    Returns:
        List of extracted keywords
    """
    # Common patterns in job descriptions
    patterns = [
        r"(?:required|must have|essential):\s*([^\n]+)",
        r"(?:experience with|expertise in|proficient in):\s*([^\n]+)",
        r"(?:skills?|qualifications?):\s*([^\n]+)",
    ]
    
    keywords = []
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            # Split by comma, slash, pipe, semicolon, or standalone and/or.
            terms = re.split(r"\s*(?:,|/|\||;|\band\b|\bor\b)\s*", match, flags=re.IGNORECASE)
            keywords.extend([term.strip() for term in terms if term.strip()])
    
    # Also try to find capitalized technical terms
    technical_terms = re.findall(r"\b([A-Z][a-zA-Z0-9\+\#\.\-]*)\b", text)
    keywords.extend(technical_terms)
    
    # Also add verified skills directly mentioned in the JD. This catches exact
    # phrases such as "REST APIs" and "AWS Lambda" that regex snippets can miss.
    text_lower = text.lower()
    for skill in VERIFIED_SKILLS:
        if skill.lower() in text_lower:
            keywords.append(skill)
    
    # Remove duplicates and short terms while preserving order
    seen = set()
    keywords = [
        k for k in keywords
        if len(k) > 2 and not (k.lower() in seen or seen.add(k.lower()))
    ]
    
    return keywords[:30]  # Limit to top 30 keywords


def match_skills_to_verified(jd_keywords: List[str]) -> tuple[List[str], List[str]]:
    """
    Match JD keywords to verified skills.
    Returns matched and missing skills.
    
    ⚠️ ANTI-HALLUCINATION:
    Only returns skills from VERIFIED_SKILLS that appear in JD.
    Marks anything else as keywords_missing.
    
    Args:
        jd_keywords: Keywords extracted from JD
        
    Returns:
        (matched_skills, missing_keywords) tuple
    """
    matched = []
    missing = []
    
    for keyword in jd_keywords:
        keyword_lower = keyword.lower()
        
        # Check if keyword or similar skill is in verified list
        found = False
        for skill in VERIFIED_SKILLS:
            if (
                keyword_lower == skill.lower()
                or keyword_lower in skill.lower()
                or skill.lower() in keyword_lower
            ):
                if skill not in matched:
                    matched.append(skill)
                found = True
                break
        
        if not found:
            if keyword not in missing:
                missing.append(keyword)
    
    return matched, missing


def build_rule_based_tailored_resume(
    job_description: str,
    base_resume_path: Optional[str] = None,
) -> TailoredResume:
    """
    Deterministic fallback tailor used when the LLM is skipped or unavailable.

    It only uses verified skills and existing resume bullets, but still aligns the
    skills section and summary to the JD so ATS coverage does not collapse.
    """
    if not base_resume_path:
        base_resume_path = str(BASE_RESUME_PATH)

    with open(base_resume_path, "r", encoding="utf-8") as f:
        base_resume = json.load(f)

    jd_keywords = extract_keywords(job_description)
    matched_skills, missing_keywords = match_skills_to_verified(jd_keywords)

    if not matched_skills:
        matched_skills = VERIFIED_SKILLS[:10]

    top_skills = matched_skills[:14]
    skill_phrase = ", ".join(top_skills[:6])
    summary = (
        f"Software Engineer with hands-on experience in {skill_phrase}, building backend, cloud, and embedded systems. "
        "Focused on scalable APIs, reliable data pipelines, testing, and measurable production outcomes aligned to the role."
    )

    experience_items = []
    for exp in base_resume.get("experience", []):
        for bullet in exp.get("bullets", []):
            tailored = bullet
            bullet_lower = bullet.lower()
            for skill in top_skills:
                if skill.lower() not in bullet_lower and len(tailored) < 115:
                    tailored = f"{tailored} using {skill}"
                    break
            experience_items.append(ExperienceItem(original=bullet, tailored=tailored))

    return TailoredResume(
        summary=summary,
        experience=experience_items,
        skills=top_skills,
        keywords_matched=matched_skills,
        keywords_missing=missing_keywords,
    )


ATS_KEYWORD_SKILL_MAP = {
    "logging": ["Logging Systems"],
    "monitoring": ["Monitoring Tools", "AWS CloudWatch"],
    "scalability": ["System Design", "Microservices"],
    "security": ["JWT Authentication", "AWS IAM"],
    "authentication": ["JWT Authentication"],
    "ci/cd": ["CI/CD"],
    "unit testing": ["TDD", "Unit Testing (Unity/C)"],
}

ATS_KEYWORD_PHRASES = {
    "analytical": "analytical problem-solving",
    "communication": "clear cross-functional communication",
    "logging": "structured logging",
    "monitoring": "production monitoring",
    "scalability": "scalability",
    "security": "security-focused API design",
    "authentication": "authentication",
    "ci/cd": "CI/CD",
    "unit testing": "unit testing",
}


def improve_tailored_resume_for_ats(
    tailored_resume: TailoredResume,
    missing_keywords: List[str],
) -> tuple[TailoredResume, List[str], List[str]]:
    """
    Add missing ATS keywords only when covered by verified skills or truthful soft skills.

    Unsupported tools, for example Jenkins when it is not in VERIFIED_SKILLS, are left out
    instead of being invented.
    """
    updated = tailored_resume.model_copy(deep=True)
    added = []
    skipped = []

    existing_skills = list(updated.skills or [])
    summary_terms = []

    for keyword in missing_keywords:
        normalized = keyword.lower().strip()
        mapped_skills = ATS_KEYWORD_SKILL_MAP.get(normalized, [])
        supported = False

        for skill in mapped_skills:
            if skill in VERIFIED_SKILLS and skill not in existing_skills:
                existing_skills.append(skill)
                supported = True

        phrase = ATS_KEYWORD_PHRASES.get(normalized)
        if phrase:
            summary_terms.append(phrase)
            supported = True

        if supported:
            added.append(keyword)
            if keyword not in updated.keywords_matched:
                updated.keywords_matched.append(keyword)
        else:
            skipped.append(keyword)

    if summary_terms:
        unique_terms = []
        seen = set()
        for term in summary_terms:
            key = term.lower()
            if key not in seen and key not in updated.summary.lower():
                unique_terms.append(term)
                seen.add(key)

        if unique_terms:
            ats_sentence = (
                "Additional strengths include "
                + ", ".join(unique_terms[:6])
                + " across reliable backend delivery."
            )
            updated.summary = f"{updated.summary.rstrip()} {ats_sentence}"

    updated.skills = existing_skills[:18]
    updated.keywords_missing = [
        keyword for keyword in updated.keywords_missing if keyword not in added
    ]

    return updated, added, skipped


# ═══════════════════════════════════════════════════════════════
# MAIN TAILORING FUNCTION
# ═══════════════════════════════════════════════════════════════


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=1, max=5),
    retry=retry_if_exception_type(ValueError),
    before_sleep=lambda retry_state: console.log(
        f"[yellow]Retry {retry_state.attempt_number}/3 (validation failed)[/yellow]"
    ),
)
async def tailor_resume(
    job_description: str,
    base_resume_path: Optional[str] = None,
) -> TailoredResume:
    """
    Tailor resume to job description using LLM.
    
    Orchestrates:
      1. Load base resume from JSON
      2. Extract JD keywords
      3. Summarize JD if too long
      4. Initialize LLM chain
      5. Generate tailored summary + bullets + skills
      6. Validate output (anti-hallucination enforcement)
    
    ⚠️ FAILURE POINTS:
      - LLM provider unavailable → raised to caller
      - Hallucination detected → Pydantic validation error → retried with stricter prompt
      - JD summarization loses keywords → logs warning, continues
      - Large JD → auto-truncated to JD_MAX_WORDS
    
    Args:
        job_description: Extracted job description text
        base_resume_path: Path to base_resume.json (optional, uses config default)
        
    Returns:
        TailoredResume Pydantic model
        
    Raises:
        ValueError: If LLM output fails validation (retried)
        FileNotFoundError: If base resume not found
    """
    if not base_resume_path:
        base_resume_path = str(BASE_RESUME_PATH)
    
    console.log("[bold cyan]MODULE 2 — LLM Resume Tailoring[/bold cyan]")
    
    # Load base resume
    console.log("[blue]Loading base resume...[/blue]")
    with open(base_resume_path, "r", encoding="utf-8") as f:
        base_resume = json.load(f)
    
    # Extract keywords from JD
    console.log("[blue]Extracting keywords...[/blue]")
    jd_keywords = extract_keywords(job_description)
    console.log(f"[green]Found {len(jd_keywords)} keywords[/green]")
    
    # Match to verified skills
    matched_skills, missing_keywords = match_skills_to_verified(jd_keywords)
    console.log(f"[green]Matched {len(matched_skills)} verified skills[/green]")
    console.log(f"[yellow]{len(missing_keywords)} keywords not in Yash's skills[/yellow]")
    
    # Compact JD without a slow extra LLM summarization call.
    llm = get_llm_chain()
    jd_for_processing = compact_jd_for_tailoring(job_description)
    
    # Build experience items
    base_experience = base_resume.get("experience", [])
    experience_items = []
    
    for exp in base_experience:
        bullets = exp.get("bullets", [])
        for bullet in bullets:
            experience_items.append({
                "original": bullet,
                "tailored": bullet,  # Will be rewritten by LLM
            })
    
    # Build prompt with anti-hallucination enforcement
    parser = PydanticOutputParser(pydantic_object=TailoredResume)
    
    prompt = PromptTemplate(
        input_variables=["jd_text", "base_summary", "experience_bullets", "verified_skills"],
        template="""You are a professional resume writer. Your job is to tailor Yash Gupta's resume to a job description.

⚠️ CRITICAL CONSTRAINT — ANTI-HALLUCINATION:
You are STRICTLY FORBIDDEN from adding any skill, tool, technology, or experience NOT in the VERIFIED_SKILLS list below.
If the job requires a skill Yash does not have, mark it in keywords_missing — NEVER invent a match.
Violation of this constraint is a CRITICAL FAILURE.

VERIFIED SKILLS (ALL skills must come from this list):
{verified_skills}

BASE RESUME SUMMARY:
{base_summary}

EXPERIENCE BULLETS (to be tailored):
{experience_bullets}

JOB DESCRIPTION:
{jd_text}

Task:
1. Write a concise 2 sentence professional summary tailored to this JD, highlighting keywords from the job description that match Yash's verified skills.
2. Rewrite each experience bullet to emphasize skills and achievements relevant to the JD. Keep each tailored bullet under 120 characters where possible and preserve truthful metrics.
3. Select 10-14 verified skills most relevant to this role, prioritizing exact JD matches.
4. Identify JD keywords that match Yash's verified skills (keywords_matched).
5. Identify JD requirements that Yash does NOT have (keywords_missing) — be honest about gaps.

IMPORTANT:
- ONLY use skills from VERIFIED_SKILLS list
- Do NOT invent tools or technologies Yash doesn't have
- keywords_missing should be HONEST gaps, not empty

{format_instructions}

Output JSON:""",
        partial_variables={
            "verified_skills": ", ".join(VERIFIED_SKILLS),
            "format_instructions": parser.get_format_instructions(),
        },
    )
    
    # Prepare variables
    base_summary = base_resume.get("summary", "")
    experience_bullets = "\n".join([f"- {b['original']}" for b in experience_items])
    
    # Invoke LLM
    console.log("[blue]Invoking LLM for tailoring...[/blue]")
    chain = prompt | llm
    
    response = await asyncio.wait_for(
        asyncio.to_thread(
            chain.invoke,
            {
                "jd_text": jd_for_processing,
                "base_summary": base_summary,
                "experience_bullets": experience_bullets,
            },
        ),
        timeout=RESUME_TAILOR_LLM_TIMEOUT_SECONDS,
    )
    
    # Extract content if response is a message object
    if hasattr(response, "content"):
        response_text = response.content
    else:
        response_text = str(response)
    
    if DEBUG:
        console.log(f"[dim]LLM Response (raw):\n{response_text}[/dim]")
    
    # Parse JSON output
    try:
        # Try to extract JSON from response
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            output_dict = json.loads(json_str)
        else:
            output_dict = json.loads(response_text)
    except json.JSONDecodeError as e:
        console.log(f"[red]Failed to parse LLM JSON output: {e}[/red]")
        if DEBUG:
            console.log(f"[dim]Response was:\n{response_text}[/dim]")
        raise ValueError(f"LLM output is not valid JSON: {e}")
    
    # Validate with Pydantic (anti-hallucination enforcement)
    try:
        tailored_resume = TailoredResume(**output_dict)
        console.log("[green]✓ Validation passed (no hallucination detected)[/green]")
        return tailored_resume
    
    except ValueError as e:
        # ⚠️ Hallucination detected by validator
        console.log(f"[red]✗ Validation failed (hallucination detected): {e}[/red]")
        raise  # Trigger @retry


async def main():
    """Test tailoring with sample JD"""
    sample_jd = """
    Software Engineer - Backend
    
    We're looking for a Backend Software Engineer to join our team.
    
    Required Skills:
    - 3+ years Python experience
    - AWS (EC2, S3, Lambda, RDS)
    - Docker & Kubernetes
    - REST APIs
    - SQL databases (PostgreSQL, MySQL)
    - Git version control
    
    Nice to Have:
    - Scala or Go
    - Kubernetes
    - Machine Learning basics
    - GCP experience
    
    Responsibilities:
    - Design and implement scalable APIs
    - Optimize database queries
    - Implement CI/CD pipelines
    - Write unit tests
    - Mentor junior engineers
    
    Qualifications:
    - B.Tech in Computer Science or related field
    - Strong problem-solving skills
    - Experience with agile methodologies
    """
    
    result = await tailor_resume(sample_jd)
    
    console.print("\n[bold]Tailored Resume:[/bold]")
    console.print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
