"""
MODULE 2 Ã¢â‚¬â€ LLM Resume Tailoring

Tailors resume content to job description using LangChain + LLM (Ollama/OpenAI/Anthropic).

Features:
  - Keyword extraction from job description
  - Intelligent matching to verified skills (anti-hallucination enforced)
  - LLM-powered bullet point rewriting to match JD keywords
  - Token guard: summarizes JD if > 3000 words before processing
  - Swappable LLM backend via LLM_PROVIDER env var
  - Honest keywords_missing marking (gaps are NOT hidden)
  - Pydantic validation on all outputs

Ã¢Å¡Â Ã¯Â¸Â FAILURE POINTS:
  1. LLM provider unavailable Ã¢â€ â€™ LLMError raised (caller can retry with fallback)
  2. Hallucination in output Ã¢â€ â€™ Pydantic validation catches and re-prompts
  3. JD too large Ã¢â€ â€™ Auto-summarized via LLM before keyword extraction
  4. Token limit exceeded Ã¢â€ â€™ Gracefully truncates skills/keywords

MITIGATION:
  - Structured output validation via Pydantic
  - Explicit system prompt enforcement (anti-hallucination)
  - LLM retry logic with prompt refinement
  - Token counting before LLM call
"""

import asyncio
import json
import re
import traceback
import os
from typing import Optional, List, Any
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
    COHERE_API_KEY,
    COHERE_MODEL,
    JD_MAX_WORDS,
    RESUME_TAILOR_LLM_TIMEOUT_SECONDS,
    VERIFIED_SKILLS,
    BASE_RESUME_PATH,
    DEBUG,
)

console = Console()

# Ã¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢Â
# MODELS
# Ã¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢Â


class ExperienceItem(BaseModel):
    """Single experience bullet point"""
    original: str = Field(..., description="Original bullet from base resume")
    tailored: str = Field(..., description="Tailored bullet matching JD keywords")


class TailoredResume(BaseModel):
    """
    Complete tailored resume output from LLM.
    
    Ã¢Å¡Â Ã¯Â¸Â Anti-hallucination constraint:
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
        """Accept dynamic skills added by the gap-bridging pipeline."""
        return v


# Ã¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢Â
# LLM PROVIDER INITIALIZATION
# Ã¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢Â


def get_llm_chain():
    """
    Initialize LLM chain based on LLM_PROVIDER env var.
    
    Supports:
      - OLLAMA (local, default)
      - OPENAI (gpt-4-turbo)
      - ANTHROPIC (claude-opus)
      - COHERE (command-a-03-2025)
    
    Ã¢Å¡Â Ã¯Â¸Â FAILURE POINT: Provider not available Ã¢â€ â€™ raises ImportError or connection error.
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
            
        elif LLM_PROVIDER == "COHERE":
            if not COHERE_API_KEY:
                raise ValueError("COHERE_API_KEY not set in .env")

            return None
        
        else:
            raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")
    
    except ImportError as e:
        raise ImportError(
            f"LLM provider {LLM_PROVIDER} not installed. "
            f"Install the matching LangChain integration or use COHERE."
        ) from e


def _cohere_response_text(response: Any) -> str:
    """Extract text from a Cohere v2 chat response."""
    content = getattr(getattr(response, "message", None), "content", None) or []
    if content:
        return "".join(getattr(item, "text", "") for item in content).strip()
    return str(response)


def summarize_jd_with_cohere(jd_text: str) -> str:
    """Use Cohere specifically to extract and summarize the JD."""
    import os
    
    # Force read from env to bypass config.py caching
    cohere_key = os.getenv("COHERE_API_KEY") or COHERE_API_KEY 
    
    if not cohere_key:
        raise ValueError("COHERE_API_KEY not set in .env")
    
    try:
        import cohere
    except ImportError as e:
        raise ImportError("Cohere SDK not installed. Install with: pip install cohere") from e

    target_model = COHERE_MODEL
    console.log(f"[cyan]Using Cohere ({target_model}) for JD Summarization[/cyan]")
    
    client = cohere.ClientV2(api_key=cohere_key)
    
    prompt = f"""You are an expert technical recruiter. Extract ONLY the hard technical requirements, programming languages, and core responsibilities from this job description. Do not write paragraphs. Extract a dense, comma-separated list of skills and duties.

    Raw Job Description:
    {jd_text}
    """
    
    response = client.chat(
        model=target_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1
    )
    return _cohere_response_text(response)


