"""Record real browser interactions against an isolated local test server.

Requires: pip install playwright; playwright install chromium
Or uses installed Chrome on Windows. Writes a captioned MP4, screenshots and JSON.
"""
import json
import os
import subprocess
import sys
import time
import threading
import uvicorn
from pathlib import Path

import httpx
import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'docs' / 'demo'
OUTPUT.mkdir(parents=True, exist_ok=True)
URL = 'http://127.0.0.1:8011'


def record():
    import tempfile
    with tempfile.TemporaryDirectory(prefix='factweave-demo-') as temp:
        sys.path.insert(0, str(ROOT))
        os.environ['FACTWEAVE_DATA_DIR'] = str(Path(temp) / 'data')
        server = uvicorn.Server(uvicorn.Config('app.main:app', host='127.0.0.1', port=8011, log_level='error'))
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
        try:
            for _ in range(100):
                try:
                    if httpx.get(URL + '/api/health').status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError('Demo server did not start')
            with sync_playwright() as p:
                chrome = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
                browser = p.chromium.launch(headless=True, **({'executable_path': str(chrome)} if chrome.exists() else {}))
                context = browser.new_context(viewport={'width': 1440, 'height': 1100}, record_video_dir=str(Path(temp) / 'video'), record_video_size={'width':1440,'height':1100})
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(URL)
                page.get_by_role('heading', name='Connect the facts.').wait_for()
                page.screenshot(path=str(OUTPUT / 'overview-empty.png'), full_page=True)

                def caption(title, detail, duration=4000):
                    page.evaluate('''([title,detail]) => {
                      let box=document.getElementById('demo-caption');
                      if(!box){box=document.createElement('div');box.id='demo-caption';document.body.appendChild(box);}
                      (document.querySelector('dialog[open]')||document.body).appendChild(box);
                      box.style.cssText='position:fixed;bottom:20px;left:280px;right:35px;z-index:99999;background:#173e32f5;color:white;padding:17px 24px;border-radius:10px;box-shadow:0 5px 25px #0002;font:14px/1.5 Segoe UI,sans-serif;pointer-events:none';
                      box.replaceChildren();const strong=document.createElement('strong');strong.textContent=title;strong.style.cssText='display:block;font-size:18px;margin-bottom:3px';box.appendChild(strong);box.appendChild(document.createTextNode(detail));
                    }''', [title,detail])
                    page.wait_for_timeout(duration)

                caption('FactWeave | An evidence-first knowledge layer', 'A local app for PDF uploads, grounded facts and explained relationships. This recording uses labeled synthetic documents.', 6000)
                caption('Upload a PDF', 'The annual review is processed through the same upload endpoint used for any new document.', 2500)
                page.locator('#file-input').set_input_files(str(ROOT / 'samples' / '01_annual_review.pdf'))
                page.wait_for_function("document.querySelector('#stat-facts').textContent === '5'")
                caption('5 grounded facts, from the first document', 'Extraction preserves the original quotation, page number and source block coordinates. No facts are hard-coded in the app.', 5500)
                page.locator('#file-input').set_input_files([str(ROOT/'samples'/'02_investor_update.pdf'), str(ROOT/'samples'/'03_context_and_scan.pdf')])
                page.wait_for_function("document.querySelector('#stat-facts').textContent === '13'")
                page.evaluate("document.getElementById('demo-caption').remove()")
                page.screenshot(path=str(OUTPUT / 'overview.png'), full_page=True)
                caption('Add two perspectives, incrementally', 'Only the new PDFs are extracted. Matching stored claims are compared; existing fact IDs and evidence are preserved.', 5000)
                page.locator('[data-view="relations"]').click()
                page.locator('[data-kind="corroborates"]').click()
                page.locator('#predicate-filter').select_option('revenue')
                page.locator('#results').scroll_into_view_if_needed()
                page.locator('summary').first.click()
                page.locator('.relation-card').first.scroll_into_view_if_needed()
                caption('Case 1 | Corroboration across different wording', 'Revenue of USD 12 million and sales of USD 12,000,000 normalize to the same value and FY2024 period.', 9000)
                page.evaluate("document.getElementById('demo-caption').remove()")
                page.screenshot(path=str(OUTPUT / 'case-1-corroboration.png'))
                page.locator('[data-evidence]').first.click()
                page.locator('#evidence-body img').wait_for()
                caption('Follow the claim to its source', 'The exact quotation and original PDF page appear together. The gold box highlights the enclosing text block.', 7000)
                page.evaluate("document.getElementById('demo-caption').remove()")
                page.screenshot(path=str(OUTPUT / 'evidence.png'))
                page.locator('#close-evidence').click()
                page.locator('#predicate-filter').select_option('')
                page.locator('[data-kind="contradicts"]').click()
                page.locator('#results').scroll_into_view_if_needed()
                page.locator('summary').first.click()
                page.locator('.relation-card').first.scroll_into_view_if_needed()
                caption('Case 2 | A likely contradiction', '240 employees versus headcount 275. Same company, FY2024, and unspecified scope. The app flags a likely conflict without choosing a winner.', 10000)
                page.evaluate("document.getElementById('demo-caption').remove()")
                page.screenshot(path=str(OUTPUT / 'case-2-contradiction.png'))
                page.locator('[data-kind="reconciled"]').click()
                page.locator('#predicate-filter').select_option('revenue')
                page.locator('#results').scroll_into_view_if_needed()
                page.locator('summary').first.click()
                page.locator('.relation-card').first.scroll_into_view_if_needed()
                caption('Case 3 | Context explains an apparent contradiction', 'USD 12 million in FY2024 and USD 9 million in FY2023 describe different periods. Both claims can coexist.', 10000)
                page.evaluate("document.getElementById('demo-caption').remove()")
                page.screenshot(path=str(OUTPUT / 'case-3-context.png'))
                page.locator('[data-view="issues"]').click()
                page.locator('#results').scroll_into_view_if_needed()
                caption('Case 4 | A real extraction failure, made visible', 'The multi-year sentence is withheld as ambiguous. The scanned appendix contains no extractable text, so its operating-profit claim is missed.', 8500)
                page.locator('.issue-card').filter(has_text='no extractable text').locator('[data-evidence]').click()
                page.locator('#evidence-body img').wait_for()
                caption('The source reveals what was missed', 'The image says operating profit was USD 3 million. FactWeave does not invent a fact. Next step: OCR with layout-aware extraction and review.', 9000)
                page.evaluate("document.getElementById('demo-caption').remove()")
                page.screenshot(path=str(OUTPUT / 'case-4-failure.png'))
                page.locator('#close-evidence').click()
                page.locator('[data-view="facts"]').click()
                page.locator('#predicate-filter').select_option('energy use')
                page.locator('#results').scroll_into_view_if_needed()
                caption('Beyond the four cases', 'Unit conversion, dynamic fact types, search, JSON export and a documented API. Offline rules prioritize precision; optional Ollama expands coverage.', 7000)
                page.locator('[data-view="overview"]').click()
                page.evaluate('window.scrollTo(0,0)')
                caption('Honest limits, inspectable decisions', 'The four cases above use synthetic fixtures. Real datasets are evaluated separately; OCR, complex tables and stronger semantic reasoning remain next steps.', 5000)
                page.evaluate("document.getElementById('demo-caption').remove()")
                synthetic_data = httpx.get(URL+'/api/export').json()
                starter_files = sorted((ROOT/'starter-datasets'/'delhivery').glob('*.pdf'))
                if starter_files:
                    caption('Now test the actual supplied documents', 'Upload three Delhivery reports: 227 pages, including annual-report dashboards and an earnings presentation.', 3500)
                    page.locator('#file-input').set_input_files([str(p) for p in starter_files])
                    page.wait_for_function("document.querySelector('#stat-documents').textContent === '6'")
                    page.wait_for_function("!document.querySelector('.doc-state.queued, .doc-state.processing')", timeout=120000)
                    page.locator('[data-view="relations"]').click()
                    page.locator('#search').fill('Delhivery')
                    page.locator('#predicate-filter').select_option('express parcel shipments')
                    page.locator('[data-kind="corroborates"]').click()
                    page.locator('#results').scroll_into_view_if_needed()
                    page.locator('summary').first.click()
                    page.locator('.relation-card').first.scroll_into_view_if_needed()
                    caption('Real corroboration | 740 million shipments', 'Annual report page 4 and earnings presentation page 6 agree. Metric, value and inherited period each retain their own source evidence.', 6500)
                    page.evaluate("document.getElementById('demo-caption').remove()")
                    page.screenshot(path=str(OUTPUT/'real-corroboration.png'))
                    page.locator('#predicate-filter').select_option('revenue from services')
                    page.locator('[data-kind="reconciled"]').click()
                    page.locator('#results').scroll_into_view_if_needed()
                    page.locator('summary').first.click()
                    page.locator('.relation-card').first.scroll_into_view_if_needed()
                    caption('Real reconciliation | Units and rounding', 'INR 81,415 million versus INR 8,142 crore in FY2024. Displayed-precision intervals overlap; rounding can explain the small difference.', 7000)
                    page.evaluate("document.getElementById('demo-caption').remove()")
                    page.screenshot(path=str(OUTPUT/'real-rounding.png'))
                    page.locator('[data-evidence]').first.click()
                    page.locator('#evidence-body img').wait_for()
                    caption('Separate evidence for inherited context', 'Layout extraction shows the metric, value, fiscal heading and company-name anchor. Ownership inference is heuristic and remains reviewable.', 5000)
                    page.evaluate("document.getElementById('demo-caption').remove()")
                    page.screenshot(path=str(OUTPUT/'real-evidence.png'))
                    page.locator('#close-evidence').click()
                    page.locator('#search').fill('')
                    page.locator('[data-view="overview"]').click()
                    page.evaluate('window.scrollTo(0,0)')
                    caption('Measured limits matter', 'The macroeconomic reports yielded only five semantic claims. Coverage remains weak there; the README reports this failure openly.', 5000)
                    page.evaluate("document.getElementById('demo-caption').remove()")
                # UI checks beyond the recording's four cases.
                document_count=page.locator('#stat-documents').inner_text()
                page.locator('#demo-button').click()
                page.wait_for_timeout(500)
                assert page.locator('#stat-documents').inner_text() == document_count
                page.locator('[data-view="facts"]').click()
                page.locator('#predicate-filter').select_option('')
                page.locator('#search').fill('recycling rate')
                assert page.locator('.fact-card').count() == 2
                page.locator('#search').fill('no-matching-entity')
                assert page.locator('.fact-card').count() == 0
                page.locator('#search').fill('')
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(OUTPUT / 'mobile.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                assert not errors, errors
                video_path = page.video.path()
                context.close()
                browser.close()
                subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-i', str(video_path), '-vf', 'scale=1440:1100', '-c:v', 'libx264', '-preset', 'fast', '-crf', '25', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(OUTPUT/'factweave-demo.mp4')], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            data = httpx.get(URL+'/api/export').json()
            (ROOT/'docs'/'sample-output.json').write_text(json.dumps(synthetic_data,indent=2),encoding='utf-8')
            report = {'video_seconds': imageio_ffmpeg.count_frames_and_secs(str(OUTPUT/'factweave-demo.mp4'))[1], 'browser_errors': errors, 'documents':len(data['documents']), 'facts':len(data['facts']), 'relationships':len(data['relationships']), 'issues':len(data['issues']), 'mobile_overflow':False, 'tested':['actual file upload','four cases','source modal','reasoning expansion','duplicate demo','search','filters','mobile layout']}
            (OUTPUT/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report,indent=2))
        finally:
            server.should_exit = True
            server_thread.join(timeout=15)
            from app.pipeline import WORKER
            WORKER.shutdown(wait=True)
            if server_thread.is_alive():
                raise RuntimeError("Demo server did not shut down")


if __name__ == '__main__':
    record()
