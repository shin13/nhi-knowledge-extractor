"""Pure rendering helpers used by chunk and render stages."""

from __future__ import annotations

import functools

import tiktoken

from .config import TIKTOKEN_ENCODING
from .types import Block, Node, Paragraph, Table


@functools.lru_cache(maxsize=1)
def _encoding():
    return tiktoken.get_encoding(TIKTOKEN_ENCODING)


def count_tokens(text: str) -> int:
    """Token count using the RAG's tokenizer (cl100k_base)."""
    if not text:
        return 0
    return len(_encoding().encode(text))


def _escape_cell(s: str) -> str:
    """Escape pipes and newlines so Markdown table cells stay one-line."""
    return s.replace("|", "\\|").replace("\n", "<br>")


def table_to_markdown(table: Table) -> str:
    """Render a Table as a GitHub-flavoured Markdown table."""
    lines: list[str] = []
    if table.caption:
        lines.append(f"**{table.caption}**")
        lines.append("")
    header = " | ".join(_escape_cell(h) for h in table.header)
    lines.append(f"| {header} |")
    lines.append("| " + " | ".join(["---"] * len(table.header)) + " |")
    for row in table.rows:
        padded = list(row) + [""] * (len(table.header) - len(row))
        rendered = " | ".join(_escape_cell(c) for c in padded[: len(table.header)])
        lines.append(f"| {rendered} |")
    return "\n".join(lines)


def _block_to_markdown(block: Block) -> str:
    if isinstance(block, Paragraph):
        return block.text
    if isinstance(block, Table):
        return table_to_markdown(block)
    raise TypeError(f"Unknown block type: {type(block).__name__}")


def render_node_to_markdown(node: Node) -> str:
    """Render a node and all descendants as Markdown.

    Format:
        ## {heading}
        {body blocks}
        {recursively rendered children}
    """
    parts: list[str] = [f"## {node.heading}"]
    for block in node.body:
        parts.append(_block_to_markdown(block))
    for child in node.children:
        parts.append(render_node_to_markdown(child))
    return "\n".join(p for p in parts if p)
