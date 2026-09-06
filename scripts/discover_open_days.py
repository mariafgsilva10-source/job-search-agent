"""
Daily sweep for LONDON law firm open days / insight events that Legal Cheek's
key-deadlines calendar hasn't listed.

Why this exists: fetch_open_days.py is only as complete as Legal Cheek's
calendar. Goodwin's "In-Person Open Afternoon" (Nov 2026) was live on the
firm's own booking system and never appeared on Legal Cheek at all, so the
pipeline could never have surfaced it. Firms announce events on their own
application portals days or weeks before an aggregator picks them up - if
they pick them up at all.

So this script goes looking directly. Every morning it re-reads the
application portals and early-careers/events pages that London firms
actually publish events on, pulls anything that reads like an open day or
insight event, and diffs it against what it saw yesterday. Whatever is new
lands in docs/discovered_events.json as an UNVERIFIED LEAD.

Leads are deliberately NOT promoted onto the dashboard automatically. The
whole open-days pipeline is fail-closed: an event only reaches Maria once
someone has opened the firm's own page and confirmed the dates, the
eligibility and the apply link. A lead here means "worth a look today", and
the daily verification pass is what turns a confirmed one into a
MANUAL_EVENTS entry in fetch_open_days.py.

Scope matches the rest of the pipeline: London law firms only. Barristers'
chambers are excluded (pupillage is a different career route to a training
contract), as are listings whose title names a non-London office.

Outputs:
  docs/discovered_events.json          - leads, newest first
  data/seen_open_day_listings.json     - fingerprint -> first-seen date
"""
import hashlib
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "docs" / "discovered_events.json"
SEEN_PATH = ROOT / "data" / "seen_open_day_listings.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}
TIMEOUT = 25
PAUSE_BETWEEN_REQUESTS = 1.0   # be a polite visitor
MAX_HITS_PER_SOURCE = 40

