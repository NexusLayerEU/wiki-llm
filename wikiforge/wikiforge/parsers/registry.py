"""Extension → parser."""
from pathlib import Path

from .base import BaseParser, ParsedDocument
from .docx_parser import DocxParser, LegacyDocParser
from .markdown_parser import MarkdownParser
from .pdf_parser import PdfParser
from .spreadsheet_parser import CsvParser, XlsxParser

_PARSERS: list[BaseParser] = [
    MarkdownParser(), DocxParser(), LegacyDocParser(),
    XlsxParser(), CsvParser(), PdfParser(),
]

_BY_EXTENSION: dict[str, BaseParser] = {
    extension: parser for parser in _PARSERS for extension in parser.supported_extensions
}

#: What the upload endpoint advertises and the watcher picks up. `.doc` is listed
#: because a clear "convert this" beats silently ignoring the file.
SUPPORTED_EXTENSIONS = tuple(sorted(_BY_EXTENSION))


def get_parser(filepath: str) -> BaseParser | None:
    return _BY_EXTENSION.get(Path(filepath).suffix.lower())


def parse_file(filepath: str) -> ParsedDocument:
    parser = get_parser(filepath)
    if parser is None:
        raise ValueError(f"No parser for {Path(filepath).suffix or 'a file with no extension'}")
    return parser.parse(filepath)
