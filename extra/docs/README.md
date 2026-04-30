# Job Application Automation Bot

**Production-ready Python application that automates end-to-end job applications for Yash Gupta.**

Orchestrates intelligent resume tailoring, PDF generation, and ATS form automation using LangChain + Playwright.

---

## 🎯 Features

### **Module 1: Job Description Extractor**
- Extracts job descriptions from ATS platforms (Greenhouse, Lever, unknown)
- Anti-bot spoofing: hides Playwright detection, realistic UA, locale/timezone
- Login wall & CAPTCHA detection with screenshots
- Structured output with platform detection
- Retry logic on network timeouts

### **Module 2: LLM Resume Tailoring**
- LangChain integration with swappable LLM backend (Ollama, OpenAI, Anthropic)
- Keyword extraction from job descriptions
- Intelligent skill matching to **verified skills only** (anti-hallucination enforced)
- Honest `keywords_missing` gap analysis
- Token guard: auto-summarizes JD if > 3000 words

### **Module 3: Resume PDF Generator**
- Jinja2 HTML template rendering
- Browser-based PDF conversion (Playwright)
- Single-page layout optimization
- Pre-populated with Yash's personal data
- Fallback to HTML if PDF conversion fails

### **Module 4: Auto-Apply ATS Automation**
- Intelligent form field detection (text, email, tel, select, file, textarea)
- Smart field mapping: first_name, last_name, email, phone, LinkedIn, GitHub
- Resume PDF file upload
- Submit button detection and post-submission confirmation
- DRY_RUN mode: fill form without submitting
- Screenshot audit trail

### **main.py Orchestrator**
- End-to-end CLI with `--url`, `--dry-run`, `--no-apply` flags
- Rich formatted output with execution summary table
- JSON result logging for each pipeline run
- Graceful error handling and retry logic

---

## 📋 Project Structure

```
job_application_bot/
├── .env.example              ← Copy to .env before running
├── requirements.txt          ← All dependencies
├── main.py                   ← Main CLI entry point
├── config/
│   ├── __init__.py
│   └── settings.py           ← Configuration & verified skills
├── data/
│   ├── base_resume.json      ← Pre-populated with Yash's resume
│   └── user_profile.json     ← Pre-populated with Yash's contact info
├── modules/
│   ├── __init__.py
│   ├── m1_extractor.py       ← Job description extraction
│   ├── m2_tailor.py          ← LLM resume tailoring
│   ├── m3_generator.py       ← PDF generation
│   └── m4_apply.py           ← Auto-apply automation
├── templates/
│   └── resume.html           ← Jinja2 resume template
└── output/                   ← Generated PDFs, screenshots, logs
```

---

## ⚡ Quick Start

### 1. Installation

```bash
# Clone/download project
cd job_application_bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (required for PDF generation & form automation)
playwright install chromium
```

### 2. Configuration

```bash
# Copy .env template
cp .env.example .env

# Edit .env with your settings
# Default: LLM_PROVIDER=OLLAMA (requires Ollama running on localhost:11434)
# Options: OLLAMA, OPENAI (set OPENAI_API_KEY), ANTHROPIC (set ANTHROPIC_API_KEY)
```

### 3. Verify Data Files

The bot comes pre-populated with Yash Gupta's data:
- ✅ `data/base_resume.json` — Complete resume with experience, education, projects
- ✅ `data/user_profile.json` — Contact info, name, email, phone, LinkedIn, GitHub

No further setup needed.

### 4. Run

```bash
# Full automation (extract JD → tailor resume → generate PDF → submit form)
python main.py --url "https://boards.greenhouse.io/example/jobs/12345"

# Dry run (fill form but don't submit)
DRY_RUN=true python main.py --url "https://..."

# Generate resume only (skip form submission)
python main.py --url "https://..." --no-apply

# Use OpenAI instead of Ollama
LLM_PROVIDER=OPENAI OPENAI_API_KEY=sk-xxx python main.py --url "https://..."
```

---

## 🔧 Configuration

### Environment Variables

```bash
# LLM Configuration
LLM_PROVIDER=OLLAMA              # OLLAMA | OPENAI | ANTHROPIC
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
OPENAI_API_KEY=sk-xxx            # If using OpenAI
ANTHROPIC_API_KEY=xxx            # If using Anthropic

# Browser Configuration
HEADLESS=true                    # false to see browser window
VIEWPORT_WIDTH=1440
VIEWPORT_HEIGHT=900
TIMEOUT_MS=30000
WAIT_NETWORK_IDLE_TIMEOUT=10000

# Application Configuration
DRY_RUN=false                    # true = fill form but don't submit
DEBUG=false                      # true = verbose logging
LOG_LEVEL=INFO

# Browser Type
BROWSER_TYPE=chromium            # chromium | firefox | webkit
```

---

