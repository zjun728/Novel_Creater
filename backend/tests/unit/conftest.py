from pathlib import Path
import tempfile

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def workspace_tmp_path():
    root = REPOSITORY_ROOT / "output" / "pytest-unit"
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as directory:
        yield Path(directory)
