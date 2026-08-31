"""
Render a ready-to-send PDF for each job's cover letter and adapted CV.

Uses reportlab (pure Python, no system libraries required) so it installs
reliably in GitHub Actions with a plain `pip install`. The CV layout mirrors
the dashboard's template styling (maroon accent, centred name/contact,
underlined section headings) so the PDF matches what's shown on the site.

Idempotent: skips any job that already has a recorded PDF path, so re-runs
only generate PDFs for newly-drafted jobs. Safe to run against the full
history, so older days get PDFs too, not just the batch just drafted.
"""

import json
import re
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle,
)

DOCS_DIR = Path(__file__).parent.parent / "docs"
PDF_DIR = DOCS_DIR / "pdfs"
DATA_FILE = DOCS_DIR / "data.json"

ACCENT = colors.HexColor("#791e3f")
LINE = colors.HexColor("#2a2a2a")
INK = colors.HexColor("#262626")
MUTED = colors.HexColor("#4d4d4d")

CV_NAME = "Maria Silva"
CV_CONTACT = (
    "38, Marlborough Road, Maidenhead, Berkshire &middot; +447935308070 &middot; "
    "mariafgsilva10@gmail.com &middot; linkedin.com/in/mariafgsilva10"
)


def safe_id(job_id):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", job_id or "")


def esc(s):
    s = s or ""
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


# ---------- Cover letter ----------

def render_cover_letter_pdf(job, out_path):
    text = (job.get("cover_letter") or "").strip()
    if not text or text.startswith("(drafting failed"):
        return False

    name_style = ParagraphStyle(
        "Name", fontName="Helvetica-Bold", fontSize=13, textColor=ACCENT, leading=16,
    )
    contact_style = ParagraphStyle(
        "Contact", fontName="Helvetica", fontSize=9, textColor=MUTED, leading=12,
    )
    date_style = ParagraphStyle(
        "Date", fontName="Helvetica", fontSize=10.5, textColor=INK, leading=14,
    )
    body_style = ParagraphStyle(
        "Body", fontName="Helvetica", fontSize=11, textColor=INK, leading=16,
        spaceAfter=11,
    )

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        topMargin=2.4 * cm, bottomMargin=2.4 * cm,
        leftMargin=2.2 * cm, rightMargin=2.2 * cm,
        title=f"Cover letter - {job.get('title', '')}",
    )

    story = [
        Paragraph(CV_NAME, name_style),
        Paragraph(CV_CONTACT, contact_style),
        Spacer(1, 14),
        Paragraph(date.today().strftime("%d %B %Y"), date_style),
        Spacer(1, 14),
    ]
    for para in text.split("\n\n"):
        para = para.strip()
        if para:
            story.append(Paragraph(esc(para).replace("\n", "<br/>"), body_style))

    doc.build(story)
    return True


# ---------- Adapted CV ----------

def _entry_flowables(entry, kind, row_style, sub_style, role_style, bullet_style):
    flows = []
    if kind == "education":
        left = esc(entry.get("title"))
        sub = esc(entry.get("institution"))
    else:
        loc = f" &middot; {esc(entry.get('location'))}" if entry.get("location") else ""
        left = esc(entry.get("employer")) + loc
        sub = None

    right = esc(entry.get("dateline"))
    row = Table(
        [[Paragraph(left, row_style), Paragraph(right, row_style)]],
        colWidths=[12.5 * cm, 4 * cm],
    )
    row.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    flows.append(row)

    if sub:
        flows.append(Paragraph(sub, sub_style))
    if kind != "education":
        flows.append(Paragraph(esc(entry.get("role")), role_style))

    for b in entry.get("bullets") or []:
        flows.append(Paragraph("&bull;&nbsp;&nbsp;" + esc(b), bullet_style))
    flows.append(Spacer(1, 8))
    return flows


