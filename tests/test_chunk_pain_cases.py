from datetime import date

from nhi_extractor.chunk import chunk_document
from nhi_extractor.config import HARD_BUDGET
from nhi_extractor.parse import parse_docx
from nhi_extractor.types import SourceDoc


def _source(path):
    return SourceDoc(
        path=path, url="https://example.com",
        display_name=path.stem, update_date_iso=date(2026, 3, 24),
    )


def test_section8_row13_no_overflow(fixture_section_8):
    """The predecessor needs csv_splitter every release on §8 row 13.
    Here: no item may exceed HARD_BUDGET, and the 8.2.4. Etanercept regulation
    must be emitted as more than one item (proving the chunker descended).
    """
    doc = parse_docx(_source(fixture_section_8))
    items = chunk_document(doc)
    assert all(i.token_count <= HARD_BUDGET for i in items)
    etanercept_items = [i for i in items if i.item_id.startswith("sec8-8.2.4")]
    assert len(etanercept_items) > 1, (
        f"Expected §8.2.4. to be split into multiple items, got {len(etanercept_items)}: "
        f"{[i.item_id for i in etanercept_items]}"
    )


def test_section9_row85_table_preserved(fixture_section_9):
    """The §9 / 9.69. drug × indication table must survive parsing and chunking
    as a real Markdown table — no Google Docs roundtrip required."""
    doc = parse_docx(_source(fixture_section_9))
    items = chunk_document(doc)
    assert all(i.token_count <= HARD_BUDGET for i in items)

    section_969_items = [i for i in items if "9.69" in i.item_id]
    assert section_969_items, "no items found under 9.69."

    drug_names = ["pembrolizumab", "nivolumab", "atezolizumab"]
    table_items = [
        i for i in section_969_items
        if "|" in i.content_md
        and all(d in i.content_md for d in drug_names)
    ]
    assert table_items, (
        "Expected at least one §9.69 item to contain a Markdown table with columns "
        f"{drug_names}. Got item content samples: "
        + " || ".join(i.content_md[:100] for i in section_969_items[:3])
    )


def test_all_fixtures_fit_budget(fixture_section_3, fixture_section_8, fixture_section_9):
    """Property test: across all fixtures, every emitted item fits HARD_BUDGET
    and all item_ids are unique within a document."""
    for p in [fixture_section_3, fixture_section_8, fixture_section_9]:
        doc = parse_docx(_source(p))
        items = chunk_document(doc)
        ids = [i.item_id for i in items]
        assert len(ids) == len(set(ids)), f"duplicate item_id in {p.name}: {ids}"
        assert all(i.token_count <= HARD_BUDGET for i in items), (
            f"{p.name} has over-budget items"
        )
