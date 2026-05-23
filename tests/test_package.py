import csv
import json
import zipfile
from datetime import date
from pathlib import Path

from nhi_extractor.package import build_release
from nhi_extractor.types import Item, SourceDoc


def _make_item(source: SourceDoc, item_id: str, heading: str, content: str) -> Item:
    return Item(
        item_id=item_id,
        section_path=["第9節 抗癌瘤藥物", heading],
        heading=heading,
        content_md=content,
        source=source,
        token_count=len(content),
    )


def test_build_release_creates_csv_manifest_changes_and_zip(tmp_path):
    sd1 = SourceDoc(
        path=Path("第9節_抗癌瘤藥物.docx"), url="https://x/9.docx",
        display_name="第9節抗癌瘤藥物", update_date_iso=date(2026, 5, 22),
    )
    items = [
        _make_item(sd1, "sec9-9.1", "9.1.", "## 9.1.\n\n內容一"),
        _make_item(sd1, "sec9-9.2", "9.2.", "## 9.2.\n\n內容二"),
    ]
    data_dir = tmp_path / "data" / "regulations" / "medication"
    changelog = tmp_path / "CHANGELOG.md"

    result = build_release(
        items=items,
        release_date=date(2026, 5, 22),
        data_dir=data_dir,
        changelog_path=changelog,
    )

    folder = data_dir / "藥品給付規定_20260522"
    assert folder.is_dir()
    assert (folder / "MANIFEST.json").exists()
    assert (folder / "CHANGES_20260522.md").exists()

    csvs = list(folder.glob("*.csv"))
    assert len(csvs) == 1
    with csvs[0].open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        assert set(reader.fieldnames) == {
            "topic", "content", "heading", "section_path",
            "item_id", "parent_id", "part_index", "total_parts",
            "source_file", "source_url", "update_date",
        }
        rows = list(reader)
        assert len(rows) == 2

    manifest = json.loads((folder / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["release_date"] == "2026-05-22"
    assert len(manifest["items"]) == 2
    assert all("content_sha256" in e for e in manifest["items"])
    assert all("token_count" in e for e in manifest["items"])

    zip_path = data_dir / "藥品給付規定_20260522.zip"
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert any(n.endswith("MANIFEST.json") for n in names)
        assert any(n.endswith("CHANGES_20260522.md") for n in names)
        assert any(n.endswith(".csv") for n in names)

    assert changelog.exists()
    text = changelog.read_text(encoding="utf-8")
    assert "[20260522]" in text
    assert "**Initial release.**" in text
    assert result.release_folder == folder
    assert result.zip_path == zip_path


def test_build_release_diff_against_prior(tmp_path):
    data_dir = tmp_path / "data" / "regulations" / "medication"
    changelog = tmp_path / "CHANGELOG.md"
    sd = SourceDoc(
        path=Path("第9節_抗癌瘤藥物.docx"), url="https://x/9.docx",
        display_name="第9節抗癌瘤藥物", update_date_iso=date(2026, 5, 22),
    )

    build_release(
        items=[_make_item(sd, "sec9-9.1", "9.1.", "old content")],
        release_date=date(2026, 4, 24),
        data_dir=data_dir, changelog_path=changelog,
    )

    build_release(
        items=[
            _make_item(sd, "sec9-9.1", "9.1.", "new content (modified)"),
            _make_item(sd, "sec9-9.2", "9.2.", "freshly added"),
        ],
        release_date=date(2026, 5, 22),
        data_dir=data_dir, changelog_path=changelog,
    )

    changes = (data_dir / "藥品給付規定_20260522" / "CHANGES_20260522.md").read_text(encoding="utf-8")
    assert "### Added" in changes and "sec9-9.2" in changes
    assert "### Modified" in changes and "sec9-9.1" in changes

    log = changelog.read_text(encoding="utf-8")
    assert log.index("[20260522]") < log.index("[20260424]")


# --- Task H: same-date re-run must replace, not duplicate --------------------

def test_build_release_same_date_replaces_existing_changelog_entry(tmp_path):
    """Running build_release twice for the SAME release_date must leave the
    CHANGELOG with exactly one entry for that date, reflecting the SECOND run's
    items. Previously _prepend_changelog blindly inserted before the first
    '## [' heading, producing duplicate dated headers per re-run."""
    data_dir = tmp_path / "data" / "regulations" / "medication"
    changelog = tmp_path / "CHANGELOG.md"
    sd = SourceDoc(
        path=Path("第9節_抗癌瘤藥物.docx"), url="https://x/9.docx",
        display_name="第9節抗癌瘤藥物", update_date_iso=date(2026, 4, 24),
    )

    # First run
    build_release(
        items=[_make_item(sd, "sec9-9.1", "9.1.", "first-run content")],
        release_date=date(2026, 4, 24),
        data_dir=data_dir, changelog_path=changelog,
    )
    # Second run, same date, different items
    build_release(
        items=[
            _make_item(sd, "sec9-9.1", "9.1.", "second-run content (revised)"),
            _make_item(sd, "sec9-9.2", "9.2.", "second-run added"),
        ],
        release_date=date(2026, 4, 24),
        data_dir=data_dir, changelog_path=changelog,
    )

    text = changelog.read_text(encoding="utf-8")
    # Exactly one header for the date.
    assert text.count("## [20260424]") == 1, (
        f"expected exactly one [20260424] header after same-date re-run, "
        f"got {text.count('## [20260424]')}; CHANGELOG:\n{text}"
    )
    # And it carries the SECOND run's payload (sec9-9.2 only existed there).
    assert "sec9-9.2" in text


def test_build_release_different_dates_still_prepend(tmp_path):
    """The same-date-replace fix must NOT regress the normal multi-date case —
    newer dates should still be prepended in front of older ones."""
    data_dir = tmp_path / "data" / "regulations" / "medication"
    changelog = tmp_path / "CHANGELOG.md"
    sd = SourceDoc(
        path=Path("第9節_抗癌瘤藥物.docx"), url="https://x/9.docx",
        display_name="第9節抗癌瘤藥物", update_date_iso=date(2026, 4, 24),
    )

    build_release(items=[_make_item(sd, "sec9-9.1", "9.1.", "april")],
                  release_date=date(2026, 4, 24),
                  data_dir=data_dir, changelog_path=changelog)
    build_release(items=[_make_item(sd, "sec9-9.1", "9.1.", "may")],
                  release_date=date(2026, 5, 22),
                  data_dir=data_dir, changelog_path=changelog)
    build_release(items=[_make_item(sd, "sec9-9.1", "9.1.", "june")],
                  release_date=date(2026, 6, 24),
                  data_dir=data_dir, changelog_path=changelog)

    text = changelog.read_text(encoding="utf-8")
    assert text.count("## [20260424]") == 1
    assert text.count("## [20260522]") == 1
    assert text.count("## [20260624]") == 1
    # Newest first.
    assert text.index("[20260624]") < text.index("[20260522]") < text.index("[20260424]")