def render_cv_pdf(job, out_path):
    cv = job.get("adapted_cv")
    if not isinstance(cv, dict) or not (cv.get("summary") or cv.get("experience")):
        return False

    name_style = ParagraphStyle(
        "CvName", fontName="Helvetica-Bold", fontSize=17, textColor=ACCENT,
        alignment=TA_CENTER, leading=20,
    )
    contact_style = ParagraphStyle(
        "CvContact", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#333333"),
        alignment=TA_CENTER, leading=12,
    )
    summary_style = ParagraphStyle(
        "Summary", fontName="Helvetica", fontSize=10, textColor=INK, leading=14.5,
    )
    heading_style = ParagraphStyle(
        "Heading", fontName="Helvetica-Bold", fontSize=9.5, textColor=ACCENT,
        leading=12, spaceBefore=10, spaceAfter=4,
    )
    row_style = ParagraphStyle(
        "Row", fontName="Helvetica-Bold", fontSize=9.5, textColor=INK, leading=12,
    )
    sub_style = ParagraphStyle(
        "Sub", fontName="Helvetica", fontSize=9.5, textColor=INK, leading=12,
    )
    role_style = ParagraphStyle(
        "Role", fontName="Helvetica-Bold", fontSize=9.5, textColor=INK, leading=12,
    )
    bullet_style = ParagraphStyle(
        "Bullet", fontName="Helvetica", fontSize=9.5, textColor=INK, leading=13,
        leftIndent=10, spaceAfter=1,
    )
    skill_style = ParagraphStyle(
        "Skill", fontName="Helvetica", fontSize=9.5, textColor=INK, leading=13,
        leftIndent=10, spaceAfter=2,
    )

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        leftMargin=2 * cm, rightMargin=2 * cm,
        title=f"CV - {job.get('title', '')}",
    )

    story = [
        Paragraph(esc(cv.get("name") or CV_NAME), name_style),
        Paragraph((cv.get("contact") or CV_CONTACT.replace("&middot;", "·")), contact_style),
        Spacer(1, 8),
        HRFlowable(width="100%", thickness=1.3, color=LINE, spaceAfter=10),
    ]

    if cv.get("summary"):
        story.append(Paragraph(esc(cv["summary"]), summary_style))
        story.append(Spacer(1, 6))

    for heading, entries, kind in (
        ("EDUCATION", cv.get("education") or [], "education"),
        ("EXPERIENCE", cv.get("experience") or [], "experience"),
    ):
        if not entries:
            continue
        story.append(Paragraph(heading, heading_style))
        story.append(HRFlowable(width="100%", thickness=1, color=LINE, spaceAfter=6))
        for e in entries:
            story.extend(_entry_flowables(e, kind, row_style, sub_style, role_style, bullet_style))

    skills = cv.get("skills") or []
    if skills:
        story.append(Paragraph("SKILLS", heading_style))
        story.append(HRFlowable(width="100%", thickness=1, color=LINE, spaceAfter=6))
        for s in skills:
            story.append(Paragraph(
                f"<b>{esc(s.get('label'))}:</b> {esc(s.get('text'))}", skill_style,
            ))

    doc.build(story)
    return True


def main():
    if not DATA_FILE.exists():
        print("No data.json found, nothing to render")
        return

    history = json.loads(DATA_FILE.read_text())
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    changed = False
    generated = 0
    failed = 0
    for day in history:
        for job in day.get("jobs", []):
            jid = safe_id(job.get("id"))
            if not jid:
                continue

            if not job.get("cover_letter_pdf"):
                out = PDF_DIR / f"{jid}_cover_letter.pdf"
                try:
                    if render_cover_letter_pdf(job, out):
                        job["cover_letter_pdf"] = f"pdfs/{out.name}"
                        changed = True
                        generated += 1
                except Exception as e:
                    print(f"  Cover letter PDF failed for {jid}: {e}")
                    failed += 1

            if not job.get("cv_pdf"):
                out = PDF_DIR / f"{jid}_cv.pdf"
                try:
                    if render_cv_pdf(job, out):
                        job["cv_pdf"] = f"pdfs/{out.name}"
                        changed = True
                        generated += 1
                except Exception as e:
                    print(f"  CV PDF failed for {jid}: {e}")
                    failed += 1

    if changed:
        DATA_FILE.write_text(json.dumps(history, indent=2))
    print(f"Generated {generated} PDF(s), {failed} failure(s)")


if __name__ == "__main__":
    main()
