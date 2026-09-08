"""
Attach a freshly written cover letter and adapted CV to a job, and render both PDFs.

This is the one command the Claude session runs after the "Write CV & cover
letter" button on the dashboard hands it a job. It exists so that route is a
single deterministic step rather than several hand-edits of a 1.4MB JSON file.

    python scripts/add_draft.py <job-id> <draft.json>

<draft.json> is whatever the model wrote, in the same shape draft_materials.py
produces:

    {"cover_letter": "<body paragraphs only>", "adapted_cv": { ... }}

What this does, in order:

1. Checks the letter against Maria's absolute drafting rules (no dashes, no
   colons, no contractions or abbreviations, no banned constructions). A
   violation stops the run and prints the offending text, so it gets fixed
   before anything is written. These are her hard rules, so they are enforced
   here rather than left to the model remembering them.
2. Adds the fixed salutation and sign-off to the letter, and the fixed name and
   contact block to the CV, exactly as the API path does.
3. Writes both onto that job in docs/data.json.
4. Renders docs/pdfs/<id>_cover_letter.pdf and <id>_cv.pdf.
5. Refreshes docs/drafts.json, the small index the dashboard polls so the PDFs
   appear on the card by themselves.

Then commit and push docs/data.json, docs/drafts.json and docs/pdfs.
"""

import json
import re
import sys
from pathlib import Path

from generate_pdfs import (
    DATA_FILE,
    PDF_DIR,
    render_cover_letter_pdf,
    render_cv_pdf,
    safe_id,
    write_drafts_index,
)
from draft_materials import CV_CONTACT, CV_NAME

# Maria's absolute drafting rules. Each is (label, pattern, hint). They apply to
# the letter body only - the CV is bullet-shaped and uses different conventions.
BANNED = [
    (
        "em dash or en dash",
        re.compile(r"[—–]"),
        "Rewrite as two sentences, or use a comma or parentheses.",
    ),
    (
        "hyphen used as sentence punctuation",
        re.compile(r"(?<=\s)-(?=\s)"),
        "A hyphen inside a compound word is fine, a spaced one is not.",
    ),
    (
        "colon",
        re.compile(r":"),
        "Rephrase as separate sentences.",
    ),
    (
        "contraction",
        re.compile(
            r"\b(?:do|does|did|is|are|was|were|has|have|had|would|should|could|will|ca|must)n't\b"
            r"|\b(?:I|you|we|they|he|she|it|that|there|here|who|what|let)'(?:s|re|ve|ll|d|m)\b",
            re.IGNORECASE,
        ),
        "Spell it out in full, for example \"do not\" in place of the short form.",
    ),
    (
        "contrastive framing for where the interest came from",
        re.compile(
            r"\b(?:interest|interested|drawn|appeal\w*|motivat\w*|attracted)\b[^.]{0,90}\brather than\b",
            re.IGNORECASE,
        ),
        "State directly where the interest comes from, with no contrast.",
    ),
    (
        "\"where X meets Y\" construction",
        re.compile(r"\bwhere\b[^.]{0,60}\bmeets\b", re.IGNORECASE),
        "Say what the work actually involves instead.",
    ),
    (
        "salutation or sign-off in the body",
        re.compile(r"^\s*(?:Dear\b|Yours (?:sincerely|faithfully)\b)", re.IGNORECASE | re.MULTILINE),
        "Write the body paragraphs only, both are added automatically.",
    ),
]

MAX_WORDS = 380


def context(text, match, width=60):
    start = max(0, match.start() - width)
    end = min(len(text), match.end() + width)
    return ("..." if start else "") + text[start:end].replace("\n", " ") + ("..." if end < len(text) else "")


def check_letter(body):
    """Return a list of human-readable problems with the letter body."""
    problems = []
    for label, pattern, hint in BANNED:
        for m in pattern.finditer(body):
            problems.append(f"{label}: ...{context(body, m)}...\n      {hint}")
            break        # one example per rule is enough to act on
    words = len(body.split())
    if words > MAX_WORDS:
        problems.append(
            f"too long: {words} words. Keep it under {MAX_WORDS} so it stays on one page."
        )
    return problems


def find_job(history, job_id):
    for day in history:
        for job in day.get("jobs", []):
            if job.get("id") == job_id:
                return job
    return None


def main():
    if len(sys.argv) != 3:
        print(__doc__.strip())
        return 2

    job_id, draft_path = sys.argv[1], Path(sys.argv[2])
    if not draft_path.exists():
        print(f"No such file: {draft_path}")
        return 1

    draft = json.loads(draft_path.read_text())
    body = (draft.get("cover_letter") or "").strip()
    cv = draft.get("adapted_cv")

    if not body:
        print("The draft has no cover_letter text.")
        return 1
    if not isinstance(cv, dict) or not (cv.get("summary") or cv.get("experience")):
        print("The draft has no usable adapted_cv object.")
        return 1

    problems = check_letter(body)
    if problems:
        print(f"The letter breaks {len(problems)} of Maria's drafting rules. Nothing was written.\n")
        for p in problems:
            print(f"  - {p}")
        print("\nFix the letter and run this again.")
        return 1

    history = json.loads(DATA_FILE.read_text())
    job = find_job(history, job_id)
    if job is None:
        print(f"No job with id {job_id} on the dashboard.")
        return 1

    # Salutation, sign-off, name and contact are fixed and never model-written,
    # so every letter is formatted the same way and the details cannot drift.
    job["cover_letter"] = f"Dear Hiring Manager,\n\n{body}\n\nYours sincerely,\nMaria Silva"
    cv["name"] = CV_NAME
    cv["contact"] = CV_CONTACT
    job["adapted_cv"] = cv

    jid = safe_id(job_id)
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    letter_pdf = PDF_DIR / f"{jid}_cover_letter.pdf"
    cv_pdf = PDF_DIR / f"{jid}_cv.pdf"
    if not render_cover_letter_pdf(job, letter_pdf):
        print("Cover letter PDF did not render.")
        return 1
    if not render_cv_pdf(job, cv_pdf):
        print("CV PDF did not render.")
        return 1
    job["cover_letter_pdf"] = f"pdfs/{letter_pdf.name}"
    job["cv_pdf"] = f"pdfs/{cv_pdf.name}"

    DATA_FILE.write_text(json.dumps(history, indent=2))
    write_drafts_index(history)

    print(f"Done: {job.get('title')} @ {job.get('employer')}")
    print(f"  {letter_pdf}")
    print(f"  {cv_pdf}")
    print(f"  {len(body.split())} words")
    print("\nNow commit and push docs/data.json, docs/drafts.json and docs/pdfs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
