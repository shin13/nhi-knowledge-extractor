"""`--skip-fetch` release selection.

`CHAPTERS_DIR` accumulates every release ever downloaded, so a caller that
globs it directly gets every release at once. That is not a cosmetic problem:
item_ids are unique per document, and `chunk_document`'s collision guard runs
per document, so a mixed-release corpus emits duplicate item_ids with no error
and breaks the diff stability the whole schema depends on.
"""

from datetime import date

import pytest

from nhi_extractor.fetch import latest_local_release, parse_release_stamp


def _touch(directory, *names):
    for n in names:
        (directory / n).write_bytes(b"")


# --- parse_release_stamp -----------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("第一節_神經系統藥物_115.8.21更新_1150821.docx", date(2026, 8, 21)),
    ("通則_113.05.28更新_1150821.odt", date(2026, 8, 21)),
    ("第十節_抗微生物劑_114.11.20更新_1150424.docx", date(2026, 4, 24)),
    # The in-title update date is NOT the release stamp — only the trailing one is.
    ("第七節_腸胃藥物_114.07.24更新_1150727.docx", date(2026, 7, 27)),
    ("section_3_normal.docx", None),
    ("第三節_代謝及營養劑(114.05.23更新).docx", None),
    ("bogus_1159999.docx", None),
])
def test_parse_release_stamp(tmp_path, name, expected):
    assert parse_release_stamp(tmp_path / name) == expected


# --- latest_local_release ----------------------------------------------------

def test_picks_only_the_newest_release(tmp_path):
    _touch(tmp_path,
           "第一節_x_1150724.docx", "第二節_x_1150724.docx",
           "第一節_x_1150821.docx", "第二節_x_1150821.docx")

    rel = latest_local_release(tmp_path)

    assert rel.update_date == date(2026, 8, 21)
    assert [p.name for p in rel.paths] == ["第一節_x_1150821.docx", "第二節_x_1150821.docx"]
    assert len(rel.superseded) == 2, "older releases must be reported, not silently dropped"


def test_includes_odt_chapters(tmp_path):
    """通則 / 第六節 / 第十一節 / 第十二節 / 第十五節 are published ODT-only.
    A .docx-only glob drops 5 of the 16 in-scope documents without a word."""
    _touch(tmp_path, "第一節_x_1150821.docx", "通則_x_1150821.odt", "第六節_x_1150821.odt")

    rel = latest_local_release(tmp_path)

    assert {p.suffix for p in rel.paths} == {".docx", ".odt"}
    assert len(rel.paths) == 3


def test_ignores_unrelated_files(tmp_path):
    _touch(tmp_path, "第一節_x_1150821.docx", "notes.txt", "MANIFEST.json", ".DS_Store")

    rel = latest_local_release(tmp_path)

    assert [p.name for p in rel.paths] == ["第一節_x_1150821.docx"]


def test_unstamped_directory_is_treated_as_one_batch(tmp_path):
    """A hand-assembled directory (e.g. the test fixtures) has no release stamps.
    It must still work — just with no release date to recover."""
    _touch(tmp_path, "section_3_normal.docx", "tongze.odt")

    rel = latest_local_release(tmp_path)

    assert rel.update_date is None, "an unstamped batch has no knowable release date"
    assert len(rel.paths) == 2
    assert rel.superseded == ()


def test_stamped_files_win_over_unstamped(tmp_path):
    _touch(tmp_path, "第一節_x_1150821.docx", "hand_placed.docx")

    rel = latest_local_release(tmp_path)

    assert [p.name for p in rel.paths] == ["第一節_x_1150821.docx"]
    assert [p.name for p in rel.superseded] == ["hand_placed.docx"]


def test_empty_directory_raises_with_the_path_named(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        latest_local_release(tmp_path)
    assert str(tmp_path) in str(exc.value)
