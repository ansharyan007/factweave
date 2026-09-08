# FactWeave

**Connect the facts. Keep the evidence.** A local fact knowledge layer for PDF uploads, grounded numerical and semantic claims, and explained corroboration, likely contradictions, contextual reconciliation and uncertainty.

![FactWeave interface](docs/demo/overview.png)

## Setup and Run Instructions

Requires **Python 3.12+**. Offline mode needs no API key, paid account or database service.

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Or use `powershell -ExecutionPolicy Bypass -File start.ps1`.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. Upload PDFs or click **Load demo dataset**. Processing updates automatically. Explore facts, filter relationships, expand reasoning, and click source links to inspect highlighted PDF evidence. Review failed or ambiguous extraction in the Review queue. Export all results as JSON.

Run **one server process / one Uvicorn worker**. Original uploads and SQLite are stored in gitignored `data/`. Set `FACTWEAVE_DATA_DIR` to isolate another knowledge layer. Limits: 30 MB and 1,000 pages per PDF. Scans are flagged, not OCR-processed.

### Change the uploaded PDFs

In **Overview → Source library**, each completed or failed PDF has **Replace** and **Delete** controls. **Clear collection** below the library starts an empty knowledge layer. Each action asks for confirmation.

- **Reprocess:** rerun the saved PDF with the current code and selected extraction mode, preserving its file and document ID. Previous derived results are removed and rebuilt, including cross-document links. Use this after upgrading the extractor; uploading identical bytes alone is deduplicated. The source library shows each PDF's fact count.
- **Replace:** select an updated PDF. The app validates it, removes the old upload and its facts, evidence, review findings and links, then extracts the replacement and compares it with the remaining documents. Other documents and their links remain intact. Replacement uses the extraction mode selected above the upload button and receives a new document ID.
- **Delete:** removes one uploaded PDF and all dependent knowledge. You can upload it again later.
- **Clear collection:** removes all uploaded PDFs and associated knowledge. Original files in `samples/` and `starter-datasets/` remain untouched. Upload custom PDFs or reload the demo afterwards.

Wait for the affected PDF to finish processing before replacing or deleting it; clearing requires all jobs to finish. Active jobs return HTTP 409. Invalid replacements and replacements that duplicate a different document preserve the original. Identical contents with the same extraction mode are a no-op, except failed jobs may be reprocessed. Accepted replacements may still encounter extraction errors, visible in their status/review findings.

File removal and database changes are coordinated: failed changes restore staged files, and startup recovery handles interrupted removals. If the operating system temporarily prevents cleanup of a staged file, it remains inaccessible through the API and cleanup retries at startup.

To reproduce the browser checks using an isolated temporary collection, install Playwright as below and run `python scripts/check_collection_ui.py`. The original demo video predates these management controls; [this screenshot](docs/collection-management.png) shows the new controls.

### Inspect connections from new PDFs

Every upload is compared with the completed documents already in the collection. **Connected documents** in Overview and Relationships lists each matched PDF pair with counts by relationship type. Select a pair to inspect both quotations, source pages and reasoning. Uploading resets stale search/pair filters so the new results are discoverable.

Source-library rows show fact and connection counts and explain whether a PDF is still processing, yielded no supported claims, or has no comparable claims in another document. Use **Reprocess** to upgrade existing results after a parser change. It preserves the original PDF and document ID.

The contextual prose extractor handles company references, document-grounded short names, financial/date wording, headcount, approximate customer/employee counts, founding years, and CEO appointment/resignation claims. It preserves interim status and qualifications. An unnamed organization stays unresolved; a matching metric/value is only a *possible* connection. `Rs.` is an unspecified rupee currency, not automatically INR. Separately quoted reporting-period definitions explain why financial-year and calendar-year totals need not agree.

Additional-upload validation: five one-page business documents previously produced zero facts. The revised run produced **21 facts and 16 connections across 8 PDF pairs**: 2 corroborations, 3 contextual reconciliations and 11 uncertain links. Automated tests also upload renamed, different-company fixtures in both orders and verify preservation of existing facts, evidence grounding and removal of stale pairs.

