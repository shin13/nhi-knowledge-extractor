# nhi-knowledge-extractor

Convert Taiwan NHI medication regulation DOCX documents into RAG-ingestion-ready CSV deliverables. Successor to `NHI-Knowledge-Extraction`. See `docs/spec.md`.

## Environment

- Python 3.13+, managed with `uv`
- Install: `uv sync`
- **LibreOffice (hard dep)**: required to convert `.odt` source documents that NHI doesn't publish as `.docx` (通則, 第六節, 第十一節, 第十二節, 第十五節). Install once:
  - macOS: `brew install --cask libreoffice`
  - Debian/Ubuntu: `sudo apt-get install libreoffice`
  - `soffice` or `libreoffice` must be on `PATH` (macOS app bundle path also detected). `fetch_all` fails fast with the install hint if missing.

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
- **NHI publishes some documents only as .doc/.odt (no .docx).** Notably 通則 and 第六節. Filter-by-extension drops them silently. Fetch by document title, prefer .docx, fall back via LibreOffice conversion. See `docs/next-fixes.md` Task A.
- **NHI cross-references like `4.1~3項規定` look like headings to a naive regex.** The predecessor's parser had an explicit exception (`^\d+\.\d+~\d+` → reject). Carry that forward. See `docs/next-fixes.md` Task E.
- **CSV `content` cells: avoid blank lines.** `\n\n` markdown joins become visible blank lines when the RAG appends extra columns. Single `\n` between blocks. See `docs/next-fixes.md` Task C.
- **The token budget is a contract, not a linter.** The predecessor discovered overflows *after* CSV generation. Here, `chunk_document` raises `ValueError` if any item exceeds `HARD_BUDGET`. Never catch and ignore.
- **`item_id` must be deterministic and stable across releases.** It's the diff key. Format: `sec{N}-{level}` (e.g. `sec9-9.69.1`). Splits use `-part1`/`-part2`. Don't change the scheme casually — it breaks release-over-release diffs.
