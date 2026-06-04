"""
MODULE 1 — Job Description Extractor

Extracts job descriptions from ATS platforms (Greenhouse, Lever) using Playwright.
Features:
  - Anti-bot spoofing (navigator.webdriver hiding, realistic UA, locale/timezone)
  - ATS-specific selectors for Greenhouse & Lever
  - Heuristic fallback scoring for unknown boards
  - Login wall & CAPTCHA detection
  - Structured output via Pydantic model

⚠️ FAILURE POINTS:
  1. Login wall without credentials → PermissionError (not recoverable)
  2. CAPTCHA detection → logs warning, screenshots, continues with best-effort extraction
  3. Network timeout → retried via tenacity decorator
  4. Unknown platform → falls back to heuristic scoring + generic selectors

MITIGATION:
  - Each failure point has dedicated exception type
  - Screenshots saved for manual review
  - Structured logging with rich console output
  - Retry logic with exponential backoff
"""

import asyncio
import json
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from playwright.async_api import async_playwright, Page, Browser
from utils.console import SafeConsole as Console
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
    DEBUG,
)

console = Console()

# ═══════════════════════════════════════════════════════════════
# ENUMS & MODELS
# ═══════════════════════════════════════════════════════════════


class Platform(str, Enum):
    """Supported ATS platforms"""
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    UNKNOWN = "unknown"


class ExtractionResult(BaseModel):
    """Structured output from job description extraction"""
    url: str = Field(..., description="Original job posting URL")
    raw_text: str = Field(..., description="Extracted job description text")
    platform: Platform = Field(..., description="Detected ATS platform")
    word_count: int = Field(..., description="Word count of extracted text")
    success: bool = Field(..., description="Extraction success status")
    error: Optional[str] = Field(None, description="Error message if failed")
    extracted_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    screenshot_path: Optional[str] = Field(None, description="Path to debug screenshot if CAPTCHA/error")

    class Config:
        use_enum_values = True


# ═══════════════════════════════════════════════════════════════
# EXCEPTION CLASSES
# ═══════════════════════════════════════════════════════════════


class JobExtractionError(Exception):
    """Base exception for extraction errors"""
    pass


class LoginWallError(JobExtractionError):
    """Raised when login is required without credentials"""
    pass


class CaptchaDetectedError(JobExtractionError):
    """Raised when CAPTCHA is detected (non-fatal, continues with best effort)"""
    pass


class NetworkTimeoutError(JobExtractionError):
    """Raised on network timeout (can be retried)"""
    pass


class PlatformDetectionError(JobExtractionError):
    """Raised when platform cannot be determined"""
    pass


# ═══════════════════════════════════════════════════════════════
# PLATFORM DETECTION & SELECTORS
# ═══════════════════════════════════════════════════════════════


def detect_platform(url: str) -> Platform:
    """
    Detect ATS platform from URL.
    
    Args:
        url: Job posting URL
        
    Returns:
        Platform enum value
    """
    domain = urlparse(url).netloc.lower()
    
    if "greenhouse" in domain or "boards.greenhouse.io" in domain:
        return Platform.GREENHOUSE
    elif "lever" in domain or "jobs.lever.co" in domain:
        return Platform.LEVER
    else:
        return Platform.UNKNOWN


def get_selectors(platform: Platform) -> dict:
    """
    Get CSS selectors for job description extraction based on platform.
    
    Args:
        platform: ATS platform enum
        
    Returns:
        Dictionary of selectors for title, body, and buttons
    """
    selectors = {
        Platform.GREENHOUSE: {
            "job_title": '[data-test="job-title"], h1, .posting-title',
            "job_body": '[data-test="job-description"], .posting-content, .content, main',
            "apply_btn": 'a[href*="/applications/new"], button:has-text("Apply"), .apply-btn',
            "login_indicator": "input[type='email'][placeholder*='email'], .login-form, .sign-in",
        },
        Platform.LEVER: {
            "job_title": ".postings-title, h1, .posting__title",
            "job_body": ".show-post-content, .posting-content, .posting__content, main",
            "apply_btn": 'a[class*="postings-btn-apply"], button:has-text("Apply"), .apply-btn',
            "login_indicator": ".auth-required, .login-form, input[type='email']",
        },
        Platform.UNKNOWN: {
            # Heuristic fallback selectors
            "job_title": "h1, h2, .job-title, .title, [role='heading']",
            "job_body": "article, main, .content, .job-content, [role='main']",
            "apply_btn": "button:has-text('Apply'), a:has-text('Apply'), .apply-btn, [type='submit']",
            "login_indicator": ".login, .auth, input[type='email'][placeholder*='email']",
        },
    }
    
    return selectors.get(platform, selectors[Platform.UNKNOWN])


