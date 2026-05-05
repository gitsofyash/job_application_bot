"""
Optional Gemini polish layer.

Gemini never owns final structured resume or cover-letter generation here. It
only rewrites prose after Cohere has produced validated objects.
"""

import asyncio
import json
from typing import Any

from rich.console import Console

from config.settings import (
    ENABLE_GEMINI_POLISH,
    GEMINI_MODEL,
    GEMINI_POLISH_TIMEOUT_SECONDS,
    GOOGLE_API_KEY,
)
from modules.m2_tailor import TailoredResume
from modules.m5_coverletter import CoverLetter

console = Console()


def _strip_json_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def _extract_text(response: Any) -> str:
    if hasattr(response, "content"):
        content = response.content
        if isinstance(content, list):
            return "".join(str(item.get("text", item)) for item in content)
        return str(content)
    return str(response)


def _gemini_llm():
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY not set")
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as e:
        raise ImportError(
            "langchain-google-genai is required for optional Gemini polish"
        ) from e

    return ChatGoogleGenerativeAI(
        google_api_key=GOOGLE_API_KEY,
        model=GEMINI_MODEL,
        temperature=0.25,
    )


async def polish_resume_with_gemini(
    tailored_resume: TailoredResume,
    missing_keywords: list[str],
) -> TailoredResume:
    """
    Rewrite summary and tailored bullets only.

    Skills, matched keywords, and missing keywords are intentionally preserved so
    Cohere/local code remains the source of truth for structured fields.
    """
    if not ENABLE_GEMINI_POLISH:
        return tailored_resume

    prompt = f"""Polish this resume content for clarity and ATS readability.

You are only allowed to rewrite:
- summary
- each experience item's tailored sentence

Do not add fake experience. Do not change original bullets.
Do not return skills, keywords_matched, or keywords_missing.
Use the missing keywords naturally only when supported by the existing text.

Missing ATS keywords to consider:
{missing_keywords[:12]}

Current resume JSON:
{tailored_resume.model_dump_json()}

Return only JSON:
{{
  "summary": "polished summary",
  "experience_tailored": ["tailored bullet 1", "tailored bullet 2"]
}}
"""

    console.log(f"[cyan]Optional Gemini resume polish enabled: {GEMINI_MODEL}[/cyan]")
    llm = _gemini_llm()
    response = await asyncio.wait_for(
        asyncio.to_thread(llm.invoke, prompt),
        timeout=GEMINI_POLISH_TIMEOUT_SECONDS,
    )
    cleaned = _strip_json_fences(_extract_text(response))
    parsed = json.loads(cleaned)

    updated = tailored_resume.model_copy(deep=True)
    if parsed.get("summary"):
        updated.summary = str(parsed["summary"])

    polished_bullets = parsed.get("experience_tailored") or []
    for item, polished in zip(updated.experience, polished_bullets):
        if polished:
            item.tailored = str(polished)

    return updated


async def polish_cover_letter_with_gemini(cover_letter: CoverLetter) -> CoverLetter:
    """Polish cover-letter prose while preserving the same schema."""
    if not ENABLE_GEMINI_POLISH:
        return cover_letter

    prompt = f"""Polish this cover letter to sound natural, concise, and professional.

Do not invent experience, companies, tools, degrees, or years.
Keep the same JSON schema and complete paragraphs.

Cover letter JSON:
{cover_letter.model_dump_json()}

Return only valid JSON with the same fields.
"""

    console.log(f"[cyan]Optional Gemini cover-letter polish enabled: {GEMINI_MODEL}[/cyan]")
    llm = _gemini_llm()
    response = await asyncio.wait_for(
        asyncio.to_thread(llm.invoke, prompt),
        timeout=GEMINI_POLISH_TIMEOUT_SECONDS,
    )
    cleaned = _strip_json_fences(_extract_text(response))
    return CoverLetter(**json.loads(cleaned))
