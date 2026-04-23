# WikiForge — File Parsers

## Design

Each file format has a dedicated parser that extracts structured content into a normalized format. Parsers are registered by file extension and selected automatically.

## Parser Interface

```python
# wikiforge/parsers/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ParsedSection:
    """A section of content extracted from a document."""
    heading: str = ""
    level: int = 1          # Heading level (1-6)
    content: str = ""       # Plain text content
    children: list["ParsedSection"] = field(default_factory=list)


@dataclass
class ParsedTable:
    """A table extracted from a document."""
    caption: str = ""
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class ParsedContent:
    """Normalized output from any file parser."""
    title: str = ""
    full_text: str = ""                         # All text concatenated
    sections: list[ParsedSection] = field(default_factory=list)
    tables: list[ParsedTable] = field(default_factory=list)
    metadata: dict = field(default_factory=dict) # Author, dates, page count, etc.
    word_count: int = 0
    section_count: int = 0
    warnings: list[str] = field(default_factory=list)  # Non-fatal issues


class BaseParser(ABC):
    """Abstract base class for file format parsers."""

    supported_extensions: list[str]  # e.g., ['.md', '.markdown']

    @abstractmethod
    def parse(self, filepath: str) -> ParsedContent:
        """Parse a file and return normalized content."""
        ...

    @abstractmethod
    def can_parse(self, filepath: str) -> bool:
        """Check if this parser can handle the file."""
        ...
```

## Parser Registry

```python
# wikiforge/parsers/registry.py

from pathlib import Path
from .base import BaseParser, ParsedContent

class ParserRegistry:
    """Maps file extensions to parsers."""

    _parsers: dict[str, BaseParser] = {}

    @classmethod
    def register(cls, parser: BaseParser):
        for ext in parser.supported_extensions:
            cls._parsers[ext.lower()] = parser

    @classmethod
    def get_parser(cls, filepath: str) -> BaseParser | None:
        ext = Path(filepath).suffix.lower()
        return cls._parsers.get(ext)

    @classmethod
    def parse_file(cls, filepath: str) -> ParsedContent:
        parser = cls.get_parser(filepath)
        if not parser:
            raise ValueError(f"No parser for extension: {Path(filepath).suffix}")
        return parser.parse(filepath)

    @classmethod
    def supported_extensions(cls) -> list[str]:
        return list(cls._parsers.keys())
```

## Markdown Parser

```python
# wikiforge/parsers/markdown.py

import re
from pathlib import Path
from .base import BaseParser, ParsedContent, ParsedSection, ParsedTable


class MarkdownParser(BaseParser):
    supported_extensions = [".md", ".markdown", ".mdown"]

    def can_parse(self, filepath: str) -> bool:
        return Path(filepath).suffix.lower() in self.supported_extensions

    def parse(self, filepath: str) -> ParsedContent:
        text = Path(filepath).read_text(encoding="utf-8", errors="replace")

        # Strip YAML frontmatter if present
        frontmatter = {}
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                frontmatter = self._parse_yaml_frontmatter(parts[1])
                text = parts[2].strip()

        sections = self._extract_sections(text)
        tables = self._extract_tables(text)
        title = self._extract_title(text, filepath)

        return ParsedContent(
            title=title,
            full_text=text,
            sections=sections,
            tables=tables,
            metadata=frontmatter,
            word_count=len(text.split()),
            section_count=len(sections),
        )

    def _extract_title(self, text: str, filepath: str) -> str:
        match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return Path(filepath).stem.replace("-", " ").replace("_", " ").title()

    def _extract_sections(self, text: str) -> list[ParsedSection]:
        sections = []
        current = None
        lines = text.split("\n")

        for line in lines:
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if heading_match:
                level = len(heading_match.group(1))
                if current:
                    sections.append(current)
                current = ParsedSection(
                    heading=heading_match.group(2).strip(),
                    level=level,
                    content="",
                )
            elif current:
                current.content += line + "\n"

        if current:
            sections.append(current)
        return sections

    def _extract_tables(self, text: str) -> list[ParsedTable]:
        tables = []
        table_pattern = re.compile(
            r"(\|.+\|)\n(\|[-:\s|]+\|)\n((?:\|.+\|\n?)+)", re.MULTILINE
        )
        for match in table_pattern.finditer(text):
            headers = [h.strip() for h in match.group(1).strip("|").split("|")]
            rows = []
            for row_line in match.group(3).strip().split("\n"):
                cells = [c.strip() for c in row_line.strip("|").split("|")]
                rows.append(cells)
            tables.append(ParsedTable(headers=headers, rows=rows))
        return tables

    def _parse_yaml_frontmatter(self, yaml_str: str) -> dict:
        # Simple key: value parser (avoids pyyaml dependency for basic cases)
        result = {}
        for line in yaml_str.strip().split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                result[key.strip()] = value.strip().strip('"').strip("'")
        return result
```

