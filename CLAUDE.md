# nhi-knowledge-extractor

Convert Taiwan NHI medication regulation DOCX documents into RAG-ingestion-ready CSV deliverables. Successor to `NHI-Knowledge-Extraction`. See `docs/spec.md`.

## Environment

- Python 3.13+, managed with `uv`
- Install: `uv sync` — **no system binaries required**

NHI publishes some chapters only as `.odt` (通則, 第六節, 第十一節, 第十二節, 第十五節). These are parsed **natively** via zipfile + lxml in `parse.parse_odt` — same `Document` tree as the DOCX path, no LibreOffice or Pandoc subprocess. See `docs/intent.md` "Lessons" for why we abandoned the conversion route.

## Commands

```bash
uv run nhi-extract sync                  # full pipeline
uv run nhi-extract sync --skip-fetch     # use local DOCX
uv run nhi-extract sync --dry-run        # build, print stats, write nothing
uv run nhi-extract parse <docx>          # debug: print tree
uv run nhi-extract chunk <docx>          # debug: print emitted items + tokens
uv run nhi-extract diff <dir_a> <dir_b>  # diff two release folders
```

## Layout

```
src/nhi_extractor/
  cli.py        Typer entry
  config.py     constants (TOPIC_PREFIX, budgets, paths)
  types.py      dataclasses (SourceDoc, Document, Node, Item, ...)
  fetch.py      NHI scraper → Manifest
  parse.py      DOCX → Document tree (python-docx)
  chunk.py      Document → [Item] (variable depth, budget contract)
  render.py     Item → CSV row (8 cols)
  diff.py       MANIFEST.json comparison
  package.py    CSVs + MANIFEST + CHANGES + CHANGELOG + zip
  markdown.py   table_to_markdown, render_node_to_markdown, count_tokens
tests/
  fixtures/     real DOCX from past NHI releases (gitignored if large)
  test_*.py     one file per module + test_chunk_pain_cases.py
data/regulations/medication/    release outputs (gitignored)
CHANGELOG.md                     rolling release history (auto-maintained)
```

## Conventions

- All paths and tunables in `src/nhi_extractor/config.py`. Do not hardcode elsewhere.
- The chunker's token budget is a **contract**: any item over `HARD_BUDGET` (7000) raises in `chunk_document`. Don't catch and ignore.
- New stages get a new module + a new `tests/test_<module>.py`. One responsibility per file.
- TDD: write the failing test first. The pain-case tests in `tests/test_chunk_pain_cases.py` are the regression net — never disable them.

## What is and isn't committed to this repo

This repo ships **the pipeline**, not the data. A weekly automated run regenerates everything downstream of the NHI website, so committing those artefacts only creates churn.

**Commit:**
- Source under `src/`, tests, docs, `pyproject.toml`/`uv.lock`, `CHANGELOG.md`
- Small fixed `tests/fixtures/*.docx` — these are pinned regression inputs, never change
- `MEMORY.md` / `CLAUDE.md` / `HANDOFF.md`

**Do NOT commit (kept in `.gitignore`):**
- `data/regulations/medication/chapters/` — downloaded NHI source documents. The NHI website is the source of truth; re-fetch when needed.
- `data/regulations/medication/藥品給付規定_*/` and `.zip` — release outputs (CSVs, MANIFEST, CHANGES). They are pipeline output, not source.

**Goal for new contributors:** `git clone` → `uv sync` → `uv run nhi-extract sync` → get the latest CSVs. No data files should be required from the repo to make that work.

## Pain cases the predecessor required manual fixes for (now automated)

- `第8節 row 13` (Etanercept) — over-budget; was hand-split with `csv_splitter.py`. Now: `chunk._chunk_node` descent + `split_leaf` numbered-list split.
- `第9節 row 85` (immune checkpoint inhibitors PD-L1 table) — over-budget + embedded matrix table. Was a Google Docs roundtrip. Now: `parse.py` reads `<w:tbl>` directly, `markdown.table_to_markdown` renders it, the chunker keeps it atomic.

## Running tests

```bash
uv run pytest                                       # all
uv run pytest tests/test_chunk_pain_cases.py -v     # the regression net
```

## Project history & lessons learned

Read these in order before making non-trivial changes:

1. [`docs/intent.md`](docs/intent.md) — original problem statement. Why the predecessor's flat-CSV model was the wrong shape; what "done right" looks like; failure modes the design must withstand; domain vocabulary (節/條/項/款/目).
2. [`docs/spec.md`](docs/spec.md) — full design spec. Pipeline stages, core types, chunker algorithm, output schema.
3. [`docs/next-fixes.md`](docs/next-fixes.md) — known issues + planned fixes (multi-format fetch for 通則/第六節, single-newline content, multi-block numbered-item splitter, tilde-reference parser fix). **If you're picking up this repo, this is your work queue.**

### Lessons carried over from the predecessor (NHI-Knowledge-Extraction)

