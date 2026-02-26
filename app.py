from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="WI from PDF API")

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

@app.post("/api/process-pdf")
async def process_pdf(file: UploadFile = File(...), detail_level: str = Form("2")):
    content = await file.read()
    size = len(content)

    # קישור דוגמה אמיתי ל-Word
    docx_url = "https://filesamples.com/samples/document/docx/sample3.docx"

    return JSONResponse({
        "received": {
            "filename": file.filename,
            "bytes": size,
            "detail_level": detail_level
        },
        "docx_url": docx_url
    })
