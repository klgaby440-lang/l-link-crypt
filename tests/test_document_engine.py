"""Tests du moteur de génération DOCX structuré de Llink Work."""

import base64
import io

import pytest
from docx import Document
from PIL import Image

from llink_api.services.document_engine import build_structured_docx


def _sample_png_data_url() -> str:
    image = Image.new("RGB", (24, 24), color=(30, 120, 80))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def test_structured_docx_contains_title_headings_lists_and_table():
    payload = {
        "filename": "rapport.docx",
        "title": "Étude botanique",
        "subtitle": "Famille des Pinaceae",
        "author": "Mugisho Baganda Divin",
        "institution": "3ème H/Scientifique",
        "blocks": [
            {"type": "heading", "level": 1, "text": "Introduction"},
            {"type": "paragraph", "text": "Les Pinaceae sont des conifères résineux."},
            {"type": "bullet", "text": "Feuilles généralement aciculaires"},
            {"type": "numbered", "text": "Pollinisation principalement anémophile"},
            {"type": "quote", "text": "La graine est nue."},
            {"type": "table", "rows": [["Genre", "Exemple"], ["Pinus", "Pin sylvestre"]]},
        ],
    }

    raw = build_structured_docx(payload)
    document = Document(io.BytesIO(raw))
    paragraphs = [paragraph.text for paragraph in document.paragraphs]

    assert "Étude botanique" in paragraphs
    assert "Introduction" in paragraphs
    assert "Les Pinaceae sont des conifères résineux." in paragraphs
    assert len(document.tables) == 1
    assert document.tables[0].cell(1, 0).text == "Pinus"


def test_structured_docx_can_embed_a_valid_png_and_caption():
    payload = {
        "title": "Pinaceae illustrées",
        "blocks": [
            {"type": "image", "data_url": _sample_png_data_url(), "alt": "Branche de pin"},
            {"type": "caption", "text": "Figure 1 — Illustration botanique"},
        ],
    }

    document = Document(io.BytesIO(build_structured_docx(payload)))

    assert len(document.inline_shapes) == 1
    assert any(paragraph.text.startswith("Figure 1") for paragraph in document.paragraphs)


@pytest.mark.parametrize(
    "block",
    [
        {"type": "image", "data_url": "https://example.com/plant.png"},
        {"type": "image", "data_url": "data:image/svg+xml;base64,PHN2Zy8+"},
        {"type": "heading", "level": 7, "text": "Niveau interdit"},
    ],
)
def test_structured_docx_rejects_untrusted_or_invalid_blocks(block):
    with pytest.raises(ValueError):
        build_structured_docx({"title": "Document invalide", "blocks": [block]})



def test_structured_docx_preserves_rich_text_runs():
    payload = {
        "title": "Texte mis en forme",
        "blocks": [{
            "type": "paragraph",
            "text": "Important et italique",
            "runs": [
                {"text": "Important", "bold": True},
                {"text": " et "},
                {"text": "italique", "italic": True},
            ],
        }],
    }
    document = Document(io.BytesIO(build_structured_docx(payload)))
    runs = document.paragraphs[-1].runs
    assert "".join(run.text for run in runs) == "Important et italique"
    assert runs[0].bold is True
    assert runs[2].italic is True
