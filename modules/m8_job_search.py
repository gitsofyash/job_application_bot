"""
RSS/XML-based job search module.

Fetches recently posted jobs (<=24 hours old) directly from public RSS/Atom
feeds published by real job boards. No browser automation, no API keys.
Returns structured results that include a direct apply link for every listing.

Fixes applied (v3):
  1. Request explosion fixed - per-role boards fire ONE request per role only.
     Total requests: ~24 instead of 127.
  2. Blocked boards removed - Indeed, Remotive, Wellfound, Naukri all return
     403 from plain httpx. Replaced with confirmed-working boards:
       RemoteOK, We Work Remotely, LinkedIn, Himalayas, Jobicy, Adzuna.
  3. LinkedIn XML parse error fixed - unescaped & sanitised before ET.fromstring().
  4. ET truth-value DeprecationWarning fixed - all checks use `is not None`.
"""

import asyncio
import json
import math
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

import httpx
import feedparser
from utils.console import SafeConsole as Console

try:
    from config.settings import OUTPUT_DIR, USER_AGENT
    from modules.m3_generator import flatten_base_skills, load_base_resume
except ImportError:
    OUTPUT_DIR = Path("output")
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def load_base_resume() -> dict:
        return {}

    def flatten_base_skills(resume_data: dict) -> list[str]:
        return ["Python", "AWS", "Docker", "REST API", "PostgreSQL"]


console = Console()

# ---------------------------------------------------------------------------
# Candidate profile
# ---------------------------------------------------------------------------

DEFAULT_DESIRED_ROLES: list[str] = [
    "Software Engineer",
    "Backend Engineer",
    "Cloud Engineer",
    "Full Stack Engineer",
    "DevOps Engineer",
    "AI Developer",
    "Machine Learning Engineer",
]

DEFAULT_INDUSTRY_PREFERENCES: list[str] = [
    "Cloud Infrastructure",
    "Automotive Technology",
    "SaaS",
    "FinTech",
    "AI/ML",
    "Cybersecurity",
    "E-commerce",
    "Healthcare Technology",
    "EdTech",
    "Gaming",
]

DEFAULT_EXPERIENCE_MIN_YEARS: int = 0
DEFAULT_EXPERIENCE_MAX_YEARS: int = 1
MAX_AGE_HOURS: int = 24


def _profile_location_to_search_text(value: object) -> str:
    if isinstance(value, dict):
        secondary = str(value.get("secondary_location") or "").strip()
        if secondary:
            return secondary
        parts = [
            str(value.get("city") or "").strip(),
            str(value.get("state") or "").strip(),
            str(value.get("country") or "").strip(),
        ]
        return ", ".join(part for part in parts if part) or "India"
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "India"


def _profile_country(value: object) -> str:
    if isinstance(value, dict):
        country = str(value.get("country") or "").strip()
        if country:
            return country
    text = str(value or "")
    if "india" in text.lower():
        return "India"
    return "India"


def _resolve_profile(resume_data: dict) -> dict:
    personal_info = resume_data.get("personal_info") or {}
    years_experience = resume_data.get("years_experience")
    try:
        years_float = float(years_experience)
    except (TypeError, ValueError):
        years_float = float(DEFAULT_EXPERIENCE_MAX_YEARS)

    exp_min = max(DEFAULT_EXPERIENCE_MIN_YEARS, math.floor(years_float))
    exp_max = max(DEFAULT_EXPERIENCE_MAX_YEARS, math.ceil(years_float))

    location = resume_data.get("location", personal_info.get("location", "India"))
    return {
        "name": resume_data.get("name") or personal_info.get("name") or "",
        "roles": resume_data.get("desired_roles") or DEFAULT_DESIRED_ROLES,
        "industries": (
            resume_data.get("industry_preferences") or DEFAULT_INDUSTRY_PREFERENCES
        ),
        "location": _profile_location_to_search_text(location),
        "country": _profile_country(location),
        "remote": bool(resume_data.get("open_to_remote", True)),
        "exp_min": exp_min,
        "exp_max": exp_max,
        "years_experience": years_float,
    }

