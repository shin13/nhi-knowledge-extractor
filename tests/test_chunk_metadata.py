"""Tests for Item.parent_id / part_index / total_parts metadata (Task J).

Lets downstream RAG consumers know "I'm part X of Y, all sharing parent Z"
so they can hydrate sibling parts when one is retrieved.
"""
from datetime import date
from pathlib import Path

from nhi_extractor.chunk import _derive_parent_id, chunk_document
from nhi_extractor.types import Document, Node, Paragraph, SourceDoc, Table


def _source() -> SourceDoc:
    return SourceDoc(path=Path("t.docx"), url="", display_name="t",
                     update_date_iso=date(2026, 4, 24))


# ---- _derive_parent_id unit ---------------------------------------------------

def test_derive_parent_id_strips_partN():
    assert _derive_parent_id("sec9-9.69-part1") == "sec9-9.69"
    assert _derive_parent_id("sec9-9.69-part4") == "sec9-9.69"


def test_derive_parent_id_strips_recursive_partN_M():
    """Recursive sub-split adds -part{N}-{M} suffix; strip both."""
    assert _derive_parent_id("sec9-9.69-part3-1") == "sec9-9.69"
    assert _derive_parent_id("sec9-9.69-part3-2") == "sec9-9.69"


def test_derive_parent_id_strips_tblN():
    assert _derive_parent_id("sec9-9.50-tbl1") == "sec9-9.50"
    assert _derive_parent_id("sec9-9.50-tbl3") == "sec9-9.50"


def test_derive_parent_id_strips_preamble():
    assert _derive_parent_id("sec3-3.2-preamble") == "sec3-3.2"


def test_derive_parent_id_returns_self_when_no_suffix():
    """Non-split rows: parent_id equals item_id."""
    assert _derive_parent_id("sec9-9.70") == "sec9-9.70"
    assert _derive_parent_id("sec0") == "sec0"
    assert _derive_parent_id("sec5-5.1.2.3") == "sec5-5.1.2.3"


# ---- Item metadata via chunk_document ----------------------------------------

def test_single_emit_item_has_self_as_parent():
    """A row that was emitted as a complete subtree → parent_id == item_id,
    part_index = 1, total_parts = 1."""
    root = Node(
        heading="第3節",
        level=(),
        children=[
            Node(heading="3.1. drugA", level=(3, 1), body=[Paragraph(text="short content")]),
            Node(heading="3.2. drugB", level=(3, 2), body=[Paragraph(text="short content")]),
        ],
    )
    doc = Document(source=_source(), title="第3節", section_number=3, root=root)
    items = chunk_document(doc)
    for it in items:
        assert it.parent_id == it.item_id, f"{it.item_id} parent_id mismatch"
        assert it.part_index == 1
        assert it.total_parts == 1


def test_strategy0_split_shares_parent_id():
    """Simulate 9.69-like leaf with 4 top-level numbered items + budget pressure.
    All 4 parts must share parent_id and have part_index 1..4, total_parts=4."""
    # Chinese characters tokenize ~1:1 in cl100k_base; need ~2000 tokens per
    # group to force over-budget aggregation.
    big = "本類藥品適用於下列患者並依規定給付。" * 200
    leaf = Node(
        heading="9.69. 免疫檢查點抑制劑",
        level=(9, 69),
        body=[
            Paragraph(text=f"1. 單獨使用適應症 {big}"),
            Paragraph(text=f"2. 併用其他藥品 {big}"),
            Paragraph(text=f"3. 使用條件 {big}"),
            Paragraph(text=f"4. 登錄結案 {big}"),
        ],
    )
    root = Node(heading="第9節", level=(), children=[leaf])
    doc = Document(source=_source(), title="第9節", section_number=9, root=root)
    items = chunk_document(doc)
    # All emitted rows are sec9-9.69-* family.
    rows = [i for i in items if i.parent_id == "sec9-9.69"]
    assert len(rows) >= 4, f"expected ≥4 parts, got {[i.item_id for i in rows]}"
    # part_index should be 1..N consecutive
    indexes = sorted(r.part_index for r in rows)
    assert indexes == list(range(1, len(rows) + 1)), f"part_index gap: {indexes}"
    # total_parts uniform
    assert {r.total_parts for r in rows} == {len(rows)}


