"""Prose claims with separately grounded document context and explicit uncertainty.

No filenames select rules. Missing organization names remain document-local;
they are never filled in from the other uploaded documents.
"""
import re
from datetime import datetime

from .extraction import clean, canonical, make_fact, valid_subject

NAME = r"[A-Z][\w&.'-]*(?:\s+[A-Z][\w&.'-]*){0,6}"
LEGAL = r"\s+(?:(?:Pvt\.?|Private)\s+)?(?:Ltd\.?|Limited|Inc\.?|Corporation|PLC)$"
DATE = r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}"
VALUE = r"(?:USD|EUR|GBP|INR|Rs\.?|US\$|[$€£₹])?\s*\d[\d,]*(?:\.\d+)?(?:\s*(?:billion|million|thousand|crore|lakh|percent|per cent|%))?"


def sentences(text):
    start = 0
    for match in re.finditer(r"(?<=[.!?])\s+(?=[A-Z])|\n+", text):
        last = text[start:match.start()].split()
        if last and last[-1].lower() in {'rs.', 'pvt.', 'ltd.', 'inc.', 'mr.', 'ms.', 'dr.', 'u.s.'}:
            continue
        yield text[start:match.start()].strip()
        start = match.end()
    if text[start:].strip():
        yield text[start:].strip()


def organization_context(pdf):
    candidates = {}
    for index in range(min(len(pdf), 12)):
        for block in pdf[index].get_text('blocks'):
            if block[6] != 0:
                continue
            for sentence in sentences(clean(block[4])):
                patterns = [r"^(" + NAME + r")\s+(?:reported|recorded|generated|posted|announced|increased its|was founded|is a .*company)",
                            r"\bdescribes\s+(" + NAME + r")\s+as\b"]
                for pattern in patterns:
                    match = re.search(pattern, sentence)
                    if match and valid_subject(match[1]) and canonical(match[1]) not in {'our company', 'the company', 'our group', 'the group', 'the firm'}:
                        candidates[match[1]] = {'role': 'document organization', 'quote': sentence,
                                                'page': index+1, 'bbox': list(block[:4])}
    if not candidates:
        return None
    best = max(candidates, key=len)
    base = re.sub(LEGAL, '', best)
    # Do not inherit a subject if the document explicitly discusses multiple
    # organizations, even if they share a common name prefix.
    if any(not (base == n or base.startswith(n+' ') or best == n) for n in candidates):
        return None
    return {'name': best, 'anchor': candidates[best],
            'aliases': sorted(set(candidates) | {base})}


def dated_context(fact, sentence):
    ctx = fact['context']
    dates = re.findall(DATE, sentence, re.I)
    if len(set(dates)) == 1:
        stamp = datetime.strptime(dates[0].title(), '%d %B %Y').date().isoformat()
        if re.search(r'financial.year ended', sentence, re.I):
            ctx.update(period='FY'+stamp[:4], period_end=stamp, period_kind='fiscal')
        else:
            ctx.update(period=stamp, period_kind='date')
    calendar = re.search(r'calendar.year\s+(\d{4})', sentence, re.I)
    if calendar:
        ctx.update(period='CY'+calendar[1], period_kind='calendar')
    if ctx.get('period'):
        ctx['periods'] = [ctx['period']]
        ctx['ambiguous'] = False


def reporting_periods(pdf):
    periods = {}
    for index in range(min(len(pdf), 12)):
        for block in pdf[index].get_text('blocks'):
            if block[6] != 0:
                continue
            for sentence in sentences(clean(block[4])):
                dates = re.findall(DATE, sentence, re.I)
                fiscal = re.search(r'\bFY(\d{4})\s+ended on\b', sentence, re.I)
                calendar = re.search(r'\bcalendar.year figure covers\b', sentence, re.I)
                if fiscal and len(dates) == 1:
                    label, end = 'FY'+fiscal[1], datetime.strptime(dates[0], '%d %B %Y').date().isoformat()
                    value = {'period_end': end, 'period_kind': 'fiscal'}
                elif calendar and len(dates) == 2:
                    start, end = [datetime.strptime(d, '%d %B %Y').date().isoformat() for d in dates]
                    if start[5:] != '01-01' or end[5:] != '12-31' or start[:4] != end[:4]:
                        continue
                    label, value = 'CY'+end[:4], {'period_start': start, 'period_end': end, 'period_kind': 'calendar'}
                else:
                    continue
                value['anchor'] = {'role': 'reporting period definition', 'quote': sentence, 'page': index+1, 'bbox': list(block[:4])}
                if label in periods and periods[label] != value:
                    periods[label] = None  # conflicting definitions are not inherited
                else:
                    periods[label] = value
    return periods


