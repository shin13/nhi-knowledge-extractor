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


# --- Tilde cross-references must NOT be parsed as headings (Task E) ----------

def test_detect_heading_rejects_tilde_range_reference():
    """Paragraphs that begin with cross-references like '4.1~3項規定' are NOT
    section headings — they're inline references to items 4.1 through 4.3.

    Before this fix, the regex ^\\d+(\\.\\d+)+ caught the leading '4.1' and
    promoted the paragraph to a fake (4,1) heading. Two of these in one doc
    (the genuine 4.1. heading + a body paragraph starting with 4.1~3項規定)
    collided on item_id 'sec4-4.1' and forced the chunker's -dup band-aid.
    """
    from nhi_extractor.parse import _detect_heading_level_from_text

    assert _detect_heading_level_from_text("4.1~3項規定，應符合下列條件") is None
    assert _detect_heading_level_from_text("7.2~5") is None
    assert _detect_heading_level_from_text("10.3~5項") is None
    # Genuine headings must still be detected.
    assert _detect_heading_level_from_text("4.1") == (4, 1)
    assert _detect_heading_level_from_text("4.1.") == (4, 1)
    assert _detect_heading_level_from_text("4.1. 療養劑") == (4, 1)
    assert _detect_heading_level_from_text("9.69.1") == (9, 69, 1)


def test_detect_heading_rejects_bare_numbered_item_with_cjk_continuation():
    """NHI body paragraphs like '2.18歲以上非瓣膜性...' look like a (2,18)
    heading to a naive regex but are list items whose content starts with
    '18歲以上...'. The trailing-separator rule (heading must be followed by
    `.`, whitespace, or end-of-string) keeps them as body paragraphs."""
    from nhi_extractor.parse import _detect_heading_level_from_text

    # Body paragraphs — number followed immediately by CJK = NOT a heading.
    assert _detect_heading_level_from_text("2.18歲以上非瓣膜性心房纖維顫動病患") is None
    assert _detect_heading_level_from_text("3.40週歲以下兒童") is None

    # Genuine headings — number followed by `.`, whitespace, or end-of-string.
    assert _detect_heading_level_from_text("2.18.Captopril內服液劑") == (2, 18)
    assert _detect_heading_level_from_text("2.18. Captopril") == (2, 18)
    assert _detect_heading_level_from_text("2.18 心臟血管藥物") == (2, 18)


def test_parse_does_not_emit_dup_item_ids_on_real_fixtures(fixture_section_9):
    """End-to-end: after the tilde-rejection fix, chunking real §9 should
    produce no item_ids carrying the -dup band-aid suffix."""
    from nhi_extractor.chunk import chunk_document
    doc = parse_document(_make_source(fixture_section_9))
    items = chunk_document(doc)
    dup_ids = [it.item_id for it in items if "-dup" in it.item_id]
    assert not dup_ids, f"unexpected -dup item_ids: {dup_ids}"
