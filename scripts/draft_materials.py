"""
For each new job, call the Claude API to draft a tailored cover letter
and a CV adapted to that specific role, using data/base_cv.md as background context.

Requires: ANTHROPIC_API_KEY environment variable.
"""

import os
import json
from pathlib import Path
from datetime import date
import anthropic

DATA_DIR = Path(__file__).parent.parent / "data"
DOCS_DIR = Path(__file__).parent.parent / "docs"

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

SYSTEM_PROMPT = """You are drafting job application materials for Maria Fernanda Silva, \
a UK-based aspiring paralegal. Follow her stated writing preferences exactly:

- Purpose-led opening, no fluff, no academic framing, no absolutist language
- Concise, clear, structured, polished but natural
- Mirror the employer's own wording where the job ad gives you language to mirror
- Emphasise: disputes experience, commercial awareness, client-focused judgement, \
attention to detail, drafting/research and litigation-adjacent capability
- Cover letters should be under 400 words, no generic filler paragraphs

You will be given her full background/base CV and a job description. Produce two \
documents, both ready to send as-is:

1. A tailored cover letter (under 400 words, no generic filler).
2. Her CV adapted specifically for this role: reorder sections/bullets so the most \
relevant experience leads, tighten and re-word bullets to mirror the job ad's own \
language where it's accurate to do so, and trim or de-emphasise less relevant detail. \
Never invent experience, qualifications, dates, employers, or achievements that aren't \
in her background — only reorder, re-word, and re-emphasise what's true. Keep the same \
overall structure (profile, education, experience, skills) and markdown formatting \
style as the background CV, and roughly the same length.

Always produce both documents using whatever information you're given, even if the job \
description is partial, truncated, or thin. Never ask a question, request more detail, \
or write anything other than the two documents — do your best with what's provided.

Output valid JSON only, with keys "cover_letter" and "adapted_cv" (both strings, plain \
text/markdown, no nested JSON). No markdown fences, no preamble."""


def draft_for_job(job, base_cv_text):
    user_prompt = f"""BACKGROUND (Maria's full base CV):
{base_cv_text}

JOB TITLE: {job['title']}
EMPLOYER: {job['employer']}
LOCATION: {job['location']}
JOB DESCRIPTION:
{job['description'][:4000]}
"""

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = resp.content[0].text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"cover_letter": text, "adapted_cv": ""}


def main():
    new_jobs_file = DATA_DIR / "new_jobs.json"
    if not new_jobs_file.exists():
        print("No new_jobs.json found, nothing to draft")
        return

    new_jobs = json.loads(new_jobs_file.read_text())
    base_cv_text = (DATA_DIR / "base_cv.md").read_text()

    drafted = []
    for job in new_jobs:
        print(f"Drafting for: {job['title']} @ {job['employer']}")
        try:
            draft = draft_for_job(job, base_cv_text)
        except Exception as e:
            print(f"  Failed: {e}")
            draft = {"cover_letter": f"(drafting failed: {e})", "adapted_cv": ""}
        drafted.append({**job, **draft})

    # Load existing dashboard history, prepend today's batch
    dashboard_file = DOCS_DIR / "data.json"
    history = []
    if dashboard_file.exists():
        history = json.loads(dashboard_file.read_text())

    today_entry = {"date": str(date.today()), "jobs": drafted}
    history.insert(0, today_entry)
    history = history[:30]  # keep last 30 days

    DOCS_DIR.mkdir(exist_ok=True)
    dashboard_file.write_text(json.dumps(history, indent=2))
    print(f"Wrote {len(drafted)} drafted jobs to dashboard")


if __name__ == "__main__":
    main()