def test_recursive_subsplit_flat_numbering():
    """When part3 is itself sub-split (recursive Strategy 0), the resulting
    sub-rows share parent_id with their siblings and use FLAT part_index
    numbering across the whole 9.69 group — not hierarchical 3.1/3.2."""
    # Need part 3 to exceed HARD_BUDGET (7000 tokens) on its own. Chinese
    # tokenizes ~1:1 — 8000 chars of meaningful Chinese ≈ 7000-8000 tokens.
    huge = "本條規定內容應依據本辦法第三項規定辦理並符合下列各款要件。" * 600
    leaf = Node(
        heading="9.69.",
        level=(9, 69),
        body=[
            Paragraph(text="1. 第一項"),
            Paragraph(text="2. 第二項"),
            Paragraph(text=f"3. 第三項 {huge}"),  # over HARD_BUDGET → sub-split
            Paragraph(text="4. 第四項"),
        ],
    )
    root = Node(heading="第9節", level=(), children=[leaf])
    doc = Document(source=_source(), title="第9節", section_number=9, root=root)
    items = chunk_document(doc)
    family = [i for i in items if i.parent_id == "sec9-9.69"]
    # Must be ≥5 rows: part1, part2, part3-1, part3-2(+), part4
    assert len(family) >= 5, f"expected recursive split to produce ≥5 rows, got {[i.item_id for i in family]}"
    # part_index goes 1, 2, 3, 4, ... (flat across the whole family)
    indexes = sorted(r.part_index for r in family)
    assert indexes == list(range(1, len(family) + 1))
    # total_parts is consistent
    assert len({r.total_parts for r in family}) == 1


def test_table_split_shares_parent_id():
    """Strategy 2 table-row splitting → all -tblN rows share parent_id."""
    huge_table = Table(
        header=["藥品", "適應症", "備註"],
        rows=[[f"藥{i}", "desc " * 100, "note " * 100] for i in range(50)],
        caption=None,
    )
    leaf = Node(heading="9.50. 大表", level=(9, 50), body=[huge_table])
    root = Node(heading="第9節", level=(), children=[leaf])
    doc = Document(source=_source(), title="第9節", section_number=9, root=root)
    items = chunk_document(doc)
    family = [i for i in items if i.parent_id == "sec9-9.50"]
    assert len(family) >= 2, f"expected table split, got {[i.item_id for i in family]}"
    assert all("tbl" in i.item_id for i in family)


def test_preamble_parent_resolution():
    """A -preamble item resolves parent_id to the bare id without `-preamble`.
    Children rows (5.1.1, 5.1.2) are SEPARATE logical units, NOT parts of
    the preamble — they have their own parent_id and stand alone.

    Rationale: `_derive_parent_id` only strips chunker-added suffixes (it's a
    syntactic split marker), not heading hierarchy. RAG hydration semantics:
    only re-assemble pieces of the same logical unit, not heading siblings.
    """
    # 5.1 has body + children. With EMIT_DEPTH=5 forcing descent past d=2, the
    # only requirement for preamble emission is `has_significant_body` (body
    # tokens > TRIVIAL_BODY_TOKEN_THRESHOLD=200). Stay well under HARD_BUDGET.
    big = "造血功能治療藥物給付規定內容應依據本辦法第三項規定辦理。" * 30
    root = Node(
        heading="第5節",
        level=(),
        children=[
            Node(
                heading="5.1.",
                level=(5, 1),
                body=[Paragraph(text=f"section intro {big}")],
                children=[
                    Node(heading="5.1.1.", level=(5, 1, 1), body=[Paragraph(text="child A")]),
                    Node(heading="5.1.2.", level=(5, 1, 2), body=[Paragraph(text="child B")]),
                ],
            ),
        ],
    )
    doc = Document(source=_source(), title="第5節", section_number=5, root=root)
    items = chunk_document(doc)
    by_id = {i.item_id: i for i in items}
    assert "sec5-5.1-preamble" in by_id, f"expected preamble, got {list(by_id)}"
    assert "sec5-5.1.1" in by_id
    assert "sec5-5.1.2" in by_id

    # Preamble parent_id strips -preamble suffix
    pre = by_id["sec5-5.1-preamble"]
    assert pre.parent_id == "sec5-5.1"
    # Preamble stands alone — no siblings under sec5-5.1
    assert pre.total_parts == 1
    assert pre.part_index == 1

    # Children rows are their own logical units, NOT siblings of preamble
    c1 = by_id["sec5-5.1.1"]
    assert c1.parent_id == "sec5-5.1.1"
    assert c1.total_parts == 1
    c2 = by_id["sec5-5.1.2"]
    assert c2.parent_id == "sec5-5.1.2"
    assert c2.total_parts == 1


def test_metadata_fields_present_on_all_items():
    """No item should be missing the new metadata fields."""
    root = Node(
        heading="第3節",
        level=(),
        children=[Node(heading="3.1.", level=(3, 1), body=[Paragraph(text="x")])],
    )
    doc = Document(source=_source(), title="第3節", section_number=3, root=root)
    items = chunk_document(doc)
    for it in items:
        assert it.parent_id and isinstance(it.parent_id, str)
        assert isinstance(it.part_index, int) and it.part_index >= 1
        assert isinstance(it.total_parts, int) and it.total_parts >= 1
        assert it.part_index <= it.total_parts
