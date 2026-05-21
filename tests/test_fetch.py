from pathlib import Path

from nhi_extractor.fetch import parse_listing


def test_parse_listing_finds_docx_links_and_update_date(tmp_path):
    html = (Path(__file__).parent / "fixtures" / "listing_page.html").read_text(encoding="utf-8")
    links, update_date_iso = parse_listing(html, base_url="https://www.nhi.gov.tw/ch/cp-7593-ad2a9-3397-1.html")
    assert len(links) > 5, "expected at least a few DOCX links on the NHI page"
    for link in links:
        assert link.url.endswith(".docx")
        assert link.display_name
    assert update_date_iso.year >= 2024
