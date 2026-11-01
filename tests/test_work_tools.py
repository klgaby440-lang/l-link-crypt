"""Tests des outils Work et des garde-fous d'export."""

import io

import pytest
from fastapi import HTTPException

from llink_api.api.routes.work_tools import create_export_bytes, safe_output_filename


def test_work_output_filename_strips_paths_and_normalizes_extension():
    assert safe_output_filename("../../rapport final", "pdf") == "rapport final.pdf"
    assert safe_output_filename("résumé.docx", "docx") == "résumé.docx"
    assert "/" not in safe_output_filename("folder\\\\tableau", "xlsx")


def test_work_export_rejects_oversized_content():
    with pytest.raises(HTTPException) as exc:
        create_export_bytes("pdf", "x" * 700_001)
    assert exc.value.status_code == 413


def test_work_pdf_export_returns_real_pdf():
    content, media_type = create_export_bytes("pdf", "# Rapport\n\nContenu du document.")
    assert media_type == "application/pdf"
    assert content.startswith(b"%PDF-")


def test_work_docx_export_returns_office_package():
    content, media_type = create_export_bytes("docx", "# Rapport\n\nContenu du document.")
    assert media_type.startswith("application/vnd.openxmlformats")
    assert content.startswith(b"PK")


def test_work_xlsx_export_accepts_json_rows_and_neutralizes_formulas():
    from openpyxl import load_workbook

    content, media_type = create_export_bytes(
        "xlsx",
        '[{"nom":"Ada","score":12},{"nom":"=2+2","score":15}]',
    )
    workbook = load_workbook(io.BytesIO(content), data_only=False)
    sheet = workbook.active
    assert media_type.startswith("application/vnd.openxmlformats")
    assert sheet["A1"].value == "nom"
    assert sheet["A3"].value == "'=2+2"
    assert sheet["A3"].data_type == "s"


def test_work_tool_routes_require_authentication(client):
    assert client.get("/api/work/tools").status_code == 401
    assert client.post(
        "/api/work/tools/search",
        json={"query": "actualité scientifique"},
    ).status_code == 401
    assert client.post(
        "/api/work/tools/python",
        json={"code": "print(1 + 1)"},
    ).status_code == 401
    assert client.post(
        "/api/work/exports/pdf",
        json={"filename": "rapport.pdf", "content": "Bonjour"},
    ).status_code == 401
