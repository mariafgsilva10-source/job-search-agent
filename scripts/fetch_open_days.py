"""
Fetch upcoming law firm Open Days / Insight Days / Insight Schemes from
Legal Cheek's Key Deadlines Calendar (a page that aggregates deadlines
sourced from firms' own recruitment sites).

Like fetch_tc_deadlines.py, this is NOT a plain scrape-and-publish. Legal
Cheek's calendar only gives a closing date - no opening date and no direct
"apply" URL for the specific event (Legal Cheek's own "Apply" button mostly
just points back at the firm's general profile page, not the event itself).

So this script scrapes Legal Cheek for the closing date (which stays fresh
automatically) and cross-references OPEN_DAY_OVERRIDES below - a manually
researched, per-entry record of: opening date (where the firm publishes
one) and the most specific "register/apply for this event" URL findable on
the firm's own site - confirmed by actually reading each firm's own early
careers pages, 2026-09-04.

Any Open Day / Insight Day entry Legal Cheek starts listing that ISN'T in
OPEN_DAY_OVERRIDES is left OUT of docs/open_days.json rather than shown with
a guessed opening date or a generic search-engine link, and is instead
written to the "needs_review" list in the same file. This mirrors
fetch_tc_deadlines.py's fail-closed design: better to leave an event out
for a day than show Maria an opening date or "apply" link that turns out to
be wrong or, worse, a stale/expired listing from a prior year's cycle.

FOUR RELEVANCE FILTERS are applied on top of all that, all per Maria's
brief. She is a LAW GRADUATE going for a solicitor training contract, based
near London, so an event only reaches her if she could actually apply to it:

  1. LAW FIRMS ONLY - barristers' chambers are dropped entirely. Chambers
     offer pupillage, not training contracts, so their open days are for a
     different career route.
  2. LONDON ONLY - events tied to a firm's non-London office (Birmingham,
     Manchester, Leeds, Bristol, Exeter, Newcastle, Liverpool, Scotland,
     Dublin, overseas) are dropped. Virtual/online sessions are kept
     regardless of which office runs them, since she can attend from
     anywhere, as are multi-office series that include London.
  3. NO SOLICITOR APPRENTICESHIPS - that route is a school-leaver /
     non-graduate entry path (Legal Cheek suffixes the firm name
     "- solicitor apprenticeship"). She has a degree, so it is closed to her.
  4. GRADUATE-ELIGIBLE ONLY - first-year and second-year insight schemes are
     aimed at current undergraduates. EVENT_AUDIENCE overrides the title test
     where a firm's wording is misleading, e.g. Davis Polk's "Penultimate Year
     & Postgraduate Insight Day" explicitly includes postgraduates and is kept.

Every filter is a flag (EXCLUDE_CHAMBERS / LONDON_ONLY /
EXCLUDE_APPRENTICESHIPS / GRADUATES_ONLY) and rejected events keep their
researched override data, so widening the net later is a one-line change
rather than a re-research job.

Output: docs/open_days.json
"""
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

APPRENTICESHIP_NOTE = (
    "This is the firm's solicitor apprenticeship route (a school-leaver / "
    "non-graduate entry path funded alongside a law degree and the SQE) - "
    "not the graduate training contract route."
)

# --- Relevance filters (see module docstring) ---
LONDON_ONLY = True
EXCLUDE_CHAMBERS = True
EXCLUDE_APPRENTICESHIPS = True
GRADUATES_ONLY = True

# Maria has finished her law degree. A "first year insight scheme" is aimed at
# undergraduates two or three years behind her and she cannot apply, so those
# are filtered out rather than shown as noise. Titles are explicit enough for
# this to be a safe title-level test; EVENT_AUDIENCE below overrides it for the
# handful where the wording is misleading.
NOT_FOR_GRADUATES_RE = re.compile(
    r"\bfirst[- ]?years?\b|\b1st[- ]?year\b|\bsecond[- ]?year\b|"
    r"\bfreshers?\b|\bpre[- ]?penultimate\b|\bschool[- ]leaver\b|\bsixth[- ]form\b",
    re.IGNORECASE,
)

# Overrides for events whose title implies a year restriction that doesn't
# actually shut a graduate out (or vice versa). "graduates" = she can apply.
EVENT_AUDIENCE = {
    # Explicitly open to postgraduates as well as penultimate-year students,
    # so a graduate is in scope - the firm's own wording, not an assumption.
    ("Davis Polk & Wardwell", "Penultimate Year & Postgraduate Insight Day"): "graduates",
}

# Shown on the card so Maria can see why an event survived the filter when its
# name still mentions a year group.
AUDIENCE_NOTES = {
    ("Davis Polk & Wardwell", "Penultimate Year & Postgraduate Insight Day"): (
        "Open to penultimate-year students and postgraduates - the firm's own "
        "wording. Worth confirming you qualify as a postgraduate for their purposes."
    ),
}

# Barristers' chambers offer pupillage, not training contracts, so their
# open days are for a different career route entirely. Most are caught by
# the regex; the set covers chambers whose name doesn't contain a giveaway
# word (Serle Court, Forum Chambers-style names, Inns of Court, etc.).
KNOWN_CHAMBERS = {
    "Serle Court",
    "Brick Court Chambers",
    "5 Essex Chambers",
    "Tanfield Chambers",
    "Monckton Chambers",
    "Express Chambers",
    # Added 2026-10-05: both are barristers' chambers whose names don't
    # contain a giveaway word, so the regex missed them and they were
    # surfacing in needs_review (4 Stone Buildings - Chancery/commercial
    # chambers; 3VB = 3 Verulam Buildings - commercial/competition
    # chambers). Pupillage, not a training contract - wrong career route.
    "4 Stone Buildings",
    "3VB",
}
CHAMBERS_RE = re.compile(r"\bchambers\b|\bpupillage\b|\bbarrister", re.IGNORECASE)

# A non-London UK/overseas city named in the event title means the event is
# tied to that office. "London" appearing anywhere wins, so a listing like
# "London & Manchester Open Day" is kept.
NON_LONDON_PLACE_RE = re.compile(
    r"\b(birmingham|manchester|leeds|bristol|exeter|newcastle|liverpool|"
    r"scotland|glasgow|edinburgh|aberdeen|dublin|belfast|cardiff|"
    r"nottingham|sheffield|cambridge|oxford|guildford|cheltenham|"
    r"southampton|middle east|dubai|abu dhabi|hong kong|singapore|"
    r"new york|paris|brussels|amsterdam|frankfurt|madrid|milan)\b",
    re.IGNORECASE,
)
LONDON_RE = re.compile(r"\blondon\b", re.IGNORECASE)

# Locations kept when LONDON_ONLY is on. "Virtual" sessions are
# location-independent; the multi-office value covers series a firm runs
# across several offices, London included.
LONDON_RELEVANT = {"London", "Virtual", "Multiple UK offices (incl. London)"}

# Where each verified event actually takes place, established alongside the
# OPEN_DAY_OVERRIDES research. Keyed on (firm, event_name) because a firm
# that repeats an event across the cycle runs every instance at the same
# office. An event in OPEN_DAY_OVERRIDES but missing here is treated as
# unknown location and held back, same fail-closed principle as the rest of
# this script.
EVENT_LOCATIONS = {
    ("Ashfords", "Bristol First Year Insight Day"): "Bristol",
    ("Ashfords", "Exeter First Year Insight Day"): "Exeter",
    ("Baker McKenzie", "General Open Day"): "London",
    ("Baker McKenzie", "Women’s Open Day"): "London",
    ("Baker McKenzie", "Opportunity Open Day"): "London",
    ("Baker McKenzie", "BakerEthnicity Open Day"): "London",
    ("Baker McKenzie", "Pride at Baker McKenzie Open Day"): "London",
    ("Baker McKenzie", "EmployAbility Open Day"): "London",
    ("BCLP", "Open Day"): "London",
    ("Bird & Bird", "Trainee Solicitor Open Day"): "London",
    ("Bristows — solicitor apprenticeship", "Solicitor Apprenticeship Open Evening"): "London",
    ("Charles Russell Speechlys", "London Open Day"): "London",
    ("Charles Russell Speechlys", "Virtual Open Day"): "Virtual",
    ("Clifford Chance", "London Insight Day"): "London",
    ("Davis Polk & Wardwell", "First Year Insight Day"): "London",
    ("Davis Polk & Wardwell", "Penultimate Year & Postgraduate Insight Day"): "London",
    ("Debevoise & Plimpton", "Open Day"): "London",
    ("Dechert", "First Year Insight Event"): "London",
    ("Dentons", "Open Day (London)"): "London",
    ("Dentons", "Open Day (Scotland)"): "Scotland",
    ("Eversheds Sutherland", "First Year Law/Second Year Non-Law Open Day"): "Multiple UK offices (incl. London)",
    ("Eversheds Sutherland", "Graduate Insight Evenings"): "Multiple UK offices (incl. London)",
    ("Fieldfisher", "Pathways to Practice Scheme (First year insight scheme)"): "London",
    ("Forsters", "First Year Insight Day"): "London",
    ("Forsters", "Open Day 1"): "London",
    ("Forsters", "Open Day 2"): "London",
    ("Forsters — solicitor apprenticeship", "Apprenticeship Insights Afternoon (Online)"): "Virtual",
    ("Forsters — solicitor apprenticeship", "Early Careers Insights Q&A"): "London",
    ("Forsters — solicitor apprenticeship", "Open day (in person)"): "London",
    ("Freshfields", "First Years Insight Scheme"): "London",
    ("Gibson Dunn", "First Year Insight Day (In-person)"): "London",
    ("Gibson Dunn", "First Year Insight Day (Virtual)"): "Virtual",
    ("Goodwin", "In-Person Open Afternoon"): "London",
    ("Goodwin", "Insight into Applications – Demystifying the Application Process"): "London",
    ("Goodwin", "Insight into the Trainee Experience: Meet Our Trainees and Q&A"): "London",
    ("Herbert Smith Freehills Kramer", "Black Talent Open Day"): "London",
    ("Herbert Smith Freehills Kramer", "Disputes Open Day"): "London",
    ("Herbert Smith Freehills Kramer", "IP Open Day"): "London",
    ("Herbert Smith Freehills Kramer", "IRIS Open Day"): "London",
    ("Herbert Smith Freehills Kramer", "MyPlus Open Day"): "London",
    ("Herbert Smith Freehills Kramer", "Social Mobility Open Day"): "London",
    ("Hill Dickinson", "Training Contract Open Evening"): "London",
    ("Hogan Lovells Cadwalader", "First Year Insight Scheme"): "London",
    ("Jones Day", "Open Evening 2"): "London",
    ("Latham & Watkins", "London Black Lawyers Group Open Day 2026"): "London",
    ("Latham & Watkins", "London LGBTQ+ Lawyers Group Open Day 2026"): "London",
    ("Latham & Watkins", "London Open Day 2026 (November)"): "London",
    ("Latham & Watkins", "London Open Day 2026 (October)"): "London",
    ("Macfarlanes", "First Year Insight Scheme"): "London",
    ("Mayer Brown", "London First Year Virtual Insight Session"): "Virtual",
    ("Milbank", "Open Day"): "London",
    ("Milbank", "Open Day (Leveraged Finance track)"): "London",
    ("Mills & Reeve", "In person Insight Event (Birmingham)"): "Birmingham",
    ("Mills & Reeve", "In person Insight Event (Leeds)"): "Leeds",
    ("Mills & Reeve", "In person Insight Event (Manchester)"): "Manchester",
    ("Mills & Reeve", "Virtual Insight Event"): "Virtual",
    ("Osborne Clarke", "Insight Scheme"): "Multiple UK offices (incl. London)",
    ("Paul, Weiss", "November Insight Afternoon"): "London",
    ("Paul, Weiss", "September Insight Afternoon"): "London",
    ("Payne Hicks Beach", "Open Day 1"): "London",
    ("Payne Hicks Beach", "Open Day 2"): "London",
    ("RPC", "Bristol Insight Day"): "Bristol",
    ("RPC", "London Insight Day"): "London",
    ("Squire Patton Boggs", "Open Day (London)"): "London",
    ("Squire Patton Boggs", "Open Day (Online)"): "Virtual",
    ("RPC — solicitor apprenticeship", "Solicitor Apprenticeship Virtual Insight Evening"): "Virtual",
    ("Simmons & Simmons", "Spring Insight Scheme"): "London",
    ("Simpson Thacher & Bartlett", "October Open Day"): "London",
    ("Slaughter and May", "Spring Open Day 1"): "London",
    ("Slaughter and May", "Spring Open Day 2"): "London",
    ("Slaughter and May", "Spring Open Day 3"): "London",
    ("TLT", "Virtual Open Evening"): "Virtual",
    ("Trowers & Hamlins", "Birmingham Office Graduate Insight Day"): "Birmingham",
    ("Trowers & Hamlins", "Exeter Office Graduate Insight Day"): "Exeter",
    ("Trowers & Hamlins", "London Office Graduate Insight Day"): "London",
    ("Trowers & Hamlins", "Manchester Office Graduate Insight Day"): "Manchester",
    ("Wedlake Bell", "Open Day"): "London",
    ("White & Case", "Open Days 2026"): "London",
    ("White & Case", "STEM Open Day 2026"): "London",
    ("Weightmans — solicitor apprenticeship", "Birmingham Open Evening"): "Birmingham",
    ("Weightmans — solicitor apprenticeship", "Leeds Open Evening"): "Leeds",
    ("Weightmans — solicitor apprenticeship", "Liverpool Open Evening"): "Liverpool",
    ("Weightmans — solicitor apprenticeship", "Manchester Open Evening"): "Manchester",
    ("Weightmans — solicitor apprenticeship", "Newcastle Open Evening"): "Newcastle",
    ("Weightmans — solicitor apprenticeship", "Online Open Evening"): "Virtual",
    ("Weil Gotshal & Manges", "Insight Day 1"): "London",
    ("Weil Gotshal & Manges", "Insight Day 2"): "London",
    ("Weil Gotshal & Manges", "Insight Day 3"): "London",
    ("Willkie Farr & Gallagher", "First Year Spring Insight Day"): "London",
    ("Withers", "Open Day"): "London",
    # Added 2026-10-05, confirmed directly on each firm's own site - see the
    # matching OPEN_DAY_OVERRIDES comment below for the research.
    ("Mishcon de Reya", "Undergraduate Open Day (In Person)"): "London",
    ("Mishcon de Reya", "Undergraduate Open Day (Virtual)"): "Virtual",
    ("Mishcon de Reya", "Disability Open Day (In Person)"): "London",
    ("Mishcon de Reya", "Disability Open Day (Virtual)"): "Virtual",
    ("Mishcon de Reya", "STEM Open Day (In Person)"): "London",
    ("Akin", "Ask Akin Open Day (Virtual)"): "Virtual",
    ("Kingsley Napley", "Kingsley Napley In-person Open Day"): "London",
    ("Kingsley Napley", "Kingsley Napley Virtual Open Day"): "Virtual",
}


