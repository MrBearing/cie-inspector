from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def ws_basic() -> Path:
    return FIXTURES / "ws_basic"


@pytest.fixture()
def ws_edge() -> Path:
    return FIXTURES / "ws_edge"