# ═══════════════════════════════════════════════════════════════
# ANTI-BOT SPOOFING
# ═══════════════════════════════════════════════════════════════


async def setup_anti_bot_context(page: Page) -> None:
    """
    Configure page with anti-bot spoofing measures:
      1. Hide navigator.webdriver (blocks Selenium/Playwright detection)
      2. Set realistic user agent
      3. Configure locale and timezone
      4. Disable geolocation
    
    ⚠️ FAILURE POINT: Some sites may have additional detection beyond these measures.
    MITIGATION: Logs warnings and continues — many sites still work despite detection.
    
    Args:
        page: Playwright page object
    """
    # Hide navigator.webdriver flag (critical for anti-detection)
    await page.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => false,
        });
        """
    )
    
    # Spoof Chrome as browser
    await page.add_init_script(
        """
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });
        """
    )
    
    # Disable geolocation permission prompt
    context = page.context
    await context.grant_permissions([])

# ═══════════════════════════════════════════════════════════════
# DETECTION LOGIC
# ═══════════════════════════════════════════════════════════════


async def detect_login_wall(page: Page, platform: Platform) -> bool:
    """
    Detect if page is behind a login wall.
    
    ⚠️ FAILURE POINT: Heuristic-based detection may have false positives/negatives.
    MITIGATION: Returns boolean; caller decides if fatal or not.
    
    Args:
        page: Playwright page object
        platform: ATS platform
        
    Returns:
        True if login wall detected, False otherwise
    """
    selectors = get_selectors(platform)
    login_indicator = selectors.get("login_indicator")
    
    if not login_indicator:
        return False
    
    try:
        element = await page.query_selector(login_indicator)
        if element:
            # Check if job content is actually visible
            job_body_selector = selectors.get("job_body")
            job_body = await page.query_selector(job_body_selector)
            
            if not job_body:
                console.log("[yellow]⚠️ Login wall detected[/yellow]")
                return True
    except Exception as e:
        console.log(f"[yellow]Warning during login detection: {e}[/yellow]")
    
    return False


async def detect_captcha(page: Page) -> bool:
    """
    Detect common CAPTCHA variants (reCAPTCHA, hCaptcha, etc.).
    
    ⚠️ FAILURE POINT: New/custom CAPTCHAs may not be detected.
    MITIGATION: Logs warning + screenshots for manual review. Continues extraction attempt.
    
    Args:
        page: Playwright page object
        
    Returns:
        True if CAPTCHA detected, False otherwise
    """
    captcha_selectors = [
        # reCAPTCHA
        ".g-recaptcha",
        "[data-sitekey]",
        "iframe[src*='recaptcha']",
        "iframe[src*='captcha']",
        # hCaptcha
        ".h-captcha",
        "[data-sitekey*='h-captcha']",
        # Custom
        ".captcha-container",
        "[role='img'][aria-label*='captcha']",
    ]
    
    for selector in captcha_selectors:
        try:
            element = await page.query_selector(selector)
            if element:
                console.log("[red]🚨 CAPTCHA DETECTED[/red]")
                return True
        except Exception:
            pass
    
    return False


# ═══════════════════════════════════════════════════════════════
# TEXT EXTRACTION
# ═══════════════════════════════════════════════════════════════


async def extract_text_content(page: Page, platform: Platform) -> str:
    """
    Extract job description text using platform-specific selectors with fallback.
    
    Strategy:
      1. Try primary selector for platform
      2. Fall back to secondary selectors
      3. As last resort, extract all visible text
    
    ⚠️ FAILURE POINT: Text extraction may include navigation/noise.
    MITIGATION: Extracted text is likely 70-90% relevant; caller can post-process if needed.
    
    Args:
        page: Playwright page object
        platform: ATS platform
        
    Returns:
        Extracted text content
    """
    selectors = get_selectors(platform)
    job_body_selector = selectors.get("job_body")
    
    if not job_body_selector:
        raise PlatformDetectionError(f"No selector for platform: {platform}")
    
    candidate_selectors = [
        job_body_selector,
        "[data-testid*='job']",
        "[class*='job-detail']",
        "[class*='job-description']",
        "[class*='description']",
        "[class*='posting']",
        "article",
        "main",
        ".content",
        "[role='main']",
        "body",
    ]

    best_text = ""
    best_score = -1
    seen_selectors = set()

    for selector in candidate_selectors:
        if not selector or selector in seen_selectors:
            continue
        seen_selectors.add(selector)
        try:
            elements = await page.query_selector_all(selector)
        except Exception:
            continue

        for element in elements[:12]:
            try:
                candidate = await element.inner_text()
            except Exception:
                continue

            candidate = "\n".join(
                line.strip() for line in candidate.split("\n") if line.strip()
            )
            word_count = len(candidate.split())
            if word_count < 20:
                continue

            lower = candidate.lower()
            job_signal_count = sum(
                1
                for term in [
                    "description",
                    "responsibilities",
                    "qualifications",
                    "requirements",
                    "basic qualifications",
                    "preferred qualifications",
                    "minimum qualifications",
                    "what you'll do",
                    "what you will do",
                    "required skills",
                    "preferred skills",
                    "job summary",
                    "tech stack",
                    "software",
                    "engineer",
                    "experience",
                ]
                if term in lower
            )
            nav_penalty = sum(
                1
                for term in [
                    "sign out",
                    "my profile",
                    "account security",
                    "settings",
                    "similar jobs",
                    "privacy policy",
                    "cookie",
                    "terms of use",
                    "job alert",
                    "create alert",
                    "share job",
                ]
                if term in lower
            )
            score = word_count + (job_signal_count * 150) - (nav_penalty * 250)

            if score > best_score:
                best_score = score
                best_text = candidate

    text_content = clean_job_description_text(best_text)
    
    if not text_content or text_content.strip() == "":
        raise PlatformDetectionError("Extracted text is empty")

    if len(text_content.split()) < 80:
        console.log("[yellow]Extracted text is very short; site may need custom selectors or login/session access[/yellow]")
    
    return text_content


def clean_job_description_text(text: str) -> str:
    """Trim common career-site navigation, cookie banners, and related-job noise."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""

    start_keywords = (
        "REQ ID:",
        "About the job",
        "About this job",
        "The Role",
        "Description",
        "Job Description",
        "Job Summary",
        "Position Summary",
        "What you'll do",
        "What you will do",
        "Responsibilities",
        "Requirements",
        "Minimum Qualifications",
        "Basic Qualifications",
        "Required Qualifications",
        "Who you are",
        "Role Summary",
    )
    end_keywords = (
        "Similar Jobs",
        "Related Jobs",
        "Recommended Jobs",
        "Learn More",
        "Our Company",
        "Our Philosophy",
        "Our Culture",
        "Cookie Consent",
        "Terms of Use",
        "Privacy Policy",
        "Applicant Privacy Notice",
        "BACK TO TOP",
    )
    noisy_exact = {
        "skip to main content",
        "english",
        "career areas",
        "life at fedex",
        "hiring & development",
        "international",
        "career search",
        "fedex careers",
        "apply",
        "share job",
        "apply now",
        "save job",
        "create job alert",
        "sign in",
    }
    noisy_contains = (
        "uses cookies",
        "cookie preference",
        "essential cookies",
        "accept all cookies",
        "reject optional cookies",
    )

    start_index = 0
    for index, line in enumerate(lines):
        if any(line.startswith(keyword) for keyword in start_keywords):
            start_index = index
            break

    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        if any(lines[index].startswith(keyword) for keyword in end_keywords):
            end_index = index
            break

    cleaned = []
    for line in lines[start_index:end_index]:
        lower = line.lower()
        if lower in noisy_exact:
            continue
        if any(term in lower for term in noisy_contains):
            continue
        cleaned.append(line)

    return "\n".join(cleaned)


