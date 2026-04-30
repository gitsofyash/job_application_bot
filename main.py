#!/usr/bin/env python3
"""
JOB APPLICATION AUTOMATION BOT — MAIN ORCHESTRATOR

End-to-end automation for job applications:
  Module 1: Extract job description from posting
  Module 2: Tailor resume to JD using LLM
  Module 3: Generate tailored resume PDF (company-specific)
  Module 4: COMMENTED OUT - Auto-fill and submit application form
  Module 5: Generate ATS-friendly cover letter (company-specific)

ENHANCEMENTS (v2.0):
  - Company name extraction from URLs
  - 1-page strict resume enforcement
  - Character encoding fixes
  - Company-based file naming (no overwrites)

Usage:
    python main.py --url "https://jobs.example.com/job/123" [--dry-run]

Environment Variables:
    DEBUG=true            Verbose logging
    LLM_PROVIDER=OLLAMA   LLM backend (OLLAMA, OPENAI, ANTHROPIC)
    HEADLESS=false        Show browser window
"""

import asyncio
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from rich.markup import escape
from rich.console import Console
from rich.table import Table
from rich.traceback import install

from config.settings import (
    PROJECT_ROOT,
    OUTPUT_DIR,
    DRY_RUN,
    DEBUG,
    BASE_RESUME_PATH,
    COVER_LETTER_USE_LLM,
)

from modules.m1_extractor import (
    extract_job_description,
    ExtractionResult,
    LoginWallError,
    PlatformDetectionError,
)
from modules.m2_tailor import (
    tailor_resume,
    TailoredResume,
    build_rule_based_tailored_resume,
    improve_tailored_resume_for_ats,
)
from modules.m3_generator import generate_resume_pdf
from modules.m5_coverletter import (
    generate_cover_letter,
    save_cover_letter,
    build_rule_based_cover_letter,
    is_local_ollama_available,
)
from utils.ats_scorer import ATSScorer
from utils.url_parser import extract_company_name, fix_encoding_issues
# COMMENTED OUT: Auto-apply feature
# from modules.m4_apply import apply_to_job, ApplyResult

# Configure rich error display
install()

console = Console()

# ═══════════════════════════════════════════════════════════════
# ORCHESTRATION LOGIC
# ═══════════════════════════════════════════════════════════════


@dataclass
class PipelineResult:
    """Complete pipeline execution result"""
    job_url: str
    extraction: Optional[ExtractionResult] = None
    tailoring: Optional[TailoredResume] = None
    resume_path: Optional[str] = None
    cover_letter_path: Optional[str] = None
    ats_score: Optional[float] = None
    # application: Optional[ApplyResult] = None  # COMMENTED OUT
    error: Optional[str] = None
    duration_seconds: float = 0.0


