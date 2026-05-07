# Operations Guide

This guide covers routine commands, outputs, and maintenance tasks.

## Generate From A JD File

```powershell
python main.py --jd-file "D:\path\to\job_description.txt"
```

Use this when you want repeatable generation and testing.

## Generate From A URL

```powershell
python main.py --url "https://company.com/jobs/123"
```

If extraction fails because of login, CAPTCHA, or unsupported page structure, save the JD manually and use `--jd-file`.

## Generate From Pasted Text

```powershell
python main.py --jd-text "Paste the job description here"
```

## Ask Profile Questions

```powershell
python main.py --ask "What is my current company?"
python main.py --ask "What are my AWS projects?"
```

Answers are based only on `data/base_resume.json` and `data/user_profile.json`.

## Job Scanning

```powershell
python main.py --scan-jobs
python main.py --scan-jobs --dry-run
python main.py --scan-jobs --scan-company "Company Name"
```

Dry run is recommended before writing to local pipeline files.

## Pipeline

```powershell
python main.py --pipeline
python main.py --process-job 1
python main.py --clean-pipeline
```

`--process-job` generates artifacts for a saved pipeline job and records the result in the tracker.

## Tracker

```powershell
python main.py --tracker
python main.py --tracker --tracker-status Applied
python main.py --update-status 1 --status Applied --notes "Applied manually"
python main.py --tracker-stats
python main.py --verify-tracker
```

## Output Folder

Each run writes a timestamped folder:

```text
output/{company}_{timestamp}/
```

Review:

- `resume_*.pdf`
- `resume_*.txt`
- `resume_*.md`
- `cover_letter_*.txt`
- `result.json`

## Verification

```powershell
venv\Scripts\python.exe -B extra\tests\test_enhancements.py
venv\Scripts\python.exe -B extra\tests\test_production_smoke.py
venv\Scripts\python.exe -B -c "import main; print('imports ok')"
```

## Maintenance

Run periodically:

```powershell
python main.py --verify-tracker
python main.py --clean-pipeline
```

Clean local generated files manually when needed:

- `output/`
- `generated_projects/`
- `data/job_pipeline.json`
- `data/applications.json`
- `data/scan_history.json`

Do not delete `data/base_resume.json` or `data/user_profile.json` unless replacing them intentionally.
