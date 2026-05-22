"""Parse a DOCX or ODT file into a Document tree.

Heading detection strategy (in priority order):
  1. (DOCX only) Paragraph style starts with "Heading " (e.g. "Heading 1") —
     use the numeric suffix as depth.
  2. Paragraph text starts with a numeric prefix like "N.M.", "N.M.K.",
     "N.M.K.L." with at least two components — depth = number of
     dot-separated components.

     Single-digit prefixes like "1.", "2.", "3." are treated as body
     paragraphs (numbered list items), NOT headings.

Tables in the body become Table blocks attached to whichever Node
is currently "open" (i.e. the deepest heading encountered so far).

ODT parsing uses zipfile + lxml directly — no external binary required.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Iterator, Union

import docx as python_docx  # the `python-docx` package
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
from lxml import etree

from .types import Block, Document, Node, Paragraph, SourceDoc, Table

# Matches a numeric prefix with at least 2 components: "N.M.", "N.M.K.", etc.
# Requires the first component to be followed by a dot and at least one more
# digit group.  Single-digit list items ("1.", "2.") do NOT match.
HEADING_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)+)\.?")

SECTION_NUMBER_RE = re.compile(r"第(\d+)節")
TONGZE_TITLE_RE = re.compile(r"通則")

# A unified block stream — both DOCX and ODT walkers feed into the same
# tree-builder. "p" carries the paragraph text (already stripped); "tbl"
# carries a fully-converted Table dataclass.
UnifiedBlock = tuple[str, Union[str, Table]]


def _iter_body_blocks(doc: DocxDocument):
    """Yield (kind, obj) for each paragraph and table in the document body.

    We pass ``doc`` (the Document object) as the parent so that
    ``Paragraph.style`` can resolve style names via ``doc.part``.
    """
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag
        if tag == qn("w:p"):
            yield "p", DocxParagraph(child, doc)
        elif tag == qn("w:tbl"):
            yield "tbl", DocxTable(child, doc)


def _detect_heading_level_from_text(text: str) -> tuple[int, ...] | None:
    """Text-only heading detection. Used by both DOCX (as fallback) and ODT paths."""
    text = (text or "").strip()
    m_prefix = HEADING_PREFIX_RE.match(text)
    if m_prefix:
        parts = m_prefix.group(1).split(".")
        return tuple(int(x) for x in parts)
    return None


def _detect_heading_level(p: DocxParagraph) -> tuple[int, ...] | None:
    """Return the numeric level tuple if this paragraph is a heading, else None.

    Strategy:
    1. If the style name starts with "Heading " use that depth, optionally
       overriding with the numeric prefix if present.
    2. If the text starts with a 2+-component numeric prefix (e.g. "9.1."),
       use the prefix depth.
    """
    style_name = (p.style.name or "") if p.style else ""
    text = (p.text or "").strip()

    m_style = re.match(r"Heading\s+(\d+)", style_name)
    if m_style:
        # Check if there is also a numeric prefix we can use for exact level
        m_prefix = HEADING_PREFIX_RE.match(text)
        if m_prefix:
            parts = m_prefix.group(1).split(".")
            return tuple(int(x) for x in parts)
        depth = int(m_style.group(1))
        return (0,) * depth

    # Fall back to numeric prefix with >= 2 components
    m_prefix = HEADING_PREFIX_RE.match(text)
    if m_prefix:
        parts = m_prefix.group(1).split(".")
        return tuple(int(x) for x in parts)

    return None


def _convert_table(tbl: DocxTable) -> Table:
    """Convert a python-docx Table to our Table dataclass."""
    rows_text: list[list[str]] = []
    for row in tbl.rows:
        rows_text.append([cell.text.strip() for cell in row.cells])
    if not rows_text:
        return Table(header=[], rows=[], caption=None)
    header = rows_text[0]
    rows = rows_text[1:]
    return Table(header=header, rows=rows, caption=None)


def _attach_block(stack: list[Node], root: Node, block: Block) -> None:
    """Attach a body block to the currently open node."""
    target = stack[-1] if stack else root
    target.body.append(block)


def _attach_heading_node(root: Node, stack: list[Node], heading: Node) -> None:
    """Pop the stack until we find a parent shallower than heading, then attach."""
    while stack and len(stack[-1].level) >= len(heading.level):
        stack.pop()
    parent = stack[-1] if stack else root
    parent.children.append(heading)
    stack.append(heading)


# --- ODT walker --------------------------------------------------------------

_ODT_NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text":   "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table":  "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
}

_ODT_TEXT_TAG_PREFIXES = (
    f"{{{_ODT_NS['text']}}}p",
    f"{{{_ODT_NS['text']}}}h",
)
_ODT_TABLE_TAG = f"{{{_ODT_NS['table']}}}table"
_ODT_ROW_TAG = f"{{{_ODT_NS['table']}}}table-row"
_ODT_CELL_TAG = f"{{{_ODT_NS['table']}}}table-cell"


def _odt_extract_text(elem: etree._Element) -> str:
    """Concatenate all text descendants of an ODT element, preserving order."""
    # lxml's `.itertext()` walks all descendant text in document order.
    # Whitespace-only / empty parts are joined as-is.
    return "".join(elem.itertext()).strip()


def _odt_convert_table(tbl_elem: etree._Element) -> Table:
    """Build a Table dataclass from an ODT <table:table> element."""
    rows_text: list[list[str]] = []
    for row in tbl_elem.iter(_ODT_ROW_TAG):
        cells: list[str] = []
        for cell in row.findall(_ODT_CELL_TAG):
            cells.append(_odt_extract_text(cell))
        if cells:
            rows_text.append(cells)
    if not rows_text:
        return Table(header=[], rows=[], caption=None)
    return Table(header=rows_text[0], rows=rows_text[1:], caption=None)


def _iter_odt_blocks(path: Path) -> Iterator[UnifiedBlock]:
    """Yield ("p", text) or ("tbl", Table) for each top-level body element of an ODT."""
    with zipfile.ZipFile(path) as z:
        with z.open("content.xml") as f:
            tree = etree.parse(f)
    text_root = tree.getroot().find(".//office:body/office:text", _ODT_NS)
    if text_root is None:
        return
    for child in text_root:
        tag = child.tag
        if tag in _ODT_TEXT_TAG_PREFIXES or tag.startswith(f"{{{_ODT_NS['text']}}}"):
            # text:p, text:h, text:list (we flatten lists into their text)
            text = _odt_extract_text(child)
            if text:
                yield "p", text
        elif tag == _ODT_TABLE_TAG:
            yield "tbl", _odt_convert_table(child)


def _iter_docx_blocks_unified(docx: DocxDocument) -> Iterator[UnifiedBlock]:
    """Adapter: convert DOCX walker output to the unified (kind, text|Table) form."""
    for kind, obj in _iter_body_blocks(docx):
        if kind == "p":
            text = (obj.text or "").strip()
            if text:
                yield "p", text
        elif kind == "tbl":
            yield "tbl", _convert_table(obj)


# --- Shared tree builder -----------------------------------------------------

def _build_document_from_blocks(blocks: Iterator[UnifiedBlock], source: SourceDoc) -> Document:
    """Common tree-building used by both DOCX and ODT paths.

    Heading detection is purely text-based here. For DOCX, style-based detection
    happens upstream (in the dedicated DOCX path) — but since NHI documents have
    no real heading styles anyway, the text-based detection is sufficient.
    """
    blocks = list(blocks)

    # Title is the first non-empty paragraph.
    title = ""
    for kind, payload in blocks:
        if kind == "p" and payload:
            title = payload  # type: ignore[assignment]
            break

    section_match = SECTION_NUMBER_RE.search(title)
    if section_match:
        section_number: int | None = int(section_match.group(1))
    elif TONGZE_TITLE_RE.search(title):
        section_number = 0  # 通則 is treated as section 0 for item_id stability
    else:
        section_number = None

    root = Node(heading=title, level=())
    stack: list[Node] = [root]
    title_consumed = False

    for kind, payload in blocks:
        if kind == "p":
            text = payload  # type: ignore[assignment]
            if not title_consumed and text == title:
                title_consumed = True
                continue
            level = _detect_heading_level_from_text(text)
            if level is not None:
                new_node = Node(heading=text, level=level)
                _attach_heading_node(root, stack, new_node)
            else:
                _attach_block(stack, root, Paragraph(text=text))
        elif kind == "tbl":
            _attach_block(stack, root, payload)  # type: ignore[arg-type]

    return Document(source=source, title=title, section_number=section_number, root=root)


# --- Public entry points -----------------------------------------------------

def parse_docx(source: SourceDoc) -> Document:
    """Parse a DOCX file into a Document tree."""
    docx = python_docx.Document(str(source.path))
    # Heading detection in the original path used DocxParagraph.style for the
    # 'Heading N' fallback. NHI files never use real heading styles, so the
    # unified text-based detector produces the same result while letting ODT
    # share the same code. The legacy `_detect_heading_level` is retained for
    # any future doc that does use styles.
    return _build_document_from_blocks(_iter_docx_blocks_unified(docx), source)


def parse_odt(source: SourceDoc) -> Document:
    """Parse an ODT file into a Document tree.

    Uses zipfile + lxml directly — no external binary needed. ODT structure:
    content.xml has <office:body><office:text> whose children are paragraphs
    (text:p / text:h), tables (table:table), and lists — all in document order.
    """
    return _build_document_from_blocks(_iter_odt_blocks(source.path), source)


def parse_document(source: SourceDoc) -> Document:
    """Dispatch to the parser matching the source file extension."""
    suffix = source.path.suffix.lower()
    if suffix == ".docx":
        return parse_docx(source)
    if suffix == ".odt":
        return parse_odt(source)
    raise ValueError(f"Unsupported document extension {suffix!r} for {source.path}")
