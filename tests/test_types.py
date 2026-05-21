from datetime import date
from pathlib import Path

from nhi_extractor.types import (
    SourceDoc, Manifest, Document, Node, Paragraph, Table, Item,
)


def test_source_doc_is_frozen():
    sd = SourceDoc(
        path=Path("/tmp/foo.docx"),
        url="https://example.com/foo.docx",
        display_name="Foo",
        update_date_iso=date(2026, 3, 24),
    )
    assert sd.display_name == "Foo"


def test_node_default_body_and_children_are_independent():
    n1 = Node(heading="9.69.", level=(9, 69))
    n2 = Node(heading="9.70.", level=(9, 70))
    n1.body.append(Paragraph(text="some text"))
    assert len(n1.body) == 1
    assert len(n2.body) == 0  # not shared


def test_table_minimal():
    t = Table(header=["A", "B"], rows=[["1", "2"]], caption=None)
    assert t.header == ["A", "B"]


def test_document_holds_root():
    sd = SourceDoc(
        path=Path("/tmp/foo.docx"),
        url="x",
        display_name="y",
        update_date_iso=date(2026, 3, 24),
    )
    doc = Document(source=sd, title="第9節 抗癌瘤藥物", section_number=9, root=Node(heading="root", level=()))
    assert doc.section_number == 9


def test_item_is_frozen():
    sd = SourceDoc(
        path=Path("/tmp/foo.docx"),
        url="x",
        display_name="y",
        update_date_iso=date(2026, 3, 24),
    )
    item = Item(
        item_id="sec9-9.69.1",
        section_path=["第9節 抗癌瘤藥物", "9.69.", "9.69.1."],
        heading="9.69.1.",
        content_md="# 9.69.1.\n\nfoo",
        source=sd,
        token_count=42,
    )
    assert item.item_id == "sec9-9.69.1"
