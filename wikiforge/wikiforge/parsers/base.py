"""Normalised parser output, shared by every format."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedSection:
    heading: str = ""
    level: int = 1
    content: str = ""
    children: list["ParsedSection"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "heading": self.heading,
            "level": self.level,
            "content": self.content,
            "children": [child.to_dict() for child in self.children],
        }


@dataclass
class ParsedTable:
    caption: str = ""
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"caption": self.caption, "headers": self.headers, "rows": self.rows}

    def to_markdown(self) -> str:
        """Tables reach the model as Markdown; prose-only extraction loses the grid."""
        if not self.headers and not self.rows:
            return ""
        headers = self.headers or [f"col{i + 1}" for i in range(len(self.rows[0]))]
        lines = [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for row in self.rows:
            padded = list(row) + [""] * (len(headers) - len(row))
            lines.append("| " + " | ".join(str(cell) for cell in padded[: len(headers)]) + " |")
        caption = f"**{self.caption}**\n\n" if self.caption else ""
        return caption + "\n".join(lines)


@dataclass
class ParsedDocument:
    title: str = ""
    full_text: str = ""
    sections: list[ParsedSection] = field(default_factory=list)
    tables: list[ParsedTable] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    word_count: int = 0
    section_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def finalise(self) -> "ParsedDocument":
        """Fill in the counts, so no parser has to remember to."""
        self.word_count = len(self.full_text.split())
        self.section_count = len(self.sections)
        return self

    def to_dict(self) -> dict:
        return {
            "type": "document",
            "title": self.title,
            "sections": [section.to_dict() for section in self.sections],
            "tables": [table.to_dict() for table in self.tables],
            "metadata": self.metadata,
        }


class ParserError(RuntimeError):
    pass


class BaseParser(ABC):
    supported_extensions: list[str] = []

    @abstractmethod
    def parse(self, filepath: str) -> ParsedDocument: ...

    def can_parse(self, filepath: str) -> bool:
        return Path(filepath).suffix.lower() in self.supported_extensions
