"""Grounded statistical prose extraction; no filename or dataset rules."""
import re
from collections import Counter

import pycountry

from .extraction import clean, make_fact


def country_subject(pdf):
    names = [c.name for c in pycountry.countries]
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b")
    counts, anchors = Counter(), {}
    for index in range(min(12, len(pdf))):
        for block in pdf[index].get_text("blocks"):
            if block[6] != 0:
                continue
            text = clean(block[4])
            for name in pattern.findall(text):
                counts[name] += 1
                anchors.setdefault(name, {"role": "inferred country subject", "page": index + 1,
                                          "quote": text, "bbox": list(block[:4])})
    ranked = counts.most_common(2)
    if ranked and ranked[0][1] >= 5 and (len(ranked) == 1 or ranked[0][1] >= 3 * ranked[1][1]):
        return {"name": ranked[0][0], "anchor": anchors[ranked[0][0]]}
    return None


def reading_blocks(blocks):
    """Join nearby prose fragments sharing a left edge, never across columns."""
    groups = []
    for block in sorted(blocks, key=lambda b: (b[1], b[0])):
        text = clean(block[4])
        target = next((g for g in reversed(groups)
                       if abs(g[0] - block[0]) < 8 and -2 <= block[1] - g[3] <= 8
                       and g[2] <= block[0] + max(280, block[2]-block[0])
                       and len(text) >= 20 and len(g[4]) >= 20
                       and not re.search(r"[.!?]$", g[4])
                       and len(g[4]) < 6000), None)
        if target is None:
            groups.append([*block[:4], text, [block]])
        else:
            target[2] = max(target[2], block[2])
            target[3] = max(target[3], block[3])
            target[4] += " " + text
            target[5].append(block)
    return groups


# Vocabulary identifies metrics, not a fixed output schema. Other explicit noun
# phrases can be supported later; arbitrary nearby numbers are never facts.
METRIC = re.compile(
    r"(?P<metric>(?:(?:real|nominal|headline|core|retail|consumer price|food|fuel|wholesale price|merchandise|private|public)\s+)?"
    r"(?:gross domestic product(?:\s*\(GDP\))?|GDP|gross value added(?:\s*\(GVA\))?|GVA|"
    r"inflation|unemployment(?: rate)?|labor force participation rate|labour force participation rate|"
    r"private consumption|private final consumption expenditure|investment|industrial sector|"
    r"agriculture sector|manufacturing sector|services sector|exports|imports|fiscal deficit|"
    r"current account deficit|foreign exchange reserves)"
    r"(?:\d)?(?:\s+growth|\s+rate)?)(?:\d)?(?:\s+for\s+FY\d{2,4}(?:/\d{2})?)?\s+"
    r"(?P<link>(?:(?:is|was|are|were|has been|has|had|is also|is estimated to be|is estimated to|"
    r"is projected to|is expected to|is forecast to|is also estimated to|has been estimated to)\s+)?"
    r"(?:grow by|grew by|expanded by|increased to|declined to|moderated to|stood at|reached|"
    r"was|is|recorded|rose to|fell to|grow at|grew at|be|of)?\s*)"
    r"(?P<value>-?\d+(?:\.\d+)?\s*(?:per cent|percent|%))", re.I)


