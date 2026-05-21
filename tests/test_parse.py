from datetime import date
from pathlib import Path

from nhi_extractor.parse import parse_docx
from nhi_extractor.types import Document, Node, Paragraph, SourceDoc, Table


def _make_source(p: Path) -> SourceDoc:
    return SourceDoc(
        path=p, url="https://example.com/x.docx",
        display_name=p.stem, update_date_iso=date(2026, 3, 24),
    )


def test_parse_returns_document(fixture_section_3):
    doc = parse_docx(_make_source(fixture_section_3))
    assert isinstance(doc, Document)
    assert doc.title  # non-empty
    assert isinstance(doc.root, Node)


def test_parse_extracts_section_number(fixture_section_3):
    doc = parse_docx(_make_source(fixture_section_3))
    assert doc.section_number == 3


def test_parse_builds_hierarchical_tree(fixture_section_9):
    doc = parse_docx(_make_source(fixture_section_9))
    assert len(doc.root.children) > 5
    assert any(len(c.children) > 0 for c in doc.root.children)


def test_parse_preserves_tables(fixture_section_9):
    doc = parse_docx(_make_source(fixture_section_9))

    def find_tables(node: Node) -> list[Table]:
        out = [b for b in node.body if isinstance(b, Table)]
        for c in node.children:
            out.extend(find_tables(c))
        return out

    tables = find_tables(doc.root)
    assert len(tables) >= 1, "section 9 should contain at least one table"


def test_parse_node_body_separated_from_children(fixture_section_3):
    doc = parse_docx(_make_source(fixture_section_3))
    def has_both(node: Node) -> bool:
        if node.body and node.children:
            return True
        return any(has_both(c) for c in node.children)
    assert has_both(doc.root)
