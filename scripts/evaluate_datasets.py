"""Evaluate arbitrary local dataset folders through the public upload API.

Usage: python scripts/evaluate_datasets.py [root-with-dataset-folders]
Original PDFs are not copied into the repository outputs.
"""
import json
import os
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from app.main import app
from app.pipeline import WORKER

root = Path(sys.argv[1] if len(sys.argv)>1 else 'starter-datasets')
out = Path('docs/evaluation')
out.mkdir(parents=True,exist_ok=True)
summaries=[]
for dataset in sorted(p for p in root.iterdir() if p.is_dir()):
    with tempfile.TemporaryDirectory(prefix='factweave-eval-') as temp:
        os.environ['FACTWEAVE_DATA_DIR']=temp
        start=time.perf_counter()
        with TestClient(app) as client:
            for path in sorted(dataset.glob('*.pdf')):
                response=client.post('/api/documents',files={'file':(path.name,path.read_bytes(),'application/pdf')})
                response.raise_for_status()
            WORKER.submit(lambda:None).result(timeout=300)
            data=client.get('/api/knowledge').json()
            # Verify all claimed evidence spans against stored source pages.
            for fact in data['facts']:
                page=client.get(f"/api/documents/{fact['document_id']}/pages/{fact['page']}").json()
                assert fact['quote'] in page['text'], fact
                for part in fact.get('evidence_parts',[]):
                    page=client.get(f"/api/documents/{fact['document_id']}/pages/{part['page']}").json()
                    assert part['quote'] in page['text'], part
            summary={'dataset':dataset.name,'documents':len(data['documents']),'pages':sum(d['pages'] for d in data['documents']),
                     'facts':len(data['facts']),'relationships':dict(Counter(r['kind'] for r in data['relationships'])),
                     'issues':dict(Counter(i['kind'] for i in data['issues'])),
                     'seconds':round(time.perf_counter()-start,2),'evidence_checks':'all fact and context spans found in source pages',
                     'quality_note':'Automated grounding check, not a precision/recall score. Layout ownership and context are heuristic.'}
            summaries.append(summary)
            data['issue_count']=len(data['issues'])
            data['issues']=data['issues'][:50]
            data['issues_truncated']=data['issue_count']>50
            (out/(dataset.name+'.json')).write_text(json.dumps(data,indent=2),encoding='utf-8')
            print(json.dumps(summary,indent=2))
(out/'summary.json').write_text(json.dumps(summaries,indent=2),encoding='utf-8')
