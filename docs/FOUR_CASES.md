# Four required cases

These examples come from the **synthetic** PDFs in `samples/`, processed through the normal pipeline. The supplied real PDFs are evaluated separately in [Real Data](REAL_DATA.md).

## 1. Corroboration

**Annual review, page 1:** “Aster Labs reported revenue of USD 12 million in FY2024.”

**Investor update, page 1:** “Aster Labs recorded sales of USD 12,000,000 in FY2024.”

Sales maps to revenue; both quantities normalize to 12000000 USD. Entity and FY2024 align. The result is **corroborates**, with both quotations and normalization steps. Scope is unspecified and source independence is not established.

## 2. Likely contradiction

**Annual review, page 1:** “Aster Labs employed 240 employees in FY2024.”

**Investor update, page 1:** “Aster Labs' headcount was 275 in FY2024.”

Headcount maps to employees. Values 240 and 275 differ for the same company and explicit FY2024 period. The result is **contradicts**, labeled “likely contradiction” in the UI. Unspecified scope and omitted definitions (contractors, average versus closing headcount) remain caveats. No source wins automatically.

## 3. Contextual reconciliation

**Annual review, page 1:** “Aster Labs reported revenue of USD 12 million in FY2024.”

**Context and caveats, page 1:** “Aster Labs reported revenue of USD 9 million in FY2023.”

The company, metric and currency match, but periods differ. The result is **reconciled**: both claims can coexist. This explains comparability, not the cause of the underlying change.

## 4. Extraction failure

**Context and caveats, page 2** is an intentionally rasterized scan. Its visible source says: “Aster Labs' operating profit was USD 3 million in FY2024.”

No text is recovered. The review queue reports **no_extractable_text**, shows the original page, and emits no operating-profit fact. Next: OCR followed by layout reconstruction, numerical confidence thresholds and human review.

Page 1 also contains a multiple-value, multiple-year “respectively” sentence. The parser withholds it rather than incorrectly aligning values and periods.

## Reproduce

1. Start the app and load the demo, or upload the three PDFs individually.
2. Open Relationships. Select Corroboration, Contradiction or Context; filter revenue for cases 1 and 3.
3. Expand the reasoning and click the source links to inspect quotations and highlighted page blocks.
4. Open Review queue and inspect the scan and ambiguous statement.
5. Export the complete JSON.

See the [sample output](sample-output.json) and [captioned video](demo/factweave-demo.mp4). Bonus examples include equivalent addresses, energy units, percentages, scope differences and missing-context uncertainty.