def is_chambers(firm, event_name):
    """True for barristers' chambers - a different career route to a
    solicitor training contract, so filtered out entirely."""
    if firm in KNOWN_CHAMBERS:
        return True
    return bool(CHAMBERS_RE.search(firm) or CHAMBERS_RE.search(event_name))


def is_graduate_eligible(firm, event_name):
    """False for schemes aimed at a year group Maria has already passed."""
    override = EVENT_AUDIENCE.get((firm, event_name))
    if override is not None:
        return override == "graduates"
    return not NOT_FOR_GRADUATES_RE.search(event_name)


def looks_non_london(firm, event_name):
    """Cheap title-based check, used for listings we haven't researched yet
    (needs_review) where no EVENT_LOCATIONS entry exists. A title naming
    London anywhere wins over a named regional office."""
    if LONDON_RE.search(event_name) or LONDON_RE.search(firm):
        return False
    return bool(NON_LONDON_PLACE_RE.search(event_name))

# Manually verified against each firm's own early-careers pages, 2026-09-04.
# Key is (firm, event_name, deadline_label) exactly as Legal Cheek shows it -
# deadline_label (not just firm+event_name) is part of the key because a
# handful of firms repeat the same event_name multiple times in one cycle
# with different dates (e.g. Goodwin's monthly webinar series, Davis Polk's
# two Penultimate Year sessions) - keying on the closing date too keeps each
# instance's own opening date/apply link correctly matched instead of
# collapsing them together. "opens_confirmed" False means no explicit
# "applications open on X" date is published anywhere on the firm's own
# site - opens_date is then either None (genuinely unknown) or a firm-stated
# approximate/pattern-based date not phrased as a hard commitment. Note this
# also means an override needs re-verifying each time a firm's cycle shifts
# to new closing dates - which is deliberate, not a bug: better to have a
# fresh cycle's events sit in needs_review for a day than silently carry
# over a stale opening date or link from the old cycle.
OPEN_DAY_OVERRIDES = {
    ("Paul, Weiss", "September Insight Afternoon", "07/09/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://pweuropecareers.app.candidats.io/roles",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Simpson Thacher & Bartlett", "October Open Day", "13/09/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://ukearlycareers.stblaw.com/our-offer/events/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Goodwin", "Insight into Applications – Demystifying the Application Process", "18/09/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://goodwinlaw.app.candidats.io/event/3cae80ec-5b90-4a54-a960-c4040ec066e5",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("BCLP", "Open Day", "25/09/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://apply.candidats.io/4043257c-7a63-449b-ac60-50b45db8edd5",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Weightmans — solicitor apprenticeship", "Birmingham Open Evening", "28/09/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://www.eventbrite.co.uk/e/1997832167794",
        "link_is_specific": True, "eligibility_note": APPRENTICESHIP_NOTE,
    },
    ("Brick Court Chambers", "Brick Court Chambers Student Open Day", "29/09/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://www.brickcourt.co.uk/pupillage-and-mini-pupillage/equal-opportunities-social-mobility-events",
        "link_is_specific": True, "eligibility_note": "Barristers' chambers (pupillage, not a training contract). No online application - apply by emailing a CV directly to the Pupillage Manager (details on the page).",
    },
    ("Davis Polk & Wardwell", "Penultimate Year & Postgraduate Insight Day", "30/09/2026"): {
        "opens_date": "2026-09-10", "opens_confirmed": True,
        "apply_link": "https://www.davispolk.com/careers/law-students-trainees/london",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Weightmans — solicitor apprenticeship", "Newcastle Open Evening", "30/09/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://www.eventbrite.co.uk/e/1997837897933",
        "link_is_specific": True, "eligibility_note": APPRENTICESHIP_NOTE,
    },
    ("Weil Gotshal & Manges", "Insight Day 1", "30/09/2026"): {
        "opens_date": "2026-09-01", "opens_confirmed": True,
        "apply_link": "https://weil.app.candidats.io/roles",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Bristows — solicitor apprenticeship", "Solicitor Apprenticeship Open Evening", "01/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://sites-bristows.vuturevx.com/44/1601/landing-pages/rsvp---blank.asp",
        "link_is_specific": True, "eligibility_note": APPRENTICESHIP_NOTE,
    },
    ("Herbert Smith Freehills Kramer", "IP Open Day", "01/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://careers.hsfkramer.com/global/en/uk/early-careers/open-days",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Herbert Smith Freehills Kramer", "Social Mobility Open Day", "01/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://careers.hsfkramer.com/global/en/uk/early-careers/open-days",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Milbank", "Open Day", "01/10/2026"): {
        "opens_date": "2026-09-03", "opens_confirmed": True,
        "apply_link": "https://www.apply4law.com/milbank/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Milbank", "Open Day (Leveraged Finance track)", "01/10/2026"): {
        "opens_date": "2026-09-03", "opens_confirmed": True,
        "apply_link": "https://www.apply4law.com/milbank/",
        "link_is_specific": False, "eligibility_note": "For students on a Finance LLM.",
    },
    ("Forsters", "Open Day 1", "02/10/2026"): {
        "opens_date": "2026-09-03", "opens_confirmed": True,
        "apply_link": "https://forsters.grad.allhires.com/app/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Goodwin", "Insight into Applications – Demystifying the Application Process", "02/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://goodwinlaw.app.candidats.io/event/7daf0946-4519-4c67-9dfe-d6b69f87c123",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Mills & Reeve", "In person Insight Event (Manchester)", "05/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://apply.candidats.io/ca0b7f0c-fe8a-441f-9048-030f548e6464",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("RPC — solicitor apprenticeship", "Solicitor Apprenticeship Virtual Insight Evening", "05/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://www.rpclegal.com/careers/early-talent/uk/meet-us-uk/london-solicitor-apprenticeship-insight-event",
        "link_is_specific": True, "eligibility_note": APPRENTICESHIP_NOTE,
    },
    ("Weightmans — solicitor apprenticeship", "Leeds Open Evening", "07/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://www.eventbrite.co.uk/e/1997838114581",
        "link_is_specific": True, "eligibility_note": APPRENTICESHIP_NOTE,
    },
    ("Weightmans — solicitor apprenticeship", "Online Open Evening", "08/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://www.eventbrite.co.uk/e/1998432780242",
        "link_is_specific": True, "eligibility_note": APPRENTICESHIP_NOTE,
    },
    ("Goodwin", "Insight into the Trainee Experience: Meet Our Trainees and Q&A", "09/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://goodwinlaw.app.candidats.io/event/ed2ce890-e0fe-41a5-a966-da86dc7ecb26",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Latham & Watkins", "London Open Day 2026 (October)", "11/10/2026"): {
        "opens_date": "2026-09-01", "opens_confirmed": False,
        "apply_link": "https://uk-earlyassociatecareers-lw.icims.com/jobs/10939/open-day---graduate-recruitment---28-october-2026---london/job",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Herbert Smith Freehills Kramer", "Black Talent Open Day", "12/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://careers.hsfkramer.com/global/en/uk/early-careers/open-days",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Herbert Smith Freehills Kramer", "Disputes Open Day", "12/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://careers.hsfkramer.com/global/en/uk/early-careers/open-days",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Herbert Smith Freehills Kramer", "IRIS Open Day", "12/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://careers.hsfkramer.com/global/en/uk/early-careers/open-days",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Herbert Smith Freehills Kramer", "MyPlus Open Day", "12/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://careers.hsfkramer.com/global/en/uk/early-careers/open-days",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Weightmans — solicitor apprenticeship", "Liverpool Open Evening", "12/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://www.eventbrite.co.uk/e/1997838450586",
        "link_is_specific": True, "eligibility_note": APPRENTICESHIP_NOTE,
    },
    ("Weil Gotshal & Manges", "Insight Day 2", "13/10/2026"): {
        "opens_date": "2026-09-01", "opens_confirmed": True,
        "apply_link": "https://weil.app.candidats.io/roles",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Bird & Bird", "Trainee Solicitor Open Day", "14/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://twobirds.app.candidats.io/roles",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Mills & Reeve", "In person Insight Event (Birmingham)", "15/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://apply.candidats.io/061385f8-ee8c-4173-a84a-afced419232d",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Mills & Reeve", "In person Insight Event (Leeds)", "15/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://apply.candidats.io/6c37d888-74d3-4691-91eb-f8fd377686c1",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("RPC", "London Insight Day", "15/10/2026"): {
        "opens_date": "2026-09-01", "opens_confirmed": True,
        "apply_link": "https://fsr.cvmailuk.com/rpc/main.cfm?page=jobSpecific&jobId=76370&rcd=86628&queryString=groupType%5F4%3D5614%26groupType%5F73%3D%26x%2Dtoken%3Dca1nfctbox2mrfuqfudsbjnh146e5p6uccl853sb",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Weightmans — solicitor apprenticeship", "Manchester Open Evening", "15/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://www.eventbrite.co.uk/e/1997838304148",
        "link_is_specific": True, "eligibility_note": APPRENTICESHIP_NOTE,
    },
    ("Forsters — solicitor apprenticeship", "Apprenticeship Insights Afternoon (Online)", "16/10/2026"): {
        "opens_date": "2026-09-03", "opens_confirmed": True,
        "apply_link": "https://forsters.grad.allhires.com/app/",
        "link_is_specific": False, "eligibility_note": APPRENTICESHIP_NOTE,
    },
    ("Forsters — solicitor apprenticeship", "Open day (in person)", "16/10/2026"): {
        "opens_date": "2026-09-03", "opens_confirmed": True,
        "apply_link": "https://forsters.grad.allhires.com/app/",
        "link_is_specific": False, "eligibility_note": APPRENTICESHIP_NOTE,
    },
    ("Goodwin", "Insight into the Trainee Experience: Meet Our Trainees and Q&A", "16/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://goodwinlaw.app.candidats.io/event/c04c8ed0-8f3e-48a8-95ac-425534c084a4",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Latham & Watkins", "London Open Day 2026 (November)", "18/10/2026"): {
        "opens_date": "2026-09-01", "opens_confirmed": False,
        "apply_link": "https://uk-earlyassociatecareers-lw.icims.com/jobs/10940/job",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Jones Day", "Open Evening 2", "22/10/2026"): {
        "opens_date": "2026-10-08", "opens_confirmed": True,
        "apply_link": "https://www.jonesday.com/en/careers/locations/united-kingdom?tab=events",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Latham & Watkins", "London LGBTQ+ Lawyers Group Open Day 2026", "25/10/2026"): {
        "opens_date": "2026-09-01", "opens_confirmed": False,
        "apply_link": "https://uk-earlyassociatecareers-lw.icims.com/jobs/10941/job",
        "link_is_specific": True, "eligibility_note": "Themed for the LGBTQ+ Lawyers Group but open to all interested students.",
    },
    ("Paul, Weiss", "November Insight Afternoon", "26/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://pweuropecareers.app.candidats.io/roles",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Weil Gotshal & Manges", "Insight Day 3", "29/10/2026"): {
        "opens_date": "2026-09-01", "opens_confirmed": True,
        "apply_link": "https://weil.app.candidats.io/roles",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Eversheds Sutherland", "Graduate Insight Evenings", "30/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://eversheds-sutherland.grad.allhires.com/app/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("TLT", "Virtual Open Evening", "30/10/2026"): {
        "opens_date": "2026-10-01", "opens_confirmed": True,
        "apply_link": "https://www.tlt.com/careers/early-careers/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Davis Polk & Wardwell", "Penultimate Year & Postgraduate Insight Day", "31/10/2026"): {
        "opens_date": "2026-10-01", "opens_confirmed": True,
        "apply_link": "https://www.davispolk.com/careers/law-students-trainees/london",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Latham & Watkins", "London Black Lawyers Group Open Day 2026", "01/11/2026"): {
        "opens_date": "2026-09-01", "opens_confirmed": False,
        "apply_link": "https://uk-earlyassociatecareers-lw.icims.com/jobs/10942/job",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Forsters — solicitor apprenticeship", "Early Careers Insights Q&A", "04/11/2026"): {
        "opens_date": "2026-09-03", "opens_confirmed": True,
        "apply_link": "https://forsters.grad.allhires.com/app/",
        "link_is_specific": False, "eligibility_note": APPRENTICESHIP_NOTE,
    },
    ("Fieldfisher", "Pathways to Practice Scheme (First year insight scheme)", "06/11/2026"): {
        "opens_date": "2026-09-14", "opens_confirmed": True,
        "apply_link": "https://www.fieldfisher.com/en/careers/earlycareers/future-lawyer-programmes",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Withers", "Open Day", "06/11/2026"): {
        "opens_date": "2026-10-01", "opens_confirmed": True,
        "apply_link": "https://www.witherscareers.com/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Trowers & Hamlins", "London Office Graduate Insight Day", "09/11/2026"): {
        "opens_date": "2026-10-01", "opens_confirmed": True,
        "apply_link": "https://www.apply4law.com/Trowers/",
        "link_is_specific": False, "eligibility_note": None,
    },
    # Researched 2026-10-04: Charles Russell Speechlys' own open-days page
    # (charlesrussellspeechlys.com/en/careers/early-talent/uk-graduate-
    # opportunities/open-days/) has finally refreshed for the 2026/27 cycle -
    # the 4 Sept rejection note ("text dated exactly one year earlier...
    # appears stale") no longer applies. States plainly: "We offer open days
    # in our London, Guildford and Cheltenham offices that any university
    # student or graduate can apply to (including those currently working).
    # We also offer a non-office specific virtual open day" - applications
    # open 15 Sept 2026, close 12 Nov 2026, matching Legal Cheek's own
    # needs_review deadline for both "London Open Day" and "Virtual Open
    # Day" exactly. No per-event apply link exists - the page itself links
    # to the firm's general candidats.io portal, so the open-days page is
    # used as the (non-specific) apply_link, same pattern as Stephenson
    # Harwood on 25 Sept. London event: Tuesday 8 Dec 2026. Virtual event:
    # Friday 11 Dec 2026 (Guildford 1 Dec and Cheltenham 3 Dec excluded -
    # non-London offices).
    ("Charles Russell Speechlys", "London Open Day", "12/11/2026"): {
        "opens_date": "2026-09-15", "opens_confirmed": True,
        "apply_link": "https://www.charlesrussellspeechlys.com/en/careers/early-talent/uk-graduate-opportunities/open-days/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Charles Russell Speechlys", "Virtual Open Day", "12/11/2026"): {
        "opens_date": "2026-09-15", "opens_confirmed": True,
        "apply_link": "https://www.charlesrussellspeechlys.com/en/careers/early-talent/uk-graduate-opportunities/open-days/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Mills & Reeve", "Virtual Insight Event", "12/11/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://apply.candidats.io/a8f00b84-f1fb-4b6b-abde-ecf792f4d573",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Goodwin", "Insight into Applications – Demystifying the Application Process", "13/11/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://goodwinlaw.app.candidats.io/event/a6272983-248e-4d31-a7fd-b099838d027f",
        "link_is_specific": True, "eligibility_note": None,
    },
    # Researched 2026-10-04: not previously tracked (new firm to this repo).
    # Found via a lawcareers.net diary listing, confirmed directly on the
    # firm's own careers.hilldickinson.com/early-careers/open-evenings page:
    # "Tuesday, 1 December" at the London office, application window 1 Oct -
    # 15 Nov 2026, explicitly "open to everyone, whether you're still in
    # education, considering a career change or simply exploring your
    # options" - a graduate is in scope, no eligibility_note needed. Matches
    # Legal Cheek's own needs_review deadline (15/11/2026) for "Training
    # Contract Open Evening" exactly. No per-event apply link - the firm's
    # page gives only its general AllHires application portal.
    ("Hill Dickinson", "Training Contract Open Evening", "15/11/2026"): {
        "opens_date": "2026-10-01", "opens_confirmed": True,
        "apply_link": "https://hilldickinson.grad.allhires.com/app/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Wedlake Bell", "Open Day", "16/11/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://wedlakebell.app.candidats.io/roles",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Trowers & Hamlins", "Birmingham Office Graduate Insight Day", "17/11/2026"): {
        "opens_date": "2026-10-01", "opens_confirmed": True,
        "apply_link": "https://www.apply4law.com/Trowers/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Forsters", "Open Day 2", "20/11/2026"): {
        "opens_date": "2026-10-05", "opens_confirmed": True,
        "apply_link": "https://forsters.grad.allhires.com/app/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Goodwin", "Insight into the Trainee Experience: Meet Our Trainees and Q&A", "21/11/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://goodwinlaw.app.candidats.io/event/338ddfd7-d308-47ed-8983-4dc6d35ff6c2",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Payne Hicks Beach", "Open Day 1", "22/11/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://phb.grad.allhires.com/app/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Payne Hicks Beach", "Open Day 2", "22/11/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://phb.grad.allhires.com/app/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Trowers & Hamlins", "Manchester Office Graduate Insight Day", "23/11/2026"): {
        "opens_date": "2026-10-01", "opens_confirmed": True,
        "apply_link": "https://www.apply4law.com/Trowers/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Trowers & Hamlins", "Exeter Office Graduate Insight Day", "25/11/2026"): {
        "opens_date": "2026-10-01", "opens_confirmed": True,
        "apply_link": "https://www.apply4law.com/Trowers/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Dechert", "First Year Insight Event", "31/12/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://dechert.app.candidats.io/roles",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Debevoise & Plimpton", "Open Day", "04/01/2027"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://debevoise.grad.allhires.com/app/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Slaughter and May", "Spring Open Day 1", "06/01/2027"): {
        "opens_date": "2026-10-05", "opens_confirmed": True,
        "apply_link": "https://www.slaughterandmay.com/careers/early-careers/apply/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Slaughter and May", "Spring Open Day 2", "06/01/2027"): {
        "opens_date": "2026-10-05", "opens_confirmed": True,
        "apply_link": "https://www.slaughterandmay.com/careers/early-careers/apply/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Slaughter and May", "Spring Open Day 3", "06/01/2027"): {
        "opens_date": "2026-10-05", "opens_confirmed": True,
        "apply_link": "https://www.slaughterandmay.com/careers/early-careers/apply/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Macfarlanes", "First Year Insight Scheme", "15/01/2027"): {
        "opens_date": "2026-11-02", "opens_confirmed": True,
        "apply_link": "https://apply.candidats.io/267c1af6-28a4-4634-8fdf-34cd677ae806",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Willkie Farr & Gallagher", "First Year Spring Insight Day", "25/01/2027"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://www.willkie.com/careers/legal-professional/early-careers/discover-more-and-apply/united-kingdom",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Mayer Brown", "London First Year Virtual Insight Session", "31/01/2027"): {
        "opens_date": "2026-09-01", "opens_confirmed": False,
        "apply_link": "https://mayerbrown.grad.allhires.com/app/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Dentons", "Open Day (London)", "05/02/2027"): {
        "opens_date": "2026-09-01", "opens_confirmed": False,
        "apply_link": "https://challengers.dentons.com/uk-trainees/opportunities/open-days/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Dentons", "Open Day (Scotland)", "05/02/2027"): {
        "opens_date": "2026-09-01", "opens_confirmed": False,
        "apply_link": "https://challengers.dentons.com/uk-trainees/opportunities/open-days/",
        "link_is_specific": False, "eligibility_note": "For students on a qualifying Scots law degree.",
    },
    ("Ashfords", "Bristol First Year Insight Day", "08/02/2027"): {
        "opens_date": "2026-12-01", "opens_confirmed": True,
        "apply_link": "https://ashfords.hr.candidats.io/events",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Ashfords", "Exeter First Year Insight Day", "08/02/2027"): {
        "opens_date": "2026-12-01", "opens_confirmed": True,
        "apply_link": "https://ashfords.hr.candidats.io/events",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Freshfields", "First Years Insight Scheme", "12/02/2027"): {
        "opens_date": "2026-11-30", "opens_confirmed": True,
        "apply_link": "https://www.freshfields.com/en/your-career/united-kingdom/early-careers/first-years-insight-scheme",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Gibson Dunn", "First Year Insight Day (In-person)", "12/02/2027"): {
        "opens_date": "2026-09-01", "opens_confirmed": True,
        "apply_link": "https://www.apply4law.com/GibsonDunn/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Gibson Dunn", "First Year Insight Day (Virtual)", "12/02/2027"): {
        "opens_date": "2026-09-01", "opens_confirmed": True,
        "apply_link": "https://www.apply4law.com/GibsonDunn/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("RPC", "Bristol Insight Day", "18/02/2027"): {
        "opens_date": "2026-09-01", "opens_confirmed": True,
        "apply_link": "https://fsr.cvmailuk.com/rpc/main.cfm?page=jobSpecific&jobId=76369&rcd=81569&queryString=groupType%5F4%3D5614%26groupType%5F112%3D%26groupType%5F73%3D%26x%2Dtoken%3Dfvvfqvo5kmynfbodecpl22jrbj1o62ckk3kuq5wm",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Davis Polk & Wardwell", "First Year Insight Day", "22/02/2027"): {
        "opens_date": "2027-02-01", "opens_confirmed": True,
        "apply_link": "https://www.davispolk.com/careers/law-students-trainees/london",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Hogan Lovells Cadwalader", "First Year Insight Scheme", "28/02/2027"): {
        "opens_date": "2027-01-04", "opens_confirmed": True,
        "apply_link": "https://apply.candidats.io/210ee084-369b-4abc-b7c0-7eb878c06281",
        "link_is_specific": True, "eligibility_note": "Firm identity independently verified: Hogan Lovells and Cadwalader, Wickersham & Taft merged, forming Hogan Lovells Cadwalader (combined firm launched 1 July 2026).",
    },
    ("Osborne Clarke", "Insight Scheme", "28/02/2027"): {
        "opens_date": "2026-10-01", "opens_confirmed": True,
        "apply_link": "https://join.osborneclarke.com/insight-scheme",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Eversheds Sutherland", "First Year Law/Second Year Non-Law Open Day", "02/03/2027"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://eversheds-sutherland.grad.allhires.com/app/",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("Forsters", "First Year Insight Day", "23/04/2027"): {
        "opens_date": "2026-09-03", "opens_confirmed": True,
        "apply_link": "https://forsters.grad.allhires.com/app/",
        "link_is_specific": False, "eligibility_note": None,
    },
    # --- Researched 2026-09-23 directly on uk-graduates.bakermckenzie.com/
    # events/ and confirmed on each event's own careers.bakermckenzie.com/
    # en_US/events/EventDetail page. All six are explicitly open to
    # "second year, penultimate year, final year students, or graduates in
    # any degree discipline" (firm's own wording) with a 2:1 or expected
    # 2:1, so a graduate is in scope for every one. Each is a diversity/
    # access-focused open day open to Maria as a graduate; recorded here as
    # eligibility_note per Maria's brief.
    ("Baker McKenzie", "General Open Day", "07/10/2026"): {
        "opens_date": "2026-09-07", "opens_confirmed": True,
        "apply_link": "https://careers.bakermckenzie.com/en_US/events/EventDetail?eventId=3607",
        "link_is_specific": True, "eligibility_note": None,
    },
    # Bug found 2026-10-07: the "07/10/2026" key above never fires on the one
    # day it matters. Legal Cheek's scraper replaces the literal date with
    # the word "Today" once the deadline lands on the current day (and
    # "Tomorrow" the day before - see Milbank's Leveraged Finance row in
    # needs_review today, deadline 08/10/2026 shown as "Tomorrow"), and
    # OPEN_DAY_OVERRIDES keys on the literal deadline_label string Legal
    # Cheek shows, not the parsed date - so this event sat invisible in
    # needs_review again this morning despite being "confirmed" two weeks
    # ago, the same silent-miss failure mode as the Squire Patton Boggs bug
    # (29 Sept). Re-verified directly on the event's own EventDetail page
    # today (still live, deadline literally today, 7 Oct) and added this
    # second key so the override fires under the label Legal Cheek is
    # actually showing. Same eligibility as the other five Baker McKenzie
    # open days - "second year, penultimate year, final year students, or
    # graduates in any degree discipline" - no note needed. General lesson:
    # any override whose deadline is today or tomorrow needs checking for
    # this exact mismatch, not just Baker McKenzie's.
    ("Baker McKenzie", "General Open Day", "Today"): {
        "opens_date": "2026-09-07", "opens_confirmed": True,
        "apply_link": "https://careers.bakermckenzie.com/en_US/events/EventDetail?eventId=3607",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Baker McKenzie", "Opportunity Open Day", "12/10/2026"): {
        "opens_date": "2026-09-07", "opens_confirmed": True,
        "apply_link": "https://careers.bakermckenzie.com/en_US/events/EventDetail?eventId=3638",
        "link_is_specific": True,
        "eligibility_note": "For candidates from lower socio-economic backgrounds (firm's own wording).",
    },
    ("Baker McKenzie", "Women’s Open Day", "12/10/2026"): {
        "opens_date": "2026-09-07", "opens_confirmed": True,
        "apply_link": "https://careers.bakermckenzie.com/en_US/events/EventDetail?eventId=3634",
        "link_is_specific": True, "eligibility_note": "For female applicants (firm's own wording).",
    },
    ("Baker McKenzie", "BakerEthnicity Open Day", "26/10/2026"): {
        "opens_date": "2026-09-07", "opens_confirmed": True,
        "apply_link": "https://careers.bakermckenzie.com/en_US/events/EventDetail?eventId=3639",
        "link_is_specific": True,
        "eligibility_note": "For candidates from ethnic minority backgrounds (firm's own wording).",
    },
    ("Baker McKenzie", "Pride at Baker McKenzie Open Day", "10/11/2026"): {
        "opens_date": "2026-09-07", "opens_confirmed": True,
        "apply_link": "https://careers.bakermckenzie.com/en_US/events/EventDetail?eventId=3640",
        "link_is_specific": True, "eligibility_note": "For LGBTQ+ applicants (firm's own wording).",
    },
    ("Baker McKenzie", "EmployAbility Open Day", "16/11/2026"): {
        "opens_date": "2026-09-07", "opens_confirmed": True,
        "apply_link": "https://careers.bakermckenzie.com/en_US/events/EventDetail?eventId=3641",
        "link_is_specific": True,
        "eligibility_note": "For candidates with disabilities, run with My Plus Consulting (firm's own wording).",
    },
    # Researched 2026-09-25: White & Case's "Open Days 2026" and "STEM Open
    # Day 2026" have been sitting in needs_review as stale/blocked (see the
    # 2026-09-04 rejection note below - the sweep gets a 403 from this
    # firm's site). Confirmed directly on whitecase.com/careers/locations/
    # uk/early-careers/our-offer/open-days 2026-09-25: General Open Days run
    # 18-19 Nov 2026 (matches Legal Cheek's 18/10/2026 deadline), STEM Open
    # Day runs 26 Nov 2026 (matches Legal Cheek's 01/11/2026 deadline).
    # Applications for both opened 24 Sept 2026 (already open as of today)
    # through the same apply4law.com/whitecase portal - no per-event link is
    # published. General Open Days eligibility per the firm's own wording:
    # "Penultimate-year and final-year law students, final-year non-law
    # students, and graduates from any discipline" - explicitly includes
    # graduates, no note needed.
    ("White & Case", "Open Days 2026", "18/10/2026"): {
        "opens_date": "2026-09-24", "opens_confirmed": True,
        "apply_link": "https://www.apply4law.com/whitecase",
        "link_is_specific": False, "eligibility_note": None,
    },
    ("White & Case", "STEM Open Day 2026", "01/11/2026"): {
        "opens_date": "2026-09-24", "opens_confirmed": True,
        "apply_link": "https://www.apply4law.com/whitecase",
        "link_is_specific": False,
        "eligibility_note": "For candidates from STEM degree disciplines (firm's own wording).",
    },
    # Researched 2026-09-29: Clifford Chance's "London Insight Day" has been
    # sitting in needs_review (Legal Cheek gives it a 19/10/2026 deadline,
    # matching exactly). Confirmed directly on jobs.cliffordchance.com/
    # meet-us-london (Insight Events accordion) and on the event's own job
    # posting (jobs.cliffordchance.com/job/london-insight-day-in-london-
    # jid-3551, ref REF3378M) - live, not expired, active Apply button
    # (note: fetching that same URL headlessly showed "This vacancy has
    # expired", a stale/cached response contradicted by the live rendered
    # page - the browser pane's JS-rendered read was trusted over it, per
    # the established rule for this kind of mismatch). Event held 10
    # November 2026, at the firm's Canary Wharf office. The event serves two
    # eligibility tracks (firm's own wording): SPARK (first/second-year law,
    # or penultimate-year non-law) and the Training Contract route
    # ("penultimate year of a law degree, final year of any degree, or
    # graduated") - a graduate is explicitly in scope via the TC route, no
    # eligibility_note needed. Distinct from Clifford Chance's "Middle East
    # Insight Day" (12 Nov, same accordion), which is out of scope (non-
    # London office) and not added.
    ("Clifford Chance", "London Insight Day", "19/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://jobs.cliffordchance.com/job/london-insight-day-in-london-jid-3551",
        "link_is_specific": True, "eligibility_note": None,
    },
    # Bug fix 2026-09-29: Squire Patton Boggs was confirmed directly on the
    # firm's own cvmailuk portal 2026-09-24 (see the MANUAL_EVENTS comment
    # near "Squire Patton Boggs") and a MANUAL_EVENTS entry was added that
    # day, but no matching OPEN_DAY_OVERRIDES entry was ever added - and
    # since Legal Cheek already lists this firm/event under the identical
    # (firm, event_name), the MANUAL_EVENTS copy has been silently skipped
    # as a duplicate every day since (build_entries() always treats a
    # (firm, event_name) match against legal_cheek_keys as reason to defer
    # to the OPEN_DAY_OVERRIDES/Legal Cheek path instead of the manual one -
    # see the comment there). Both events have therefore never actually
    # appeared on the dashboard despite being confirmed 5 days ago, and the
    # closing date is now only 13 days away. Adding the missing override
    # here (found on 2026-09-24, re-confirmed live via the browser pane
    # 2026-09-29 that the cvmailuk listings are still up) fixes this once
    # tomorrow's scrape runs.
    ("Squire Patton Boggs", "Open Day (London)", "12/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://fsr.cvmailuk.com/spb/main.cfm?page=jobSpecific&jobId=78947",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Squire Patton Boggs", "Open Day (Online)", "12/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://fsr.cvmailuk.com/spb/main.cfm?page=jobSpecific&jobId=78948",
        "link_is_specific": True, "eligibility_note": None,
    },
    # --- Researched 2026-09-04 but left OUT deliberately: each firm's own
    # site either didn't show a live/current listing for this event (stale
    # prior-cycle content, a 404, or "not yet published"), the event
    # couldn't be found at all, or the dates/identity found didn't clearly
    # match Legal Cheek's listing - so these stay in needs_review until a
    # clearer source is found rather than risking a wrong opens-date or
    # apply-link. See conversation notes for what was checked per firm:
    #   - Akin (Open Day virtual / London office): could not confirm either
    #     event still exists on Akin's current site
    #   - Winston Taylor (7 events closing 25/09/2026 + First Year Insight
    #     Day): could not find any of these events despite extensive
    #     searching - firm's early-careers content is mid-migration
    #     following the Winston & Strawn/Taylor Wessing merger
    #   - DWF (Insight Days) / DWF — solicitor apprenticeship (Insight
    #     days): no live 2026 event page found (only stale archived pages)
    #   - Squire Patton Boggs (all 5 Open Day locations): referenced URL
    #     404s, vacancy portal shows no UK Open Day listings
    #   - Bird & Bird (Trainee Solicitor Open Day) / Bird & Bird —
    #     solicitor apprenticeship: official page still shows the 2025
    #     cycle live, 2026/27 cycle not yet published
    #   - Clifford Chance (London Insight Day): "Meet us" page shows only
    #     expired 2025/26-season events, nothing live for 2026
    #   - Cripps — solicitor apprenticeship (both events): could not locate
    #     dedicated pages for either on cripps.co.uk
    #   - Clyde & Co (Bristol Insight Day): no open date published, and the
    #     firm's own events board lists what may be a differently-named/
    #     dated event ("Bristol Energy & Construction Insight Day", 5 Nov)
    #     - not confirmed to be the same event
    #   - Kirkland & Ellis (Open Day): site not yet refreshed for the Nov
    #     2026 cycle, so the 01/11/2026 close date couldn't be verified
    #   - Pinsent Masons (Insight Days): this is an 8-city series that
    #     doesn't map to one close date/link the way Legal Cheek lists it
    #   - HFW — solicitor apprenticeship (Solicitor Apprenticeship Open
    #     Day): portal shows only a prior-cycle listing marked "deadline
    #     passed"
    #   - Norton Rose Fulbright (all 4: Aspiring Black Lawyers Insights
    #     Day, Law/Non-law/STEM Open Day): repeated robots.txt blocks on
    #     the firm's own pages, and one page found contained conflicting
    #     stale content ("not planned to take place")
    #   - 5 Essex Chambers (all 3 Inside 5 Open Evenings): event dates
    #     found on the firm's own page don't clearly reconcile with Legal
    #     Cheek's close dates
    #   - HFW (Open Day, Virtual Insight Day): portal shows only prior-
    #     cycle listings marked "deadline passed"
    #   - Charles Russell Speechlys (all 4 Open Day locations): official
    #     page shows text dated exactly one year earlier than Legal
    #     Cheek's cycle, appears stale/not refreshed
    #   - Bates Wells — solicitor apprenticeship (Solicitor Apprenticeship
    #     Open Evening): firm's page gives a different date (19 Nov) than
    #     Legal Cheek's close date, and its own FAQ says graduates should
    #     use the training contract route instead
    #   - Serle Court (Open Day In-Person/Virtual): the firm's own site
    #     calls this a "Prospective Pupillage Evening" with different
    #     dates - not confirmed to be the same listing
    #   - Tanfield Chambers (Pupillage Open Evening): site says sign-up
    #     details "will be released shortly" - not open yet
    #   - Paul Hastings (December Insight Day): could only confirm last
    #     year's cycle, not a live 2026 listing
    #   - Simmons & Simmons — solicitor apprenticeship (London/Bristol open
    #     days): could not locate either event on the firm's own site
    #   - Linklaters — solicitor apprenticeship (Solicitor Apprentice open
    #     day): could not find a page for this specific event; the firm's
    #     apprenticeship programme window found runs different dates
    #   - Farrer & Co (First Year Insight Vacation Scheme): could not
    #     confirm this event exists under this name on farrer.co.uk
    #   - Burges Salmon (Trainee Insight Day for first-year/non-law
    #     students): firm's own vacancy/events search returned no results
    #   - Morgan Lewis (Open Day): could not confirm the 2027-cycle close
    #     date against the live site (only prior cycle found)
    #   - Winston Taylor — solicitor apprenticeship (Solicitor
    #     Apprenticeship Open Evening): site only shows the prior cycle
    #   - Addleshaw Goddard (all 4: London/Scotland/North/Virtual Insight
    #     Day): site only shows the prior cycle, and no per-location
    #     breakdown was found (all route through one generic link)
    #   - Simmons & Simmons (Spring Insight Scheme): could not find this
    #     event's details on the firm's own site
    #   - Dentons (Middle East Summer Insight Scheme): no page found
    #     distinct from Dentons' general Middle East vacation scheme
    #   - Vinson & Elkins (Open Day / "discoVEr V&E"): site shows only the
    #     prior (2025/26) cycle, 2026/27 not yet live
    #   - Ashfords (Virtual Insight Afternoon): source page had a date
    #     conflict (event date given as one day later than the close date,
    #     and stated "no applications are required")
    #   - Weightmans (Legal Insights Programme In-person/Virtual): 2027-
    #     cycle dates are "to be confirmed shortly" on the firm's own page,
    #     and the real programme structure (virtual stage feeding an
    #     invite-only in-person placement) doesn't clearly match Legal
    #     Cheek's two-listing framing
    #   - King & Spalding (Fund Finance Insight Day): firm's own page
    #     states 2026/2027 events "will update... from September 2026" -
    #     not yet published, and the event wasn't found anywhere else on
    #     the site

    # Researched 2026-10-05: Mishcon de Reya's five needs_review rows
    # (Undergraduate x2, Disability x2, STEM) have sat unconfirmed since
    # this repo began - the old /graduates/open-day page is a dead 2020
    # page (checked and confirmed stale again today), but the firm's main
    # /graduates page itself now lists a full, dated 2026/27 Open Days
    # section with its own "Registrations close" date for each event,
    # which matches every one of Legal Cheek's five scraped deadlines
    # exactly. Each event's own cvmailuk job posting was opened individually
    # to confirm eligibility. Undergraduate Open Day (both formats):
    # explicitly "including graduates" in the firm's own wording - no note
    # needed. Disability Open Day (both formats): open to "penultimate year
    # ... and onwards (including graduates)", run with the firm's Disability
    # Equity Committee but not restricted to applicants who are themselves
    # disabled - kept as a note since the framing is EDI-focused. STEM Open
    # Day: explicitly "for students and graduates from a STEM background" -
    # kept as a note since it's discipline-restricted. Two further Mishcon
    # open days on the same live page (Pride Open Day, Black Heritage
    # Graduate Breakfast) have deadlines that have already passed (25 Sept
    # and 2 Oct) - not added. Social Mobility and Race Equity Open Days'
    # deadlines had also already passed - not added either.
    ("Mishcon de Reya", "Undergraduate Open Day (In Person)", "09/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://fsr.cvmailuk.com/mishconearlycareersportal/main.cfm?page=jobSpecific&jobId=78895&rcd=8505512&queryString=&srxksl=1",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Mishcon de Reya", "Undergraduate Open Day (Virtual)", "14/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://fsr.cvmailuk.com/mishconearlycareersportal/main.cfm?page=jobSpecific&jobId=78896&rcd=8505512&queryString=",
        "link_is_specific": True, "eligibility_note": None,
    },
    ("Mishcon de Reya", "Disability Open Day (In Person)", "16/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://fsr.cvmailuk.com/mishconearlycareersportal/main.cfm?page=jobSpecific&jobId=78899&rcd=8505512&queryString=&srxksl=1",
        "link_is_specific": True,
        "eligibility_note": (
            "Run with the firm's Disability Equity Committee (firm's own "
            "wording) - open to penultimate year and onwards, including "
            "graduates; not restricted to applicants who are themselves "
            "disabled or neurodivergent."
        ),
    },
    ("Mishcon de Reya", "Disability Open Day (Virtual)", "21/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://fsr.cvmailuk.com/mishconearlycareersportal/main.cfm?page=jobSpecific&jobId=78900&rcd=8505512&queryString=&srxksl=1",
        "link_is_specific": True,
        "eligibility_note": (
            "Run with the firm's Disability Equity Committee (firm's own "
            "wording) - open to penultimate year and onwards, including "
            "graduates; not restricted to applicants who are themselves "
            "disabled or neurodivergent."
        ),
    },
    ("Mishcon de Reya", "STEM Open Day (In Person)", "30/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://fsr.cvmailuk.com/mishconearlycareersportal/main.cfm?page=jobSpecific&jobId=78968&rcd=6604135&queryString=&srxksl=1",
        "link_is_specific": True,
        "eligibility_note": "For students and graduates from a STEM background (firm's own wording).",
    },

    # Researched 2026-10-05: Akin's "Ask Akin Open Day" has sat in
    # needs_review under a drifting deadline (previously unconfirmable per
    # the 2026-09-04 note - "could not confirm either event still exists on
    # Akin's current site"). The firm's own events page
    # (akingump.com/en/careers/uk-students/meet-us-workshops-virtual-events-
    # and-more) now lists both the in-person and virtual sessions clearly.
    # The in-person "Ask Akin Open Day" (20 Oct 2026) closed for
    # applications Sunday 4 October 2026 - already passed as of today, not
    # added (Legal Cheek's own needs_review deadline for it, "Today"/5 Oct,
    # disagrees by a day - same kind of scrape-vs-firm-page drift seen
    # elsewhere in this repo; the firm's own page is trusted). The virtual
    # "Ask Akin Open Day" (29 Oct 2026, 11am-3pm) closes 18 October 2026 -
    # matches Legal Cheek's needs_review deadline for the virtual row
    # exactly. Eligibility per the firm's own wording: "penultimate-year law
    # students, final-year law and non-law students, and graduates from all
    # degree disciplines" - graduate explicitly included, no note needed.
    # There is no web apply form - the firm asks for a CV plus a short
    # paragraph emailed to graduaterecruitment@akingump.com - so the apply
    # link given is the event listing page itself (which has the full
    # instructions), not a submission form.
    ("Akin", "Ask Akin Open Day (Virtual)", "18/10/2026"): {
        "opens_date": "2026-09-17", "opens_confirmed": True,
        "apply_link": "https://www.akingump.com/en/careers/uk-students/meet-us-workshops-virtual-events-and-more",
        "link_is_specific": False,
        "eligibility_note": (
            "No online application form - email a CV and a short (max "
            "250-word) paragraph to graduaterecruitment@akingump.com with "
            "subject line 'Ask Akin Virtual Open Day Application' (firm's "
            "own instructions)."
        ),
    },

    # Researched 2026-10-05: Kingsley Napley's two needs_review rows have
    # sat unconfirmed. The firm's own open-days page
    # (kingsleynapley.co.uk/careers/early-careers/open-days/) uses different
    # naming ("Kingsley Napley Insight Day" / "Kingsley Napley Virtual
    # Insight Day") from Legal Cheek's "...Open Day" titles, but both events'
    # deadlines match Legal Cheek's scraped deadline_label exactly (12 Oct
    # and 18 Nov), strong evidence they're the same two events under the
    # firm's own rebranded name - kept Legal Cheek's event_name here (rather
    # than switching to MANUAL_EVENTS) since the deadlines agree exactly,
    # unlike the Bird & Bird case where they didn't. In-person Insight Day
    # (6 Nov 2026): eligibility per the firm's own wording "Aged 18+ and
    # either a university student (second year or above), a recent
    # graduate, or a career changer" - graduate explicitly included, no note
    # needed. Virtual Insight Day (18 Nov 2026): firm's own wording is "no
    # eligibility requirements or selection process... open to all
    # prospective applicants" - no note needed either. A third event on the
    # same page, "Black Professionals in Law Insight Day - Kingsley Napley x
    # Bridging Barriers" (23 Oct 2026, deadline 5 Oct 2026 - today), has no
    # Legal Cheek row at all - entered in MANUAL_EVENTS instead, see below.
    ("Kingsley Napley", "Kingsley Napley In-person Open Day", "12/10/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://kingsleynapley.app.candidats.io/event/5300f520-ce8c-4a48-9322-1255b4c3e8cd",
        "link_is_specific": True,
        "eligibility_note": (
            "Firm's own wording: aged 18+ and either a university student "
            "(second year or above), a recent graduate, or a career changer."
        ),
    },
    ("Kingsley Napley", "Kingsley Napley Virtual Open Day", "18/11/2026"): {
        "opens_date": None, "opens_confirmed": False,
        "apply_link": "https://kingsleynapley.app.candidats.io/event/a8f0bdaa-926b-4004-a19f-a2a131e8e53b",
        "link_is_specific": True, "eligibility_note": None,
    },
    # Researched 2026-10-07: Simmons & Simmons' "Spring Insight Scheme" has
    # sat in needs_review unconfirmed since the original 4 Sept pass ("could
    # not find this event's details on the firm's own site"). The firm's own
    # /en/graduates page now has a live "Find the scheme for you" section
    # describing it directly: a two-day scheme (20-21 April 2027) in the
    # London office, paid GBP150 for the two days, with shadowing and
    # interactive sessions. "Applications for our spring insight scheme open
    # from 10 December 2026 - 31 January 2027" - matches Legal Cheek's own
    # needs_review deadline (31/01/2027) exactly. No per-scheme application
    # form exists yet (applications aren't open until 10 Dec) - the
    # graduates page itself, which has the "Register your interest" link, is
    # used as the apply_link rather than guessing at a future portal URL.
    # The page doesn't restrict this scheme by year of study or exclude
    # graduates, so no eligibility_note.
    ("Simmons & Simmons", "Spring Insight Scheme", "31/01/2027"): {
        "opens_date": "2026-12-10", "opens_confirmed": True,
        "apply_link": "https://www.simmons-simmons.com/en/graduates",
        "link_is_specific": False, "eligibility_note": None,
    },
}

# Events verified directly on a firm's own site/registration page that
# Legal Cheek's calendar does not list at all - unlike OPEN_DAY_OVERRIDES
# above (which only fills in the opening date/apply link for a row Legal
# Cheek DOES show), these have no Legal Cheek row to cross-reference, so
# the full record (including the deadline) is entered here from the firm's
# own page directly. If Legal Cheek later starts listing the same event,
# build_entries() skips the manual copy so it isn't shown twice.
MANUAL_EVENTS = [
    {
        "firm": "Goodwin",
        "event_name": "In-Person Open Afternoon",
        "summary": (
            "An in-person event giving a comprehensive overview of the firm, its "
            "practice areas and its opportunities, with application guidance for "
            "vacation schemes and trainee solicitor roles and networking with "
            "current staff. Event held 10 November 2026."
        ),
        "opens_date": None,
        "opens_confirmed": False,
        "deadline_label": "16/10/2026",
        "deadline_date": "2026-10-16",
        "apply_link": "https://apply.candidats.io/b075c749-882c-4b93-9d74-40170c143384",
        "link_is_specific": True,
        "eligibility_note": None,
        "location": "London",
        "found_on": "2026-09-05",
    },
    # The three below fill in the "Open finding" noted 10 Sept 2026: Goodwin's
    # own candidats.io portal (goodwinlaw.app.candidats.io/roles) lists two
    # more In-Person Open Afternoon dates and a Virtual Open Afternoon that
    # never showed up via Legal Cheek. Confirmed directly on each event's own
    # apply page 2026-09-21 (clicked "Job Details" through to
    # apply.candidats.io for each). "(3 November)"/"(12 November)" is added
    # to the event_name only to keep each entry's id unique - both share the
    # exact same 16/10/2026 deadline as the 10 November session above, which
    # is a single shared application window covering three event dates, not
    # a typo.
    {
        "firm": "Goodwin",
        "event_name": "In-Person Open Afternoon (3 November)",
        "summary": (
            "An in-person event giving a comprehensive overview of the firm, its "
            "practice areas and its opportunities, with application guidance for "
            "vacation schemes and trainee solicitor roles and networking with "
            "current staff. Event held 3 November 2026."
        ),
        "opens_date": None,
        "opens_confirmed": False,
        "deadline_label": "16/10/2026",
        "deadline_date": "2026-10-16",
        "apply_link": "https://apply.candidats.io/c31a84b0-74d0-40ea-a581-0aaecb281b51",
        "link_is_specific": True,
        "eligibility_note": None,
        "location": "London",
        "found_on": "2026-09-21",
    },
    {
        "firm": "Goodwin",
        "event_name": "In-Person Open Afternoon (12 November)",
        "summary": (
            "An in-person event giving a comprehensive overview of the firm, its "
            "practice areas and its opportunities, with application guidance for "
            "vacation schemes and trainee solicitor roles and networking with "
            "current staff. Event held 12 November 2026."
        ),
        "opens_date": None,
        "opens_confirmed": False,
        "deadline_label": "16/10/2026",
        "deadline_date": "2026-10-16",
        "apply_link": "https://apply.candidats.io/602cfc51-ea22-45a8-b993-a5841ffc476f",
        "link_is_specific": True,
        "eligibility_note": None,
        "location": "London",
        "found_on": "2026-09-21",
    },
    {
        "firm": "Goodwin",
        "event_name": "Virtual Open Afternoon",
        "summary": (
            "A virtual/online event giving a comprehensive overview of the firm, "
            "its practice areas and its opportunities, with application guidance "
            "for vacation schemes and trainee solicitor roles and networking with "
            "current staff. Event held 25 November 2026."
        ),
        "opens_date": None,
        "opens_confirmed": False,
        "deadline_label": "18/11/2026",
        "deadline_date": "2026-11-18",
        "apply_link": "https://apply.candidats.io/88f35414-cb0e-4033-98bf-780d6a6a3473",
        "link_is_specific": True,
        "eligibility_note": None,
        "location": "Virtual",
        "found_on": "2026-09-21",
    },
    # Jones Day's own events page (jonesday.com/en/careers/locations/united-
    # kingdom?tab=events) lists two sessions literally titled "Open Evening":
    # 22 Oct 2026 (already on the dashboard as "Open Evening 2", via
    # OPEN_DAY_OVERRIDES/Legal Cheek) and this one, 11 Nov 2026, which Legal
    # Cheek has not listed yet. Named "Open Evening 3" to match the firm's
    # own sequential numbering (confirmed by third-party listings using the
    # same name) and to avoid colliding with "Open Evening 2" if Legal Cheek
    # adds this one later. Deadline follows this repo's existing convention
    # for this exact event type at this firm (see Open Evening 2): the
    # firm's page gives no separate closing date, so deadline = event date.
    # Confirmed on the firm's own page 2026-09-21.
    {
        "firm": "Jones Day",
        "event_name": "Open Evening 3",
        "summary": (
            "An in-person event featuring an office tour, talks from trainees "
            "and partners, and Q&A about the firm and its application process."
        ),
        "opens_date": "2026-10-28",
        "opens_confirmed": True,
        "deadline_label": "11/11/2026",
        "deadline_date": "2026-11-11",
        "apply_link": "https://www.jonesday.com/en/careers/locations/united-kingdom?tab=events",
        "link_is_specific": False,
        "eligibility_note": None,
        "location": "London",
        "found_on": "2026-09-21",
    },
    # Not on Legal Cheek's calendar at all. Found via lawcareers.net's
    # "Law firm open days and insight schemes 2026/27" roundup (15 Sept
    # 2026) and confirmed directly on DLA Piper's own early-careers site
    # 2026-09-22: careers.dlapiper.com/early-careers/europe/uk/discovery-
    # days.html lists five UK Discovery Days this cycle (London, Manchester,
    # Leeds, Birmingham, Edinburgh), each with its own date/deadline/apply
    # link - only the London one is in scope here. Eligibility per the
    # firm's own page: second-/third-/final-year law students, final-year
    # non-law students, and graduates/career changers are all explicitly
    # welcome, so no eligibility_note is needed.
    {
        "firm": "DLA Piper",
        "event_name": "London Discovery Day",
        "summary": (
            "An in-person event for students, graduates and career changers to "
            "learn about DLA Piper's practice areas, meet trainees and staff, "
            "and get guidance on the application process. One of five UK "
            "Discovery Days run this cycle (also in Manchester, Leeds, "
            "Birmingham and Edinburgh); event held 12 October 2026."
        ),
        "opens_date": None,
        "opens_confirmed": False,
        "deadline_label": "05/10/2026",
        "deadline_date": "2026-10-05",
        "apply_link": "https://forms.rmp-connect.com/form/aeWYJ0eHRCrBtsQj9ap0sZVcPa/6dx8y5qzSBEqnn8Fa5Pg",
        "link_is_specific": True,
        "eligibility_note": None,
        "location": "London",
        "found_on": "2026-09-22",
    },
    # Not on Legal Cheek's calendar. Found via a TCLA forum roundup (last
    # edited 21 Sept 2026), then confirmed directly on Mayer Brown's own
    # site (mayerbrown.com/en/careers/students-and-graduates/europe)
    # 2026-09-23: two London Insight Day sessions this cycle, both open to
    # "all undergraduates and graduates, regardless of degree discipline"
    # (firm's own wording - no eligibility_note needed), applications open
    # 1 Sept, both share the same 5 Oct closing date. Apply link is the
    # firm's general AllHires portal (also used for Mayer Brown's existing
    # First Year Virtual Insight Session override) - no per-session link is
    # published.
    {
        "firm": "Mayer Brown",
        "event_name": "London Insight Day 1",
        "summary": (
            "An in-person event featuring talks, Q&A, and networking with "
            "trainees, giving a flavour of life and work at the firm. Event "
            "held 21 October 2026."
        ),
        "opens_date": "2026-09-01",
        "opens_confirmed": True,
        "deadline_label": "05/10/2026",
        "deadline_date": "2026-10-05",
        "apply_link": "https://mayerbrown.grad.allhires.com/app/",
        "link_is_specific": False,
        "eligibility_note": None,
        "location": "London",
        "found_on": "2026-09-23",
    },
    {
        "firm": "Mayer Brown",
        "event_name": "London Insight Day 2",
        "summary": (
            "An in-person event featuring talks, Q&A, and networking with "
            "trainees, giving a flavour of life and work at the firm. Event "
            "held 17 November 2026."
        ),
        "opens_date": "2026-09-01",
        "opens_confirmed": True,
        "deadline_label": "05/10/2026",
        "deadline_date": "2026-10-05",
        "apply_link": "https://mayerbrown.grad.allhires.com/app/",
        "link_is_specific": False,
        "eligibility_note": None,
        "location": "London",
        "found_on": "2026-09-23",
    },
    # Not on Legal Cheek's calendar. Found via the same TCLA roundup,
    # confirmed directly on Dechert's own application portal
    # (dechert.app.candidats.io -> "Open Event - 16 November 2026")
    # 2026-09-23. The event page states explicitly: "for those who are
    # currently eligible to apply for a vacation scheme, which is
    # penultimate year law undergraduates, all final year undergraduates
    # (both law and non-law), all graduates, post-graduates and career
    # changers" - so a graduate is in scope, no eligibility_note needed.
    {
        "firm": "Dechert",
        "event_name": "Open Event",
        "summary": (
            "An in-person event featuring talks, Q&A, and networking with "
            "trainees and associates, plus an application skills session, "
            "giving a flavour of life and work at the firm before applying "
            "to the vacation scheme. Event held 16 November 2026."
        ),
        "opens_date": None,
        "opens_confirmed": False,
        "deadline_label": "30/10/2026",
        "deadline_date": "2026-10-30",
        "apply_link": "https://apply.candidats.io/09d37113-dd30-41e8-a464-be001b3cbdfb",
        "link_is_specific": True,
        "eligibility_note": None,
        "location": "London",
        "found_on": "2026-09-23",
    },
    # Not on Legal Cheek's calendar. Found via the same TCLA roundup ("Meet
    # Cooley"), confirmed directly on Cooley's own application portal
    # (cooley.app.candidats.io -> "Meet Cooley - In Person" /
    # "Meet Cooley - Virtual") 2026-09-23. Neither event page publishes a
    # specific session date (only a closing date for registrations, which
    # may close early due to limited capacity) or an explicit eligibility
    # statement - Cooley UK's general early-careers materials describe this
    # event series as prioritising penultimate-year law / final-year
    # non-law / graduates / career changers, consistent with a graduate
    # being in scope, but that wording wasn't repeated on this cycle's
    # event page itself.
    {
        "firm": "Cooley",
        "event_name": "Meet Cooley - In Person",
        "summary": (
            "An in-person flagship student event bringing together partners, "
            "associates, trainees and the graduate recruitment team for a day "
            "of insight, conversation and networking. Limited capacity - "
            "registrations may close before the stated deadline."
        ),
        "opens_date": None,
        "opens_confirmed": False,
        "deadline_label": "13/10/2026",
        "deadline_date": "2026-10-13",
        "apply_link": "https://apply.candidats.io/54a424cb-40e9-4f21-9985-ec2d172c8ba5",
        "link_is_specific": True,
        "eligibility_note": None,
        "location": "London",
        "found_on": "2026-09-23",
    },
    {
        "firm": "Cooley",
        "event_name": "Meet Cooley - Virtual",
        "summary": (
            "A virtual flagship student event bringing together partners, "
            "associates, trainees and the graduate recruitment team for an "
            "afternoon of insight, conversation and networking. Limited "
            "capacity - registrations may close before the stated deadline."
        ),
        "opens_date": None,
        "opens_confirmed": False,
        "deadline_label": "03/11/2026",
        "deadline_date": "2026-11-03",
        "apply_link": "https://apply.candidats.io/f0e4d84d-acc4-42e7-b6c4-7799dda6e237",
        "link_is_specific": True,
        "eligibility_note": None,
        "location": "Virtual",
        "found_on": "2026-09-23",
    },
    # Squire Patton Boggs is already in needs_review via Legal Cheek ("Open
    # Day (London)" and "Open Day (Online)", both deadline 12/10/2026) but
    # was previously left unresearched - the 2026-09-04 notes record the
    # referenced URL 404ing and the vacancy portal showing no UK Open Day
    # listings. That has since changed: confirmed directly on the firm's own
    # cvmailuk application portal 2026-09-24, both events live with matching
    # deadlines. event_name is kept identical to the Legal Cheek listing so
    # build_entries() treats this as the same event once Legal Cheek's own
    # row is verified (it's already skipped as a manual duplicate whenever
    # (firm, event_name) is in legal_cheek_keys, which it is here).
    {
        "firm": "Squire Patton Boggs",
        "event_name": "Open Day (London)",
        "summary": (
            "An in-person event to help with Training Contract/Vacation "
            "Scheme applications, with talks and networking at the firm's "
            "London office. Event held 26 November 2026."
        ),
        "opens_date": None,
        "opens_confirmed": False,
        "deadline_label": "12/10/2026",
        "deadline_date": "2026-10-12",
        "apply_link": "https://fsr.cvmailuk.com/spb/main.cfm?page=jobSpecific&jobId=78947",
        "link_is_specific": True,
        "eligibility_note": None,
        "location": "London",
        "found_on": "2026-09-24",
    },
    {
        "firm": "Squire Patton Boggs",
        "event_name": "Open Day (Online)",
        "summary": (
            "A virtual event to help with Training Contract/Vacation Scheme "
            "applications, with talks and networking. Event held 24 "
            "November 2026."
        ),
        "opens_date": None,
        "opens_confirmed": False,
        "deadline_label": "12/10/2026",
        "deadline_date": "2026-10-12",
        "apply_link": "https://fsr.cvmailuk.com/spb/main.cfm?page=jobSpecific&jobId=78948",
        "link_is_specific": True,
        "eligibility_note": None,
        "location": "Virtual",
        "found_on": "2026-09-24",
    },
    # Not on Legal Cheek's calendar at all - found via a general web search,
    # confirmed directly on Norton Rose Fulbright's own Workday job posting
    # 2026-09-24: applications explicitly stated as open 7 September - 18
    # October 2026 (today, 24 Sept, falls inside that window). Distinct from
    # NRF's other events already in needs_review (Aspiring Black Lawyers/
    # Law/Non-law/STEM Open Day) - this is a separate "Commercial Law Open
    # Day" listing not otherwise seen. Eligibility per the posting:
    # "undergraduate students and recent graduates from a law academic
    # discipline" - explicitly includes recent graduates, no note needed.
    {
        "firm": "Norton Rose Fulbright",
        "event_name": "Commercial Law Open Day",
        "summary": (
            "An in-person event introducing NRF's commercial law practice "
            "areas, with talks, Q&A and networking, for undergraduates and "
            "recent graduates from a law discipline. Event held 10 November "
            "2026."
        ),
        "opens_date": "2026-09-07",
        "opens_confirmed": True,
        "deadline_label": "18/10/2026",
        "deadline_date": "2026-10-18",
        "apply_link": "https://nrf.wd3.myworkdayjobs.com/Graduates/job/London-United-Kingdom/Commercial-Law-Open-Day_R-4343",
        "link_is_specific": True,
        "eligibility_note": None,
        "location": "London",
        "found_on": "2026-09-24",
    },
    # Not on Legal Cheek's calendar at all - Stephenson Harwood has no
    # existing entry anywhere in this repo. Found via a general web search
    # (Bright Network/lawcareers.net listings pointed at the firm), then
    # confirmed directly on the firm's own page
    # (stephensonharwood.com/careers/early-careers/early-careers-london/
    # open-days/) 2026-09-25: "For all open days, applications open from
    # 10am Monday 5 October 2026 and will close at 10am Friday 6 November
    # 2026" - one shared application window covering three in-scope London
    # events (a fourth and fifth, both explicitly "Solicitor Apprenticeship"
    # sessions, are excluded by EXCLUDE_APPRENTICESHIPS). No per-event apply
    # form is published - the page states enquiries go to
    # future.talent@stephensonharwood.com and gives no URL beyond itself, so
    # the open-days page is used as the (non-specific) apply_link rather
    # than guessing at a portal link. Eligibility for the Training Contract
    # Open Day and its virtual counterpart is not restricted by year of
    # study on the firm's page. The Disability Open Day's own wording is
    # "first year of university and beyond with a disability,
    # neurodiversity, or long-term health condition" - kept as a note since
    # it doesn't explicitly say "graduate" but doesn't exclude one either.
    {
        "firm": "Stephenson Harwood",
        "event_name": "Training Contract Open Day",
        "summary": (
            "An in-person event introducing the firm, its training contract "
            "and its application process, with talks and networking. Event "
            "held 1 December 2026."
        ),
        "opens_date": "2026-10-05",
        "opens_confirmed": True,
        "deadline_label": "06/11/2026",
        "deadline_date": "2026-11-06",
        "apply_link": "https://www.stephensonharwood.com/careers/early-careers/early-careers-london/open-days/",
        "link_is_specific": False,
        "eligibility_note": None,
        "location": "London",
        "found_on": "2026-09-25",
    },
    {
        "firm": "Stephenson Harwood",
        "event_name": "Virtual Training Contract Insight Day",
        "summary": (
            "A virtual/online event introducing the firm, its training "
            "contract and its application process, with talks and "
            "networking. Event held 9 December 2026."
        ),
        "opens_date": "2026-10-05",
        "opens_confirmed": True,
        "deadline_label": "06/11/2026",
        "deadline_date": "2026-11-06",
        "apply_link": "https://www.stephensonharwood.com/careers/early-careers/early-careers-london/open-days/",
        "link_is_specific": False,
        "eligibility_note": None,
        "location": "Virtual",
        "found_on": "2026-09-25",
    },
    {
        "firm": "Stephenson Harwood",
        "event_name": "Disability Open Day",
        "summary": (
            "An in-person event introducing the firm, its training contract "
            "and its application process, focused on supporting candidates "
            "with a disability, neurodivergence or long-term health "
            "condition. Event held 14 December 2026."
        ),
        "opens_date": "2026-10-05",
        "opens_confirmed": True,
        "deadline_label": "06/11/2026",
        "deadline_date": "2026-11-06",
        "apply_link": "https://www.stephensonharwood.com/careers/early-careers/early-careers-london/open-days/",
        "link_is_specific": False,
        "eligibility_note": "For candidates with a disability, neurodivergence, or long-term health condition, first year of university and beyond (firm's own wording).",
        "location": "London",
        "found_on": "2026-09-25",
    },
    # Confirmed 2026-09-27 directly on kslaw.com (the "Meet Our Team" /
    # Upcoming Events section of the UK Training Contracts page), but that
    # day's push to GitHub failed (egress proxy 403 + device bridge offline)
    # and the change was never applied - see the pending note written that
    # day. Re-verified live on the same page 2026-09-29: both events and the
    # application window are unchanged. King & Spalding's own page states no
    # event-specific deadline for either - only the firm's general training
    # contract application window (1 Oct 2026 - 26 Feb 2027), used here as
    # deadline_date since nothing more specific is published. Apply link is
    # the firm's general AllHires portal (no per-event link exists).
    # Eligibility per the firm's standard wording ("penultimate year of a law
    # degree, final year of a non-law degree or have already graduated") -
    # graduates explicitly included, no note needed. Distinct from the
    # unrelated "Fund Finance Insight Day" already sitting in needs_review
    # (Legal Cheek's own scrape gives that one a 26/10/2027 deadline, a full
    # year off from anything on the firm's live site - left alone).
    {
        "firm": "King & Spalding",
        "event_name": "In-Person Insight Afternoon - Spotlight on Fund Finance",
        "summary": (
            "An in-person event at the firm's London office featuring a "
            "spotlight session on the Fund Finance practice, with networking "
            "with trainees, associates and partners and insight into the "
            "application and interview process. Event held 12 November 2026, "
            "1:45pm-7:30pm."
        ),
        "opens_date": "2026-10-01",
        "opens_confirmed": True,
        "deadline_label": "26/02/2027",
        "deadline_date": "2027-02-26",
        "apply_link": "https://kslaw.grad.allhires.com/app/",
        "link_is_specific": False,
        "eligibility_note": None,
        "location": "London",
        "found_on": "2026-09-27",
    },
    {
        "firm": "King & Spalding",
        "event_name": "Virtual Insight Afternoon - Spotlight on Corporate",
        "summary": (
            "A virtual event featuring a spotlight session on the Corporate "
            "practice, with networking with trainees, associates and partners "
            "and insight into the application and interview process. Event "
            "held 21 January 2027, 1:15pm-5:00pm."
        ),
        "opens_date": "2026-10-01",
        "opens_confirmed": True,
        "deadline_label": "26/02/2027",
        "deadline_date": "2027-02-26",
        "apply_link": "https://kslaw.grad.allhires.com/app/",
        "link_is_specific": False,
        "eligibility_note": None,
        "location": "Virtual",
        "found_on": "2026-09-27",
    },
    # Researched 2026-10-01, re-verified 2026-10-02 and 2026-10-03 (no push
    # access on any of those days - see claude/london-open-day-search-
    # pending-2026-10-0{1,2}.md). Legal Cheek already lists "Bird & Bird" /
    # "Trainee Solicitor Open Day" (it drifts between needs_review rows with
    # different stale deadlines day to day - "02/10/2026", then "Today", and
    # today (3 Oct) it has dropped out of both events and needs_review
    # entirely), but the firm's own careers page (twobirds.com/en/careers/
    # united-kingdom/early-careers/open-days-and-drop-ins) gives a different,
    # stable deadline - 09 October 2026 - for the same event, confirmed via
    # the browser pane on 1 Oct directly on the event's own candidats.io
    # application page (apply.candidats.io/cac35db5-ec6d-4bcf-acd1-
    # f18834aaad15): the page's static body text says "Deadline: Midday on 2
    # October 2026" (stale leftover copy - the same kind of WebFetch-vs-
    # rendered-page mismatch as the Clifford Chance case on 29 Sept), but the
    # page's own dynamically-rendered "Application deadline" field says "9
    # October 2026". Independently corroborated 3 Oct by The Corporate Law
    # Academy's open-day deadlines thread (edited that same day), which lists
    # "Bird & Bird / Trainee Solicitor Open Day" opening 14 Sep 2026 and
    # closing 9 Oct 2026 - matching exactly. Event is virtual, 21 October
    # 2026. Eligibility per the firm's own wording: "in your final year of a
    # non-law degree; or in your penultimate or final year of a law degree;
    # or studying or have completed the PgDL; or studying or have completed
    # SQE1 and/or SQE2" - a law graduate is explicitly in scope via the
    # PgDL/SQE routes, no eligibility_note needed. Entered here as
    # MANUAL_EVENTS rather than OPEN_DAY_OVERRIDES, and named "Trainee
    # Solicitor Open Day (Virtual)" (matching the firm's own site, which
    # distinguishes it from the Solicitor Apprentice Open Day) rather than
    # Legal Cheek's bare "Trainee Solicitor Open Day", specifically so it is
    # NOT skipped as a legal_cheek_keys duplicate the way Squire Patton Boggs
    # was on 24-29 Sept - this event's real deadline (9 Oct) differs from
    # every deadline Legal Cheek's scrape has shown for it so far.
    {
        "firm": "Bird & Bird",
        "event_name": "Trainee Solicitor Open Day (Virtual)",
        "summary": (
            "A virtual/online session featuring a virtual tour and talks "
            "introducing the firm and its application process, with insight "
            "talks, panel discussions, Q&As and skill sessions. Event held "
            "21 October 2026."
        ),
        "opens_date": "2026-09-14",
        "opens_confirmed": True,
        "deadline_label": "09/10/2026",
        "deadline_date": "2026-10-09",
        "apply_link": "https://apply.candidats.io/cac35db5-ec6d-4bcf-acd1-f18834aaad15",
        "link_is_specific": True,
        "eligibility_note": None,
        "location": "Virtual",
        "found_on": "2026-10-01",
    },
    # Researched 2026-10-03. Not on Legal Cheek's calendar at all under this
    # name, and not previously tracked anywhere in this repo. Confirmed
    # directly on the firm's own registration page (slaughterandmay.com/
    # careers/early-careers/october-virtual-insight-afternoon/ - read live via
    # the browser pane since this is a noindex/nofollow page that WebFetch
    # could only partially read): "Please register your place below for our
    # October Virtual Insight Afternoon on Wednesday 28 October", with an
    # inline registration form on that same page (no separate apply URL - the
    # event page itself IS the specific apply link). The firm's general
    # virtual-insight-afternoons hub page (slaughterandmay.com/careers/
    # trainee-solicitors/work-experience-opportunities/virtual-insight-
    # afternoons) gives the deadline: "the October session... registrations
    # are open and will close on Wednesday 21 October 2026" (an earlier 29
    # Sept session is already full/closed). Eligibility per the firm's own
    # registration page: "this event is for finalists and graduates only" -
    # a graduate is explicitly in scope, no eligibility_note needed.
    # Independently corroborated by The Corporate Law Academy's open-day
    # deadlines thread (edited 3 Oct 2026), which lists a Slaughter and May
    # "Virtual Insight Afternoon" opening 21 Sep 2026 and closing 21 Oct
    # 2026 - matching the firm's own deadline exactly (opens_date taken from
    # TCLA only, so opens_confirmed is False; the deadline itself is firm-
    # confirmed). Distinct from this firm's existing "Spring Open Day
    # 1/2/3" (6 Jan 2027 deadline) and "Commercial Law"/"Explore Law Virtual
    # Insight Programme" (1 Sep 2027 deadline) entries already in this repo.
    {
        "firm": "Slaughter and May",
        "event_name": "October Virtual Insight Afternoon",
        "summary": (
            "A virtual session giving finalists and graduates an insight "
            "into a career as a lawyer at the firm - hearing from partners "
            "and trainees, learning about a recent deal, and finding out "
            "what the firm looks for in training contract applicants. "
            "Event held 28 October 2026."
        ),
        "opens_date": "2026-09-21",
        "opens_confirmed": False,
        "deadline_label": "21/10/2026",
        "deadline_date": "2026-10-21",
        "apply_link": "https://www.slaughterandmay.com/careers/early-careers/october-virtual-insight-afternoon/",
        "link_is_specific": True,
        "eligibility_note": None,
        "location": "Virtual",
        "found_on": "2026-10-03",
    },
    # Researched 2026-10-04. Not on Legal Cheek's calendar at all (no
    # needs_review row exists for Skadden), and not previously tracked
    # anywhere in this repo. Skadden's own UK careers page
    # (skadden.com/careers/attorneys/law-students-and-graduates/
    # united-kingdom) only mentions a first-year-only spring open day, but
    # links to "our graduate recruitment events" - skadden.allhires.com -
    # which is itself a JS-rendered empty shell to a plain fetch (same
    # problem as the candidats.io group); read directly via the browser
    # pane instead. Confirmed two in-scope events on the firm's own AllHires
    # portal (PositionDetails?id=473 and id=479) out of four currently
    # listed there - the other two ("Meet the Graduate Recruitment Team",
    # 15 Oct and 2 Nov) are informal webinar Q&As, not an open day/evening,
    # insight day/evening, insight scheme or first-year scheme, so excluded
    # as out of scope (same call as Bird & Bird's "Office Drop-In" on
    # 3 Oct). An AllAboutLaw listing separately mentioned an "Open Evening -
    # 6 October 2026" that doesn't appear on the firm's own live portal at
    # all - not added (fail closed; the portal is the source of truth).
    {
        "firm": "Skadden",
        "event_name": "Open Evening",
        "summary": (
            "An in-person insight evening for aspiring lawyers interested in "
            "a career in commercial law at the firm, with the chance to gain "
            "insight into the firm, its graduate recruitment process, and "
            "network with trainees and lawyers. Event held 28 October 2026 "
            "at 22 Bishopsgate, London."
        ),
        "opens_date": None,
        "opens_confirmed": False,
        "deadline_label": "15/10/2026",
        "deadline_date": "2026-10-15",
        "apply_link": "https://skadden.allhires.com/app/PositionDetails?id=473",
        "link_is_specific": True,
        "eligibility_note": (
            "Firm's own listing: \"undergraduate candidates need to have at "
            "least reached the penultimate year of their law degree or the "
            "final year of a non-law degree\" - graduates not named "
            "explicitly but not excluded either."
        ),
        "location": "London",
        "found_on": "2026-10-04",
    },
    {
        "firm": "Skadden",
        "event_name": "Online Open Day",
        "summary": (
            "A virtual open day for aspiring lawyers looking to secure a "
            "vacation scheme and training contract at the firm, covering "
            "the graduate recruitment process, the firm's work and its pro "
            "bono practice. Event held 11 November 2026, 14:00-17:00."
        ),
        "opens_date": None,
        "opens_confirmed": False,
        "deadline_label": "09/11/2026",
        "deadline_date": "2026-11-09",
        "apply_link": "https://skadden.allhires.com/app/PositionDetails?id=479",
        "link_is_specific": True,
        "eligibility_note": None,
        "location": "Virtual",
        "found_on": "2026-10-04",
    },
    # Found 2026-10-05 via a general web search, confirmed directly on
    # Kingsley Napley's own open-days page
    # (kingsleynapley.co.uk/careers/early-careers/open-days/). Not on Legal
    # Cheek's calendar at all - no needs_review row exists for it, unlike
    # this firm's other two events (see the OPEN_DAY_OVERRIDES entries
    # above). TIME-CRITICAL: applications close today, 5 October 2026 -
    # the deadline may already have passed by the time this is read.
    {
        "firm": "Kingsley Napley",
        "event_name": "Black Professionals in Law Insight Day - Kingsley Napley x Bridging Barriers",
        "summary": (
            "An in-person Insight Day run with Bridging Barriers for "
            "candidates of Black or mixed Black heritage interested in "
            "exploring a career in law, with talks from lawyers across the "
            "firm and insight into pathways into the profession. Event held "
            "23 October 2026, 10:00am-4:30pm."
        ),
        "opens_date": None,
        "opens_confirmed": False,
        "deadline_label": "05/10/2026",
        "deadline_date": "2026-10-05",
        "apply_link": "https://kingsleynapley.app.candidats.io/event/f83c578b-46f7-47d9-ad7f-d510ba9c1701",
        "link_is_specific": True,
        "eligibility_note": (
            "Firm's own wording: for candidates of Black or mixed Black "
            "heritage, aged 18+, and either a university student (second "
            "year or above), a recent graduate, or a career changer."
        ),
        "location": "London",
        "found_on": "2026-10-05",
    },
    # Found 2026-10-07 via a general web search, confirmed directly on
    # Travers Smith's own recruitment portal (traverssmithhires.app
    # .candidats.io/events - one of the candidats.io group that normally
    # arrives as an empty shell to a plain fetch; read via the browser pane
    # instead, which showed a live events list). Travers Smith has no
    # existing entry anywhere in this repo and wasn't previously confirmable
    # - the portal was genuinely empty on 4 Oct, the last time it was
    # checked. The same events page also lists several "Presentation"
    # sessions (Durham/Bristol/Cambridge/Warwick/Edinburgh/Oxford/London
    # Morning/London Evening/London Virtual) - these are standard campus-
    # style recruitment talks, not an open day/evening, insight day/evening,
    # insight scheme or first-year scheme format per Maria's brief (same
    # call as Bird & Bird's "Office Drop-In" and Skadden's "Meet the
    # Graduate Recruitment Team" webinar, both excluded as out of format
    # scope), so none of those were added. "Black Heritage Insight Evening
    # 2026" is different - the firm's own name for it is "Insight Evening",
    # it runs 4:00-7:30pm at the firm's London office with a panel of Black
    # heritage lawyers and networking, and the registration page states "for
    # any student exploring their options in law" - EDI-focused but not
    # restricted to applicants who are themselves of Black heritage, and a
    # graduate isn't excluded either (kept as a note since it isn't
    # explicitly named). The registration page (checked, including the
    # registration form itself) publishes no separate application deadline
    # at all - it's a simple RSVP (name/email/dietary/accessibility only, no
    # CV or eligibility screening), so deadline = event date, same
    # convention used for Jones Day's Open Evenings where the firm
    # publishes no closing date of its own.
    {
        "firm": "Travers Smith",
        "event_name": "Black Heritage Insight Evening",
        "summary": (
            "An in-person event featuring a panel of Black heritage lawyers "
            "at the firm sharing insight into life at a City law firm, plus "
            "networking. Event held 5 November 2026, 4:00pm-7:30pm."
        ),
        "opens_date": None,
        "opens_confirmed": False,
        "deadline_label": "05/11/2026",
        "deadline_date": "2026-11-05",
        "apply_link": "https://traverssmithhires.app.candidats.io/event/8dad8cec-56df-4a88-a245-a77850a0d5fd",
        "link_is_specific": True,
        "eligibility_note": (
            "Firm's own wording: \"for any student exploring their options "
            "in law\" - EDI-focused (a panel of Black heritage lawyers) but "
            "not restricted to applicants of Black heritage, and graduates "
            "aren't excluded either. No application deadline is published - "
            "it's a capacity-limited RSVP (name/email only, no CV or "
            "screening), so register as early as possible."
        ),
        "location": "London",
        "found_on": "2026-10-07",
    },
]


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


def build_entries():
    today = date.today()
    rows = fetch_rows()
    entries = []
    needs_review = []
    legal_cheek_keys = set()
    filtered_out = {"chambers": 0, "outside_london": 0, "apprenticeships": 0, "not_graduate_eligible": 0}

    for row in rows:
        date_el = row.select_one(".c-key-deadlines__date")
        name_el = row.select_one("h3.c-heading .name")
        event_el = row.select_one(".c-key-deadlines__name")

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

        # Barristers' chambers: wrong career route, dropped before anything
        # else so they never reach the dashboard or needs_review.
        if EXCLUDE_CHAMBERS and is_chambers(firm, event_name):
            filtered_out["chambers"] += 1
            continue

        if EXCLUDE_APPRENTICESHIPS and (
            "apprenticeship" in firm.lower() or "apprentice" in event_name.lower()
        ):
            filtered_out["apprenticeships"] += 1
            continue

        # She is a graduate - schemes for current first/second years are out.
        if GRADUATES_ONLY and not is_graduate_eligible(firm, event_name):
            filtered_out["not_graduate_eligible"] += 1
            continue

        key = (firm, event_name, deadline_label)
        legal_cheek_keys.add((firm, event_name))
        if key not in OPEN_DAY_OVERRIDES:
            # Not researched yet. Skip the obviously-regional ones so the
            # review list stays relevant, but keep anything unplaceable.
            if LONDON_ONLY and looks_non_london(firm, event_name):
                filtered_out["outside_london"] += 1
                continue
            needs_review.append({"firm": firm, "event_name": event_name, "deadline_label": deadline_label})
            continue

        location = EVENT_LOCATIONS.get((firm, event_name))
        if LONDON_ONLY and location not in LONDON_RELEVANT:
            # Either a known non-London office, or a researched event whose
            # location was never established - held back either way.
            filtered_out["outside_london"] += 1
            continue

        override = OPEN_DAY_OVERRIDES[key]
        deadline_iso = deadline_date.isoformat() if deadline_date else None

        entries.append({
            "id": f"{firm}|{event_name}|{deadline_label}".lower().replace(" ", "-").replace("/", "-"),
            "firm": firm,
            "event_name": event_name,
            "summary": describe_event(event_name),
            "location": location,
            "opens_date": override["opens_date"],
            "opens_confirmed": override["opens_confirmed"],
            "deadline_label": deadline_label,
            "deadline_date": deadline_iso,
            "apply_link": override["apply_link"],
            "link_is_specific": override["link_is_specific"],
            "eligibility_note": AUDIENCE_NOTES.get((firm, event_name)) or override["eligibility_note"],
            "source": "legal_cheek",
            "found_on": None,
        })

    # Add events verified directly on a firm's own site that Legal Cheek's
    # calendar doesn't list at all (as opposed to OPEN_DAY_OVERRIDES, which
    # only supplements a row Legal Cheek DOES show). If Legal Cheek starts
    # listing the same (firm, event_name) itself, skip the manual copy here
    # so it doesn't get shown twice - the scraped row (via OPEN_DAY_OVERRIDES
    # or needs_review) takes over from then on.
    for ev in MANUAL_EVENTS:
        if (ev["firm"], ev["event_name"]) in legal_cheek_keys:
            continue
        if EXCLUDE_CHAMBERS and is_chambers(ev["firm"], ev["event_name"]):
            filtered_out["chambers"] += 1
            continue
        if LONDON_ONLY and ev.get("location") not in LONDON_RELEVANT:
            filtered_out["outside_london"] += 1
            continue
        if EXCLUDE_APPRENTICESHIPS and (
            "apprenticeship" in ev["firm"].lower() or "apprentice" in ev["event_name"].lower()
        ):
            filtered_out["apprenticeships"] += 1
            continue
        if GRADUATES_ONLY and not is_graduate_eligible(ev["firm"], ev["event_name"]):
            filtered_out["not_graduate_eligible"] += 1
            continue
        deadline_date = parse_deadline(ev["deadline_label"], today)
        if deadline_date is not None and deadline_date < today:
            continue
        entries.append({
            "id": f"{ev['firm']}|{ev['event_name']}|{ev['deadline_label']}".lower().replace(" ", "-").replace("/", "-"),
            "firm": ev["firm"],
            "event_name": ev["event_name"],
            "summary": ev["summary"],
            "location": ev.get("location"),
            "opens_date": ev["opens_date"],
            "opens_confirmed": ev["opens_confirmed"],
            "deadline_label": ev["deadline_label"],
            "deadline_date": ev["deadline_date"],
            "apply_link": ev["apply_link"],
            "link_is_specific": ev["link_is_specific"],
            "eligibility_note": ev["eligibility_note"],
            "source": "direct",
            "found_on": ev.get("found_on"),
        })

    # Soonest deadline first; entries with an unparsed date go last.
    entries.sort(key=lambda e: (e["deadline_date"] is None, e["deadline_date"] or ""))
    return entries, needs_review, filtered_out


def main():
    entries, needs_review, filtered_out = build_entries()
    payload = {
        "source": SOURCE_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "note": (
            "London law firm Open Days / Insight Days that a graduate can apply "
            "to. Filtered out: barristers' chambers (pupillage is a different "
            "route), solicitor apprenticeships (a school-leaver route), first- "
            "and second-year insight schemes, and events tied to a firm's "
            "non-London office. Virtual sessions are kept. Every event shown has "
            "been manually verified against the firm's own site; new listings "
            "Legal Cheek starts showing are held back in needs_review until "
            "checked, not guessed at."
        ),
        "filters": {
            "london_only": LONDON_ONLY,
            "exclude_chambers": EXCLUDE_CHAMBERS,
            "exclude_apprenticeships": EXCLUDE_APPRENTICESHIPS,
            "graduates_only": GRADUATES_ONLY,
            "filtered_out_counts": filtered_out,
        },
        "events": entries,
        "needs_review": needs_review,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(entries)} verified London open day / insight day events to {OUTPUT_PATH}")
    print(
        f"Filtered out: {filtered_out['chambers']} chambers, "
        f"{filtered_out['outside_london']} outside London, "
        f"{filtered_out['apprenticeships']} apprenticeship, "
        f"{filtered_out['not_graduate_eligible']} not open to graduates"
    )
    if needs_review:
        print(f"{len(needs_review)} new/unverified entries held back - see needs_review in the output file")


if __name__ == "__main__":
    main()