# Sources are the places London firms actually publish early-careers events:
# shared application platforms first (candidats.io, allhires, apply4law,
# icims - these carry the real per-event booking links), then firms' own
# events pages. Every firm here recruits into a London office.
#
# URLs verified 2026-09-06. A few firms render their event list with
# JavaScript (Travers Smith, Norton Rose Fulbright) or sit behind bot
# protection (White & Case, Farrer & Co, Charles Russell Speechlys,
# Fieldfisher), so those return little or fail outright - they are recorded
# in the output's "failures" list rather than silently ignored, and the
# daily verification pass covers them by search instead.
SOURCES = [
    # --- candidats.io firm portals ---
    {"firm": "Goodwin", "url": "https://goodwinlaw.app.candidats.io/roles"},
    {"firm": "Paul, Weiss", "url": "https://pweuropecareers.app.candidats.io/roles"},
    {"firm": "Weil Gotshal & Manges", "url": "https://weil.app.candidats.io/roles"},
    {"firm": "Bird & Bird", "url": "https://twobirds.app.candidats.io/roles"},
    {"firm": "Dechert", "url": "https://dechert.app.candidats.io/roles"},
    {"firm": "Wedlake Bell", "url": "https://wedlakebell.app.candidats.io/roles"},
    {"firm": "Mills & Reeve", "url": "https://millsandreeve.app.candidats.io/roles"},
    {"firm": "Macfarlanes", "url": "https://macfarlanes.app.candidats.io/roles"},
    {"firm": "Hogan Lovells Cadwalader", "url": "https://ukearlycareers.hlc.com/"},

    # --- allhires graduate portals ---
    {"firm": "Forsters", "url": "https://forsters.grad.allhires.com/app/"},
    {"firm": "Payne Hicks Beach", "url": "https://phb.grad.allhires.com/app/"},
    {"firm": "Debevoise & Plimpton", "url": "https://debevoise.grad.allhires.com/app/"},
    {"firm": "Eversheds Sutherland", "url": "https://eversheds-sutherland.grad.allhires.com/app/"},
    {"firm": "Mayer Brown", "url": "https://mayerbrown.grad.allhires.com/app/"},

    # --- apply4law portals ---
    {"firm": "Milbank", "url": "https://www.apply4law.com/milbank/"},
    {"firm": "Trowers & Hamlins", "url": "https://www.apply4law.com/Trowers/"},
    {"firm": "Gibson Dunn", "url": "https://www.apply4law.com/GibsonDunn/"},
    {"firm": "Morgan Lewis", "url": "https://www.apply4law.com/morganlewis/"},

    # --- firms' own early-careers / events pages ---
    {"firm": "Simpson Thacher & Bartlett", "url": "https://ukearlycareers.stblaw.com/our-offer/events/"},
    {"firm": "Herbert Smith Freehills Kramer", "url": "https://careers.hsfkramer.com/global/en/uk/early-careers/open-days"},
    {"firm": "Jones Day", "url": "https://www.jonesday.com/en/careers/locations/united-kingdom?tab=events"},
    {"firm": "Slaughter and May", "url": "https://www.slaughterandmay.com/careers/early-careers/apply/"},
    {"firm": "Osborne Clarke", "url": "https://join.osborneclarke.com/insight-scheme"},
    {"firm": "Dentons", "url": "https://challengers.dentons.com/uk-trainees/opportunities/open-days/"},
    {"firm": "Withers", "url": "https://www.witherscareers.com/"},
    {"firm": "TLT", "url": "https://www.tlt.com/careers/early-careers/"},
    {"firm": "Fieldfisher", "url": "https://www.fieldfisher.com/en/careers/earlycareers/future-lawyer-programmes"},
    {"firm": "Davis Polk & Wardwell", "url": "https://www.davispolk.com/careers/law-students-trainees/london"},
    {"firm": "Willkie Farr & Gallagher", "url": "https://www.willkie.com/careers/legal-professional/early-careers/discover-more-and-apply/united-kingdom"},
    {"firm": "Freshfields", "url": "https://www.freshfields.com/en/your-career/united-kingdom/early-careers/"},
    {"firm": "BCLP", "url": "https://trainee.bclplaw.com/meet-us"},
    {"firm": "Bristows", "url": "https://www.bristows.com/careers/trainees/what-we-offer/workshops/"},
    {"firm": "RPC", "url": "https://www.rpclegal.com/careers/early-talent/uk/meet-us-uk/"},

    # --- major London firms not currently represented in the tracker ---
    {"firm": "Clifford Chance", "url": "https://jobs.cliffordchance.com/meet-us-london"},
    {"firm": "Linklaters", "url": "https://careers.linklaters.com/en/early-careers/uk/events"},
    {"firm": "A&O Shearman", "url": "https://careers.aoshearman.com/en/early-careers-london"},
    {"firm": "Ashurst Perkins Coie", "url": "https://www.ashurstperkinscoie.com/en/careers/students-and-graduates/uk-london-training-contract/"},
    {"firm": "Travers Smith", "url": "https://traverssmithhires.app.candidats.io/events"},
    {"firm": "Kirkland & Ellis", "url": "https://ukgraduate.kirkland.com/events"},
    {"firm": "Sidley Austin", "url": "https://www.sidleycareers.com/en/europe/london-trainee-solicitor-programme"},
    {"firm": "White & Case", "url": "https://www.whitecase.com/careers/locations/united-kingdom/london"},
    {"firm": "Baker McKenzie", "url": "https://uk-graduates.bakermckenzie.com/events/"},
    {"firm": "Norton Rose Fulbright", "url": "https://www.nortonrosefulbright.com/en-gb/graduates/opportunities"},
    {"firm": "Pinsent Masons", "url": "https://www.pinsentmasons.com/careers/early-talent/events"},
    {"firm": "Charles Russell Speechlys", "url": "https://www.charlesrussellspeechlys.com/en/careers/early-careers/"},
    {"firm": "Taylor Wessing", "url": "https://united-kingdom.taylorwessing.com/en/careers/graduates"},
    {"firm": "Stephenson Harwood", "url": "https://www.shlegal.com/careers/early-careers"},
    {"firm": "Farrer & Co", "url": "https://www.farrer.co.uk/careers/early-careers/"},
    {"firm": "Burges Salmon", "url": "https://www.burges-salmon.com/join-us/emerging-talent/"},
    {"firm": "Addleshaw Goddard", "url": "https://earlycareers.addleshawgoddard.com/careers/insight-day/"},
    {"firm": "Simmons & Simmons", "url": "https://www.simmons-simmons.com/en/careers/early-careers"},
    {"firm": "Latham & Watkins", "url": "https://uk-earlyassociatecareers-lw.icims.com/jobs"},
]

# What counts as an open day / insight event.
OPEN_DAY_RE = re.compile(
    r"open day|open evening|open afternoon|open morning|"
    r"insight (day|evening|afternoon|event|scheme|session|programme|program|series)|"
    r"insight into|insights? (afternoon|evening|q&a)|"
    r"discovery day|discover .{0,20}day|first year (scheme|programme|insight)|"
    r"campus (day|event)|meet (us|our|the) (firm|team|trainees|graduate)|"
    r"law fair|careers (evening|open)",
    re.IGNORECASE,
)

# Things that look like an event but aren't the thing we want.
NOT_WANTED_RE = re.compile(
    r"vacation scheme|training contract application|work placement application|"
    r"apprentice|apprenticeship|paralegal|legal secretary|business services|"
    r"lateral|associate|partner|privacy|cookie|terms|accessibility|sitemap",
    re.IGNORECASE,
)

CHAMBERS_RE = re.compile(r"\bchambers\b|\bpupillage\b|\bbarrister|\binns? of court\b", re.IGNORECASE)

NON_LONDON_PLACE_RE = re.compile(
    r"\b(birmingham|manchester|leeds|bristol|exeter|newcastle|liverpool|"
    r"scotland|glasgow|edinburgh|aberdeen|dublin|belfast|cardiff|"
    r"nottingham|sheffield|cambridge|oxford|guildford|cheltenham|"
    r"southampton|middle east|dubai|abu dhabi|hong kong|singapore|"
    r"new york|washington|paris|brussels|amsterdam|frankfurt|munich|"
    r"madrid|milan|tokyo|sydney|toronto|riyadh|doha)\b",
    re.IGNORECASE,
)
LONDON_RE = re.compile(r"\blondon\b", re.IGNORECASE)


