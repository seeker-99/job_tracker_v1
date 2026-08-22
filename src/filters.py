"""Role & location relevance filtering."""
import re

# Generic non-job text that commonly leaks through when a site's selector
# is slightly too broad (nav links, pagination, legal/footer links). These
# are filtered out regardless of filter_mode, since they're never real job
# titles on any site.
_JUNK_EXACT = {
    "english", "privacy notice", "eeo policy", "terms of use", "cookie policy",
    "open roles", "skip to jobs search results", "g & a", "join talent community",
    "browse careers", "careers home", "our history", "culture", "benefits",
    "students", "military", "pilots", "events", "view all", "apply now",
    "login", "sign in", "all jobs", "home", "menu", "search", "filter",
    "next", "previous", "load more", "show more",
}


def _looks_like_junk(title: str) -> bool:
    t = title.strip().lower()
    if not t:
        return True
    if t in _JUNK_EXACT:
        return True
    # Pure numbers / pagination controls (e.g. "1", "2", "5")
    if re.fullmatch(r"\d{1,3}", t):
        return True
    # Single short word with no letters suggesting a real job title
    # (real titles are almost always 2+ words, or one long compound word)
    word_count = len(t.split())
    if word_count == 1 and len(t) < 8:
        return True
    return False


def is_relevant(title: str, location: str, roles_cfg: dict, locations_cfg: dict) -> bool:
    if not title:
        return False

    if _looks_like_junk(title):
        return False

    t = title.lower()

    # Always exclude unwanted categories regardless of mode.
    for kw in roles_cfg.get("exclude_keywords", []):
        if kw.lower() in t:
            return False

    filter_mode = roles_cfg.get("filter_mode", "include_priority")
    if filter_mode == "include_priority":
        matched_role = any(kw.lower() in t for kw in roles_cfg.get("priority_keywords", [])) or \
            any(kw.lower() in t for kw in roles_cfg.get("include_keywords", []))
        if not matched_role:
            return False
    # else: exclude_only mode - already passed the junk + exclude checks above.

    if location:
        loc = location.lower()
        preferred = [c.lower() for c in locations_cfg.get("preferred_cities", [])]
        if preferred and not any(city in loc for city in preferred):
            return False

    return True


def extract_experience(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"(\d+)\s*[-to]{1,3}\s*(\d+)\s*(?:years|yrs)", text, re.IGNORECASE)
    if m:
        return f"{m.group(1)}-{m.group(2)} years"
    m2 = re.search(r"(\d+)\+?\s*(?:years|yrs)", text, re.IGNORECASE)
    if m2:
        return f"{m2.group(1)}+ years"
    return ""
