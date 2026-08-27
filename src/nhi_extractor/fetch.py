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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import get_args
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from curl_cffi.requests import exceptions as cffi_exceptions

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


SOURCE_EXTENSIONS = (".docx", ".odt")

# Reads back the `_{ROC}{MM}{DD}` suffix that _safe_filename writes. Anchored to
# the extension so an update date inside the title (…_115.8.21更新_1150821.docx)
# cannot be mistaken for the release stamp.
_RELEASE_STAMP_RE = re.compile(r"_(\d{3})(\d{2})(\d{2})\.(?:docx|odt)$", re.IGNORECASE)


@dataclass(frozen=True)
class LocalRelease:
    """One release's worth of already-downloaded source files.

    `update_date` is None when the directory carries no release stamps at all —
    a hand-assembled folder, which is still usable but whose release date is not
    recoverable from the filenames.
    """
    update_date: date | None
    paths: tuple[Path, ...]
    superseded: tuple[Path, ...] = ()


def parse_release_stamp(path: Path) -> date | None:
    """Recover the release date `_safe_filename` encoded into a filename."""
    m = _RELEASE_STAMP_RE.search(path.name)
    if not m:
        return None
    roc, mo, da = (int(g) for g in m.groups())
    try:
        return date(roc + 1911, mo, da)
    except ValueError:
        return None


def latest_local_release(chapters_dir: Path) -> LocalRelease:
    """Select the newest downloaded release from `chapters_dir`.

    The download directory accumulates every release ever fetched, so it must
    never be globbed wholesale: item_ids are unique within a document and
    `chunk_document`'s collision guard is per-document, so a mixed-release
    corpus emits duplicate item_ids silently and destroys diff stability.

    Both `.docx` and `.odt` count — 通則 and four 節 are published ODT-only, so a
    `.docx`-only glob drops 5 of the 16 in-scope documents without a word.
    """
    by_release: dict[date, list[Path]] = {}
    unstamped: list[Path] = []
    for p in sorted(chapters_dir.glob("*")):
        if p.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        stamp = parse_release_stamp(p)
        if stamp is None:
            unstamped.append(p)
        else:
            by_release.setdefault(stamp, []).append(p)

    if by_release:
        newest = max(by_release)
        older = [p for d, ps in by_release.items() if d != newest for p in ps]
        return LocalRelease(
            update_date=newest,
            paths=tuple(sorted(by_release[newest])),
            superseded=tuple(sorted(older + unstamped)),
        )

    if unstamped:
        return LocalRelease(update_date=None, paths=tuple(unstamped))

    raise FileNotFoundError(
        f"No .docx or .odt source documents in {chapters_dir}. "
        "Run `nhi-extract sync` without --skip-fetch to download them first."
    )


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


class NetworkUnreachable(RuntimeError):
    """The request never reached NHI — DNS, connection or timeout.

    Kept separate from CloudflareBlocked because the two need opposite advice:
    a fingerprint problem is worth trying another profile for, a dead network is
    not. Conflating them tells an offline user, at length and in two languages,
    that their network is fine.
    """


# Errors that are a fact about one profile rather than about the connection.
# Only these advance the walk; anything else means the fingerprint is not the
# variable and continuing would re-hit a dead host once per candidate.
_PROFILE_ERRORS = (cffi_exceptions.ImpersonateError,)


def _catalog_raw():
    """Raw (names, normalizer) from curl_cffi's impersonation catalog.

    Split out purely so the guard in `_catalog_candidates` is testable. Both
    names live in `curl_cffi.requests.impersonate` and are undocumented.
    """
    from curl_cffi.requests import impersonate as imp

    return get_args(imp.BrowserTypeLiteral), imp.normalize_browser_type


def _is_chromium(target: str) -> bool:
    return target.startswith(("chrome", "edge"))


