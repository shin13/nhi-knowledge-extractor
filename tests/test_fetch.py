from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nhi_extractor.fetch import (
    DocLinks,
    classify_document,
    parse_listing,
)


FIXTURE = Path(__file__).parent / "fixtures" / "listing_page.html"
BASE_URL = "https://www.nhi.gov.tw/ch/cp-7593-ad2a9-3397-1.html"


# --- parse_listing -----------------------------------------------------------

def test_parse_listing_groups_by_title_across_formats():
    html = FIXTURE.read_text(encoding="utf-8")
    docs, update_date = parse_listing(html, base_url=BASE_URL)

    assert len(docs) > 40, f"expected many documents, got {len(docs)}"
    assert update_date.year >= 2024
    # Every doc should carry at least one URL
    for d in docs:
        assert d.docx_url or d.odt_url or d.pdf_url, f"doc {d.title!r} has no URLs"
    # Titles should NOT contain file extensions
    for d in docs:
        assert ".docx" not in d.title and ".odt" not in d.title and ".pdf" not in d.title


def test_parse_listing_finds_odt_only_regulations():
    """通則 and 第六節 are published only as .doc/.odt/.pdf — fetcher must see them via ODT."""
    html = FIXTURE.read_text(encoding="utf-8")
    docs, _ = parse_listing(html, base_url=BASE_URL)
    by_title = {d.title: d for d in docs}

    tongze = next((d for t, d in by_title.items() if t.startswith("通則")), None)
    assert tongze is not None, f"通則 missing from parsed listing; titles: {list(by_title)[:5]}..."
    assert tongze.docx_url is None
    assert tongze.odt_url is not None

    sec6 = next((d for t, d in by_title.items() if t.startswith("第六節")), None)
    assert sec6 is not None, "第六節 missing from parsed listing"
    assert sec6.docx_url is None
    assert sec6.odt_url is not None


def test_parse_listing_keeps_docx_when_available():
    """Documents with native .docx must still expose docx_url."""
    html = FIXTURE.read_text(encoding="utf-8")
    docs, _ = parse_listing(html, base_url=BASE_URL)
    with_docx = [d for d in docs if d.docx_url]
    assert len(with_docx) >= 30, f"expected ≥30 docs with docx, got {len(with_docx)}"


# --- classify_document -------------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("通則", "regulation"),
    ("通則(113.05.28更新)", "regulation"),
    ("第一節 全身性抗感染劑", "regulation"),
    ("第六節 呼吸道藥物(115.3.23更新)", "regulation"),
    ("第十一節 解毒劑", "regulation"),
    ("第十五節 婦科製劑(114.07.24更新)", "regulation"),
    ("附表一：全民健康保險醫療常用第一線抗微生物製劑品名表", "appendix_form"),
    ("附表二-D：使用健保給付PCSK9血脂調節劑事前審查申請表(114.08.22更新)", "appendix_form"),
    ("附表十三", "appendix_form"),
    ("藥品事前審查申請表（空白表格）", "unrecognized_title"),
    ("某個未知文件", "unrecognized_title"),
])
def test_classify_document(title, expected):
    assert classify_document(title) == expected


# --- _open_session impersonation fallback ------------------------------------
#
# NHI sits behind Cloudflare, which gates on the TLS/JA3 fingerprint. A given
# impersonation target works until Cloudflare decides otherwise, so the fetcher
# walks a candidate list. These tests pin the walk; they do not touch the network.

def _sessions_for(monkeypatch, codes):
    """Stub _make_session so the Nth call yields a session returning codes[N].

    Calls past the end of `codes` return 403 — once the pinned candidates are
    exhausted the walk continues into the curl_cffi catalog, and these tests
    are about the pinned prefix.

    Returns the list of created (target, session) pairs so tests can assert
    which candidates were tried and that rejected sessions were closed.
    """
    created = []

    def fake_make_session(target):
        i = len(created)
        code = codes[i] if i < len(codes) else 403
        session = MagicMock()
        session.get = MagicMock(return_value=MagicMock(status_code=code))
        created.append((target, session))
        return session

    monkeypatch.setattr("nhi_extractor.fetch._make_session", fake_make_session)
    return created


def test_open_session_uses_first_candidate_that_clears(monkeypatch):
    created = _sessions_for(monkeypatch, [200])
    from nhi_extractor.fetch import _open_session

    session, resp = _open_session(BASE_URL, candidates=("firefox147", "safari184"))

    assert [t for t, _ in created] == ["firefox147"], "must not probe past a working target"
    assert session is created[0][1]
    assert resp.status_code == 200


def test_open_session_falls_back_past_a_challenge(monkeypatch):
    created = _sessions_for(monkeypatch, [403, 403, 200])
    from nhi_extractor.fetch import _open_session

    session, resp = _open_session(BASE_URL, candidates=("chrome146", "chrome142", "firefox147"))

    assert [t for t, _ in created] == ["chrome146", "chrome142", "firefox147"]
    assert session is created[2][1]
    assert resp.status_code == 200
    for _, rejected in created[:2]:
        rejected.close.assert_called_once()


def _sessions_raising(monkeypatch, outcomes):
    """Stub _make_session where each outcome is either an exception to raise
    from .get() or a status code to return."""
    created = []

    def fake_make_session(target):
        outcome = outcomes[len(created)]
        session = MagicMock()
        if isinstance(outcome, Exception):
            session.get = MagicMock(side_effect=outcome)
        else:
            session.get = MagicMock(return_value=MagicMock(status_code=outcome))
        created.append((target, session))
        return session

    monkeypatch.setattr("nhi_extractor.fetch._make_session", fake_make_session)
    return created