The app accepts arbitrary PDF filenames and contents, but it cannot promise a meaningful connection for every pair of PDFs. Unrelated material, scans without OCR, and unsupported grammar may yield none. It reports these limitations instead of inventing links.

### API

Interactive API docs: **http://127.0.0.1:8000/docs**.

```bash
curl -F "file=@your-document.pdf" -F "mode=rules" http://127.0.0.1:8000/api/documents
curl http://127.0.0.1:8000/api/documents
curl http://127.0.0.1:8000/api/knowledge
curl -o knowledge.json http://127.0.0.1:8000/api/export
```

On PowerShell use `curl.exe`. Upload returns HTTP 202 and an ID. Poll the document endpoint until `complete`, `needs_review` or `failed`.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/documents` | Upload arbitrary PDFs; content-hash deduplication |
| `PUT /api/documents/{id}` | Replace using multipart `file` and optional `mode`; rebuild facts and links |
| `DELETE /api/documents/{id}` | Remove one PDF and all dependent knowledge |
| `POST /api/collection/reset` | Clear uploads and knowledge; requires JSON `{"confirm": true}` |
| `GET /api/documents` | Job status and page progress |
| `GET /api/documents/{id}` | Status of one upload |
| `GET /api/knowledge` | Facts, evidence, predicates, relationships and issues |
| `GET /api/documents/{id}/pdf` | Original PDF |
| `GET /api/documents/{id}/pages/{page}` | Extracted page text and dimensions |
| `GET /api/documents/{id}/pages/{page}/image` | Rendered source page |
| `POST /api/documents/{id}/reprocess?mode=rules` | Rebuild results for a saved, idle PDF; optionally use `mode=ollama` |
| `POST /api/documents/{id}/retry` | Retry failed/interrupted processing |
| `POST /api/demo` | Process bundled synthetic examples |
| `GET /api/export` | Download full JSON output |

### Optional local model

Install/start [Ollama](https://ollama.com/), run `ollama pull qwen2.5:7b`, and select **Local model · Ollama** before uploading. Optional shell variables: `OLLAMA_URL` (default `http://127.0.0.1:11434`) and `OLLAMA_MODEL` (default `qwen2.5:7b`). `.env.example` documents them; `.env` is not auto-loaded. A remote endpoint receives extracted text, so use a local endpoint for local-only processing.

The adapter is implemented and tested with mocked responses; a live model was not installed during development. Offline mode and committed sample outputs are sufficient to evaluate the project. Duplicates preserve their original extraction mode; use Reprocess to change it, or another data directory to retain results for comparison.

### Tests and demo reproduction

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

On Windows without environment activation, prefix commands with `.venv\Scripts\python -m`. The suite has 71 tests. The sample PDFs are committed; regenerate with `python scripts/create_samples.py`. To record the actual UI interactions and run browser checks:

```bash
pip install playwright
playwright install chromium ffmpeg
python scripts/record_demo.py
```

The recorder uses installed Chrome on Windows when available, otherwise Playwright Chromium. It starts an isolated server on port 8011 and writes a captioned MP4, screenshots, verification report and sample JSON. It leaves your normal knowledge layer untouched. If the supplied Delhivery PDFs are present under starter-datasets/delhivery, the recording includes their real examples. Run python scripts/evaluate_datasets.py starter-datasets to reproduce both full dataset evaluations.

## Video Demo

[Watch/download the captioned demo (under 3 minutes)](docs/demo/factweave-demo.mp4). The video shows an actual PDF upload, incremental processing and all four required cases, including evidence and reasoning. It is committed with the project; no paid account is needed. If GitHub does not play it inline, click **View raw** or download it.

The video includes the four synthetic cases plus real Delhivery corroboration and rounding reconciliation. Also see [real-data evaluation](docs/REAL_DATA.md), [Four Cases](docs/FOUR_CASES.md) and [full sample output](docs/sample-output.json).

## Approach

