from datetime import date
from types import SimpleNamespace

from src.services.document_intelligence import completeness_issues, staleness_issues


def doc(**kwargs):
    defaults = {
        "id": "d",
        "family_key": None,
        "document_type": "other",
        "amendment_number": None,
        "relevant": True,
        "as_of_date": None,
        "document_date": None,
    }
    return SimpleNamespace(**(defaults | kwargs))


def test_missing_amendment_chain_is_detected():
    documents = [
        doc(document_type="lease", family_key="Acme / Suite 1"),
        doc(document_type="lease_amendment", family_key="Acme / Suite 1", amendment_number=2),
    ]
    issues = completeness_issues(documents)
    assert any(i["code"] == "missing_lease_amendment" and i["missing_number"] == 1 for i in issues)


def test_expired_modeled_lease_and_old_rent_roll_are_flagged():
    documents = [doc(document_type="rent_roll", as_of_date=date(2025, 1, 1))]
    leases = [SimpleNamespace(id="lease-1", lease_end_date=date(2025, 12, 31))]
    issues = staleness_issues(documents, date(2026, 1, 1), leases)
    assert {issue["code"] for issue in issues} == {"expired_lease_in_model", "stale_document"}


def test_completeness_names_what_the_model_is_missing():
    issues = completeness_issues([doc(document_type="rent_roll")])
    assert {i["code"] for i in issues} == {"missing_expense_source", "missing_assumption_source"}
    assert completeness_issues([doc(document_type="appraisal")]) == []
    assert completeness_issues([doc(document_type=None)]) == []


def test_excel_rent_roll_is_rendered_as_text():
    import io

    from openpyxl import Workbook

    from src.services.document_intelligence import spreadsheet_text

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Rent Roll"
    sheet.append(["Tenant", "SF", "Rent"])
    sheet.append(["Acme", 5000, 32.5])
    stream = io.BytesIO()
    workbook.save(stream)

    text = spreadsheet_text(stream.getvalue())
    assert "## Sheet: Rent Roll" in text
    assert "Acme,5000,32.5" in text
