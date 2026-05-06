"""
Global settings and configuration management for job application bot.
Loads environment variables with sensible defaults and validates types.
"""

import os
import sys
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

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
LLM_PROVIDER: Literal["COHERE", "OLLAMA", "OPENAI", "ANTHROPIC"] = os.getenv(
    "LLM_PROVIDER", "COHERE"
).upper()  # type: ignore

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4-turbo")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus")

COHERE_API_KEY = os.getenv("COHERE_API_KEY", "")
COHERE_MODEL = os.getenv("COHERE_MODEL", "command-a-03-2025")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
ENABLE_GEMINI_POLISH = os.getenv("ENABLE_GEMINI_POLISH", "false").lower() == "true"
GEMINI_POLISH_MIN_SCORE = float(os.getenv("GEMINI_POLISH_MIN_SCORE", "90"))
GEMINI_POLISH_TIMEOUT_SECONDS = int(os.getenv("GEMINI_POLISH_TIMEOUT_SECONDS", "25"))

# ATS score policy. The pipeline treats 90 as the minimum acceptable score and
# keeps optimizing toward 97 when truthful resume/profile evidence supports it.
ATS_MIN_SCORE = float(os.getenv("ATS_MIN_SCORE", "90"))
ATS_TARGET_SCORE = float(os.getenv("ATS_TARGET_SCORE", "97"))
ATS_MAX_IMPROVEMENT_PASSES = int(os.getenv("ATS_MAX_IMPROVEMENT_PASSES", "5"))

# Token guard: max words to process before summarization
JD_MAX_WORDS = int(os.getenv("JD_MAX_WORDS", "1000"))

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
    "Kubernetes",
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
    "Distributed Systems",
    "Event-driven Architecture",
    "Database Optimization",
    "Performance Optimization",
    "Testing",
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
# Strict 1-page enforcement with optimized content distribution
MAX_RESUME_LINES = 52  # Realistic for 8-9pt font on 1-page with 0.3in margins
MIN_FONT_SIZE = 8  # Absolute minimum for readability
INITIAL_FONT_SIZE = 8.6  # Optimal balance for ATS and readability at 1-page
CONTENT_CUTOFF_THRESHOLD = 0.95  # Fill closer to max capacity (95% of page)


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