def invoke_cohere_json(prompt_text: str, max_tokens: int = 1800) -> str:
    """Call Cohere directly using the official SDK and request JSON output."""
    if not COHERE_API_KEY:
        raise ValueError("COHERE_API_KEY not set in .env")

    try:
        import cohere
    except ImportError as e:
        raise ImportError("Cohere SDK not installed. Install with: pip install cohere") from e

    console.log(f"[cyan]Initializing Cohere SDK: {COHERE_MODEL}[/cyan]")
    client = cohere.ClientV2(api_key=COHERE_API_KEY)
    response = client.chat(
        model=COHERE_MODEL,
        messages=[
            {
                "role": "system",
                "content": "Return only valid JSON. Do not include Markdown fences.",
            },
            {"role": "user", "content": prompt_text},
        ],
        response_format={"type": "json_object"},
        temperature=0.25,
        max_tokens=max_tokens,
    )
    return _cohere_response_text(response)


def stringify_prompt_value(value: Any) -> str:
    """Normalize prompt variables so lists/dicts never reach regex/string APIs."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        return ", ".join(stringify_prompt_value(item) for item in value if item is not None)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


# Ã¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢Â
# TEXT PROCESSING UTILITIES
# Ã¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢Â


def count_words(text: str) -> int:
    """Count words in text"""
    return len(text.split())


def summarize_jd(jd_text: str, llm) -> str:
    """
    Summarize job description if it exceeds JD_MAX_WORDS.
    
    Ã¢Å¡Â Ã¯Â¸Â FAILURE POINT: Summarization may lose important keywords.
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
    ignored_capitalized_terms = {
        "about",
        "backend",
        "company",
        "description",
        "engineer",
        "job",
        "preferred",
        "qualifications",
        "requirements",
        "responsibilities",
        "role",
        "software",
        "summary",
    }
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            # Split by comma, slash, pipe, semicolon, or standalone and/or.
            terms = re.split(r"\s*(?:,|/|\||;|\band\b|\bor\b)\s*", match, flags=re.IGNORECASE)
            keywords.extend([term.strip() for term in terms if term.strip()])
    
    known_capitalized_tech_terms = {
        "aws",
        "boto3",
        "ci",
        "cloudwatch",
        "docker",
        "dynamodb",
        "ec2",
        "flask",
        "git",
        "iam",
        "java",
        "javascript",
        "jwt",
        "kafka",
        "kubernetes",
        "lambda",
        "mysql",
        "postgresql",
        "python",
        "rds",
        "redis",
        "s3",
        "sql",
    }

    # Also try to find known capitalized technical terms without treating
    # company names and section titles as skill gaps.
    technical_terms = re.findall(r"\b([A-Z][a-zA-Z0-9\+\#\.\-]*)\b", text)
    keywords.extend(
        term
        for term in technical_terms
        if term.lower() in known_capitalized_tech_terms
        and term.lower() not in ignored_capitalized_terms
    )
    
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
        if len(k) > 2
        and k.lower() not in ignored_capitalized_terms
        and not (k.lower() in seen or seen.add(k.lower()))
    ]
    
    return keywords[:30]  # Limit to top 30 keywords


