# Contributing

Thanks for looking at this project. It converts Taiwan NHI medication regulation
documents into RAG-ingestion-ready CSVs; the full design lives in
[`docs/spec.md`](docs/spec.md), and [`CLAUDE.md`](CLAUDE.md) is the orientation
guide for both human contributors and AI coding agents.

## Setup

```bash
git clone https://github.com/shin13/nhi-knowledge-extractor.git
cd nhi-knowledge-extractor
uv sync
```

No system binaries are required — ODT is parsed natively via `zipfile` + `lxml`,
so there is no LibreOffice or `antiword` dependency to install.

## The three gates

CI runs all three on every pull request. Run them locally before pushing:

```bash
uv run ruff check src/ tests/
uv run mypy
uv run pytest
```

`mypy` runs in `strict` mode with no per-module exemptions. If you add a module,
it is expected to type-check cleanly rather than be added to an ignore list.

## The live test

`uv run pytest` is offline and deterministic — `tests/test_fetch.py` mocks the
HTTP session, so **a green test run is not evidence that fetching works.**

NHI sits behind Cloudflare, which gates on the TLS fingerprint. If you change
anything in `fetch.py` or `config.IMPERSONATE_CANDIDATES`, run the opt-in live
test as well and say so in the PR:

```bash
uv run pytest -m live
```

If you are diagnosing a 403, measure with **n ≥ 10 requests per profile and
interleave the targets** before drawing a conclusion. A single sample cannot
distinguish a blocked fingerprint from ordinary flakiness, and this repo has
twice recorded a wrong diagnosis made from one.

## Contracts that must not be quietly broken

These are enforced in code and covered by tests. If a change requires altering
one, say so explicitly in the PR rather than relaxing it in passing.

- **The token budget is a contract.** `chunk_document` raises `ValueError` if any
  emitted item exceeds `HARD_BUDGET` (7000). Do not catch and ignore it.
- **`item_id` collisions are a hard error**, not a warning. Diff stability across
  NHI releases depends on IDs being unique and stable.
- **CSV content cells contain no blank lines.** `\n\n` renders as empty rows in
  downstream RAG, so every join site uses `\n`.
- **All paths and tunables live in `src/nhi_extractor/config.py`.** Do not
  hardcode them elsewhere.
- **`fetch._catalog_candidates` swallows every exception on purpose.** It reads
  undocumented `curl_cffi` internals; degrading to the pinned candidate list is
  the intended behaviour, and a crash there would be worse than the 403 it exists
  to route around. Please do not "clean up" that bare `except`.

## Tests

Write the failing test first. `tests/test_chunk_pain_cases.py` is the regression
net for the two cases the predecessor had to fix by hand every release — never
disable it.

One responsibility per file. When a module's tests grow unwieldy, split them into
several focused files (`test_<module>_<topic>.py`) rather than growing one file to
match the module.

## Pull requests

`main` is protected — no direct pushes.

1. Branch off `main`.
2. Make the change, with tests.
3. Open a PR. CI must be green.
4. Squash merge.

Keep independent fixes in independent PRs. It costs a little more setup and makes
each change reviewable and revertible on its own.
