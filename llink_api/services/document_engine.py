"""Moteur de génération de documents Word structurés pour Llink Work."""

from __future__ import annotations

import base64
import binascii
import io
import re
from typing import Any

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from PIL import Image, UnidentifiedImageError

MAX_BLOCKS = 160
MAX_TEXT_CHARS = 30_000
MAX_IMAGE_BYTES = 4_000_000
MAX_IMAGE_PIXELS = 20_000_000
MAX_TABLE_ROWS = 50
MAX_TABLE_COLUMNS = 12
ALLOWED_BLOCKS = {
    "paragraph", "heading", "bullet", "numbered", "quote",
    "table", "image", "caption", "page_break",
}


def _text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str):
        raise ValueError("Le texte d'un bloc doit être une chaîne.")
    if len(value) > limit:
        raise ValueError("Un bloc de texte dépasse la limite autorisée.")
    return value


def _set_cell_shading(cell: Any, fill: str) -> None:
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shading)


def _set_repeat_table_header(row: Any) -> None:
    properties = row._tr.get_or_add_trPr()
    repeat = OxmlElement("w:tblHeader")
    repeat.set(qn("w:val"), "true")
    properties.append(repeat)


def _add_page_number(paragraph: Any) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run("Page ")
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin, instruction, separate, text, end])


def _image_bytes(data_url: str) -> bytes:
    match = re.fullmatch(
        r"data:image/(png|jpeg);base64,([A-Za-z0-9+/=]+)",
        data_url or "",
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError("Une image doit être fournie en data URL PNG ou JPEG.")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Les données de l'image sont invalides.") from exc
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("Une image ne peut pas dépasser 4 Mo.")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in {"PNG", "JPEG"}:
                raise ValueError("Seules les images PNG et JPEG sont acceptées.")
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError("La résolution de l'image dépasse la limite autorisée.")
            source.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Le fichier image est illisible.") from exc
    return raw


def _add_image(document: Document, block: dict[str, Any]) -> None:
    raw = _image_bytes(_text(block.get("data_url", ""), MAX_IMAGE_BYTES * 2))
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(6)
    paragraph.paragraph_format.space_after = Pt(2)
    run = paragraph.add_run()
    picture = run.add_picture(io.BytesIO(raw), width=Inches(5.6))
    alt = block.get("alt")
    if isinstance(alt, str) and alt.strip():
        picture._inline.docPr.set("descr", alt.strip()[:500])


def _add_table(document: Document, block: dict[str, Any]) -> None:
    rows = block.get("rows")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_TABLE_ROWS:
        raise ValueError("Un tableau doit contenir entre 1 et 50 lignes.")
    normalized: list[list[str]] = []
    for row in rows:
        if not isinstance(row, list) or not row or len(row) > MAX_TABLE_COLUMNS:
            raise ValueError("Chaque ligne du tableau doit contenir entre 1 et 12 cellules.")
        normalized.append([_text(cell, 3_000) for cell in row])
    columns = max(len(row) for row in normalized)
    table = document.add_table(rows=len(normalized), cols=columns)
    table.style = "Table Grid"
    table.autofit = True
    for row_index, values in enumerate(normalized):
        row = table.rows[row_index]
        for column_index in range(columns):
            cell = row.cells[column_index]
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            cell.text = values[column_index] if column_index < len(values) else ""
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_after = Pt(2)
                for run in paragraph.runs:
                    run.font.size = Pt(8.5)
                    if row_index == 0:
                        run.bold = True
            if row_index == 0:
                _set_cell_shading(cell, "DCE8E2")
        if row_index == 0:
            _set_repeat_table_header(row)


def build_structured_docx(payload: dict[str, Any]) -> bytes:
    """Construit un DOCX natif depuis une liste de blocs contrôlés."""
    blocks = payload.get("blocks")
    if not isinstance(blocks, list) or not blocks or len(blocks) > MAX_BLOCKS:
        raise ValueError("Le document doit contenir entre 1 et 160 blocs.")

    document = Document()
    section = document.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)

    properties = document.core_properties
    properties.title = _text(payload.get("title", "Document créé avec Llink Work"), 300)
    properties.subject = "Document généré par Llink Work"
    properties.author = _text(payload.get("author", "Llink Work"), 160)

    normal = document.styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = RGBColor(38, 48, 43)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.12

    for style_name, size in (("Title", 25), ("Heading 1", 17), ("Heading 2", 14), ("Heading 3", 12)):
        style = document.styles[style_name]
        style.font.name = "Aptos Display"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(33, 82, 59)
        style.font.bold = True

    header = section.header.paragraphs[0]
    header.text = "LLINK WORK"
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for run in header.runs:
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(105, 120, 110)
    _add_page_number(section.footer.paragraphs[0])

    title = _text(payload.get("title", ""), 300).strip()
    subtitle = _text(payload.get("subtitle", ""), 500).strip()
    if title:
        p = document.add_paragraph(style="Title")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(36)
        p.paragraph_format.space_after = Pt(8)
        p.add_run(title)
    if subtitle:
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(18)
        run = p.add_run(subtitle)
        run.italic = True
        run.font.size = Pt(13)
        run.font.color.rgb = RGBColor(88, 103, 93)

    author = _text(payload.get("author", ""), 160).strip()
    institution = _text(payload.get("institution", ""), 200).strip()
    if author or institution:
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(20)
        meta = " — ".join(value for value in (author, institution) if value)
        run = p.add_run(meta)
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(100, 110, 104)

    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            raise ValueError(f"Le bloc {index + 1} doit être un objet.")
        kind = str(block.get("type", "")).strip().lower()
        if kind not in ALLOWED_BLOCKS:
            raise ValueError(f"Type de bloc non pris en charge : {kind or 'vide'}.")

        if kind == "page_break":
            document.add_page_break()
        elif kind == "heading":
            level = block.get("level", 1)
            if isinstance(level, bool) or not isinstance(level, int) or level not in {1, 2, 3}:
                raise ValueError("Le niveau d'un titre doit être 1, 2 ou 3.")
            document.add_heading(_text(block.get("text", "")), level=level)
        elif kind in {"paragraph", "bullet", "numbered", "quote", "caption"}:
            value = _text(block.get("text", ""))
            if kind == "bullet":
                paragraph = document.add_paragraph(style="List Bullet")
            elif kind == "numbered":
                paragraph = document.add_paragraph(style="List Number")
            elif kind == "quote":
                paragraph = document.add_paragraph(style="Quote")
            else:
                paragraph = document.add_paragraph()
            run = paragraph.add_run(value)
            if kind == "caption":
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run.italic = True
                run.font.size = Pt(9)
                run.font.color.rgb = RGBColor(95, 105, 98)
            elif kind == "quote":
                run.italic = True
        elif kind == "table":
            _add_table(document, block)
            document.add_paragraph()
        elif kind == "image":
            _add_image(document, block)
        if len(document.paragraphs) > 1_000:
            raise ValueError("Le document contient trop de paragraphes.")

    output = io.BytesIO()
    document.save(output)
    return output.getvalue()
