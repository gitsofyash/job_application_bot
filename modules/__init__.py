"""
Job Application Automation Bot Modules

Orchestrates job description extraction, resume tailoring, PDF generation, and auto-apply workflows.
"""

from .m1_extractor import ExtractionResult, extract_job_description
from .m2_tailor import TailoredResume, tailor_resume
from .m3_generator import generate_resume_pdf
from .m4_apply import apply_to_job

__all__ = [
    "ExtractionResult",
    "extract_job_description",
    "TailoredResume",
    "tailor_resume",
    "generate_resume_pdf",
    "apply_to_job",
]
