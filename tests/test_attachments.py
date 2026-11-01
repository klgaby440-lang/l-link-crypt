"""Tests de classification, extraction et réception des pièces jointes Phase 5."""

import io
import zipfile

import pytest
from fastapi.responses import JSONResponse

from llink_api.api.routes import attachment as attachment_routes
from llink_api.services.attachment_processor import (
    classify_attachment,
    extract_text_attachment,
    validate_media_signature,
)


def make_zip(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return stream.getvalue()


def test_classifies_common_multimodal_and_office_files():
    assert classify_attachment("photo.PNG") == ("image", "image/png")
    assert classify_attachment("scan.pdf") == ("document", "application/pdf")
    assert classify_attachment("voice.MP3") == ("audio", "audio/mpeg")
    assert classify_attachment("clip.mp4") == ("video", "video/mp4")
    assert classify_attachment("notes.txt") == ("text", "text/plain")
    assert classify_attachment("report.docx") == ("document", "Word")
    assert classify_attachment("table.xlsx") == ("spreadsheet", "Excel")
    assert classify_attachment("slides.pptx") == ("presentation", "PowerPoint")
    assert classify_attachment("binary.unknown") is None


def test_extracts_plain_text_and_html_without_script_content():
    kind, text = extract_text_attachment("notes.txt", b"Bonjour Llink")
    assert kind == "text"
    assert text == "Bonjour Llink"

    kind, html_text = extract_text_attachment(
        "page.html",
        b"<h1>Titre</h1><script>secret()</script><p>Texte visible</p>",
    )
    assert kind == "text"
    assert "Titre" in html_text
    assert "Texte visible" in html_text
    assert "secret" not in html_text


def test_extracts_docx_text():
    data = make_zip({
        "word/document.xml": (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b'<w:body><w:p><w:r><w:t>Document Llink</w:t></w:r></w:p></w:body></w:document>'
        )
    })
    kind, text = extract_text_attachment("report.docx", data)
    assert kind == "document"
    assert "Document Llink" in text


def test_extracts_xlsx_shared_and_inline_cell_values():
    data = make_zip({
        "xl/workbook.xml": (
            b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            b'<sheets><sheet name="Feuille1" sheetId="1" r:id="rId1" '
            b'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets>'
            b'</workbook>'
        ),
        "xl/sharedStrings.xml": (
            b'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            b'<si><t>Chiffre</t></si></sst>'
        ),
        "xl/worksheets/sheet1.xml": (
            b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            b'<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c>'
            b'<c r="B1"><v>42</v></c></row></sheetData></worksheet>'
        ),
    })
    kind, text = extract_text_attachment("table.xlsx", data)
    assert kind == "spreadsheet"
    assert "A1=Chiffre" in text
    assert "B1=42" in text


def test_extracts_pptx_slide_text():
    data = make_zip({
        "ppt/slides/slide1.xml": (
            b'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            b'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            b'<a:t>Diapositive de test</a:t></p:sld>'
        )
    })
    kind, text = extract_text_attachment("slides.pptx", data)
    assert kind == "presentation"
    assert "Diapositive de test" in text


def test_rejects_invalid_office_zip():
    with pytest.raises(ValueError):
        extract_text_attachment("bad.docx", b"not a zip")


def test_validates_image_and_pdf_signatures():
    validate_media_signature("image", "image/png", b"\x89PNG\r\n\x1a\npayload")
    validate_media_signature("document", "application/pdf", b"%PDF-1.7\npayload")
    with pytest.raises(ValueError):
        validate_media_signature("image", "image/png", b"not an image")
    with pytest.raises(ValueError):
        validate_media_signature("document", "application/pdf", b"not a pdf")


def prepare_attachment_route(monkeypatch, captured):
    async def allow_quota(**_kwargs):
        return None

    async def fake_chat(payload, request, user, db):
        captured["message"] = payload.message
        captured["level"] = payload.level
        return JSONResponse({"message": payload.message})

    monkeypatch.setattr(attachment_routes, "enforce_endpoint_quota", allow_quota)
    monkeypatch.setattr(attachment_routes, "resolve_entitled_level", lambda _user, _db: "velora")
    monkeypatch.setattr(attachment_routes, "chat_endpoint", fake_chat)


def test_multipart_attachment_route_extracts_text_and_reuses_chat(client, monkeypatch):
    captured = {}
    prepare_attachment_route(monkeypatch, captured)
    response = client.post(
        "/api/chat/attachments",
        data={
            "message": "Résume ce fichier.",
            "model": "gemini-1.5-flash",
            "level": "velora",
            "history": "[]",
            "mode": "chat",
        },
        files=[("files", ("notes.txt", b"Contenu important du fichier.", "text/plain"))],
    )
    assert response.status_code == 200
    assert "Contenu important du fichier." in captured["message"]
    assert "Résume ce fichier." in captured["message"]
    assert response.headers["x-llink-attachment-count"] == "1"


def test_multipart_route_accepts_unknown_extensions_but_discloses_limitation(
    client, monkeypatch
):
    captured = {}
    prepare_attachment_route(monkeypatch, captured)
    response = client.post(
        "/api/chat/attachments",
        data={"message": "Que contient ce fichier?", "model": "gemini-1.5-flash"},
        files=[("files", ("archive.custom", b"\x00\x01\x02", "application/octet-stream"))],
    )
    assert response.status_code == 200
    assert "archive.custom" in captured["message"]
    assert "ne dispose pas encore d'un extracteur" in captured["message"]


def test_multipart_route_rejects_invalid_pdf_signature(client, monkeypatch):
    captured = {}
    prepare_attachment_route(monkeypatch, captured)
    response = client.post(
        "/api/chat/attachments",
        data={"message": "Lis le PDF", "model": "gemini-1.5-flash"},
        files=[("files", ("fake.pdf", b"not a pdf", "application/pdf"))],
    )
    assert response.status_code == 415


def test_multipart_route_enforces_per_file_limit(client, monkeypatch):
    captured = {}
    prepare_attachment_route(monkeypatch, captured)
    monkeypatch.setenv("MAX_ATTACHMENT_BYTES", "5")
    response = client.post(
        "/api/chat/attachments",
        data={"message": "Lis ce fichier", "model": "gemini-1.5-flash"},
        files=[("files", ("notes.txt", b"123456", "text/plain"))],
    )
    assert response.status_code == 413


def test_multipart_route_enforces_file_count_limit(client, monkeypatch):
    captured = {}
    prepare_attachment_route(monkeypatch, captured)
    monkeypatch.setenv("MAX_ATTACHMENT_FILES", "1")
    response = client.post(
        "/api/chat/attachments",
        data={"message": "Lis les fichiers", "model": "gemini-1.5-flash"},
        files=[
            ("files", ("one.txt", b"one", "text/plain")),
            ("files", ("two.txt", b"two", "text/plain")),
        ],
    )
    assert response.status_code == 413
