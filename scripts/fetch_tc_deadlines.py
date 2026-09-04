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
    # --- Batch 2, researched 2026-09-04 against each firm's own site. ---
    ("Winston Taylor", "Dublin Training Contract"): {
        "opens_date": "2026-09-01",
        "opens_confirmed": False,
        "apply_link": "https://www.taylorwessing.com/en/careers/ireland",
        "eligibility_note": "Open to those who've completed (or are completing) the FE1 exams - no vacation scheme or final-year-only restriction stated.",
    },
    ("Travers Smith", "Direct Training Contract 1"): {
        "opens_date": "2026-09-18",
        "opens_confirmed": True,
        "apply_link": "https://traverssmithhires.app.candidats.io/roles",
        "eligibility_note": "Firm states direct applicants (via Recruitment Days) have the same chances as Vacation Scheme applicants - no vacation scheme required.",
    },
    ("Travers Smith", "Direct Training Contract 2"): {
        "opens_date": "2026-10-16",
        "opens_confirmed": True,
        "apply_link": "https://traverssmithhires.app.candidats.io/roles",
        "eligibility_note": "Second direct-application window at the same firm, same policy - no vacation scheme required.",
    },
    ("TLT", "Belfast Training Contract"): {
        "opens_date": "2026-09-01",
        "opens_confirmed": True,
        "apply_link": "https://apply.tlt.com/vacancies/4932/apply/",
        "eligibility_note": "Open to law graduates from England, Wales and Northern Ireland - no vacation scheme required.",
    },
    ("Slaughter and May", "Training Contract 2029/2030"): {
        "opens_date": "2026-08-17",
        "opens_confirmed": True,
        "apply_link": "https://joinus.slaughterandmay.com/V2/Vacancy",
        "eligibility_note": "Open to finalists and graduates, law or non-law - firm states no legal work experience is required to apply.",
    },
    ("CMS", "England Training Contract"): {
        "opens_date": "2026-10-01",
        "opens_confirmed": True,
        "apply_link": "https://cmsemergingtalent.com/programmes/england-wales-ni/training-contract/",
        "eligibility_note": "Firm's eligibility explicitly includes graduates of law and non-law subjects and career changers - no vacation scheme required.",
    },
    ("CMS", "Scotland Training Contract"): {
        "opens_date": "2026-09-24",
        "opens_confirmed": True,
        "apply_link": "https://cmsemergingtalent.com/programmes/scotland/training-contract/",
        "eligibility_note": "Same firm-wide graduate eligibility as the England route - no vacation scheme required.",
    },
    ("Irwin Mitchell", "Training Contract (business services group)"): {
        "opens_date": "2026-09-01",
        "opens_confirmed": False,
        "apply_link": "https://www.irwinmitchell.com/about-us/careers/training-contracts",
        "eligibility_note": "Eligibility explicitly includes law or non-law graduates - the firm currently runs no legal work placement route at all, so nothing is gated behind one.",
    },
    ("Irwin Mitchell", "Training Contract (legal services for individuals)"): {
        "opens_date": "2026-09-01",
        "opens_confirmed": False,
        "apply_link": "https://www.irwinmitchell.com/about-us/careers/training-contracts",
        "eligibility_note": "Eligibility explicitly includes law or non-law graduates - no vacation scheme required.",
    },
    ("Linklaters", "Training Contract"): {
        "opens_date": "2026-09-01",
        "opens_confirmed": False,
        "apply_link": "https://linklaters.apply.cappats.com/Jobs",
        "eligibility_note": "Open to penultimate/final-year students, graduates and postgraduates - the firm asks for general legal work experience (paralegal role, vacation scheme or internship, any of the three), not specifically its own vacation scheme.",
    },
    ("Akin", "Middle East Training Programme"): {
        "opens_date": "2026-09-01",
        "opens_confirmed": False,
        "apply_link": "https://www.akingump.com/en/careers/middle-east-early-careers/uae-early-careers",
        "eligibility_note": "Explicitly aimed at law graduates (or non-law graduates with a PGDL) who've already passed LPC/SQE1 and SQE2 - a graduate-only route by design, no vacation scheme required.",
    },
    ("DWF", "Direct Training Contract"): {
        "opens_date": "2026-09-01",
        "opens_confirmed": False,
        "apply_link": "https://dwfgroup.com/en/careers/join-us/early-careers/training-contract",
        "eligibility_note": "Firm's own site implies direct (non-vacation-scheme) training contract applications remain open outside Scotland - no graduate exclusion stated.",
    },
    ("Brabners", "Training Contract"): {
        "opens_date": "2026-10-01",
        "opens_confirmed": True,
        "apply_link": "https://www.brabners.com/careers/early-law-careers-opportunities",
        "eligibility_note": "Firm confirms a direct training contract route exists alongside the vacation scheme; eligibility includes postgraduates and degree-holders - no vacation scheme required.",
    },
    ("Withers", "Training Contract 2029"): {
        "opens_date": "2026-10-01",
        "opens_confirmed": True,
        "apply_link": "https://www.withersworldwide.com/en-gb/careers/students-and-graduates/united-kingdom/training-in-london",
        "eligibility_note": "Firm welcomes applicants \"at all stages of their careers\", including those who've completed their degree - no vacation scheme required.",
    },
    ("Weightmans", "Training Contract"): {
        "opens_date": "2026-09-30",
        "opens_confirmed": False,
        "apply_link": "https://www.weightmans.com/careers/early-careers/training-contracts/",
        "eligibility_note": "Open to graduates studying towards or holding the LPC/SQE route - no vacation scheme required.",
    },
    ("Charles Russell Speechlys", "Cheltenham Direct Training Contract"): {
        "opens_date": "2026-10-01",
        "opens_confirmed": False,
        "apply_link": "https://www.charlesrussellspeechlys.com/en/careers/early-talent/uk-graduate-opportunities/apply/",
        "eligibility_note": "Firm's FAQ explicitly welcomes \"those that have already graduated\" via a direct training contract route separate from the placement scheme - one firm-wide policy across all its offices.",
    },
    ("Charles Russell Speechlys", "Guilford Direct Training Contract"): {
        "opens_date": "2026-10-01",
        "opens_confirmed": False,
        "apply_link": "https://www.charlesrussellspeechlys.com/en/careers/early-talent/uk-graduate-opportunities/apply/",
        "eligibility_note": "Same firm-wide policy as Cheltenham/London - graduates explicitly welcomed, no vacation scheme required.",
    },
    ("Charles Russell Speechlys", "London Direct Training Contract"): {
        "opens_date": "2026-10-01",
        "opens_confirmed": False,
        "apply_link": "https://www.charlesrussellspeechlys.com/en/careers/early-talent/uk-graduate-opportunities/apply/",
        "eligibility_note": "Same firm-wide policy as Cheltenham/Guildford - graduates explicitly welcomed, no vacation scheme required.",
    },
    ("Osborne Clarke", "Training Contract 2029"): {
        "opens_date": "2026-10-01",
        "opens_confirmed": True,
        "apply_link": "https://join.osborneclarke.com/apply",
        "eligibility_note": "Firm's own \"Apply\" page lists a \"Graduate or Career Changer\" direct Training Contract route for those who can't do the summer Vacation Scheme.",
    },
    ("Cripps", "Training Contract"): {
        "opens_date": "2026-10-05",
        "opens_confirmed": False,
        "apply_link": "https://www.cripps.co.uk/join-us/graduates-and-students/trainee-solicitor-programme/",
        "eligibility_note": "Firm explicitly welcomes \"graduates who have already completed their studies\" - no vacation scheme required.",
    },
    ("Mayer Brown", "Training Contract"): {
        "opens_date": "2026-09-01",
        "opens_confirmed": True,
        "apply_link": "https://www.apply4law.com/mayerbrown/",
        "eligibility_note": "Firm's FAQ states graduates can apply directly at any point in the cycle - the vacation scheme is recommended but not required.",
    },
    ("Kingsley Napley", "Training Contract"): {
        "opens_date": "2026-12-01",
        "opens_confirmed": False,
        "apply_link": "https://apply.candidats.io/a7d4f5ac-60fc-4351-9990-15b280543d24?utm_campaign=KNwebsite",
        "eligibility_note": "Firm explicitly welcomes \"candidates who already hold a degree\" - no vacation scheme required.",
    },
    ("Russell-Cooke", "Training Contract"): {
        "opens_date": "2026-11-03",
        "opens_confirmed": True,
        "apply_link": "https://russell-cooke.grad.allhires.com/app/",
        "eligibility_note": "Firm's FAQ explicitly offers the direct training contract route to those who can't attend the vacation scheme - no vacation scheme required.",
    },
    ("Broadfield", "Training Contract"): {
        "opens_date": "2026-09-01",
        "opens_confirmed": True,
        "apply_link": "https://broadfield.grad.allhires.com/app/",
        "eligibility_note": "Eligibility is simply holding/completing a qualifying law route by Sept 2027 - no vacation scheme or final-year-only restriction stated.",
    },
    ("King & Spalding", "Training Contract"): {
        "opens_date": "2026-09-01",
        "opens_confirmed": False,
        "apply_link": "https://kslaw.grad.allhires.com/app/",
        "eligibility_note": "Firm's own site explicitly lists \"have already graduated\" as an eligible route - no vacation scheme required.",
    },
    ("Winckworth Sherwood", "Training Contract"): {
        "opens_date": "2026-12-01",
        "opens_confirmed": False,
        "apply_link": "https://www.apply4law.com/winckworths/",
        "eligibility_note": "Firm accepts applications from \"law and non-law undergraduates and graduates\" - no vacation scheme mentioned anywhere on the site.",
    },
    ("Foot Anstey", "Training Contract"): {
        "opens_date": "2026-12-01",
        "opens_confirmed": False,
        "apply_link": "https://footanstey.app.candidats.io/roles",
        "eligibility_note": "Firm's FAQ explicitly says a vacation scheme isn't required - \"some people... don't do one at all\" and are still considered.",
    },
    ("Stephenson Harwood", "London Training Contract"): {
        "opens_date": "2026-10-05",
        "opens_confirmed": True,
        "apply_link": "https://shlegal.app.candidats.io/roles",
        "eligibility_note": "Firm's site explicitly states \"you may also have already graduated\" - no vacation scheme required.",
    },
    ("Bevan Brittan", "Training Contract"): {
        "opens_date": "2027-01-01",
        "opens_confirmed": False,
        "apply_link": "https://www.bevanbrittan.com/careers/opportunities/trainee-solicitors/",
        "eligibility_note": "Firm explicitly states it \"also consider[s] direct applicants for training contracts\" alongside graduates - no vacation scheme required.",
    },
    ("Farrer & Co", "Training Contract"): {
        "opens_date": "2026-11-01",
        "opens_confirmed": False,
        "apply_link": "https://farrer.grad.allhires.com/app/",
        "eligibility_note": "Firm welcomes \"graduates from any academic discipline\" and runs the vacation scheme and training contract as separate application processes.",
    },
    ("RPC", "Bristol Training Contract"): {
        "opens_date": "2026-10-01",
        "opens_confirmed": True,
        "apply_link": "https://www.rpclegal.com/careers/early-talent/uk/training-contract/bristol-training-contract/",
        "eligibility_note": "Firm's own site states \"graduates can apply at any time\" - no vacation scheme required.",
    },
    ("Payne Hicks Beach", "Training Contract"): {
        "opens_date": "2026-09-01",
        "opens_confirmed": False,
        "apply_link": "https://phb.grad.allhires.com/app/",
        "eligibility_note": "Firm recruits \"both law and non-law graduates and also mature students\" - no vacation scheme mentioned as a prerequisite.",
    },
    ("Ashfords", "Bristol Training Contract"): {
        "opens_date": "2026-11-01",
        "opens_confirmed": True,
        "apply_link": "https://ashfords.app.candidats.io/",
        "eligibility_note": "Firm runs a standalone Assessment Centre route separate from the Summer Scheme, open to anyone \"at least\" in their qualifying study year - graduates included.",
    },
    ("Ashfords", "Exeter Training Contract"): {
        "opens_date": "2026-11-01",
        "opens_confirmed": True,
        "apply_link": "https://ashfords.app.candidats.io/",
        "eligibility_note": "Same firm-wide policy as Bristol - firm confirms eligibility criteria are identical across both locations.",
    },
    ("Bates Wells", "Training Contract"): {
        "opens_date": "2026-12-01",
        "opens_confirmed": True,
        "apply_link": "https://bateswells.grad.allhires.com/app/",
        "eligibility_note": "Firm's FAQ explicitly confirms it \"consider[s] all direct training contract applications\" - no vacation scheme required.",
    },
    ("Wedlake Bell", "Training Contract"): {
        "opens_date": "2026-11-01",
        "opens_confirmed": True,
        "apply_link": "https://wedlakebell.app.candidats.io/roles",
        "eligibility_note": "Firm's own criteria explicitly list \"already graduated with a law/non-law degree\" as qualifying routes - no vacation scheme required.",
    },
    ("Fried Frank", "Training Contract"): {
        "opens_date": "2026-09-01",
        "opens_confirmed": False,
        "apply_link": "https://www.friedfrank.com/careers/attorneyjobopportunities?gh_jid=5680560004",
        "eligibility_note": "Firm's own page states it \"welcome[s] graduates and those changing careers\" - no vacation scheme required.",
    },
    ("BCLP", "Training Contract 2028/29"): {
        "opens_date": "2026-10-13",
        "opens_confirmed": True,
        "apply_link": "https://apply.candidats.io/5a98a4ec-b014-4b41-81d9-679f3e0893eb",
        "eligibility_note": "Firm's FAQ explicitly lists \"graduates and postgraduates from any discipline\" as eligible for the Direct Training Contract route - a separate route from the Vacation Scheme.",
    },
    ("Sullivan & Cromwell", "Training Contract"): {
        "opens_date": "2027-05-03",
        "opens_confirmed": True,
        "apply_link": "https://sullcrom.grad.allhires.com/",
        "eligibility_note": "Firm's site explicitly includes \"graduates and postgraduates\" alongside students - no vacation scheme required.",
    },
    ("Morgan Lewis", "Training Contract"): {
        "opens_date": "2026-10-01",
        "opens_confirmed": False,
        "apply_link": "https://www.apply4law.com/morganlewis/",
        "eligibility_note": "Firm states the vacation scheme and training contract are both open to \"graduates\" separately - the vacation scheme is presented as optional, not a prerequisite.",
    },
    ("Eversheds Sutherland", "Edinburgh Training Contract 2029"): {
        "opens_date": "2027-03-01",
        "opens_confirmed": True,
        "apply_link": "https://eversheds-sutherland.grad.allhires.com/app/",
        "eligibility_note": "Firm confirms the process is the same whether applying via the Vacation Scheme or applying directly, and explicitly welcomes those \"who've already graduated\".",
    },
    ("Burges Salmon", "Bristol Direct Training Contract"): {
        "opens_date": "2026-10-01",
        "opens_confirmed": False,
        "apply_link": "https://www.burges-salmon.com/jobs/",
        "eligibility_note": "Firm's own listing explicitly welcomes \"applicants that have graduated or are changing careers\" - a direct (non-vacation-scheme) route by design.",
    },
    ("Paul Hastings", "Direct Training Contract"): {
        "opens_date": "2026-01-05",
        "opens_confirmed": False,
        "apply_link": "https://paulhastings.grad.allhires.com/",
        "eligibility_note": "Firm's early-careers routes are open to \"final-year non-law students and graduates\", with the training contract application handled separately from the PHirst Steps scheme.",
    },
    ("HFW", "Training Contract"): {
        "opens_date": "2026-09-01",
        "opens_confirmed": False,
        "apply_link": "https://hfw.grad.allhires.com/",
        "eligibility_note": "Firm's own site states outright: \"You can also apply for a Training Contract without completing a vacation scheme.\"",
    },
    ("K&L Gates", "Training Contract"): {
        "opens_date": "2026-11-01",
        "opens_confirmed": False,
        "apply_link": "https://klgateseurope.bigredsky.com/page.php?pageID=160&windowUID=0&AdvertID=1071",
        "eligibility_note": "Firm welcomes law and non-law applicants without restricting to current penultimate/final-year status - no vacation scheme required.",
    },
    ("Walker Morris", "Direct Training Contract"): {
        "opens_date": "2026-04-30",
        "opens_confirmed": False,
        "apply_link": "https://walkermorris.grad.allhires.com/app/",
        "eligibility_note": "Firm runs a dedicated Direct Training Contract route for people who can't commit to the full vacation scheme (e.g. because they're working or studying) - graduates welcomed.",
    },
    # --- Excluded: confirmed to require this firm's own vacation scheme first,
    # or otherwise not open to direct graduate applicants. Kept here (rather
    # than just omitted) so it's obvious on inspection that these were
    # checked, not missed. ---
    ("Gateley", "Training Contract"): None,  # recruits all trainees from its own summer vacation placements
    ("Davis Polk & Wardwell", "Training Programme"): None,  # filled exclusively via the vacation scheme
    # --- Researched 2026-09-04 but left OUT deliberately (not None, not
    # included): each firm's own site was ambiguous or contradictory on
    # graduate/vacation-scheme eligibility, so these stay in needs_review
    # until a clearer source is found rather than risking a wrong guess
    # either way. See conversation notes for what was checked:
    #   - Lawrence Stephens (Training Contract): no clear statement either way
    #   - DAC Beachcroft (Training Contract): no clear statement either way
    #   - Thomson Snell & Passmore (Training Contract): no clear statement either way
    #   - Kennedys (Training Contract): every live vacancy checked shows "closed"
    #   - Wiggin (Training Contract): no clear statement on graduates specifically
    #   - Watson Farley & Williams (Direct Training Contract): no clear statement either way
    #   - Hogan Lovells Cadwalader (London Training Contract): firm identity itself
    #     unconfirmed (possible 2025 merger of Hogan Lovells + Cadwalader) - held
    #     back until that can be verified independently.
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
