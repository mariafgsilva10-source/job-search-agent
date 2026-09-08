"""
Attach a freshly written cover letter and adapted CV to a job, and render both PDFs.

This is the hand-written route. The dashboard button does not use it: that runs
the draft-one-job workflow, which drafts through the API and pushes by itself.
Use this when a letter is written by hand, in a chat, or anywhere other than the
API, and needs putting onto the dashboard in the same shape as everything else.

    python scripts/add_draft.py <job-id> <draft.json>

<draft.json> is whatever was written, in the same shape draft_materials.py
produces:

    {"cover_letter": "<body paragraphs only>", "adapted_cv": { ... }}

What this does, in order:

1. Checks the letter against Maria's absolute drafting rules, the same
   check_letter() the API route uses. A violation stops the run and prints the
   offending text, so it gets fixed before anything is written.
2. Adds the fixed salutation and sign-off to the letter, and the fixed name and
   contact block to the CV, exactly as the API path does.
3. Writes both onto that job in docs/data.json.
4. Renders docs/pdfs/<id>_cover_letter.pdf and <id>_cv.pdf.
5. Refreshes docs/drafts.json, the small index the dashboard polls so the PDFs
   appear on the card by themselves.

Then commit and push docs/data.json, docs/drafts.json and docs/pdfs.
"""

import json
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
from draft_materials import CV_CONTACT, CV_NAME, check_letter


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
