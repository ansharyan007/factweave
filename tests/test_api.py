import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.pipeline import WORKER


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('FACTWEAVE_DATA_DIR', str(tmp_path))
    with TestClient(app) as client:
        yield client
        WORKER.submit(lambda: None).result(timeout=30)


def pdf(text):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((50, 50), text)
        return doc.tobytes()


def upload(client, content, name='unseen.pdf'):
    response = client.post('/api/documents', files={'file': (name, content, 'application/pdf')})
    assert response.status_code == 202, response.text
    return response.json()


def wait(client):
    WORKER.submit(lambda: None).result(timeout=30)
    return client.get('/api/knowledge').json()


def test_upload_grounding_incremental_and_dedup(client):
    content = pdf("Orbit Works' headcount was 19 in FY2026.")
    first = upload(client, content, '../../arbitrary.pdf')
    initial = wait(client)
    fact = initial['facts'][0]
    assert first['name'] == 'arbitrary.pdf'
    assert fact['block_text'][fact['evidence_start']:fact['evidence_end']] == fact['quote']
    assert fact['bbox'][2] > fact['bbox'][0]
    assert upload(client, content, 'renamed.pdf')['duplicate'] is True
    upload(client, pdf("Orbit Works employed 27 people in FY2026."), 'another.pdf')
    updated = wait(client)
    assert len(updated['documents']) == 2
    assert len(updated['facts']) == 2
    assert updated['facts'][0]['id'] == fact['id']
    assert updated['relationships'][0]['kind'] == 'contradicts'
    assert client.get(f"/api/documents/{first['id']}/pages/1/image").headers['content-type'] == 'image/png'
    assert client.get(f"/api/documents/{first['id']}/pages/1").json()['text']
    assert client.get('/api/export').json()['facts'] == updated['facts']


def test_synthetic_four_cases(client):
    assert client.post('/api/demo').status_code == 202
    data = wait(client)
    assert {'corroborates','contradicts','reconciled'} <= {r['kind'] for r in data['relationships']}
    assert 'no_extractable_text' in {i['kind'] for i in data['issues']}
    assert 'ambiguous_statement' in {i['kind'] for i in data['issues']}
    assert len(data['facts']) == 13
    assert not any(f['predicate'] == 'operating profit' for f in data['facts'])
    for fact in data['facts']:
        assert fact['quote'] in client.get(f"/api/documents/{fact['document_id']}/pages/{fact['page']}").json()['text']


def test_rejects_invalid_and_locked_pdf(client):
    assert client.post('/api/documents', files={'file': ('bad.pdf', b'not a pdf')}).status_code == 400
    assert client.post('/api/documents', files={'file': ('bad.pdf', b'%PDF-corrupt')}).status_code == 422
    with pymupdf.open() as doc:
        doc.new_page()
        locked = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='reader')
    assert client.post('/api/documents', files={'file': ('locked.pdf', locked)}).status_code == 422
    assert client.get('/api/documents/missing').status_code == 404
    assert client.get('/api/documents/../../etc/passwd/pdf').status_code == 404


def test_upload_limit(client, monkeypatch):
    monkeypatch.setattr('app.main.MAX_BYTES', 32)
    assert client.post('/api/documents', files={'file': ('large.pdf', b'%PDF-' + b'a'*40)}).status_code == 413


def test_scanned_or_blank_page_is_reviewable(client):
    doc = upload(client, pdf(''))
    data = wait(client)
    assert data['documents'][0]['status'] == 'needs_review'
    assert not data['facts']
    assert data['issues'][0]['kind'] == 'no_extractable_text'
    assert client.get(f"/api/documents/{doc['id']}/pages/2/image").status_code == 404


def test_concurrent_duplicate_uploads(client):
    content = pdf("Orbit Works' capacity was 90 in FY2026.")
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda _: upload(client, content), range(3)))
    data = wait(client)
    assert sum(not r['duplicate'] for r in results) == 1
    assert len(data['facts']) == 1


def test_failed_job_can_retry(client, monkeypatch):
    from app import pipeline
    original = pipeline.pymupdf.open
    def broken(*args, **kwargs):
        if args and isinstance(args[0], Path):
            raise RuntimeError('test failure')
        return original(*args, **kwargs)
    monkeypatch.setattr(pipeline.pymupdf, 'open', broken)
    doc = upload(client, pdf("Orbit Works' headcount was 19 in FY2026."))
    data = wait(client)
    assert data['documents'][0]['status'] == 'failed'
    monkeypatch.setattr(pipeline.pymupdf, 'open', original)
    assert client.post(f"/api/documents/{doc['id']}/retry").status_code == 202
    assert len(wait(client)['facts']) == 1
    assert client.post(f"/api/documents/{doc['id']}/retry").status_code == 409