def extract_contextual(text, owner, document_id):
    facts = []
    for sentence in sentences(text):
        if re.search(r'\b(not|no longer|may|might|respectively|between)\b', sentence, re.I):
            continue
        subject = owner['name'] if owner else 'Unspecified organization'
        inferred = True
        explicit = re.match(r'^('+NAME+r")\s+(?:reported|recorded|generated|posted|announced|increased|employs|employed|serves|was founded)", sentence)
        if explicit and valid_subject(explicit[1]):
            subject, inferred = explicit[1], False
            if owner and subject in owner['aliases']:
                subject = owner['name']

        def emit(predicate, value, named_subject=None):
            f = make_fact(named_subject or subject, predicate, value, sentence, 'contextual prose')
            dated_context(f, sentence)
            if not named_subject:
                f['context']['subject_inferred'] = inferred
                if owner:
                    f['context']['subject_aliases'] = owner['aliases']
                    f.setdefault('evidence_parts', []).append(dict(owner['anchor']))
                    f['confidence_note'] += ' Organization context and observed short names come from the separate source span.'
                elif inferred:
                    f['subject_key'] = 'unresolved:' + document_id
                    f['context']['subject_unresolved'] = True
                    f['confidence_note'] += ' The organization is unnamed; cross-document identity is unresolved.'
            bound = re.search(r'\b(more than|over|at least|roughly|approximately|about)\s+\d', sentence, re.I)
            if bound:
                f['context']['value_qualifier'] = bound[1].lower()
                f['context']['approximate'] = True
            if re.search(r'\b(registered|principal) office\b', sentence, re.I):
                f['context']['scope'] = re.search(r'\b(registered|principal) office\b', sentence, re.I)[0].lower()
            facts.append(f)
            return f

        # Dynamic predicates in explicit possessive change grammar.
        change = re.search(r'\bincreased its\s+([a-z][a-z ]{1,60}?)\s+to\s+('+VALUE+r')', sentence)
        if change and not inferred:
            emit(change[1], change[2])
        else:
            metric = re.search(r'\b(revenue|sales|turnover|net profit|operating profit)\s+(?:reached|of|was|stood at|totaled|totalled)\s+('+VALUE+r')', sentence, re.I)
            if metric and (owner or explicit or re.match(r'^(?:The company|The firm)\b',sentence)):
                emit(metric[1], metric[2])
        employees = re.search(r'\b(?:had|has|employs|employed|records)\s+(?:(?:roughly|approximately|more than|over|at least)\s+)?(\d[\d,]*)\s+(?:employees|people)\b', sentence, re.I)
        strength = re.search(r'\bemployee strength\s+(?:increased to|was|reached)\s+(\d[\d,]*)\s+people\b', sentence, re.I)
        if employees or strength:
            emit('employees', (employees or strength)[1]+' employees')
        customers = re.search(r'\bserves\s+(?:(?:over|more than|at least)\s+)?(\d[\d,]*)\s+customers\b|\bused by\s+(?:(?:over|more than|at least)\s+)?(\d[\d,]*)\s+(?:business\s+)?customers\b', sentence, re.I)
        if customers:
            emit('customers', (customers[1] or customers[2]))
        founded = re.search(r'\bfounded in\s+(\d{4})\b', sentence, re.I)
        if founded and (owner or explicit):
            f = emit('founding year', founded[1])
            f['context'].update(period=None, periods=[])
        address = re.search(r'\b(?:based at|registered office is)\s+(.+?)(?:\.$|$)', sentence, re.I)
        if address and re.match(r'\d', address[1]) and len(address[1]) <= 200:
            emit('address', address[1])
        location = re.search(r'\bas a\s+([A-Z][a-z]+)-based company\b', sentence)
        if location:
            emit('office city', location[1])

        role = r'(?:Interim\s+)?(?:Chief Executive Officer|CEO)'
        # Person-level role events work even when the organization is unnamed.
        appointment = re.search(r'('+NAME+r')\s+(?:(was appointed|had become|continued as|was)\s+(?:the\s+)?('+role+r')|(resigned)\s+as\s+('+role+r'))', sentence)
        resignation = re.search(r'\bresignation of\s+('+NAME+r')\s+on\s+('+DATE+r')', sentence)
        if appointment or resignation:
            person = (appointment or resignation)[1]
            action = 'resigned' if resignation or (appointment and appointment[4]) else 'active'
            f = emit('chief executive role status', action, person)
            f['context']['role_qualifier'] = 'interim' if appointment and 'Interim' in (appointment[3] or appointment[5] or '') else 'unspecified'
            f['context']['organization'] = owner['name'] if owner else None
            if owner:
                f.setdefault('evidence_parts', []).append(dict(owner['anchor']))
            f['context']['event_type'] = action
    return facts
