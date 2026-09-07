from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import pymupdf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import store
from .pipeline import WORKER, identifier, process

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 30 * 1024 * 1024
MAX_PAGES = 1000


@asynccontextmanager
async def lifespan(app):
    store.initialize()
    yield


app = FastAPI(title="FactWeave", description="Local PDF facts, evidence and explainable comparisons.", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0", "modes": ["rules", "ollama"]}


def ingest(content: bytes, name: str, mode: str) -> dict:
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "Maximum PDF size is 30 MB.")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(400, "File does not have a PDF signature.")
    try:
        with pymupdf.open(stream=content, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise HTTPException(422, "Password-protected PDFs are not supported. Upload an unlocked copy.")
            page_count = len(pdf)
            if not 0 < page_count <= MAX_PAGES:
                raise HTTPException(422, "PDF must contain between 1 and 1000 pages.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "PDF is damaged or unreadable.")
    digest = hashlib.sha256(content).hexdigest()
    with store.connect() as db:
        # Serialize deduplication and job creation, including concurrent requests.
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT * FROM documents WHERE sha256=?", (digest,)).fetchone()
        if existing:
            return {**dict(existing), "duplicate": True}
        doc_id = identifier()
        (store.data_dir() / f"{doc_id}.pdf").write_bytes(content)
        safe_name = name.replace("\\", "/").split("/")[-1][:200]
        db.execute("INSERT INTO documents(id,name,sha256,status,pages,mode) VALUES(?,?,?,'queued',?,?)", (doc_id, safe_name, digest, page_count, mode))
    WORKER.submit(process, doc_id)
    return {"id": doc_id, "name": safe_name, "status": "queued", "pages": page_count, "duplicate": False}


@app.post("/api/documents", status_code=202)
def upload(file: UploadFile = File(...), mode: Literal["rules", "ollama"] = Form("rules")):
    content = file.file.read(MAX_BYTES + 1)
    return ingest(content, file.filename or "document.pdf", mode)


@app.post("/api/demo", status_code=202)
def demo():
    paths = sorted((ROOT / "samples").glob("*.pdf"))
    if not paths:
        raise HTTPException(404, "Sample PDFs are absent. Run python scripts/create_samples.py.")
    return {"documents": [ingest(p.read_bytes(), p.name, "rules") for p in paths], "synthetic": True}


@app.get("/api/knowledge")
def knowledge():
    return store.snapshot()


@app.get("/api/documents")
def documents():
    return store.rows("documents")


def get_document(doc_id):
    with store.connect() as db:
        row = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Document not found.")
    return dict(row)


@app.get("/api/documents/{doc_id}")
def document(doc_id: str):
    return get_document(doc_id)


@app.post("/api/documents/{doc_id}/retry", status_code=202)
def retry(doc_id: str, mode: Literal["rules", "ollama"] = "rules"):
    get_document(doc_id)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        status = db.execute("SELECT status FROM documents WHERE id=?", (doc_id,)).fetchone()[0]
        if status != "failed":
            raise HTTPException(409, "Only failed jobs can be retried. Other documents retain their original extraction mode.")
        db.execute("DELETE FROM relationships WHERE left_id IN (SELECT id FROM facts WHERE document_id=?) OR right_id IN (SELECT id FROM facts WHERE document_id=?)", (doc_id, doc_id))
        for table in ("facts", "issues", "pages"):
            db.execute(f"DELETE FROM {table} WHERE document_id=?", (doc_id,))
        db.execute("UPDATE documents SET status='queued',processed_pages=0,error=NULL,mode=? WHERE id=?", (mode, doc_id))
    WORKER.submit(process, doc_id)
    return {"id": doc_id, "status": "queued"}


@app.get("/api/documents/{doc_id}/pdf")
def pdf_file(doc_id: str):
    doc = get_document(doc_id)
    return FileResponse(store.data_dir() / f"{doc_id}.pdf", media_type="application/pdf", filename=doc["name"], content_disposition_type="inline")


@app.get("/api/documents/{doc_id}/pages/{number}")
def page_text(doc_id: str, number: int):
    get_document(doc_id)
    with store.connect() as db:
        row = db.execute("SELECT * FROM pages WHERE document_id=? AND number=?", (doc_id, number)).fetchone()
    if not row:
        raise HTTPException(404, "Page is not available yet.")
    return dict(row)


@app.get("/api/documents/{doc_id}/pages/{number}/image")
def page_image(doc_id: str, number: int):
    doc = get_document(doc_id)
    if not 1 <= number <= doc["pages"]:
        raise HTTPException(404, "Page not found.")
    with pymupdf.open(store.data_dir() / f"{doc_id}.pdf") as pdf:
        page = pdf[number - 1]
        scale = min(1.5, 1600 / max(page.rect.width, page.rect.height))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        return Response(pix.tobytes("png"), media_type="image/png")


@app.get("/api/export")
def export():
    return Response(json.dumps(store.snapshot(), indent=2), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="factweave-knowledge.json"'})
