"""Typer CLI: `nhi-extract sync|parse|chunk|diff`."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table as RichTable

from . import config as cfg
from .chunk import chunk_document
from .diff import compute_diff
from .fetch import fetch_all
from .package import build_release
from .parse import parse_docx
from .types import Manifest, SourceDoc

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


def _build_manifest_from_chapters(chapters_dir: Path) -> Manifest:
    """When --skip-fetch is used: synthesise a Manifest from local DOCX files.
    The update_date is today's date (no website data to consult)."""
    today = date.today()
    docs: list[SourceDoc] = []
    for p in sorted(chapters_dir.glob("*.docx")):
        docs.append(SourceDoc(
            path=p, url="", display_name=p.stem, update_date_iso=today,
        ))
    if not docs:
        raise typer.BadParameter(f"No .docx found in {chapters_dir}")
    return Manifest(update_date_iso=today, documents=tuple(docs))


@app.command()
def sync(
    skip_fetch: bool = typer.Option(False, "--skip-fetch", help="Use already-downloaded DOCX."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Build but don't write the zip."),
) -> None:
    """Full pipeline: fetch -> parse -> chunk -> render -> package."""
    manifest = _build_manifest_from_chapters(cfg.CHAPTERS_DIR) if skip_fetch else fetch_all()
    console.print(f"[bold]Fetched:[/bold] {len(manifest.documents)} documents, release date {manifest.update_date_iso}")
    if manifest.skipped_documents:
        by_reason: dict[str, int] = {}
        for s in manifest.skipped_documents:
            by_reason[s.reason] = by_reason.get(s.reason, 0) + 1
        summary = ", ".join(f"{n} {r}" for r, n in sorted(by_reason.items()))
        console.print(f"[dim]Skipped {len(manifest.skipped_documents)} ({summary}) — see MANIFEST.json[/dim]")

    all_items = []
    for source in manifest.documents:
        doc = parse_docx(source)
        items = chunk_document(doc)
        all_items.extend(items)
        console.print(f"  {source.path.name}: {len(items)} items")

    max_tokens = max(i.token_count for i in all_items) if all_items else 0
    console.print(f"[bold]Total:[/bold] {len(all_items)} items, max token count {max_tokens}")

    if dry_run:
        console.print("[yellow]--dry-run: skipping write[/yellow]")
        return

    result = build_release(
        items=all_items,
        release_date=manifest.update_date_iso,
        data_dir=cfg.DATA_DIR,
        changelog_path=cfg.CHANGELOG_PATH,
        skipped_documents=manifest.skipped_documents,
    )
    console.print(f"[green]Wrote:[/green] {result.zip_path}")
    console.print(
        f"Diff vs prior: +{len(result.diff.added)} / ~{len(result.diff.modified)} / -{len(result.diff.removed)}"
    )


@app.command("parse")
def cmd_parse(docx_path: Path) -> None:
    """Debug: parse one DOCX and print the Document tree."""
    sd = SourceDoc(path=docx_path, url="", display_name=docx_path.stem, update_date_iso=date.today())
    doc = parse_docx(sd)
    console.print(f"[bold]Title:[/bold] {doc.title}")
    console.print(f"[bold]Section:[/bold] {doc.section_number}")

    def walk(n, depth=0):
        prefix = "  " * depth
        console.print(f"{prefix}- {n.heading}  (level={n.level}, body={len(n.body)}, children={len(n.children)})")
        for c in n.children:
            walk(c, depth + 1)
    walk(doc.root)


@app.command("chunk")
def cmd_chunk(docx_path: Path) -> None:
    """Debug: parse + chunk one DOCX and print all emitted items."""
    sd = SourceDoc(path=docx_path, url="", display_name=docx_path.stem, update_date_iso=date.today())
    doc = parse_docx(sd)
    items = chunk_document(doc)
    table = RichTable(title=f"{doc.title} -- {len(items)} items")
    table.add_column("item_id")
    table.add_column("tokens", justify="right")
    table.add_column("heading")
    for it in items:
        table.add_row(it.item_id, str(it.token_count), it.heading[:60])
    console.print(table)


@app.command("diff")
def cmd_diff(release_a: Path, release_b: Path) -> None:
    """Diff two release folders by their MANIFEST.json."""
    a = json.loads((release_a / "MANIFEST.json").read_text(encoding="utf-8"))["items"]
    b = json.loads((release_b / "MANIFEST.json").read_text(encoding="utf-8"))["items"]
    d = compute_diff(old=a, new=b)
    console.print(f"Added:    {len(d.added)}")
    for i in d.added:
        console.print(f"  + {i}")
    console.print(f"Modified: {len(d.modified)}")
    for i in d.modified:
        console.print(f"  ~ {i}")
    console.print(f"Removed:  {len(d.removed)}")
    for i in d.removed:
        console.print(f"  - {i}")
