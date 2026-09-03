"""
Fetch upcoming graduate-eligible, direct-entry Training Contract deadlines.

Unlike fetch_open_days.py, this file is NOT a plain scrape-and-publish: Legal
Cheek's Key Deadlines Calendar lists a closing date and nothing else - no
opening date, no direct "apply" URL, and critically no eligibility info. Some
firms' "Training Contract" listings are only open to candidates who've
already done that firm's vacation scheme, or only to final-year students -
not to graduates applying directly. Maria is a graduate, so those have to be
excluded, not just left in with a caveat.

So this script scrapes Legal Cheek for the closing date (which stays fresh
automatically) and cross-references TC_OVERRIDES below - a manually
researched, per-entry record of: opening date, the most specific apply URL
findable on the firm's own site, and a plain-English eligibility note -
confirmed by actually reading each firm's own graduate recruitment pages.

Any Training Contract entry Legal Cheek starts listing that ISN'T in
TC_OVERRIDES is deliberately left OUT of docs/tc_deadlines.json rather than
guessed at, and is instead written to the "needs_review" list in the same
file so a future run (human or Claude) knows to research it before it can
show up on the dashboard. This fails closed by design: better to miss a
brand new listing for a day than to show Maria a training contract she can't
actually apply to as a graduate.

Output: docs/tc_deadlines.json
"""
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.legalcheek.com/key-deadlines-calendar/"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "tc_deadlines.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

RELEVANT_RE = re.compile(r"training contract|training programme", re.IGNORECASE)
EXCLUDE_RE = re.compile(r"vacation scheme", re.IGNORECASE)

# Manually verified against each firm's own graduate recruitment pages,
# 2026-09-03. Key is (firm, event_name) exactly as Legal Cheek shows it.
# "opens_confirmed": False means the opening date is estimated from last
# year's cycle (the firm's site didn't have next cycle's exact date
# published yet) - the closing date always comes fresh from Legal Cheek,
# which is the reliable part.
TC_OVERRIDES = {
    ("A&O Shearman", "Direct Training Contract"): {
        "opens_date": "2026-09-01",
        "opens_confirmed": True,
        "apply_link": "https://careers.aoshearman.com/en/job/london/march-2028-training-contract/3392/43859038208",
        "eligibility_note": "Open to graduates of any degree applying directly - no vacation scheme required.",
    },
    ("Clifford Chance", "London Training Contract"): {
        "opens_date": "2026-09-15",
        "opens_confirmed": False,
        "apply_link": "https://jobs.cliffordchance.com/training-contract-london",
        "eligibility_note": "Open to penultimate/final-year students and graduates applying directly - no vacation scheme required.",
    },
    ("Gowling WLG", "Birmingham Direct Training Contract"): {
        "opens_date": "2026-10-01",
        "opens_confirmed": False,
        "apply_link": "https://ehjc.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_17/requisitions",
        "eligibility_note": "Open to graduates of any degree applying directly - no vacation scheme required.",
    },
    ("Gowling WLG", "Birmingham Real Estate Training Contract"): {
        "opens_date": "2026-10-01",
        "opens_confirmed": False,
        "apply_link": "https://ehjc.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_17/requisitions",
        "eligibility_note": "Open to graduates of any degree applying directly - no vacation scheme required.",
    },
    ("Gowling WLG", "London Direct Training Contract"): {
        "opens_date": "2026-10-01",
        "opens_confirmed": False,
        "apply_link": "https://ehjc.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_17/requisitions",
        "eligibility_note": "Open to graduates of any degree applying directly - no vacation scheme required.",
    },
    ("Gowling WLG", "London Real Estate Training Contract"): {
        "opens_date": "2026-10-01",
        "opens_confirmed": False,
        "apply_link": "https://ehjc.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_17/requisitions",
        "eligibility_note": "Open to graduates of any degree applying directly - no vacation scheme required.",
    },
    ("Foot Anstey", "Northern Ireland Training Contract"): {
        "opens_date": "2026-09-15",
        "opens_confirmed": False,
        "apply_link": "https://www.footanstey.com/careers/early-careers/training-contracts/",
        "eligibility_note": "Open to final-year students or those who've already graduated - no vacation scheme required.",
    },
    ("Lewis Silkin", "Belfast Training Contract"): {
        "opens_date": "2026-10-21",
        "opens_confirmed": True,
        "apply_link": "https://www.lewissilkin.com/en/life-at-ls/careers/trainees",
        "eligibility_note": "Open to all graduates, all final-year non-law students and all penultimate-year law students - no vacation scheme required.",
    },
    ("Lewis Silkin", "Cardiff Training Contract"): {
        "opens_date": "2026-10-21",
        "opens_confirmed": True,
        "apply_link": "https://www.lewissilkin.com/en/life-at-ls/careers/trainees",
        "eligibility_note": "Open to all graduates, all final-year non-law students and all penultimate-year law students - no vacation scheme required.",
    },
    ("Lewis Silkin", "London Training Contract"): {
        "opens_date": "2026-10-21",
        "opens_confirmed": True,
        "apply_link": "https://apply.candidats.io/ac73d7b3-9468-457a-8279-6910d8e13fd0",
        "eligibility_note": "Open to all graduates, all final-year non-law students and all penultimate-year law students - no vacation scheme required.",
    },
    ("Lewis Silkin", "Manchester Training Contract"): {
        "opens_date": "2026-10-21",
        "opens_confirmed": True,
        "apply_link": "https://www.lewissilkin.com/en/life-at-ls/careers/trainees",
        "eligibility_note": "Open to all graduates, all final-year non-law students and all penultimate-year law students - no vacation scheme required.",
    },
    ("Greenberg Traurig", "2029 Training Contract"): {
        "opens_date": "2026-09-01",
        "opens_confirmed": True,
        "apply_link": "https://gtlaw.wd1.myworkdayjobs.com/GTLAW/job/London/XMLNAME-2029-Training-Contract_JR202601534",
        "eligibility_note": "Greenberg Traurig runs no vacation scheme at all - every training contract application is direct, including from graduates.",
    },
    ("Kirkland & Ellis", "Training Contract"): {
        "opens_date": "2026-10-01",
        "opens_confirmed": False,
        "apply_link": "https://ukgraduate.kirkland.com/your-application/",
        "eligibility_note": "Open to law students from penultimate year onwards, non-law students from final year onwards, and graduates - no vacation scheme required.",
    },
    ("Bristows", "Training Contract"): {
        "opens_date": "2026-09-05",
        "opens_confirmed": False,
        "apply_link": "https://www.apply4law.com/bristows/",
        "eligibility_note": "Open to penultimate-year law students, all final-year students and graduates applying directly - no vacation scheme required.",
    },
    ("Forsters", "Direct Training Contract 2029"): {
        "opens_date": "2026-09-03",
        "opens_confirmed": True,
        "apply_link": "https://forsters.grad.allhires.com/app/",
        "eligibility_note": "Direct route for anyone unable to attend the vacation scheme, incl. graduates - a vacation scheme is not required first.",
    },
    ("Trowers & Hamlins", "Direct Training Contract"): {
        "opens_date": "2026-10-01",
        "opens_confirmed": True,
        "apply_link": "https://trowers.grad.allhires.com/?mt=T2UYWEVT56",
        "eligibility_note": "Open to penultimate/final-year students, graduates and career changers applying directly - no vacation scheme required.",
    },
    ("Gibson Dunn", "London Direct Training Contract"): {
        "opens_date": "2026-09-01",
        "opens_confirmed": False,
        "apply_link": "https://www.apply4law.com/GibsonDunn/",
        "eligibility_note": "Vacation scheme is encouraged first but not required - the direct training contract route is open to graduates too.",
    },
    ("Gibson Dunn", "UAE Training Contract"): {
        "opens_date": "2026-09-01",
        "opens_confirmed": False,
        "apply_link": "https://gibsondunn.grad.allhires.com/app/",
        "eligibility_note": "Open to final-year students, career changers and recent graduates applying directly - no vacation scheme required.",
    },
    # --- Excluded: confirmed to require this firm's own vacation scheme first,
    # or otherwise not open to direct graduate applicants. Kept here (rather
    # than just omitted) so it's obvious on inspection that these were
    # checked, not missed. ---
    ("Gateley", "Training Contract"): None,  # recruits all trainees from its own summer vacation placements
    ("Davis Polk & Wardwell", "Training Programme"): None,  # filled exclusively via the vacation scheme
}


