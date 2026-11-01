"""Classification et extraction contrôlée des pièces jointes Llink."""

from __future__ import annotations

import io
import re
import zipfile
from html.parser import HTMLParser
from pathlib import PurePosixPath
from xml.etree import ElementTree

MAX_ARCHIVE_ENTRIES = 500
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 32_000_000
MAX_EXTRACTED_CHARS_PER_FILE = 18_000

TEXT_MIME_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".xml": "text/xml",
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".py": "text/x-python",
    ".sql": "application/sql",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".toml": "application/toml",
    ".ini": "text/plain",
    ".log": "text/plain",
    ".rtf": "application/rtf",
    ".sh": "text/plain",
    ".java": "text/plain",
    ".c": "text/plain",
    ".cpp": "text/plain",
    ".h": "text/plain",
    ".cs": "text/plain",
    ".go": "text/plain",
    ".rs": "text/plain",
    ".php": "text/plain",
    ".rb": "text/plain",
    ".ipynb": "application/json",
}

IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".heic": "image/heic",
    ".heif": "image/heif",
}

AUDIO_MIME_TYPES = {
    ".mp3": "audio/mpeg",
    ".mpga": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mp4a": "audio/mp4",
    ".aac": "audio/aac",
    ".pcm": "audio/pcm",
}

VIDEO_MIME_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mpeg": "video/mpeg",
    ".mpg": "video/mpg",
    ".avi": "video/avi",
    ".wmv": "video/wmv",
    ".3gp": "video/3gpp",
    ".flv": "video/x-flv",
}

OFFICE_TYPES = {
    ".docx": ("document", "Word"),
    ".xlsx": ("spreadsheet", "Excel"),
    ".pptx": ("presentation", "PowerPoint"),
}


