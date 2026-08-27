"""The catalog fallback sweep.

When every pinned candidate is blocked, the fetcher sweeps the rest of the
profiles curl_cffi ships rather than giving up. That list is derived from
`curl_cffi.requests.impersonate`, which is NOT documented public API — so the
derivation must degrade to "pinned candidates only" if its shape ever changes.
Crashing there would be strictly worse than the 403 it exists to avoid.
"""

from unittest.mock import MagicMock

import pytest

from nhi_extractor import fetch

URL = "https://www.nhi.gov.tw/ch/cp-7593-ad2a9-3397-1.html"


# --- catalog derivation ------------------------------------------------------

def test_catalog_is_non_empty_and_collapses_aliases():
    catalog = fetch._catalog_candidates()
    assert len(catalog) > 20, f"expected the full curl_cffi catalog, got {catalog}"
    assert len(catalog) == len(set(catalog)), "aliases must collapse to distinct targets"
    # The bare aliases are what caused the original bug — never probe them.
    assert not ({"chrome", "firefox", "safari", "edge"} & set(catalog))


def test_catalog_puts_non_chromium_first():
    """Measured 2026-08-27: every Edge and all but three Chrome profiles were
    blocked, while Firefox/Safari/Tor cleared. Probing Chromium first would
    burn ~20 requests before reaching anything likely to work."""
    catalog = fetch._catalog_candidates()
    chromium = [i for i, t in enumerate(catalog) if t.startswith(("chrome", "edge"))]
    others = [i for i, t in enumerate(catalog) if not t.startswith(("chrome", "edge"))]
    assert others and chromium
    assert max(others) < min(chromium), "all non-Chromium must precede all Chromium"


def test_catalog_excludes_already_tried_profiles():
    catalog = fetch._catalog_candidates(exclude=("firefox147", "safari184"))
    assert "firefox147" not in catalog
    assert "safari184" not in catalog


def test_catalog_degrades_to_empty_if_curl_cffi_changes_shape(monkeypatch):
    """The whole point: a curl_cffi bump must not turn a recoverable 403 into
    an AttributeError raised from inside the fetcher."""
    def boom():
        raise AttributeError("BrowserTypeLiteral moved")

    monkeypatch.setattr(fetch, "_catalog_raw", boom)
    assert fetch._catalog_candidates() == ()


# --- the hybrid walk ---------------------------------------------------------

def _record_sessions(monkeypatch, clears):
    """Sessions 403 unless their target is in `clears`."""
    tried = []

    def fake_make_session(target):
        tried.append(target)
        session = MagicMock()
        code = 200 if target in clears else 403
        session.get = MagicMock(return_value=MagicMock(status_code=code))
        return session

    monkeypatch.setattr(fetch, "_make_session", fake_make_session)
    return tried


def test_pinned_candidates_are_tried_before_the_catalog(monkeypatch):
    tried = _record_sessions(monkeypatch, clears={"safari184"})

    session, resp = fetch._open_session(URL, candidates=("firefox147", "safari184"))

    assert tried == ["firefox147", "safari184"], "must not reach the catalog"
    assert resp.status_code == 200


def test_catalog_is_swept_once_the_pinned_list_is_exhausted(monkeypatch):
    """This is the durability claim: 22 of 45 profiles cleared in a live sweep,
    so exhausting three pinned ones should not be the end of the road."""
    tried = _record_sessions(monkeypatch, clears={"tor145"})

    session, resp = fetch._open_session(URL, candidates=("chrome146", "chrome142"))

    assert resp.status_code == 200
    assert tried[:2] == ["chrome146", "chrome142"]
    assert "tor145" in tried[2:]


def test_no_profile_is_probed_twice(monkeypatch):
    tried = _record_sessions(monkeypatch, clears=set())

    with pytest.raises(fetch.CloudflareBlocked):
        fetch._open_session(URL, candidates=("firefox147", "safari184"))

    assert len(tried) == len(set(tried)), f"duplicate probes: {tried}"
    assert tried[:2] == ["firefox147", "safari184"]


def test_exhausting_everything_still_raises_the_bilingual_error(monkeypatch):
    _record_sessions(monkeypatch, clears=set())

    with pytest.raises(fetch.CloudflareBlocked) as exc:
        fetch._open_session(URL, candidates=("firefox147",))

    msg = str(exc.value)
    assert "被 Cloudflare 阻擋" in msg and "Blocked by Cloudflare" in msg
    # With a catalog sweep the "tried" list is long; the message must summarise
    # rather than paste 45 names into the terminal.
    assert "45" in msg or "profiles" in msg


def test_catalog_failure_does_not_break_the_pinned_walk(monkeypatch):
    monkeypatch.setattr(fetch, "_catalog_raw", lambda: (_ for _ in ()).throw(ImportError("gone")))
    tried = _record_sessions(monkeypatch, clears={"safari184"})

    session, resp = fetch._open_session(URL, candidates=("firefox147", "safari184"))
    assert resp.status_code == 200
    assert tried == ["firefox147", "safari184"]
