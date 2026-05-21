from nhi_extractor.markdown import (
    count_tokens, table_to_markdown, render_node_to_markdown,
)
from nhi_extractor.types import Node, Paragraph, Table


def test_count_tokens_empty():
    assert count_tokens("") == 0


def test_count_tokens_nontrivial():
    n = count_tokens("hello world")
    assert n > 0
    assert n == count_tokens("hello world")  # deterministic


def test_table_to_markdown_basic():
    t = Table(header=["A", "B"], rows=[["1", "2"], ["3", "4"]], caption=None)
    md = table_to_markdown(t)
    assert "| A | B |" in md
    assert "| --- | --- |" in md
    assert "| 1 | 2 |" in md
    assert "| 3 | 4 |" in md


def test_table_to_markdown_with_caption():
    t = Table(header=["X"], rows=[["v"]], caption="表 9.69.1")
    md = table_to_markdown(t)
    assert md.startswith("**表 9.69.1**")
    assert "| X |" in md


def test_table_to_markdown_escapes_pipes_and_newlines():
    t = Table(header=["A|B"], rows=[["line1\nline2"]], caption=None)
    md = table_to_markdown(t)
    assert "A\\|B" in md
    assert "line1<br>line2" in md


def test_render_node_to_markdown_leaf_with_paragraph():
    n = Node(heading="9.69.1.", level=(9, 69, 1), body=[Paragraph(text="第一段")])
    md = render_node_to_markdown(n)
    assert "9.69.1." in md
    assert "第一段" in md


def test_render_node_to_markdown_with_table():
    n = Node(
        heading="9.69.1.",
        level=(9, 69, 1),
        body=[Paragraph(text="說明："), Table(header=["X"], rows=[["v"]], caption=None)],
    )
    md = render_node_to_markdown(n)
    assert "說明：" in md
    assert "| X |" in md


def test_render_node_to_markdown_recurses_into_children():
    child = Node(heading="9.69.1.", level=(9, 69, 1), body=[Paragraph(text="child text")])
    parent = Node(
        heading="9.69.",
        level=(9, 69),
        body=[Paragraph(text="parent intro")],
        children=[child],
    )
    md = render_node_to_markdown(parent)
    assert "9.69." in md
    assert "parent intro" in md
    assert "9.69.1." in md
    assert "child text" in md
    assert md.index("parent intro") < md.index("child text")