- **Evidence first:** retain the source PDF, page, exact whitespace-normalized quote, character offsets and enclosing source-block coordinates.
- **Understandable extraction:** general English grammar and geometric KPI/simple-table extraction support explicit claims; predicates can arise from document text. Optional Ollama supports broader phrasing with strict substring grounding.
- **Statistical prose:** join nearby text fragments within a column; recognize common growth/inflation/trade measures and `per cent` wording. A dominant country can supply an explicitly labeled, separately grounded inferred subject. Estimates and forecasts remain qualified claims. No filenames select extraction rules.
- **Context before conflict:** normalize values and units, align explicit periods/scopes, and abstain when comparison is unsafe.
- **Explain each connection:** every relationship carries both source links and a decision trace. Agreement is not proof; confidence is heuristic.
- **Incremental storage:** SQLite retrieves indexed predicate candidates, then checks entity identity and document-grounded aliases. New uploads preserve existing facts. Content hashing prevents duplicate evidence inflation. Flexible payloads accept new fact types.
- **Visible failures:** scans, ambiguous statements, unsupported qualifiers and model errors enter a review queue.

Architecture: **FastAPI + PyMuPDF + SQLite + vanilla HTML/CSS/JavaScript**, with optional Ollama. A graph database is unnecessary for this prototype; the useful part is grounded extraction and explanation. See [engineering notes](docs/APPROACH.md) for architecture, trade-offs, actual bugs and references.

**AI tools used:** OpenAI Codex assisted with architecture, implementation, test design, debugging, documentation and the scripted demo. No paid LLM is used by the default runtime. Review and understand the implementation before presenting it.

## Limitations and Next Steps

- **Real-data coverage is uneven.** Both supplied datasets were evaluated: 212 claims from 227 Delhivery pages and 31 claims with 30 uncertain links from 284 macroeconomic pages. The macroeconomic baseline was five claims (zero from RBI); prose reconstruction and statistical extraction improve coverage but leave many statements unsupported. These are extraction counts, not accuracy scores. See [real-data evaluation](docs/REAL_DATA.md).
- The statistical supplement uses an expandable metric vocabulary; it is not a general language understanding model. Country inheritance is heuristic and can be wrong for implicit subpopulations or comparisons. Bare inflation subtypes remain unresolved. Offline grammar has limited English coverage. Complex tables, indirect claims, cross-sentence references and unfamiliar units can be missed or flagged.
- Scans need OCR. Next: OCR with numerical confidence review, layout reconstruction and table/header/footnote alignment.
- Semantic matching uses conservative aliases and normalization. Broader paraphrases and entity aliases need resolution and entailment checks; different text values usually remain uncertain.
- Layout facts retain separate metric/value/period/subject spans. Company ownership is inferred from document evidence and can be wrong on partner/case-study pages. Table-wide units and footnotes remain unresolved and force uncertain comparisons.
- Period parsing is coarse. Exact dates, fiscal calendars, overlapping intervals and implicit scope need richer context handling. Omitted scope weakens likely contradictions.
- Exact source substrings prove lexical grounding, not truth or complete entailment. Live model quality and real-document precision/recall are unmeasured; supplied-dataset coverage and source-span checks are reported.
- Single-worker processing, full snapshot responses and dense candidate buckets limit scale. Add durable workers, pagination, retrieval ranking, resource isolation and benchmarks.
- This is a local prototype, without authentication or multi-user isolation. Public hosting needs additional engineering.

## Additional Notes

| Required case | Included example |
| --- | --- |
| Corroboration | Revenue USD 12 million ↔ sales USD 12,000,000, FY2024 |
| Likely contradiction | 240 employees ↔ headcount 275, FY2024 |
| Contextual reconciliation | Revenue USD 12 million in FY2024 ↔ USD 9 million in FY2023 |
| Extraction failure | Scanned operating-profit claim is missed, its page is exposed in the review queue, and no fact is invented |

Bonus examples: address abbreviations, percentages, energy unit conversion, scope differences and missing-context uncertainty. All companies and figures in `samples/` are fictional. Extraction and comparison modules do not depend on sample values or filenames; only the demo loader locates the sample directory.

Credentials, uploaded PDFs, local data and the virtual environment are gitignored. Only synthetic PDFs, results and demo artifacts are committed. GitHub Actions runs the test suite on pushes and pull requests.

Before submitting, review the code, review the real-data evaluation, and provide the repository and video links through the assignment form. The form is not submitted automatically.
