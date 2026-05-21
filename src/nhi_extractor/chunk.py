"""Chunker — turns a Document tree into a flat list of Items, each within the token budget.

This file is built in three layers:
  1. helpers (this task): has_significant_body, make_item_id, format_section_path
  2. leaf splitter (Task 7): split_leaf
  3. main descent (Task 8): chunk_document

Each layer depends only on what came before — no circular references.
"""

from __future__ import annotations

import re

from .config import TRIVIAL_BODY_TOKEN_THRESHOLD
from .markdown import count_tokens, render_node_to_markdown, table_to_markdown
from .types import Item, Node, Paragraph, SourceDoc, Table


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


# ---------------------------------------------------------------------------
# Leaf splitting (spec §4.2)
# ---------------------------------------------------------------------------

NUMBERED_LIST_RE = re.compile(r"^(\d+)\.\s", re.MULTILINE)


def _split_paragraph_by_numbered_list(paragraph: Paragraph) -> list[str] | None:
    """If the paragraph contains 2+ "N. " items at line start, return them as chunks.
    Each chunk includes everything from one "N. " up to (but not including) the next.
    Returns None if fewer than 2 matches (nothing to split).
    """
    matches = list(NUMBERED_LIST_RE.finditer(paragraph.text))
    if len(matches) < 2:
        return None
    chunks: list[str] = []
    preamble = paragraph.text[: matches[0].start()].strip()
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(paragraph.text)
        piece = paragraph.text[m.start():end].strip()
        if preamble:
            piece = f"{preamble}\n\n{piece}"
        chunks.append(piece)
    return chunks


def _split_table_by_rows(table: Table, target_budget: int) -> list[Table]:
    """Slice a table into smaller tables, each with the same header.
    Greedy: keep adding rows until the next row would exceed target_budget.
    """
    if not table.rows:
        return [table]
    out: list[Table] = []
    current_rows: list[list[str]] = []

    for row in table.rows:
        tentative = current_rows + [row]
        size = count_tokens(table_to_markdown(Table(header=table.header, rows=tentative, caption=table.caption)))
        if size > target_budget and current_rows:
            out.append(Table(header=table.header, rows=current_rows, caption=table.caption))
            current_rows = [row]
        else:
            current_rows = tentative
    if current_rows:
        out.append(Table(header=table.header, rows=current_rows, caption=table.caption))
    return out


def _make_chunk_item(
    *,
    base_id: str,
    part_index: int,
    suffix: str,
    heading: str,
    section_path: list[str],
    content_md: str,
    source: SourceDoc,
) -> Item:
    return Item(
        item_id=f"{base_id}-{suffix}{part_index}",
        section_path=section_path,
        heading=heading,
        content_md=content_md,
        source=source,
        token_count=count_tokens(content_md),
    )