def _catalog_candidates(exclude: Sequence[str] = ()) -> tuple[str, ...]:
    """Every distinct profile curl_cffi ships, non-Chromium first.

    Used only after the pinned candidates are exhausted. Ordering is not
    cosmetic: in the 2026-08-27 sweep all Edge and all but three Chrome
    profiles were blocked while Firefox/Safari/Tor cleared, so probing
    Chromium first would spend ~20 requests before reaching a likely winner.

    Derived from undocumented curl_cffi internals, so every access is guarded:
    if the catalog's shape changes on a version bump we return nothing and the
    caller falls back to the pinned list. A crash here would be strictly worse
    than the 403 this exists to route around.
    """
    try:
        names, normalize = _catalog_raw()
        seen: set[str] = set()
        targets: list[str] = []
        for name in sorted(names):
            real = normalize(name)
            if real not in seen:
                seen.add(real)
                targets.append(real)
    except Exception:
        return ()

    skip = set(exclude)
    return tuple(
        t for t in sorted(targets, key=lambda t: (_is_chromium(t), t)) if t not in skip
    )


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

    Two phases. The pinned `candidates` are the fast path — in the normal case
    the first one clears and nothing else is touched. Only once they are all
    blocked does the catalog sweep run, covering every other profile curl_cffi
    ships. A live sweep on 2026-08-27 cleared 22 of 45, so exhausting three
    pinned profiles is a long way from being out of options; the sweep costs
    roughly 13s worst case, paid only when the alternative is a hard failure.
    """
    attempts: list[str] = []
    last_status: int | str | None = None

    for target in (*candidates, *_catalog_candidates(exclude=candidates)):
        attempts.append(target)
        session = _make_session(target)
        try:
            resp = session.get(url)
        except _PROFILE_ERRORS as exc:
            # This profile is unusable; says nothing about the others.
            session.close()
            last_status = f"{type(exc).__name__}: {exc}"
            continue
        except Exception as exc:
            # Connection, DNS or timeout: the fingerprint is not the variable.
            # Trying the rest would re-hit a dead host once per candidate and
            # then blame Cloudflare for it.
            session.close()
            raise NetworkUnreachable(
                "\n"
                f"Could not reach {url} — {type(exc).__name__}: {exc}\n"
                f"無法連線至 {url} —— {type(exc).__name__}: {exc}\n"
                "\n"
                "What this means / 這代表什麼:\n"
                "  The request never reached the NHI server, so this is not a\n"
                "  Cloudflare block and trying other browser profiles would not\n"
                "  help. Check your network, DNS, VPN or proxy.\n"
                "  請求根本沒有送達健保署伺服器，所以這不是 Cloudflare 封鎖，\n"
                "  換其他瀏覽器 profile 也沒有用。請檢查網路、DNS、VPN 或 proxy。\n"
                "\n"
                "  You can still run the rest of the pipeline on files you already\n"
                "  have: nhi-extract sync --skip-fetch\n"
                "  仍可用既有檔案跑後續流程：nhi-extract sync --skip-fetch\n"
            ) from exc
        if _cleared_challenge(resp):
            return session, resp
        session.close()
        last_status = resp.status_code

    raise CloudflareBlocked(
        "\n"
        "Blocked by Cloudflare — every browser fingerprint was rejected (HTTP 403).\n"
        "被 Cloudflare 阻擋——所有瀏覽器指紋都被拒絕（HTTP 403）。\n"
        "\n"
        f"  URL           : {url}\n"
        f"  Tried / 已嘗試 : {len(attempts)} profiles — {', '.join(attempts[:4])}"
        f"{', …' if len(attempts) > 4 else ''}\n"
        f"  Last / 最後結果: {last_status}\n"
        "\n"
        "What this means / 這代表什麼:\n"
        "  The NHI website is reachable, but Cloudflare rejected every TLS\n"
        "  fingerprint curl_cffi can produce — not just the preferred ones.\n"
        "  Your network is fine and the parsing pipeline is not broken; the\n"
        "  download simply never started.\n"
        "  健保署網站連得到，但 Cloudflare 拒絕了 curl_cffi 能產生的每一種 TLS\n"
        "  指紋——不只是優先的那幾個。你的網路沒問題，解析流程也沒壞，\n"
        "  只是連下載都還沒開始就被擋掉了。\n"
        "\n"
        "How to fix / 如何修復:\n"
        "  1. Retry in a few minutes; blocks are sometimes temporary.\n"
        "     幾分鐘後重試，封鎖有時是暫時的。\n"
        "  2. Since every bundled profile failed, a newer curl_cffi may be needed:\n"
        "     uv add --upgrade curl-cffi\n"
        "     所有內建 profile 都失敗，可能需要更新的 curl_cffi：\n"
        "     uv add --upgrade curl-cffi\n"
        "     Then put any profile that works into IMPERSONATE_CANDIDATES in\n"
        "     src/nhi_extractor/config.py, testing each at least 10 times — a\n"
        "     single success cannot be told apart from ordinary flakiness.\n"
        "     再把可用的 profile 填進 config.py 的 IMPERSONATE_CANDIDATES，\n"
        "     每個至少測 10 次——單次成功無法與偶發性波動區分。\n"
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
