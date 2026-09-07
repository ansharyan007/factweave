from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pymupdf

from . import store
from .comparison import compare
from .extraction import clean, extract_model, extract_rules

WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdf-worker")


def identifier() -> str:
    return uuid.uuid4().hex


def process(document_id: str):
    try:
        with store.connect() as db:
            document = dict(db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone())
            db.execute("UPDATE documents SET status='processing',error=NULL WHERE id=?", (document_id,))
        with pymupdf.open(store.data_dir() / f"{document_id}.pdf") as pdf:
            for index in range(len(pdf)):
                page = pdf[index]
                blocks = [b for b in page.get_text("blocks", sort=True) if b[6] == 0]
                page_text = "\n".join(clean(b[4]) for b in blocks)
                page_facts, page_issues = [], []
                if len(page_text.strip()) < 30:
                    page_issues.append({"kind": "no_extractable_text", "quote": page_text,
                                        "reason": "Page has little or no text. Likely scanned/image content; OCR is not enabled. No facts invented."})
                for block in blocks:
                    text = clean(block[4])
                    if len(text) > 16000:
                        page_issues.append({"kind": "oversized_block", "quote": text[:300],
                                            "reason": "Block exceeds 16,000 characters; skipped to bound model and parsing cost."})
                        continue
                    extractor = extract_model if document["mode"] == "ollama" else extract_rules
                    try:
                        facts, issues = extractor(text)
                    except Exception as exc:
                        # Do not silently fall back or label a failed model as successful.
                        facts, issues = [], [{"kind": "model_failure", "quote": text[:500],
                                             "reason": f"Local model failed ({type(exc).__name__}). Retry with offline mode or check Ollama."}]
                    bbox = list(block[:4])
                    for fact in facts:
                        start = text.find(fact["quote"])
                        if start < 0:
                            continue
                        fact.update(id=identifier(), document_id=document_id, document_name=document["name"],
                                    page=index + 1, bbox=bbox, block_text=text,
                                    evidence_start=start, evidence_end=start + len(fact["quote"]))
                        page_facts.append(fact)
                    for issue in issues:
                        issue["bbox"] = bbox
                    page_issues.extend(issues)
                with store.connect() as db:
                    db.execute("INSERT INTO pages VALUES(?,?,?,?,?)", (document_id, index + 1, page_text, page.rect.width, page.rect.height))
                    for fact in page_facts:
                        # Only compare indexed candidates; no global all-pairs rebuild.
                        candidates = db.execute("SELECT f.payload FROM facts f JOIN documents d ON d.id=f.document_id WHERE f.subject_key=? AND f.predicate=? AND f.document_id<>? AND d.status IN ('complete','needs_review')",
                                                (fact["subject_key"], fact["predicate"], document_id)).fetchall()
                        db.execute("INSERT INTO facts VALUES(?,?,?,?,?,?)", (fact["id"], document_id, index + 1, fact["subject_key"], fact["predicate"], json.dumps(fact)))
                        for candidate in candidates:
                            previous = json.loads(candidate["payload"])
                            relation = compare(previous, fact)
                            if relation:
                                relation.update(id=identifier(), left_id=previous["id"], right_id=fact["id"])
                                db.execute("INSERT INTO relationships VALUES(?,?,?,?,?)", (relation["id"], relation["left_id"], relation["right_id"], relation["kind"], json.dumps(relation)))
                    for issue in page_issues:
                        issue.update(id=identifier(), document_id=document_id, document_name=document["name"], page=index + 1)
                        db.execute("INSERT INTO issues VALUES(?,?,?,?)", (issue["id"], document_id, index + 1, json.dumps(issue)))
                    db.execute("UPDATE documents SET processed_pages=? WHERE id=?", (index + 1, document_id))
        with store.connect() as db:
            issue_count = db.execute("SELECT count(*) FROM issues WHERE document_id=?", (document_id,)).fetchone()[0]
            db.execute("UPDATE documents SET status=? WHERE id=?", ("needs_review" if issue_count else "complete", document_id))
    except Exception as exc:
        with store.connect() as db:
            db.execute("UPDATE documents SET status='failed',error=? WHERE id=?", (f"Processing failed: {type(exc).__name__}. Retry or inspect PDF integrity.", document_id))
