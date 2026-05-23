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
      section_number=0, level=()          → "sec0"          (通則, whole doc)
      section_number=N, level=()          → "secN"          (whole doc as one item)
      section_number=None, level=()       → "appendix-doc"
    """
    if section_number is None:
        return "appendix-doc"
    if not level:
        return f"sec{section_number}"
    return f"sec{section_number}-{_level_to_str(level)}"


def format_section_path(node: Node, ancestors: list[Node]) -> list[str]:
    """Full chain from document title (first ancestor) through this node's heading."""
    return [a.heading for a in ancestors] + [node.heading]


# ---------------------------------------------------------------------------
# Leaf splitting (spec §4.2)
# ---------------------------------------------------------------------------

NUMBERED_LIST_RE = re.compile(r"^(\d+)\.\s", re.MULTILINE)

# Top-level numbered item at the start of a paragraph: "1.X" or "1. X".
# NHI writes "1.本類藥品..." (no space after the dot) — we must match that.
# The negative lookahead `(?!\d)` excludes "4.1" cross-references and dotted
# heading prefixes like "9.69." from being mistaken for top-level items.
TOP_LEVEL_ITEM_RE = re.compile(r"^(\d+)\.(?!\d)")


def _group_blocks_by_numbered_item(body: list) -> list[list] | None:
    """Group body blocks by top-level numbered item.

    Each Paragraph whose text matches `^N.\\s` opens a new group. Tables and
    continuation paragraphs attach to whichever group is currently open. Any
    blocks before the first numbered item form a preamble group that gets
    merged into the first item group (so preamble context isn't orphaned).

    Returns:
      List of groups (each a list of blocks) when ≥2 numbered items found,
      else None (caller should try another strategy).
    """
    groups: list[list] = [[]]  # index 0 = preamble bucket
    item_starts = 0
    for block in body:
        if isinstance(block, Paragraph) and TOP_LEVEL_ITEM_RE.match(block.text):
            groups.append([block])
            item_starts += 1
        else:
            groups[-1].append(block)
    if item_starts < 2:
        return None
    preamble, *item_groups = groups
    if preamble:
        # Prepend preamble blocks to the first item group so context is preserved.
        item_groups[0] = preamble + item_groups[0]
    return item_groups


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
            piece = f"{preamble}\n{piece}"
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

    from .config import HARD_BUDGET

    base_id = make_item_id(section_number, leaf.level)
    section_path = format_section_path(leaf, ancestors)
    heading_prefix = f"## {leaf.heading}\n"

    # Strategy 0: multi-block leaf with top-level numbered items (e.g. 9.69.).
    # Group blocks so each chunk holds one complete numbered item; tables and
    # continuation paragraphs travel with whichever item they describe.
    groups = _group_blocks_by_numbered_item(leaf.body)
    if groups is not None:
        items: list[Item] = []
        for i, group in enumerate(groups, start=1):
            rendered_blocks: list[str] = []
            for b in group:
                if isinstance(b, Paragraph):
                    rendered_blocks.append(b.text)
                else:
                    rendered_blocks.append(table_to_markdown(b))
            content = heading_prefix + "\n".join(rendered_blocks)
            items.append(_make_chunk_item(
                base_id=base_id, part_index=i, suffix="part",
                heading=leaf.heading, section_path=section_path,
                content_md=content, source=source,
            ))
        # If any chunk still exceeds HARD_BUDGET, recursively split that one
        # group by recursing into split_leaf with a temp Node containing only
        # those blocks. The numbered-item content itself is now atomic context.
        out: list[Item] = []
        for it, group in zip(items, groups):
            if it.token_count <= HARD_BUDGET:
                out.append(it)
            else:
                sub_leaf = Node(heading=leaf.heading, level=leaf.level, body=group)
                sub_items = _split_leaf_without_strategy_0(
                    sub_leaf,
                    ancestors=ancestors,
                    section_number=section_number,
                    source=source,
                    target_budget=target_budget,
                )
                # Re-id with the parent part index so ids remain stable.
                for j, si in enumerate(sub_items, start=1):
                    from dataclasses import replace
                    out.append(replace(si, item_id=f"{it.item_id}-{j}"))
        return out

    return _split_leaf_without_strategy_0(
        leaf,
        ancestors=ancestors,
        section_number=section_number,
        source=source,
        target_budget=target_budget,
    )


