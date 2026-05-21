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
