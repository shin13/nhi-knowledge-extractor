# nhi-knowledge-extractor — Follow-up Fixes Plan

> Five issues surfaced after the first real production run. Each issue has a self-contained task with a test.

**Repo:** `/Users/shin/Projects/nhi-knowledge-extractor`

**Baseline commit:** `49204cb` (working tree clean after first production run)

---

## Issue summary

| # | Symptom | Root cause | Fix |
|---|---------|-----------|-----|
| 1 | 通則 (first chapter) not in release | NHI publishes 通則 only as `.doc`/`.odt`/`.pdf`, no `.docx` | Fetch falls back to `.odt`; convert to `.docx` via LibreOffice |
| 2 | DOCX files gitignored | `.gitignore` excludes `chapters/` | Remove that line, commit existing files |
| 3 | 第六節 呼吸道藥物 missing | Same as #1 | Same fix as #1 |
| 4 | Blank lines between every line of `content` | `render_node_to_markdown` joins with `\n\n` | Use `\n` instead |
| 5 | 9.69 split mid-numbered-item, table orphaned | Strategy 1 only fires on single-paragraph leaves | Multi-block numbered-item-aware splitter |

---

## Task A — Multi-format fetch (Issues 1 + 3)

**Problem:** NHI publishes each document in `.doc`/`.docx`/`.odt`/`.pdf`. Our scraper filters `.docx` only, silently dropping documents NHI didn't publish in DOCX (通則, 第六節 呼吸道藥物).

**Strategy:** Fetch by **document title**, not by file extension. For each unique title, prefer `.docx`, fall back to `.odt`. Convert `.odt` to `.docx` at fetch time via LibreOffice subprocess.

Skip `.doc` (old binary, no good Python parser, libreoffice converts slowly). Skip `.pdf` (different parsing pipeline entirely).

### Files

- Modify: `src/nhi_extractor/config.py` — add `ODT_LINK_PATTERN`
- Modify: `src/nhi_extractor/fetch.py` — group links by title, prefer docx, convert odt
- Add: `tests/test_fetch_multiformat.py`
- Update: `tests/fixtures/listing_page.html` — refresh if needed

### Steps

**A1. Add ODT pattern + helper to config**

Append to `src/nhi_extractor/config.py`:

```python
ODT_LINK_PATTERN = r".*\.odt$"
```

**A2. Refactor `parse_listing` to group by title**

In `src/nhi_extractor/fetch.py`, change `parse_listing` to return links grouped by document title with all available formats:

```python
@dataclass(frozen=True)
class _DocLinks:
    title: str                  # canonical title with extension stripped
    docx_url: str | None
    odt_url: str | None

def parse_listing(html: str, *, base_url: str) -> tuple[list[_DocLinks], date]:
    soup = BeautifulSoup(html, "html.parser")
    # Map: normalized title → {ext: url}
    groups: dict[str, dict[str, str]] = {}
    for a in soup.find_all("a", href=True):
        href = a.get("href")
        title = a.get("title") or ""
        if not title:
            continue
        m = re.search(r"\.(docx|odt)$", title, re.IGNORECASE)
        if not m:
            continue
        ext = m.group(1).lower()
        norm_title = re.sub(r"\.(docx|odt)$", "", title, flags=re.IGNORECASE).strip()
        groups.setdefault(norm_title, {})[ext] = urljoin(base_url, href)

    docs: list[_DocLinks] = []
    for title, urls in groups.items():
        docs.append(_DocLinks(
            title=title,
            docx_url=urls.get("docx"),
            odt_url=urls.get("odt"),
        ))

    update_date = _parse_update_date(soup)
    if update_date is None:
        raise RuntimeError("Could not parse website update date — page structure changed?")
    return docs, update_date
```

**A3. Update `fetch_all` to convert ODT-only documents**

