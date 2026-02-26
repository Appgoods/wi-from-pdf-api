import uuid
from pathlib import Path
from typing import List

from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse

import pdfplumber
from docx import Document
from docx.shared import Pt

TMP_DIR = Path("/tmp")  # דיסק זמני שמתאים ל-POC על Render

app = FastAPI(title="WI from PDF API")

# CORS פתוח ל-POC (אפשר להדק לכתובת Netlify שלך לאחר הבדיקה)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # לדוגמה: ["https://wi-from-pdf.netlify.app"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health():
    return {"status": "ok"}

def extract_text_from_pdf(pdf_path: Path) -> str:
    """חילוץ טקסט בסיסי מכל העמודים. אם המסמך סרוק—נוסיף OCR בהמשך."""
    texts: List[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            if txt.strip():
                texts.append(txt.strip())
    return "\n\n".join(texts).strip()

def build_docx_from_text(text: str, out_path: Path, title: str = "הנחיות עבודה – טיוטה"):
    """בניית DOCX פשוט עם מבנה קבוע על בסיס הטקסט שחולץ."""
    doc = Document()

    # כותרת
    doc.add_heading(title, level=0)

    # בטיחות (Placeholder)
    doc.add_heading("בטיחות", level=1)
    doc.add_paragraph("• PPE לפי הנהלים\n• הגנת ESD\n• נתק חשמל לפני עבודה מכנית")

    # צעדים (נאיבי: שורות ארוכות → צעדים)
    doc.add_heading("צעדי עבודה (טיוטה)", level=1)
    steps = []
    for line in text.splitlines():
        line = line.strip()
        if len(line) > 20 and any(c.isalpha() for c in line):
            steps.append(line)
            if len(steps) >= 12:
                break
    if steps:
        for i, st in enumerate(steps, 1):
            p = doc.add_paragraph()
            run = p.add_run(f"{i}. {st}")
            run.font.size = Pt(11)
    else:
        doc.add_paragraph("— לא נמצאו צעדים מפורשים בטקסט —")

    # סיכום
    doc.add_heading("סיכום", level=1)
    doc.add_paragraph("DOCX זה נוצר אוטומטית מקובץ ה‑PDF לצורך POC. נרחיב לחילוץ חכם בהמשך (BOM/מומנטים/מודולים).")

    doc.save(str(out_path))

@app.post("/api/process-pdf")
async def process_pdf(
    request: Request,
    file: UploadFile = File(...),
    detail_level: str = Form("2"),
):
    # בדיקת סוג קובץ ושמירה זמנית
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="נא להעלות קובץ PDF")

    pdf_path = TMP_DIR / f"pdf-{uuid.uuid4().hex}.pdf"
    pdf_bytes = await file.read()
    pdf_path.write_bytes(pdf_bytes)

    # חילוץ טקסט; אם ריק (סרוק) נציין זאת—OCR נוסיף בהמשך
    try:
        text = extract_text_from_pdf(pdf_path)
    except Exception:
        text = ""

    # יצירת DOCX אמיתי
    docx_name = f"wi-{uuid.uuid4().hex}.docx"
    docx_path = TMP_DIR / docx_name
    build_docx_from_text(text or "אין טקסט קריא (כנראה מסמך סרוק). נוסיף OCR בשלב הבא.", docx_path)

    # החזרת קישור להורדה מתוך השרת
    base_url = str(request.base_url).rstrip("/")   # https://...onrender.com
    docx_url = f"{base_url}/api/download/{docx_name}"

    return JSONResponse({
        "received": {"filename": file.filename, "bytes": len(pdf_bytes), "detail_level": detail_level},
        "docx_url": docx_url
    })

@app.get("/api/download/{filename}")
def download_docx(filename: str):
    path = TMP_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="הקובץ לא נמצא (ייתכן שפג תוקפו).")
    return FileResponse(
        path=str(path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename
    )

# (לא חובה) דף בית ידידותי במקום 404 בשורש
@app.get("/")
def index():
    return {"service": "wi-from-pdf-api",
            "endpoints": ["/api/health", "/api/process-pdf", "/api/download/{filename}"]}
