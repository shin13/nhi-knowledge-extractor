# Changelog

Pipeline version history. Per-release NHI data diffs live in `data/regulations/medication/CHANGELOG_data.md` (gitignored, regenerated each `sync`).

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [v0.1.2] - 2026-08-27

### Added
- `nhi-extract --version`, and `nhi_extractor.__version__`. Both read the installed
  package metadata via `importlib.metadata`, so `pyproject.toml` stays the single
  source of truth rather than gaining a fourth hand-synced copy of the number.
- `ruff` (`E,F,I,UP,B,SIM`) and `mypy --strict` now gate every pull request alongside
  the test suite. mypy runs with no per-module exemptions; the only override is
  `ignore_missing_imports` for `curl_cffi`.
- `config.IMPERSONATE_CANDIDATES` is typed as curl_cffi's own `BrowserTypeLiteral`
  (imported under `TYPE_CHECKING`, so an upstream rename fails CI rather than the
  package). A profile name that does not exist is now caught by `mypy` instead of
  surfacing as a Cloudflare 403 on someone's next `sync`.
- `CONTRIBUTING.md`, and CI / license / Python-version badges on the README.
- Catalog fallback sweep. Once the pinned candidates are exhausted, `fetch` walks every other profile curl_cffi ships, non-Chromium first — a live sweep found 22 of 45 profiles clearing while all Edge and all but three Chrome were blocked. Derived defensively from undocumented curl_cffi internals: if their shape changes on a version bump the sweep yields nothing and the pinned list still works, rather than raising from inside the fetcher.
- `fetch.NetworkUnreachable`, raised immediately on a DNS/connection/timeout failure. Previously any exception advanced the walk, so an offline machine would probe every candidate and then be told at length, in two languages, that its network was fine. Only errors specific to a profile (`ImpersonateError`) now continue the walk.
- When every profile is blocked, `sync` now exits with a bilingual (English / 繁體中文) explanation — what failed, what it does *not* mean (the site and your network are fine), and how to recover — instead of a `curl_cffi` traceback. Raised as `fetch.CloudflareBlocked` so the CLI can present it without a stack trace.
- `pytest -m live` — an opt-in test that hits the real NHI site. The rest of `test_fetch.py` mocks the session and cannot detect a Cloudflare block.

### Fixed
- `sync` no longer fails with `403 Forbidden`. Cloudflare began rejecting recent Chrome TLS fingerprints, including the one the `impersonate="chrome"` alias resolved to. `fetch` now walks `config.IMPERSONATE_CANDIDATES` and keeps the first profile that clears the challenge, so a future block on one fingerprint degrades to a slower first request instead of a hard failure.
- `--skip-fetch` no longer silently builds a corpus from every release at once. The download directory accumulates one file set per release, and the old `*.docx` glob swept all of them into a single run: on a 7-release directory it emitted 3689 items with duplicated `item_id`s instead of 575. (`chunk_document`'s collision guard is per-document, so nothing caught it.) It now selects the newest release by the date stamp in the filename and reports how many older files it ignored.
- `--skip-fetch` no longer drops the ODT-only chapters. The `*.docx` glob excluded 通則, 第六節, 第十一節, 第十二節 and 第十五節 — 5 of the 16 in-scope documents — with no warning.
- `--skip-fetch` now dates the release from the source filenames instead of `date.today()`, so the output folder is named for the NHI release it actually contains.
- `_odt_extract_text` would raise `TypeError` on an ODT element containing a comment
  or processing-instruction node: `lxml`'s `itertext()` yields `bytes` for those, and
  the join assumed `str` throughout. Non-text nodes are now dropped. Surfaced by the
  new type-check; no released input is known to have triggered it.

### Changed
- Impersonation targets are pinned explicitly. The bare `"chrome"`/`"firefox"` aliases track whatever curl_cffi ships as newest, which silently changes the fingerprint on a dependency bump.

## [v0.1.1] - 2026-07-27

### Fixed
- `fetch` no longer fails with `403 Forbidden` on `sync`. NHI's Cloudflare now serves a JS managed challenge that `cloudscraper` could not pass and that plain `requests` cleared only intermittently. Switched to `curl_cffi` with Chrome TLS impersonation, which clears it deterministically.

### Changed
- Dependency: replaced `cloudscraper` with `curl-cffi` (still pure-pip, no system binary required).

## [v0.1.0] - 2026-05-24

First public release.

### Added
- `EMIT_DEPTH` parameter (default 5) — decouples editorial chunk granularity from token budget. Chunker forces descent past shallow nodes even when the subtree fits. CLI: `--emit-depth N` on `sync` and `chunk`.
- Item metadata `parent_id` / `part_index` / `total_parts` (+ matching CSV columns) for downstream RAG hydration of split siblings.
- Anchor preamble in Strategy 0 recursive sub-split — continuation sub-parts (e.g. `sec9-9.69-part3-2`) inject `{opener}（續）：` so each row is self-contained.
- GitHub Actions CI: pytest on push and PR.
- `docs/roadmap.md` (P0–P6 future plan) and `docs/emit-depth-plan.md` (chunker overhaul rationale).

### Changed
- CSV schema: 8 → 11 columns. New: `parent_id`, `part_index`, `total_parts`. **Breaking** for positional readers; `csv.DictReader` and pandas are transparent.
- `CHANGELOG.md` is now project version history only. Pipeline-generated data-release diffs moved to `data/regulations/medication/CHANGELOG_data.md` (gitignored).
- README rewritten with English + Traditional Chinese, quickstart, and a worked CSV row example.

### Fixed
- 9 / 512 rows that previously merged multiple drugs into one chunk (1.8% pollution) now split per-drug. Worst case: `sec5-5.1` 糖尿病用藥 (12 sub-headings → 12 rows).

### Pre-history

Pre-v0.1.0 work lives in git commits. Highlights: DOCX/ODT parser with native table extraction; variable-depth chunker with hard token budget contract; multi-format NHI fetcher (DOCX + ODT, 17 chapters); Strategy 0 leaf-splitter; same-date CHANGELOG replace; tilde cross-reference rejection.

[Unreleased]: https://github.com/shin13/nhi-knowledge-extractor/compare/v0.1.2...HEAD
[v0.1.2]: https://github.com/shin13/nhi-knowledge-extractor/releases/tag/v0.1.2
[v0.1.1]: https://github.com/shin13/nhi-knowledge-extractor/releases/tag/v0.1.1
[v0.1.0]: https://github.com/shin13/nhi-knowledge-extractor/releases/tag/v0.1.0
