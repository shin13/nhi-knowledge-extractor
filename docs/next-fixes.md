# Follow-up fixes plan

> Originally planned 2026-05-22 as a sequenced fix-up after the first production run. Tasks A–H all landed (see commits below). Task G (附表 forms → structured CSV) is the only open item.

## Live website survey (2026-05-22)

Source page (<https://www.nhi.gov.tw/ch/cp-7593-ad2a9-3397-1.html>) publishes **92 documents**:

| Formats | Count |
|---|---|
| docx + odt + pdf | 44 |
| doc + odt + pdf | 31 |
| odt + pdf | 14 |
| pdf only | 2 (附表十三, 附表十五) |
| doc + odt | 1 (第十一節 解毒劑) |

**Decision:** target *規定* (通則 + 第N節, ~17 docs). 附表 (~75 form documents) deferred to Task G with paper trail in `Manifest.skipped_documents`.

**Format strategy:** native `.docx` preferred; `.odt` fallback parsed via zipfile + lxml (no LibreOffice). `.doc` ignored (every `.doc` has an `.odt` companion).

---

## Tasks A–H — landed in v0.1.0

<details>
<summary>All issues from the first production run are resolved. Click to expand task-by-task summary.</summary>

| Task | Commit | Result |
|---|---|---|
| **A** | `3866c08` | Multi-format fetch + 附表 classification. Listing parser groups links by document title (not href regex); fetcher prefers `.docx`, falls back to `.odt`. Brings coverage from 44/92 → 17/17 in-scope regulation documents. |
| _(side)_ | `4721433` | Native ODT parser supersedes LibreOffice route. ODT is zipped XML — we walk `office:body > office:text` directly and emit the same `Document` tree as the DOCX path. Drops 795MB install dependency. |
| ~~B~~ | — | Dropped 2026-05-22: downloads + CSV outputs are pipeline-regenerated artefacts, not repo content. `.gitignore` stays as-is. |
| **C** | `e486be9` + `ac694e0` | No blank lines in CSV `content`. All join sites in `markdown.render_node_to_markdown`, `chunk.split_leaf` (4 strategies), and `chunk._emit_body_only` use `\n` instead of `\n\n`. Regression: `test_split_leaf_outputs_have_no_blank_lines`. |
| **D** | `5981ab1` | Strategy 0 — multi-block leaf split at top-level numbered items. Tables travel with the numbered item they describe, not orphaned. Fixes 9.69 PD-L1 table case. Regex: `^(\d+)\.(?!\d)` (NHI uses no-space-after-dot). |
| **E** | `8b53f64` | Reject tilde cross-references (`4.1~3項規定`) as headings via `parse.TILDE_REFERENCE_RE`. Tightened `HEADING_PREFIX_RE` to require `.`/whitespace/EOL after numeric prefix. Hard collision check in `chunk_document` replaces the `-dup` band-aid. |
| **F** | (verification) | Full E2E smoke against live NHI page: 16 regulations / 513 items / max 5992 tokens; 8 quality gates green. Surfaced the remaining blank-line leaks → `ac694e0`. |
| **H** | landed | `package._prepend_changelog` replaces same-date entries instead of stacking duplicates. |

Tasks I–M (EMIT_DEPTH + RAG metadata + anchor preamble) were planned and landed separately — see [`docs/emit-depth-plan.md`](emit-depth-plan.md).

</details>

---

## Task G (open) — 附表 forms → structured CSV

**Status:** deferred. Scoped here so the design exists when picked up.

> Familiarity needed before starting: [`spec.md`](spec.md) §2.2 (current 11-column schema), §3 (Document / Node / Item types), §5 (`parse` and `chunk` stages). The form pipeline will live alongside, not replace, the regulation pipeline.

### Problem

~75 of the 92 source documents are 附表 (appendix forms): application sheets, scoring rubrics, treatment-tracking forms. They are referenced from regulation prose (e.g. "依附表二-D 申請") and clinicians need them, but their shape differs from regulation chapters:

- Single-page form templates, not hierarchical 節/條/項/款/目
- Heavy use of tables for layout (boxes, checkboxes), not for data
- Two are pure PDF (附表十三 DAS 28, 附表十五 RA 生物製劑申請表) — no DOCX/ODT
- Title carries semantic meaning (e.g. "附表二-D：使用健保給付 PCSK9 血脂調節劑事前審查申請表")

### Why the current chunker can't handle them

- `parse._detect_heading_level` looks for `^\d+(\.\d+)+` numeric prefixes. Forms have no such structure.
- `chunk_document` assumes a tree with `level` tuples. Forms are essentially flat.
- The CSV `topic` / `section_path` columns assume hierarchical context. A form has only `topic = 藥品給付規定 / 附表二-D`.

### Sketch of the eventual design

1. **New classifier** in `parse.py`: detect "appendix form" by title regex `^附表` (title is the only hierarchy).
2. **`parse.parse_form_document`** emits a `FormDocument` type with: title, optional intro paragraphs, optional form-fields table, optional notes table.
3. **`chunk.chunk_form_document`** — likely 1 item per form (forms fit budget) or splits at internal headings when present.
4. **PDF-only forms**: `pdfplumber` / `pymupdf` branch extracts text + tables, funnels into the same `FormDocument`. PDF→DOCX via LibreOffice is unreliable for form layouts; native PDF extraction is more controllable.
5. **`render.py`**: forms → separate CSV per form (or one combined `forms.csv` with `form_id`). The 11-column schema may need a `form_id` field, or repurpose `section_path` for form title.
6. **`fetch.py`**: stop skipping 附表; download best-available per form. ODT preferred (universal except 2 PDF-only), DOCX where available.
7. **Cross-linking**: regulation chunker already preserves "附表二-D" verbatim in `content`. No back-reference work needed on regulation side — form CSV's `item_id` (e.g. `form-2-D`) recoverable from the prose mention.

### Open design questions

- Per-form CSV vs one `forms.csv` with `form_id` rows? (Probably per-form for parity with chapter CSVs.)
- `item_id` namespace: `form-{N}{letter}` (e.g. `form-2-D`, `form-13`) — separate from `sec{N}-*`?
- Does form `content` reproduce form layout in markdown, or just list field labels? (Layout brittle; labels likely good enough for RAG retrieval.)

### Files this touches

`parse.py`, `chunk.py`, `render.py`, `fetch.py`, `types.py`, `config.py` (add `FORM_TITLE_PATTERN`), plus tests per module and a pain-case test for at least one PDF-only form.

### Trigger to start

When a downstream user reports they need form contents in RAG, or when chapter coverage is stable and we want completeness.

### Estimated effort

- DOCX / ODT path (forms with structured source): **2–3 days** including tests
- PDF-only branch (附表十三, 附表十五): **+1–2 days** — needs `pdfplumber` / `pymupdf` integration and at least one pain-case fixture
- Cross-link verification (regulation prose mentions → form `item_id` resolves): **+0.5 day**

Total: roughly one working week for end-to-end coverage of the ~75 forms.
