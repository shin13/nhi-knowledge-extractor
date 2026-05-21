from nhi_extractor.chunk import format_section_path, has_significant_body, make_item_id
from nhi_extractor.types import Node, Paragraph, Table


def test_has_significant_body_empty():
    n = Node(heading="9.", level=(9,))
    assert not has_significant_body(n)


def test_has_significant_body_trivial_paragraph():
    n = Node(heading="9.", level=(9,), body=[Paragraph(text="短引言")])
    assert not has_significant_body(n)


def test_has_significant_body_multiple_paragraphs():
    n = Node(
        heading="9.",
        level=(9,),
        body=[Paragraph(text="一"), Paragraph(text="二")],
    )
    assert has_significant_body(n)


def test_has_significant_body_with_table():
    n = Node(
        heading="9.",
        level=(9,),
        body=[Table(header=["A"], rows=[["1"]], caption=None)],
    )
    assert has_significant_body(n)


def test_has_significant_body_long_paragraph():
    long = "藥品給付規定詳細說明。" * 200
    n = Node(heading="9.", level=(9,), body=[Paragraph(text=long)])
    assert has_significant_body(n)


def test_make_item_id_section():
    assert make_item_id(section_number=9, level=(9, 69, 1)) == "sec9-9.69.1"


def test_make_item_id_top_level_section():
    assert make_item_id(section_number=9, level=(9,)) == "sec9-9"


def test_make_item_id_appendix():
    assert make_item_id(section_number=None, level=()) == "appendix-doc"


def test_format_section_path_includes_document_title_and_chain():
    ancestors = [
        Node(heading="第9節 抗癌瘤藥物", level=()),
        Node(heading="9.69. 免疫檢查點抑制劑", level=(9, 69)),
    ]
    node = Node(heading="9.69.1. PD-L1", level=(9, 69, 1))
    path = format_section_path(node, ancestors)
    assert path == ["第9節 抗癌瘤藥物", "9.69. 免疫檢查點抑制劑", "9.69.1. PD-L1"]
