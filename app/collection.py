"""Transactional removal of document records and their owned source files.

PDFs are moved to a private quarantine before a database commit. A failed
transaction restores them. Startup recovery handles interruptions between the
filesystem operation and SQLite commit; unrelated files are never removed.
"""
from contextlib import contextmanager
from pathlib import Path
import re

from fastapi import HTTPException

from . import store

ACTIVE = {"queued", "processing"}


def source_path(doc_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", doc_id):
        raise ValueError("Invalid stored document ID")
    return store.data_dir() / f"{doc_id}.pdf"


def require_idle(document):
    if document["status"] in ACTIVE:
        raise HTTPException(409, "Wait for PDF processing to finish before removing or replacing it.")


def remove_records(db, doc_id):
    db.execute(
        "DELETE FROM relationships WHERE left_id IN (SELECT id FROM facts WHERE document_id=?) "
        "OR right_id IN (SELECT id FROM facts WHERE document_id=?)", (doc_id, doc_id))
    for table in ("facts", "issues", "pages"):
        db.execute(f"DELETE FROM {table} WHERE document_id=?", (doc_id,))
    db.execute("DELETE FROM documents WHERE id=?", (doc_id,))


@contextmanager
def mutation():
    """Hold the SQLite write lock through file staging and all record changes."""
    staged = []
    created = []
    try:
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")

            def stage(doc_id):
                original = source_path(doc_id)
                if original.exists():
                    quarantine = store.data_dir() / ".removed"
                    quarantine.mkdir(exist_ok=True)
                    target = quarantine / original.name
                    try:
                        original.replace(target)
                    except OSError as exc:
                        raise HTTPException(409, "The PDF is in use or cannot be moved. Close it and try again.") from exc
                    staged.append((original, target))

            yield db, stage, created
    except BaseException:
        for original, target in reversed(staged):
            target.replace(original)
        for path in created:
            path.unlink(missing_ok=True)
        raise
    else:
        for _, target in staged:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                # The committed deletion remains inaccessible. Retry file cleanup
                # on startup if Windows still has an open file handle.
                pass


def recover_removals():
    directory = store.data_dir() / ".removed"
    if not directory.exists():
        return
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for path in directory.iterdir():
            if not path.is_file() or not re.fullmatch(r"[0-9a-f]{32}\.pdf", path.name):
                continue
            exists = db.execute("SELECT 1 FROM documents WHERE id=?", (path.stem,)).fetchone()
            if exists:
                path.replace(source_path(path.stem))
            else:
                try:
                    path.unlink()
                except OSError:
                    pass
