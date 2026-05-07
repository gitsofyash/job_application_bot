"""
MODULE 9 - Resume/Profile Q&A

Answers questions about Yash using only local resume and profile JSON data.
The module is deterministic and grounded: if the information is not present in
the local data files, it says so instead of guessing.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from config.settings import BASE_RESUME_PATH, USER_PROFILE_PATH
from utils.url_parser import fix_encoding_issues


STOPWORDS = {
    "a", "an", "and", "anything", "about", "are", "as", "ask", "be", "can",
    "did", "do", "for", "from", "get", "give", "i", "in", "is", "it", "me",
    "mention", "mentioned", "my", "of", "on", "or", "profile", "regarding",
    "resume", "so", "tell", "that", "the", "this", "to", "what", "when",
    "where", "which", "who", "with", "you",
}


@dataclass
class ProfileAnswer:
    """Answer with source snippets from local resume/profile files."""

    answer: str
    sources: list[str]
    confidence: float


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _clean(value: Any) -> str:
    return fix_encoding_issues(str(value)).strip()


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9+#.]+", text.lower())
        if len(token) > 1 and token not in STOPWORDS
    }


def _flatten(value: Any, label: str) -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        title_bits = []
        for key in ("title", "degree", "company", "institution", "name"):
            if value.get(key):
                title_bits.append(_clean(value[key]))
        next_label = f"{label}: {' - '.join(title_bits)}" if title_bits else label

        scalar_parts = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                yield from _flatten(item, f"{next_label} > {key}")
            elif item not in (None, ""):
                scalar_parts.append(f"{key}: {_clean(item)}")
        if scalar_parts:
            yield next_label, "; ".join(scalar_parts)
    elif isinstance(value, list):
        for index, item in enumerate(value, 1):
            yield from _flatten(item, f"{label} #{index}")
    elif value not in (None, ""):
        yield label, _clean(value)


def build_profile_knowledge_base(
    base_resume_path: Optional[str] = None,
    user_profile_path: Optional[str] = None,
) -> list[tuple[str, str, str]]:
    """Return searchable local facts as (source_file, label, text)."""
    resume_path = Path(base_resume_path) if base_resume_path else BASE_RESUME_PATH
    profile_path = Path(user_profile_path) if user_profile_path else USER_PROFILE_PATH
    documents = [
        ("base_resume.json", _load_json(resume_path)),
        ("user_profile.json", _load_json(profile_path)),
    ]

    facts = []
    seen = set()
    for source_name, payload in documents:
        for label, text in _flatten(payload, source_name):
            normalized = re.sub(r"\s+", " ", text.lower())
            if normalized and normalized not in seen:
                facts.append((source_name, label, text))
                seen.add(normalized)
    return facts


def _direct_answer(question: str, resume: dict[str, Any], profile: dict[str, Any]) -> Optional[ProfileAnswer]:
    q = question.lower()
    personal = resume.get("personal_info", {})
    mappings = profile.get("form_field_mappings", {})

    if "current company" in q and profile.get("currently_employed") is False:
        return ProfileAnswer("Not currently employed", ["currently_employed"], 0.98)

    if "current title" in q and profile.get("currently_employed") is False:
        return ProfileAnswer(
            _clean(mappings.get("current_title") or "Software Engineer"),
            ["target title"],
            0.9,
        )

    direct_fields = {
        "email": personal.get("email") or profile.get("email"),
        "phone": personal.get("phone") or profile.get("phone"),
        "location": personal.get("location") or profile.get("location"),
        "linkedin": personal.get("linkedin") or profile.get("linkedin"),
        "github": personal.get("github") or profile.get("github"),
        "notice period": profile.get("notice_period_days"),
        "current company": mappings.get("current_company"),
        "current title": mappings.get("current_title"),
        "experience": profile.get("years_experience"),
    }

    for field, value in direct_fields.items():
        if field in q and value not in (None, ""):
            text = _clean(value)
            if field == "notice period":
                text = f"{text} days"
            elif field == "experience":
                text = f"{text} years"
            return ProfileAnswer(text, [field], 0.98)

    return None


def answer_profile_question(
    question: str,
    base_resume_path: Optional[str] = None,
    user_profile_path: Optional[str] = None,
    max_sources: int = 5,
) -> ProfileAnswer:
    """Answer a question using only resume/profile JSON facts."""
    resume_path = Path(base_resume_path) if base_resume_path else BASE_RESUME_PATH
    profile_path = Path(user_profile_path) if user_profile_path else USER_PROFILE_PATH
    resume = _load_json(resume_path)
    profile = _load_json(profile_path)

    direct = _direct_answer(question, resume, profile)
    if direct:
        return direct

    query_tokens = _tokenize(question)
    if not query_tokens:
        return ProfileAnswer(
            "Ask a more specific question about your resume or profile.",
            [],
            0.0,
        )

    scored = []
    for source_name, label, text in build_profile_knowledge_base(str(resume_path), str(profile_path)):
        haystack = _tokenize(f"{label} {text}")
        overlap = query_tokens & haystack
        if not overlap:
            continue
        phrase_bonus = 1 if question.lower() in text.lower() else 0
        score = (len(overlap) * 2) + phrase_bonus + min(len(text.split()) / 80, 1)
        scored.append((score, source_name, label, text))

    scored.sort(key=lambda item: item[0], reverse=True)
    best = scored[:max_sources]

    if not best:
        return ProfileAnswer(
            "I could not find that in your saved resume or profile data.",
            [],
            0.15,
        )

    lines = [item[3] for item in best]
    sources = [f"{item[1]} > {item[2]}" for item in best]
    confidence = min(0.95, 0.35 + (best[0][0] / 10))
    answer = "\n".join(f"- {line}" for line in lines)
    return ProfileAnswer(answer=answer, sources=sources, confidence=round(confidence, 2))
