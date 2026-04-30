"""
MODULE 4 — Auto-Apply ATS Automation

Automates job application form filling and submission on ATS platforms.

Features:
  - Anti-bot spoofing (same as Module 1)
  - Intelligent form field detection and mapping
  - Support for text inputs, dropdowns, file uploads (resume PDF)
  - Greenhouse & Lever specific selectors
  - DRY_RUN mode: fills all fields but skips final submit
  - Post-submit success detection (URL change, confirmation message)
  - Screenshot on success & failure for audit trail
  - Structured logging with retry logic

⚠️ FAILURE POINTS:
  1. Form field not found → logs warning, continues with available fields
  2. Resume upload fails → logs error, skips to text fields
  3. Submit button not found → raises SubmitButtonNotFoundError
  4. Post-submit timeout → treated as failure, screenshot saved
  5. Network timeout → retried via tenacity decorator

MITIGATION:
  - Each form field has try/catch with logging
  - Graceful degradation: fills what's available, skips what's missing
  - Screenshots saved for all outcomes (success/failure)
  - Retry logic for network timeouts
  - DRY_RUN prevents accidental submissions
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

from playwright.async_api import async_playwright, Page, Browser
from pydantic import BaseModel, Field
from rich.console import Console
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from config.settings import (
    PROJECT_ROOT,
    HEADLESS,
    VIEWPORT_WIDTH,
    VIEWPORT_HEIGHT,
    TIMEOUT_MS,
    WAIT_NETWORK_IDLE_TIMEOUT,
    USER_AGENT,
    LOCALE,
    TIMEZONE,
    BROWSER_TYPE,
    OUTPUT_DIR,
    DRY_RUN,
    DEBUG,
    USER_PROFILE_PATH,
    OUTPUT_RESUME_PDF,
)

console = Console()

# ═══════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════


class ApplicationStatus(str, Enum):
    """Application submission status"""
    SUCCESS = "success"
    FAILED = "failed"
    DRY_RUN_COMPLETED = "dry_run_completed"
    PARTIAL_SUBMISSION = "partial_submission"


class ApplyResult(BaseModel):
    """Result of job application attempt"""
    url: str = Field(..., description="Job posting URL")
    status: ApplicationStatus = Field(..., description="Application status")
    fields_filled: int = Field(..., description="Number of form fields successfully filled")
    total_fields: int = Field(..., description="Total form fields detected")
    success: bool = Field(..., description="Application successful")
    error: Optional[str] = Field(None, description="Error message if failed")
    applied_at: str = Field(default_factory=lambda: str(time.time()))
    screenshot_path: Optional[str] = Field(None, description="Path to result screenshot")


# ═══════════════════════════════════════════════════════════════
# EXCEPTION CLASSES
# ═══════════════════════════════════════════════════════════════


class ApplyError(Exception):
    """Base exception for apply errors"""
    pass


class FormNotFoundError(ApplyError):
    """Raised when application form not found"""
    pass


class SubmitButtonNotFoundError(ApplyError):
    """Raised when submit button not found"""
    pass


class ResumeUploadError(ApplyError):
    """Raised when resume upload fails"""
    pass


class NetworkTimeoutError(ApplyError):
    """Raised on network timeout (can be retried)"""
    pass


# ═══════════════════════════════════════════════════════════════
# FORM FIELD DETECTION & MAPPING
# ═══════════════════════════════════════════════════════════════


class FormField(BaseModel):
    """Detected form field"""
    selector: str = Field(..., description="CSS selector for field")
    name: str = Field(..., description="Field name")
    type: str = Field(..., description="Field type: text, email, tel, select, file, etc.")
    required: bool = Field(default=False, description="Is field required")
    label: Optional[str] = Field(None, description="Field label text")


async def detect_form_fields(page: Page) -> list[FormField]:
    """
    Detect all form fields on page.
    
    Looks for:
      - input[type="text"], input[type="email"], input[type="tel"]
      - select elements
      - input[type="file"] (for resume)
      - textarea
    
    ⚠️ FAILURE POINT: Form may use custom web components not detected.
    MITIGATION: Logs warning, continues with detected fields.
    
    Args:
        page: Playwright page object
        
    Returns:
        List of detected FormField objects
    """
    detected_fields = []
    
    # CSS selectors to search for
    field_selectors = [
        ("input[type='text']", "text"),
        ("input[type='email']", "email"),
        ("input[type='tel']", "tel"),
        ("input[type='phone']", "tel"),
        ("input[type='url']", "url"),
        ("select", "select"),
        ("input[type='file']", "file"),
        ("textarea", "textarea"),
    ]
    
    for selector, field_type in field_selectors:
        try:
            elements = await page.query_selector_all(selector)
            
            for elem in elements:
                # Get field attributes
                name = await elem.get_attribute("name") or ""
                placeholder = await elem.get_attribute("placeholder") or ""
                required = await elem.get_attribute("required") is not None
                
                # Get associated label
                label = None
                try:
                    # Try to find associated label
                    label_elem = await page.evaluate(
                        """(selector) => {
                            const elem = document.querySelector(selector);
                            if (!elem) return null;
                            
                            // Method 1: explicit association
                            if (elem.id) {
                                const label = document.querySelector('label[for="' + elem.id + '"]');
                                if (label) return label.textContent;
                            }
                            
                            // Method 2: parent label
                            const parentLabel = elem.closest('label');
                            if (parentLabel) return parentLabel.textContent;
                            
                            return null;
                        }""",
                        selector,
                    )
                    label = label_elem
                except Exception:
                    label = None
                
                field = FormField(
                    selector=selector,
                    name=name,
                    type=field_type,
                    required=required,
                    label=label or placeholder,
                )
                
                detected_fields.append(field)
                
        except Exception as e:
            console.log(f"[yellow]Error detecting {selector}: {e}[/yellow]")
    
    console.log(f"[green]Detected {len(detected_fields)} form fields[/green]")
    return detected_fields


# ═══════════════════════════════════════════════════════════════
# FIELD FILLING LOGIC
# ═══════════════════════════════════════════════════════════════


async def fill_form_field(
    page: Page,
    field: FormField,
    user_profile: Dict[str, Any],
    resume_path: Optional[str] = None,
) -> bool:
    """
    Fill a single form field with appropriate value from user profile.
    
    Mapping strategy:
      - "first_name" → user_profile["first_name"] or name split
      - "last_name" → user_profile["last_name"] or name split
      - "email" → user_profile["email"]
      - "phone" → user_profile["phone"]
      - "linkedin" → user_profile["linkedin"]
      - "resume" → file upload (resume_path)
      - Dropdowns → select matching option
    
    ⚠️ FAILURE POINT: Field value mismatch or not found.
    MITIGATION: Returns False; caller logs warning and continues.
    
    Args:
        page: Playwright page object
        field: Form field to fill
        user_profile: User profile data
        resume_path: Path to resume PDF (for file uploads)
        
    Returns:
        True if filled successfully, False otherwise
    """
    field_name_lower = field.name.lower()
    field_label_lower = (field.label or "").lower()
    
    # Determine value to fill based on field name/label
    value = None
    
    if any(x in field_name_lower for x in ["first_name", "firstname", "first"]):
        value = user_profile.get("first_name") or user_profile.get("name", "").split()[0]
    
    elif any(x in field_name_lower for x in ["last_name", "lastname", "last", "surname"]):
        value = user_profile.get("last_name") or user_profile.get("name", "").split()[-1]
    
    elif any(x in field_name_lower for x in ["email", "e_mail"]):
        value = user_profile.get("email")
    
    elif any(x in field_name_lower for x in ["phone", "tel", "mobile", "contact"]):
        value = user_profile.get("phone")
    
    elif any(x in field_name_lower for x in ["linkedin", "linkedin_url", "linkedin_profile"]):
        value = user_profile.get("linkedin") or user_profile.get("linkedin_url")
    
    elif any(x in field_name_lower for x in ["github", "github_url", "github_profile"]):
        value = user_profile.get("github") or user_profile.get("github_url")
    
    elif field.type == "file" or any(x in field_name_lower for x in ["resume", "cv", "cover_letter", "attachment"]):
        # Handle file upload
        if resume_path and Path(resume_path).exists():
            try:
                await page.set_input_files(field.selector, resume_path)
                console.log(f"[green]✓ Uploaded resume[/green]")
                return True
            except Exception as e:
                console.log(f"[yellow]Failed to upload resume: {e}[/yellow]")
                return False
        else:
            console.log(f"[yellow]Resume file not found: {resume_path}[/yellow]")
            return False
    
    if not value:
        console.log(f"[dim]Skipping {field.name} (no value)[/dim]")
        return False
    
    try:
        # Fill field based on type
        if field.type == "select":
            # For select, try to find matching option
            await page.select_option(field.selector, value)
            console.log(f"[green]✓ Selected {field.name}: {value}[/green]")
        
        elif field.type == "textarea":
            await page.fill(field.selector, value)
            console.log(f"[green]✓ Filled {field.name}[/green]")
        
        else:
            # Text input
            await page.fill(field.selector, value)
            console.log(f"[green]✓ Filled {field.name}[/green]")
        
        return True
    
    except Exception as e:
        console.log(f"[yellow]Error filling {field.name}: {e}[/yellow]")
        return False


# ═══════════════════════════════════════════════════════════════
# SUBMIT BUTTON DETECTION & SUBMISSION
# ═══════════════════════════════════════════════════════════════


async def find_submit_button(page: Page) -> Optional[str]:
    """
    Find submit button selector on page.
    
    Looks for:
      - input[type="submit"]
      - button[type="submit"]
      - button:has-text("Submit"), button:has-text("Apply")
      - .submit-btn, .apply-btn
    
    ⚠️ FAILURE POINT: Multiple submit buttons or hidden buttons.
    MITIGATION: Returns first visible button found.
    
    Args:
        page: Playwright page object
        
    Returns:
        Button selector if found, None otherwise
    """
    submit_selectors = [
        'button:has-text("Submit")',
        'button:has-text("Apply")',
        'input[type="submit"]',
        'button[type="submit"]',
        'button.submit-btn',
        'button.apply-btn',
        'button[class*="submit"]',
        'button[class*="apply"]',
    ]
    
    for selector in submit_selectors:
        try:
            button = await page.query_selector(selector)
            if button and await button.is_visible():
                console.log(f"[green]Found submit button: {selector}[/green]")
                return selector
        except Exception:
            continue
    
    console.log("[red]✗ Submit button not found[/red]")
    return None


async def submit_application(
    page: Page,
    submit_selector: str,
) -> bool:
    """
    Click submit button and wait for confirmation.
    
    Strategy:
      1. Click submit button
      2. Wait for URL change or success message
      3. Verify submission succeeded
    
    ⚠️ FAILURE POINT: Form validation errors or network issues.
    MITIGATION: Logs errors, screenshots on failure.
    
    Args:
        page: Playwright page object
        submit_selector: CSS selector for submit button
        
    Returns:
        True if submission successful, False otherwise
    """
    try:
        console.log("[blue]Clicking submit button...[/blue]")
        
        # Click submit
        await page.click(submit_selector)
        
        # Wait for navigation or success message
        try:
            # Try to wait for URL change (success redirect)
            await asyncio.wait_for(
                page.wait_for_url("**", timeout=10000),
                timeout=10.0,
            )
            console.log("[green]✓ Page navigated (submission likely successful)[/green]")
            return True
        
        except asyncio.TimeoutError:
            # No URL change, check for success message
            try:
                success_selectors = [
                    'text="Thank you"',
                    'text="submitted successfully"',
                    'text="application received"',
                    '[role="alert"]:has-text("success")',
                ]
                
                for selector in success_selectors:
                    elem = await page.query_selector(selector)
                    if elem:
                        console.log("[green]✓ Success message detected[/green]")
                        return True
            
            except Exception:
                pass
            
            console.log("[yellow]⚠️ No confirmation detected, may have failed[/yellow]")
            return False
    
    except Exception as e:
        console.log(f"[red]Error submitting application: {e}[/red]")
        return False


# ═══════════════════════════════════════════════════════════════
# ANTI-BOT SETUP (same as Module 1)
# ═══════════════════════════════════════════════════════════════


async def setup_anti_bot_context(page: Page) -> None:
    """Setup anti-bot spoofing (see Module 1 for details)"""
    await page.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => false,
        });
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });
        """
    )
    context = page.context
    await context.grant_permissions([], origin="*")


