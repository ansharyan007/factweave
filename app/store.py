from __future__ import annotations

import json
from contextlib import contextmanager
import os
import sqlite3
from pathlib import Path


def data_dir() -> Path:
    root = Path(os.getenv("FACTWEAVE_DATA_DIR", "data")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


@contextmanager
def connect():
    connection = sqlite3.connect(data_dir() / "knowledge.sqlite3", timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize():
    with connect() as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS documents (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, sha256 TEXT UNIQUE NOT NULL,
          status TEXT NOT NULL, pages INTEGER DEFAULT 0, processed_pages INTEGER DEFAULT 0,
          mode TEXT NOT NULL, error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS pages (
          document_id TEXT REFERENCES documents(id), number INTEGER, text TEXT NOT NULL,
          width REAL, height REAL, PRIMARY KEY(document_id,number));
        CREATE TABLE IF NOT EXISTS facts (
          id TEXT PRIMARY KEY, document_id TEXT REFERENCES documents(id), page INTEGER,
          subject_key TEXT, predicate TEXT, payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS fact_match ON facts(subject_key,predicate);
        CREATE INDEX IF NOT EXISTS fact_predicate ON facts(predicate);
        CREATE TABLE IF NOT EXISTS relationships (
          id TEXT PRIMARY KEY, left_id TEXT REFERENCES facts(id), right_id TEXT REFERENCES facts(id),
          kind TEXT, payload TEXT NOT NULL, UNIQUE(left_id,right_id));
        CREATE TABLE IF NOT EXISTS issues (
          id TEXT PRIMARY KEY, document_id TEXT REFERENCES documents(id), page INTEGER, payload TEXT NOT NULL);
        """)
        # Single-process prototype: interrupted jobs are visible and can be retried.
        db.execute("UPDATE documents SET status='failed', error='Server restarted during processing. Retry this document.' WHERE status IN ('queued','processing')")


def read_rows(db, table: str) -> list[dict]:
    assert table in {"facts", "relationships", "issues", "documents"}
    values = db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
    if table == "documents":
        return [dict(row) for row in values]
    return [json.loads(row["payload"]) for row in values]


def rows(table: str) -> list[dict]:
    with connect() as db:
        return read_rows(db, table)


def snapshot() -> dict:
    with connect() as db:
        db.execute("BEGIN")
        documents, all_facts, all_relationships, all_issues = (
            read_rows(db, table) for table in ("documents", "facts", "relationships", "issues"))
    complete = {d["id"] for d in documents if d["status"] in ("complete", "needs_review")}
    facts = [f for f in all_facts if f["document_id"] in complete]
    ids = {f["id"] for f in facts}
    relationships = [r for r in all_relationships if r["left_id"] in ids and r["right_id"] in ids]
    by_id = {f['id']: f for f in facts}
    pairs = {}
    for relation in relationships:
        pair = tuple(sorted((by_id[relation['left_id']]['document_id'], by_id[relation['right_id']]['document_id'])))
        item = pairs.setdefault(pair, {'document_ids': list(pair), 'count': 0, 'kinds': {}})
        item['count'] += 1
        item['kinds'][relation['kind']] = item['kinds'].get(relation['kind'], 0) + 1
    for document in documents:
        document['fact_count'] = sum(f['document_id'] == document['id'] for f in facts)
        document['connection_count'] = sum(p['count'] for p in pairs.values() if document['id'] in p['document_ids'])
        document['connection_diagnostic'] = (
            'Processing; results will appear when extraction finishes.' if document['id'] not in complete else
            'No supported claims extracted. Review skipped source text; scans need OCR.' if not document['fact_count'] else
            'Claims extracted, but no comparable cross-document claims found yet.' if not document['connection_count'] else
            'Open a document pair to inspect the matched claims and uncertainty.')
    return {"documents": documents, "facts": facts, "relationships": relationships,
            "document_connections": list(pairs.values()),
            "issues": [i for i in all_issues if i["document_id"] in complete],
            "predicates": sorted({f["predicate"] for f in facts}),
            "metadata": {"extractor_version": "1.0.0", "evidence": "Whitespace-normalized exact source spans; enclosing block rectangles.",
                         "disclaimer": "Claims and heuristic relationships, not verified real-world truth."}}
