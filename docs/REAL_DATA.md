# Evaluation on the supplied PDFs

Both local starter datasets were evaluated through the same public PDF-upload API, with isolated knowledge layers. No filenames or company values are used by the extractor. The synthetic fixtures remain useful for deterministic tests and the deliberately conflicting headcount case.

| Dataset | PDFs / pages | Extracted claims | Relationships | Measured local evaluation time |
| --- | --- | --- | --- | --- |
| Delhivery | 3 / 227 | 212 | 1 corroboration, 1 reconciliation, 10 uncertain | approximately 15 seconds |
| India macroeconomy | 3 / 284 | 31 | 30 uncertain | approximately 6 seconds |

These counts are **coverage observations, not accuracy scores**. Every emitted fact quote and inherited grounding span was checked against its stored source page. Lexical grounding does not establish correct semantic interpretation, entity ownership or numerical units. The run includes extraction, storage, comparison and source-span checks; it is not a controlled performance benchmark.

Machine-readable [summary](evaluation/summary.json), [Delhivery output](evaluation/delhivery.json), and [macroeconomy output](evaluation/india-macroeconomy.json) are included. Output files contain all extracted facts/relationships and the first 50 issues, with the total issue count and an explicit truncation flag. Full results can be exported when running locally.

## Real corroboration: parcel shipments

The Delhivery annual-report excerpt, PDF page **4**, displays **740Mn** with the label “Express parcels shipped.” The earnings presentation, PDF page **6**, displays **740 Mn** with “Express parcel shipments in FY24.”

The general layout extractor pairs a large number with a nearby aligned label. It preserves the metric, value, fiscal heading and document-subject anchor as separate source spans. General token normalization maps parcels/shipped to parcel/shipments. Both normalize to 740000000 for FY2024 and return **corroborates**.

The annual-report heading “of FY24” supplies inherited context; the presentation metric itself supplies FY24. The company is inferred from a repeated legal-name or sign-off line. This remains a heuristic association, visible in the source inspector.

## Real reconciliation: units and displayed precision

The annual-report excerpt, PDF page **4**, displays revenue from services of **INR 81,415 million**. The earnings presentation, PDF page **6**, displays **INR 8,142 crore** for FY24.

After normalization these are INR 81,415,000,000 and INR 81,420,000,000. The difference is INR 5,000,000. The displayed increments are INR 1,000,000 and INR 10,000,000, so their half-increment precision intervals overlap. The relationship is **reconciled**: rounding can explain the discrepancy. This is an explanation of compatibility, not proof that either disclosure was rounded in a particular way.

## A reasoning failure found and corrected

An early layout pass compared “Wages” in a complaints table with “Wages” in a financial expense table and produced false conflicts. The identical row label did not imply the same measure. Grouped/nested headers had been only partially aligned.

The revised extractor rejects partial column mappings and repeated subrow labels without a resolved parent metric. Unresolved table-wide units or footnotes now force **uncertain** comparisons. A regression test covers the grouped-year failure. No genuine contradiction is asserted from these real datasets by the final run; the synthetic conflicting-headcount fixture demonstrates the required likely-contradiction behavior.

Other real limitations remain: a page about a partner's operations can inherit the main document's company name. Layout ownership is heuristic, and some table labels remain less informative than a full semantic measure. These are exposed through method/confidence notes and separate evidence spans, not hidden behind an accuracy claim.

## The macroeconomy failure

The original parser found only five claims, including zero from RBI. RBI stored prose as individual line blocks, and the grammar missed statistical verbs and the unit spelling `per cent`. Reading PDF pages successfully did not mean facts had been extracted.

The updated implementation joins nearby text fragments sharing a column edge and retains their original rectangles as separate evidence spans. A statistical prose supplement recognizes common measures, preserves metric modifiers and attached periods, and keeps estimates/forecasts labeled. An ISO country catalogue supports a dominant-country heuristic with a visible source anchor; no PDF filenames or India-specific extraction rules select behavior.

The revised run yields **11 Economic Survey facts, 7 RBI facts, and 13 IMF facts**. For example, RBI excerpt page 8 now supplies real GDP growth of 6.5 per cent in 2024-25, and IMF page 10 supplies 6.5 percent in FY2024/25. Their values agree, but the comparison remains uncertain because the period labels need calendar alignment. Survey page 4 supplies the 6.4 per cent FY25 *estimate*, which is not asserted as a contradiction with later reported growth. The 30 links are all uncertain; no extra corroboration or contradiction is claimed merely to improve a count.

Reviewing the first expanded run exposed incorrect candidates: a *contribution to inflation* parsed as inflation, and a quarter inheriting the year of an earlier clause. Regression tests now reject share/contribution claims in this grammar and preserve attached quarter/month/range context. Unknown metric modifiers are rejected; an unspecified inflation subtype forces uncertain comparison.

Coverage remains limited: complex tables, implicit references, national-account revisions, contextual subpopulations and unfamiliar statistical grammar still need review. Country inheritance and layout reconstruction are heuristics. The optional Ollama adapter is implemented but live model quality was not evaluated. Source substring checks do not establish semantic accuracy.

Already uploaded PDFs can be updated using **Reprocess**, without uploading again. Original bytes and document IDs stay in place while derived facts, evidence and links are rebuilt. Tests exercise this through the API and browser.

## Reproduce and provenance

Place the supplied folders under `starter-datasets/`, then run:

```bash
python scripts/evaluate_datasets.py starter-datasets
```

Development dependencies are required. The directory is gitignored to keep the repository focused on code and evaluation artifacts. The PDF originals are available from the supplied public-source links below. PDF page numbers in this project refer to positions **inside the excerpts**, not printed original-report page numbers.

- [Delhivery prospectus](https://www.delhivery.com/wp-content/uploads/2022/05/Delhivery-Limited-Prospectus-1-min.pdf): source PDF pages 1, 4, 26–37, 94–120, 216–245, 250–278 (100 retained).
- [Delhivery FY24 annual report](https://www.delhivery.com/uploads/2024/08/Annual_Report_FY24.pdf): source PDF pages 2–64 and 105–141 (100 retained).
- [Delhivery earnings presentation](https://www.bseindia.com/xml-data/corpfiling/AttachHis/d70668ee-4f13-485e-ba19-62bec5116a59.pdf): all 27 pages.
- [Economic Survey](https://www.indiabudget.gov.in/budget2025-26/economicsurvey/doc/echapter.pdf): pages 4–6, 46–78, 124–176 (89 retained).
- [RBI Annual Report](https://rbidocs.rbi.org.in/rdocs/AnnualReport/PDFs/0ANNUALREPORT202425DA4AE08189C848C8846718B080F2A0A9.PDF): pages 9–13, 27–111, 307–316 (100 retained).
- [IMF Article IV](https://www.imf.org/en/publications/cr/issues/2025/11/25/india-2025-article-iv-consultation-press-release-staff-report-and-statement-by-the-572056): pages 1–95.

The provenance above comes from the supplied dataset README files. Original downloads were not independently fetched during this evaluation.
