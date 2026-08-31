"""
Save each job's finished CV and cover letter PDFs into the user's own Dropbox,
one folder per job, named "<Job Title> - <Employer>", with the files inside
named "CV.pdf" and "Cover Letter.pdf".

Uses a long-lived Dropbox refresh token (never expires until revoked) to mint
a short-lived access token on every run - the standard approach for
unattended automation. Nothing here ever touches Maria's actual Dropbox
password; the refresh token only grants the specific app permissions chosen
when the Dropbox app was created (recommended: "App folder" access, so this
script can only see its own dedicated folder, not the rest of her Dropbox).

Idempotent: marks each job with "dropbox_saved": true once uploaded, so
re-runs only upload newly-drafted jobs, and a job is only ever uploaded once
even if the workflow runs again.

Requires these env vars (GitHub Actions secrets):
  DROPBOX_APP_KEY
  DROPBOX_APP_SECRET
  DROPBOX_REFRESH_TOKEN

If they aren't set, the step is skipped entirely (so this script is safe to
run even before Dropbox is configured).
"""

import json
import os
import re
from pathlib import Path

import requests

DOCS_DIR = Path(__file__).parent.parent / "docs"
DATA_FILE = DOCS_DIR / "data.json"

APP_KEY = os.environ.get("DROPBOX_APP_KEY")
APP_SECRET = os.environ.get("DROPBOX_APP_SECRET")
REFRESH_TOKEN = os.environ.get("DROPBOX_REFRESH_TOKEN")

TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
UPLOAD_URL = "https://content.dropboxapi.com/2/files/upload"


def get_access_token():
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": REFRESH_TOKEN},
        auth=(APP_KEY, APP_SECRET),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def safe_folder_name(name):
    # Dropbox disallows / \ < > : " | ? * and trailing dots/spaces.
    name = re.sub(r'[/\\<>:"|?*]', "-", name or "").strip()
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:150] or "Untitled role"


def upload(access_token, local_path, dropbox_path):
    with open(local_path, "rb") as f:
        content = f.read()
    resp = requests.post(
        UPLOAD_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Dropbox-API-Arg": json.dumps({
                "path": dropbox_path,
                "mode": "overwrite",
                "autorename": False,
                "mute": True,
            }),
            "Content-Type": "application/octet-stream",
        },
        data=content,
        timeout=60,
    )
    resp.raise_for_status()


def main():
    if not (APP_KEY and APP_SECRET and REFRESH_TOKEN):
        print("Dropbox not configured (missing secrets) - skipping Dropbox save step")
        return

    if not DATA_FILE.exists():
        print("No data.json found, nothing to save")
        return

    history = json.loads(DATA_FILE.read_text())
    access_token = get_access_token()

    changed = False
    saved = 0
    failed = 0
    for day in history:
        for job in day.get("jobs", []):
            if job.get("dropbox_saved"):
                continue
            cl_pdf = job.get("cover_letter_pdf")
            cv_pdf = job.get("cv_pdf")
            if not (cl_pdf and cv_pdf):
                continue  # only save once both PDFs exist

            folder = safe_folder_name(f"{job.get('title', '')} - {job.get('employer', '')}")
            try:
                upload(access_token, DOCS_DIR / cv_pdf, f"/{folder}/CV.pdf")
                upload(access_token, DOCS_DIR / cl_pdf, f"/{folder}/Cover Letter.pdf")
                job["dropbox_saved"] = True
                changed = True
                saved += 1
            except Exception as e:
                print(f"  Dropbox save failed for {job.get('id')}: {e}")
                failed += 1

    if changed:
        DATA_FILE.write_text(json.dumps(history, indent=2))
    print(f"Saved {saved} job(s) to Dropbox, {failed} failure(s)")


if __name__ == "__main__":
    main()
