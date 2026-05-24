# nhi-knowledge-extractor — contributor & AI-agent guide

Primary onboarding doc for human contributors and AI coding agents. New session? Read this first, then `docs/` per the project-history list.

Convert Taiwan NHI medication regulation documents into RAG-ingestion-ready CSV deliverables. Successor to `NHI-Knowledge-Extraction`. Full design in [`docs/spec.md`](docs/spec.md).

## Environment

- Python 3.13+, managed with `uv`
- Install: `uv sync` — **no system binaries required** (ODT parsed natively via zipfile + lxml)

## Commands

```bash
uv run nhi-extract sync                  # full pipeline
uv run nhi-extract sync --skip-fetch     # use local DOCX
uv run nhi-extract sync --dry-run        # build, print stats, write nothing
uv run nhi-extract parse <docx>          # debug: print tree
uv run nhi-extract chunk <docx>          # debug: print emitted items + tokens
uv run nhi-extract diff <dir_a> <dir_b>  # diff two release folders
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
  test_*.py     one file per module + test_chunk_pain_cases.py
```

## Conventions

- All paths and tunables in `src/nhi_extractor/config.py`. Do not hardcode elsewhere.
- The chunker's token budget is a **contract**: any item over `HARD_BUDGET` (7000) raises in `chunk_document`. Don't catch and ignore.
- New stages get a new module + a new `tests/test_<module>.py`. One responsibility per file.
- TDD: write the failing test first. `tests/test_chunk_pain_cases.py` is the regression net — never disable it.

## What is and isn't committed

This repo ships **the pipeline**, not the data. Re-fetch produces everything downstream.

**Commit:** `src/`, `tests/`, `docs/`, `pyproject.toml`/`uv.lock`, `CHANGELOG.md`, small fixed `tests/fixtures/*.docx`, `CLAUDE.md`.

**Gitignored:** `data/regulations/medication/chapters/` (downloaded sources), `data/.../藥品給付規定_*/` (release outputs), `data/.../CHANGELOG_data.md` (pipeline-generated), `.private/` (local dev notes).

**Goal:** `git clone` → `uv sync` → `uv run nhi-extract sync` → get the latest CSVs.

## Pain cases the predecessor fixed manually (now automated)

The predecessor (`NHI-Knowledge-Extraction`) needed two hand-fixes every release. See [`docs/intent.md`](docs/intent.md) for the full manual workflow this replaces.

- `第8節 row 13` (Etanercept) — was hand-split with the predecessor's `csv_splitter.py`. Now: `chunk._chunk_node` descent + `split_leaf` numbered-list split.
- `第9節 row 85` (PD-L1 table) — was a Google Docs → Markdown → LLM roundtrip. Now: `parse.py` reads `<w:tbl>` directly, table preserved atomically.

## Running tests

```bash
uv run pytest                                    # all
uv run pytest tests/test_chunk_pain_cases.py -v  # regression net
```

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
