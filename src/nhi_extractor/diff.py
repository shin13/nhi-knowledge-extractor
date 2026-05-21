"""Compare two MANIFEST.json entry lists and emit a release-diff report."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DiffResult:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    initial: bool = False
    added_paths: dict[str, str] = field(default_factory=dict)
    removed_paths: dict[str, str] = field(default_factory=dict)
    modified_paths: dict[str, str] = field(default_factory=dict)

    def to_markdown(self, *, release_label: str, iso_date: str, roc_date: str,
                    summary: str | None = None) -> str:
        lines: list[str] = [f"## [{release_label}] — {iso_date}（{roc_date}）"]
        if self.initial:
            lines.append("**Initial release.**")
        if summary:
            lines.append(summary)
        lines.append("")

        def _section(title: str, ids: list[str], paths: dict[str, str]):
            if not ids:
                return
            lines.append(f"### {title}")
            for i in ids:
                p = paths.get(i, "")
                if p:
                    lines.append(f"- `{i}` — {p}")
                else:
                    lines.append(f"- `{i}`")
            lines.append("")

        _section("Added", self.added, self.added_paths)
        _section("Modified", self.modified, self.modified_paths)
        _section("Removed", self.removed, self.removed_paths)
        return "\n".join(lines).rstrip() + "\n"


def compute_diff(*, old: list[dict], new: list[dict]) -> DiffResult:
    """`old` and `new` are lists of manifest entries (each a dict with
    'item_id', 'content_sha256', and optionally 'section_path')."""
    old_map = {e["item_id"]: e for e in old}
    new_map = {e["item_id"]: e for e in new}
    added_ids = sorted(set(new_map) - set(old_map))
    removed_ids = sorted(set(old_map) - set(new_map))
    common = set(old_map) & set(new_map)
    modified_ids = sorted(
        i for i in common if old_map[i]["content_sha256"] != new_map[i]["content_sha256"]
    )

    initial = not old

    return DiffResult(
        added=added_ids,
        removed=removed_ids,
        modified=modified_ids,
        initial=initial,
        added_paths={i: new_map[i].get("section_path", "") for i in added_ids},
        removed_paths={i: old_map[i].get("section_path", "") for i in removed_ids},
        modified_paths={i: new_map[i].get("section_path", "") for i in modified_ids},
    )