```python
import subprocess
import shutil

def _convert_odt_to_docx(odt_path: Path) -> Path:
    """Use LibreOffice headless to convert ODT → DOCX. Returns the new .docx path."""
    if not shutil.which("libreoffice") and not shutil.which("soffice"):
        raise RuntimeError(
            "ODT-only documents found but LibreOffice (libreoffice/soffice) not installed. "
            "Install with: brew install --cask libreoffice"
        )
    cmd_name = "libreoffice" if shutil.which("libreoffice") else "soffice"
    result = subprocess.run(
        [cmd_name, "--headless", "--convert-to", "docx",
         "--outdir", str(odt_path.parent), str(odt_path)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"LibreOffice conversion failed: {result.stderr}")
    new_path = odt_path.with_suffix(".docx")
    if not new_path.exists():
        raise RuntimeError(f"Expected {new_path} after conversion, not found")
    return new_path


def fetch_all(*, download_dir: Path = CHAPTERS_DIR, source_url: str = SOURCE_URL) -> Manifest:
    download_dir.mkdir(parents=True, exist_ok=True)
    session = cloudscraper.create_scraper()
    resp = session.get(source_url)
    resp.raise_for_status()
    docs, update_date = parse_listing(resp.text, base_url=source_url)

    sources: list[SourceDoc] = []
    for d in docs:
        # Prefer docx; fall back to odt + convert
        if d.docx_url:
            url = d.docx_url
            ext = "docx"
        elif d.odt_url:
            url = d.odt_url
            ext = "odt"
        else:
            continue  # neither — skip
        fname = _safe_filename(d.title, update_date, ext)
        out_path = download_dir / fname
        if not out_path.exists():
            r = session.get(url, stream=True)
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)

        # Convert if needed
        if ext == "odt":
            out_path = _convert_odt_to_docx(out_path)

        sources.append(SourceDoc(
            path=out_path, url=url,
            display_name=d.title, update_date_iso=update_date,
        ))
    return Manifest(update_date_iso=update_date, documents=tuple(sources))


def _safe_filename(display_name: str, update_date: date, ext: str = "docx") -> str:
    name = re.sub(r"\.(docx|odt)$", "", display_name, flags=re.IGNORECASE)
    name = re.sub(r"[^\w\.\-一-鿿]", "_", name).strip("._")
    roc = update_date.year - 1911
    suffix = f"_{roc}{update_date.month:02d}{update_date.day:02d}"
    return f"{name}{suffix}.{ext}"
```

**A4. Update the existing fetch test** (`tests/test_fetch.py`)

The existing `parse_listing` test now returns a different shape. Update:

```python
def test_parse_listing_finds_documents_and_update_date():
    html = (Path(__file__).parent / "fixtures" / "listing_page.html").read_text(encoding="utf-8")
    docs, update_date_iso = parse_listing(html, base_url="https://www.nhi.gov.tw/ch/cp-7593-ad2a9-3397-1.html")
    assert len(docs) > 40
    # At least one document available only as ODT (e.g. 通則, 第六節)
    odt_only = [d for d in docs if d.odt_url and not d.docx_url]
    assert len(odt_only) >= 2, f"expected ≥2 odt-only documents, got {len(odt_only)}"
    # Confirm 通則 and 第六節 are among them
    titles = [d.title for d in odt_only]
    assert any("通則" in t for t in titles), f"通則 missing from odt-only: {titles}"
    assert any("第六節" in t for t in titles), f"第六節 missing from odt-only: {titles}"
    assert update_date_iso.year >= 2024
```

**A5. Verify LibreOffice is installed**

```bash
which libreoffice || which soffice
```

If neither: `brew install --cask libreoffice` (one-time setup). Document in CLAUDE.md.

**A6. Run tests, commit**

```bash
cd /Users/shin/Projects/nhi-knowledge-extractor
uv run pytest tests/test_fetch.py -v
git add src/nhi_extractor/config.py src/nhi_extractor/fetch.py tests/test_fetch.py
git commit -m "fix(fetch): support ODT-only documents (通則, 第六節) via LibreOffice conversion"
```

---

## Task B — Commit DOCX source files (Issue 2)

**Problem:** `data/regulations/medication/chapters/` is in `.gitignore`. User wants source DOCX preserved in repo for traceability.

### Steps

**B1. Remove chapters from .gitignore**

Edit `/Users/shin/Projects/nhi-knowledge-extractor/.gitignore`, delete the line:

```
data/regulations/medication/chapters/
```

**B2. Commit the existing DOCX files**

```bash
cd /Users/shin/Projects/nhi-knowledge-extractor
git add .gitignore data/regulations/medication/chapters/
git commit -m "chore: track downloaded DOCX source files in repo for traceability"
```

The release zips and release folders remain gitignored — only the upstream sources are committed.

