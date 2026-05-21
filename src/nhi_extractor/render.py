"""Item -> CSV row (dict). Pure field mapping per spec §5.3."""

from __future__ import annotations

from datetime import date

from .config import SECTION_PATH_SEPARATOR, TOPIC_PREFIX
from .types import Item


def format_dual_calendar(d: date) -> str:
    """e.g. date(2026,3,24) -> '2026/03/24 (民國115年3月24日)'.
    Western part is zero-padded; ROC part is not (matches NHI's own style)."""
    roc_year = d.year - 1911
    western = f"{d.year}/{d.month:02d}/{d.day:02d}"
    roc = f"民國{roc_year}年{d.month}月{d.day}日"
    return f"{western} ({roc})"


def render(item: Item) -> dict[str, str]:
    breadcrumb = SECTION_PATH_SEPARATOR.join(item.section_path)
    return {
        "topic": TOPIC_PREFIX + breadcrumb,
        "content": item.content_md,
        "heading": item.heading,
        "section_path": breadcrumb,
        "item_id": item.item_id,
        "source_file": item.source.path.name,
        "source_url": item.source.url,
        "update_date": format_dual_calendar(item.source.update_date_iso),
    }