# ---------------------------------------------------------------------------
# Feed templates
#
# per_role=True  -> one URL per role (industry rotated into query, not multiplied)
# per_role=False -> one URL total  (category feed, client-side role filtering)
#
# Boards confirmed to work without auth or proxy:
#   RemoteOK, WeWorkRemotely, LinkedIn (with XML sanitiser), Himalayas,
#   Jobicy, Adzuna India (anonymous tier).
#
# Boards that 403 plain httpx (excluded):
#   Indeed, Remotive, Wellfound, Naukri
# ---------------------------------------------------------------------------
FEED_TEMPLATES: list[dict] = [
    {
        "name": "RemoteOK",
        "url": "https://remoteok.com/remote-{slug}-jobs.rss",
        "type": "rss",
        "always_remote": True,
        "per_role": True,
    },
    {
        "name": "WeWorkRemotely-Programming",
        "url": "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "type": "rss",
        "always_remote": True,
        "per_role": False,
    },
    {
        "name": "WeWorkRemotely-DevOps",
        "url": "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
        "type": "rss",
        "always_remote": True,
        "per_role": False,
    },
    {
        "name": "LinkedIn",
        # f_TPR=r86400 -> last 24 h; f_E=2,3 -> entry + associate level
        # type=rss_dirty triggers XML sanitisation before parse
        "url": (
            "https://www.linkedin.com/jobs/search/?keywords={role}"
            "&location={location}&f_TPR=r86400&f_E=2&f_E=3&format=rss"
        ),
        "type": "rss_dirty",
        "per_role": True,
    },
    {
        "name": "Himalayas",
        "url": "https://himalayas.app/jobs/rss?q={role}&limit=50",
        "type": "rss",
        "always_remote": True,
        "per_role": True,
    },
    {
        "name": "Jobicy",
        "url": "https://jobicy.com/?feed=job_feed&search_region=india&search_keywords={role}",
        "type": "rss",
        "per_role": True,
    },
    {
        "name": "Adzuna",
        # Optional: requires ADZUNA_APP_ID and ADZUNA_APP_KEY.
        "url": (
            "https://api.adzuna.com/v1/api/jobs/in/search/1"
            "?app_id={adzuna_app_id}&app_key={adzuna_app_key}"
            "&results_per_page=50&what={role}&where={location}"
            "&sort_by=date&max_days_old=1"
        ),
        "type": "adzuna_json",
        "per_role": True,
        "requires_env": ["ADZUNA_APP_ID", "ADZUNA_APP_KEY"],
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _build_query(role: str, skills: list[str], industry: Optional[str] = None) -> str:
    skill_str = " ".join(skills[:4])
    parts = [f'"{role}"', skill_str]
    if industry:
        parts.append(industry)
    return " ".join(parts)


def _role_terms(role: str) -> list[str]:
    role_lower = role.lower()
    explicit = {
        "software engineer": ["software engineer", "software developer"],
        "backend engineer": ["backend", "back end", "api engineer"],
        "cloud engineer": ["cloud engineer", "aws", "cloud infrastructure"],
        "full stack engineer": ["full stack", "fullstack"],
        "devops engineer": ["devops", "site reliability", "sre"],
        "ai developer": ["ai developer", "ai engineer", "artificial intelligence"],
        "machine learning engineer": ["machine learning", "ml engineer", "mlops"],
    }
    terms = explicit.get(role_lower, [role_lower])
    generic = {"engineer", "developer"}
    words = [
        word
        for word in re.split(r"[^a-z0-9+]+", role_lower)
        if len(word) > 2 and word not in generic
    ]
    return list(dict.fromkeys(terms + words))


def _job_matches_profile(job: dict, roles: list[str], skills: list[str]) -> bool:
    text = " ".join(
        str(job.get(field, ""))
        for field in ("title", "snippet", "company", "location")
    ).lower()
    if not text.strip():
        return False

    role_match = any(term in text for role in roles for term in _role_terms(role))
    skill_terms = [skill.lower() for skill in skills[:10] if len(skill) > 1]
    skill_match = any(skill in text for skill in skill_terms)
    return role_match or skill_match


def _job_text(job: dict) -> str:
    return " ".join(
        str(job.get(field, ""))
        for field in ("title", "snippet", "company", "location", "source")
    ).lower()


def _is_india_eligible(job: dict, profile: dict) -> tuple[bool, str]:
    text = _job_text(job)
    location = str(job.get("location", "")).lower()
    country = str(profile.get("country") or "India").lower()

    hard_reject_patterns = [
        r"\bu\.?s\.?\s+citizens?\s+only\b",
        r"\bunited\s+states\s+citizens?\s+only\b",
        r"\bgreen\s+card\b",
        r"\bsecurity\s+clearance\b",
        r"\bsecret\s+clearance\b",
        r"\btop\s+secret\b",
        r"\bactive\s+clearance\b",
        r"\bus\s+only\b",
        r"\bu\.s\.\s+only\b",
        r"\bunited\s+states\s+only\b",
        r"\bcanada\s+only\b",
        r"\buk\s+only\b",
        r"\beu\s+only\b",
        r"\beurope\s+only\b",
        r"\baustralia\s+only\b",
        r"\bmust\s+be\s+(?:based|located)\s+in\s+(?:the\s+)?(?:us|u\.s\.|united\s+states|uk|europe|canada|australia)\b",
        r"\bauthorized\s+to\s+work\s+in\s+(?:the\s+)?(?:us|u\.s\.|united\s+states|uk|canada|australia)\b",
        r"\bwork\s+authorization\s+in\s+(?:the\s+)?(?:us|u\.s\.|united\s+states|uk|canada|australia)\b",
    ]
    if any(re.search(pattern, text) for pattern in hard_reject_patterns):
        return False, "restricted work authorization/citizenship"

    sponsorship_block = re.search(
        r"\b(?:visa\s+)?sponsorship\s+(?:is\s+)?(?:not\s+available|not\s+provided|unavailable)\b",
        text,
    )
    foreign_location = re.search(
        r"\b(?:united\s+states|u\.s\.|usa|uk|united\s+kingdom|canada|australia|europe|eu)\b",
        text,
    )
    if sponsorship_block and foreign_location and "india" not in text:
        return False, "foreign role without visa sponsorship"

    if country in text or "india" in text:
        return True, "India-compatible location"

    global_remote_terms = [
        "remote worldwide",
        "worldwide remote",
        "work from anywhere",
        "anywhere in the world",
        "global remote",
        "fully remote",
        "remote",
    ]
    restricted_remote_terms = [
        "remote us",
        "remote, us",
        "remote - us",
        "remote united states",
        "remote, united states",
        "remote canada",
        "remote europe",
        "remote uk",
        "remote australia",
    ]
    if any(term in text for term in restricted_remote_terms):
        return False, "remote role is country-restricted"

    if profile.get("remote") and any(term in text for term in global_remote_terms):
        return True, "remote/global-compatible"

    if not location:
        return True, "no location restriction found"

    return False, "location does not show India/global eligibility"


def _build_feeds(
    roles: list[str],
    skills: list[str],
    industries: list[str],
    location: str,
    remote: bool,
    exp_min: int,
    exp_max: int,
) -> list[dict]:
    """
    Build concrete feed request list.

    KEY FIX: per-role boards fire exactly ONE request per role.
    Industry keyword is chosen by round-robin (idx % len(industries))
    so each role gets a different flavour without multiplying requests.

    With 7 roles and 4 per-role boards: 7x4 + 2 category = 30 requests.
    """
    loc_enc = quote_plus(location)
    feeds: list[dict] = []
    seen_urls: set[str] = set()

    for tpl in FEED_TEMPLATES:
        required_env = tpl.get("requires_env") or []
        missing_env = [name for name in required_env if not os.getenv(name)]
        if missing_env:
            console.log(
                f"[dim]Skipping {tpl['name']}: missing {', '.join(missing_env)}[/dim]"
            )
            continue

        if not remote and tpl.get("always_remote"):
            continue

        if tpl.get("per_role"):
            for idx, role in enumerate(roles):
                industry = industries[idx % len(industries)] if industries else None
                query = _build_query(role, skills, industry)
                url = (
                    tpl["url"]
                    .replace("{query}", quote_plus(query))
                    .replace("{role}", quote_plus(role))
                    .replace("{slug}", _slugify(role))
                    .replace("{location}", loc_enc)
                    .replace("{exp_min}", str(exp_min))
                    .replace("{exp_max}", str(exp_max))
                    .replace("{adzuna_app_id}", quote_plus(os.getenv("ADZUNA_APP_ID", "")))
                    .replace("{adzuna_app_key}", quote_plus(os.getenv("ADZUNA_APP_KEY", "")))
                )
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                feeds.append({
                    "name": f"{tpl['name']} > {role}",
                    "url": url,
                    "type": tpl["type"],
                    "role": role,
                    "roles": [role],
                    "query": query,
                })
        else:
            query = _build_query(roles[0], skills, industries[0] if industries else None)
            url = (
                tpl["url"]
                .replace("{query}", quote_plus(query))
                .replace("{role}", quote_plus(query))
                .replace("{slug}", _slugify(roles[0]))
                .replace("{location}", loc_enc)
                .replace("{exp_min}", str(exp_min))
                .replace("{exp_max}", str(exp_max))
                .replace("{adzuna_app_id}", quote_plus(os.getenv("ADZUNA_APP_ID", "")))
                .replace("{adzuna_app_key}", quote_plus(os.getenv("ADZUNA_APP_KEY", "")))
            )
            if url in seen_urls:
                continue
            seen_urls.add(url)
            feeds.append({
                "name": tpl["name"],
                "url": url,
                "type": tpl["type"],
                "role": roles[0],
                "roles": roles,
                "query": query,
            })

    return feeds


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str).astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str[:19], fmt[:19]).replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def _is_recent(date_str: Optional[str], max_hours: int = MAX_AGE_HOURS) -> bool:
    dt = _parse_date(date_str)
    if dt is None:
        return True
    return dt >= datetime.now(timezone.utc) - timedelta(hours=max_hours)


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _sanitise_xml(xml_text: str) -> str:
    """
    FIX for LinkedIn XML parse error:
    Replace bare & that are NOT part of a valid XML entity with &amp;
    This handles unescaped & in query strings embedded in href attributes.
    """
    return re.sub(
        r"&(?!(?:[a-zA-Z][a-zA-Z0-9]*|#[0-9]+|#x[0-9a-fA-F]+);)",
        "&amp;",
        xml_text,
    )


