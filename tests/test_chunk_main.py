from datetime import date
from pathlib import Path

from nhi_extractor.chunk import chunk_document
from nhi_extractor.config import HARD_BUDGET
from nhi_extractor.types import Document, Node, Paragraph, SourceDoc, Table


def _source(p: Path = Path("test.docx")) -> SourceDoc:
    return SourceDoc(path=p, url="", display_name="t", update_date_iso=date(2026, 3, 24))


def test_chunk_document_small_doc_one_item():
    """A document whose root is well within budget produces one item per child."""
    root = Node(
        heading="第3節 代謝及營養劑",
        level=(),
        children=[
            Node(heading="3.1. 一個小規則", level=(3, 1), body=[Paragraph(text="內容很短。")]),
            Node(heading="3.2. 另一個小規則", level=(3, 2), body=[Paragraph(text="也很短。")]),
        ],
    )
    doc = Document(source=_source(), title="第3節 代謝及營養劑", section_number=3, root=root)
    items = chunk_document(doc)
    assert len(items) == 2
    assert items[0].item_id == "sec3-3.1"
    assert items[1].item_id == "sec3-3.2"
    assert all("第3節 代謝及營養劑" in i.section_path[0] for i in items)


def test_chunk_document_descends_when_over_budget():
    big_body = Paragraph(text="長文本。" * 5000)
    root = Node(
        heading="第9節",
        level=(),
        children=[
            Node(
                heading="9.1.",
                level=(9, 1),
                children=[
                    Node(heading="9.1.1.", level=(9, 1, 1), body=[big_body]),
                    Node(heading="9.1.2.", level=(9, 1, 2), body=[Paragraph(text="短")]),
                ],
            ),
        ],
    )
    doc = Document(source=_source(), title="第9節", section_number=9, root=root)
    items = chunk_document(doc)
    item_ids = [i.item_id for i in items]
    assert any(i.startswith("sec9-9.1.1") for i in item_ids)
    assert any(i.startswith("sec9-9.1.2") for i in item_ids)


def test_chunk_document_budget_contract():
    """No item may exceed HARD_BUDGET."""
    root = Node(
        heading="第9節",
        level=(),
        children=[
            Node(heading="9.1.", level=(9, 1), body=[Paragraph(text="x" * 100_000)]),
        ],
    )
    doc = Document(source=_source(), title="第9節", section_number=9, root=root)
    items = chunk_document(doc)
    for item in items:
        assert item.token_count <= HARD_BUDGET, f"{item.item_id} = {item.token_count} tokens"


def test_chunk_document_root_only_emits_single_item():
    """When the root has body content but no detected children (e.g. 通則 which
    uses Chinese-numeral headings), the whole document should emit as one item
    if it fits within budget — not be silently dropped."""
    root = Node(
        heading="藥品給付規定通則",
        level=(),
        body=[
            Paragraph(text="一、本保險醫事服務機構申報之藥品..."),
            Paragraph(text="二、本保險醫療用藥..."),
            Paragraph(text="三、本保險處方用藥..."),
        ],
        children=[],
    )
    doc = Document(source=_source(), title="藥品給付規定通則", section_number=0, root=root)
    items = chunk_document(doc)
    assert len(items) == 1
    assert items[0].item_id == "sec0"
    assert "一、" in items[0].content_md
    assert "三、" in items[0].content_md


def test_chunk_document_skip_node_with_no_body_only_children():
    """A pure section heading (no body, has children) emits no item itself."""
    root = Node(
        heading="第9節",
        level=(),
        children=[
            Node(
                heading="9. 抗癌瘤藥物",
                level=(9,),
                body=[],
                children=[Node(heading="9.1.", level=(9, 1), body=[Paragraph(text="x")])],
            ),
        ],
    )
    doc = Document(source=_source(), title="第9節", section_number=9, root=root)
    items = chunk_document(doc)
    assert not any(i.item_id == "sec9-9" for i in items)
    assert any(i.item_id == "sec9-9.1" for i in items)
