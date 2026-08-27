"""Download NHI medication-regulation source documents.

Strategy:

1. Group listing-page links by document title (extension stripped), not by href.
2. Classify each title: `regulation` (通則 + 第N節) → in-scope; `appendix_form` (附表)
   → recorded but not downloaded; anything else → recorded as `unrecognized_title`.
3. For regulations, prefer `.docx`; fall back to `.odt` (parsed natively, no
   external conversion needed — see parse.parse_odt).

No external binary dependencies — `uv sync` is sufficient.

The NHI site sits behind Cloudflare, which fingerprints the TLS/JA3 handshake
and serves a managed challenge (HTTP 403, sometimes 503) to clients whose
fingerprint it does not like. `cloudscraper` 1.2.71 cannot pass it and plain
`requests` is flaky even with a browser User-Agent; `curl_cffi` impersonates a
real browser's TLS fingerprint, which clears it.

Which fingerprint works is not stable over time. As of 2026-08-27 Cloudflare
rejects recent Chrome profiles (`chrome146`, which the bare `"chrome"` alias
resolves to, cleared only 3/12) while Firefox and Safari profiles clear 12/12.
`_open_session` therefore walks `config.IMPERSONATE_CANDIDATES` and keeps the
first profile that gets through, instead of pinning one and hoping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

from .config import (
    APPENDIX_FORM_TITLE_PATTERN,
    CHAPTERS_DIR,
    IMPERSONATE_CANDIDATES,
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


def _make_session(impersonate: str):
    """HTTP session pinned to one curl_cffi TLS-impersonation profile."""
    return cffi_requests.Session(impersonate=impersonate)


CHALLENGE_STATUS = 403


class CloudflareBlocked(RuntimeError):
    """Every impersonation profile was rejected — nothing was downloaded.

    A distinct type so the CLI can present the (bilingual, actionable) message
    on its own instead of buried under a traceback. Deliberately narrow: it must
    not become a catch-all that swallows real pipeline failures.
    """


def _cleared_challenge(resp) -> bool:
    """Did this response get past Cloudflare, or should we try the next profile?

    Only a 403 means "wrong TLS fingerprint, try another profile". Every other
    status — including 404 and 5xx — means the request reached NHI, so the
    caller must see the real result rather than a fabricated Cloudflare error.
    """
    return resp.status_code != CHALLENGE_STATUS


def _open_session(url: str, *, candidates=IMPERSONATE_CANDIDATES):
    """Return `(session, response)` for the first profile that clears Cloudflare.

    Probes `url` once per candidate. The winning session is returned open so the
    whole run reuses one cleared connection — re-probing per download would cost
    an extra request per file and risk landing on a blocked profile mid-run.

    The probe response is returned rather than discarded: `url` is the page the
    caller wanted anyway, so this costs no extra request.
    """
    attempts: list[str] = []
    last_status: int | str | None = None

    for target in candidates:
        attempts.append(target)
        session = _make_session(target)
        try:
            resp = session.get(url)
        except Exception as exc:  # transport-level failure — try the next profile
            session.close()
            last_status = f"{type(exc).__name__}: {exc}"
            continue
        if _cleared_challenge(resp):
            return session, resp
        session.close()
        last_status = resp.status_code

    raise CloudflareBlocked(
        "\n"
        "Blocked by Cloudflare — every browser fingerprint was rejected (HTTP 403).\n"
        "被 Cloudflare 阻擋——所有瀏覽器指紋都被拒絕（HTTP 403）。\n"
        "\n"
        f"  URL          : {url}\n"
        f"  Tried / 已嘗試: {', '.join(attempts)}\n"
        f"  Last / 最後結果: {last_status}\n"
        "\n"
        "What this means / 這代表什麼:\n"
        "  The NHI website is up, but Cloudflare no longer accepts any of the TLS\n"
        "  fingerprints this tool impersonates. Your network is fine and nothing in\n"
        "  the parsing pipeline is broken — the download simply never started.\n"
        "  健保署網站是正常的，但 Cloudflare 已不再接受本工具偽裝的任何一種 TLS 指紋。\n"
        "  你的網路沒問題，解析流程也沒壞——只是連下載都還沒開始就被擋掉了。\n"
        "\n"
        "How to fix / 如何修復:\n"
        "  1. Retry in a few minutes; blocks are sometimes temporary.\n"
        "     幾分鐘後重試，封鎖有時是暫時的。\n"
        "  2. If it persists, find a working profile and add it to\n"
        "     IMPERSONATE_CANDIDATES in src/nhi_extractor/config.py.\n"
        "     若持續失敗，找出可用的 profile 並加進 config.py 的 IMPERSONATE_CANDIDATES。\n"
        "     Test each candidate at least 10 times before trusting it — a single\n"
        "     success cannot be told apart from ordinary flakiness.\n"
        "     每個候選至少測 10 次再採信——單次成功無法與偶發性波動區分。\n"
        "     Try Firefox, Safari and Tor profiles first — Cloudflare blocks by\n"
        "     engine family, not by age, and Chromium ones fare worst.\n"
        "     優先試 Firefox、Safari、Tor 的 profile——Cloudflare 是按引擎家族封鎖，\n"
        "     不是按新舊，其中 Chromium 系列最容易被擋。\n"
        "  3. Meanwhile you can still run the rest of the pipeline on files you\n"
        "     already have: nhi-extract sync --skip-fetch\n"
        "     在此期間仍可用既有檔案跑後續流程：nhi-extract sync --skip-fetch\n"
    )


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
    session, resp = _open_session(source_url)
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