# ═══════════════════════════════════════════════════════════════
# PAGE LOAD LOGIC
# ═══════════════════════════════════════════════════════════════


async def wait_for_page_ready(page: Page, timeout_ms: int) -> None:
    """
    Wait for page to be ready with multiple strategies.
    
    Strategy:
      1. Wait for network idle (slower but more reliable)
      2. Fall back to DOM ready if timeout
      3. Check for job content visible
    
    ⚠️ FAILURE POINT: Some SPAs never reach "networkidle"; will timeout.
    MITIGATION: Falls back after timeout; likely still has loaded content.
    
    Args:
        page: Playwright page object
        timeout_ms: Max time to wait
    """
    try:
        # Try network idle first (most reliable)
        await asyncio.wait_for(
            page.wait_for_load_state("networkidle", timeout=timeout_ms),
            timeout=timeout_ms / 1000.0,
        )
        console.log("[green]✓ Network idle[/green]")
    except asyncio.TimeoutError:
        console.log("[yellow]⚠️ Network idle timeout, trying domcontentloaded[/yellow]")
        try:
            await asyncio.wait_for(
                page.wait_for_load_state("domcontentloaded", timeout=5000),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            console.log("[yellow]⚠️ DOM load timeout, continuing anyway[/yellow]")
    
    # Small delay for JS rendering
    await asyncio.sleep(1)


async def dismiss_cookie_banner(page: Page) -> None:
    """Best-effort dismissal for cookie banners that cover job content."""
    button_names = [
        "Reject Optional Cookies",
        "Accept All Cookies",
        "Accept Cookies",
        "Accept",
        "I Agree",
    ]
    for name in button_names:
        try:
            button = page.get_by_role("button", name=name)
            if await button.count():
                await button.first.click(timeout=1500)
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue


# ═══════════════════════════════════════════════════════════════
# MAIN EXTRACTION FUNCTION
# ═══════════════════════════════════════════════════════════════


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    retry=retry_if_exception_type(NetworkTimeoutError),
    before_sleep=lambda retry_state: console.log(
        f"[yellow]Retry {retry_state.attempt_number}/3[/yellow]"
    ),
)
async def extract_job_description(job_url: str) -> ExtractionResult:
    """
    Extract job description from a job posting URL.
    
    Orchestrates:
      1. Browser initialization with anti-bot measures
      2. Platform detection
      3. Page load and readiness check
      4. Login wall & CAPTCHA detection
      5. Text extraction with fallback selectors
    
    ⚠️ FAILURE POINTS:
      - Network timeout → retried via @retry decorator
      - Login wall → raises PermissionError
      - CAPTCHA → logs warning, attempts extraction anyway
      - Unknown platform → uses heuristic fallback
      - Empty extraction → raises PlatformDetectionError
    
    Args:
        job_url: URL of job posting to extract
        
    Returns:
        ExtractionResult with extracted text, platform, etc.
        
    Raises:
        LoginWallError: If page requires login
        PlatformDetectionError: If extraction fails completely
        NetworkTimeoutError: On network timeout (retried)
    """
    browser: Optional[Browser] = None
    
    try:
        # Detect platform
        platform = detect_platform(job_url)
        console.log(f"[cyan]Detected platform: {platform.value}[/cyan]")
        
        # Launch browser
        async with async_playwright() as playwright_instance:
            browser_type = getattr(playwright_instance, BROWSER_TYPE)
            browser = await browser_type.launch(headless=HEADLESS)
            
            # Create context with anti-bot measures
            context = await browser.new_context(
                viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                user_agent=USER_AGENT,
                locale=LOCALE,
                timezone_id=TIMEZONE,
            )
            
            page = await context.new_page()
            
            # Apply anti-bot spoofing
            await setup_anti_bot_context(page)
            
            # Set timeouts
            page.set_default_timeout(TIMEOUT_MS)
            page.set_default_navigation_timeout(TIMEOUT_MS)
            
            # Navigate to URL
            console.log(f"[blue]→ Navigating to {job_url}[/blue]")
            try:
                await page.goto(job_url, wait_until="domcontentloaded")
            except Exception as e:
                console.log(f"[red]Navigation error: {e}[/red]")
                raise NetworkTimeoutError(f"Failed to navigate: {e}")
            
            # Wait for page to be ready
            await wait_for_page_ready(page, WAIT_NETWORK_IDLE_TIMEOUT)
            await dismiss_cookie_banner(page)
            
            # Check for login wall
            if await detect_login_wall(page, platform):
                raise LoginWallError(
                    f"Job page requires authentication. URL: {job_url}"
                )
            
            # Check for CAPTCHA (non-fatal)
            captcha_detected = await detect_captcha(page)
            screenshot_path = None
            if captcha_detected:
                # Take screenshot for manual review
                screenshot_path = str(
                    OUTPUT_DIR / f"captcha_{int(time.time())}.png"
                )
                await page.screenshot(path=screenshot_path)
                console.log(f"[yellow]CAPTCHA screenshot saved: {screenshot_path}[/yellow]")
            
            # Extract text
            console.log("[blue]Extracting text...[/blue]")
            raw_text = await extract_text_content(page, platform)
            
            word_count = len(raw_text.split())
            console.log(f"[green]✓ Extracted {word_count} words[/green]")
            
            if not screenshot_path:
                screenshot_path = str(OUTPUT_DIR / f"jd_{int(time.time())}.png")
                await page.screenshot(path=screenshot_path, full_page=True)
                console.log(f"[green]JD screenshot saved: {screenshot_path}[/green]")

            await context.close()
            
            # Build result
            result = ExtractionResult(
                url=job_url,
                raw_text=raw_text,
                platform=platform,
                word_count=word_count,
                success=True,
                error=None,
                screenshot_path=screenshot_path,
            )
            
            return result
    
    except LoginWallError as e:
        console.log(f"[red]✗ {e}[/red]")
        return ExtractionResult(
            url=job_url,
            raw_text="",
            platform=detect_platform(job_url),
            word_count=0,
            success=False,
            error=str(e),
        )
    
    except PlatformDetectionError as e:
        console.log(f"[red]✗ {e}[/red]")
        return ExtractionResult(
            url=job_url,
            raw_text="",
            platform=detect_platform(job_url),
            word_count=0,
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
        
        return ExtractionResult(
            url=job_url,
            raw_text="",
            platform=detect_platform(job_url),
            word_count=0,
            success=False,
            error=f"Unexpected error: {str(e)}",
        )
    
    finally:
        if browser:
            await browser.close()


# ═══════════════════════════════════════════════════════════════
# CLI TEST COMMAND
# ═══════════════════════════════════════════════════════════════


async def main():
    """Test extraction with sample URL"""
    # Example: Replace with actual job posting URL
    test_url = "https://boards.greenhouse.io/example/jobs/1234"
    
    console.print(
        "[bold cyan]MODULE 1 — Job Description Extractor[/bold cyan]"
    )
    console.print(f"[dim]Testing URL: {test_url}[/dim]")
    
    result = await extract_job_description(test_url)
    
    console.print("\n[bold]Extraction Result:[/bold]")
    console.print(result.model_dump_json(indent=2))
    
    # Save result to file
    output_file = OUTPUT_DIR / f"extraction_{int(time.time())}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(), f, indent=2)
    console.log(f"[green]Result saved to: {output_file}[/green]")


if __name__ == "__main__":
    asyncio.run(main())
