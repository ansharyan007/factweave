import pymupdf

from app.comparison import compare
from app.extraction import context, extract_rules, normalize_value
from app.layout import document_subject, extract_layout


def test_short_fiscal_year_and_quarter():
    assert context("FY24")["period"] == "FY2024"
    assert context("Q4 FY24")["period"] == "Q4FY2024"
    assert context("FY2024/25")["period"] == "FY2024/25"


def test_rounding_reconciliation():
    from app.extraction import make_fact
    a=make_fact("Example Limited","revenue from services","INR 81415 million","INR 81415 million in FY2024")
    b=make_fact("Example Limited","revenue from services","INR 8142 crore","INR 8142 crore in FY2024")
    assert compare(a,b)["kind"] == "reconciled"
    assert "precision" in compare(a,b)["reason"]


def test_rejects_non_entity_clause():
    facts,issues=extract_rules("As our business depends on our customers' trust in us and our platform, we are committed to privacy.")
    assert not facts
    assert issues


def test_layout_on_unseen_company_and_metric():
    with pymupdf.open() as pdf:
        page=pdf.new_page()
        page.insert_text((40,40),"For Lumen Systems Limited",fontsize=10)
        page.insert_text((40,90),"FY27",fontsize=16)
        page.insert_text((40,150),"45 Mn",fontsize=28)
        page.insert_text((40,172),"Sensors shipped",fontsize=11)
        subject=document_subject(pdf)
        assert subject["subject"]=="Lumen Systems Limited"
        facts=extract_layout(page,1,subject)
        assert len(facts)==1
        assert facts[0]["predicate"]=="sensors shipments"
        assert facts[0]["normalized"]["value"]=="45000000"
        assert facts[0]["context"]["period"]=="FY2027"
        assert len(facts[0]["evidence_parts"])==4


def test_column_headers_and_footnotes():
    with pymupdf.open() as pdf:
        page=pdf.new_page()
        page.insert_text((40,40),"For Lumen Systems Limited")
        page.insert_text((250,90),"Q4 FY25")
        page.insert_text((400,90),"Q4 FY26")
        page.insert_text((40,125),"Active sensors(1)")
        page.insert_text((265,125),"450")
        page.insert_text((415,125),"480")
        facts=extract_layout(page,1,document_subject(pdf))
        assert len(facts)==2
        assert {f["context"]["period"] for f in facts}=={"Q4FY2025","Q4FY2026"}
        assert all(f["context"]["qualifier_unresolved"] for f in facts)
        assert compare(*facts)["kind"]=="uncertain"


def test_rejects_partial_mapping_under_grouped_years():
    with pymupdf.open() as pdf:
        page=pdf.new_page()
        page.insert_text((40,40),"For Lumen Systems Limited")
        page.insert_text((250,90),"FY25")
        page.insert_text((400,90),"FY26")
        page.insert_text((40,125),"Wages")
        for x,value in [(265,"74"),(310,"0"),(415,"58"),(460,"0")]:
            page.insert_text((x,125),value)
        assert extract_layout(page,1,document_subject(pdf)) == []
