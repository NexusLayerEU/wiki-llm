"""PDF via PyMuPDF."""
from pathlib import Path

from .base import BaseParser, ParsedDocument, ParsedSection, ParserError


class PdfParser(BaseParser):
    supported_extensions = [".pdf"]

    def parse(self, filepath: str) -> ParsedDocument:
        try:
            import fitz  # PyMuPDF
        except ImportError as cause:  # pragma: no cover
            raise ParserError("PyMuPDF is not installed") from cause

        path = Path(filepath)
        try:
            source = fitz.open(str(path))
        except Exception as cause:
            raise ParserError(f"Could not open {path.name}: {cause}") from cause

        document = ParsedDocument(title=path.stem)
        page_texts: list[str] = []

        try:
            for number, page in enumerate(source, start=1):
                text = (page.get_text() or "").strip()
                if not text:
                    continue
                page_texts.append(text)
                document.sections.append(
                    ParsedSection(heading=f"Page {number}", level=1, content=text)
                )

            info = source.metadata or {}
            document.metadata = {
                "author": info.get("author", "") or "",
                "title": info.get("title", "") or "",
                "created": info.get("creationDate", "") or "",
                "page_count": source.page_count,
            }
            if info.get("title"):
                document.title = info["title"]
        finally:
            source.close()

        document.full_text = "\n\n".join(page_texts)
        if not document.full_text.strip():
            document.warnings.append(
                "No selectable text — the PDF is probably scanned images and needs OCR."
            )
        return document.finalise()