## DOCX Parser

```python
# wikiforge/parsers/docx.py

from pathlib import Path
from .base import BaseParser, ParsedContent, ParsedSection, ParsedTable


class DocxParser(BaseParser):
    supported_extensions = [".docx"]

    def can_parse(self, filepath: str) -> bool:
        return Path(filepath).suffix.lower() == ".docx"

    def parse(self, filepath: str) -> ParsedContent:
        from docx import Document as DocxDocument
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        doc = DocxDocument(filepath)
        sections = []
        tables = []
        full_text_parts = []
        current_section = None
        metadata = self._extract_metadata(doc)

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            full_text_parts.append(text)

            # Detect headings
            if para.style and para.style.name.startswith("Heading"):
                level = int(para.style.name.replace("Heading ", "").replace("Heading", "1"))
                if current_section:
                    sections.append(current_section)
                current_section = ParsedSection(heading=text, level=level, content="")
            elif current_section:
                current_section.content += text + "\n"
            else:
                # Content before first heading
                if not sections:
                    current_section = ParsedSection(heading="", level=0, content=text + "\n")

        if current_section:
            sections.append(current_section)

        # Extract tables
        for tbl in doc.tables:
            parsed = self._parse_table(tbl)
            if parsed:
                tables.append(parsed)

        full_text = "\n".join(full_text_parts)
        title = sections[0].heading if sections and sections[0].heading else Path(filepath).stem

        return ParsedContent(
            title=title,
            full_text=full_text,
            sections=sections,
            tables=tables,
            metadata=metadata,
            word_count=len(full_text.split()),
            section_count=len(sections),
        )

    def _parse_table(self, table) -> ParsedTable | None:
        try:
            rows = []
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                rows.append(cells)
            if len(rows) < 2:
                return None
            return ParsedTable(
                headers=rows[0],
                rows=rows[1:],
            )
        except Exception:
            return None

    def _extract_metadata(self, doc) -> dict:
        props = doc.core_properties
        return {
            k: str(v) for k, v in {
                "author": props.author,
                "title": props.title,
                "created": props.created,
                "modified": props.modified,
                "subject": props.subject,
            }.items() if v
        }
```

## Legacy DOC Parser

```python
# wikiforge/parsers/doc.py

import subprocess
import tempfile
from pathlib import Path
from .base import BaseParser, ParsedContent
from .docx import DocxParser


class DocParser(BaseParser):
    """Handles legacy .doc files by converting to .docx first via LibreOffice."""

    supported_extensions = [".doc"]

    def can_parse(self, filepath: str) -> bool:
        return Path(filepath).suffix.lower() == ".doc"

    def parse(self, filepath: str) -> ParsedContent:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Convert .doc → .docx using LibreOffice
            result = subprocess.run(
                ["libreoffice", "--headless", "--convert-to", "docx", filepath, "--outdir", tmpdir],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                raise RuntimeError(f"LibreOffice conversion failed: {result.stderr}")

            docx_path = Path(tmpdir) / (Path(filepath).stem + ".docx")
            if not docx_path.exists():
                raise FileNotFoundError(f"Converted file not found: {docx_path}")

            # Parse the converted .docx
            parser = DocxParser()
            content = parser.parse(str(docx_path))
            content.warnings.append("Converted from legacy .doc format — some formatting may be lost")
            return content
```

## XLSX Parser

```python
# wikiforge/parsers/xlsx.py

from pathlib import Path
from .base import BaseParser, ParsedContent, ParsedSection, ParsedTable


class XlsxParser(BaseParser):
    supported_extensions = [".xlsx", ".xls"]

    def can_parse(self, filepath: str) -> bool:
        return Path(filepath).suffix.lower() in self.supported_extensions

    def parse(self, filepath: str) -> ParsedContent:
        from openpyxl import load_workbook

        wb = load_workbook(filepath, read_only=True, data_only=True)
        sections = []
        tables = []
        full_text_parts = []

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                continue

            # Treat each sheet as a section
            section_content_parts = []

            # First row as headers (if it looks like a header row)
            headers = [str(c) if c is not None else "" for c in rows[0]]
            data_rows = []

            for row in rows[1:]:
                cells = [str(c) if c is not None else "" for c in row]
                if any(cells):  # Skip empty rows
                    data_rows.append(cells)
                    section_content_parts.append(" | ".join(cells))

            if headers and data_rows:
                tables.append(ParsedTable(
                    caption=f"Sheet: {sheet_name}",
                    headers=headers,
                    rows=data_rows,
                ))

            section_text = "\n".join(section_content_parts)
            sections.append(ParsedSection(
                heading=sheet_name,
                level=1,
                content=section_text,
            ))
            full_text_parts.append(f"## {sheet_name}\n{section_text}")

        wb.close()
        full_text = "\n\n".join(full_text_parts)

        return ParsedContent(
            title=Path(filepath).stem,
            full_text=full_text,
            sections=sections,
            tables=tables,
            metadata={"sheet_count": len(wb.sheetnames)},
            word_count=len(full_text.split()),
            section_count=len(sections),
        )
```