def split_leaf(
    leaf: Node,
    *,
    ancestors: list[Node],
    section_number: int | None,
    source: SourceDoc | None = None,
    target_budget: int = None,
) -> list[Item]:
    """Split an over-budget leaf into multiple Items following spec §4.2 priority."""
    from .config import TARGET_BUDGET
    target_budget = target_budget if target_budget is not None else TARGET_BUDGET

    if source is None:
        from datetime import date
        from pathlib import Path
        source = SourceDoc(
            path=Path("test.docx"), url="", display_name="test",
            update_date_iso=date(1970, 1, 1),
        )

    base_id = make_item_id(section_number, leaf.level)
    section_path = format_section_path(leaf, ancestors)
    heading_prefix = f"## {leaf.heading}\n\n"

    # Strategy 1: numbered-list split (one big paragraph with a list)
    if len(leaf.body) == 1 and isinstance(leaf.body[0], Paragraph):
        pieces = _split_paragraph_by_numbered_list(leaf.body[0])
        if pieces:
            items: list[Item] = []
            for i, piece in enumerate(pieces, start=1):
                content = f"{heading_prefix}{piece}"
                items.append(_make_chunk_item(
                    base_id=base_id, part_index=i, suffix="part",
                    heading=leaf.heading, section_path=section_path,
                    content_md=content, source=source,
                ))
            return items

    # Strategy 2: leaf is one giant table → split by rows
    if len(leaf.body) == 1 and isinstance(leaf.body[0], Table):
        slices = _split_table_by_rows(leaf.body[0], target_budget=target_budget)
        items = []
        for i, t in enumerate(slices, start=1):
            content = f"{heading_prefix}{table_to_markdown(t)}"
            items.append(_make_chunk_item(
                base_id=base_id, part_index=i, suffix="tbl",
                heading=leaf.heading, section_path=section_path,
                content_md=content, source=source,
            ))
        return items

    # Strategy 3: paragraph-by-paragraph accumulation
    from .config import HARD_BUDGET
    items = []
    current_parts: list[str] = []
    current_size = count_tokens(heading_prefix)
    part_idx = 1

    def flush():
        nonlocal current_parts, current_size, part_idx
        if not current_parts:
            return
        content = heading_prefix + "\n\n".join(current_parts)
        items.append(_make_chunk_item(
            base_id=base_id, part_index=part_idx, suffix="part",
            heading=leaf.heading, section_path=section_path,
            content_md=content, source=source,
        ))
        current_parts = []
        current_size = count_tokens(heading_prefix)
        part_idx += 1

    def _char_split_oversized(rendered: str) -> None:
        """Last-resort: split a single block that exceeds HARD_BUDGET by character boundaries.

        Uses an adaptive approach: estimate a conservative chars-per-token ratio, then
        trim each slice so the final content (including heading_prefix) stays within HARD_BUDGET.
        """
        nonlocal part_idx
        heading_tokens = count_tokens(heading_prefix)
        content_budget = HARD_BUDGET - heading_tokens
        block_tokens = count_tokens(rendered)
        char_len = len(rendered)
        # Conservative estimate: assume slightly more tokens per char than observed.
        tokens_per_char = block_tokens / max(1, char_len)
        # Start with estimated max chars; we'll trim if actual count exceeds budget.
        estimated_max_chars = int(content_budget / max(tokens_per_char, 0.001))
        start = 0
        while start < char_len:
            end = min(start + estimated_max_chars, char_len)
            # Trim end backward until the slice fits within content_budget.
            while end > start:
                piece = rendered[start:end]
                if count_tokens(piece) <= content_budget:
                    break
                # Reduce by ~10% and retry.
                end = max(start + 1, end - max(1, (end - start) // 10))
            piece = rendered[start:end]
            content = f"{heading_prefix}{piece}"
            items.append(_make_chunk_item(
                base_id=base_id, part_index=part_idx, suffix="part",
                heading=leaf.heading, section_path=section_path,
                content_md=content, source=source,
            ))
            part_idx += 1
            start = end

    for block in leaf.body:
        if isinstance(block, Paragraph):
            rendered = block.text
        else:
            rendered = table_to_markdown(block)
        block_size = count_tokens(rendered)
        if current_size + block_size > target_budget and current_parts:
            flush()
        if block_size > HARD_BUDGET:
            # Single block exceeds HARD_BUDGET — flush pending, then character-split this block.
            flush()
            _char_split_oversized(rendered)
        else:
            current_parts.append(rendered)
            current_size += block_size
    flush()

    return items


# ---------------------------------------------------------------------------
# Main recursive descent (spec §4.1)
# ---------------------------------------------------------------------------

def _emit_full_subtree(
    node: Node,
    ancestors: list[Node],
    section_number: int | None,
    source: SourceDoc,
) -> Item:
    """Emit a Node + its entire subtree as one Item."""
    content_md = render_node_to_markdown(node)
    return Item(
        item_id=make_item_id(section_number, node.level),
        section_path=format_section_path(node, ancestors),
        heading=node.heading,
        content_md=content_md,
        source=source,
        token_count=count_tokens(content_md),
    )


def _emit_body_only(
    node: Node,
    ancestors: list[Node],
    section_number: int | None,
    source: SourceDoc,
) -> Item:
    """Emit just this node's body (preamble before children) as a -preamble Item."""
    parts: list[str] = [f"## {node.heading}"]
    for block in node.body:
        if isinstance(block, Paragraph):
            parts.append(block.text)
        else:
            parts.append(table_to_markdown(block))
    content_md = "\n\n".join(parts)
    base_id = make_item_id(section_number, node.level)
    return Item(
        item_id=f"{base_id}-preamble",
        section_path=format_section_path(node, ancestors),
        heading=node.heading,
        content_md=content_md,
        source=source,
        token_count=count_tokens(content_md),
    )


def _chunk_node(
    node: Node,
    ancestors: list[Node],
    section_number: int | None,
    source: SourceDoc,
    target_budget: int,
) -> list[Item]:
    # Pure-heading nodes (no body, has children) always descend — never emit as a single item.
    if node.children and not node.body:
        out: list[Item] = []
        new_ancestors = ancestors + [node]
        for child in node.children:
            out.extend(_chunk_node(child, new_ancestors, section_number, source, target_budget))
        return out

    rendered = render_node_to_markdown(node)
    if count_tokens(rendered) <= target_budget:
        return [_emit_full_subtree(node, ancestors, section_number, source)]

    if node.children:
        out = []
        if has_significant_body(node):
            out.append(_emit_body_only(node, ancestors, section_number, source))
        new_ancestors = ancestors + [node]
        for child in node.children:
            out.extend(_chunk_node(child, new_ancestors, section_number, source, target_budget))
        return out

    # Leaf, over budget → semantic split.
    return split_leaf(
        node,
        ancestors=ancestors,
        section_number=section_number,
        source=source,
        target_budget=target_budget,
    )


def chunk_document(doc) -> list[Item]:
    """Public entry point: Document → list[Item], all within HARD_BUDGET."""
    from .config import HARD_BUDGET, TARGET_BUDGET
    items: list[Item] = []
    for child in doc.root.children:
        items.extend(_chunk_node(
            child,
            ancestors=[doc.root],
            section_number=doc.section_number,
            source=doc.source,
            target_budget=TARGET_BUDGET,
        ))

    over = [i for i in items if i.token_count > HARD_BUDGET]
    if over:
        ids = ", ".join(f"{i.item_id}({i.token_count})" for i in over)
        raise ValueError(
            f"Budget contract violated — {len(over)} items exceed HARD_BUDGET={HARD_BUDGET}: {ids}"
        )

    return items
