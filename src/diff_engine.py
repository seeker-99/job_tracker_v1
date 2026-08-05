"""Compares freshly scraped jobs against SQLite state to find NEW / UPDATED / REMOVED."""
from dataclasses import dataclass
from src import db
from src.filters import is_relevant, extract_experience


@dataclass
class DiffItem:
    status: str  # NEW | UPDATED | REMOVED
    company: str
    title: str
    location: str
    experience: str
    posted_date: str
    link: str


def diff_site(site_id: str, company: str, raw_jobs: list, roles_cfg: dict,
              locations_cfg: dict, run_id: str) -> list[DiffItem]:
    existing = db.get_existing_jobs_for_site(site_id)
    seen_keys = set()
    diffs: list[DiffItem] = []

    for job in raw_jobs:
        if not is_relevant(job.title, job.location, roles_cfg, locations_cfg):
            continue

        key = db.make_job_key(site_id, job.link)
        seen_keys.add(key)
        experience = job.experience or extract_experience(job.title)
        chash = db.content_hash(job.title, job.location, experience, job.posted_date)

        prior = existing.get(key)
        if prior is None:
            status = "NEW"
        elif prior["content_hash"] != chash:
            status = "UPDATED"
        else:
            status = None  # unchanged, don't report

        db.upsert_job(key, site_id, company, job.title, job.location, experience,
                       job.posted_date, job.link, chash, run_id)

        if status:
            diffs.append(DiffItem(status, company, job.title, job.location,
                                   experience, job.posted_date, job.link))

    removed_keys = [k for k in existing if k not in seen_keys]
    if removed_keys:
        db.mark_removed(removed_keys, run_id)
        for k in removed_keys:
            prior = existing[k]
            diffs.append(DiffItem("REMOVED", prior["company"], prior["title"],
                                   prior["location"], prior["experience"],
                                   prior["posted_date"], prior["link"]))

    return diffs
