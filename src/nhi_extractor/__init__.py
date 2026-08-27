"""Convert Taiwan NHI medication regulation documents into RAG-ingestion-ready CSVs."""

from importlib.metadata import PackageNotFoundError, version

try:
    # Read from installed package metadata rather than hardcoding. pyproject.toml
    # stays the single source of truth, so this does not become a fourth place
    # the version has to be kept in sync by hand.
    __version__ = version("nhi-extractor")
except PackageNotFoundError:  # pragma: no cover - source tree with no install
    # Importable straight off `src/` without `uv sync`. Deliberately not a
    # plausible version number, so a stray copy of it is obvious in a bug report.
    __version__ = "0.0.0+not-installed"

__all__ = ["__version__"]
