"""
Fetch paralegal/legal vacancies from Reed and Adzuna (legitimate APIs, ToS-compliant).

Requires environment variables:
  REED_API_KEY     - free key from https://www.reed.co.uk/developers
  ADZUNA_APP_ID    - free from https://developer.adzuna.com/
  ADZUNA_APP_KEY

Config below controls search terms and locations - edit to taste.
"""

import os
import json
import base64
import requests
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
SEEN_FILE = DATA_DIR / "seen_jobs.json"

SEARCH_TERMS = ["paralegal", "legal assistant", "junior legal", "trainee paralegal"]
LOCATIONS = ["Reading", "High Wycombe", "Loudwater", "Maidenhead"]
RESULTS_PER_SEARCH = 20
MAX_NEW_JOBS_PER_RUN = 10  # caps drafting cost/volume per run, incl. the first big run


def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()).get("seen_job_ids", []))
    return set()


def save_seen(seen_ids):
    SEEN_FILE.write_text(json.dumps({"seen_job_ids": sorted(seen_ids)}, indent=2))


def fetch_reed():
    api_key = os.environ.get("REED_API_KEY")
    if not api_key:
        print("REED_API_KEY not set, skipping Reed")
        return []

    results = []
    auth = base64.b64encode(f"{api_key}:".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}

    for term in SEARCH_TERMS:
        for loc in LOCATIONS:
            resp = requests.get(
                "https://www.reed.co.uk/api/1.0/search",
                headers=headers,
                params={
                    "keywords": term,
                    "locationName": loc,
                    "distanceFromLocation": 10,
                    "resultsToTake": RESULTS_PER_SEARCH,
                },
                timeout=20,
            )
            if resp.status_code != 200:
                print(f"Reed error {resp.status_code} for {term}/{loc}: {resp.text[:200]}")
                continue
            for job in resp.json().get("results", []):
                results.append({
                    "source": "reed",
                    "id": f"reed_{job['jobId']}",
                    "title": job.get("jobTitle"),
                    "employer": job.get("employerName"),
                    "location": job.get("locationName"),
                    "salary": job.get("minimumSalary") and f"£{job['minimumSalary']}-{job.get('maximumSalary')}",
                    "url": job.get("jobUrl"),
                    "description": job.get("jobDescription", ""),
                })
    return results


def fetch_adzuna():
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        print("ADZUNA_APP_ID/KEY not set, skipping Adzuna")
        return []

    results = []
    for term in SEARCH_TERMS:
        resp = requests.get(
            "https://api.adzuna.com/v1/api/jobs/gb/search/1",
            params={
                "app_id": app_id,
                "app_key": app_key,
                "what": term,
                "where": "Reading",
                "distance": 25,
                "results_per_page": RESULTS_PER_SEARCH,
                "content-type": "application/json",
            },
            timeout=20,
        )
        if resp.status_code != 200:
            print(f"Adzuna error {resp.status_code} for {term}: {resp.text[:200]}")
            continue
        for job in resp.json().get("results", []):
            results.append({
                "source": "adzuna",
                "id": f"adzuna_{job['id']}",
                "title": job.get("title"),
                "employer": (job.get("company") or {}).get("display_name"),
                "location": (job.get("location") or {}).get("display_name"),
                "salary": job.get("salary_min") and f"£{job['salary_min']:.0f}-{job.get('salary_max', 0):.0f}",
                "url": job.get("redirect_url"),
                "description": job.get("description", ""),
            })
    return results


def main():
    seen = load_seen()
    all_jobs = fetch_reed() + fetch_adzuna()

    new_jobs = [j for j in all_jobs if j["id"] not in seen]

    # dedupe within this batch by id
    dedup = {}
    for j in new_jobs:
        dedup[j["id"]] = j
    new_jobs = list(dedup.values())

    print(f"Fetched {len(all_jobs)} total, {len(new_jobs)} new")

    to_draft = new_jobs[:MAX_NEW_JOBS_PER_RUN]
    held_back = new_jobs[MAX_NEW_JOBS_PER_RUN:]
    if held_back:
        print(f"Capping at {MAX_NEW_JOBS_PER_RUN}; {len(held_back)} held back for a future run")

    (DATA_DIR / "new_jobs.json").write_text(json.dumps(to_draft, indent=2))

    # only mark drafted ones as seen - held-back ones stay eligible for tomorrow's run
    seen.update(j["id"] for j in to_draft)
    save_seen(seen)


if __name__ == "__main__":
    main()
