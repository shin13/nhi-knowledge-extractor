from nhi_extractor.chunk import split_leaf
from nhi_extractor.types import Node, Paragraph, Table


def _ancestors():
    return [Node(heading="第9節 抗癌瘤藥物", level=())]


def test_split_leaf_by_numbered_list():
    body_text = "\n".join([
        "前言說明。",
        "1. 第一項規定的內容。",
        "2. 第二項規定的內容。",
        "3. 第三項規定的內容。",
    ])
    leaf = Node(heading="9.69. 免疫檢查點抑制劑", level=(9, 69),
                body=[Paragraph(text=body_text)])
    chunks = split_leaf(leaf, ancestors=_ancestors(), section_number=9, target_budget=20)
    assert len(chunks) >= 3
    assert all("9.69." in c.content_md for c in chunks)
    assert chunks[0].item_id == "sec9-9.69-part1"
    assert chunks[1].item_id == "sec9-9.69-part2"


def test_split_leaf_oversize_table_by_rows():
    big_table = Table(
        header=["藥品", "適應症A", "適應症B"],
        rows=[[f"drug{i}", f"crit-a-{i}", f"crit-b-{i}"] for i in range(20)],
        caption="表 9.69.1",
    )
    leaf = Node(heading="9.69.1.", level=(9, 69, 1), body=[big_table])
    chunks = split_leaf(leaf, ancestors=_ancestors(), section_number=9, target_budget=80)
    assert len(chunks) >= 2
    for c in chunks:
        assert "| 藥品 | 適應症A | 適應症B |" in c.content_md
    assert all("tbl" in c.item_id for c in chunks)


def test_split_leaf_fallback_paragraph_split():
    leaf = Node(
        heading="9.99.",
        level=(9, 99),
        body=[
            Paragraph(text="段落一。" * 20),
            Paragraph(text="段落二。" * 20),
            Paragraph(text="段落三。" * 20),
        ],
    )
    chunks = split_leaf(leaf, ancestors=_ancestors(), section_number=9, target_budget=40)
    assert len(chunks) >= 2


# --- Strategy 0: multi-block numbered-item grouping (Task D) -----------------

def test_split_leaf_multiblock_with_numbered_items_and_table():
    """A real-world shape from §9.69: heading + (1. ...) paragraph + table +
    (2. ...) paragraph. The table belongs with item 1 (its descriptive prose).
    Each chunk should contain one complete numbered item, table living with item 1."""
    leaf = Node(
        heading="9.69. 免疫檢查點抑制劑",
        level=(9, 69),
        body=[
            Paragraph(text="1. 本類藥品說明，包含 (1)黑色素瘤 (2)非小細胞肺癌等子項目。"),
            Paragraph(text="續論：詳細表格如下，列出各藥品適應症對照。"),
            Table(header=["給付範圍", "pembrolizumab", "nivolumab"],
                  rows=[["黑色素瘤", "可", "可"], ["肺癌", "可", "可"]], caption=None),
            Paragraph(text="2. 第二項規定的內容如此這般。"),
            Paragraph(text="3. 第三項。"),
        ],
    )
    chunks = split_leaf(leaf, ancestors=_ancestors(), section_number=9, target_budget=200)
    # Expect ≥3 chunks — one per top-level numbered item.
    assert len(chunks) >= 3, f"got {len(chunks)} chunks: {[c.item_id for c in chunks]}"

    # The chunk containing item 1 must also contain the table.
    item1_chunks = [c for c in chunks if "1. 本類藥品" in c.content_md]
    assert item1_chunks, f"no chunk contains item 1; ids={[c.item_id for c in chunks]}"
    assert any("給付範圍" in c.content_md for c in item1_chunks), (
        "table must travel with the item-1 chunk (its descriptive prose); "
        f"got item-1 chunks without table: {[c.content_md[:120] for c in item1_chunks]}"
    )

    # No chunk should contain a fragment of item 1 AND a fragment of item 2.
    for c in chunks:
        if "1. 本類藥品" in c.content_md:
            assert "2. 第二項" not in c.content_md, (
                f"chunk {c.item_id} mixes items 1 and 2 — violates self-contained rule"
            )

    # Heading should appear in every chunk for retrieval context.
    assert all("9.69." in c.content_md for c in chunks)


def test_split_leaf_multiblock_preamble_kept_with_first_item():
    """If body has prose before the first numbered item, that preamble should
    travel with item 1 — otherwise it's orphaned content with no heading context."""
    leaf = Node(
        heading="9.50.",
        level=(9, 50),
        body=[
            Paragraph(text="本規定總則：適用於下列情形。"),
            Paragraph(text="1. 第一情形的細節。"),
            Paragraph(text="2. 第二情形的細節。"),
        ],
    )
    chunks = split_leaf(leaf, ancestors=_ancestors(), section_number=9, target_budget=200)
    assert len(chunks) >= 2
    # First chunk must contain both the preamble and item 1.
    first = chunks[0]
    assert "本規定總則" in first.content_md, f"preamble missing from first chunk: {first.content_md[:200]}"
    assert "1. 第一情形" in first.content_md


def test_split_leaf_multiblock_no_numbered_items_falls_back():
    """Multi-block leaf with no top-level numbered items must fall through to
    the existing greedy paragraph accumulator (Strategy 3)."""
    leaf = Node(
        heading="9.99.",
        level=(9, 99),
        body=[
            Paragraph(text="一、第一段。" + "甲" * 50),
            Paragraph(text="二、第二段。" + "乙" * 50),
            Paragraph(text="三、第三段。" + "丙" * 50),
        ],
    )
    chunks = split_leaf(leaf, ancestors=_ancestors(), section_number=9, target_budget=60)
    assert len(chunks) >= 2
    # No chunk is the same as the input — proves the splitter ran.


def test_split_leaf_multiblock_single_numbered_item_falls_back():
    """If only ONE `^N.\\s` item is found in the body, that's not enough to split
    by — must fall through to other strategies."""
    leaf = Node(
        heading="9.50.",
        level=(9, 50),
        body=[
            Paragraph(text="說明一。" * 50),
            Paragraph(text="1. 只有一個編號項。" * 30),
            Paragraph(text="說明二。" * 50),
        ],
    )
    chunks = split_leaf(leaf, ancestors=_ancestors(), section_number=9, target_budget=50)
    # Should not split by numbered-item grouping (only 1 item); falls back to
    # paragraph accumulation → ≥2 chunks.
    assert len(chunks) >= 2
