"""Parse a DOCX file into a Document tree.

Heading detection strategy (in priority order):
  1. Paragraph style starts with "Heading " (e.g. "Heading 1") — use the
     numeric suffix as depth.
  2. Paragraph text starts with a numeric prefix like "N.M.", "N.M.K.",
     "N.M.K.L." with at least two components — depth = number of
     dot-separated components.

     Single-digit prefixes like "1.", "2.", "3." are treated as body
     paragraphs (numbered list items), NOT headings.

Tables in the DOCX body become Table blocks attached to whichever Node
is currently "open" (i.e. the deepest heading encountered so far).
"""

from __future__ import annotations

import re
from pathlib import Path

import docx as python_docx  # the `python-docx` package
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph

from .types import Block, Document, Node, Paragraph, SourceDoc, Table

# Matches a numeric prefix with at least 2 components: "N.M.", "N.M.K.", etc.
# Requires the first component to be followed by a dot and at least one more
# digit group.  Single-digit list items ("1.", "2.") do NOT match.
HEADING_PREFIX_RE = re.compile(r"^(\d+(?:\.\d+)+)\.?")

SECTION_NUMBER_RE = re.compile(r"第(\d+)節")


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


def parse_docx(source: SourceDoc) -> Document:
    """Parse a DOCX file into a Document tree.

    Args:
        source: metadata + path of the DOCX to parse.

    Returns:
        A Document with a heading tree rooted at ``root``.
    """
    docx = python_docx.Document(str(source.path))

    # Determine document title from the first non-empty paragraph.
    title = ""
    for kind, obj in _iter_body_blocks(docx):
        if kind == "p" and obj.text.strip():
            title = obj.text.strip()
            break

    section_match = SECTION_NUMBER_RE.search(title)
    section_number = int(section_match.group(1)) if section_match else None

    root = Node(heading=title, level=())
    # stack tracks the currently-open node at each depth level.
    # We start with root on the stack so orphan paragraphs before any heading
    # land on root.body.
    stack: list[Node] = [root]
    title_consumed = False

    for kind, obj in _iter_body_blocks(docx):
        if kind == "p":
            text = obj.text.strip()
            if not text:
                continue
            # Skip the title paragraph (already used for doc.title).
            if not title_consumed and text == title:
                title_consumed = True
                continue

            level = _detect_heading_level(obj)
            if level is not None:
                new_node = Node(heading=text, level=level)
                _attach_heading_node(root, stack, new_node)
            else:
                _attach_block(stack, root, Paragraph(text=text))

        elif kind == "tbl":
            _attach_block(stack, root, _convert_table(obj))

    return Document(
        source=source,
        title=title,
        section_number=section_number,
        root=root,
    )
