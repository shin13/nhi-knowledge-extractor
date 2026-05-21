from nhi_extractor.diff import DiffResult, compute_diff


def _entry(item_id, hash_, path="9.docx", tokens=100):
    return {
        "item_id": item_id, "content_sha256": hash_,
        "source_file": path, "token_count": tokens,
        "section_path": "第9節 > " + item_id,
    }


def test_diff_added_only():
    result = compute_diff(old=[], new=[_entry("a", "h1"), _entry("b", "h2")])
    assert result.added == ["a", "b"]
    assert result.removed == []
    assert result.modified == []


def test_diff_removed_only():
    result = compute_diff(old=[_entry("a", "h1")], new=[])
    assert result.removed == ["a"]


def test_diff_modified_content_hash():
    result = compute_diff(
        old=[_entry("a", "h1")],
        new=[_entry("a", "h2")],
    )
    assert result.modified == ["a"]
    assert result.added == []
    assert result.removed == []


def test_diff_no_change():
    e = _entry("a", "h1")
    result = compute_diff(old=[e], new=[e])
    assert result.added == result.removed == result.modified == []


def test_diff_to_markdown_initial_release():
    result = DiffResult(added=["sec9-9.1", "sec9-9.2"], removed=[], modified=[], initial=True)
    md = result.to_markdown(release_label="20260521", iso_date="2026/05/21", roc_date="民國115年5月21日")
    assert "**Initial release.**" in md
    assert "sec9-9.1" in md
    assert "sec9-9.2" in md


def test_diff_to_markdown_normal_release():
    entries_new = {"a": "第9節 > 9.1.", "b": "第9節 > 9.2."}
    entries_old = {"c": "第9節 > 9.3."}
    md = DiffResult(
        added=["a", "b"], removed=["c"], modified=[],
        added_paths=entries_new, removed_paths=entries_old, modified_paths={},
    ).to_markdown(release_label="20260521", iso_date="2026/05/21", roc_date="民國115年5月21日")
    assert "## [20260521]" in md
    assert "### Added" in md
    assert "### Removed" in md
    assert "### Modified" not in md  # no empty section
