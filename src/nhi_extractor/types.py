"""Core dataclass types shared across all pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Union


@dataclass(frozen=True)
class SourceDoc:
    """One downloaded NHI document plus its metadata."""
    path: Path
    url: str
    display_name: str
    update_date_iso: date


@dataclass(frozen=True)
class SkippedDoc:
    """A document the fetcher saw on the listing but deliberately did not download.

    `reason` is a short machine-readable tag, e.g. "appendix_form", "unrecognized_title",
    "pdf_only". `url` is the best-available source URL so a human can still grab it.
    """
    title: str
    url: str
    reason: str


@dataclass(frozen=True)
class Manifest:
    """The full set of source documents for one release."""
    update_date_iso: date
    documents: tuple[SourceDoc, ...]
    skipped_documents: tuple[SkippedDoc, ...] = ()


@dataclass
class Paragraph:
    """A prose paragraph."""
    text: str


@dataclass
class Table:
    """An embedded table inside a regulation."""
    header: list[str]
    rows: list[list[str]]
    caption: str | None = None


# A Block is either a paragraph or a table.
Block = Union[Paragraph, Table]


@dataclass
class Node:
    """A node in the regulation heading tree.

    `body` holds prose/tables that appear *under this heading but before
    the first child heading*. `children` are the nested sub-headings.
    """
    heading: str
    level: tuple[int, ...]
    body: list[Block] = field(default_factory=list)
    children: list[Node] = field(default_factory=list)


@dataclass
class Document:
    """A parsed source document."""
    source: SourceDoc
    title: str
    section_number: int | None
    root: Node


@dataclass(frozen=True)
class Item:
    """One emitted knowledge item — sized to fit the token budget."""
    item_id: str
    section_path: list[str]
    heading: str
    content_md: str
    source: SourceDoc
    token_count: int