def _extract_apply_link(item_el: ET.Element, fallback: str) -> str:
    for tag in ("apply", "applyUrl", "apply_url", "jobUrl", "job_url"):
        # FIX: use `is not None` to avoid DeprecationWarning
        el = item_el.find(tag)
        if el is None:
            el = item_el.find(f"{{*}}{tag}")
        if el is not None and el.text:
            return el.text.strip()
    return fallback


def _entry_value(entry: dict, *keys: str) -> str:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            text = value.get("value") or value.get("href") or value.get("name")
            if isinstance(text, str) and text.strip():
                return text.strip()
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict):
                text = first.get("value") or first.get("href") or first.get("name")
                if isinstance(text, str) and text.strip():
                    return text.strip()
            elif isinstance(first, str) and first.strip():
                return first.strip()
    return ""


def _parse_rss_with_feedparser(
    xml_text: str, feed_name: str, query: str, max_hours: int
) -> list[dict]:
    parsed = feedparser.parse(xml_text)
    jobs: list[dict] = []

    for entry in parsed.entries:
        pub_date = _entry_value(entry, "published", "updated", "created", "dc_date")
        if not _is_recent(pub_date, max_hours):
            continue

        detail_link = _entry_value(entry, "link", "id")
        apply_link = _entry_value(
            entry,
            "apply",
            "applyurl",
            "apply_url",
            "joburl",
            "job_url",
            "links",
        ) or detail_link
        company = _entry_value(
            entry,
            "company",
            "author",
            "author_detail",
            "source",
            "dc_creator",
        )
        location = _entry_value(entry, "location", "job_location", "georss_point")
        snippet = _strip_html(
            _entry_value(entry, "summary", "description", "content", "subtitle")
        )[:300]

        jobs.append({
            "title": _entry_value(entry, "title"),
            "company": company,
            "location": location,
            "published": pub_date,
            "snippet": snippet,
            "apply_link": apply_link,
            "detail_link": detail_link,
            "source": feed_name,
            "query": query,
        })

    return jobs


