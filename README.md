# Job Application Automation Bot

Production-oriented job application assistant for extracting job descriptions, tailoring resumes, generating ATS-friendly one-page resumes, creating cover letters, scanning job sources, and tracking applications.

## What It Does

- Extracts job descriptions from job URLs with Playwright.
- Cleans noisy career pages by removing nav, footer, cookie, and similar-job text.
- Tailors a resume from `data/base_resume.json` and `data/user_profile.json`.
- Generates PDF, HTML, Markdown, and ATS text resume artifacts.
- Scores resumes against the JD and enforces a configurable ATS minimum.
- Improves ATS coverage truthfully using verified skills and supported soft-skill labels.
- Generates cover letters.
- Scans configured job sources into a local job pipeline.
- Tracks generated applications and statuses.
- Answers questions about your saved resume/profile.

## Quick Start

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
Copy-Item .env.example .env
```

Add your API keys to `.env` if you want LLM-backed tailoring or cover letters.

## Main Commands

Generate resume and cover letter from a live job URL:

```powershell
python main.py --url "https://jobs.example.com/job/123"
```

Generate from a saved job description:

```powershell
python main.py --jd-file "D:\path\to\job_description.txt"
```

Generate from pasted JD text:

```powershell
python main.py --jd-text "Paste the job description here"
```

Ask about your resume/profile:

```powershell
python main.py --ask "What are my AWS projects?"
```

Scan configured job sources:

```powershell
python main.py --scan-jobs
```

Preview scan without updating local data:

```powershell
python main.py --scan-jobs --dry-run
```

Show pipeline jobs:

```powershell
python main.py --pipeline
```

Process a saved pipeline job:

```powershell
python main.py --process-job 1
```

Show application tracker:

```powershell
python main.py --tracker
```

Update application status:

```powershell
python main.py --update-status 1 --status Applied --notes "Applied manually"
```

Show tracker stats and verify artifact links:

```powershell
python main.py --tracker-stats
python main.py --verify-tracker
```

## Output

Each job run creates a timestamped folder under `output/`:

```text
output/{company}_{timestamp}/
  jd_{company}.txt
  resume_{company}.pdf
  resume_{company}.html
  resume_{company}.md
  resume_{company}.txt
  cover_letter_{company}.txt
  result.json
```

The resume template renders LinkedIn and GitHub as clickable links while showing compact labels such as:

```text
linkedin.com/in/yash-gupta2601
github.com/gitsofyash
```

## ATS Policy

Configured in `.env` or `config/settings.py`:

```env
ATS_MIN_SCORE=90
ATS_TARGET_SCORE=97
ATS_MAX_IMPROVEMENT_PASSES=5
```

The pipeline treats `ATS_MIN_SCORE` as the minimum acceptable score and keeps improving toward `ATS_TARGET_SCORE` when truthful resume/profile evidence supports it.

## Modules

| Module | File | Purpose |
|---|---|---|
| 1 | `modules/m1_extractor.py` | Extract and clean job descriptions from URLs. |
| 2 | `modules/m2_tailor.py` | Tailor resume content and improve ATS keyword coverage. |
| 2.5 | `modules/m2_5_gap_filler.py` | Create independent learning gap projects when enabled by missing keywords. |
| 3 | `modules/m3_generator.py` | Generate one-page resume PDF, HTML, Markdown, and text mirror. |
| 4 | `modules/m4_apply.py` | Auto-apply form filler. Present but disabled in `main.py`. |
| 5 | `modules/m5_coverletter.py` | Generate tailored cover letters. |
| 6 | `modules/m6_gemini_polish.py` | Optional Gemini polish for resume and cover letter content. |
| 7 | `modules/m7_latex_resume.py` | Generate LaTeX resume output. |
| 8 | `modules/m8_job_search.py` | Search jobs from RSS sources. |
| 9 | `modules/m9_profile_qa.py` | Answer questions from saved resume/profile data. |
| 10 | `modules/m10_job_scanner.py` | Scan configured job sources into the local pipeline. |
| 11 | `modules/m11_application_tracker.py` | Track applications, scores, statuses, and artifact links. |

## Data Files

| File | Purpose |
|---|---|
| `data/base_resume.json` | Source resume content. |
| `data/user_profile.json` | Personal profile and application field mappings. |
| `config/job_sources.json` | Optional configured company/API sources for scanning. |
| `data/job_pipeline.json` | Local generated job queue, ignored by git. |
| `data/applications.json` | Local application tracker, ignored by git. |
| `data/scan_history.json` | Local scan history/dedupe memory, ignored by git. |

## Configuration

Use `.env.example` as the template. Supported main tailoring providers:

- `COHERE`
- `OLLAMA`
- `OPENAI`
- `ANTHROPIC`

Gemini is used only by the optional polish module through:

```env
ENABLE_GEMINI_POLISH=true
GOOGLE_API_KEY=...
```

## Verification

Run the lightweight checks:

```powershell
venv\Scripts\python.exe -B extra\tests\test_enhancements.py
venv\Scripts\python.exe -B extra\tests\test_production_smoke.py
venv\Scripts\python.exe -B -c "import main; print('imports ok')"
```

`PYTHONDONTWRITEBYTECODE=1` is set by default to avoid creating project `__pycache__` files.

## Production Notes

- Keep `.env` private.
- Review generated gap projects before sending resumes.
- Use `--jd-file` for repeat runs after a successful extraction.
- Use `--verify-tracker` periodically to find broken artifact links.
- Auto-apply is intentionally disabled until you explicitly choose to enable it.