async def orchestrate_application(
    job_url: str,
    skip_apply: bool = False,
    dry_run: Optional[bool] = None,
) -> PipelineResult:
    """
    Orchestrate complete job application workflow.
    
    Pipeline:
      1. MODULE 1: Extract job description
      2. MODULE 2: Tailor resume to JD
      3. MODULE 3: Generate resume PDF
      4. MODULE 4: Auto-apply (DISABLED)
      5. MODULE 5: Generate cover letter
    
    Each module's success/failure is tracked and logged.
    
    ⚠️ FAILURE HANDLING:
      - Module 1 fails → stops pipeline, returns error
      - Module 2 fails → continues with base resume
      - Module 3 fails → continues without PDF
      - Module 4 is disabled
      - Module 5 fails → logs error but doesn't block
    
    Args:
        job_url: Job posting URL
        skip_apply: Ignored (auto-apply is disabled)
        dry_run: Ignored (auto-apply is disabled)
        
    Returns:
        PipelineResult with all module outputs
    """
    start_time = asyncio.get_event_loop().time()
    result = PipelineResult(job_url=job_url)
    
    # Extract company name from URL for file naming
    company_name = extract_company_name(job_url)
    console.log(f"[cyan]Extracted company name: {company_name}[/cyan]")
    
    # Load resume data early for use in cover letter generation
    try:
        with open(BASE_RESUME_PATH, "r", encoding="utf-8") as f:
            base_resume_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        base_resume_data = {}
    
    try:
        console.print(
            f"\n[bold cyan]═══════════════════════════════════════════════════════════[/bold cyan]"
        )
        console.print(
            f"[bold cyan]JOB APPLICATION AUTOMATION BOT[/bold cyan]"
        )
        console.print(
            f"[bold cyan]═══════════════════════════════════════════════════════════[/bold cyan]"
        )
        console.print(f"[bold]Job URL:[/bold] {job_url}\n")
        
        # ═══════════════════════════════════════════════════════════════
        # MODULE 1: EXTRACT JOB DESCRIPTION
        # ═══════════════════════════════════════════════════════════════
        
        console.print(
            "[bold cyan]╔════════════════════════════════════════╗[/bold cyan]"
        )
        console.print(
            "[bold cyan]║ MODULE 1: Job Description Extraction  ║[/bold cyan]"
        )
        console.print(
            "[bold cyan]╚════════════════════════════════════════╝[/bold cyan]\n"
        )
        
        m1_start = asyncio.get_event_loop().time()
        
        extraction = await extract_job_description(job_url)
        result.extraction = extraction
        
        m1_duration = asyncio.get_event_loop().time() - m1_start
        
        if not extraction.success:
            console.print(
                f"[red]✗ Module 1 Failed: {extraction.error}[/red]"
            )
            result.error = f"Extraction failed: {extraction.error}"
            return result
        
        console.print(
            f"[green]✓ Module 1 Complete ({m1_duration:.2f}s)[/green]\n"
        )
        console.print(f"[dim]Platform: {extraction.platform}[/dim]")
        console.print(f"[dim]Words: {extraction.word_count}[/dim]")
        console.print(f"[dim]Preview: {extraction.raw_text[:200]}...[/dim]\n")
        
        # ═══════════════════════════════════════════════════════════════
        # MODULE 2: TAILOR RESUME (Optimized for speed)
        # ═══════════════════════════════════════════════════════════════
        
        console.print(
            "[bold cyan]╔════════════════════════════════════════╗[/bold cyan]"
        )
        console.print(
            "[bold cyan]║ MODULE 2: LLM Resume Tailoring        ║[/bold cyan]"
        )
        console.print(
            "[bold cyan]╚════════════════════════════════════════╝[/bold cyan]\n"
        )
        
        m2_start = asyncio.get_event_loop().time()
        
        # OPTIMIZATION: Skip LLM tailoring for very small JDs (< 200 words)
        jd_word_count = len(extraction.raw_text.split()) if extraction.raw_text else 0
        if jd_word_count < 200:
            console.print(f"[yellow]⚠️ JD too small ({jd_word_count} words), skipping LLM tailoring[/yellow]\n")
            result.tailoring = build_rule_based_tailored_resume(extraction.raw_text)
        else:
            try:
                tailored = await tailor_resume(extraction.raw_text)
                result.tailoring = tailored
                
                m2_duration = asyncio.get_event_loop().time() - m2_start
                
                console.print(
                    f"[green]✓ Module 2 Complete ({m2_duration:.2f}s)[/green]\n"
                )
                if tailored.summary:
                    summary_preview = tailored.summary[:150] if len(tailored.summary) > 150 else tailored.summary
                    console.print(f"[dim]Summary: {escape(summary_preview)}...[/dim]")
                
                skills_count = len(tailored.skills) if tailored.skills else 0
                matched_count = len(tailored.keywords_matched) if tailored.keywords_matched else 0
                missing_count = len(tailored.keywords_missing) if tailored.keywords_missing else 0
                console.print(f"[dim]Skills: {skills_count} | Matched: {matched_count} | Gap: {missing_count}[/dim]\n")
            
            except Exception as e:
                console.print(f"[yellow]⚠️ Module 2 Warning: {escape(str(e))}[/yellow]")
                console.print(f"[yellow]Continuing with base resume[/yellow]\n")
                result.tailoring = build_rule_based_tailored_resume(extraction.raw_text)
        
        # ═══════════════════════════════════════════════════════════════
        # MODULE 3: GENERATE RESUME PDF
        # ═══════════════════════════════════════════════════════════════
        
        console.print(
            "[bold cyan]╔════════════════════════════════════════╗[/bold cyan]"
        )
        console.print(
            "[bold cyan]║ MODULE 3: Resume PDF Generation       ║[/bold cyan]"
        )
        console.print(
            "[bold cyan]╚════════════════════════════════════════╝[/bold cyan]\n"
        )
        
        m3_start = asyncio.get_event_loop().time()
        
        try:
            resume_path = await generate_resume_pdf(
                result.tailoring,
                company_name=company_name
            )
            result.resume_path = str(resume_path)
            
            m3_duration = asyncio.get_event_loop().time() - m3_start
            
            console.print(
                f"[green]✓ Module 3 Complete ({m3_duration:.2f}s)[/green]\n"
            )
            console.print(f"[dim]Output: {resume_path}[/dim]")
            console.print(f"[dim]Company: {company_name}[/dim]")

            ats_text_path = Path(resume_path).with_suffix(".txt")
            if ats_text_path.exists():
                scorer = ATSScorer()
                resume_text = ats_text_path.read_text(encoding="utf-8")
                score, ats_report = scorer.score_resume(resume_text, extraction.raw_text, str(ats_text_path))
                result.ats_score = round(score, 2)
                score_color = "green" if result.ats_score >= 90 else "yellow"
                console.print(f"[bold {score_color}]ATS Score: {result.ats_score}/100[/bold {score_color}]")
                if result.ats_score < 90 and ats_report.keywords_missing:
                    console.print(f"[yellow]Missing JD keywords: {', '.join(ats_report.keywords_missing[:8])}[/yellow]")
                    improved_tailoring, added_keywords, skipped_keywords = improve_tailored_resume_for_ats(
                        result.tailoring,
                        ats_report.keywords_missing,
                    )
                    if added_keywords:
                        console.print(
                            f"[cyan]ATS improvement pass: adding truthful keywords: {', '.join(added_keywords[:8])}[/cyan]"
                        )
                        if skipped_keywords:
                            console.print(
                                f"[dim]Skipped unsupported keywords: {', '.join(skipped_keywords[:8])}[/dim]"
                            )
                        result.tailoring = improved_tailoring
                        resume_path = await generate_resume_pdf(
                            result.tailoring,
                            company_name=company_name,
                        )
                        result.resume_path = str(resume_path)
                        ats_text_path = Path(resume_path).with_suffix(".txt")
                        resume_text = ats_text_path.read_text(encoding="utf-8")
                        score, ats_report = scorer.score_resume(resume_text, extraction.raw_text, str(ats_text_path))
                        result.ats_score = round(score, 2)
                        score_color = "green" if result.ats_score >= 90 else "yellow"
                        console.print(f"[bold {score_color}]ATS Score after improvement: {result.ats_score}/100[/bold {score_color}]")
                        if result.ats_score < 90 and ats_report.keywords_missing:
                            console.print(f"[yellow]Still missing: {', '.join(ats_report.keywords_missing[:8])}[/yellow]")
            console.print()
        
        except Exception as e:
            console.print(f"[red]✗ Module 3 Failed: {escape(str(e))}[/red]\n")
            result.resume_path = None
        
        # ═══════════════════════════════════════════════════════════════
        # MODULE 4: AUTO-APPLY (COMMENTED OUT)
        # ═══════════════════════════════════════════════════════════════
        
        # Auto-apply feature has been disabled
        # if skip_apply:
        #     console.print(
        #         "[yellow]⊘ Skipping Module 4 (--no-apply flag)[/yellow]\n"
        #     )
        # 
        # else:
        #     console.print(
        #         "[bold cyan]╔════════════════════════════════════════╗[/bold cyan]"
        #     )
        #     console.print(
        #         "[bold cyan]║ MODULE 4: Auto-Apply ATS Automation   ║[/bold cyan]"
        #     )
        #     console.print(
        #         "[bold cyan]╚════════════════════════════════════════╝[/bold cyan]\n"
        #     )
        #     
        #     m4_start = asyncio.get_event_loop().time()
        #     
        #     try:
        #         application = await apply_to_job(
        #             job_url,
        #             resume_path=result.resume_path,
        #         )
        #         result.application = application
        #         
        #         m4_duration = asyncio.get_event_loop().time() - m4_start
        #         
        #         if application.success:
        #             console.print(
        #                 f"[green]✓ Module 4 Complete ({m4_duration:.2f}s)[/green]\n"
        #             )
        #             console.print(
        #                 f"[green]✓ Application Submitted Successfully![/green]"
        #             )
        #         else:
        #             console.print(
        #                 f"[yellow]⚠️ Module 4 Complete ({m4_duration:.2f}s)[/yellow]\n"
        #             )
        #             console.print(
        #                 f"[yellow]⚠️ Application status: {application.status}[/yellow]"
        #             )
        #         
        #         if application.screenshot_path:
        #             console.print(
        #                 f"[dim]Screenshot: {application.screenshot_path}[/dim]"
        #             )
        #         console.print()
        #     
        #     except Exception as e:
        #         console.print(f"[red]✗ Module 4 Failed: {e}[/red]\n")
        #         result.application = None
        
        # ═══════════════════════════════════════════════════════════════
        # MODULE 5: GENERATE COVER LETTER
        # ═══════════════════════════════════════════════════════════════
        
        console.print(
            "[bold cyan]╔════════════════════════════════════════╗[/bold cyan]"
        )
        console.print(
            "[bold cyan]║ MODULE 5: Generate Cover Letter       ║[/bold cyan]"
        )
        console.print(
            "[bold cyan]╚════════════════════════════════════════╝[/bold cyan]\n"
        )
        
        m5_start = asyncio.get_event_loop().time()
        
        try:
            try:
                if not COVER_LETTER_USE_LLM:
                    raise RuntimeError("fast cover-letter mode is enabled")
                if not is_local_ollama_available():
                    raise RuntimeError("Ollama is not running at localhost:11434")
                cover_letter = await generate_cover_letter(
                    extraction.raw_text,
                    resume_data=base_resume_data,
                )
            except Exception as llm_error:
                console.print(
                    f"[yellow]LLM cover letter unavailable, using rule-based fallback: {escape(str(llm_error))}[/yellow]"
                )
                cover_letter = build_rule_based_cover_letter(
                    extraction.raw_text,
                    resume_data=base_resume_data,
                )
            
            # Save cover letter with company-based naming
            cover_letter_path = await save_cover_letter(
                cover_letter,
                company_name=company_name
            )
            result.cover_letter_path = str(cover_letter_path)
            
            m5_duration = asyncio.get_event_loop().time() - m5_start
            
            console.print(
                f"[green]✓ Module 5 Complete ({m5_duration:.2f}s)[/green]\n"
            )
            console.print(f"[dim]Output: {cover_letter_path}[/dim]")
            console.print(f"[dim]Company: {company_name}[/dim]\n")
        
        except Exception as e:
            console.print(f"[yellow]⚠️ Module 5 Warning: {escape(str(e))}[/yellow]\n")
            result.cover_letter_path = None
        
        # ═══════════════════════════════════════════════════════════════
        # SUMMARY
        # ═══════════════════════════════════════════════════════════════
        
        duration = asyncio.get_event_loop().time() - start_time
        result.duration_seconds = duration
        
        print_pipeline_summary(result)
        
        return result
    
    except KeyboardInterrupt:
        console.print("\n[red]✗ Interrupted by user[/red]")
        result.error = "Interrupted by user"
        return result
    
    except Exception as e:
        console.print(f"\n[red]✗ Unexpected error: {escape(str(e))}[/red]")
        if DEBUG:
            import traceback
            traceback.print_exc()
        result.error = str(e)
        return result


