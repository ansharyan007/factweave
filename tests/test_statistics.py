import pytest

from app.comparison import compare
from app.extraction import normalize_value
from app.statistics import extract_statistics, reading_blocks

OWNER = {'name': 'India', 'anchor': {'quote': 'India', 'page': 1, 'bbox': [0, 0, 100, 20]}}


def test_percent_wording_and_grounded_cross_document_match():
    a = extract_statistics("India's real GDP grew by 6.5 per cent in FY2024/25.")[0]
    b = extract_statistics("India's real gross domestic product (GDP) growth moderated to 6.5 percent in FY2024/25.")[0]
    assert compare(a, b)['kind'] == 'corroborates'
    assert a['raw_value'] in a['quote']
    assert normalize_value('6.5 per cent', 'growth')['value'] == '6.5'


def test_columns_reconstruct_without_crossing():
    blocks = [(50,50,280,68,'Although real gross domestic product (GDP)3',0,0),
              (320,50,560,68,'Other text in the right hand column',1,0),
              (50,67,280,85,'growth moderated to 6.5 per cent in 2024-25,',2,0),
              (320,67,560,85,'continues separately with its own content.',3,0)]
    groups = reading_blocks(blocks)
    assert len(groups) == 2
    facts = extract_statistics(groups[0][4], OWNER)
    assert facts[0]['predicate'] == 'real gdp growth'
    assert facts[0]['context']['period'] == '2024/25'
    assert facts[0]['context']['scope'] is None  # 'domestic product' is not scope
    assert 'right hand' not in facts[0]['quote']


@pytest.mark.parametrize('text', [
    'Their contribution to overall inflation stood at 32.3 per cent in FY25.',
    'The share of PFCE in real GDP increased to 56.7 per cent in 2024-25.',
    'Coconut oil inflation increased to 10.2 percent in 2025.',
    'Average headline inflation is 4.2 percent when excluding food.',
    'Global real GDP grew by 3.2 percent in 2025.',
    'Canada reported that real GDP grew by 3.2 percent in 2025.',
    'Real GDP may grow by 6.2 percent in 2025.',
])
def test_unsupported_context_not_silently_lost(text):
    assert extract_statistics(text, OWNER) == []


def test_quarter_does_not_inherit_previous_claim_year():
    f = extract_statistics('Following economic growth of 6.5 percent in FY2024/25, real GDP expanded by 7.8 percent in the first quarter of FY2025/26.', OWNER)[0]
    assert f['context']['period'] == 'THEFIRSTQUARTEROFFY2025/26'


def test_estimates_and_forecasts_are_qualified():
    estimate = extract_statistics("India's real GDP is estimated to grow by 6.4 per cent in FY25.")[0]
    actual = extract_statistics("India's real GDP grew by 6.5 percent in FY25.")[0]
    assert estimate['context']['assertion_type'] == 'estimate'
    assert compare(estimate, actual)['kind'] == 'uncertain'
    forecast = extract_statistics('IMF has projected an inflation rate of 4.4 per cent in FY25 and 4.1 per cent in FY26 for India.', OWNER)[0]
    assert forecast['context']['assertion_type'] == 'forecast'


def test_explicit_subject_beats_document_subject():
    f = extract_statistics("Canada's real GDP grew by 2 percent in 2025.", OWNER)[0]
    assert f['subject'] == 'Canada'
    assert not f['context']['subject_inferred']


def test_temporal_modifiers_and_metric_modifiers_survive():
    f = extract_statistics('Fuel inflation increased to 1.5 per cent in March 2025.', OWNER)[0]
    assert f['predicate'] == 'fuel inflation'
    assert f['context']['period'] == 'MARCH2025'
    f = extract_statistics('Merchandise imports grew by 5.2 per cent during April-December 2024.', OWNER)[0]
    assert f['predicate'] == 'merchandise imports growth'
    assert f['context']['period'] == 'APRIL/DECEMBER2024'


def test_period_inside_metric_grammar():
    f = extract_statistics('The real gross domestic product (GDP) growth for FY25 is estimated to be 6.4 per cent.', OWNER)[0]
    assert f['context']['period'] == 'FY2025'
    assert f['context']['assertion_type'] == 'estimate'
