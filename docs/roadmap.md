# Future Plans

Categorised by priority and stance toward YAGNI. Status here reflects 2026-08-27 (post-v0.1.2).

## P0 — Demand-triggered (currently YAGNI)

Do not start until a real user need surfaces.

| Item | Trigger | Estimate | Design status |
|---|---|---|---|
| **Task G — appendix forms (附表) structured CSV** | A downstream RAG user reports "appendix X not found" | 1–2 days | Drafted in `docs/next-fixes.md` Task G |
| **`--allow-over-budget` flag** | Embedding model upgrade + user insists on "one drug class per row" for 9.69-style cases | 0.5 day | Designed (Q2 (b) path in `docs/emit-depth-plan.md`) |
| **PDF-only document handling** | Appendix 13 / 15 specifically requested | 1 day | Sub-problem of Task G |

## P1 — Public-repo polish (post-push)

Run these once the repo is live on GitHub.

| Item | Why | Estimate |
|---|---|---|
| `gh repo create … --push` | Make the repo a public asset | 5 min — **done in this session** |
| README badges (CI, license, Python version) | Standard public-repo signaling | 10 min — **done** |
| `CONTRIBUTING.md` | Required when accepting outside PRs | 30 min — **done** |
| GitHub Actions CI (pytest) | Auto-gate PRs | 30 min — **done in this session** |
| Add `ruff check` to CI | Style + dead-code guardrail | 30 min — **done** |
| Add `mypy src/` to CI | Type-drift guardrail | 2–4 hr — **done, and strict** |
| PyPI release | `pip install nhi-knowledge-extractor` instead of cloning | 1 hr (trusted publisher setup) |
| **Docs revision — succinct + more approachable** | 1223 lines across `docs/` + `README.md` + `CLAUDE.md` + `CONTRIBUTING.md`, and `CLAUDE.md` asks a contributor to read **five** docs in order before any non-trivial change. `docs/spec.md` alone is 327 lines. The content is accurate but the on-ramp is heavy, and several docs restate each other (the pain cases and the Cloudflare lesson each appear in three places). Scope: shorten, de-duplicate, put a genuine 5-minute path first, and make each doc state plainly who it is for. Accuracy is not the problem — **do not trade correctness for brevity**, and do not delete a recorded lesson just because it is repeated; consolidate it to one home and link | 0.5–1 day |

## P2 — Code-quality (raise the bar)

| Item | Pain it solves | Estimate |
|---|---|---|
| **ruff** | Unified style, catch unused imports | 30 min — **done** (`E,F,I,UP,B,SIM`) |
| **mypy strict** | Catch type drift; some functions still un-annotated | 2–4 hr — **done, no per-module exemptions** |
| **pre-commit hooks** | Gate at local commit, not just CI | 30 min — **done** (`.pre-commit-config.yaml`; pre-commit = hygiene + ruff + mypy, pre-push = tests + coverage) |
| **Coverage threshold + badge** | Encourage tests with new features | 30 min — **done** (`fail_under = 90`, actual 92.5%; badge asserts `≥90%` so it cannot go stale) |
| **Codebase review & optimization** | No sweep has been done since the module split. Concrete starting points, all observed 2026-08-27: `chunk.py` has **8 function-level imports** (`from .config import TARGET_BUDGET/HARD_BUDGET/EMIT_DEPTH` ×4, `dataclasses.replace` ×2, `collections.defaultdict`, `datetime`+`pathlib`) with **no circular-import justification** — the module already imports `.config` at line 15, so these are leftovers; `chunk.py` is the largest module at 263 statements and holds the most intricate algorithm; `cli.py` sits at 71% coverage (lowest — error and interactive paths untested) and `parse.py` at 87%. Scope: dead code, redundant imports, extract-function on the chunker's longest paths, and raise the two low-coverage modules. **Not** a rewrite — the token-budget contract and `item_id` scheme stay untouched | 1–2 days |

## P3 — Feature expansion (changes how the tool is used)

