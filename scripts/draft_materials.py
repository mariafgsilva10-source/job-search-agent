"""
For each new job, call the Claude API to draft a tailored cover letter
and CV bullet suggestions, using data/base_cv.md as background context.

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
- CV suggestions should be specific bullet rewrites, not vague advice

You will be given her background and a job description. Produce:
1. A tailored cover letter
2. 2-4 specific CV bullet point suggestions/tweaks relevant to this specific role

Output valid JSON only, with keys "cover_letter" and "cv_suggestions" (array of strings). \
No markdown fences, no preamble."""


def draft_for_job(job, base_cv_text):
    user_prompt = f"""BACKGROUND:
{base_cv_text}

JOB TITLE: {job['title']}
EMPLOYER: {job['employer']}
LOCATION: {job['location']}
JOB DESCRIPTION:
{job['description'][:4000]}
"""

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = resp.content[0].text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"cover_letter": text, "cv_suggestions": []}


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
            draft = {"cover_letter": f"(drafting failed: {e})", "cv_suggestions": []}
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