- **Heading-based splitting destroys structure.** The predecessor split at 2/3-level headings and forced everything below into one CSV cell. This is why `csv_splitter.py` had to exist. The chunker here splits by token budget *as a contract*, descending the tree until each item fits.
- **`odfpy.getElementsByType(P)` cannot see tables.** That's why the predecessor required a Google Docs → Markdown → LLM roundtrip for §9.69. `python-docx` walks `<w:tbl>` natively; tables become first-class `Block` types.
- **NHI publishes some documents only as .doc/.odt (no .docx).** Notably 通則 (only .doc/.odt/.pdf), 第六節, 第十一節, 第十二節, 第十五節. Filter-by-extension silently drops half the corpus. `fetch.parse_listing` groups by title and `fetch.classify_document` routes by 規定 / 附表. `.odt` files are parsed natively by `parse.parse_odt` (zipfile + lxml) — no LibreOffice or other external binary.
- **NHI cross-references like `4.1~3項規定` look like headings to a naive regex.** The predecessor parser had an explicit exception (`^\d+\.\d+~\d+` → reject). Re-added in `parse.TILDE_REFERENCE_RE`. Also: `HEADING_PREFIX_RE` requires the prefix be followed by `.`, whitespace, or end-of-string — so `"2.18歲以上..."` (a list-item paragraph) stays as body, not a phantom `2.18` heading.
- **CSV `content` cells: no blank lines anywhere.** `\n\n` between blocks becomes visible empty rows when the RAG renders cells. Every join site in `markdown.render_node_to_markdown`, `chunk.split_leaf` (all four strategies), and `chunk._emit_body_only` uses `\n`. Regression test: `tests/test_chunk_leaf.py::test_split_leaf_outputs_have_no_blank_lines`.
- **通則 uses Chinese-numeral headings (一、二、三).** Doesn't match the Arabic-only heading regex, so it lands entirely in `root.body` with no children. `chunk_document` detects this root-only shape and emits it as a single `sec0` item (split via leaf splitter if it ever exceeds budget). `parse._build_document_from_blocks` assigns `section_number = 0` when title contains "通則" for stable item_id.
- **附表 forms are out of scope for the chunker.** ~75 NHI 附表 (application/scoring forms) have non-hierarchical structure. `fetch.fetch_all` records them in `Manifest.skipped_documents` with reason `"appendix_form"` — visible in `MANIFEST.json`, not silently dropped. Structured-CSV pipeline for forms sketched in `docs/next-fixes.md` Task G.
- **`item_id` collisions are a hard error, not a warning.** Diff stability across releases depends on unique IDs. `chunk_document` raises if any item_id appears twice, pointing the reader at `parse.TILDE_REFERENCE_RE` as the first place to check.
- **`package._prepend_changelog` replaces same-date entries.** Re-running `sync` for the same NHI release date used to stack duplicate `## [YYYYMMDD]` headers. Now splices in place.
- **The token budget is a contract, not a linter.** The predecessor discovered overflows *after* CSV generation. Here, `chunk_document` raises `ValueError` if any item exceeds `HARD_BUDGET`. Never catch and ignore.
- **`item_id` must be deterministic and stable across releases.** It's the diff key. Format: `sec{N}-{level}` (e.g. `sec9-9.69.1`). Splits use `-part1`/`-part2`. Don't change the scheme casually — it breaks release-over-release diffs.
- **Decouple editorial granularity from embedding ceiling.** Early design used `TARGET_BUDGET=6000` as both "what fits embedding" AND implicit "what's a row" — they coincided by luck for NHI content. A larger embedding window (or NHI re-numbering) would silently collapse rows. `EMIT_DEPTH` (default 5, see `docs/emit-depth-plan.md`) is a separate knob: minimum tree depth at which a node may emit as a single row. Below it, chunker MUST descend regardless of budget. Verified fix: 9/512 rows (1.8%) merged ≥2 drug regulations into one chunk under the pre-EMIT_DEPTH behavior (worst case `sec5-5.1` 糖尿病用藥 with 12 sub-headings merged). Run audit `grep -c '^## ' content > 1` per release as regression check.
- **`parent_id` / `part_index` / `total_parts` for RAG hydration.** When the chunker splits a logical unit (e.g. `sec9-9.69` → 5 parts), every part carries the same `parent_id` and 1-based `part_index` / `total_parts`. Downstream RAG should hydrate siblings when any part is retrieved (LangChain `ParentDocumentRetriever` / LlamaIndex `AutoMergingRetriever` pattern). Non-split rows have `parent_id == item_id`, `part_index=1`, `total_parts=1`. Derivation strips chunker-added suffixes only (`-partN[-M]`, `-tblN`, `-preamble`) — heading hierarchy (`sec5-5.1.1` vs `sec5-5.1`) does NOT share `parent_id`; they are different logical units.
- **Recursive sub-split needs anchor preamble.** When Strategy 0 sub-splits an over-budget numbered group, continuation sub-parts (part3-2 onwards) would otherwise start mid-list with no link to the parent numbered item — e.g. begin at "II. ..." with no clue they belong to "3. 使用條件:" of 9.69. Strategy 0 now extracts the group opener line, strips trailing colon, and injects `{opener}（續）：` after the heading in every continuation sub-part. First sub-part needs no injection (naturally contains opener).
