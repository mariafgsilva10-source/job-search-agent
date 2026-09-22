"""
Write an edit from the dashboard into the application tracker.

Reads the payload from the PAYLOAD environment variable rather than a command
line argument, so the JSON cannot be mangled by shell quoting.

Everything here is validation. The tracker is the one file on the dashboard
that Maria edits directly, and a malformed write would leave the My
Applications tab unable to load at all, so nothing is written unless the whole
payload parses and every row makes sense. Rows are normalised to the same shape
the daily gather produces, so the two writers cannot drift apart.
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

TRACKER = Path(__file__).resolve().parent.parent / "docs" / "applications.json"

TYPES = {"open_day", "training_contract", "job"}
STAGES = {"planned", "in_progress", "submitted"}
OUTCOMES = {
    "", "Under review", "Interview booked", "Interviewed", "Assessment",
    "Place confirmed", "Offer", "Rejected", "Withdrawn",
}

MAX_ROWS = 400
FIELDS = (
    "id", "firm", "what", "type", "stage", "outcome", "event_date", "deadline",
    "link", "ref", "notes", "source", "added_on", "updated_on", "is_new",
)


def fail(message):
    print(f"Refusing to write the tracker: {message}")
    sys.exit(1)


def clean_date(value, label, row_id):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        date.fromisoformat(text)
    except ValueError:
        fail(f"row {row_id!r} has a {label} that is not a date: {text!r}")
    return text


def clean_row(raw, index, seen_ids):
    if not isinstance(raw, dict):
        fail(f"row {index} is not an object")

    row_id = str(raw.get("id") or "").strip()
    firm = str(raw.get("firm") or "").strip()
    what = str(raw.get("what") or "").strip()
    if not row_id:
        fail(f"row {index} has no id")
    if not firm or not what:
        fail(f"row {row_id!r} needs both a firm and a description")
    if row_id in seen_ids:
        fail(f"row id {row_id!r} appears more than once")
    seen_ids.add(row_id)

    row_type = str(raw.get("type") or "").strip()
    if row_type not in TYPES:
        fail(f"row {row_id!r} has an unknown type {row_type!r}")

    stage = str(raw.get("stage") or "").strip()
    if stage not in STAGES:
        fail(f"row {row_id!r} has an unknown stage {stage!r}")

    outcome = raw.get("outcome") or ""
    outcome = str(outcome).strip()
    if outcome not in OUTCOMES:
        fail(f"row {row_id!r} has an unknown status {outcome!r}")
    # A status only means anything once the application has actually gone in.
    if stage != "submitted":
        outcome = ""

    link = str(raw.get("link") or "").strip()
    if link and not link.lower().startswith(("http://", "https://")):
        fail(f"row {row_id!r} has a link that is not a web address: {link!r}")

    today = date.today().isoformat()
    return {
        "id": row_id[:120],
        "firm": firm[:120],
        "what": what[:200],
        "type": row_type,
        "stage": stage,
        "outcome": outcome or None,
        "event_date": clean_date(raw.get("event_date"), "event date", row_id),
        "deadline": clean_date(raw.get("deadline"), "deadline", row_id),
        "link": link or None,
        "ref": (str(raw.get("ref")).strip()[:60] or None) if raw.get("ref") else None,
        "notes": str(raw.get("notes") or "")[:2000],
        "source": "you" if str(raw.get("source") or "") == "you" else "claude",
        "added_on": clean_date(raw.get("added_on"), "added date", row_id) or today,
        "updated_on": today,
        "is_new": bool(raw.get("is_new")),
    }


def main():
    payload_text = os.environ.get("PAYLOAD", "")
    if not payload_text.strip():
        fail("the payload was empty")

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        fail(f"the payload is not valid JSON ({exc})")

    rows = payload.get("applications") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        fail("the payload has no list of applications")
    if len(rows) > MAX_ROWS:
        fail(f"{len(rows)} rows is more than this is meant to hold")

    seen_ids = set()
    cleaned = [clean_row(raw, i, seen_ids) for i, raw in enumerate(rows)]

    existing = {}
    if TRACKER.exists():
        try:
            existing = json.loads(TRACKER.read_text())
        except json.JSONDecodeError:
            existing = {}

    TRACKER.write_text(json.dumps({
        "generated_at": date.today().isoformat(),
        "last_gathered": existing.get("last_gathered"),
        "note": existing.get("note", ""),
        "applications": cleaned,
    }, indent=2) + "\n")

    before = len(existing.get("applications", []))
    print(f"Wrote {len(cleaned)} row(s) to {TRACKER.name} (was {before})")


if __name__ == "__main__":
    main()
