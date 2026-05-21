"""Download DOCX files + release update date from the NHI source page."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import cloudscraper
from bs4 import BeautifulSoup

from .config import (
    CHAPTERS_DIR, DOCX_LINK_PATTERN, SOURCE_URL, UPDATE_DATE_SELECTOR,
)
from .types import Manifest, SourceDoc


@dataclass(frozen=True)
class _Link:
    url: str
    display_name: str


def _parse_update_date(soup: BeautifulSoup) -> date | None:
    el = soup.select_one(UPDATE_DATE_SELECTOR)
    if not el or not el.text.strip():
        return None
    txt = el.text.strip()
    # ROC year-mm-dd (e.g. "115-03-24")
    m = re.search(r"(\d{2,3})[-/](\d{1,2})[-/](\d{1,2})", txt)
    if not m:
        return None
    roc_year, mo, da = (int(x) for x in m.groups())
    return date(roc_year + 1911, mo, da)


def parse_listing(html: str, *, base_url: str) -> tuple[list[_Link], date]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[_Link] = []
    pattern = re.compile(DOCX_LINK_PATTERN)
    for a in soup.find_all("a", href=pattern):
        href = a.get("href")
        title = a.get("title") or a.text.strip() or "Unknown"
        if href:
            links.append(_Link(url=urljoin(base_url, href), display_name=title))
    update_date = _parse_update_date(soup)
    if update_date is None:
        raise RuntimeError("Could not parse website update date — page structure changed?")
    return links, update_date


def _safe_filename(display_name: str, update_date: date) -> str:
    name = re.sub(r"\.docx$", "", display_name, flags=re.IGNORECASE)
    name = re.sub(r"[^\w\.\-一-鿿]", "_", name).strip("._")
    roc = update_date.year - 1911
    suffix = f"_{roc}{update_date.month:02d}{update_date.day:02d}"
    return f"{name}{suffix}.docx"


def fetch_all(*, download_dir: Path = CHAPTERS_DIR, source_url: str = SOURCE_URL) -> Manifest:
    """Download all DOCX from the listing page. Returns a Manifest."""
    download_dir.mkdir(parents=True, exist_ok=True)
    session = cloudscraper.create_scraper()
    resp = session.get(source_url)
    resp.raise_for_status()
    links, update_date = parse_listing(resp.text, base_url=source_url)

    docs: list[SourceDoc] = []
    for link in links:
        fname = _safe_filename(link.display_name, update_date)
        out_path = download_dir / fname
        if not out_path.exists():
            r = session.get(link.url, stream=True)
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
        docs.append(SourceDoc(
            path=out_path, url=link.url,
            display_name=link.display_name, update_date_iso=update_date,
        ))
    return Manifest(update_date_iso=update_date, documents=tuple(docs))