---

## Task C — Fix blank lines in content (Issue 4)

**Problem:** `render_node_to_markdown` joins blocks with `"\n\n"`, creating a blank line between every paragraph when viewed as CSV cell content.

### Files

- Modify: `src/nhi_extractor/markdown.py`
- Modify: `tests/test_markdown.py`

### Steps

**C1. Change the join to single newline**

In `src/nhi_extractor/markdown.py`, change the last line of `render_node_to_markdown`:

```python
def render_node_to_markdown(node: Node) -> str:
    parts: list[str] = [f"## {node.heading}"]
    for block in node.body:
        parts.append(_block_to_markdown(block))
    for child in node.children:
        parts.append(render_node_to_markdown(child))
    return "\n".join(p for p in parts if p)  # was "\n\n"
```

Tables internally still use `\n` between header/separator/rows — that's fine. The fix is only for the inter-block join.

**C2. Update the test for `test_render_node_to_markdown_recurses_into_children`**

The existing test asserts ordering (parent intro before child text). That still passes. But add a new test:

```python
def test_render_node_to_markdown_no_blank_lines_between_paragraphs():
    n = Node(
        heading="9.1.",
        level=(9, 1),
        body=[Paragraph(text="段落一"), Paragraph(text="段落二"), Paragraph(text="段落三")],
    )
    md = render_node_to_markdown(n)
    # No blank line: between adjacent paragraphs, only a single newline separates them
    assert "段落一\n段落二\n段落三" in md
    assert "段落一\n\n段落二" not in md
```

**C3. Run tests + smoke-test the output**

```bash
cd /Users/shin/Projects/nhi-knowledge-extractor
uv run pytest tests/test_markdown.py -v
# Re-run a chunk to eyeball the content
uv run nhi-extract chunk tests/fixtures/section_3_normal.docx | head -5
```

**C4. Commit**

```bash
git add src/nhi_extractor/markdown.py tests/test_markdown.py
git commit -m "fix(markdown): use single newline between blocks (no blank lines in CSV content)"
```

---

## Task D — Numbered-item-aware multi-block splitter (Issue 5)

**Problem:** Strategy 1 of `split_leaf` only fires for single-paragraph leaves. Real regulations like `9.69.` have multiple paragraphs + an embedded table. They fall through to Strategy 3 (greedy paragraph accumulation) which has no awareness of `1.`/`2.`/`3.` semantic boundaries — splitting mid-numbered-item and orphaning the table.

**Design:** Before Strategy 1, add a new **Strategy 0** that handles multi-block leaves by:

1. Scanning all body blocks
2. Identifying paragraphs that START with a top-level `^(\d+)\.\s` numbered item
3. Grouping consecutive blocks under whichever numbered item is "open"
4. Each group becomes one chunk

Tables and non-numbered paragraphs travel with the most recently opened numbered item (or the preamble if no item has been opened yet).

If a single group still exceeds HARD_BUDGET, recurse with the existing Strategy 3 character-split for that group only.

### Files

- Modify: `src/nhi_extractor/chunk.py`
- Modify: `tests/test_chunk_leaf.py`

### Steps

**D1. Write failing test**

Add to `tests/test_chunk_leaf.py`:

