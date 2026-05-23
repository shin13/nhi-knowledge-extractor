"""Tests for Strategy 0 anchor preamble in continuation sub-parts (Task K).

When a numbered-item group itself exceeds HARD_BUDGET and gets recursively
sub-split, every sub-part except the first must inject the group's opener
line (e.g. `3. 使用條件`) followed by `（續）：` so the row is self-contained
for RAG retrieval.
"""
from datetime import date
from pathlib import Path

from nhi_extractor.chunk import chunk_document, split_leaf
from nhi_extractor.types import Document, Node, Paragraph, SourceDoc


def _source() -> SourceDoc:
    return SourceDoc(path=Path("t.docx"), url="", display_name="t",
                     update_date_iso=date(2026, 4, 24))


def _make_leaf_with_oversized_group_3():
    """Build a 4-numbered-item leaf where group 3 alone exceeds HARD_BUDGET.

    Use multiple medium paragraphs in group 3 (closer to real NHI shape) so
    Strategy 3 paragraph-accumulation can flush at natural boundaries — avoids
    relying on the brittle char-split last-resort.
    """
    para = "本條規定內容應依據本辦法第三項規定辦理並符合下列各款要件之規定不得違反相關法令。" * 35
    return Node(
        heading="9.69. 免疫檢查點抑制劑",
        level=(9, 69),
        body=[
            Paragraph(text="1. 第一項規定。"),
            Paragraph(text="2. 第二項規定。"),
            Paragraph(text="3. 使用條件："),  # group-3 opener
            Paragraph(text=f"(1) {para}"),
            Paragraph(text=f"(2) {para}"),
            Paragraph(text=f"(3) {para}"),
            Paragraph(text=f"(4) {para}"),
            Paragraph(text=f"(5) {para}"),
            Paragraph(text="4. 第四項規定。"),
        ],
    )


def test_first_subpart_does_not_repeat_anchor():
    """The first continuation sub-part naturally contains the group opener
    (e.g. `3. 使用條件：...`) — it must NOT have a `（續）` marker prepended."""
    leaf = _make_leaf_with_oversized_group_3()
    items = split_leaf(leaf, ancestors=[Node(heading="第9節", level=())],
                       section_number=9)
    # Find sub-parts of group 3 (item_id contains '-part3-')
    part3_subs = sorted(
        (i for i in items if "-part3-" in i.item_id),
        key=lambda i: i.item_id,
    )
    assert len(part3_subs) >= 2, f"expected sub-split, got {[i.item_id for i in items]}"
    first_sub = part3_subs[0]
    assert "（續）" not in first_sub.content_md, (
        f"first sub-part should NOT have (續), got:\n{first_sub.content_md[:300]}"
    )


def test_continuation_subparts_have_anchor_with_continuation_marker():
    """Sub-parts 2..N must contain the anchor line followed by `（續）：`."""
    leaf = _make_leaf_with_oversized_group_3()
    items = split_leaf(leaf, ancestors=[Node(heading="第9節", level=())],
                       section_number=9)
    part3_subs = sorted(
        (i for i in items if "-part3-" in i.item_id),
        key=lambda i: i.item_id,
    )
    assert len(part3_subs) >= 2
    for sub in part3_subs[1:]:
        assert "3. 使用條件" in sub.content_md, (
            f"continuation sub-part missing anchor:\n{sub.content_md[:300]}"
        )
        assert "（續）" in sub.content_md, (
            f"continuation sub-part missing （續） marker:\n{sub.content_md[:300]}"
        )


def test_anchor_strips_trailing_colon_to_avoid_double_colon():
    """Opener `3. 使用條件：` should produce `3. 使用條件（續）：`, not
    `3. 使用條件：（續）：` with doubled colon."""
    leaf = _make_leaf_with_oversized_group_3()
    items = split_leaf(leaf, ancestors=[Node(heading="第9節", level=())],
                       section_number=9)
    part3_subs = sorted(
        (i for i in items if "-part3-" in i.item_id),
        key=lambda i: i.item_id,
    )
    for sub in part3_subs[1:]:
        assert "：（續）" not in sub.content_md, (
            f"double colon detected in:\n{sub.content_md[:300]}"
        )


def test_non_recursive_group_unchanged():
    """A group that fits under HARD_BUDGET should NOT have `（續）` injected —
    only triggered when recursive sub-splitting actually happens."""
    # All four groups stay small, no recursion.
    medium = "適應症說明文字。" * 100  # ~800 chars
    leaf = Node(
        heading="9.69.",
        level=(9, 69),
        body=[
            Paragraph(text=f"1. {medium}"),
            Paragraph(text=f"2. {medium}"),
            Paragraph(text=f"3. {medium}"),
            Paragraph(text=f"4. {medium}"),
        ],
    )
    items = split_leaf(leaf, ancestors=[Node(heading="第9節", level=())],
                       section_number=9)
    # 4 parts, none recursively split → no `（續）` anywhere
    for it in items:
        assert "（續）" not in it.content_md, (
            f"unexpected (續) in non-recursive split: {it.item_id}"
        )


def test_full_chunk_document_preserves_anchor():
    """End-to-end via chunk_document: 9.69-style leaf produces 5 rows with
    `（續）` on the recursive continuation."""
    leaf = _make_leaf_with_oversized_group_3()
    root = Node(heading="第9節", level=(), children=[leaf])
    doc = Document(source=_source(), title="第9節", section_number=9, root=root)
    items = chunk_document(doc)
    family = [i for i in items if i.parent_id == "sec9-9.69"]
    assert len(family) >= 5
    continuation = [i for i in family if "-part3-" in i.item_id]
    assert len(continuation) >= 2
    # At least one continuation row contains the anchor
    assert any("使用條件" in i.content_md and "（續）" in i.content_md
               for i in continuation[1:])
