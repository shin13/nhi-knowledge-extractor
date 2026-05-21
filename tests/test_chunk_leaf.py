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