```python
def test_split_leaf_multiblock_with_numbered_items_and_table():
    """A real-world shape: heading + (1. ...) paragraph + table + (2. ...) paragraph.
    The table belongs with item 1 (its descriptive prose). Each chunk should contain
    one complete numbered item, with the table living with item 1.
    """
    leaf = Node(
        heading="9.69. 免疫檢查點抑制劑",
        level=(9, 69),
        body=[
            Paragraph(text="1. 本類藥品說明，包含 (1)黑色素瘤 (2)非小細胞肺癌等子項目。"),
            Paragraph(text="續論：詳細表格如下，列出各藥品適應症對照。"),
            Table(header=["給付範圍", "pembrolizumab", "nivolumab"],
                  rows=[["黑色素瘤", "可", "可"], ["肺癌", "可", "可"]], caption=None),
            Paragraph(text="2. 第二項規定的內容如此這般。"),
            Paragraph(text="3. 第三項。"),
        ],
    )
    chunks = split_leaf(leaf, ancestors=[Node(heading="第9節", level=())],
                       section_number=9, target_budget=200)
    # At least 3 chunks (one per top-level item 1/2/3), maybe 4 if preamble exists
    assert len(chunks) >= 3
    # The chunk containing item 1 must also contain the table
    item1_chunks = [c for c in chunks if "1. 本類藥品" in c.content_md]
    assert item1_chunks, f"no chunk contains item 1; ids={[c.item_id for c in chunks]}"
    assert any("給付範圍" in c.content_md for c in item1_chunks), (
        "table must travel with the item-1 chunk (its descriptive prose), "
        f"got item-1 chunks without table: {[c.content_md[:100] for c in item1_chunks]}"
    )
    # No chunk should contain a fragment of item 1 AND a fragment of item 2
    for c in chunks:
        if "1. 本類藥品" in c.content_md:
            assert "2. 第二項" not in c.content_md, (
                f"chunk {c.item_id} mixes items 1 and 2 — violates self-contained rule"
            )


def test_split_leaf_multiblock_falls_back_when_no_numbered_items():
    """If body has multiple blocks but no top-level numbered items, fall back to
    the old paragraph-accumulation behaviour."""
    leaf = Node(
        heading="9.99.",
        level=(9, 99),
        body=[
            Paragraph(text="段落一。" * 20),
            Paragraph(text="段落二。" * 20),
            Paragraph(text="段落三。" * 20),
        ],
    )
    chunks = split_leaf(leaf, ancestors=[Node(heading="第9節", level=())],
                       section_number=9, target_budget=40)
    assert len(chunks) >= 2
```

**D2. Implement Strategy 0**

In `src/nhi_extractor/chunk.py`, add a new helper above `split_leaf`:

```python
# Top-level numbered item — exactly the prefix the user wants to split on.
# Must be at the START of a paragraph's text (not embedded in the middle).
TOP_LEVEL_ITEM_RE = re.compile(r"^(\d+)\.\s")


def _group_blocks_by_numbered_item(body: list) -> list[list] | None:
    """Walk body blocks. Whenever a Paragraph starts with `^N.\s` (top-level
    numbered item), start a new group. Everything that follows (including tables
    and continuation paragraphs) attaches to that group until the next `N.` starts.

    Returns:
      - List of groups (each group is a list of blocks) if ≥2 numbered items found
      - None if fewer than 2 (not splittable this way)

    The first group may be a "preamble" (blocks before the first numbered item),
    which the caller can decide to discard or prepend.
    """
    groups: list[list] = [[]]  # start with empty preamble group
    item_starts_found = 0
    for block in body:
        if isinstance(block, Paragraph) and TOP_LEVEL_ITEM_RE.match(block.text):
            groups.append([block])
            item_starts_found += 1
        else:
            groups[-1].append(block)
    if item_starts_found < 2:
        return None
    # Drop empty preamble if no preamble blocks
    if not groups[0]:
        groups = groups[1:]
    return groups
```

Then update `split_leaf` to try Strategy 0 first:

