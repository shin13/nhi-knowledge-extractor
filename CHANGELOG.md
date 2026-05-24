# Changelog

Pipeline version history. Per-release NHI data diffs live in `data/regulations/medication/CHANGELOG_data.md` (gitignored, regenerated each `sync`).

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_(nothing yet)_

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

[Unreleased]: https://github.com/shin13/nhi-knowledge-extractor/compare/v0.1.0...HEAD
[v0.1.0]: https://github.com/shin13/nhi-knowledge-extractor/releases/tag/v0.1.0
