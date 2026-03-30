import uuid
import re
from pathlib import Path
from typing import List, Tuple

from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse

import pdfplumber
import fitz  # PyMuPDF
from docx import Document
from docx.shared import Inches

TMP_DIR = Path("/tmp")

# עוגנים (Anchors) לחיתוך תמונות לפי שלבים – מבוסס על הטקסט שמופיע בשרטוט שלך [1](blob:https://www.microsoft365.com/42cb9126-67ba-478b-9073-3445f54b20dc)
STEP_ANCHORS = [
    ("שלב 1 – מיקום Kapton (View A)", "Fix the kapton in this position before assembly"),
    ("שלב 2 – לפני הרכבה: מילוי ג’ל מוליכות XTS-8030", "Before assembly: Fill volume"),
    ("שלב 3 – פתח מילוי (Opening for filling)", "Openning for filling"),
    ("שלב 4 – אחרי הרכבת MINID: מילוי ג’ל בין הלוחות לכיסוי תחתון", "After that MINID will be assembled"),
    ("שלב 5 – אזור תווית עליונה", "Area for label"),
]

app = FastAPI(title="WI from PDF API (Step Images + BOM)")

# CORS פתוח ל-POC (אחר כך אפשר להדק לכתובת Netlify שלך)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.get("/")
def index():
    return {
        "service": "wi-from-pdf-api",
        "endpoints": ["/api/health", "/api/process-pdf", "/api/download/{filename}"]
    }

# -----------------------------
# 1) חילוץ BOM בסיסי מתוך טקסט ה-PDF
# -----------------------------
def extract_bom_rows_from_pdf(pdf_path: Path) -> List[Tuple[str, str, str, str]]:
    """
    מחלץ טבלת BOM בפורמט: (item, qty, part_number, description)
    לפי כותרת 'ITEM QTY PART NUMBER DESCRIPTION' שמופיעה בשרטוט. [1](blob:https://www.microsoft365.com/42cb9126-67ba-478b-9073-3445f54b20dc)
    """
    text_all: List[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for p in pdf.pages:
            text_all.append(p.extract_text() or "")
    text = "\n".join(text_all)

    bom: List[Tuple[str, str, str, str]] = []
    m = re.search(
        r"ITEM\s+QTY\.?\s+PART\s+NUMBER\s+DESCRIPTION(.*?)(?:Table\s+1|SIGNED\s+DATE|UNLESS\s+OTHERWISE|$)",
        text,
        flags=re.S | re.I
    )
    if not m:
        return bom

    block = m.group(1)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in block.splitlines()]
    for ln in lines:
        if not ln:
            continue
        mm = re.match(r"^(\d+)\s+(\d+)\s+([0-9A-Za-z.\-_]+)\s+(.*)$", ln)
        if mm:
            item, qty, part, desc = mm.groups()
            bom.append((item, qty, part, desc))

    return bom

# -----------------------------
# 2) חיתוך תמונות לפי עוגני טקסט מהעמוד הראשון
# -----------------------------
def clip_from_anchor(page: fitz.Page, anchor_text: str,
                     clip_above: int = 220, clip_below: int = 80,
                     left_pad: int = 40, right_pad: int = 300):
    rects = page.search_for(anchor_text)
    if not rects:
        return None

    r = rects[0]
    for rr in rects[1:]:
        r |= rr

    clip = fitz.Rect(
        max(0, r.x0 - left_pad),
        max(0, r.y0 - clip_above),
        min(page.rect.width, r.x1 + right_pad),
        min(page.rect.height, r.y1 + clip_below),
    )
    return clip

def render_clip_to_png(pdf_path: Path, page_num: int, clip: fitz.Rect, out_path: Path, zoom: int = 2):
    doc = fitz.open(str(pdf_path))
    page = doc.load_page(page_num)
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    pix.save(str(out_path))
    doc.close()
    return out_path

# -----------------------------
# 3) בניית DOCX: BOM + תמונות לפי שלבים + צעדים תמציתיים
# -----------------------------
def build_docx_with_step_images(pdf_path: Path, bom_rows, out_docx: Path):
    doc = Document()
    doc.add_heading("הנחיות עבודה – MiNID (טיוטה)", 0)

    doc.add_heading("בטיחות", level=1)
    doc.add_paragraph("• PPE לפי הנהלים")
    doc.add_paragraph("• הגנת ESD")
    doc.add_paragraph("• נתק חשמל לפני עבודה מכנית")

    # BOM
