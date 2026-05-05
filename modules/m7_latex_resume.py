"""
Standalone LaTeX / Overleaf resume exporter.

This module does not replace the HTML/PDF pipeline. It generates an Overleaf-
ready .tex file from the same base resume data and optional tailored resume.
"""

import json
from pathlib import Path
from typing import Any, Optional

from rich.console import Console

from config.settings import OUTPUT_DIR
from modules.m2_tailor import TailoredResume, extract_keywords
from modules.m3_generator import (
    build_density_variant,
    DENSITY_PROFILES,
    load_base_resume,
    load_user_profile,
    merge_resume_data,
)
from utils.url_parser import sanitize_filename

console = Console()


def latex_escape(value: Any) -> str:
    """Escape text for LaTeX."""
    text = str(value or "")
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text


def _itemize(items: list[str]) -> str:
    lines = ["\\begin{itemize}"]
    for item in items:
        lines.append(f"  \\item {latex_escape(item)}")
    lines.append("\\end{itemize}")
    return "\n".join(lines)


def build_latex_resume(
    tailored_resume: Optional[TailoredResume] = None,
    base_resume_data: Optional[dict] = None,
    job_description: Optional[str] = None,
) -> str:
    """Build Overleaf-ready LaTeX source for the same resume content."""
    base_resume = json.loads(json.dumps(base_resume_data)) if base_resume_data else load_base_resume()
    user_profile = load_user_profile()
    resume_data = merge_resume_data(base_resume, user_profile, tailored_resume)

    jd_keywords = extract_keywords(job_description or "") if job_description else []
    if tailored_resume:
        jd_keywords.extend(tailored_resume.keywords_matched or [])
        jd_keywords.extend(tailored_resume.skills or [])
    jd_keywords = list(dict.fromkeys(str(keyword) for keyword in jd_keywords if str(keyword).strip()))
    resume_data = build_density_variant(resume_data, DENSITY_PROFILES[3], jd_keywords=jd_keywords)

    contact_parts = [
        latex_escape(resume_data.email),
        latex_escape(resume_data.phone),
        latex_escape(resume_data.linkedin or ""),
        latex_escape(resume_data.github or ""),
    ]
    contact = " $|$ ".join(part for part in contact_parts if part)

    lines = [
        r"\documentclass[10pt,letterpaper]{article}",
        r"\usepackage[margin=0.45in]{geometry}",
        r"\usepackage[hidelinks]{hyperref}",
        r"\usepackage{enumitem}",
        r"\usepackage{titlesec}",
        r"\setlength{\parindent}{0pt}",
        r"\setlist[itemize]{leftmargin=*, topsep=2pt, itemsep=1pt}",
        r"\titleformat{\section}{\large\bfseries}{}{0em}{}[\titlerule]",
        r"\begin{document}",
        rf"\begin{{center}}{{\LARGE \textbf{{{latex_escape(resume_data.name)}}}}}\\",
        rf"{contact}",
        r"\end{center}",
        r"\section*{Professional Summary}",
        latex_escape(resume_data.summary),
        r"\section*{Technical Skills}",
        latex_escape(", ".join(resume_data.skills)),
        r"\section*{Professional Experience}",
    ]

    for job in resume_data.experience:
        lines.append(
            rf"\textbf{{{latex_escape(job.get('title', ''))}}} $|$ "
            rf"{latex_escape(job.get('company', ''))} $|$ "
            rf"{latex_escape(job.get('duration', ''))}"
        )
        lines.append(_itemize([str(bullet) for bullet in job.get("bullets", [])]))

    lines.append(r"\section*{Projects}")
    for project in resume_data.projects:
        technologies = ", ".join(str(tech) for tech in project.get("technologies", []))
        lines.append(
            rf"\textbf{{{latex_escape(project.get('title', ''))}}} "
            rf"$|$ {latex_escape(technologies)}"
        )
        if project.get("description"):
            lines.append(latex_escape(project["description"]))
        lines.append(_itemize([str(bullet) for bullet in project.get("bullets", [])]))

    lines.append(r"\section*{Education}")
    for edu in resume_data.education:
        lines.append(
            rf"\textbf{{{latex_escape(edu.get('degree', ''))}}} $|$ "
            rf"{latex_escape(edu.get('institution', ''))} $|$ "
            rf"{latex_escape(edu.get('duration', ''))}"
        )

    if resume_data.certifications:
        lines.append(r"\section*{Certifications}")
        lines.append(_itemize([str(item) for item in resume_data.certifications]))

    if resume_data.achievements:
        lines.append(r"\section*{Achievements}")
        lines.append(_itemize([str(item) for item in resume_data.achievements]))

    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"


def save_latex_resume(
    tailored_resume: Optional[TailoredResume] = None,
    base_resume_data: Optional[dict] = None,
    job_description: Optional[str] = None,
    company_name: str = "default",
    output_dir: Optional[Path] = None,
) -> Path:
    """Save Overleaf-ready .tex resume and return the path."""
    output_dir = Path(output_dir or OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"resume_{sanitize_filename(company_name)}.tex"
    path.write_text(
        build_latex_resume(
            tailored_resume=tailored_resume,
            base_resume_data=base_resume_data,
            job_description=job_description,
        ),
        encoding="utf-8",
    )
    console.log(f"[green]LaTeX resume saved:[/green] {path}")
    return path


def main() -> None:
    """Generate a base-resume LaTeX file when run as a module."""
    path = save_latex_resume(company_name="base")
    console.print(f"LaTeX resume ready for Overleaf: {path}")


if __name__ == "__main__":
    main()
