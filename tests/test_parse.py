from datetime import date
from pathlib import Path

from nhi_extractor.parse import parse_docx, parse_document, parse_odt
from nhi_extractor.types import Document, Node, Paragraph, SourceDoc, Table


def _make_source(p: Path) -> SourceDoc:
    return SourceDoc(
        path=p, url=f"https://example.com/{p.name}",
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


# --- ODT parsing -------------------------------------------------------------

def test_parse_odt_tongze_has_no_arabic_headings_but_has_body(fixture_tongze_odt):
    """通則 uses Chinese-numeral headings (一、二、三). Our Arabic-only heading
    detector should not split it — instead the whole document lands in root.body
    so the chunker can emit it as one item."""
    doc = parse_odt(_make_source(fixture_tongze_odt))
    assert doc.section_number == 0, "通則 must be classified as section 0 for stable item_id"
    assert "通則" in doc.title
    assert len(doc.root.children) == 0, "no Arabic-numeral subheadings should be detected"
    assert len(doc.root.body) > 10, f"expected many body paragraphs, got {len(doc.root.body)}"


def test_parse_odt_regulation_with_arabic_headings(fixture_section_6_odt):
    """第六節 from ODT source must produce the same kind of tree as a DOCX section."""
    doc = parse_odt(_make_source(fixture_section_6_odt))
    assert doc.section_number == 6
    assert "第6節" in doc.title or "第六節" in doc.title
    assert len(doc.root.children) >= 1, "expected Arabic-numeral subheadings (6.1, 6.2, ...)"


def test_parse_document_dispatcher_by_extension(fixture_section_3, fixture_section_6_odt):
    """parse_document picks DOCX vs ODT based on file extension."""
    d_docx = parse_document(_make_source(fixture_section_3))
    d_odt = parse_document(_make_source(fixture_section_6_odt))
    assert d_docx.section_number == 3
    assert d_odt.section_number == 6


def test_parse_document_unsupported_extension(tmp_path):
    import pytest
    bogus = tmp_path / "x.pdf"
    bogus.write_bytes(b"")
    with pytest.raises(ValueError, match="Unsupported document extension"):
        parse_document(_make_source(bogus))
