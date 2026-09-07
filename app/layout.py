"""Geometry-based extraction for explicit KPI cards and simple period-column tables.

No filename, company or document-specific metric rules. Inherited context has its
own source evidence and conservative confidence; arbitrary tables are not guessed.
"""
from collections import Counter
import re

from .extraction import clean, context, make_fact, normalize_value, predicate_key

LEGAL = r"(?:Limited|Ltd\.?|Inc\.?|Corporation|PLC)"
NAME = r"[A-Z][A-Za-z0-9&.'-]*(?:\s+(?:[A-Z][A-Za-z0-9&.'-]*|of|and)){0,6}\s+" + LEGAL


def document_subject(pdf):
    candidates, evidence = Counter(), {}
    for index, page in enumerate(pdf):
        for block in page.get_text("blocks"):
            if block[6] != 0:
                continue
            for raw in block[4].splitlines():
                line = clean(raw)
                match = re.fullmatch(r"(?:For\s+)?(" + NAME + r")", line, re.I if line.isupper() else 0)
                if match:
                    name = match[1]
                    key = name.casefold()
                    candidates[key] += 4 if line.startswith("For ") else 1
                    evidence[key] = {"role":"subject", "quote":line, "page":index+1, "bbox":list(block[:4]), "subject":name}
    if not candidates:
        return None
    best = candidates.most_common(2)
    if len(best) > 1 and best[0][1] <= best[1][1]:
        return None
    return evidence[best[0][0]]


def line_items(page):
    output = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            text = clean("".join(span["text"] for span in line["spans"]))
            if text:
                output.append({"text":text, "bbox":list(line["bbox"]),
                               "size":max(span["size"] for span in line["spans"])})
    return output


def label_ok(text):
    return (bool(re.search(r"[A-Za-z]", text)) and 1 <= len(text.split()) <= 9
            and not re.match(r"^(?:of|in|for|by)\b", text, re.I)
            and not re.search(r"[.!?:;]|\b(?:is|was|were|are|has|have|includes|excluding|by|from the)\b", text, re.I)
            and not re.fullmatch(r"(?:Q[1-4]\s*)?FY\s*\d{2,4}", text, re.I))


def metric(text):
    text = re.sub(r"\(\d+(?:,\d+)*\)", "", text)
    text = re.sub(r"\b(?:Q[1-4]\s*)?FY\s*\d{2,4}\b", "", text, flags=re.I)
    text = re.sub(r"\s+in\s*$", "", text)
    return clean(text).strip(" -*")


def part(role, line, page):
    return {"role":role,"quote":line["text"],"bbox":line["bbox"],"page":page}


