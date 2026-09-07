import json

import pytest

from app.comparison import compare
from app.extraction import extract_model, extract_rules, make_fact, normalize_value


def fact(sentence):
    facts, issues = extract_rules(sentence)
    assert not issues, issues
    assert len(facts) == 1
    return facts[0]


@pytest.mark.parametrize('left,right,kind', [
    ("Northwind reported revenue of USD 1.2 million in FY2025.", "Northwind recorded sales of USD 1,200,000 in FY2025.", "corroborates"),
    ("Northwind employed 42 people in FY2025.", "Northwind's headcount was 51 in FY2025.", "contradicts"),
    ("Northwind reported revenue of EUR 8 million in FY2024.", "Northwind reported revenue of EUR 9 million in FY2025.", "reconciled"),
    ("Northwind reported consolidated revenue of EUR 8 million in FY2025.", "Northwind reported standalone revenue of EUR 9 million in FY2025.", "reconciled"),
    ("Northwind reported revenue of EUR 8 million in FY2025.", "Northwind reported revenue of USD 9 million in FY2025.", "uncertain"),
    ("Northwind's headcount was 42.", "Northwind's headcount was 51.", "uncertain"),
    ("Northwind's headcount was 42 in FY2025.", "Northwind's headcount was 42.", "uncertain"),
    ("Northwind's energy use was 2 MWh in FY2025.", "Northwind's energy use was 2000 kWh in FY2025.", "corroborates"),
    ("Northwind's registered office was 7 Lake Rd, Delhi in FY2025.", "Northwind's registered address was 7 Lake Road, Delhi in FY2025.", "corroborates"),
    ("Northwind's revenue was USD 8 million in FY2025.", "Northwind's revenue was USD 9 million in 2025.", "uncertain"),
    ("Northwind's status was active in FY2025.", "Northwind's status was operating in FY2025.", "uncertain"),
    ("Northwind's revenue was $8 million in FY2025.", "Northwind's revenue was $8 million in FY2025.", "uncertain"),
])
def test_comparisons(left, right, kind):
    a, b = fact(left), fact(right)
    result = compare(a, b)
    assert result['kind'] == kind
    assert compare(b, a)['kind'] == kind
    assert len(result['steps']) >= 5


def test_new_predicate_without_schema_change():
    parsed = fact("River Robotics' battery endurance was 14 in FY2026.")
    assert parsed['predicate'] == 'battery endurance'
    assert parsed['subject'] == 'River Robotics'


def test_different_legal_entities_do_not_merge():
    a = fact("Nova Ltd's headcount was 20 in FY2025.")
    b = fact("Nova Inc's headcount was 25 in FY2025.")
    assert compare(a, b) is None


@pytest.mark.parametrize('sentence', [
    "Northwind's revenue was USD 9 million and USD 12 million in FY2023 and FY2024 respectively.",
    "Northwind's headcount was approximately 42 in FY2025.",
    "Northwind's headcount was not 42 in FY2025.",
    "Northwind's headcount was between 40 and 50 in FY2025.",
    "Northwind's headcount was more than 42 in FY2025.",
    "Northwind's capacity was 2 m in FY2025.",
])
def test_abstains_on_qualifiers(sentence):
    facts, issues = extract_rules(sentence)
    assert not facts
    assert issues


def test_decimal_normalization():
    assert normalize_value('USD 0.1 million', 'revenue')['value'] == '100000'
    assert normalize_value('5000 g', 'mass')['value'] == '5'
    assert normalize_value('72 percent', 'rate')['unit'] == '%'


def test_model_rejects_invented_quote(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {'response': json.dumps({'facts': [{'subject': 'Fake', 'predicate': 'revenue', 'value': '100', 'quote': 'Fake revenue 100'}]})}
    monkeypatch.setattr('app.extraction.httpx.post', lambda *args, **kwargs: Response())
    facts, issues = extract_model('Northwind reported revenue of USD 12 million in FY2025.')
    assert not facts
    assert issues[0]['kind'] == 'rejected_model_fact'


def test_model_accepts_grounded_new_predicate(monkeypatch):
    text = "Lake Systems' signal quality was excellent in FY2025."
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {'response': json.dumps({'facts': [{'subject': 'Lake Systems', 'predicate': 'signal quality', 'value': 'excellent', 'quote': text}]})}
    monkeypatch.setattr('app.extraction.httpx.post', lambda *args, **kwargs: Response())
    facts, issues = extract_model(text)
    assert not issues
    assert facts[0]['predicate'] == 'signal quality'
