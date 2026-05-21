"""Chunker — turns a Document tree into a flat list of Items, each within the token budget.

This file is built in three layers:
  1. helpers (this task): has_significant_body, make_item_id, format_section_path
  2. leaf splitter (Task 7): split_leaf
  3. main descent (Task 8): chunk_document

Each layer depends only on what came before — no circular references.
"""

from __future__ import annotations

from .config import TRIVIAL_BODY_TOKEN_THRESHOLD
from .markdown import count_tokens
from .types import Node, Paragraph, Table


def has_significant_body(node: Node) -> bool:
    """Per spec §4.3: body is significant if it has a table, multiple paragraphs,
    or a single paragraph that exceeds the trivial-body token threshold.
    """
    if not node.body:
        return False
    if len(node.body) > 1:
        return True
    if any(isinstance(b, Table) for b in node.body):
        return True
    only = node.body[0]
    assert isinstance(only, Paragraph)
    return count_tokens(only.text) > TRIVIAL_BODY_TOKEN_THRESHOLD


def _level_to_str(level: tuple[int, ...]) -> str:
    return ".".join(str(n) for n in level)


def make_item_id(section_number: int | None, level: tuple[int, ...]) -> str:
    """Per spec §3.3.

    Examples:
      section_number=9, level=(9, 69, 1)  → "sec9-9.69.1"
      section_number=9, level=(9,)        → "sec9-9"
      section_number=None, level=()       → "appendix-doc"
    """
    if section_number is None:
        return "appendix-doc"
    return f"sec{section_number}-{_level_to_str(level)}"


def format_section_path(node: Node, ancestors: list[Node]) -> list[str]:
    """Full chain from document title (first ancestor) through this node's heading."""
    return [a.heading for a in ancestors] + [node.heading]
