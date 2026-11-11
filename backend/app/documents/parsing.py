"""Extract plain text from an uploaded CV or job description (PDF, DOCX, TXT, MD)."""

import io
import re
import zipfile

from docx import Document as DocxDocument
from pypdf import PdfReader
from pypdf.errors import PdfReadError

# Vercel rejects request bodies over 4.5 MB, so uploads are capped just below that.
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
SUPPORTED = ".pdf, .docx, .txt or .md"


class ParseError(ValueError):
    """The file can't be used. The message is safe to show to the user."""


def extract_text(filename: str, data: bytes) -> str:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ParseError("The file is larger than 4 MB. Save it as a smaller PDF or a .docx.")
    if not data:
        raise ParseError("The file is empty.")
    name = filename.lower()
    if name.endswith(".pdf") or data.startswith(b"%PDF"):
        text = _pdf(data)
    elif name.endswith(".docx"):
        text = _docx(data)
    elif name.endswith((".txt", ".md")):
        text = data.decode("utf-8", errors="replace")
    elif name.endswith(".doc"):
        raise ParseError("Old .doc files aren't supported. Save it as .docx or PDF and try again.")
    else:
        raise ParseError(f"Unsupported file type. Upload a {SUPPORTED} file.")
    text = clean_text(text)
    if len(text.split()) < 20:
        raise ParseError(
            "Couldn't find enough text in this file. If it's a scanned PDF, upload a version "
            "with selectable text (or a .docx)."
        )
    return text


def _pdf(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ParseError("This PDF is password-protected. Remove the password and try again.")
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except (PdfReadError, ValueError, KeyError) as exc:
        if isinstance(exc, ParseError):
            raise
        raise ParseError("This PDF couldn't be read. Try exporting it again.") from exc


def _docx(data: bytes) -> str:
    try:
        doc = DocxDocument(io.BytesIO(data))
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise ParseError("This .docx file couldn't be read.") from exc
    lines: list[str] = []
    for block in doc.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = "".join(t.text or "" for t in block.iter() if t.tag.endswith("}t"))
            style = block.find(".//{*}pStyle")
            is_list = block.find(".//{*}numPr") is not None or (
                style is not None and "List" in (style.get(_W_VAL) or "")
            )
            lines.append(f"- {text}" if is_list and text.strip() else text)
        elif tag == "tbl":
            for row in block.iter():
                if row.tag.endswith("}tr"):
                    cells = [
                        "".join(t.text or "" for t in cell.iter() if t.tag.endswith("}t"))
                        for cell in row
                        if cell.tag.endswith("}tc")
                    ]
                    lines.append(" | ".join(c for c in cells if c.strip()))
    return "\n".join(lines)


_W_VAL = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val"

_BULLETS = re.compile(r"^\s*[•●▪◦‣∙·\-\*–]\s*")


def clean_text(text: str) -> str:
    """Normalise whitespace and bullets; keep one item per line."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl")
    out: list[str] = []
    for raw in text.split("\n"):
        line = " ".join(raw.split())
        if not line:
            if out and out[-1] != "":
                out.append("")
            continue
        if _BULLETS.match(line):
            line = "- " + _BULLETS.sub("", line)
        out.append(line)
    return "\n".join(out).strip()