```python
def split_leaf(
    leaf: Node,
    *,
    ancestors: list[Node],
    section_number: int | None,
    source: SourceDoc | None = None,
    target_budget: int = None,
) -> list[Item]:
    from .config import TARGET_BUDGET
    target_budget = target_budget if target_budget is not None else TARGET_BUDGET

    if source is None:
        from datetime import date
        from pathlib import Path
        source = SourceDoc(
            path=Path("test.docx"), url="", display_name="test",
            update_date_iso=date(1970, 1, 1),
        )

    base_id = make_item_id(section_number, leaf.level)
    section_path = format_section_path(leaf, ancestors)
    heading_prefix = f"## {leaf.heading}\n"  # single newline now (Task C consistency)

    # ------- Strategy 0: multi-block numbered-item grouping (NEW) -------
    groups = _group_blocks_by_numbered_item(leaf.body)
    if groups is not None:
        items: list[Item] = []
        for i, group in enumerate(groups, start=1):
            rendered_blocks: list[str] = []
            for b in group:
                if isinstance(b, Paragraph):
                    rendered_blocks.append(b.text)
                else:
                    rendered_blocks.append(table_to_markdown(b))
            content = heading_prefix + "\n".join(rendered_blocks)
            items.append(_make_chunk_item(
                base_id=base_id, part_index=i, suffix="part",
                heading=leaf.heading, section_path=section_path,
                content_md=content, source=source,
            ))
        # If any chunk still exceeds HARD_BUDGET, recursively character-split THAT chunk.
        # (Spec: aim for budget but never silently violate it.)
        from .config import HARD_BUDGET
        out: list[Item] = []
        for it in items:
            if it.token_count <= HARD_BUDGET:
                out.append(it)
            else:
                out.extend(_char_split_item(it, target_budget))
        return out

    # ------- Strategy 1: single-paragraph numbered-list (existing) -------
    if len(leaf.body) == 1 and isinstance(leaf.body[0], Paragraph):
        pieces = _split_paragraph_by_numbered_list(leaf.body[0])
        if pieces:
            items = []
            for i, piece in enumerate(pieces, start=1):
                content = f"{heading_prefix}{piece}"
                items.append(_make_chunk_item(
                    base_id=base_id, part_index=i, suffix="part",
                    heading=leaf.heading, section_path=section_path,
                    content_md=content, source=source,
                ))
            return items

    # ------- Strategy 2: single oversize table (existing) -------
    if len(leaf.body) == 1 and isinstance(leaf.body[0], Table):
        slices = _split_table_by_rows(leaf.body[0], target_budget=target_budget)
        items = []
        for i, t in enumerate(slices, start=1):
            content = f"{heading_prefix}{table_to_markdown(t)}"
            items.append(_make_chunk_item(
                base_id=base_id, part_index=i, suffix="tbl",
                heading=leaf.heading, section_path=section_path,
                content_md=content, source=source,
            ))
        return items

    # ------- Strategy 3: greedy paragraph accumulation (existing) -------
    # [keep existing strategy 3 code]
```

Also extract the existing character-split logic from inside the strategy-3 fallback into a reusable `_char_split_item(item, target_budget)` helper so Strategy 0 can call it for oversized chunks.

**D3. Run tests**

```bash
cd /Users/shin/Projects/nhi-knowledge-extractor
uv run pytest tests/test_chunk_leaf.py -v
uv run pytest tests/test_chunk_pain_cases.py -v
uv run pytest -v  # full sweep
```

The full sweep must stay green. The pain-case test for §9 row 85 must still pass (the table is still preserved — just attached to its descriptive prose chunk instead of orphaned).

**D4. Eyeball the 9.69 output**

```bash
cd /Users/shin/Projects/nhi-knowledge-extractor
uv run nhi-extract sync --skip-fetch
python3 -c "
import csv
with open('data/regulations/medication/藥品給付規定_20260424/第九節_抗癌瘤藥物_115.4.23更新_1150424.csv', encoding='utf-8-sig') as f:
    rows = [r for r in csv.DictReader(f) if r['item_id'].startswith('sec9-9.69-')]
for r in rows:
    print(f'=== {r[\"item_id\"]} ===')
    # Show first numbered item in this chunk
    import re
    for line in r['content'].split('\n'):
        if re.match(r'^\d+\.', line):
            print(f'  starts: {line[:80]}')
            break
    print(f'  has table: {\"|\" in r[\"content\"] and \"---\" in r[\"content\"]}')
    print(f'  length: {len(r[\"content\"])} chars')
"
```

Expected: each chunk corresponds to one numbered item, the table appears in whichever chunk has its descriptive prose, no chunk mixes numbered items.

**D5. Commit**

```bash
git add src/nhi_extractor/chunk.py tests/test_chunk_leaf.py
git commit -m "fix(chunk): split multi-block leaves at top-level numbered items (1./2./3.)

Strategy 0: when a leaf has multiple body blocks AND ≥2 paragraphs start
with top-level numbered items (^N.\\s), group blocks by which item they
belong to. Tables and continuation paragraphs travel with the numbered
item they describe. Each chunk is self-contained.

Fixes 9.69. immune-checkpoint-inhibitor regulation where the drug ×
indication table was orphaned from its descriptive prose."
```

---

## Task E — Bonus: clean up `-dup` band-aid

While we're touching `parse.py`, fix the tilde-reference misclassification surfaced in the original Task 9 (cross-references like `"4.1~3項規定..."` get parsed as headings, triggering `-dup` suffix logic in `chunk_document`).

### Files

