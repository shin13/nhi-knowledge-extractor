from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nhi_extractor.fetch import (
    DocLinks,
    _convert_odt_to_docx,
    _find_soffice,
    classify_document,
    parse_listing,
)


FIXTURE = Path(__file__).parent / "fixtures" / "listing_page.html"
BASE_URL = "https://www.nhi.gov.tw/ch/cp-7593-ad2a9-3397-1.html"


# --- parse_listing -----------------------------------------------------------

def test_parse_listing_groups_by_title_across_formats():
    html = FIXTURE.read_text(encoding="utf-8")
    docs, update_date = parse_listing(html, base_url=BASE_URL)

    assert len(docs) > 40, f"expected many documents, got {len(docs)}"
    assert update_date.year >= 2024
    # Every doc should carry at least one URL
    for d in docs:
        assert d.docx_url or d.odt_url or d.pdf_url, f"doc {d.title!r} has no URLs"
    # Titles should NOT contain file extensions
    for d in docs:
        assert ".docx" not in d.title and ".odt" not in d.title and ".pdf" not in d.title


def test_parse_listing_finds_odt_only_regulations():
    """通則 and 第六節 are published only as .doc/.odt/.pdf — fetcher must see them via ODT."""
    html = FIXTURE.read_text(encoding="utf-8")
    docs, _ = parse_listing(html, base_url=BASE_URL)
    by_title = {d.title: d for d in docs}

    tongze = next((d for t, d in by_title.items() if t.startswith("通則")), None)
    assert tongze is not None, f"通則 missing from parsed listing; titles: {list(by_title)[:5]}..."
    assert tongze.docx_url is None
    assert tongze.odt_url is not None

    sec6 = next((d for t, d in by_title.items() if t.startswith("第六節")), None)
    assert sec6 is not None, "第六節 missing from parsed listing"
    assert sec6.docx_url is None
    assert sec6.odt_url is not None


def test_parse_listing_keeps_docx_when_available():
    """Documents with native .docx must still expose docx_url."""
    html = FIXTURE.read_text(encoding="utf-8")
    docs, _ = parse_listing(html, base_url=BASE_URL)
    with_docx = [d for d in docs if d.docx_url]
    assert len(with_docx) >= 30, f"expected ≥30 docs with docx, got {len(with_docx)}"


# --- classify_document -------------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("通則", "regulation"),
    ("通則(113.05.28更新)", "regulation"),
    ("第一節 全身性抗感染劑", "regulation"),
    ("第六節 呼吸道藥物(115.3.23更新)", "regulation"),
    ("第十一節 解毒劑", "regulation"),
    ("第十五節 婦科製劑(114.07.24更新)", "regulation"),
    ("附表一：全民健康保險醫療常用第一線抗微生物製劑品名表", "appendix_form"),
    ("附表二-D：使用健保給付PCSK9血脂調節劑事前審查申請表(114.08.22更新)", "appendix_form"),
    ("附表十三", "appendix_form"),
    ("藥品事前審查申請表（空白表格）", "unrecognized_title"),
    ("某個未知文件", "unrecognized_title"),
])
def test_classify_document(title, expected):
    assert classify_document(title) == expected


# --- LibreOffice integration -------------------------------------------------

def test_find_soffice_raises_with_install_hint(monkeypatch):
    """When LibreOffice is missing, error must tell the user how to install it."""
    monkeypatch.setattr("nhi_extractor.fetch.shutil.which", lambda _name: None)
    monkeypatch.setattr("nhi_extractor.fetch.Path.exists", lambda _self: False)
    with pytest.raises(RuntimeError, match="brew install --cask libreoffice"):
        _find_soffice()


def test_convert_odt_to_docx_invokes_libreoffice(tmp_path, monkeypatch):
    odt = tmp_path / "doc.odt"
    odt.write_bytes(b"fake odt")
    expected_docx = tmp_path / "doc.docx"

    monkeypatch.setattr("nhi_extractor.fetch._find_soffice", lambda: "/fake/soffice")

    def fake_run(cmd, **kwargs):
        # Simulate LibreOffice creating the .docx
        expected_docx.write_bytes(b"fake converted docx")
        return MagicMock(returncode=0, stderr="")

    monkeypatch.setattr("nhi_extractor.fetch.subprocess.run", fake_run)
    result = _convert_odt_to_docx(odt)
    assert result == expected_docx
    assert result.exists()


def test_fetch_all_records_skipped_appendix_forms(tmp_path, monkeypatch):
    """Appendix forms must be in skipped_documents, not silently dropped."""
    html = FIXTURE.read_text(encoding="utf-8")

    # Fake cloudscraper session: returns the fixture HTML for the listing,
    # arbitrary bytes for any downloaded file.
    fake_session = MagicMock()
    listing_resp = MagicMock(text=html)
    listing_resp.raise_for_status = MagicMock()
    download_resp = MagicMock()
    download_resp.raise_for_status = MagicMock()
    download_resp.iter_content = lambda _n: [b"fake docx bytes"]
    fake_session.get = MagicMock(side_effect=lambda url, **kw: listing_resp if url.endswith(".html") else download_resp)
    monkeypatch.setattr("nhi_extractor.fetch.cloudscraper.create_scraper", lambda: fake_session)

    # Fake LibreOffice: pretend it's there and just rename .odt → .docx
    monkeypatch.setattr("nhi_extractor.fetch._find_soffice", lambda: "/fake/soffice")

    def fake_run(cmd, **kwargs):
        odt_path = Path(cmd[-1])
        odt_path.with_suffix(".docx").write_bytes(b"fake converted")
        return MagicMock(returncode=0, stderr="")
    monkeypatch.setattr("nhi_extractor.fetch.subprocess.run", fake_run)

    from nhi_extractor.fetch import fetch_all
    manifest = fetch_all(download_dir=tmp_path)

    # 通則 + 第N節 must be downloaded
    titles = {d.display_name for d in manifest.documents}
    assert any(t.startswith("通則") for t in titles), f"通則 not in documents: {sorted(titles)[:5]}"
    assert any(t.startswith("第六節") for t in titles), "第六節 not in documents"

    # 附表 must be in skipped, with reason
    appendix_skipped = [s for s in manifest.skipped_documents if s.reason == "appendix_form"]
    assert len(appendix_skipped) >= 20, f"expected many appendix forms skipped, got {len(appendix_skipped)}"
    for s in appendix_skipped:
        assert s.title.startswith("附表")
        assert s.url


def test_convert_odt_to_docx_raises_when_libreoffice_fails(tmp_path, monkeypatch):
    odt = tmp_path / "doc.odt"
    odt.write_bytes(b"fake")
    monkeypatch.setattr("nhi_extractor.fetch._find_soffice", lambda: "/fake/soffice")
    monkeypatch.setattr(
        "nhi_extractor.fetch.subprocess.run",
        lambda *a, **kw: MagicMock(returncode=1, stderr="conversion broken"),
    )
    with pytest.raises(RuntimeError, match="LibreOffice conversion failed"):
        _convert_odt_to_docx(odt)
