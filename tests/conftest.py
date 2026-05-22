from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_section_3() -> Path:
    p = FIXTURES / "section_3_normal.docx"
    assert p.exists(), f"missing fixture: {p}"
    return p


@pytest.fixture
def fixture_section_8() -> Path:
    p = FIXTURES / "section_8_pain_case.docx"
    assert p.exists(), f"missing fixture: {p}"
    return p


@pytest.fixture
def fixture_section_9() -> Path:
    p = FIXTURES / "section_9_pain_case.docx"
    assert p.exists(), f"missing fixture: {p}"
    return p


@pytest.fixture
def fixture_tongze_odt() -> Path:
    """通則 ODT — Chinese-numeral headings, no Arabic-numeral structure."""
    p = FIXTURES / "tongze.odt"
    assert p.exists(), f"missing fixture: {p}"
    return p


@pytest.fixture
def fixture_section_6_odt() -> Path:
    """第六節 ODT — regulation with normal Arabic-numeral headings, source format is ODT."""
    p = FIXTURES / "section_6_odt.odt"
    assert p.exists(), f"missing fixture: {p}"
    return p
