"""Download NHI medication-regulation source documents.

Strategy:

1. Group listing-page links by document title (extension stripped), not by href.
2. Classify each title: `regulation` (通則 + 第N節) → in-scope; `appendix_form` (附表)
   → recorded but not downloaded; anything else → recorded as `unrecognized_title`.
3. For regulations, prefer `.docx`; fall back to `.odt` (parsed natively, no
   external conversion needed — see parse.parse_odt).

No external binary dependencies — `uv sync` is sufficient.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import cloudscraper
from bs4 import BeautifulSoup

from .config import (
    APPENDIX_FORM_TITLE_PATTERN,
    CHAPTERS_DIR,
    REGULATION_TITLE_PATTERN,
    SOURCE_URL,
    UPDATE_DATE_SELECTOR,
)
from .types import Manifest, SkippedDoc, SourceDoc


# --- Listing parse -----------------------------------------------------------

@dataclass(frozen=True)
class DocLinks:
    """All format URLs found on the listing page for one document title."""
    title: str                  # canonical title, extension stripped
    docx_url: str | None = None
    odt_url: str | None = None
    pdf_url: str | None = None


_EXT_RE = re.compile(r"\.(docx|doc|odt|pdf)\b", re.IGNORECASE)


def _strip_ext(title: str) -> str:
    return _EXT_RE.sub("", title).strip()


def _parse_update_date(soup: BeautifulSoup) -> date | None:
    el = soup.select_one(UPDATE_DATE_SELECTOR)
    if not el or not el.text.strip():
        return None
    txt = el.text.strip()
    m = re.search(r"(\d{2,3})[-/](\d{1,2})[-/](\d{1,2})", txt)
    if not m:
        return None
    roc_year, mo, da = (int(x) for x in m.groups())
    return date(roc_year + 1911, mo, da)


def parse_listing(html: str, *, base_url: str) -> tuple[list[DocLinks], date]:
    """Group <a> tags by document title and collect every available format URL."""
    soup = BeautifulSoup(html, "html.parser")
    groups: dict[str, dict[str, str]] = {}
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        title_attr = (a.get("title") or "").strip()
        # Detect extension from title (preferred) or href
        m = _EXT_RE.search(title_attr) or _EXT_RE.search(href)
        if not m:
            continue
        ext = m.group(1).lower()
        if ext not in ("docx", "odt", "pdf"):
            continue  # skip legacy .doc — every .doc doc also has .odt
        canonical_title = _strip_ext(title_attr) if title_attr else _strip_ext(href.rsplit("/", 1)[-1])
        if not canonical_title:
            continue
        groups.setdefault(canonical_title, {}).setdefault(ext, urljoin(base_url, href))

    docs = [
        DocLinks(
            title=title,
            docx_url=urls.get("docx"),
            odt_url=urls.get("odt"),
            pdf_url=urls.get("pdf"),
        )
        for title, urls in groups.items()
    ]

    update_date = _parse_update_date(soup)
    if update_date is None:
        raise RuntimeError("Could not parse website update date — page structure changed?")
    return docs, update_date


# --- Classification ----------------------------------------------------------

def classify_document(title: str) -> str:
    """Return 'regulation' | 'appendix_form' | 'unrecognized_title'."""
    if re.match(REGULATION_TITLE_PATTERN, title):
        return "regulation"
    if re.match(APPENDIX_FORM_TITLE_PATTERN, title):
        return "appendix_form"
    return "unrecognized_title"


# --- Filename + download -----------------------------------------------------

def _safe_filename(title: str, update_date: date, ext: str) -> str:
    name = re.sub(r"[^\w\.\-一-鿿]", "_", title).strip("._")
    roc = update_date.year - 1911
    suffix = f"_{roc}{update_date.month:02d}{update_date.day:02d}"
    return f"{name}{suffix}.{ext}"


def _download(session, url: str, out_path: Path) -> None:
    if out_path.exists():
        return
    r = session.get(url, stream=True)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)


# --- Top-level orchestration -------------------------------------------------

def fetch_all(
    *,
    download_dir: Path = CHAPTERS_DIR,
    source_url: str = SOURCE_URL,
) -> Manifest:
    """Download all in-scope regulation documents. Returns a Manifest.

    Out-of-scope documents (附表 forms, unrecognized titles, PDF-only regulations)
    are not downloaded but are recorded in `manifest.skipped_documents`.
    """
    download_dir.mkdir(parents=True, exist_ok=True)
    session = cloudscraper.create_scraper()
    resp = session.get(source_url)
    resp.raise_for_status()
    docs, update_date = parse_listing(resp.text, base_url=source_url)

    sources: list[SourceDoc] = []
    skipped: list[SkippedDoc] = []

    for d in docs:
        kind = classify_document(d.title)

        if kind == "appendix_form":
            skipped.append(SkippedDoc(
                title=d.title,
                url=d.docx_url or d.odt_url or d.pdf_url or "",
                reason="appendix_form",
            ))
            continue

        if kind == "unrecognized_title":
            skipped.append(SkippedDoc(
                title=d.title,
                url=d.docx_url or d.odt_url or d.pdf_url or "",
                reason="unrecognized_title",
            ))
            continue

        # kind == "regulation": prefer docx → fall back odt → fail if neither.
        if d.docx_url:
            url, ext = d.docx_url, "docx"
        elif d.odt_url:
            url, ext = d.odt_url, "odt"
        else:
            skipped.append(SkippedDoc(
                title=d.title,
                url=d.pdf_url or "",
                reason="pdf_only_regulation",
            ))
            continue

        fname = _safe_filename(d.title, update_date, ext)
        out_path = download_dir / fname
        _download(session, url, out_path)

        sources.append(SourceDoc(
            path=out_path,
            url=url,
            display_name=d.title,
            update_date_iso=update_date,
        ))

    return Manifest(
        update_date_iso=update_date,
        documents=tuple(sources),
        skipped_documents=tuple(skipped),
    )