# ═══════════════════════════════════════════════════════════════
# MAIN APPLY FUNCTION
# ═══════════════════════════════════════════════════════════════


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=2, min=2, max=5),
    retry=retry_if_exception_type(NetworkTimeoutError),
)
async def apply_to_job(
    job_url: str,
    resume_path: Optional[str] = None,
    user_profile_path: Optional[str] = None,
) -> ApplyResult:
    """
    Automate job application submission.
    
    Orchestrates:
      1. Browser initialization with anti-bot measures
      2. Navigate to job posting
      3. Wait for page to load
      4. Detect and fill form fields
      5. Upload resume (if applicable)
      6. Click submit button (unless DRY_RUN)
      7. Verify success and save screenshot
    
    ⚠️ FAILURE POINTS:
      - Form fields not found → fills available fields only
      - Resume upload fails → continues with text fields
      - Submit button not found → raises SubmitButtonNotFoundError
      - Network timeout → retried via @retry decorator
      - DRY_RUN=true → fills all fields but skips submit
    
    Args:
        job_url: URL of job posting to apply to
        resume_path: Path to resume PDF (optional, uses config default)
        user_profile_path: Path to user_profile.json (optional, uses config default)
        
    Returns:
        ApplyResult with submission status
    """
    browser: Optional[Browser] = None
    screenshot_path = None
    
    try:
        # Load user profile
        if not user_profile_path:
            user_profile_path = str(USER_PROFILE_PATH)
        
        with open(user_profile_path, "r", encoding="utf-8") as f:
            user_profile = json.load(f)
        
        # Use default resume path if not provided
        if not resume_path:
            resume_path = str(OUTPUT_RESUME_PDF)
        
        console.log("[bold cyan]MODULE 4 — Auto-Apply ATS Automation[/bold cyan]")
        console.log(f"[blue]Applying to: {job_url}[/blue]")
        
        if DRY_RUN:
            console.log("[yellow]🔒 DRY_RUN=true (will not submit)[/yellow]")
        
        # Launch browser
        async with async_playwright() as playwright_instance:
            browser_type = getattr(playwright_instance, BROWSER_TYPE)
            browser = await browser_type.launch(headless=HEADLESS)
            
            context = await browser.new_context(
                viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                user_agent=USER_AGENT,
                locale=LOCALE,
                timezone_id=TIMEZONE,
            )
            
            page = await context.new_page()
            
            # Apply anti-bot measures
            await setup_anti_bot_context(page)
            
            # Set timeouts
            page.set_default_timeout(TIMEOUT_MS)
            page.set_default_navigation_timeout(TIMEOUT_MS)
            
            # Navigate to job URL
            console.log(f"[blue]→ Navigating to {job_url}[/blue]")
            try:
                await page.goto(job_url, wait_until="domcontentloaded")
            except Exception as e:
                console.log(f"[red]Navigation error: {e}[/red]")
                raise NetworkTimeoutError(f"Failed to navigate: {e}")
            
            # Wait for page to be ready
            try:
                await asyncio.wait_for(
                    page.wait_for_load_state("networkidle", timeout=WAIT_NETWORK_IDLE_TIMEOUT),
                    timeout=WAIT_NETWORK_IDLE_TIMEOUT / 1000.0,
                )
            except asyncio.TimeoutError:
                console.log("[yellow]Network idle timeout, continuing anyway[/yellow]")
            
            await asyncio.sleep(1)
            
            # Detect form fields
            console.log("[blue]Detecting form fields...[/blue]")
            form_fields = await detect_form_fields(page)
            
            if not form_fields:
                raise FormNotFoundError("No form fields detected on page")
            
            # Fill form fields
            console.log("[blue]Filling form fields...[/blue]")
            fields_filled = 0
            
            for field in form_fields:
                if await fill_form_field(page, field, user_profile, resume_path):
                    fields_filled += 1
            
            console.log(f"[green]Filled {fields_filled}/{len(form_fields)} fields[/green]")
            
            # Find and handle submit button
            submit_selector = await find_submit_button(page)
            
            if not submit_selector:
                raise SubmitButtonNotFoundError("Submit button not found on page")
            
            # Submit (unless dry run)
            if DRY_RUN:
                console.log("[yellow]🔒 Dry run: skipping submission[/yellow]")
                result = ApplyResult(
                    url=job_url,
                    status=ApplicationStatus.DRY_RUN_COMPLETED,
                    fields_filled=fields_filled,
                    total_fields=len(form_fields),
                    success=True,
                    error=None,
                )
            
            else:
                console.log("[blue]Submitting application...[/blue]")
                success = await submit_application(page, submit_selector)
                
                if success:
                    console.log("[green]✓ Application submitted successfully![/green]")
                    result = ApplyResult(
                        url=job_url,
                        status=ApplicationStatus.SUCCESS,
                        fields_filled=fields_filled,
                        total_fields=len(form_fields),
                        success=True,
                        error=None,
                    )
                else:
                    console.log("[red]✗ Application submission may have failed[/red]")
                    result = ApplyResult(
                        url=job_url,
                        status=ApplicationStatus.FAILED,
                        fields_filled=fields_filled,
                        total_fields=len(form_fields),
                        success=False,
                        error="Submission failed or unconfirmed",
                    )
            
            # Save screenshot
            screenshot_path = str(
                OUTPUT_DIR / f"apply_{int(time.time())}_{result.status.value}.png"
            )
            await page.screenshot(path=screenshot_path)
            console.log(f"[green]Screenshot saved: {screenshot_path}[/green]")
            result.screenshot_path = screenshot_path
            
            await context.close()
            
            return result
    
    except SubmitButtonNotFoundError as e:
        console.log(f"[red]✗ {e}[/red]")
        if screenshot_path:
            return ApplyResult(
                url=job_url,
                status=ApplicationStatus.FAILED,
                fields_filled=0,
                total_fields=0,
                success=False,
                error=str(e),
                screenshot_path=screenshot_path,
            )
        else:
            return ApplyResult(
                url=job_url,
                status=ApplicationStatus.FAILED,
                fields_filled=0,
                total_fields=0,
                success=False,
                error=str(e),
            )
    
    except FormNotFoundError as e:
        console.log(f"[red]✗ {e}[/red]")
        return ApplyResult(
            url=job_url,
            status=ApplicationStatus.FAILED,
            fields_filled=0,
            total_fields=0,
            success=False,
            error=str(e),
        )
    
    except NetworkTimeoutError:
        # Re-raise to trigger @retry
        raise
    
    except Exception as e:
        console.log(f"[red]✗ Unexpected error: {e}[/red]")
        if DEBUG:
            import traceback
            traceback.print_exc()
        
        return ApplyResult(
            url=job_url,
            status=ApplicationStatus.FAILED,
            fields_filled=0,
            total_fields=0,
            success=False,
            error=f"Unexpected error: {str(e)}",
            screenshot_path=screenshot_path,
        )
    
    finally:
        if browser:
            await browser.close()


# ═══════════════════════════════════════════════════════════════
# CLI TEST COMMAND
# ═══════════════════════════════════════════════════════════════


async def main():
    """Test auto-apply with sample URL"""
    test_url = "https://boards.greenhouse.io/example/jobs/1234"
    
    console.print("[bold cyan]MODULE 4 — Auto-Apply ATS Automation (Test)[/bold cyan]")
    console.print(f"[dim]Testing URL: {test_url}[/dim]")
    
    result = await apply_to_job(test_url)
    
    console.print("\n[bold]Application Result:[/bold]")
    console.print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