def fetch_rows():
    resp = requests.get(SOURCE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return soup.select("li.c-table-row")


def parse_deadline(label, today):
    label = (label or "").strip()
    if not label:
        return None
    if label.lower() == "today":
        return today
    if label.lower() == "tomorrow":
        return today + timedelta_days_compat(1)
    try:
        return datetime.strptime(label, "%d/%m/%Y").date()
    except ValueError:
        return None


def timedelta_days_compat(n):
    from datetime import timedelta
    return timedelta(days=n)


def build_entries():
    today = date.today()
    rows = fetch_rows()
    entries = []
    needs_review = []

    for row in rows:
        date_el = row.select_one(".c-key-deadlines__date")
        name_el = row.select_one("h3.c-heading .name")
        event_el = row.select_one(".c-key-deadlines__name")

        firm = (name_el.get_text(strip=True) if name_el else "").strip()
        event_name = (event_el.get_text(strip=True) if event_el else "").strip()
        if not firm or not event_name:
            continue
        if not RELEVANT_RE.search(event_name) or EXCLUDE_RE.search(event_name):
            continue

        deadline_label = (date_el.get_text(strip=True) if date_el else "").strip()
        deadline_date = parse_deadline(deadline_label, today)
        if deadline_date is not None and deadline_date < today:
            continue

        key = (firm, event_name)
        if key not in TC_OVERRIDES:
            needs_review.append({"firm": firm, "event_name": event_name, "deadline_label": deadline_label})
            continue

        override = TC_OVERRIDES[key]
        if override is None:
            continue  # confirmed excluded (requires vacation scheme, etc.)

        entries.append({
            "id": f"{firm}|{event_name}".lower().replace(" ", "-"),
            "firm": firm,
            "event_name": event_name,
            "opens_date": override["opens_date"],
            "opens_confirmed": override["opens_confirmed"],
            "closes_date": deadline_date.isoformat() if deadline_date else None,
            "closes_label": deadline_label,
            "apply_link": override["apply_link"],
            "eligibility_note": override["eligibility_note"],
        })

    entries.sort(key=lambda e: (e["closes_date"] is None, e["closes_date"] or ""))
    return entries, needs_review


def main():
    entries, needs_review = build_entries()
    payload = {
        "source": SOURCE_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "note": (
            "Only includes Training Contract listings manually verified as open to "
            "graduates applying directly, without needing to have done that firm's "
            "own vacation scheme first. New listings Legal Cheek starts showing are "
            "held back in needs_review until checked, not guessed at."
        ),
        "events": entries,
        "needs_review": needs_review,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(entries)} verified graduate training contract deadlines to {OUTPUT_PATH}")
    if needs_review:
        print(f"{len(needs_review)} new/unverified entries held back - see needs_review in the output file")


if __name__ == "__main__":
    main()
