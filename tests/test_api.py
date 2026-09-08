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


def test_delete_removes_owned_data_and_preserves_other_links(client):
    from app import store
    a = upload(client, pdf("Orbit Works' headcount was 19 in FY2026."))
    upload(client, pdf("Orbit Works employed 27 people in FY2026."), 'b.pdf')
    upload(client, pdf("Orbit Works' headcount was 27 in FY2026."), 'c.pdf')
    before = wait(client)
    retained = next(r for r in before['relationships'] if r['kind'] == 'corroborates')
    assert client.delete(f"/api/documents/{a['id']}").status_code == 200
    after = client.get('/api/knowledge').json()
    assert len(after['documents']) == 2
    assert len(after['facts']) == 2
    assert after['relationships'] == [retained]
    assert not (store.data_dir() / f"{a['id']}.pdf").exists()
    assert client.get(f"/api/documents/{a['id']}/pdf").status_code == 404
    assert client.get(f"/api/documents/{a['id']}/pages/1").status_code == 404
    assert client.delete(f"/api/documents/{a['id']}").status_code == 404
    with store.connect() as db:
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        for table in ('facts', 'issues', 'pages'):
            assert db.execute(f'SELECT count(*) FROM {table} WHERE document_id=?', (a['id'],)).fetchone()[0] == 0


def test_replace_rebuilds_links_and_allows_reupload_of_old_content(client):
    from app import store
    old_content = pdf("Orbit Works' headcount was 19 in FY2026.")
    a = upload(client, old_content)
    upload(client, pdf("Orbit Works employed 27 people in FY2026."), 'b.pdf')
    before = wait(client)
    assert before['relationships'][0]['kind'] == 'contradicts'
    stable = next(f for f in before['facts'] if f['document_id'] != a['id'])
    new_content = pdf("Orbit Works' headcount was 27 in FY2026.")
    response = client.put(f"/api/documents/{a['id']}", files={'file': ('updated.pdf', new_content)})
    assert response.status_code == 202
    new_id = response.json()['id']
    assert response.json()['replaced_id'] == a['id']
    after = wait(client)
    assert len(after['documents']) == 2
    assert after['relationships'][0]['kind'] == 'corroborates'
    assert stable in after['facts']
    assert client.get(f'/api/documents/{new_id}/pdf').content == new_content
    assert not (store.data_dir() / f"{a['id']}.pdf").exists()
    assert not upload(client, old_content)['duplicate']
    assert len(wait(client)['documents']) == 3


def test_invalid_duplicate_and_unchanged_replacement_preserve_original(client):
    a_content, b_content = pdf("Orbit Works' headcount was 19 in FY2026."), pdf('Other source document.')
    a = upload(client, a_content)
    upload(client, b_content)
    before = wait(client)
    for content, status in [(b'broken', 400), (b'%PDF-broken', 422), (b_content, 409)]:
        assert client.put(f"/api/documents/{a['id']}", files={'file': ('bad.pdf', content)}).status_code == status
        assert client.get('/api/knowledge').json() == before
    same = client.put(f"/api/documents/{a['id']}", files={'file': ('renamed.pdf', a_content)})
    assert same.json()['duplicate']
    assert same.json()['id'] == a['id']
    assert client.get('/api/knowledge').json() == before


def test_clear_requires_confirmation_and_removes_only_registered_uploads(client):
    from app import store
    upload(client, pdf("Orbit Works' headcount was 19 in FY2026."))
    upload(client, pdf(''))
    before = wait(client)
    sentinel = store.data_dir() / 'keep-original.pdf'
    sentinel.write_bytes(b'original source outside the uploaded collection')
    assert client.post('/api/collection/reset').status_code == 422
    assert client.post('/api/collection/reset', json={'confirm': False}).status_code == 422
    assert client.get('/api/knowledge').json() == before
    assert client.post('/api/collection/reset', json={'confirm': True}).json()['deleted_documents'] == 2
    after = client.get('/api/export').json()
    assert all(after[key] == [] for key in ['documents', 'facts', 'issues', 'relationships', 'predicates'])
    assert sentinel.exists()
    assert list(store.data_dir().glob('*.pdf')) == [sentinel]
    assert client.post('/api/collection/reset', json={'confirm': True}).json()['deleted_documents'] == 0
    assert client.post('/api/demo').status_code == 202
    assert len(wait(client)['facts']) == 13


@pytest.mark.parametrize('status', ['queued', 'processing'])
def test_active_documents_cannot_be_removed_or_replaced(client, monkeypatch, status):
    from app import store
    content = pdf("Orbit Works' headcount was 19 in FY2026.")
    with monkeypatch.context() as context:
        context.setattr(WORKER, 'submit', lambda *args: None)
        doc = upload(client, content)
    with store.connect() as db:
        db.execute('UPDATE documents SET status=? WHERE id=?', (status, doc['id']))
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 409
    assert client.put(f"/api/documents/{doc['id']}", files={'file': ('new.pdf', content)}).status_code == 409
    assert client.post('/api/collection/reset', json={'confirm': True}).status_code == 409
    assert client.get(f"/api/documents/{doc['id']}/pdf").content == content


def test_removal_rollback_restores_pdf_and_database(client, monkeypatch):
    content = pdf("Orbit Works' headcount was 19 in FY2026.")
    doc = upload(client, content)
    before = wait(client)
    def fail(*args):
        raise RuntimeError('simulated database operation failure')
    monkeypatch.setattr('app.main.remove_records', fail)
    with pytest.raises(RuntimeError):
        client.put(f"/api/documents/{doc['id']}", files={'file': ('new.pdf', pdf('Replacement source.'))})
    assert client.get('/api/knowledge').json() == before
    assert client.get(f"/api/documents/{doc['id']}/pdf").content == content
    from app import store
    assert len(list(store.data_dir().glob('*.pdf'))) == 1


def test_startup_recovers_interrupted_file_removal(client):
    from app import store
    from app.collection import recover_removals, source_path
    doc = upload(client, pdf('Source content for recovery.'))
    wait(client)
    quarantine = store.data_dir() / '.removed'
    quarantine.mkdir()
    source_path(doc['id']).replace(quarantine / f"{doc['id']}.pdf")
    orphan = quarantine / ('a' * 32 + '.pdf')
    orphan.write_bytes(b'deleted source')
    recover_removals()
    assert source_path(doc['id']).exists()
    assert not orphan.exists()
    assert not list(quarantine.iterdir())


def test_remove_completed_pdf_while_another_is_extracting(client, monkeypatch):
    from threading import Event
    from app import pipeline
    old = upload(client, pdf("Orbit Works' headcount was 19 in FY2026."))
    wait(client)
    entered, release = Event(), Event()
    original = pipeline.extract_rules
    def pause(text):
        entered.set()
        assert release.wait(timeout=10)
        return original(text)
    monkeypatch.setattr(pipeline, 'extract_rules', pause)
    upload(client, pdf("Orbit Works' headcount was 27 in FY2026."))
    try:
        assert entered.wait(timeout=10)
        assert client.delete(f"/api/documents/{old['id']}").status_code == 200
    finally:
        release.set()
    after = wait(client)
    assert len(after['facts']) == 1
    assert after['documents'][0]['status'] == 'complete'
    assert not after['relationships']
