"""Package stage: render Items into CSVs, write MANIFEST.json + CHANGES_*.md,
prepend CHANGELOG.md, zip the release folder."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .diff import DiffResult, compute_diff
from .render import render
from .types import Item

CSV_FIELDS = [
    "topic", "content", "heading", "section_path",
    "item_id", "source_file", "source_url", "update_date",
]


@dataclass(frozen=True)
class BuildResult:
    release_folder: Path
    zip_path: Path
    changelog_path: Path
    diff: DiffResult


def _release_label(d: date) -> str:
    return f"{d.year}{d.month:02d}{d.day:02d}"


def _items_to_manifest_entries(items: list[Item]) -> list[dict]:
    entries: list[dict] = []
    for it in items:
        h = hashlib.sha256(it.content_md.encode("utf-8")).hexdigest()
        entries.append({
            "item_id": it.item_id,
            "content_sha256": h,
            "section_path": " > ".join(it.section_path),
            "source_file": it.source.path.name,
            "token_count": it.token_count,
        })
    return entries


def _find_prior_manifest(data_dir: Path, exclude_label: str) -> list[dict]:
    """Find the most recent prior release (by folder name sort) and return its manifest entries.
    Returns [] if none."""
    candidates: list[Path] = []
    if data_dir.exists():
        for child in data_dir.iterdir():
            if not child.is_dir():
                continue
            m = re.match(r"藥品給付規定_(\d{8})$", child.name)
            if not m or m.group(1) == exclude_label:
                continue
            manifest = child / "MANIFEST.json"
            if manifest.exists():
                candidates.append(child)
    if not candidates:
        return []
    candidates.sort(key=lambda p: p.name, reverse=True)
    return json.loads((candidates[0] / "MANIFEST.json").read_text(encoding="utf-8"))["items"]


def _write_csvs(items: list[Item], folder: Path) -> list[Path]:
    """Group items by source filename → one CSV each."""
    groups: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        groups[it.source.path.stem].append(it)
    written: list[Path] = []
    for stem, group in groups.items():
        path = folder / f"{stem}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for it in group:
                writer.writerow(render(it))
        written.append(path)
    return written


def _zip_folder(folder: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in folder.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=path.relative_to(folder.parent))


def _prepend_changelog(changelog_path: Path, section_md: str) -> None:
    if changelog_path.exists():
        existing = changelog_path.read_text(encoding="utf-8")
    else:
        existing = "# Changelog\n\n"
    m = re.search(r"^## \[", existing, flags=re.MULTILINE)
    if m:
        new = existing[: m.start()] + section_md + "\n" + existing[m.start():]
    else:
        new = existing.rstrip() + "\n\n" + section_md
    changelog_path.write_text(new, encoding="utf-8")


def build_release(
    *,
    items: list[Item],
    release_date: date,
    data_dir: Path,
    changelog_path: Path,
    skipped_documents: tuple = (),
) -> BuildResult:
    label = _release_label(release_date)
    folder = data_dir / f"藥品給付規定_{label}"
    folder.mkdir(parents=True, exist_ok=True)

    # 1. CSVs
    _write_csvs(items, folder)

    # 2. MANIFEST.json
    new_entries = _items_to_manifest_entries(items)
    manifest_obj = {
        "release_date": release_date.isoformat(),
        "item_count": len(new_entries),
        "items": new_entries,
        "skipped_documents": [
            {"title": s.title, "url": s.url, "reason": s.reason}
            for s in skipped_documents
        ],
    }
    (folder / "MANIFEST.json").write_text(
        json.dumps(manifest_obj, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    # 3. Diff vs prior
    prior_entries = _find_prior_manifest(data_dir, exclude_label=label)
    diff = compute_diff(old=prior_entries, new=new_entries)

    iso_date = f"{release_date.year}/{release_date.month:02d}/{release_date.day:02d}"
    roc_date = f"民國{release_date.year - 1911}年{release_date.month}月{release_date.day}日"
    max_tokens = max((e["token_count"] for e in new_entries), default=0)
    summary = (
        f"**Source manifest:** {len({e['source_file'] for e in new_entries})} documents, "
        f"{len(new_entries)} items emitted, max token count {max_tokens}."
    )
    diff_md = diff.to_markdown(
        release_label=label, iso_date=iso_date, roc_date=roc_date, summary=summary,
    )

    # 4. CHANGES_YYYYMMDD.md inside release folder
    (folder / f"CHANGES_{label}.md").write_text(diff_md, encoding="utf-8")

    # 5. CHANGELOG.md prepend
    _prepend_changelog(changelog_path, diff_md)

    # 6. Zip
    zip_path = data_dir / f"藥品給付規定_{label}.zip"
    if zip_path.exists():
        zip_path.unlink()
    _zip_folder(folder, zip_path)

    return BuildResult(
        release_folder=folder, zip_path=zip_path,
        changelog_path=changelog_path, diff=diff,
    )
