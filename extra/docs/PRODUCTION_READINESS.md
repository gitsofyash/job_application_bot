# Production Readiness Plan

This project is a working CLI application today. To make it production grade,
the goal is to preserve the existing behavior while improving boundaries,
operability, safety, and testability.

## Current State

- `main.py` is the legacy entrypoint and still owns most orchestration.
- `python -m job_application_bot ...` is now available as a package entrypoint.
- `pyproject.toml` defines install metadata and the `job-application-bot` console command.
- Runtime state is local JSON under `data/` and generated files under `output/`.
- `data/base_resume.json` and `data/user_profile.json` are source-of-truth profile inputs.
- `data/applications.json`, `data/job_pipeline.json`, and `data/scan_history.json` are runtime state and should not be committed with real personal data.

## Production Priorities

1. Package boundary
   - Keep `job_application_bot/` as the installable application package.
   - Gradually move CLI code from `main.py` into `job_application_bot/cli.py`.
   - Move workflow orchestration into `job_application_bot/orchestrator.py`.

2. Runtime state boundary
   - Keep private state out of commits.
   - Add sample files for shareable structure, such as `data/applications.example.json`.
   - Consider `JOB_BOT_DATA_DIR` for deployments where state should live outside the repo.

3. Configuration
   - Keep secrets only in `.env` or environment variables.
   - Validate configuration at startup before long-running workflows.
   - Fail fast for missing browser dependencies when URL extraction is requested.

4. Testing
   - Keep deterministic smoke tests for import, URL parsing, JD quality, resume rendering, and encoding cleanup.
   - Add focused unit tests for each module before larger refactors.
   - Add an end-to-end test using `--jd-text` so CI does not depend on external job sites.

5. Observability
   - Keep console output sanitized through `utils.console.SafeConsole`.
   - Add structured logs for pipeline runs once runtime state is moved out of source-controlled files.
   - Keep `result.json` per run for reproducibility and auditability.

6. Safety
   - Auto-apply should remain disabled until form filling has strict dry-run review and confirmation.
   - Resume tailoring must keep anti-hallucination constraints and expose unsupported missing keywords.
   - Generated artifacts should always be reviewed before sending.

## Target Layout

```text
job_application_bot/
  cli.py
  orchestrator.py
  metadata.py
  runtime.py
  extraction.py
  resume_tailoring.py
  resume_generation.py
  cover_letters.py
  job_scanner.py
  tracker.py
config/
data/
modules/        # legacy modules while migration is in progress
templates/
utils/
tests/
```

## Migration Rule

Do not rewrite large modules just to rename them. Move one boundary at a time,
keep `main.py` as a compatibility wrapper, and run smoke tests after every move.
