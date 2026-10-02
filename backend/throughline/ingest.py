"""Turning an uploaded syllabus file into text."""

from __future__ import annotations

import html
import io
import mimetypes
import re
import zipfile

from .llm import Engine, EngineUnavailable

TEXT_EXTS = (".txt", ".md", ".markdown", ".html", ".htm")
IMAGE_MIMES = ("image/png", "image/jpeg", "image/webp", "image/heic")


class UnsupportedFile(ValueError):
    pass


def guess_mime(filename: str, declared: str | None) -> str:
    if declared and declared not in ("application/octet-stream", ""):
        return declared
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    xml = re.sub(r"<w:br/>", "\n", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text(extraction_mode="layout") or "")  # keeps schedule table columns apart
        except Exception:
            pages.append(page.extract_text() or "")
    return "\n".join(pages)


def _html_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", "", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", raw)
    raw = re.sub(r"(?i)</t[dh]>", "\t", raw)
    return html.unescape(re.sub(r"<[^>]+>", "", raw))


def syllabus_text(engine: Engine, data: bytes, filename: str, mime: str) -> str:
    """Extract text locally when possible; fall back to Gemini for scans and images."""
    name = (filename or "").lower()
    if name.endswith(".doc") and not name.endswith(".docx"):
        raise UnsupportedFile("Old .doc files can't be read. Open it in Word or Google Docs and save as PDF or .docx.")
    if name.endswith(".docx"):
        return _docx_text(data)
    if name.endswith(TEXT_EXTS) or mime.startswith("text/"):
        raw = data.decode("utf-8", errors="replace")
        return _html_text(raw) if name.endswith((".html", ".htm")) or "<html" in raw[:500].lower() else raw
    if name.endswith(".pdf") or mime == "application/pdf":
        text = _pdf_text(data)
        if len(text.strip()) >= 300:
            return text
        mime = "application/pdf"  # likely a scan: let Gemini read it
    elif not mime.startswith(IMAGE_MIMES):
        raise UnsupportedFile("Upload the syllabus as PDF, .docx, text, or a photo.")
    try:
        return engine.read_document(data, mime, filename)
    except EngineUnavailable as exc:
        raise UnsupportedFile(str(exc)) from exc