def _split_leaf_without_strategy_0(
    leaf: Node,
    *,
    ancestors: list[Node],
    section_number: int | None,
    source: SourceDoc,
    target_budget: int,
) -> list[Item]:
    """Strategies 1–3 of leaf splitting (the original split_leaf logic).

    Extracted so Strategy 0 can recurse into it for over-budget groups."""
    from .config import HARD_BUDGET

    base_id = make_item_id(section_number, leaf.level)
    section_path = format_section_path(leaf, ancestors)
    heading_prefix = f"## {leaf.heading}\n"

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
    items = []
    current_parts: list[str] = []
    current_size = count_tokens(heading_prefix)
    part_idx = 1

    def flush():
        nonlocal current_parts, current_size, part_idx
        if not current_parts:
            return
        content = heading_prefix + "\n".join(current_parts)
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
    content_md = "\n".join(parts)
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
    emit_depth: int,
) -> list[Item]:
    # Pure-heading nodes (no body, has children) always descend — never emit as a single item.
    if node.children and not node.body:
        out: list[Item] = []
        new_ancestors = ancestors + [node]
        for child in node.children:
            out.extend(_chunk_node(child, new_ancestors, section_number, source,
                                   target_budget, emit_depth))
        return out

    # Task I: depth gate. A node with children that's shallower than emit_depth
    # MUST descend, even if its whole subtree would fit budget. This is what
    # prevents "整節一筆" collapse when budget is large relative to NHI content.
    # Leaves (no children) are exempt — there's nowhere to go.
    depth = len(node.level)
    if depth < emit_depth and node.children:
        out = []
        if has_significant_body(node):
            out.append(_emit_body_only(node, ancestors, section_number, source))
        new_ancestors = ancestors + [node]
        for child in node.children:
            out.extend(_chunk_node(child, new_ancestors, section_number, source,
                                   target_budget, emit_depth))
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
            out.extend(_chunk_node(child, new_ancestors, section_number, source,
                                   target_budget, emit_depth))
        return out

    # Leaf, over budget → semantic split.
    return split_leaf(
        node,
        ancestors=ancestors,
        section_number=section_number,
        source=source,
        target_budget=target_budget,
    )


def chunk_document(doc, *, emit_depth: int | None = None) -> list[Item]:
    """Public entry point: Document → list[Item], all within HARD_BUDGET.

    Args:
        doc: parsed Document tree.
        emit_depth: minimum tree depth at which a node may emit as a single
            row. Defaults to `config.EMIT_DEPTH` (5). Must be ≥ 1.
    """
    from .config import EMIT_DEPTH, HARD_BUDGET, TARGET_BUDGET
    if emit_depth is None:
        emit_depth = EMIT_DEPTH
    if not isinstance(emit_depth, int) or emit_depth < 1:
        raise ValueError(f"emit_depth must be a positive integer, got {emit_depth!r}")

    items: list[Item] = []
    if doc.root.children:
        for child in doc.root.children:
            items.extend(_chunk_node(
                child,
                ancestors=[doc.root],
                section_number=doc.section_number,
                source=doc.source,
                target_budget=TARGET_BUDGET,
                emit_depth=emit_depth,
            ))
    elif doc.root.body:
        # Document with body content but no detected headings (e.g. 通則, which
        # uses Chinese numerals 一、二、三 that don't match the Arabic heading
        # regex). Treat the root itself as a single chunkable unit — emit as
        # one item if it fits, otherwise split via the leaf splitter.
        items.extend(_chunk_node(
            doc.root,
            ancestors=[],
            section_number=doc.section_number,
            source=doc.source,
            target_budget=TARGET_BUDGET,
            emit_depth=emit_depth,
        ))

    # item_id uniqueness contract: every emitted item_id must be unique within
    # a document. Historically a "-dup{N}" band-aid covered collisions caused
    # by tilde cross-references ("4.1~3項規定") being misclassified as the
    # 4.1 heading — that's fixed at the parser level now (parse.TILDE_REFERENCE_RE).
    # If any collision still slips through, fail loud rather than emit unstable
    # ids that would poison release-over-release diffs.
    seen: dict[str, int] = {}
    for item in items:
        seen[item.item_id] = seen.get(item.item_id, 0) + 1
    collisions = {k: v for k, v in seen.items() if v > 1}
    if collisions:
        raise ValueError(
            f"item_id collisions detected — parser likely missing a heading exception. "
            f"Collisions: {collisions}"
        )

    over = [i for i in items if i.token_count > HARD_BUDGET]
    if over:
        ids = ", ".join(f"{i.item_id}({i.token_count})" for i in over)
        raise ValueError(
            f"Budget contract violated — {len(over)} items exceed HARD_BUDGET={HARD_BUDGET}: {ids}"
        )

    return items
