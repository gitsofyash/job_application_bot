"""
Global settings and configuration management for job application bot.
Loads environment variables with sensible defaults and validates types.
"""

import os
import sys
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv

# Load .env file
load_dotenv()

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

# ═══════════════════════════════════════════════════════════════
# PROJECT PATHS
# ═══════════════════════════════════════════════════════════════
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# Ensure directories exist
OUTPUT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# LLM CONFIGURATION
# ═══════════════════════════════════════════════════════════════
LLM_PROVIDER: Literal["OLLAMA", "OPENAI", "ANTHROPIC"] = os.getenv(
    "LLM_PROVIDER", "OLLAMA"
).upper()  # type: ignore

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = "gpt-4-turbo"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = "claude-opus"

# Token guard: max words to process before summarization
JD_MAX_WORDS = 1000

# Resume tailoring defaults to the deterministic ATS-optimized path. Turn this
# on only when you specifically want slower LLM bullet rewriting.
RESUME_TAILOR_USE_LLM = os.getenv("RESUME_TAILOR_USE_LLM", "false").lower() == "true"
RESUME_TAILOR_LLM_TIMEOUT_SECONDS = int(os.getenv("RESUME_TAILOR_LLM_TIMEOUT_SECONDS", "45"))

# Cover letters default to a fast deterministic generator. Set true only when
# you specifically want the slower LLM-written version.
COVER_LETTER_USE_LLM = os.getenv("COVER_LETTER_USE_LLM", "false").lower() == "true"
COVER_LETTER_MAX_CHARS = int(os.getenv("COVER_LETTER_MAX_CHARS", "2400"))
COVER_LETTER_LLM_TIMEOUT_SECONDS = int(os.getenv("COVER_LETTER_LLM_TIMEOUT_SECONDS", "35"))
COVER_LETTER_LLM_MAX_WORDS = int(os.getenv("COVER_LETTER_LLM_MAX_WORDS", "650"))
COVER_LETTER_LLM_MAX_TOKENS = int(os.getenv("COVER_LETTER_LLM_MAX_TOKENS", "650"))

# ═══════════════════════════════════════════════════════════════
# BROWSER CONFIGURATION
# ═══════════════════════════════════════════════════════════════
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
VIEWPORT_WIDTH = int(os.getenv("VIEWPORT_WIDTH", "1440"))
VIEWPORT_HEIGHT = int(os.getenv("VIEWPORT_HEIGHT", "900"))
TIMEOUT_MS = int(os.getenv("TIMEOUT_MS", "30000"))
WAIT_NETWORK_IDLE_TIMEOUT = int(os.getenv("WAIT_NETWORK_IDLE_TIMEOUT", "10000"))
BROWSER_TYPE = os.getenv("BROWSER_TYPE", "chromium").lower()

# Anti-bot spoofing
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
LOCALE = "en-US"
TIMEZONE = "Asia/Kolkata"

# ═══════════════════════════════════════════════════════════════
# APPLICATION CONFIGURATION
# ═══════════════════════════════════════════════════════════════
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ═══════════════════════════════════════════════════════════════
# RETRY LOGIC (tenacity)
# ═══════════════════════════════════════════════════════════════
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2
RETRY_INITIAL_WAIT = 2

# ═══════════════════════════════════════════════════════════════
# VERIFIED SKILLS (Anti-hallucination constraint)
# ═══════════════════════════════════════════════════════════════
VERIFIED_SKILLS = [
    "Python",
    "Golang",
    "SQL",
    "C++",
    "Embedded C",
    "JavaScript",
    "Bash",
    "Flask",
    "REST APIs",
    "Microservices",
    "System Design",
    "Data Structures",
    "Algorithms",
    "API Design",
    "Git",
    "Docker",
    "VS Code",
    "AWS EC2",
    "AWS S3",
    "AWS Lambda",
    "AWS RDS",
    "AWS DynamoDB",
    "AWS API Gateway",
    "AWS IAM",
    "AWS CloudWatch",
    "Boto3",
    "MySQL",
    "PostgreSQL",
    "Redis",
    "SQLAlchemy",
    "SQLAlchemy ORM",
    "JWT Authentication",
    "CI/CD",
    "TDD",
    "Agile/Scrum",
    "SDLC",
    "Cloud Cost Optimization",
    "CAN Bus protocols",
    "Sensor Fusion",
    "Real-time Data Processing",
    "Embedded Systems",
    "System Reliability",
    "Unit Testing (Unity/C)",
    "ASPICE compliance",
    "Jinja2",
    "Hash-based deduplication",
    "S3 pre-signed URLs",
    "Apache Kafka",
    "Monitoring Tools",
    "Logging Systems",
    "Debugging Tools",
]

# ATS Platform selectors
ATS_SELECTORS = {
    "greenhouse": {
        "job_title": '[data-test="job-title"]',
        "job_body": '[data-test="job-description"]',
        "apply_btn": 'a[href*="/applications/new"]',
    },
    "lever": {
        "job_title": ".postings-title",
        "job_body": ".show-post-content",
        "apply_btn": 'a[class*="postings-btn-apply"]',
    },
}

# ═══════════════════════════════════════════════════════════════
# RESUME GENERATION SETTINGS
# ═══════════════════════════════════════════════════════════════
# Strict 1-page enforcement
MAX_RESUME_LINES = 45  # Approximate lines per page
MIN_FONT_SIZE = 8  # Don't go below this
INITIAL_FONT_SIZE = 9.3  # Fill the page visually, then reduce content if needed
CONTENT_CUTOFF_THRESHOLD = 0.85  # Stop at 85% of page when reducing

# ═══════════════════════════════════════════════════════════════
# FILE PATHS
# ═══════════════════════════════════════════════════════════════
BASE_RESUME_PATH = DATA_DIR / "base_resume.json"
USER_PROFILE_PATH = DATA_DIR / "user_profile.json"
RESUME_TEMPLATE_PATH = TEMPLATES_DIR / "resume_ats.html"
OUTPUT_RESUME_PDF = OUTPUT_DIR / "resume_final.pdf"
OUTPUT_RESUME_LATEX = OUTPUT_DIR / "resume_final.tex"

if __name__ == "__main__":
    # Diagnostic: print all settings
    print(f"LLM Provider: {LLM_PROVIDER}")
    print(f"Project Root: {PROJECT_ROOT}")
    print(f"Output Dir: {OUTPUT_DIR}")
    print(f"Dry Run: {DRY_RUN}")
    print(f"Debug: {DEBUG}")
