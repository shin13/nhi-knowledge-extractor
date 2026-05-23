"""Tests for the EMIT_DEPTH parameter (Task I).

EMIT_DEPTH is the minimum tree depth at which a node may emit as a single row.
Below this depth, chunker MUST descend (ignoring budget). At or beyond it,
existing budget-driven logic applies.
"""
from datetime import date
from pathlib import Path

import pytest

from nhi_extractor.chunk import chunk_document
from nhi_extractor.types import Document, Node, Paragraph, SourceDoc


def _source() -> SourceDoc:
    return SourceDoc(path=Path("t.docx"), url="", display_name="t",
                     update_date_iso=date(2026, 4, 24))


def test_emit_depth_forces_descent_when_subtree_fits_budget():
    """A d=1 node with children — even if its whole subtree fits — must descend
    when EMIT_DEPTH > 1. Without this rule, big budgets collapse to '整節一筆'."""
    root = Node(
        heading="第3節 代謝及營養劑",
        level=(),
        children=[
            Node(
                heading="3.1.",
                level=(3, 1),
                body=[Paragraph(text="短")],
                children=[
                    Node(heading="3.1.1. 藥A", level=(3, 1, 1), body=[Paragraph(text="A 短")]),
                    Node(heading="3.1.2. 藥B", level=(3, 1, 2), body=[Paragraph(text="B 短")]),
                ],
            ),
        ],
    )
    doc = Document(source=_source(), title="第3節", section_number=3, root=root)
    items = chunk_document(doc, emit_depth=3)
    ids = [i.item_id for i in items]
    # Must NOT emit sec3-3.1 as a single subtree — must descend to its children.
    assert "sec3-3.1" not in ids, f"expected descent past d=2 with EMIT_DEPTH=3, got {ids}"
    assert "sec3-3.1.1" in ids
    assert "sec3-3.1.2" in ids


def test_emit_depth_emits_at_target_when_fits():
    """A node at exactly EMIT_DEPTH that fits budget should emit as single subtree."""
    root = Node(
        heading="第3節",
        level=(),
        children=[
            Node(
                heading="3.1. drugA",
                level=(3, 1),
                body=[Paragraph(text="content")],
                children=[
                    Node(heading="3.1.1.", level=(3, 1, 1), body=[Paragraph(text="leaf")]),
                ],
            ),
        ],
    )
    doc = Document(source=_source(), title="第3節", section_number=3, root=root)
    items = chunk_document(doc, emit_depth=2)
    ids = [i.item_id for i in items]
    # At EMIT_DEPTH=2, 3.1 is at target depth — emit as single subtree.
    assert "sec3-3.1" in ids
    # 3.1.1 should NOT be a separate row — it was rolled up into 3.1.
    assert "sec3-3.1.1" not in ids


def test_emit_depth_descends_past_target_when_over_budget():
    """Budget can push descent deeper than EMIT_DEPTH — a node at target depth
    that's over budget must still descend / leaf-split."""
    big = Paragraph(text="x" * 50_000)
    root = Node(
        heading="第9節",
        level=(),
        children=[
            Node(
                heading="9.1.",
                level=(9, 1),
                children=[Node(heading="9.1.1.", level=(9, 1, 1), body=[big])],
            ),
        ],
    )
    doc = Document(source=_source(), title="第9節", section_number=9, root=root)
    items = chunk_document(doc, emit_depth=2)
    # 9.1 is at EMIT_DEPTH=2 but oversized — chunker must descend past it.
    ids = [i.item_id for i in items]
    assert any(i.startswith("sec9-9.1.1") for i in ids), f"expected descent into 9.1.1, got {ids}"


def test_emit_depth_leaf_emits_regardless_of_depth():
    """A leaf (no children) at d=1 must emit — there's nothing to descend into,
    even if d < EMIT_DEPTH. (NHI shape: e.g. 9.70 Pertuzumab is a d=2 leaf.)"""
    root = Node(
        heading="第9節",
        level=(),
        children=[
            Node(heading="9.70. Pertuzumab", level=(9, 70),
                 body=[Paragraph(text="single drug regulation")]),
        ],
    )
    doc = Document(source=_source(), title="第9節", section_number=9, root=root)
    items = chunk_document(doc, emit_depth=5)
    # 9.70 is d=2 leaf; EMIT_DEPTH=5 can't push past leaf → must emit at d=2.
    ids = [i.item_id for i in items]
    assert "sec9-9.70" in ids


def test_emit_depth_too_large_is_safe():
    """Setting emit_depth higher than tree max depth should NOT error — it
    gracefully degrades to 'emit at every leaf'."""
    root = Node(
        heading="第3節",
        level=(),
        children=[
            Node(heading="3.1.", level=(3, 1), body=[Paragraph(text="short")]),
            Node(heading="3.2.", level=(3, 2), body=[Paragraph(text="short")]),
        ],
    )
    doc = Document(source=_source(), title="第3節", section_number=3, root=root)
    # Tree max depth is 2; setting 99 should produce same result as 5 or 2.
    items_99 = chunk_document(doc, emit_depth=99)
    items_5 = chunk_document(doc, emit_depth=5)
    items_2 = chunk_document(doc, emit_depth=2)
    assert [i.item_id for i in items_99] == [i.item_id for i in items_5] == [i.item_id for i in items_2]


def test_emit_depth_validates_positive_int():
    """emit_depth < 1 should raise."""
    root = Node(heading="t", level=(), children=[
        Node(heading="3.1.", level=(3, 1), body=[Paragraph(text="x")]),
    ])
    doc = Document(source=_source(), title="t", section_number=3, root=root)
    with pytest.raises(ValueError, match="emit_depth"):
        chunk_document(doc, emit_depth=0)
    with pytest.raises(ValueError, match="emit_depth"):
        chunk_document(doc, emit_depth=-1)


def test_emit_depth_root_only_doc_unchanged(fixture_tongze_odt):
    """通則 (root-only doc, no children) emits as a single item regardless of
    EMIT_DEPTH — there are no children to descend into."""
    from nhi_extractor.parse import parse_document
    sd = SourceDoc(path=fixture_tongze_odt, url="", display_name="通則",
                   update_date_iso=date(2026, 4, 24))
    doc = parse_document(sd)
    items = chunk_document(doc, emit_depth=5)
    assert len(items) == 1
    assert items[0].item_id == "sec0"
