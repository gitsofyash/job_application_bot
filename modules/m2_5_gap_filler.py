"""
Module 2.5 - Gap-Bridging Project Generator.

Creates a small independent-learning project for missing JD keywords and writes
starter code to generated_projects/<project_name>/<filename>.
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from utils.console import SafeConsole as Console

from config.settings import COHERE_API_KEY, COHERE_MODEL, PROJECT_ROOT

console = Console()

GENERATED_PROJECTS_DIR = PROJECT_ROOT / "generated_projects"


def _strip_markdown_fences(text: str) -> str:
    """Return raw JSON even if the model wraps it in Markdown fences."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def _safe_path_part(value: str, fallback: str = "gap-project") -> str:
    """Sanitize names used for generated project folders and files."""
    value = re.sub(r"[^\w\s.-]", "", value or fallback)
    value = re.sub(r"[\s_]+", "-", value).strip(".-").lower()
    return value[:60] or fallback


def _cohere_response_text(response: Any) -> str:
    """Extract text from a Cohere v2 chat response."""
    content = getattr(getattr(response, "message", None), "content", None) or []
    if content:
        return "".join(getattr(item, "text", "") for item in content).strip()
    return str(response)


def _call_cohere_gap_project(prompt: str) -> str:
    """Call Cohere and return the generated JSON text."""
    if not COHERE_API_KEY:
        raise ValueError("COHERE_API_KEY not set in .env")

    try:
        import cohere
    except ImportError as e:
        raise ImportError("Cohere SDK not installed. Install with: pip install cohere") from e

    client = cohere.ClientV2(api_key=COHERE_API_KEY)
    response = client.chat(
        model=COHERE_MODEL,
        messages=[
            {
                "role": "system",
                "content": "Return only valid JSON. Do not include Markdown fences.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=1200,
    )
    return _cohere_response_text(response)


async def generate_gap_project(missing_skills: list[str]) -> dict:
    """
    Generate and save a beginner-friendly backend/cloud project for missing skills.

    Returns:
        Parsed project dictionary with title, description, technologies, filename,
        boilerplate_code, project_path, and resume_project.
    """
    selected_skills = [str(skill).strip() for skill in missing_skills if str(skill).strip()]
    selected_skills = list(dict.fromkeys(selected_skills))[:10]
    if not selected_skills:
        return {}

    skills_text = ", ".join(selected_skills)
    prompt = f"""Design a beginner-friendly backend/cloud weekend project for Yash Gupta.

Missing JD skills to bridge:
{skills_text}

Use Python/AWS as the base and naturally incorporate the missing skills where realistic.
Incorporate enough of these missing skills to ensure the candidate achieves a minimum ATS keyword match score of 90+, aiming for maximum coverage.

Return ONLY strict JSON with exactly these fields:
{{
  "title": "short project title",
  "description": "one ATS-friendly bullet point describing what the project demonstrates",
  "technologies": ["technology", "technology"],
  "filename": "main.py",
  "boilerplate_code": "20-40 lines of runnable starter code"
}}

Rules:
- Keep the project beginner-friendly and plausible as independent learning.
- Prefer Python code unless a missing skill requires a tiny config/sample file.
- The boilerplate_code must be 20-40 lines.
- Do not include Markdown fences.
"""

    console.log(f"[cyan]Generating gap-bridging project with Cohere: {skills_text}[/cyan]")
    response_text = await asyncio.to_thread(_call_cohere_gap_project, prompt)
    cleaned = _strip_markdown_fences(response_text)

    try:
        project = json.loads(cleaned)
    except json.JSONDecodeError:
        start_idx = cleaned.find("{")
        end_idx = cleaned.rfind("}")
        if start_idx == -1 or end_idx <= start_idx:
            raise ValueError("Cohere gap project response did not contain a JSON object")
        project = json.loads(cleaned[start_idx : end_idx + 1])

    required = {"title", "description", "technologies", "filename", "boilerplate_code"}
    missing_fields = sorted(required - set(project))
    if missing_fields:
        raise ValueError(f"Gap project JSON missing fields: {missing_fields}")

    project_name = _safe_path_part(project["title"])
    filename = _safe_path_part(project["filename"], fallback="main.py")
    if "." not in filename:
        filename = f"{filename}.py"

    project_dir = GENERATED_PROJECTS_DIR / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    output_path = project_dir / filename
    output_path.write_text(str(project["boilerplate_code"]).rstrip() + "\n", encoding="utf-8")

    project["filename"] = filename
    project["project_path"] = str(output_path)
    project["resume_project"] = {
        "title": f"{project['title']} (Independent Learning)",
        "date": "Independent Learning",
        "description": project["description"],
        "technologies": [str(tech) for tech in project.get("technologies", [])],
        "bullets": [project["description"]],
    }
    console.log(f"[green]Gap project saved: {output_path}[/green]")
    return project