- Modify: `src/nhi_extractor/parse.py` — reject tilde-references in `_detect_heading_level`
- Modify: `src/nhi_extractor/chunk.py` — remove the `-dup` collision band-aid (now unnecessary)
- Add: regression test

### Steps

**E1. Add tilde-reference rejection in `parse.py`**

In `_detect_heading_level`, before the existing numeric-prefix match, add:

```python
TILDE_REFERENCE_RE = re.compile(r"^\d+\.\d+~\d+")

def _detect_heading_level(p: DocxParagraph) -> tuple[int, ...] | None:
    style_name = (p.style.name or "") if p.style else ""
    text = (p.text or "").strip()

    # Exception: tilde cross-references like "4.1~3項規定" are NOT headings.
    if TILDE_REFERENCE_RE.match(text):
        return None

    # ... rest unchanged
```

**E2. Add regression test**

In `tests/test_parse.py`:

```python
def test_parse_tilde_reference_not_treated_as_heading(fixture_section_9):
    """Cross-references like '4.1~3項規定' must not be parsed as headings.
    This was the cause of '-dup' band-aid IDs in the chunker."""
    doc = parse_docx(_make_source(fixture_section_9))

    def walk(node):
        out = [node]
        for c in node.children:
            out.extend(walk(c))
        return out

    all_headings = [n.heading for n in walk(doc.root)]
    tilde_headings = [h for h in all_headings if "~" in h and any(c.isdigit() for c in h[:5])]
    assert not tilde_headings, f"tilde cross-references parsed as headings: {tilde_headings}"
```

**E3. Remove `-dup` collision band-aid from `chunk_document`**

In `chunk.py`, locate the post-collection dedup logic the implementer added and revert it:

```python
def chunk_document(doc) -> list[Item]:
    from .config import HARD_BUDGET, TARGET_BUDGET
    items: list[Item] = []
    for child in doc.root.children:
        items.extend(_chunk_node(
            child,
            ancestors=[doc.root],
            section_number=doc.section_number,
            source=doc.source,
            target_budget=TARGET_BUDGET,
        ))

    # Budget contract
    over = [i for i in items if i.token_count > HARD_BUDGET]
    if over:
        ids = ", ".join(f"{i.item_id}({i.token_count})" for i in over)
        raise ValueError(
            f"Budget contract violated — {len(over)} items exceed HARD_BUDGET={HARD_BUDGET}: {ids}"
        )

    # Uniqueness contract: with parser fixed, IDs should be naturally unique.
    ids = [i.item_id for i in items]
    if len(set(ids)) != len(ids):
        from collections import Counter
        dups = {k: v for k, v in Counter(ids).items() if v > 1}
        raise ValueError(f"Duplicate item_ids: {dups}")

    return items
```

**E4. Run all tests**

```bash
uv run pytest -v
```

If any test fails due to a now-removed `-dup` ID assertion, update the assertion to expect the natural unique ID.

**E5. Commit**

```bash
git add src/nhi_extractor/parse.py src/nhi_extractor/chunk.py tests/test_parse.py
git commit -m "fix(parse): reject tilde cross-references as headings; remove -dup band-aid"
```

---

## Task F — Full E2E smoke + sanity checks

After Tasks A–E are committed, do a final end-to-end against the live NHI site to confirm everything works.

```bash
cd /Users/shin/Projects/nhi-knowledge-extractor

# Clean previous release artefacts (NOT chapters/ — those are now committed)
rm -f data/regulations/medication/藥品給付規定_*.zip
rm -rf data/regulations/medication/藥品給付規定_*/

uv run nhi-extract sync
```

Verify:

1. `data/regulations/medication/藥品給付規定_YYYYMMDD/` contains a CSV for 通則
2. Same folder contains 第六節_呼吸道藥物 CSV
3. Open `第九節_*.csv`, find `sec9-9.69-part*` rows: each is a self-contained numbered item; the table is with the `1.` chunk
4. Open any CSV in Excel: `content` column has no blank lines between paragraphs
5. `git status data/regulations/medication/chapters/` shows new files (any new conversions) but the existing committed ones unchanged
6. `uv run pytest -v` all green

Commit any CHANGELOG.md updates from the smoke run.

---

## Execution order

A → B → C → D → E → F. Tasks A and B are independent; C, D, E touch chunker/parser code in sequence and should be done in order to avoid merge conflicts.
