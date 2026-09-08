import pymupdf
import pytest

from app.contextual import extract_contextual, organization_context, sentences
from app.comparison import compare
from app.extraction import make_fact, normalize_value


def test_abbreviations_do_not_split_source_claims():
    source = 'Cedar Tools Pvt. Ltd. reported revenue of Rs. 80 crore in FY2024. Staff grew.'
    assert list(sentences(source)) == [source.split(' Staff')[0], 'Staff grew.']
    value = normalize_value('Rs. 80 crore', 'revenue')
    assert value['value'] == '800000000'
    assert value['unit'] == 'rs'


def test_document_context_uses_text_not_filename():
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 40), 'Cedar Tools Pvt. Ltd. is a software company founded in 2018.')
        page.insert_text((40, 70), 'Cedar reported revenue of Rs. 50 crore in FY2024.')
        owner = organization_context(pdf)
    assert owner['name'] == 'Cedar Tools Pvt. Ltd.'
    assert 'Cedar' in owner['aliases']
    f = extract_contextual('The company had 240 employees as of 31 March 2024.', owner, 'doc')[0]
    assert f['subject'] == 'Cedar Tools Pvt. Ltd'
    assert f['context']['period'] == '2024-03-31'
    assert f['evidence_parts'][0]['quote'].startswith('Cedar Tools')


def test_multiple_organizations_do_not_supply_pronoun_owner():
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40,40), 'Cedar Tools reported revenue of USD 1 million in FY2025.')
        page.insert_text((40,70), 'Cedar Health reported revenue of USD 2 million in FY2025.')
        assert organization_context(pdf) is None


def test_registered_office_relative_clause_is_not_an_address():
    assert extract_contextual('The regional language of the city, where our Registered Office is located), is used in the newspaper.', None, 'doc') == []


def test_unknown_company_match_is_possible_not_corroborated():
    a = extract_contextual('The filing records 560 employees as of 31 March 2025.', None, 'filing')[0]
    b = make_fact('Cedar Tools', 'employees', '560 employees', 'Cedar Tools employed 560 people in FY2025.')
    assert a['context']['subject_unresolved']
    assert compare(a, b)['kind'] == 'uncertain'
    b['normalized']['value'] = '561'
    assert compare(a, b) is None


def test_shared_short_alias_does_not_merge_two_distinct_companies():
    a = make_fact('Cedar Tools', 'employees', '50', 'source')
    b = make_fact('Cedar Health', 'employees', '50', 'source')
    for f in (a,b):
        f['context']['subject_aliases'] = ['Cedar']
    assert compare(a,b) is None


def test_person_events_corroborate_but_interim_is_preserved():
    a = extract_contextual('Mira Shah resigned as Chief Executive Officer effective 30 June 2025.', None, 'a')[0]
    b = extract_contextual('The announcement followed the resignation of Mira Shah on 30 June 2025.', None, 'b')[0]
    assert compare(a,b)['kind'] == 'corroborates'
    appointment = extract_contextual('Robin Jain was appointed Interim Chief Executive Officer effective 1 July 2025.', None, 'b')[0]
    assert appointment['context']['role_qualifier'] == 'interim'


@pytest.mark.parametrize('word', ['roughly', 'more than'])
def test_qualified_counts_are_not_exact(word):
    f = extract_contextual(f'The firm employs {word} 550 people.', None, 'doc')[0]
    assert f['context']['value_qualifier'] == word