## 📖 Usage Examples

### Example 1: Complete Automation

```bash
python main.py --url "https://boards.greenhouse.io/company/jobs/12345"
```

**Output:**
```
═══════════════════════════════════════════════════════════
JOB APPLICATION AUTOMATION BOT
═══════════════════════════════════════════════════════════
Job URL: https://boards.greenhouse.io/company/jobs/12345

╔════════════════════════════════════════╗
║ MODULE 1: Job Description Extraction  ║
╚════════════════════════════════════════╝

✓ Module 1 Complete (2.34s)
Platform: greenhouse
Words: 1250
Preview: We're looking for a Software Engineer...

╔════════════════════════════════════════╗
║ MODULE 2: LLM Resume Tailoring        ║
╚════════════════════════════════════════╝

✓ Module 2 Complete (8.12s)
Summary: Results-driven Software Engineer with expertise in Python...
Skills matched: 5
Skills missing: 2

[... Module 3 & 4 output ...]

PIPELINE EXECUTION SUMMARY
Module                       | Status           | Details              | Artifact
Module 1: Extraction        | ✓ SUCCESS       | 1250 words          | greenhouse
Module 2: Tailoring         | ✓ SUCCESS       | 5 matched, 2 missing | 5 keywords
Module 3: PDF Generation    | ✓ SUCCESS       | PDF generated        | resume_final.pdf
Module 4: Auto-Apply        | ✓ SUCCESS       | 8/8 fields           | apply_timestamp.png

Total Duration: 28.45s
✓ Pipeline completed
```

### Example 2: Dry Run (No Submission)

```bash
DRY_RUN=true python main.py --url "https://jobs.example.com/job/123"
```

Fills all form fields but **does not click submit button**. Perfect for testing.

### Example 3: Resume Generation Only

```bash
python main.py --url "https://jobs.example.com/job/123" --no-apply
```

Generates tailored resume PDF, skips form submission.

### Example 4: Using OpenAI

```bash
LLM_PROVIDER=OPENAI \
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxx \
python main.py --url "https://jobs.example.com/job/123"
```

### Example 5: Debug Mode with Browser Visible

```bash
DEBUG=true HEADLESS=false python main.py --url "https://jobs.example.com/job/123"
```

---

## ⚙️ Module Details

### Module 1: Extraction

**Command:**
```bash
python -m modules.m1_extractor
```

**Key Features:**
- Auto-detects ATS platform (Greenhouse, Lever, unknown)
- Heuristic fallback selectors for unknown platforms
- CAPTCHA detection + screenshot
- Login wall detection → raises `LoginWallError`

**Output:** `ExtractionResult` with `raw_text`, `platform`, `word_count`

---

### Module 2: Tailoring

**Command:**
```bash
python -m modules.m2_tailor
```

**Key Features:**
- LangChain + configurable LLM backend
- Keyword extraction from JD
- Anti-hallucination: validates all skills against `VERIFIED_SKILLS`
- Token guard: auto-summarizes large JDs
- Retry logic on validation failure

**Output:** `TailoredResume` with summary, experience, skills, keywords_matched, keywords_missing

**⚠️ Anti-Hallucination Enforcement:**
- **Verified Skills Only:** `VERIFIED_SKILLS` list in `config/settings.py`
- **No Inventing:** If job requires a skill Yash doesn't have, it's marked in `keywords_missing`
- **Pydantic Validation:** All skills validated; errors trigger LLM retry

**Verified Skills for Yash:**
```python
Python, SQL, C++, Embedded C, Flask, REST APIs, Git, Docker, VS Code,
AWS EC2, AWS S3, AWS Lambda, AWS RDS, AWS DynamoDB, AWS API Gateway, AWS IAM,
Boto3, MySQL, PostgreSQL, Agile/Scrum, SDLC, Cloud Cost Optimization,
CAN Bus protocols, Sensor Fusion, Unit Testing (Unity/C), ASPICE compliance,
Jinja2, Hash-based deduplication, S3 pre-signed URLs
```

---

### Module 3: PDF Generation

**Command:**
```bash
python -m modules.m3_generator
```

**Key Features:**
- Jinja2 HTML template rendering
- Browser-based PDF conversion (Playwright)
- Professional single-page layout
- Fallback to HTML if PDF fails

**Output:** `output/resume_final.pdf`

---

### Module 4: Auto-Apply

**Command:**
```bash
python -m modules.m4_apply
```

**Key Features:**
- Intelligent form field detection
- Smart field mapping (first_name, email, phone, LinkedIn, GitHub, resume)
- Resume PDF file upload
- DRY_RUN mode (fill without submit)
- Screenshot on success & failure

**Output:** `ApplyResult` with status, fields_filled, screenshot_path

---

## 🐛 Failure Points & Mitigation

