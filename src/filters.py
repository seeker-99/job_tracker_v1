"""Role & location relevance filtering."""
import re


def is_relevant(title: str, location: str, roles_cfg: dict, locations_cfg: dict) -> bool:
    if not title:
        return False
    t = title.lower()

    # Always exclude unwanted categories regardless of mode.
    for kw in roles_cfg.get("exclude_keywords", []):
        if kw.lower() in t:
            return False

    filter_mode = roles_cfg.get("filter_mode", "include_priority")
    # "include_priority" (original behavior): title must match one of
    #   priority_keywords / include_keywords to pass.
    # "exclude_only" (relaxed): anything not caught by exclude_keywords
    #   passes - broadens results a lot, useful for smaller companies
    #   whose roles don't fit a fixed keyword list (e.g. Ather's "Test
    #   Engineer" wouldn't match "software engineer" etc.)
    if filter_mode == "include_priority":
        matched_role = any(kw.lower() in t for kw in roles_cfg.get("priority_keywords", [])) or \
            any(kw.lower() in t for kw in roles_cfg.get("include_keywords", []))
        if not matched_role:
            return False
    # else: exclude_only mode - already passed the exclude check above, so proceed.

    if location:
        loc = location.lower()
        preferred = [c.lower() for c in locations_cfg.get("preferred_cities", [])]
        if preferred and not any(city in loc for city in preferred):
            # Location present but doesn't match India / preferred cities -> exclude
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