## CSV Parser

```python
# wikiforge/parsers/csv_parser.py

import csv
from pathlib import Path
from .base import BaseParser, ParsedContent, ParsedSection, ParsedTable


class CsvParser(BaseParser):
    supported_extensions = [".csv", ".tsv"]

    def can_parse(self, filepath: str) -> bool:
        return Path(filepath).suffix.lower() in self.supported_extensions

    def parse(self, filepath: str) -> ParsedContent:
        ext = Path(filepath).suffix.lower()
        delimiter = "\t" if ext == ".tsv" else ","

        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f, delimiter=delimiter)
            rows = list(reader)

        if not rows:
            return ParsedContent(title=Path(filepath).stem, warnings=["Empty CSV file"])

        headers = rows[0]
        data_rows = rows[1:]

        full_text = "\n".join([delimiter.join(row) for row in rows])

        return ParsedContent(
            title=Path(filepath).stem,
            full_text=full_text,
            sections=[ParsedSection(heading=Path(filepath).stem, level=1, content=full_text)],
            tables=[ParsedTable(headers=headers, rows=data_rows)],
            metadata={"row_count": len(data_rows), "column_count": len(headers)},
            word_count=len(full_text.split()),
            section_count=1,
        )
```

## PDF Parser

```python
# wikiforge/parsers/pdf.py

from pathlib import Path
from .base import BaseParser, ParsedContent, ParsedSection, ParsedTable


class PdfParser(BaseParser):
    supported_extensions = [".pdf"]

    def can_parse(self, filepath: str) -> bool:
        return Path(filepath).suffix.lower() == ".pdf"

    def parse(self, filepath: str) -> ParsedContent:
        import fitz  # PyMuPDF

        doc = fitz.open(filepath)
        sections = []
        full_text_parts = []
        tables = []
        warnings = []

        metadata = {
            "page_count": len(doc),
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "created": doc.metadata.get("creationDate", ""),
        }

        for page_num, page in enumerate(doc, 1):
            text = page.get_text("text")
            if not text.strip():
                warnings.append(f"Page {page_num}: no text extracted (may be scanned/image)")
                continue

            full_text_parts.append(text)

            # Basic section detection from font sizes
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if block.get("type") == 0:  # Text block
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            # Heuristic: larger font = heading
                            if span.get("size", 12) > 14:
                                sections.append(ParsedSection(
                                    heading=span["text"].strip(),
                                    level=1 if span["size"] > 18 else 2,
                                    content="",
                                ))

            # Attempt table extraction
            try:
                page_tables = page.find_tables()
                for tbl in page_tables:
                    extracted = tbl.extract()
                    if extracted and len(extracted) >= 2:
                        headers = [str(c) if c else "" for c in extracted[0]]
                        rows = [[str(c) if c else "" for c in row] for row in extracted[1:]]
                        tables.append(ParsedTable(
                            caption=f"Table from page {page_num}",
                            headers=headers,
                            rows=rows,
                        ))
            except Exception:
                warnings.append(f"Page {page_num}: table extraction failed")

        doc.close()
        full_text = "\n\n".join(full_text_parts)
        title = metadata.get("title") or Path(filepath).stem

        return ParsedContent(
            title=title,
            full_text=full_text,
            sections=sections if sections else [ParsedSection(heading=title, level=1, content=full_text)],
            tables=tables,
            metadata=metadata,
            word_count=len(full_text.split()),
            section_count=max(len(sections), 1),
            warnings=warnings,
        )
```

## Registration

All parsers must be registered at application startup:

```python
# wikiforge/parsers/__init__.py

from .registry import ParserRegistry
from .markdown import MarkdownParser
from .docx import DocxParser
from .doc import DocParser
from .xlsx import XlsxParser
from .csv_parser import CsvParser
from .pdf import PdfParser


def register_all_parsers():
    ParserRegistry.register(MarkdownParser())
    ParserRegistry.register(DocxParser())
    ParserRegistry.register(DocParser())
    ParserRegistry.register(XlsxParser())
    ParserRegistry.register(CsvParser())
    ParserRegistry.register(PdfParser())
```

## Dependencies

```
python-docx>=1.1.0       # .docx parsing
openpyxl>=3.1.0           # .xlsx parsing
PyMuPDF>=1.24.0           # PDF parsing (imported as fitz)
# LibreOffice must be installed for .doc → .docx conversion
```
