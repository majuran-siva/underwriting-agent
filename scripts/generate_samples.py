"""Writes the synthetic loan files as real PDFs and phone-photo JPGs: samples/<case-id>/<filename>.

Every file carries a marker (PDF Subject / JPEG comment) naming its case and filename. The prototype's
upload step uses it to recognize a file; the documents' content comes from underwriting/demo_cases.py.

Run: .venv/bin/python -m scripts.generate_samples
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.colors import Color, black, grey
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from underwriting.demo_cases import CASES

OUT = Path(__file__).parent.parent / "samples"
WATERMARK = "SYNTHETIC – FOR TESTING ONLY"
ISSUERS = {
    "pay_stub": "Payroll statement", "employment_letter": "Letter of employment", "t4": "T4 Statement of Remuneration Paid",
    "noa": "Notice of Assessment (simulated)", "t1_general": "T1 General Income Tax and Benefit Return (simulated)",
    "business_registration": "Business name registration", "bank_statement": "Bank account statement",
    "credit_bureau": "Consumer credit report (simulated bureau)", "purchase_agreement": "Agreement of Purchase and Sale",
    "appraisal": "Residential appraisal report", "property_tax": "Final property tax bill",
    "condo_fees": "Condominium status certificate", "id": "Photo identification (specimen)",
    "lease": "Residential tenancy agreement", "mortgage_statement": "Mortgage statement",
}


def marker(case_id: str, filename: str) -> str:
    return f"UWPROTO|{case_id}|{filename}"


def lines_for(d: dict) -> list[str]:
    lines = []
    for key, value in d["fields"].items():
        label = key.replace("_", " ").capitalize()
        if isinstance(value, list):
            lines.append(f"{label}:")
            for item in value:
                lines.append("    " + "   ".join(str(v) for v in (item.values() if isinstance(item, dict) else [item])))
        elif isinstance(value, dict):
            lines.append(f"{label}:")
            lines += [f"    {k}: {v}" for k, v in value.items()]
        else:
            lines.append(f"{label}: {value}")
    return lines


def write_pdf(path: Path, case_id: str, docs: list[dict]):
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setSubject(marker(case_id, path.name))
    c.setTitle(", ".join(d["label"] for d in docs))
    meta = next((d["pdf_metadata"] for d in docs if d.get("pdf_metadata")), None)
    if meta:
        c.setProducer(meta["producer"])
        c.setCreator(meta["producer"])
    width, height = letter
    page = 1
    for d in sorted(docs, key=lambda x: x["page"]):
        while page < d["page"]:   # filler so citations like "p.9" land on the right page
            c.setFont("Helvetica", 9)
            c.setFillColor(grey)
            c.drawString(40, height - 30, f"{WATERMARK}  ·  supporting page {page}")
            c.showPage()
            page += 1
        page += 1
        c.saveState()
        c.setFillColor(Color(0.85, 0.1, 0.1, alpha=0.12))
        c.setFont("Helvetica-Bold", 40)
        c.translate(width / 2, height / 2)
        c.rotate(35)
        c.drawCentredString(0, 0, WATERMARK)
        c.restoreState()
        c.setFillColor(grey)
        c.setFont("Helvetica", 8)
        c.drawString(40, height - 30, WATERMARK)
        c.setFillColor(black)
        c.setFont("Helvetica-Bold", 15)
        c.drawString(40, height - 60, ISSUERS.get(d["type"], d["label"]))
        c.setFont("Helvetica", 10)
        c.drawString(40, height - 76, d["label"])
        y = height - 110
        c.setFont("Courier", 10)
        for line in lines_for(d):
            c.drawString(40, y, line[:95])
            y -= 15
        if d.get("hidden_text"):   # white text: invisible on the page, present in the file
            c.setFillColor(Color(1, 1, 1))
            c.setFont("Helvetica", 6)
            c.drawString(40, 40, d["hidden_text"])
        c.showPage()
    c.save()


def write_jpg(path: Path, case_id: str, d: dict):
    plain = lambda text: text.replace("–", "-")  # the bitmap font has no en dash
    img = Image.new("RGB", (1000, 1300), (250, 248, 242))
    draw = ImageDraw.Draw(img)
    big, small = ImageFont.load_default(size=34), ImageFont.load_default(size=22)
    draw.text((50, 40), plain(WATERMARK), fill=(200, 40, 40), font=small)
    draw.text((50, 90), plain(ISSUERS.get(d["type"], d["label"])), fill=(20, 20, 20), font=big)
    draw.text((50, 140), plain(d["label"]), fill=(60, 60, 60), font=small)
    y = 210
    for line in lines_for(d):
        draw.text((50, y), plain(line)[:70], fill=(25, 25, 25), font=small)
        y += 34
    img = img.rotate(-2.5 if d["confidence"] >= 0.8 else -6, expand=True, fillcolor=(90, 90, 90))
    if d["confidence"] < 0.8:
        img = img.filter(ImageFilter.GaussianBlur(3))
    img.save(path, "JPEG", quality=70, comment=marker(case_id, path.name).encode())


def main():
    for case in CASES:
        folder = OUT / case["id"]
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.iterdir():
            old.unlink()
        by_file: dict[str, list[dict]] = {}
        for d in case["documents"]:
            by_file.setdefault(d["filename"], []).append(d)
        for filename, docs in by_file.items():
            path = folder / filename
            if filename.lower().endswith(".jpg"):
                write_jpg(path, case["id"], docs[0])
            else:
                write_pdf(path, case["id"], docs)
        print(f"{case['id']}: {len(by_file)} files → {folder.relative_to(OUT.parent)}")


if __name__ == "__main__":
    main()
