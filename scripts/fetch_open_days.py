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

Some entries are for a firm's SOLICITOR APPRENTICESHIP route rather than
its graduate training contract (the firm name is suffixed
"- solicitor apprenticeship" in Legal Cheek's own listing). These are kept
in the output (Maria may still want to see them) but carry an
"eligibility_note" flagging that the apprenticeship route is a school
leaver / non-graduate entry path, not the graduate route - mirroring how
fetch_tc_deadlines.py flags graduate eligibility for Training Contracts.

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

        key = (firm, event_name, deadline_label)
        legal_cheek_keys.add((firm, event_name))
        if key not in OPEN_DAY_OVERRIDES:
            needs_review.append({"firm": firm, "event_name": event_name, "deadline_label": deadline_label})
            continue

        override = OPEN_DAY_OVERRIDES[key]
        deadline_iso = deadline_date.isoformat() if deadline_date else None

        entries.append({
            "id": f"{firm}|{event_name}|{deadline_label}".lower().replace(" ", "-").replace("/", "-"),
            "firm": firm,
            "event_name": event_name,
            "summary": describe_event(event_name),
            "opens_date": override["opens_date"],
            "opens_confirmed": override["opens_confirmed"],
            "deadline_label": deadline_label,
            "deadline_date": deadline_iso,
            "apply_link": override["apply_link"],
            "link_is_specific": override["link_is_specific"],
            "eligibility_note": override["eligibility_note"],
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
        deadline_date = parse_deadline(ev["deadline_label"], today)
        if deadline_date is not None and deadline_date < today:
            continue
        entries.append({
            "id": f"{ev['firm']}|{ev['event_name']}|{ev['deadline_label']}".lower().replace(" ", "-").replace("/", "-"),
            "firm": ev["firm"],
            "event_name": ev["event_name"],
            "summary": ev["summary"],
            "opens_date": ev["opens_date"],
            "opens_confirmed": ev["opens_confirmed"],
            "deadline_label": ev["deadline_label"],
            "deadline_date": ev["deadline_date"],
            "apply_link": ev["apply_link"],
            "link_is_specific": ev["link_is_specific"],
            "eligibility_note": ev["eligibility_note"],
        })

    # Soonest deadline first; entries with an unparsed date go last.
    entries.sort(key=lambda e: (e["deadline_date"] is None, e["deadline_date"] or ""))
    return entries, needs_review


def main():
    entries, needs_review = build_entries()
    payload = {
        "source": SOURCE_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "note": (
            "Only includes Open Day / Insight Day listings manually verified against "
            "the firm's own site. New listings Legal Cheek starts showing are held "
            "back in needs_review until checked, not guessed at."
        ),
        "events": entries,
        "needs_review": needs_review,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(entries)} verified open day / insight day events to {OUTPUT_PATH}")
    if needs_review:
        print(f"{len(needs_review)} new/unverified entries held back - see needs_review in the output file")


if __name__ == "__main__":
    main()