# ═══════════════════════════════════════════════════════════════
# SUMMARY & REPORTING
# ═══════════════════════════════════════════════════════════════


def print_pipeline_summary(result: PipelineResult) -> None:
    """Print formatted summary table of all modules"""
    
    console.print(
        "\n[bold cyan]═══════════════════════════════════════════════════════════[/bold cyan]"
    )
    console.print("[bold cyan]PIPELINE EXECUTION SUMMARY[/bold cyan]")
    console.print(
        "[bold cyan]═══════════════════════════════════════════════════════════[/bold cyan]\n"
    )
    
    table = Table(title="Module Status", show_header=True, header_style="bold cyan")
    table.add_column("Module", width=30)
    table.add_column("Status", width=20)
    table.add_column("Details", width=40)
    table.add_column("Artifact", width=30)
    
    # Module 1
    if result.extraction:
        m1_status = "[green]✓ SUCCESS[/green]" if result.extraction.success else "[red]✗ FAILED[/red]"
        m1_details = f"{result.extraction.word_count} words"
        m1_artifact = result.extraction.platform
    else:
        m1_status = "[yellow]⊘ SKIPPED[/yellow]"
        m1_details = ""
        m1_artifact = ""
    
    table.add_row("Module 1: Extraction", m1_status, m1_details, m1_artifact)
    
    # Module 2
    if result.tailoring:
        m2_status = "[green]✓ SUCCESS[/green]"
        skills_count = len(result.tailoring.skills) if result.tailoring.skills else 0
        matched_count = len(result.tailoring.keywords_matched) if result.tailoring.keywords_matched else 0
        m2_details = f"{skills_count} skills, {matched_count} matched"
        missing_count = len(result.tailoring.keywords_missing) if result.tailoring.keywords_missing else 0
        m2_artifact = f"Gap: {missing_count} keywords"
    elif result.extraction and result.extraction.success:
        m2_status = "[yellow]⚠️ SKIPPED[/yellow]"
        m2_details = "Using base resume"
        m2_artifact = ""
    else:
        m2_status = "[red]✗ FAILED[/red]"
        m2_details = "No JD extracted"
        m2_artifact = ""
    
    table.add_row("Module 2: Tailoring", m2_status, m2_details, m2_artifact)
    
    # Module 3
    if result.resume_path:
        m3_status = "[green]✓ SUCCESS[/green]"
        score_suffix = f", ATS {result.ats_score}/100" if result.ats_score is not None else ""
        m3_details = f"PDF generated{score_suffix}"
        m3_artifact = Path(result.resume_path).name
    else:
        m3_status = "[yellow]⚠️ SKIPPED[/yellow]"
        m3_details = "No PDF output"
        m3_artifact = ""
    
    table.add_row("Module 3: PDF Generation", m3_status, m3_details, m3_artifact)
    
    # Module 4 - COMMENTED OUT
    # if result.application:
    #     app_status_map = {
    #         "success": "[green]✓ SUCCESS[/green]",
    #         "dry_run_completed": "[cyan]◆ DRY-RUN[/cyan]",
    #         "failed": "[red]✗ FAILED[/red]",
    #         "partial_submission": "[yellow]⚠️ PARTIAL[/yellow]",
    #     }
    #     m4_status = app_status_map.get(result.application.status, "[gray]?[/gray]")
    #     m4_details = f"{result.application.fields_filled}/{result.application.total_fields} fields"
    #     m4_artifact = Path(result.application.screenshot_path).name if result.application.screenshot_path else ""
    # else:
    #     m4_status = "[yellow]⊘ SKIPPED[/yellow]"
    #     m4_details = ""
    #     m4_artifact = ""
    # 
    # table.add_row("Module 4: Auto-Apply", m4_status, m4_details, m4_artifact)
    
    # Module 5
    if result.cover_letter_path:
        m5_status = "[green]✓ SUCCESS[/green]"
        m5_details = "Cover letter generated"
        m5_artifact = Path(result.cover_letter_path).name
    else:
        m5_status = "[yellow]⚠️ SKIPPED[/yellow]"
        m5_details = "No cover letter"
        m5_artifact = ""
    
    table.add_row("Module 5: Cover Letter", m5_status, m5_details, m5_artifact)
    
    # Overall status
    console.print(f"\n[bold]Total Duration:[/bold] {result.duration_seconds:.2f}s")
    
    if result.error:
        console.print(f"[red]Error: {result.error}[/red]")
    else:
        console.print(f"[green]✓ Pipeline completed[/green]")
    
    # Save result to JSON
    result_file = OUTPUT_DIR / f"result_{int(asyncio.get_event_loop().time())}.json"
    
    result_dict = {
        "job_url": result.job_url,
        "timestamp": datetime.now().isoformat(),
        "duration_seconds": result.duration_seconds,
        "extraction": result.extraction.model_dump() if result.extraction else None,
        "tailoring": result.tailoring.model_dump() if result.tailoring else None,
        "resume_path": result.resume_path,
        "cover_letter_path": result.cover_letter_path,
        "ats_score": result.ats_score,
        # "application": result.application.model_dump() if result.application else None,  # COMMENTED OUT
        "error": result.error,
    }
    
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result_dict, f, indent=2)
    
    console.print(f"\n[dim]Result saved to: {result_file}[/dim]")


# ═══════════════════════════════════════════════════════════════
# CLI ARGUMENT PARSING
# ═══════════════════════════════════════════════════════════════


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description="Job Application Automation Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate ATS-friendly resume and cover letter:
  python main.py --url "https://jobs.example.com/job/123"
  
  # Use OpenAI instead of Ollama:
  LLM_PROVIDER=OPENAI OPENAI_API_KEY=sk-xxx python main.py --url "..."
        """,
    )
    
    parser.add_argument(
        "--url",
        required=True,
        help="Job posting URL to extract JD and generate resume/cover letter",
        type=str,
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    
    return parser.parse_args()


# ═══════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════


async def main():
    """Main entry point"""
    args = parse_args()
    
    # Run orchestration
    result = await orchestrate_application(
        job_url=args.url,
        skip_apply=False,  # Auto-apply is disabled, always skip
        dry_run=None,
    )
    
    # Exit with appropriate code
    if result.error:
        sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
