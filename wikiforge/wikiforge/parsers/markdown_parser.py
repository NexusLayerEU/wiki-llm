"""Markdown and plain text."""
import re
from pathlib import Path

from .base import BaseParser, ParsedDocument, ParsedSection

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


class MarkdownParser(BaseParser):
    supported_extensions = [".md", ".markdown", ".txt"]

    def parse(self, filepath: str) -> ParsedDocument:
        path = Path(filepath)
        raw = path.read_text(encoding="utf-8", errors="replace")

        document = ParsedDocument(full_text=raw, metadata={"source_format": path.suffix})

        sections: list[ParsedSection] = []
        current: ParsedSection | None = None
        body: list[str] = []

        for line in raw.splitlines():
            match = _HEADING.match(line)
            if match:
                if current is not None:
                    current.content = "\n".join(body).strip()
                    sections.append(current)
                current = ParsedSection(heading=match.group(2).strip(), level=len(match.group(1)))
                body = []
            else:
                body.append(line)

        if current is not None:
            current.content = "\n".join(body).strip()
            sections.append(current)
        elif body:
            # A file with no headings is still one section, not zero.
            sections.append(ParsedSection(heading=path.stem, level=1, content=raw.strip()))

        document.sections = sections
        document.title = sections[0].heading if sections else path.stem
        return document.finalise()
