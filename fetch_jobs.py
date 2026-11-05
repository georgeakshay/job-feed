"""Fetch fresh UAE job listings with JobSpy and save them to jobs.json.

Runs on GitHub Actions. A Claude scheduled task reads jobs.json,
filters by fit and experience, de-duplicates against past emails,
and sends the shortlist.
"""
import json
import time
from datetime import datetime, timezone

import pandas as pd
from jobspy import scrape_jobs

SEARCH_TERMS = [
    "business analyst",
    "data analyst",
    "business intelligence analyst",
    "power bi",
    "reporting analyst",
    "MIS",
    "odoo",
    "business systems analyst",
    "automation analyst",
    "revenue analyst",
]
HOURS_OLD = 24
RESULTS_PER_SEARCH = 15
DESC_LIMIT = 3500  # characters of description kept per job

SOURCES = [
    # (site, extra kwargs)
    ("linkedin", {"location": "United Arab Emirates", "linkedin_fetch_description": True}),
    ("indeed", {"location": "Dubai", "country_indeed": "united arab emirates"}),
    ("bayt", {"location": "Dubai"}),
]

KEEP_COLS = ["site", "title", "company", "location", "date_posted", "is_remote",
             "job_type", "job_level", "job_url", "job_url_direct", "description"]


def main():
    frames, log = [], []
    for site, kwargs in SOURCES:
        for term in SEARCH_TERMS:
            try:
                df = scrape_jobs(site_name=[site], search_term=term,
                                 results_wanted=RESULTS_PER_SEARCH,
                                 hours_old=HOURS_OLD, verbose=0, **kwargs)
                df["search_term"] = term
                frames.append(df)
                log.append({"site": site, "term": term, "found": len(df)})
            except Exception as e:  # keep going if one site/term fails
                log.append({"site": site, "term": term, "error": str(e)[:200]})
            time.sleep(3)

    jobs = []
    if frames:
        all_df = pd.concat(frames, ignore_index=True)
        all_df = all_df.drop_duplicates(subset=["job_url"])
        all_df = all_df.drop_duplicates(subset=["title", "company"])
        for _, r in all_df.iterrows():
            job = {c: (None if c not in r or pd.isna(r[c]) else r[c]) for c in KEEP_COLS}
            job["search_term"] = r["search_term"]
            if job["date_posted"] is not None:
                job["date_posted"] = str(job["date_posted"])
            if job["is_remote"] is not None:
                job["is_remote"] = bool(job["is_remote"])
            if job["description"]:
                job["description"] = str(job["description"])[:DESC_LIMIT]
            jobs.append(job)

    counts = {}
    for j in jobs:
        counts[j["site"]] = counts.get(j["site"], 0) + 1

    out = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hours_old": HOURS_OLD,
        "counts_by_site": counts,
        "total": len(jobs),
        "search_log": log,
        "jobs": jobs,
    }
    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print(f"Saved {len(jobs)} jobs: {counts}")


if __name__ == "__main__":
    main()
