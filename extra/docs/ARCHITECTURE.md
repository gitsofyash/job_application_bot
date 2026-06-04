# Architecture

## Runtime Flow

```text
CLI
 -> job_application_bot.cli
 -> main.main compatibility entrypoint
 -> orchestrate_application
 -> extraction
 -> resume tailoring
 -> optional gap project
 -> resume generation
 -> ATS scoring and improvement
 -> cover letter generation
 -> tracker and pipeline updates
```

## Major Components

- `config/settings.py`: environment-backed settings and project paths.
- `modules/m1_extractor.py`: browser-based JD extraction and page cleanup.
- `modules/m2_tailor.py`: deterministic and optional LLM resume tailoring.
- `modules/m2_5_gap_filler.py`: independent-learning project generation for large gaps.
- `modules/m3_generator.py`: resume merge, one-page rendering, PDF/HTML/Markdown/text output.
- `modules/m5_coverletter.py`: deterministic and optional LLM cover letter generation.
- `modules/m10_job_scanner.py`: configured job source scanning.
- `modules/m11_application_tracker.py`: local application tracking.
- `utils/ats_scorer.py`: ATS keyword and structure scoring.
- `utils/console.py`: safe console wrapper for readable Windows output.
- `utils/url_parser.py`: company-name parsing, filename helpers, and text encoding cleanup.

## Production Boundary

The package `job_application_bot/` is the production-facing application layer.
The current `modules/` directory remains the legacy domain implementation layer.
The next refactor should move orchestration code out of `main.py` without changing
the module behavior.

Current stable package facades:

- `job_application_bot.cli`: package and console-script entrypoint.
- `job_application_bot.orchestrator`: workflow facade for the legacy orchestrator.
- `job_application_bot.profile_qa`: profile Q&A facade.