def extract_layout(page, page_number, subject):
    if not subject:
        return []
    lines = line_items(page)
    facts = []
    def finish(label, value, primary, extra, ctx=None):
        pred = predicate_key(metric(label))
        if not pred:
            return
        fact = make_fact(subject["subject"], pred, value, primary["text"], "layout")
        if fact["normalized"]["kind"] != "number":
            return
        fact["context"] = ctx or context(label)
        fact["confidence"] = .6
        fact["confidence_note"] = "Layout and document-subject inference; inspect the separate evidence spans. Not a truth probability."
        fact["evidence_parts"] = [subject, part("value and/or row", primary, page_number)] + extra
        fact["subject_inferred"] = True
        fact["bbox"] = primary["bbox"]
        fact["block_text"] = primary["text"]
        fact["evidence_start"] = 0
        fact["evidence_end"] = len(primary["text"])
        facts.append(fact)

    # Large number above a short, left-aligned metric label. Ordinary body text
    # and numeric chart ticks without a nearby metric do not qualify.
    for value in lines:
        if value["size"] < 18 or len(value["text"]) > 30:
            continue
        if normalize_value(value["text"], "")["kind"] != "number":
            continue
        x0,y0,x1,y1 = value["bbox"]
        choices = [line for line in lines
                   if abs(line["bbox"][0]-x0) < 8
                   and -8 <= line["bbox"][1]-y1 <= 20
                   and line["size"] < value["size"]*.8
                   and label_ok(line["text"])]
        if len(choices) != 1:
            continue
        label = choices[0]
        ctx = context(label["text"])
        evidence = [part("metric",label,page_number)]
        # Inherit only an isolated, explicit fiscal/quarter heading above this KPI.
        if not ctx["period"]:
            headers = [line for line in lines if line["bbox"][1] < y0 and
                       re.fullmatch(r"(?:(?:of|for|in)\s+)?(?:Q[1-4]\s*)?FY\s*\d{2,4}",line["text"],re.I)]
            periods = {context(h["text"])["period"] for h in headers}
            if len(periods) == 1:
                ctx = context(headers[0]["text"])
                evidence.append(part("period heading", headers[0],page_number))
        finish(label["text"],value["text"],value,evidence,ctx)

    # Row blocks containing one label and 2+ numeric cells, aligned geometrically
    # with explicit period headers. Each cell inherits only its own header.
    headers = [line for line in lines if re.fullmatch(r"(?:Q[1-4]\s*)?(?:FY|CY)\s*\d{2,4}(?:[-/]\d{2,4})?",line["text"],re.I)]
    blocks = [b for b in page.get_text("blocks",sort=True) if b[6] == 0]
    row_labels = Counter(metric(clean(b[4].splitlines()[0])).casefold() for b in blocks if b[4].splitlines())
    for block in blocks:
        if block[6]!=0 or block[3]-block[1] > 35:
            continue
        row = [line for line in lines if line["bbox"][0] >= block[0]-.5 and line["bbox"][2] <= block[2]+.5
               and line["bbox"][1] >= block[1]-.5 and line["bbox"][3] <= block[3]+.5]
        row.sort(key=lambda line:line["bbox"][0])
        if len(row) < 3 or not label_ok(row[0]["text"]):
            continue
        label=row[0]
        if row_labels[metric(label["text"]).casefold()] > 1:
            continue  # Repeated subrow labels require their parent metric.
        # Units in row headers need a separate unit parser; avoid mislabeling.
        if re.search(r"\b(million|thousand|billion|crore|sq|percent)\b|[%₹$€]", label["text"],re.I):
            continue
        cells=row[1:]
        if any(not re.fullmatch(r"-?\d[\d,]*(?:\.\d+)?",c["text"]) for c in cells):
            continue
        aligned=[]
        for cell in cells:
            center=(cell["bbox"][0]+cell["bbox"][2])/2
            matches=[h for h in headers if 0 < block[1]-h["bbox"][3] < page.rect.height*.65
                     and abs((h["bbox"][0]+h["bbox"][2])/2-center) < 22]
            if not matches:
                break
            header=max(matches,key=lambda h:h["bbox"][1])
            aligned.append((cell,header))
        if len(aligned) != len(cells) or len({tuple(h["bbox"]) for _,h in aligned}) != len(cells):
            continue  # Never assign only some cells under grouped/nested headers.
        if max(h["bbox"][1] for _,h in aligned)-min(h["bbox"][1] for _,h in aligned) > 5:
            continue
        for cell,header in aligned:
            ctx=context(header["text"])
            footnotes=re.findall(r"\((\d+)\)",label["text"])
            # Footnoted rows remain useful facts, but their unmodeled definitions
            # prevent automatic comparison from pretending that scope is aligned.
            ctx["qualifier_unresolved"]=bool(footnotes)
            ctx["unit_unresolved"]=True  # A row alone does not establish its table-wide units.
            primary={"text":clean(block[4]),"bbox":list(block[:4])}
            finish(label["text"],cell["text"],primary,[part("metric",label,page_number),part("period column",header,page_number),part("value cell",cell,page_number)],ctx)
    return facts
