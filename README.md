# Job Application Automation Bot

An end-to-end job application assistant that extracts job descriptions, tailors a resume, generates ATS-friendly one-page resume artifacts, creates cover letters, scans job sources, and tracks applications locally.

The project is designed for software engineering roles such as Software Engineer, SDE, Backend Engineer, Cloud Engineer, Platform Engineer, AI Engineer, and related product/MNC roles.

## Features

- Extract job descriptions from live job URLs using Playwright.
- Clean noisy job pages by removing navigation, cookies, footers, and related-job text.
- Tailor resume content from `data/base_resume.json` and `data/user_profile.json`.
- Generate PDF, HTML, Markdown, and ATS text resume outputs.
- Score generated resumes against the JD and improve keyword coverage truthfully.
- Generate cover letters from the JD and saved resume/profile data.
- Scan configured job sources into a local pipeline.
- Track applications, statuses, scores, notes, and generated artifacts.
- Answer questions from the saved resume/profile data.

## Quick Start

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
Copy-Item .env.example .env
```

Edit `.env` and add your API key if you want LLM-backed tailoring or cover letters:

```env
LLM_PROVIDER=COHERE
COHERE_API_KEY=your_key_here
```

The deterministic tailoring path works without LLM rewriting when `RESUME_TAILOR_USE_LLM=false`.

## Personalization

Before using this for another person, update:

- `data/base_resume.json`: resume source of truth, experience, projects, skills, education, achievements, certifications.
- `data/user_profile.json`: name, contact details, current role/company, target roles, preferences, application form mappings.
- `.env`: private API keys and runtime settings.

Never share your own `.env`, `output/`, `data/applications.json`, `data/job_pipeline.json`, or `data/scan_history.json` with someone else.

## Main Commands

Generate resume and cover letter from a live job URL:

```powershell
python main.py --url "https://jobs.example.com/job/123"
```

Generate from a saved JD file:

```powershell
python main.py --jd-file "D:\path\to\job_description.txt"
```

Generate from pasted JD text:

```powershell
python main.py --jd-text "Paste the job description here"
```

Ask about the saved profile:

```powershell
python main.py --ask "What are my AWS projects?"
```

Scan configured job sources:

```powershell
python main.py --scan-jobs
```

Preview a scan without writing data:

```powershell
python main.py --scan-jobs --dry-run
```

Show and process pipeline jobs:

```powershell
python main.py --pipeline
python main.py --process-job 1
```

Track applications:

```powershell
python main.py --tracker
python main.py --update-status 1 --status Applied --notes "Applied manually"
python main.py --tracker-stats
python main.py --verify-tracker
```

Clean low-quality pipeline rows:

```powershell
python main.py --clean-pipeline
```

## Output

Each run creates a timestamped folder under `output/`:

```text
output/{company}_{timestamp}/
  jd_{company}.txt
  resume_{company}.pdf
  resume_{company}.html
  resume_{company}.md
  resume_{company}.txt
  cover_letter_{company}.txt
  cover_letter_{company}.html
  result.json
```

## Resume Policy

The pipeline is tuned to improve ATS coverage without inventing experience.

- Verified skills come from the saved resume/profile and configured verified skill list.
- Seniority terms are filtered from generated summaries and keyword lists.
- Gap projects only run when the JD is very different from the saved resume.
- Gap projects are marked as independent learning and should be reviewed before use.
- Missing unsupported JD keywords remain visible rather than being silently erased.

## ATS Settings

Configured in `.env` or `config/settings.py`:

```env
ATS_MIN_SCORE=90
ATS_TARGET_SCORE=97
ATS_MAX_IMPROVEMENT_PASSES=5
```

The pipeline treats `ATS_MIN_SCORE` as the minimum acceptable score and improves toward `ATS_TARGET_SCORE` when truthful evidence supports it.

## LLM Providers

Supported main providers:

- `COHERE`
- `OLLAMA`
- `OPENAI`
- `ANTHROPIC`

Optional Gemini polish:

```env
ENABLE_GEMINI_POLISH=true
GOOGLE_API_KEY=your_key_here
```

## Important Files

| File | Purpose |
|---|---|
| `main.py` | CLI entrypoint and workflow orchestration. |
| `data/base_resume.json` | Resume source of truth. |
| `data/user_profile.json` | Personal profile and form mappings. |
| `config/settings.py` | Runtime configuration and defaults. |
| `config/job_sources.json` | Optional job source configuration. |
| `templates/resume_ats.html` | Resume HTML/PDF template. |
| `.env.example` | Safe environment variable template. |

## Modules

| Module | File | Purpose |
|---|---|---|
| 1 | `modules/m1_extractor.py` | Extract and clean job descriptions from URLs. |
| 2 | `modules/m2_tailor.py` | Tailor resume content and improve ATS keyword coverage. |
| 2.5 | `modules/m2_5_gap_filler.py` | Generate independent learning projects for large JD/profile gaps. |
| 3 | `modules/m3_generator.py` | Generate one-page resume PDF, HTML, Markdown, and text. |
| 4 | `modules/m4_apply.py` | Auto-apply form filler, present but disabled in `main.py`. |
| 5 | `modules/m5_coverletter.py` | Generate cover letters. |
| 6 | `modules/m6_gemini_polish.py` | Optional Gemini polish layer. |
| 8 | `modules/m8_job_search.py` | Search jobs from RSS/API sources. |
| 9 | `modules/m9_profile_qa.py` | Answer questions from saved profile data. |
| 10 | `modules/m10_job_scanner.py` | Scan configured job sources into local pipeline. |
| 11 | `modules/m11_application_tracker.py` | Track applications, scores, statuses, and artifacts. |

## Verification

Run these checks before sharing or after edits:

```powershell
venv\Scripts\python.exe -B extra\tests\test_enhancements.py
venv\Scripts\python.exe -B extra\tests\test_production_smoke.py
venv\Scripts\python.exe -B -c "import main; print('imports ok')"
```

## More Docs

- `extra/docs/SETUP_AND_SHARING.md`: how to set up, share, and personalize the project.
- `extra/docs/PROFILE_CUSTOMIZATION.md`: how to edit resume/profile JSON safely.
- `extra/docs/OPERATIONS.md`: common commands, troubleshooting, and maintenance.

## Safety Notes

- Keep `.env` private.
- Review generated resume and cover letter before sending.
- Use `--jd-file` for repeatable runs after extraction succeeds.
- Use `--verify-tracker` periodically to find broken artifact links.
- Auto-apply is intentionally disabled in the main workflow.
