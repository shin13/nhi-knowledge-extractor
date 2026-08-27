# nhi-knowledge-extractor — contributor & AI-agent guide

Primary onboarding doc for human contributors and AI coding agents. New session? Read this first, then `docs/` per the project-history list.

Convert Taiwan NHI medication regulation documents into RAG-ingestion-ready CSV deliverables. Successor to `NHI-Knowledge-Extraction`. Full design in [`docs/spec.md`](docs/spec.md).

## Environment

- Python 3.13+, managed with `uv`
- Install: `uv sync` — **no system binaries required** (ODT parsed natively via zipfile + lxml)

## Commands

```bash
uv run nhi-extract sync                  # full pipeline
uv run nhi-extract sync --skip-fetch     # newest already-downloaded release (.docx + .odt)
uv run nhi-extract sync --dry-run        # build, print stats, write nothing
uv run nhi-extract parse <docx>          # debug: print tree
uv run nhi-extract chunk <docx>          # debug: print emitted items + tokens
uv run nhi-extract diff <dir_a> <dir_b>  # diff two release folders
uv run nhi-extract --version             # installed version (read from package metadata)
```

## "I want to..." quick map

| Goal | Start here |
|---|---|
| Understand the pipeline shape | [`docs/spec.md`](docs/spec.md) §3.1 |
| Add or change a CLI flag | `src/nhi_extractor/cli.py` |
| Add a new chunk-splitting strategy | `src/nhi_extractor/chunk.py` + [`docs/spec.md`](docs/spec.md) §4.2 |
| Fix a heading-detection bug | `src/nhi_extractor/parse.py` + [`docs/spec.md`](docs/spec.md) §5 |
| Change CSV schema | `src/nhi_extractor/render.py` + [`docs/spec.md`](docs/spec.md) §2.2 |
| Add support for 附表 forms | [`docs/next-fixes.md`](docs/next-fixes.md) Task G |
| Understand `EMIT_DEPTH` / `parent_id` design | [`docs/emit-depth-plan.md`](docs/emit-depth-plan.md) |
| Look up a term (item_id, EMIT_DEPTH, Strategy 0…) | [`docs/spec.md`](docs/spec.md) §Glossary |

## Layout

```
src/nhi_extractor/
  cli.py        Typer entry
  config.py     constants (TOPIC_PREFIX, budgets, paths)
  types.py      dataclasses (SourceDoc, Document, Node, Item, ...)
  fetch.py      NHI scraper → Manifest
  parse.py      DOCX/ODT → Document tree
  chunk.py      Document → [Item] (variable depth, budget contract)
  render.py     Item → CSV row (11 cols incl. parent_id/part_index/total_parts)
  diff.py       MANIFEST.json comparison
  package.py    CSVs + MANIFEST + CHANGES + zip
  markdown.py   table_to_markdown, render_node_to_markdown, count_tokens
tests/
  fixtures/     real DOCX from past NHI releases
  test_*.py     one or more focused files per module — split by topic once a
                single file grows unwieldy (see test_chunk_*.py, test_fetch*.py)
```

## Conventions

- All paths and tunables in `src/nhi_extractor/config.py`. Do not hardcode elsewhere.
- The chunker's token budget is a **contract**: any item over `HARD_BUDGET` (7000) raises in `chunk_document`. Don't catch and ignore.
- New stages get a new module + test coverage under `tests/`. One responsibility per file — which means splitting a module's tests across several focused files once one grows unwieldy (`test_<module>_<topic>.py`), not growing a single file to match the module.
- TDD: write the failing test first. `tests/test_chunk_pain_cases.py` is the regression net — never disable it.
- `mypy` runs **strict with no per-module exemptions**. A new module is expected to type-check clean, not to be added to an ignore list. The only override in `pyproject.toml` is `ignore_missing_imports` for `curl_cffi`.
- `config.IMPERSONATE_CANDIDATES` is typed as curl_cffi's own `BrowserTypeLiteral`, imported under `TYPE_CHECKING` only. A profile name that does not exist now fails `mypy` in CI instead of failing against Cloudflare on someone's next `sync`. Keep the import guarded — a runtime import would let an upstream rename break the whole package.

## What is and isn't committed

This repo ships **the pipeline**, not the data. Re-fetch produces everything downstream.

**Commit:** `src/`, `tests/`, `docs/`, `pyproject.toml`/`uv.lock`, `CHANGELOG.md`, `CONTRIBUTING.md`, small fixed `tests/fixtures/*.docx`, `CLAUDE.md`.

**Gitignored:** `data/regulations/medication/chapters/` (downloaded sources), `data/.../藥品給付規定_*/` (release outputs), `data/.../CHANGELOG_data.md` (pipeline-generated), `.private/` (local dev notes).