| Item | Description | Estimate |
|---|---|---|
| **Richer `--diff`** | Show paragraph-level diff, not just added/modified/removed lists | 1 day |
| **Multi-release sync** | Crawl N past NHI releases, produce a time-series dataset | 2 days |
| **MANIFEST audit fields** | per-doc `max_depth_in_tree`, `emit_depth_used`, polluted-row count | 0.5 day |
| **`chunk --verbose`** | Show budget utilisation, parent_id groupings per row | 0.5 day |
| **Per-section stats dashboard** | A self-contained HTML visualisation of a release | 1–2 days |
| **MCP server — evaluate feasibility first** | Serve a release to MCP clients (coding agents, LLM desktop apps) so "which regulation covers Pembrolizumab?" is answerable without standing up a RAG stack. **Step 1 is an evaluation, not a build**: name the client, and say what MCP gives that handing the CSV to an existing RAG pipeline does not. Only scope the build if that answer is concrete. Sibling prior art: `taiwan-fda-mcp`, `dmc-data-context` | 0.5 day to evaluate |

## P4 — Cross-project integration (downstream / upstream)

| Item | Description | Where it lives |
|---|---|---|
| **RAG hydration sample** | LangChain `ParentDocumentRetriever` / LlamaIndex `AutoMergingRetriever` example | downstream RAG repo, not here |
| **Bulk ingestion into RAG backend** | Script in the consuming RAG service to ingest a release zip | consuming repo |
| **Medical-LLM backend integration** | Reference link from a medical assistant to specific NHI items | consuming repo |
| **Drug-info API cross-reference** | Drug query API surfaces the matching regulation link / summary | sibling drug-info repo |

## P5 — Pipeline robustness

| Item | Trigger | Estimate |
|---|---|---|
| `fetch` retry / backoff for 429 | Rate limiting only. TLS-fingerprint 403s are already handled by the candidate walk + catalog sweep, and timeouts now abort deliberately (`NetworkUnreachable`) — see `docs/spec.md` §5 | 0.25 day |
| Schema migration script | When CSV columns change and we need to migrate old releases | 0.5 day |
| Scheduled weekly sync (cron / CI workflow) | Auto-fetch + diff + notify. Also the only *unattended* guard against fetch breakage: `pytest -m live` can now detect a Cloudflare block, but nothing runs it on a schedule, so a block still surfaces only when someone runs `sync` by hand | 0.5 day |
| Incident log on failed sync | Traceability | 0.25 day |
| Retire `_char_split_oversized` | It's a band-aid for a pathological test; remove once spec confirms it's unreachable | 0.5 day |

## P6 — Ideas box (record, may never do)

- Other NHI regulation classes (醫材給付, 特材給付, 診療規範) — separate project or expansion?
- English translation (LLM-assisted, but medical accuracy is risky)
- Appendix → JSON Schema for hospital form generation (huge effort, unclear demand)
- Historical version lookup ("Pembrolizumab regulation diff between 110/1/1 and 113/12/1")
- GraphQL / REST API wrapper around the CSV (over-engineering; CSV is enough today)

---

## Recommended sequence (whenever the project is touched again)

1. P5 scheduled sync — the only thing that would run `pytest -m live` unattended, and
   therefore the only unattended guard against the fetch breaking again
2. P1 docs revision — the guardrails are in place, so the remaining barrier to anyone
   else using or contributing to this is the 1223-line on-ramp
3. P2 codebase review & optimization — cheapest right after the docs pass, while the
   structure is fresh in mind
4. Confirm downstream RAG integration works with current 11-column schema + hydration pattern
5. Wait for demand to drive P0 items (don't pre-build)

Feature-complete for its stated scope. 137 / 137 offline tests green at 92.5% line
coverage (gate: 90%), plus `ruff`, `mypy --strict` and the opt-in `pytest -m live`. Last pipeline check: full
`nhi-extract sync` on 2026-08-27 — NHI release 2026-08-21, 16 documents, 575 items,
max 5907 tokens per row, diff vs prior `+25 / ~13 / -1`, zip produced. The last full
audit against all five spec §7 success criteria was PR #8; this run confirms the
end-to-end shape, not each criterion individually.