def extract_statistics(text, owner=None):
    facts = []
    for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text):
        if re.search(r"\b(not|may|might|between|respectively|approximately|about|up to|at least)\b", sentence, re.I):
            continue
        for match in METRIC.finditer(sentence):
            # Require a grammatical assertion, rather than chart labels.
            if not match['link'].strip():
                continue
            prefix = sentence[:match.start()]
            if re.search(r"\b(share|contribution|excluding|excludes)\b", sentence, re.I):
                continue
            # Do not lose an unknown modifier (e.g. coconut-oil inflation or
            # GDP deflator inflation) by matching only its final noun.
            preceding = re.search(r"([A-Za-z-]+)\s+$", prefix)
            if preceding and not re.search(r"['’]s\s*$", prefix) and preceding[1].lower() not in {'the', 'a', 'an', 'and', 'in', 'although', 'underpinning', 'unchanged', 'average'}:
                continue
            explicit = re.search(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)['’]s\s*$", prefix)
            if explicit:
                subject = explicit[1]
            elif owner and not re.search(r"\b(global|world|advanced economies|emerging markets)\b", sentence, re.I):
                subject = owner['name']
                # A different named country in the clause invalidates inheritance.
                others = [c.name for c in pycountry.countries if c.name != subject and re.search(r"\b" + re.escape(c.name) + r"\b", sentence)]
                if others:
                    continue
            else:
                continue
            metric = match['metric'].lower()
            metric = re.sub(r"(?<=\))\d+", "", metric)
            metric = re.sub(r"gross domestic product(?:\s*\(gdp\))?", "gdp", metric)
            metric = re.sub(r"gross value added(?:\s*\(gva\))?", "gva", metric)
            if (re.search(r"grow|grew|expanded by", match['link']) or re.search(r"growth in\s*$", prefix, re.I)) and not metric.endswith('growth'):
                metric += ' growth'
            tail = sentence[match.end():]
            # Only context immediately attached to this measurement is used.
            tail = re.split(r",|;|\b(?:down from|up from|compared|whereas|while|and|before|from)\b", tail, maxsplit=1)[0]
            quote = sentence.strip()
            fact = make_fact(subject, metric, match['value'], quote, 'statistical prose')
            period_text = match[0] + tail
            period = re.search(r"\b(?:in|for|during)\s+((?:FY\s*)?20\d{2}\s*[-/]\s*\d{2,4}|FY\s*\d{2,4}|20\d{2}Q[1-4]|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d{2}|20\d{2})\b", period_text, re.I)
            special = re.search(r"\b(?:in|for|during)\s+((?:H[12]|Q[1-4])\s*FY\d{2,4}|the (?:first|second|third|fourth) quarter of FY\d{4}/\d{2}|[A-Za-z]+\s*[-–]\s*[A-Za-z]+\s+20\d{2}|[A-Za-z]+\s+20\d{2}\s*[-–]\s*[A-Za-z]+\s+20\d{2})\b", period_text, re.I)
            if special:
                period = special
            if not period:
                period = re.search(r"\bfor\s+(FY\d{2,4}(?:/\d{2})?)\b", match[0], re.I)
            label = re.sub(r"\s+", "", period[1]).upper() if period else None
            # Keep explicit ranges. Do not equate a lone fiscal label to a range
            # without knowing which start/end-year convention the source uses.
            if label:
                label = label.replace('-', '/').replace('–', '/')
                label = re.sub(r"^FY(\d{2})$", r"FY20\1", label)
            assertion_text = prefix + match['link']
            assertion = 'forecast' if re.search(r"expected|projected|forecast", assertion_text, re.I) else 'estimate' if re.search(r"estimated|estimates", assertion_text, re.I) else 'reported'
            fact['context'].update(period=label, periods=[label] if label else [], ambiguous=False,
                                   approximate=False, assertion_type=assertion,
                                   subject_inferred=not bool(explicit), scope=None)
            if metric == 'inflation':
                fact['context']['qualifier_unresolved'] = True
                fact['confidence_note'] += ' Inflation subtype is unspecified in this sentence and may depend on preceding context.'
            if metric in {'gdp', 'real gdp', 'nominal gdp', 'gva', 'real gva'}:
                continue  # A percentage is not a GDP/GVA level.
            if re.match(r"\s+of\s+GDP", tail, re.I):
                fact['normalized']['unit'] = '% of GDP'
            if not explicit:
                fact['evidence_parts'] = [dict(owner['anchor'])]
                fact['confidence_note'] += ' Country subject inferred from dominant mentions in the first 12 pages; inspect its separate evidence.'
            facts.append(fact)
    return facts
