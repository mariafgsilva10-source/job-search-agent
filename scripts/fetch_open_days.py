"""
Fetch upcoming law firm Open Days / Insight Days / Insight Schemes from
Legal Cheek's Key Deadlines Calendar (a page that aggregates deadlines
sourced from firms' own recruitment sites, which is also where the
"Apply" link on each entry points).

Output: docs/open_days.json - a flat list of upcoming events, soonest
deadline first, kept in its own file/tab so it never mixes with the
paralegal job search results in docs/data.json.
"""
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.legalcheek.com/key-deadlines-calendar/"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "open_days.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# Only keep events that are actually open days / insight days / insight
# schemes / insight afternoons-evenings - not every early-careers event
# on the page (vacation schemes, workshops, drop-ins, etc.).
RELEVANT_RE = re.compile(r"open day|open evening|insight", re.IGNORECASE)


def fetch_rows():
    resp = requests.get(SOURCE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    rows = soup.select("li.c-table-row")
    return rows


def parse_deadline(label, today):
    label = (label or "").strip()
    if not label:
        return None
    if label.lower() == "today":
        return today
    if label.lower() == "tomorrow":
        return today + timedelta(days=1)
    try:
        return datetime.strptime(label, "%d/%m/%Y").date()
    except ValueError:
        return None


def describe_event(event_name):
    name = (event_name or "").lower()

    if "stem" in name:
        audience = "aimed at STEM students exploring a career in law"
    elif any(k in name for k in ("under-represented", "social mobility", "black", "lgbtq", "myplus", "disab")):
        audience = "focused on supporting candidates from underrepresented or minority groups into the legal profession"
    elif "apprenticeship" in name:
        audience = "for prospective solicitor apprenticeship candidates"
    elif "non-law" in name:
        audience = "aimed at non-law students"
    elif "penultimate" in name:
        audience = "aimed at penultimate-year students"
    elif "first year" in name or "1st year" in name:
        audience = "aimed at first-year students"
    else:
        audience = None

    is_virtual = "virtual" in name or "online" in name

    if "insight" in name:
        kind_desc = "talks, Q&A, and networking with trainees, giving a flavour of life and work at the firm"
    elif "open day" in name or "open evening" in name:
        if is_virtual:
            kind_desc = "a virtual tour and talks introducing the firm and its application process"
        else:
            kind_desc = "an office tour, talks from trainees and partners, and Q&A about the firm and its application process"
    else:
        kind_desc = "activities introducing the firm's early careers programme"

    fmt = "A virtual/online session" if is_virtual else "An in-person event"
    sentence = f"{fmt} featuring {kind_desc}"
    if audience:
        sentence += f", {audience}"
    sentence += "."
    return sentence


def make_id(firm, event_name, deadline_iso, deadline_label):
    key = f"{firm}|{event_name}|{deadline_iso or deadline_label}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


def build_entries():
    today = date.today()
    rows = fetch_rows()
    entries = []

    for row in rows:
        date_el = row.select_one(".c-key-deadlines__date")
        name_el = row.select_one("h3.c-heading .name")
        link_el = row.select_one("h3.c-heading a")
        event_el = row.select_one(".c-key-deadlines__name")
        apply_el = row.select_one("a.c-button")

        firm = (name_el.get_text(strip=True) if name_el else "").strip()
        event_name = (event_el.get_text(strip=True) if event_el else "").strip()
        if not firm or not event_name:
            continue
        if not RELEVANT_RE.search(event_name):
            continue

        deadline_label = (date_el.get_text(strip=True) if date_el else "").strip()
        deadline_date = parse_deadline(deadline_label, today)

        # Drop anything whose deadline has already passed.
        if deadline_date is not None and deadline_date < today:
            continue

        deadline_iso = deadline_date.isoformat() if deadline_date else None
        firm_profile_link = link_el["href"] if link_el and link_el.has_attr("href") else None
        apply_link = apply_el["href"] if apply_el and apply_el.has_attr("href") else firm_profile_link

        entries.append({
            "id": make_id(firm, event_name, deadline_iso, deadline_label),
            "firm": firm,
            "firm_profile_link": firm_profile_link,
            "event_name": event_name,
            "summary": describe_event(event_name),
            "deadline_label": deadline_label,
            "deadline_date": deadline_iso,
            "apply_link": apply_link,
        })

    # Soonest deadline first; entries with an unparsed date go last.
    entries.sort(key=lambda e: (e["deadline_date"] is None, e["deadline_date"] or ""))
    return entries


def main():
    entries = build_entries()
    payload = {
        "source": SOURCE_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "events": entries,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(entries)} open day / insight day events to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