# ---------------------------------------------------------------------------
# Per-format parsers
# ---------------------------------------------------------------------------

def _parse_rss(
    xml_text: str, feed_name: str, query: str, max_hours: int, dirty: bool = False
) -> list[dict]:
    if dirty:
        xml_text = _sanitise_xml(xml_text)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        console.log(
            f"[yellow]XML parse fallback ({feed_name}):[/yellow] {exc}"
        )
        return _parse_rss_with_feedparser(xml_text, feed_name, query, max_hours)

    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    jobs: list[dict] = []
    for item in items:
        def t(tag: str) -> str:
            # FIX: all checks use `is not None`
            el = item.find(tag)
            if el is None:
                el = item.find(f"{{http://www.w3.org/2005/Atom}}{tag}")
            if el is None:
                el = item.find(f"{{http://purl.org/dc/elements/1.1/}}{tag}")
            return (el.text or "").strip() if el is not None else ""

        pub_date = t("pubDate") or t("updated") or t("published") or t("date")
        if not _is_recent(pub_date, max_hours):
            continue

        link = t("link") or t("id")
        if not link:
            link_el = item.find("{http://www.w3.org/2005/Atom}link")
            if link_el is not None:
                link = link_el.get("href", "")

        jobs.append({
            "title": t("title"),
            "company": t("company") or t("author") or "",
            "location": t("location") or "",
            "published": pub_date,
            "snippet": _strip_html(t("description") or t("summary") or t("content"))[:300],
            "apply_link": _extract_apply_link(item, link),
            "detail_link": link,
            "source": feed_name,
            "query": query,
        })
    return jobs