**Goal:** `git clone` → `uv sync` → `uv run nhi-extract sync` → get the latest CSVs.

## Pain cases the predecessor fixed manually (now automated)

The predecessor (`NHI-Knowledge-Extraction`) needed two hand-fixes every release. See [`docs/intent.md`](docs/intent.md) for the full manual workflow this replaces.

- `第8節 row 13` (Etanercept) — was hand-split with the predecessor's `csv_splitter.py`. Now: `chunk._chunk_node` descent + `split_leaf` numbered-list split.
- `第9節 row 85` (PD-L1 table) — was a Google Docs → Markdown → LLM roundtrip. Now: `parse.py` reads `<w:tbl>` directly, table preserved atomically.

## Running checks

CI gates on all three. Run them before pushing.

```bash
uv run ruff check src/ tests/                    # style, unused imports, bugbear
uv run mypy                                      # strict, no per-module exemptions
uv run pytest                                    # all (offline; `live` excluded by default)
uv run pytest -m live                            # opt-in: hits the real NHI site
uv run pytest tests/test_chunk_pain_cases.py -v  # regression net
```

`-m live` is the only check that can catch a Cloudflare block — everything else
mocks the session. CI runs the offline set; run the live one before claiming a
fetch change works.

## Releasing

The version lives in **three** places: `pyproject.toml`, `uv.lock` (run `uv lock` after bumping — never hand-edit), and `CHANGELOG.md`. `nhi_extractor.__version__` and `nhi-extract --version` read it from installed package metadata via `importlib.metadata`, so they follow the bump automatically — do not add a fourth hand-maintained copy.

1. Branch `release/vX.Y.Z`. In `CHANGELOG.md`: `[Unreleased]` → `[vX.Y.Z] - YYYY-MM-DD`, leave a new empty `[Unreleased]` above it, and repoint the `compare/…HEAD` link at the new tag.
2. Bump `pyproject.toml`, run `uv lock`, then run all three gates (`ruff`, `mypy`, `pytest` — see § Running checks).
3. PR → squash merge. The trunk is protected; no direct pushes.
4. Tag and publish — the tag message **is** the release body:

```bash
git tag -a vX.Y.Z --cleanup=verbatim -F <notes-file>   # annotated; verbatim is required
git push origin vX.Y.Z
gh release create vX.Y.Z --notes-from-tag --title "vX.Y.Z — <short summary>"
```

Two traps, both hit while cutting v0.1.2:

- **`--cleanup=verbatim` is not optional.** Git's default cleanup treats every
  line starting with `#` as a comment and deletes it, so `## Fixed` / `## Added`
  vanish from the tag message — and therefore from the release body — without any
  warning. Check with `git tag -l vX.Y.Z --format='%(contents)' | grep '^## '`
  before pushing.
- **`--notes-from-tag` does not set a title.** It puts the whole tag message in
  the body and leaves the release name empty, which renders as a bare tag in the
  releases list while v0.1.0 and v0.1.1 have descriptive titles. Pass `--title`.

## Project history & lessons

Read in order before non-trivial changes:

1. [`docs/intent.md`](docs/intent.md) — original problem; why the predecessor's flat-CSV was wrong; domain vocabulary (節/條/項/款/目)
2. [`docs/spec.md`](docs/spec.md) — full design (pipeline stages, types, chunker algorithm, schema)
3. [`docs/emit-depth-plan.md`](docs/emit-depth-plan.md) — ADR for `EMIT_DEPTH` + RAG metadata + anchor preamble
4. [`docs/roadmap.md`](docs/roadmap.md) — future plans (P0–P6)
5. [`docs/next-fixes.md`](docs/next-fixes.md) — Tasks A–H landed; Task G (附表 forms) is the open item

### Lessons learned

> _Reference notes — read after you've explored `src/` once. Each lesson assumes you can locate the file/function it mentions._