def test_open_session_skips_a_profile_curl_cannot_impersonate(monkeypatch):
    """An unsupported profile is a fact about that profile — try the next one."""
    from curl_cffi.requests.exceptions import ImpersonateError

    created = _sessions_raising(monkeypatch, [ImpersonateError("nope"), 200])
    from nhi_extractor.fetch import _open_session

    session, resp = _open_session(BASE_URL, candidates=("chrome146", "firefox147"))
    assert [t for t, _ in created] == ["chrome146", "firefox147"]
    assert resp.status_code == 200


def test_open_session_aborts_immediately_on_a_network_failure(monkeypatch):
    """A connection/DNS failure is not about the fingerprint. Walking the list
    would hammer the host once per candidate and then report, in confident
    bilingual prose, that the network is fine."""
    from curl_cffi.requests.exceptions import DNSError

    from nhi_extractor.fetch import NetworkUnreachable, _open_session

    created = _sessions_raising(monkeypatch, [DNSError("could not resolve"), 200, 200])

    with pytest.raises(NetworkUnreachable) as exc:
        _open_session(BASE_URL, candidates=("firefox147", "safari184", "chrome131"))

    assert len(created) == 1, "must not try another profile after a network error"
    msg = str(exc.value)
    assert "could not resolve" in msg
    assert "無法連線" in msg and "Could not reach" in msg


def test_open_session_aborts_on_timeout(monkeypatch):
    """45 candidates x a 30s timeout is a 20-minute hang, not a fallback."""
    from curl_cffi.requests.exceptions import Timeout

    from nhi_extractor.fetch import NetworkUnreachable, _open_session

    created = _sessions_raising(monkeypatch, [Timeout("timed out"), 200])

    with pytest.raises(NetworkUnreachable):
        _open_session(BASE_URL, candidates=("firefox147", "safari184"))
    assert len(created) == 1


def test_open_session_raises_when_every_candidate_is_blocked(monkeypatch):
    _sessions_for(monkeypatch, [403, 403, 403])
    from nhi_extractor.fetch import CloudflareBlocked, _open_session

    with pytest.raises(CloudflareBlocked) as exc:
        _open_session(BASE_URL, candidates=("chrome146", "chrome142", "edge101"))

    msg = str(exc.value)
    # The error must name the targets tried and the last status, or the next
    # person re-derives this whole investigation from scratch.
    assert "chrome146" in msg and "edge101" in msg
    assert "403" in msg
    # Bilingual, and it must say what to do — not just what failed.
    assert "Blocked by Cloudflare" in msg and "被 Cloudflare 阻擋" in msg
    assert "IMPERSONATE_CANDIDATES" in msg and "--skip-fetch" in msg


def test_open_session_does_not_fall_back_on_a_real_http_error(monkeypatch):
    """A 404/500 is the site being broken, not Cloudflare. Walking the list
    would waste requests and bury the real status."""
    created = _sessions_for(monkeypatch, [404, 200])
    from nhi_extractor.fetch import _open_session

    session, resp = _open_session(BASE_URL, candidates=("firefox147", "safari184"))

    assert [t for t, _ in created] == ["firefox147"], "must not retry other targets on 404"
    assert resp.status_code == 404


# --- fetch_all orchestration -------------------------------------------------

def test_fetch_all_records_skipped_appendix_forms(tmp_path, monkeypatch):
    """Appendix forms must be in skipped_documents, not silently dropped.
    Regulations are downloaded as either .docx or .odt — no external conversion."""
    html = FIXTURE.read_text(encoding="utf-8")

    fake_session = MagicMock()
    listing_resp = MagicMock(text=html)
    listing_resp.raise_for_status = MagicMock()
    download_resp = MagicMock()
    download_resp.raise_for_status = MagicMock()
    download_resp.iter_content = lambda _n: [b"fake file bytes"]
    fake_session.get = MagicMock(
        side_effect=lambda url, **kw: listing_resp if url.endswith(".html") else download_resp
    )
    monkeypatch.setattr(
        "nhi_extractor.fetch._open_session",
        lambda url, **kw: (fake_session, listing_resp),
    )

    from nhi_extractor.fetch import fetch_all
    manifest = fetch_all(download_dir=tmp_path)

    titles = {d.display_name for d in manifest.documents}
    assert any(t.startswith("通則") for t in titles), f"通則 not in documents: {sorted(titles)[:5]}"
    assert any(t.startswith("第六節") for t in titles), "第六節 not in documents"

    # ODT-only regulations keep their .odt extension — parser dispatches on it.
    sixth = next(d for d in manifest.documents if d.display_name.startswith("第六節"))
    assert sixth.path.suffix == ".odt"

    appendix_skipped = [s for s in manifest.skipped_documents if s.reason == "appendix_form"]
    assert len(appendix_skipped) >= 20, f"expected many appendix forms skipped, got {len(appendix_skipped)}"
    for s in appendix_skipped:
        assert s.title.startswith("附表")
        assert s.url


# --- live network check ------------------------------------------------------
#
# Everything above mocks the session, so a green suite is NOT evidence that the
# fetcher can actually reach NHI — the 2026-08-27 Cloudflare block passed every
# offline test. This is the only test that can catch that class of failure.
#
# Opt-in, because it hits a live government site:
#     uv run pytest -m live

@pytest.mark.live
def test_live_open_session_clears_cloudflare():
    """At least one configured impersonation profile must still get through."""
    from nhi_extractor.config import SOURCE_URL
    from nhi_extractor.fetch import _open_session

    session, resp = _open_session(SOURCE_URL)
    try:
        assert resp.status_code == 200
        docs, update_date = parse_listing(resp.text, base_url=SOURCE_URL)
        assert any(classify_document(d.title) == "regulation" for d in docs)
        assert update_date.year >= 2024
    finally:
        session.close()