def fingerprint(firm, title, url):
    raw = f"{firm}|{title.strip().lower()}|{url.strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def is_relevant(title, firm=""):
    """Keyword gate: reads like an open day, isn't a chambers event, isn't
    pinned to a non-London office. Every entry in SOURCES is a law firm, but
    the firm name is checked too so adding a chambers URL by mistake can't
    quietly put pupillage events in front of Maria."""
    text = " ".join(title.split())
    if len(text) < 6 or len(text) > 160:
        return False
    if not OPEN_DAY_RE.search(text):
        return False
    if NOT_WANTED_RE.search(text):
        return False
    if CHAMBERS_RE.search(text) or CHAMBERS_RE.search(firm):
        return False
    if NON_LONDON_PLACE_RE.search(text) and not LONDON_RE.search(text):
        return False
    return True


def extract_listings(html, page_url, firm):
    """Pull anything on the page that reads like an open-day listing.

    Deliberately structure-agnostic: these pages range from React job
    boards to hand-built HTML, and they get redesigned without warning. We
    scan links and headings for the keywords and let the verification pass
    sort out precision - a lead that turns out to be nothing costs a
    minute, a missed event costs a deadline.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    hits = {}

    for a in soup.find_all("a", href=True):
        title = a.get_text(" ", strip=True)
        if not is_relevant(title, firm):
            continue
        href = urljoin(page_url, a["href"])
        if not href.lower().startswith(("http://", "https://")):
            continue
        hits.setdefault(fingerprint(firm, title, href), {"title": title, "url": href})
        if len(hits) >= MAX_HITS_PER_SOURCE:
            return list(hits.values())

    # Headings often carry the event name with the booking link nearby.
    for h in soup.find_all(["h1", "h2", "h3", "h4", "li"]):
        title = h.get_text(" ", strip=True)
        if not is_relevant(title, firm):
            continue
        link = h.find("a", href=True)
        href = urljoin(page_url, link["href"]) if link else page_url
        hits.setdefault(fingerprint(firm, title, href), {"title": title, "url": href})
        if len(hits) >= MAX_HITS_PER_SOURCE:
            break

    return list(hits.values())


def load_seen():
    if SEEN_PATH.exists():
        try:
            return json.loads(SEEN_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def sweep():
    today = date.today()
    today_iso = today.isoformat()
    seen = load_seen()
    first_run = not seen

    leads = []
    failures = []

    for source in SOURCES:
        firm, url = source["firm"], source["url"]
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            listings = extract_listings(resp.text, url, firm)
        except Exception as exc:                      # noqa: BLE001 - one bad source must not stop the sweep
            failures.append({"firm": firm, "url": url, "error": f"{type(exc).__name__}: {exc}"[:200]})
            continue
        finally:
            time.sleep(PAUSE_BETWEEN_REQUESTS)

        for item in listings:
            fp = fingerprint(firm, item["title"], item["url"])
            first_seen = seen.get(fp)
            if first_seen is None:
                seen[fp] = today_iso
                first_seen = today_iso
            leads.append({
                "id": fp,
                "firm": firm,
                "title": item["title"],
                "url": item["url"],
                "source_page": url,
                "first_seen": first_seen,
                # On the very first run everything is technically "new",
                # which would be a wall of noise - so nothing counts as new
                # until we have a baseline to compare against.
                "is_new": (not first_run) and first_seen == today_iso,
                "status": "unverified",
            })

    return leads, failures, seen, first_run


def main():
    leads, failures, seen, first_run = sweep()

    cutoff = (date.today() - timedelta(days=7)).isoformat()
    new_leads = [l for l in leads if l["is_new"]]
    recent = [l for l in leads if l["first_seen"] >= cutoff]

    leads.sort(key=lambda l: (not l["is_new"], l["first_seen"], l["firm"]), reverse=False)
    leads.sort(key=lambda l: l["is_new"], reverse=True)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "note": (
            "Unverified leads from a daily sweep of London law firms' own "
            "application portals and events pages - the places firms announce "
            "open days before (or instead of) Legal Cheek listing them. Nothing "
            "here has been checked yet: a lead only reaches the Open Days tab "
            "once its dates, eligibility and apply link have been confirmed on "
            "the firm's own site."
        ),
        "first_run": first_run,
        "counts": {
            "sources_checked": len(SOURCES),
            "sources_failed": len(failures),
            "leads_total": len(leads),
            "new_today": len(new_leads),
            "new_last_7_days": len(recent),
        },
        "new_today": new_leads,
        "leads": leads,
        "failures": failures,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(seen, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Swept {len(SOURCES)} sources ({len(failures)} unreachable)")
    print(f"{len(leads)} open-day-ish listings found, {len(new_leads)} new since yesterday")
    if first_run:
        print("First run - baseline recorded, nothing flagged as new")
    for lead in new_leads:
        print(f"  NEW: {lead['firm']} - {lead['title']}")


if __name__ == "__main__":
    main()
