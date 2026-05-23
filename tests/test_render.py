from datetime import date
from pathlib import Path

from nhi_extractor.render import format_dual_calendar, render
from nhi_extractor.types import Item, SourceDoc


def test_format_dual_calendar():
    assert format_dual_calendar(date(2026, 3, 24)) == "2026/03/24 (民國115年3月24日)"


def test_format_dual_calendar_single_digit_padding():
    assert format_dual_calendar(date(2026, 1, 5)) == "2026/01/05 (民國115年1月5日)"


def test_render_produces_all_eleven_columns():
    sd = SourceDoc(
        path=Path("/x/第9節_抗癌瘤藥物_1150324.docx"),
        url="https://www.nhi.gov.tw/.../9.docx",
        display_name="第9節抗癌瘤藥物",
        update_date_iso=date(2026, 3, 24),
    )
    item = Item(
        item_id="sec9-9.69.1",
        section_path=["第9節 抗癌瘤藥物", "9.69. 免疫檢查點抑制劑", "9.69.1. PD-L1"],
        heading="9.69.1. PD-L1",
        content_md="## 9.69.1. PD-L1\n\n適應症說明……",
        source=sd,
        token_count=420,
        parent_id="sec9-9.69.1",
        part_index=1,
        total_parts=1,
    )
    row = render(item)
    assert set(row.keys()) == {
        "topic", "content", "heading", "section_path",
        "item_id", "parent_id", "part_index", "total_parts",
        "source_file", "source_url", "update_date",
    }
    assert row["topic"].startswith("臺灣全民健康保險藥品給付規定/")
    assert "第9節 抗癌瘤藥物 > 9.69. 免疫檢查點抑制劑 > 9.69.1. PD-L1" in row["topic"]
    assert row["item_id"] == "sec9-9.69.1"
    assert row["parent_id"] == "sec9-9.69.1"
    assert row["part_index"] == "1"
    assert row["total_parts"] == "1"
    assert row["source_file"] == "第9節_抗癌瘤藥物_1150324.docx"
    assert row["update_date"] == "2026/03/24 (民國115年3月24日)"
    assert row["section_path"] == "第9節 抗癌瘤藥物 > 9.69. 免疫檢查點抑制劑 > 9.69.1. PD-L1"


def test_render_default_item_metadata_uses_item_id_as_parent():
    """Items constructed without explicit metadata get parent_id=item_id fallback in render."""
    sd = SourceDoc(path=Path("/x/t.docx"), url="", display_name="t",
                   update_date_iso=date(2026, 3, 24))
    # Use defaults — parent_id="" by default
    item = Item(item_id="sec1-1", section_path=["a"], heading="h",
                content_md="c", source=sd, token_count=10)
    row = render(item)
    assert row["parent_id"] == "sec1-1"  # falls back to item_id when empty