**Parsing**
- **Heading-based splitting destroys structure.** The predecessor split at 2/3-level headings and flattened everything below into one CSV cell. This chunker splits by token budget *as a contract*, descending the tree until each item fits.
- **`odfpy.getElementsByType(P)` can't see tables** — why the predecessor needed Google Docs roundtrip for §9.69. `python-docx` walks `<w:tbl>` natively; tables are first-class blocks.
- **NHI publishes 通則 / 第六節 / 第十一節 / 第十二節 / 第十五節 only as .doc/.odt.** Filter-by-`.docx` silently drops half the corpus. `fetch.parse_listing` groups by title; `.odt` parsed natively (no LibreOffice).
- **NHI sits behind Cloudflare — use `curl_cffi`, not `cloudscraper`/`requests`.** Cloudflare gates its challenge on the TLS/JA3 fingerprint, not the User-Agent: `cloudscraper` gets a hard 403, a browser UA alone is flaky. `curl_cffi` impersonates a real browser's fingerprint.
- **Which fingerprint works drifts over time — never pin the bare `"chrome"` alias.** The aliases resolve to whatever that curl_cffi release considers newest, so the effective fingerprint changes when the dependency is bumped while the source line looks untouched. `config.IMPERSONATE_CANDIDATES` holds explicit pinned versions and `fetch._open_session` walks them until one clears; once they are exhausted it sweeps the rest of curl_cffi's catalog, non-Chromium first. The catalog comes from undocumented curl_cffi internals, so `_catalog_candidates` swallows any error and returns `()` — degrading to the pinned list is the whole point, and a crash there would be worse than the 403 it routes around. Don't "clean up" that bare `except`.
- **Only fingerprint-specific errors advance the walk.** `ImpersonateError` means try the next profile; a DNS/connection/timeout error raises `NetworkUnreachable` immediately. Advancing on every exception is how an offline machine gets told, in two languages, that its network is fine — and with a 45-profile catalog it also means 45 requests at a dead host. Measured 2026-08-27: `chrome146` (what `"chrome"` resolved to) cleared 3/12; `firefox147` / `safari184` / `chrome131` cleared 12/12. A full sweep of all 45 distinct profiles cleared 22 — and **Cloudflare blocks by engine family, not by age**: every Edge and every Chrome outside the narrow 123–131 band was blocked, including the oldest (`chrome99`), while Firefox, Safari and Tor cleared almost across the board. When picking a replacement, reach for non-Chromium, not merely older.
- **A 403 sweep needs n≥10 per target.** An earlier session concluded "intermittent 20-40% flake, retry fixes it" from single samples and wrote it into the handoff; the real 2026-08-27 failure was a profile-level block that retrying could not fix (same session, 6/6 × 403). Interleave targets across the sweep so a time-of-day effect can't masquerade as a per-profile signal.
- **A green `pytest` is not evidence that fetch works** — `test_fetch.py` mocks the session, and every offline test passed straight through the 2026-08-27 block. Cite `uv run pytest -m live` (the opt-in live test) or a real `sync`.
- **Tilde cross-references look like headings.** `4.1~3項規定` would parse as a `(4,1)` heading. `parse.TILDE_REFERENCE_RE` rejects them. Also: `HEADING_PREFIX_RE` requires `.` / whitespace / EOL after the numeric prefix, so `"2.18歲以上..."` stays as body.
- **通則 uses Chinese-numeral headings (一、二、三)** — doesn't match Arabic-only regex. `chunk_document` detects root-only shape and emits as a single `sec0` item.

**Chunker**
- **The token budget is a contract.** `chunk_document` raises `ValueError` if any item exceeds `HARD_BUDGET`. Never catch and ignore.
- **`item_id` collisions are a hard error**, not a warning — diff stability across releases depends on unique IDs. Format `sec{N}-{level}`; splits use `-part1`/`-part2`. Don't change the scheme casually.
- **Decouple editorial granularity from embedding ceiling.** `EMIT_DEPTH=5` (depth knob) is independent of `HARD_BUDGET` (token knob). Old design conflated them and 9/512 (1.8%) rows merged multiple drugs into one chunk. See [`docs/emit-depth-plan.md`](docs/emit-depth-plan.md) for the ADR.
- **CSV content cells: no blank lines.** `\n\n` between blocks renders as empty rows in RAG. Every join site uses `\n`. Regression: `test_split_leaf_outputs_have_no_blank_lines`.

**RAG-facing schema**
- **`parent_id` / `part_index` / `total_parts` for hydration.** When the chunker splits a logical unit, all parts share `parent_id` so downstream RAG can hydrate siblings. Heading-hierarchy siblings (`sec5-5.1.1` vs `sec5-5.1.2`) do NOT share `parent_id` — different logical units.
- **Recursive sub-split needs anchor preamble.** Continuation sub-parts (`part3-2` onwards) inject `{opener}（續）：` after the heading, so each row is self-contained for retrieval.

**Misc**
- **附表 forms are out of scope** — recorded in `Manifest.skipped_documents` with reason `"appendix_form"`. Future plan in `docs/next-fixes.md` Task G.
- **`package._prepend_changelog` replaces same-date entries** instead of stacking duplicates.
- **NHI republishes unchanged content under a new release date.** The 2026-07-24 and 2026-07-27 releases are identical except for the `source_file` and `update_date` columns, and the item-level diff correctly reports `+0 / ~0 / -0`. A zero diff is not evidence of a broken pipeline — confirm by comparing CSVs directly. Downstream RAG should not re-embed on a date-only change.
