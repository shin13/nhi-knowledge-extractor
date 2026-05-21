from datetime import date

from typer.testing import CliRunner

from nhi_extractor.cli import app

runner = CliRunner()


def test_cli_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("sync", "parse", "chunk", "diff"):
        assert cmd in result.output


def test_cli_parse_subcommand(fixture_section_3):
    result = runner.invoke(app, ["parse", str(fixture_section_3)])
    assert result.exit_code == 0
    assert "第3節" in result.output  # title


def test_cli_chunk_subcommand(fixture_section_3):
    result = runner.invoke(app, ["chunk", str(fixture_section_3)])
    assert result.exit_code == 0
    assert "sec3-" in result.output


def test_cli_sync_skip_fetch_dry_run(tmp_path, monkeypatch, fixture_section_3, fixture_section_8, fixture_section_9):
    import nhi_extractor.config as cfg
    monkeypatch.setattr(cfg, "CHAPTERS_DIR", fixture_section_3.parent)
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(cfg, "CHANGELOG_PATH", tmp_path / "CHANGELOG.md")

    result = runner.invoke(app, ["sync", "--skip-fetch", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "items" in result.output.lower()
    assert not (tmp_path / "data").exists() or not list((tmp_path / "data").rglob("*.zip"))