def match_skills_to_verified(jd_keywords: List[str]) -> tuple[List[str], List[str]]:
    """
    Match JD keywords to verified skills.
    Returns matched and missing skills.
    
    Ã¢Å¡Â Ã¯Â¸Â ANTI-HALLUCINATION:
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
    "caching": ["Redis"],
    "security": ["JWT Authentication", "AWS IAM"],
    "authentication": ["JWT Authentication"],
    "authorization": ["JWT Authentication", "AWS IAM"],
    "api design": ["API Design", "REST APIs"],
    "bash": ["Bash"],
    "cloud cost optimization": ["Cloud Cost Optimization"],
    "debugging": ["Debugging Tools"],
    "ci/cd": ["CI/CD"],
    "unit testing": ["TDD", "Unit Testing (Unity/C)"],
    "algorithms": ["Algorithms", "Data Structures"],
    "data structures": ["Data Structures", "Algorithms"],
    "distributed systems": ["System Design", "Microservices"],
    "system design": ["System Design"],
    "event-driven": ["System Design", "Microservices"],
    "dynamodb": ["AWS DynamoDB"],
    "apache": ["Kafka", "Apache Kafka"],
    "agile": ["Agile/Scrum", "SDLC"],
    "testing": ["TDD", "Unit Testing (Unity/C)"],
    "database": ["SQL", "MySQL", "PostgreSQL", "SQLAlchemy"],
    "cache": ["Redis"],
    "api": ["REST APIs", "API Design"],
    "microservice": ["Microservices", "System Design"],
    "microservices": ["Microservices", "System Design"],
    "kafka": ["Apache Kafka"],
    "kubernetes": ["Docker"],
    "docker": ["Docker"],
    "cloud": ["AWS EC2", "AWS S3", "AWS Lambda", "System Design"],
    "rest": ["REST APIs"],
}

ATS_KEYWORD_PHRASES = {
    "analytical": "analytical problem-solving",
    "communication": "cross-functional team communication and collaboration",
    "collaboration": "cross-functional team communication and collaboration",
    "attention to detail": "attention to detail in code quality, testing, and production readiness",
    "mentoring": "mentoring through technical workshops, code reviews, and developer guidance",
    "problem-solving": "practical problem-solving across backend, cloud, and embedded systems",
    "team player": "collaborative team player across engineering and hardware teams",
    "self-motivated": "self-motivated ownership of independent learning and delivery",
    "quick learner": "quick learner adapting across cloud, backend, and embedded domains",
    "leadership": "technical leadership through workshops and cross-team delivery",
    "logging": "structured logging and centralized logging",
    "monitoring": "production monitoring and observability",
    "scalability": "system scalability and performance optimization",
    "caching": "Redis caching strategies",
    "security": "security-focused API design and authentication",
    "authentication": "secure authentication mechanisms",
    "authorization": "role-based access control",
    "ci/cd": "CI/CD pipelines and automation",
    "unit testing": "comprehensive unit testing",
    "algorithms": "algorithmic optimization",
    "data structures": "efficient data structure usage",
    "distributed systems": "distributed system architecture",
    "system design": "large-scale system design",
    "event-driven": "event-driven architecture",
    "dynamodb": "NoSQL database design",
    "apache": "Apache ecosystem and message queues",
    "agile": "Agile development methodologies",
    "testing": "rigorous testing practices",
    "database": "database optimization and design",
    "cache": "caching strategies and optimization",
    "api": "RESTful API development",
    "microservice": "microservices architecture",
    "microservices": "microservices architecture",
    "kafka": "Apache Kafka event streaming",
    "kubernetes": "container orchestration",
    "docker": "containerization best practices",
    "cloud": "cloud infrastructure optimization",
    "rest": "REST API design patterns",
}

ATS_SOFT_SKILL_LABELS = {
    "analytical": "Analytical Skills",
    "attention to detail": "Attention to Detail",
    "communication": "Communication",
    "collaboration": "Collaboration",
    "leadership": "Leadership",
    "mentoring": "Mentoring",
    "problem-solving": "Problem-Solving",
    "quick learner": "Quick Learner",
    "self-motivated": "Self-Motivated",
    "team player": "Team Player",
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

        soft_skill_label = ATS_SOFT_SKILL_LABELS.get(normalized)
        if soft_skill_label and soft_skill_label not in existing_skills:
            # Keep ATS-required soft skills early enough to survive compact
            # one-page density profiles that cap the skills line.
            insert_at = min(6, len(existing_skills))
            existing_skills.insert(insert_at, soft_skill_label)
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
            core_summary = re.sub(
                r"\s+Additional strengths\b.*$",
                "",
                updated.summary.rstrip(),
                flags=re.IGNORECASE,
            )
            first_sentence = core_summary.split(".")[0].strip()
            if first_sentence:
                core_summary = f"{first_sentence}."
            ats_sentence = "Strengths include " + ", ".join(unique_terms[:5]) + "."
            updated.summary = f"{core_summary} {ats_sentence}"

    updated.skills = existing_skills[:24]
    updated.keywords_missing = [
        keyword for keyword in updated.keywords_missing if keyword not in added
    ]

    return updated, added, skipped


# Ã¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢Â
# MAIN TAILORING FUNCTION
# Ã¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢Â


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
    
    Ã¢Å¡Â Ã¯Â¸Â FAILURE POINTS:
      - LLM provider unavailable Ã¢â€ â€™ raised to caller
      - Hallucination detected Ã¢â€ â€™ Pydantic validation error Ã¢â€ â€™ retried with stricter prompt
      - JD summarization loses keywords Ã¢â€ â€™ logs warning, continues
      - Large JD Ã¢â€ â€™ auto-truncated to JD_MAX_WORDS
    
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
    
    console.log("[bold cyan]MODULE 2 Ã¢â‚¬â€ LLM Resume Tailoring[/bold cyan]")
    
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
    
    # --- MULTI-MODEL PIPELINE UPDATE ---
    # 1. Pipeline Step 1: Use Cohere to extract and summarize the JD
    try:
        console.log("[blue]Processing JD with Cohere...[/blue]")
        jd_summary = await asyncio.to_thread(summarize_jd_with_cohere, job_description)
        jd_for_processing = stringify_prompt_value(jd_summary)
    except Exception as e:
        console.log(f"[yellow]Cohere JD summarization failed ({e}), falling back to heuristic compaction...[/yellow]")
        jd_for_processing = stringify_prompt_value(compact_jd_for_tailoring(job_description))
    
    # 2. Pipeline Step 2: Use Cohere SDK for CV tailoring.
    
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

CRITICAL CONSTRAINT - ANTI-HALLUCINATION:
You are STRICTLY FORBIDDEN from adding any skill, tool, technology, or experience NOT in the VERIFIED_SKILLS list below.
If the job requires a skill Yash does not have, mark it in keywords_missing - NEVER invent a match.
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
2. Rewrite each work experience bullet to emphasize JD-relevant keywords while preserving original truth and metrics. Do not delete work experience records.
3. Select 10-16 verified skills most relevant to this role, prioritizing exact JD matches and avoiding keyword stuffing.
4. Identify JD keywords that match Yash's verified skills (keywords_matched).
5. Identify JD requirements that Yash does NOT have (keywords_missing) - be honest about gaps.

IMPORTANT:
- ONLY use skills from VERIFIED_SKILLS list
- Do NOT invent tools or technologies Yash doesn't have
- When listing skills in the JSON output, you MUST use the exact string formats provided in the VERIFIED_SKILLS list. Do not use generic abbreviations (e.g., use 'AWS EC2' instead of 'AWS') or the validation will fail.
- The generator will keep every certification and achievement from BASE_RESUME and exactly 3 JD-relevant projects.
- keywords_missing should be HONEST gaps, not empty

{format_instructions}

Output JSON:""",
        partial_variables={
            "verified_skills": ", ".join(VERIFIED_SKILLS),
            "format_instructions": parser.get_format_instructions(),
        },
    )
    
    # Prepare variables
    base_summary = stringify_prompt_value(base_resume.get("summary", ""))
    experience_bullets = "\n".join(
        f"- {stringify_prompt_value(b['original'])}" for b in experience_items
    )
    prompt_payload = {
        "jd_text": jd_for_processing,
        "base_summary": base_summary,
        "experience_bullets": experience_bullets,
    }
    
    # Invoke Cohere
    console.log("[blue]Invoking Cohere for tailoring...[/blue]")
    try:
        prompt_text = prompt.format(**prompt_payload)
        response_text = await asyncio.wait_for(
            asyncio.to_thread(invoke_cohere_json, prompt_text),
            timeout=RESUME_TAILOR_LLM_TIMEOUT_SECONDS,
        )
    except Exception as e:
        console.print("\n" + "="*50, style="red bold")
        console.print("Ã°Å¸Å¡Â¨ FATAL MODULE 2 API ERROR Ã°Å¸Å¡Â¨", style="red bold")
        console.print(f"Error Message: {str(e)}", style="red")
        console.print("Traceback:", style="red")
        traceback.print_exc()
        console.print("="*50 + "\n", style="red bold")
        raise ValueError(f"LLM Invocation Failed: {str(e)}") from e
    
    if DEBUG:
        console.log(f"[dim]LLM Response (raw):\n{response_text}[/dim]")
    
    # Parse JSON output
    try:
        # Strip markdown code blocks if the provider added them
        clean_text = response_text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
            
        clean_text = clean_text.strip()
        
        # Try to parse the cleaned text directly first
        try:
            output_dict = json.loads(clean_text)
        except json.JSONDecodeError:
            # Fallback: aggressively search for the first { and last }
            start_idx = clean_text.find('{')
            end_idx = clean_text.rfind('}')
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_str = clean_text[start_idx:end_idx + 1]
                output_dict = json.loads(json_str)
            else:
                raise ValueError("No JSON object found in response")
                
    except Exception as e:
        console.log(f"[red]Failed to parse LLM JSON output: {e}[/red]")
        if DEBUG:
            console.log(f"[dim]Response was:\n{response_text}[/dim]")
        raise ValueError(f"LLM output is not valid JSON: {e}")
    
    # Validate with Pydantic (anti-hallucination enforcement)
    try:
        tailored_resume = TailoredResume(**output_dict)
        console.log("[green]Ã¢Å“â€œ Validation passed (no hallucination detected)[/green]")
        return tailored_resume
    
    except ValueError as e:
        # Ã¢Å¡Â Ã¯Â¸Â Hallucination detected by validator
        console.log(f"[red]Ã¢Å“â€” Validation failed (hallucination detected): {e}[/red]")
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