class _VisibleHTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript"}:
            self._hidden_depth += 1
        elif tag.lower() in {"p", "div", "br", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript"} and self._hidden_depth:
            self._hidden_depth -= 1
        elif tag.lower() in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._hidden_depth and data.strip():
            self.parts.append(data.strip())


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _safe_archive(data: bytes) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("Le fichier Office est endommagé ou n'est pas une archive valide.") from exc

    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        archive.close()
        raise ValueError("Le document contient trop d'éléments internes.")
    expanded_size = sum(item.file_size for item in entries)
    if expanded_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
        archive.close()
        raise ValueError("Le contenu décompressé du document est trop volumineux.")
    if any(item.flag_bits & 0x1 for item in entries):
        archive.close()
        raise ValueError("Les documents Office chiffrés ne sont pas pris en charge.")
    return archive


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_text(xml_data: bytes) -> list[str]:
    try:
        root = ElementTree.fromstring(xml_data)
    except ElementTree.ParseError as exc:
        raise ValueError("Le document contient un XML interne invalide.") from exc
    return [
        node.text or ""
        for node in root.iter()
        if _local_name(node.tag) == "t" and (node.text or "").strip()
    ]


def _extract_docx(data: bytes) -> str:
    with _safe_archive(data) as archive:
        try:
            xml_data = archive.read("word/document.xml")
        except KeyError as exc:
            raise ValueError("Ce fichier ZIP ne contient pas un document Word valide.") from exc
    return "\n".join(_xml_text(xml_data))


def _extract_pptx(data: bytes) -> str:
    with _safe_archive(data) as archive:
        slide_names = [
            name for name in archive.namelist()
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        ]
        slide_names.sort(key=lambda name: int(re.search(r"slide(\d+)", name).group(1)))
        if not slide_names:
            raise ValueError("Aucune diapositive PowerPoint lisible n'a été trouvée.")
        sections = []
        for index, name in enumerate(slide_names, start=1):
            sections.append(f"Diapositive {index}\n" + "\n".join(_xml_text(archive.read(name))))
    return "\n\n".join(sections)


def _extract_xlsx(data: bytes) -> str:
    with _safe_archive(data) as archive:
        names = set(archive.namelist())
        if "xl/workbook.xml" not in names:
            raise ValueError("Ce fichier ZIP ne contient pas un classeur Excel valide.")

        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in names:
            try:
                root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                for item in root:
                    shared_strings.append("".join(
                        node.text or "" for node in item.iter()
                        if _local_name(node.tag) == "t"
                    ))
            except ElementTree.ParseError as exc:
                raise ValueError("Les chaînes internes du classeur Excel sont invalides.") from exc

        sheet_names = sorted(
            name for name in names
            if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
        )
        if not sheet_names:
            raise ValueError("Aucune feuille Excel lisible n'a été trouvée.")

        sections = []
        for sheet_index, name in enumerate(sheet_names, start=1):
            try:
                root = ElementTree.fromstring(archive.read(name))
            except ElementTree.ParseError as exc:
                raise ValueError("Une feuille Excel contient un XML invalide.") from exc
            rows = []
            for row in root.iter():
                if _local_name(row.tag) != "row":
                    continue
                values = []
                for cell in row:
                    if _local_name(cell.tag) != "c":
                        continue
                    cell_ref = cell.attrib.get("r", "")
                    cell_type = cell.attrib.get("t", "")
                    value_node = next(
                        (node for node in cell.iter() if _local_name(node.tag) == "v"),
                        None,
                    )
                    inline_node = next(
                        (node for node in cell.iter() if _local_name(node.tag) == "is"),
                        None,
                    )
                    if cell_type == "inlineStr" and inline_node is not None:
                        value = "".join(
                            node.text or "" for node in inline_node.iter()
                            if _local_name(node.tag) == "t"
                        )
                    elif value_node is not None:
                        raw = value_node.text or ""
                        if cell_type == "s":
                            try:
                                value = shared_strings[int(raw)]
                            except (ValueError, IndexError):
                                value = raw
                        else:
                            value = raw
                    else:
                        value = ""
                    if value != "":
                        values.append(f"{cell_ref}={value}" if cell_ref else value)
                if values:
                    rows.append(" | ".join(values))
            if rows:
                sections.append(f"Feuille {sheet_index}\n" + "\n".join(rows))
    return "\n\n".join(sections)


def classify_attachment(filename: str, declared_mime: str | None = None) -> tuple[str, str] | None:
    extension = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    declared = (declared_mime or "").split(";", 1)[0].strip().lower()
    if extension == ".webm" and declared.startswith("audio/"):
        return "audio", "audio/webm"
    if extension in {".mp4", ".mov", ".webm", ".mpeg", ".mpg"} and declared.startswith("audio/"):
        return "audio", declared
    if extension in {".mp4", ".mov", ".webm", ".mpeg", ".mpg", ".avi", ".wmv", ".3gp"} and declared.startswith("video/"):
        return "video", declared
    if extension == ".pdf":
        return "document", "application/pdf"
    if extension in IMAGE_MIME_TYPES:
        return "image", IMAGE_MIME_TYPES[extension]
    if extension in AUDIO_MIME_TYPES:
        return "audio", AUDIO_MIME_TYPES[extension]
    if extension in VIDEO_MIME_TYPES:
        return "video", VIDEO_MIME_TYPES[extension]
    if extension in TEXT_MIME_TYPES:
        return "text", TEXT_MIME_TYPES[extension]
    if extension in OFFICE_TYPES:
        return OFFICE_TYPES[extension]
    return None


def extract_text_attachment(filename: str, data: bytes) -> tuple[str, str]:
    """Retourne (type lisible, texte) sans exécuter le contenu du fichier."""
    extension = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if extension == ".docx":
        kind, _label = OFFICE_TYPES[extension]
        extracted = _extract_docx(data)
    elif extension == ".xlsx":
        kind, _label = OFFICE_TYPES[extension]
        extracted = _extract_xlsx(data)
    elif extension == ".pptx":
        kind, _label = OFFICE_TYPES[extension]
        extracted = _extract_pptx(data)
    elif extension in TEXT_MIME_TYPES:
        kind = "text"
        extracted = _decode_text(data)
        if extension in {".html", ".htm"}:
            parser = _VisibleHTMLText()
            parser.feed(extracted)
            parser.close()
            extracted = "\n".join(parser.parts)
        elif extension == ".rtf":
            extracted = re.sub(r"\\'[0-9a-fA-F]{2}", " ", extracted)
            extracted = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", extracted)
            extracted = extracted.replace("{", " ").replace("}", " ")
    else:
        raise ValueError("Ce format ne possède pas d'extracteur de texte intégré.")
    extracted = extracted.replace("\x00", "").strip()
    if not extracted:
        raise ValueError("Aucun texte exploitable n'a été trouvé dans ce fichier.")
    if len(extracted) > MAX_EXTRACTED_CHARS_PER_FILE:
        extracted = extracted[:MAX_EXTRACTED_CHARS_PER_FILE] + "\n[Contenu tronqué pour respecter la limite de contexte.]"
    return kind, extracted


def validate_media_signature(kind: str, mime_type: str, data: bytes) -> None:
    """Vérifie les signatures utiles avant de remettre les octets au fournisseur."""
    if not data:
        raise ValueError("Le fichier est vide.")
    if kind == "image":
        valid = (
            (mime_type == "image/jpeg" and data.startswith(b"\xff\xd8\xff"))
            or (mime_type == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
            or (
                mime_type == "image/webp"
                and len(data) >= 12
                and data.startswith(b"RIFF")
                and data[8:12] == b"WEBP"
            )
            or (mime_type == "image/bmp" and data.startswith(b"BM"))
            or (
                mime_type in {"image/heic", "image/heif"}
                and len(data) >= 12
                and data[4:8] == b"ftyp"
                and data[8:12] in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}
            )
        )
        if not valid:
            raise ValueError("Le contenu réel ne correspond pas au format image annoncé.")
    elif mime_type == "application/pdf" and not data.startswith(b"%PDF-"):
        raise ValueError("Le fichier n'a pas une signature PDF valide.")
    elif kind == "video":
        is_mp4_family = (
            mime_type in {"video/mp4", "video/quicktime", "video/3gpp"}
            and len(data) >= 12
            and data[4:8] == b"ftyp"
        )
        is_webm = mime_type == "video/webm" and data.startswith(b"\x1a\x45\xdf\xa3")
        is_avi = (
            mime_type == "video/avi"
            and len(data) >= 12
            and data.startswith(b"RIFF")
            and data[8:12] == b"AVI "
        )
        is_mpeg = mime_type in {"video/mpeg", "video/mpg"} and data.startswith(b"\x00\x00\x01")
        is_wmv = (
            mime_type in {"video/wmv", "video/x-ms-wmv"}
            and data.startswith(bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c"))
        )
        is_flv = mime_type == "video/x-flv" and data.startswith(b"FLV")
        if not (is_mp4_family or is_webm or is_avi or is_mpeg or is_wmv or is_flv):
            raise ValueError("Le contenu réel ne correspond pas au format vidéo annoncé.")