| Failure Point | Module | Mitigation |
|---|---|---|
| Login wall | M1 | Raises `LoginWallError`; caller skips job |
| CAPTCHA | M1 | Takes screenshot, logs warning, continues |
| Network timeout | M1, M4 | Retried 3x with exponential backoff |
| Unknown ATS | M1 | Falls back to generic selectors |
| JD too large | M2 | Auto-summarized to 3000 words |
| Hallucination | M2 | Pydantic validation fails → LLM retries |
| PDF conversion fails | M3 | Saves HTML fallback |
| Form field not found | M4 | Logs warning, continues with available fields |
| Resume upload fails | M4 | Skips to text fields, continues |

---

## 📊 Output Files

All outputs saved to `output/` directory:

```
output/
├── resume_final.pdf                    ← Generated resume
├── resume_final.html                   ← HTML fallback (if DEBUG=true)
├── result_1234567890.json              ← Pipeline result (all module outputs)
├── extraction_1234567890.json          ← Module 1 extraction
├── apply_1234567890_success.png        ← Module 4 success screenshot
├── apply_1234567890_failed.png         ← Module 4 failure screenshot
├── captcha_1234567890.png              ← CAPTCHA screenshot (if detected)
```

---

## 🔍 Debugging

### Enable Debug Mode

```bash
DEBUG=true python main.py --url "https://..."
```

Produces:
- Verbose console logging
- Intermediate HTML resume saved
- Full exception tracebacks

### See Browser Window

```bash
HEADLESS=false python main.py --url "https://..."
```

### Run Individual Modules

```bash
# Test extraction alone
python -m modules.m1_extractor

# Test tailoring alone
python -m modules.m2_tailor

# Test PDF generation alone
python -m modules.m3_generator

# Test auto-apply alone
python -m modules.m4_apply
```

### Check Configuration

```bash
python -c "from config.settings import *; print(f'LLM: {LLM_PROVIDER}'); print(f'DRY_RUN: {DRY_RUN}')"
```

---

## 🛠️ Troubleshooting

### "ModuleNotFoundError: No module named 'langchain'"

```bash
pip install -r requirements.txt
```

### "ConnectionError: Failed to connect to Ollama at localhost:11434"

Ollama not running. Start it:

```bash
# macOS/Linux
ollama serve

# Or use OpenAI instead
LLM_PROVIDER=OPENAI OPENAI_API_KEY=sk-xxx python main.py --url "https://..."
```

### "Playwright browser not installed"

```bash
playwright install chromium
```

### Form fields not filling

Enable debug mode to see detected fields:

```bash
DEBUG=true python main.py --url "https://..."
```

Check `output/` for screenshots of form state.

### Slow performance

- Set `HEADLESS=true` (default) to disable browser window
- Use `--no-apply` to skip form automation
- Reduce `TIMEOUT_MS` if network is stable

---

## 📝 Customization

### Modify Resume Template

Edit `templates/resume.html` to change layout, styling, sections.

Jinja2 variables available:
- `name`, `email`, `phone`, `linkedin`, `github`
- `summary`, `experience`, `education`, `skills`, `certifications`, `achievements`

### Update Verified Skills

Edit `config/settings.py`:

```python
VERIFIED_SKILLS = [
    "Python",
    "AWS EC2",
    # ... add more
]
```

### Add Custom ATS Platform

Edit `modules/m1_extractor.py`:

```python
ATS_SELECTORS = {
    "my_platform": {
        "job_title": ".my-title-selector",
        "job_body": ".my-body-selector",
        "apply_btn": ".my-apply-btn",
    },
}
```

---

## 🔐 Security

- **No credentials stored:** All secrets via environment variables or `.env`
- **Anti-bot measures:** Hides Playwright detection, realistic UA, locale/timezone
- **Screenshot audit trail:** All form submissions photographed
- **DRY_RUN mode:** Safe testing without actual submissions
- **No hardcoded URLs:** All URLs from command-line arguments

---

## 📄 License & Usage

This is a **production-ready reference implementation** for automated job applications.

**Built for:** Yash Gupta (yash-gupta, 2004yggupta@gmail.com)

---

## 🚀 Next Steps

1. **Configure LLM:** Set `LLM_PROVIDER` in `.env` (default: Ollama)
2. **Test extraction:** `python -m modules.m1_extractor`
3. **Test tailoring:** `python -m modules.m2_tailor`
4. **Generate sample resume:** `python -m modules.m3_generator`
5. **Full automation:** `python main.py --url "https://..."`

---

## 📞 Support

For issues:
1. Enable `DEBUG=true` to see detailed logs
2. Check `output/` directory for screenshots/JSON results
3. Test individual modules
4. Review error messages in console output

---

**Built with:** Python 3.10+, LangChain, Playwright, Pydantic, Jinja2, tenacity, Rich

**Status:** ✅ Production-Ready