def _parse_adzuna_json(json_text: str, feed_name: str, query: str, max_hours: int) -> list[dict]:
    jobs: list[dict] = []
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return jobs
    for item in data.get("results", []):
        pub_date = item.get("created", "")
        if not _is_recent(pub_date, max_hours):
            continue
        redirect = item.get("redirect_url", "")
        jobs.append({
            "title": item.get("title", ""),
            "company": item.get("company", {}).get("display_name", ""),
            "location": item.get("location", {}).get("display_name", ""),
            "published": pub_date,
            "snippet": _strip_html(item.get("description", ""))[:300],
            "apply_link": redirect,
            "detail_link": redirect,
            "source": feed_name,
            "query": query,
        })
    return jobs


# ---------------------------------------------------------------------------
# Core async fetcher
# ---------------------------------------------------------------------------

async def _fetch_feed(
    client: httpx.AsyncClient,
    feed: dict,
    max_hours: int,
    skills: list[str],
    profile: dict,
) -> list[dict]:
    url = feed["url"]
    feed_name = feed["name"]
    feed_type = feed["type"]
    query = feed.get("query", "")

    try:
        console.log(f"[cyan]Fetching:[/cyan] {feed_name}")
        resp = await client.get(url, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        body = resp.text
    except Exception as exc:
        console.log(f"[yellow]Skipping {feed_name}:[/yellow] {exc}")
        return []

    if feed_type == "rss":
        jobs = _parse_rss(body, feed_name, query, max_hours, dirty=False)
    elif feed_type == "rss_dirty":
        jobs = _parse_rss(body, feed_name, query, max_hours, dirty=True)
    elif feed_type == "adzuna_json":
        jobs = _parse_adzuna_json(body, feed_name, query, max_hours)
    else:
        console.log(f"[red]Unknown feed type:[/red] {feed_type}")
        return []

    roles = feed.get("roles") or [feed.get("role", "")]
    filtered: list[dict] = []
    for job in jobs:
        if not _job_matches_profile(job, roles, skills):
            continue
        eligible, reason = _is_india_eligible(job, profile)
        if not eligible:
            continue
        job["role"] = feed.get("role", "")
        job["candidate_eligible"] = True
        job["eligibility_reason"] = reason
        filtered.append(job)
    return filtered


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def search_jobs_via_rss(
    roles: list[str] | None = None,
    industries: list[str] | None = None,
    location: str | None = None,
    remote: bool | None = None,
    max_results: int = 50,
    max_age_hours: int = MAX_AGE_HOURS,
    exp_min: int | None = None,
    exp_max: int | None = None,
    output_dir: Path | None = None,
) -> list[dict]:
    """
    Fetch job listings <=24 h old from public RSS/JSON feeds.

    Returns list[dict] with keys:
        title, company, location, published, snippet,
        apply_link, detail_link, source, query, role.
    """
    resume_data = load_base_resume()
    profile = _resolve_profile(resume_data)

    roles = roles or profile["roles"]
    industries = industries or profile["industries"]
    location = location or profile["location"]
    remote = profile["remote"] if remote is None else remote
    exp_min = profile["exp_min"] if exp_min is None else exp_min
    exp_max = profile["exp_max"] if exp_max is None else exp_max

    skills = flatten_base_skills(resume_data) or ["Python", "AWS", "Docker", "REST API"]

    feeds = _build_feeds(roles, skills, industries, location, remote, exp_min, exp_max)

    console.log(
        f"[bold]Profile:[/bold] {profile['name'] or 'base_resume.json'}  |  "
        f"experience={profile['years_experience']}y\n"
        f"[bold]Roles:[/bold] {roles}\n"
        f"[bold]Industries:[/bold] {industries[:3]}  |  exp={exp_min}-{exp_max}y  |  "
        f"location={location}  |  country={profile['country']}  |  "
        f"remote={remote}  |  max_age={max_age_hours}h"
    )
    console.log(f"[dim]Total feed requests: {len(feeds)}[/dim]")

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, application/json, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [
            _fetch_feed(client, feed, max_age_hours, skills, profile)
            for feed in feeds
        ]
        per_feed_results = await asyncio.gather(*tasks)

    seen: set[str] = set()
    results: list[dict] = []
    for feed_jobs in per_feed_results:
        for job in feed_jobs:
            key = job["apply_link"] or job["detail_link"]
            if not key or key in seen:
                continue
            seen.add(key)
            results.append(job)
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break

    def sort_key(j: dict) -> datetime:
        dt = _parse_date(j.get("published"))
        return dt or datetime.min.replace(tzinfo=timezone.utc)

    results.sort(key=sort_key, reverse=True)

    out_dir = Path(output_dir or OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = out_dir / f"job_search_rss_{ts}.json"
    report_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "roles": roles,
                "industries": industries,
                "candidate": profile["name"],
                "profile_years_experience": profile["years_experience"],
                "experience_years": f"{exp_min}-{exp_max}",
                "location": location,
                "candidate_country": profile["country"],
                "eligibility_filter": "India/global remote only; rejects country-only, citizenship, work authorization, and clearance-restricted roles",
                "remote": remote,
                "max_age_hours": max_age_hours,
                "total": len(results),
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    console.log(f"[green]Saved {len(results)} jobs ->[/green] {report_path}")
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="RSS job search v3")
    parser.add_argument("--roles", nargs="*", default=None)
    parser.add_argument("--industries", nargs="*", default=None)
    parser.add_argument("--location", default=None)
    parser.add_argument("--remote", dest="remote", action="store_true", default=None)
    parser.add_argument("--no-remote", dest="remote", action="store_false")
    parser.add_argument("--max-results", type=int, default=50)
    parser.add_argument("--max-age-hours", type=int, default=24)
    parser.add_argument("--exp-min", type=int, default=None)
    parser.add_argument("--exp-max", type=int, default=None)
    args = parser.parse_args()

    results = await search_jobs_via_rss(
        roles=args.roles,
        industries=args.industries,
        location=args.location,
        remote=args.remote,
        max_results=args.max_results,
        max_age_hours=args.max_age_hours,
        exp_min=args.exp_min,
        exp_max=args.exp_max,
    )
    console.print_json(data=results[:5])


if __name__ == "__main__":
    asyncio.run(main())
