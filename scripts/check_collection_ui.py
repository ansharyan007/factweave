"""Test document management with temporary PDFs/database; never touches user data."""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import pymupdf
import uvicorn
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
URL = 'http://127.0.0.1:8012'


def main():
    with tempfile.TemporaryDirectory(prefix='factweave-ui-') as temp:
        directory = Path(temp)
        os.environ['FACTWEAVE_DATA_DIR'] = str(directory / 'data')
        server = uvicorn.Server(uvicorn.Config('app.main:app', host='127.0.0.1', port=8012, log_level='error'))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                try:
                    if httpx.get(URL + '/api/health').is_success:
                        break
                except httpx.ConnectError:
                    pass
                time.sleep(.1)
            for name, value in [('initial',19), ('supporting',27), ('updated',27)]:
                with pymupdf.open() as pdf:
                    pdf.new_page().insert_text((45,70), f"Orbit Works' headcount was {value} in FY2026.")
                    pdf.save(directory / f'{name}.pdf')
            (directory/'invalid.pdf').write_bytes(b'not a PDF')
            with sync_playwright() as p:
                chrome = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
                browser = p.chromium.launch(headless=True, **({'executable_path':str(chrome)} if chrome.exists() else {}))
                page = browser.new_page(viewport={'width':1440,'height':1100})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(URL)
                page.locator('#file-input').set_input_files([str(directory/'initial.pdf'),str(directory/'supporting.pdf')])
                page.wait_for_function("document.querySelector('#stat-facts').textContent === '2'")
                assert page.locator('.badge.contradicts').count() == 1
                assert '1 facts' in page.locator('.doc-meta').first.inner_text()
                old_fact_ids = {f['id'] for f in httpx.get(URL+'/api/knowledge').json()['facts']}
                page.locator('[data-reprocess]').first.click()
                page.wait_for_function("document.querySelector('#notice').textContent.includes('Reprocessing')")
                page.wait_for_function("document.querySelector('#stat-facts').textContent === '2' && !document.querySelector('[data-reprocess]').disabled")
                new_fact_ids = {f['id'] for f in httpx.get(URL+'/api/knowledge').json()['facts']}
                assert old_fact_ids != new_fact_ids
                assert page.locator('.badge.contradicts').count() == 1
                page.once('dialog', lambda dialog: dialog.dismiss())
                page.get_by_role('button',name='Delete initial.pdf',exact=True).click()
                assert page.locator('#stat-documents').inner_text() == '2'
                page.get_by_role('button',name='Replace initial.pdf',exact=True).click()
                page.once('dialog', lambda dialog: dialog.accept())
                page.locator('#replacement-input').set_input_files(str(directory/'invalid.pdf'))
                page.wait_for_function("document.querySelector('#notice').textContent.includes('PDF signature')")
                assert page.locator('.doc-name',has_text='initial.pdf').count() == 1
                page.get_by_role('button',name='Replace initial.pdf',exact=True).click()
                page.once('dialog', lambda dialog: dialog.accept())
                page.locator('#replacement-input').set_input_files(str(directory/'updated.pdf'))
                page.locator('.badge.corroborates').wait_for()
                assert page.locator('.doc-name',has_text='initial.pdf').count() == 0
                assert page.locator('#stat-documents').inner_text() == '2'
                page.locator('#documents-section').scroll_into_view_if_needed()
                page.screenshot(path=str(ROOT/'docs'/'collection-management.png'))
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.set_viewport_size({'width':1440,'height':1100})
                page.once('dialog', lambda dialog: dialog.dismiss())
                page.locator('#reset-collection').click()
                assert page.locator('#stat-documents').inner_text() == '2'
                page.once('dialog', lambda dialog: dialog.accept())
                page.get_by_role('button',name='Delete updated.pdf',exact=True).click()
                page.wait_for_function("document.querySelector('#stat-documents').textContent === '1'")
                assert page.locator('#stat-relations').inner_text() == '0'
                page.locator('#file-input').set_input_files(str(directory/'initial.pdf'))
                page.wait_for_function("document.querySelector('#stat-facts').textContent === '2'")
                page.once('dialog', lambda dialog: dialog.accept())
                page.locator('#reset-collection').click()
                page.wait_for_function("document.querySelector('#stat-documents').textContent === '0'")
                page.reload()
                page.wait_for_function("document.querySelector('#stat-documents').textContent === '0'")
                assert page.locator('#reset-collection').is_disabled()
                page.locator('#demo-button').click()
                page.wait_for_function("document.querySelector('#stat-facts').textContent === '13'")
                assert not errors, errors
                browser.close()
            print('PASS: replace, invalid replacement, fresh links, delete, cancel, reset, persistence, reupload, demo reload, mobile, zero browser errors.')
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            from app.pipeline import WORKER
            WORKER.shutdown(wait=True)


if __name__ == '__main__':
    main()
