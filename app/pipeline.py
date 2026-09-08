from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pymupdf

from . import store
from .comparison import compare
from .layout import document_subject, extract_layout
from .extraction import clean, extract_model, extract_rules
from .statistics import country_subject, extract_statistics, reading_blocks
from .contextual import organization_context, extract_contextual, reporting_periods

WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdf-worker")


def identifier() -> str:
    return uuid.uuid4().hex


def process(document_id: str):
    try:
        with store.connect() as db:
            document = dict(db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone())
            db.execute("UPDATE documents SET status='processing',error=NULL WHERE id=?", (document_id,))
        with pymupdf.open(store.data_dir() / f"{document_id}.pdf") as pdf:
            subject = document_subject(pdf) if document["mode"] == "rules" else None
            country = country_subject(pdf) if document["mode"] == "rules" else None
            organization = organization_context(pdf) if document["mode"] == "rules" else None
            periods = reporting_periods(pdf) if document['mode'] == 'rules' else {}
            for index in range(len(pdf)):
                page = pdf[index]
                blocks = [b for b in page.get_text("blocks", sort=True) if b[6] == 0]
                page_text = "\n".join(clean(b[4]) for b in blocks)
                prose = reading_blocks(blocks)
                # Preserve raw blocks for layout evidence, and joined reading
                # spans for prose quotes. Reconstruction only adds whitespace.
                joined = [b[4] for b in prose if len(b[5]) > 1]
                if joined:
                    page_text += "\n[Reconstructed reading spans]\n" + "\n".join(joined)
                page_facts, page_issues = [], []
                if len(page_text.strip()) < 30:
                    page_issues.append({"kind": "no_extractable_text", "quote": page_text,
                                        "reason": "Page has little or no text. Likely scanned/image content; OCR is not enabled. No facts invented."})
                for block in prose:
                    text = clean(block[4])
                    if len(text) > 16000:
                        page_issues.append({"kind": "oversized_block", "quote": text[:300],
                                            "reason": "Block exceeds 16,000 characters; skipped to bound model and parsing cost."})
                        continue
                    extractor = extract_model if document["mode"] == "ollama" else extract_rules
                    try:
                        facts, issues = extractor(text)
                        if document["mode"] == "rules":
                            extra = [f for f in extract_statistics(text, country)
                                     if not any(f["quote"] == old["quote"] for old in facts)]
                            facts.extend(extra)
                            contextual = [f for f in extract_contextual(text, organization, document_id)
                                          if not any(f['quote'] == old['quote'] and f['predicate'] == old['predicate'] for old in facts)]
                            facts.extend(contextual)
                            extra.extend(contextual)
                            recovered = {f["quote"] for f in extra}
                            issues = [i for i in issues if i.get("quote") not in recovered]
                    except Exception as exc:
                        # Do not silently fall back or label a failed model as successful.
                        facts, issues = [], [{"kind": "extraction_failure", "quote": text[:500],
                                             "reason": f"Extractor failed ({type(exc).__name__}); this block needs review."}]
                    bbox = list(block[:4])
                    for fact in facts:
                        definition = periods.get(fact['context'].get('period'))
                        if definition:
                            fact['context'].update({k: v for k,v in definition.items() if k != 'anchor'})
                            fact.setdefault('evidence_parts', []).append(dict(definition['anchor']))
                        start = text.find(fact["quote"])
                        if start < 0:
                            continue
                        fact.update(id=identifier(), document_id=document_id, document_name=document["name"],
                                    page=index + 1, bbox=bbox, block_text=text,
                                    evidence_start=start, evidence_end=start + len(fact["quote"]))
                        if len(block[5]) > 1:
                            fact.setdefault("evidence_parts", []).extend(
                                {"role": "joined source fragment", "page": index + 1,
                                 "quote": clean(part[4]), "bbox": list(part[:4])} for part in block[5])
                        for part in fact.get("evidence_parts", []):
                            part["document_id"] = document_id
                        page_facts.append(fact)
                    for issue in issues:
                        issue["bbox"] = bbox
                    page_issues.extend(issues)
                for fact in extract_layout(page, index + 1, subject):
                    fact.update(id=identifier(), document_id=document_id, document_name=document["name"], page=index+1)
                    for part in fact["evidence_parts"]:
                        part["document_id"] = document_id
                    page_facts.append(fact)
                with store.connect() as db:
                    # Serialize candidate reads with document deletion/replacement
                    # so a referenced fact cannot disappear before its new edge.
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("INSERT INTO pages VALUES(?,?,?,?,?)", (document_id, index + 1, page_text, page.rect.width, page.rect.height))
                    for fact in page_facts:
                        # Only compare indexed candidates; no global all-pairs rebuild.
                        candidates = db.execute("SELECT f.payload FROM facts f JOIN documents d ON d.id=f.document_id WHERE f.predicate=? AND f.document_id<>? AND d.status IN ('complete','needs_review')",
                                                (fact["predicate"], document_id)).fetchall()
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
