"""Projection validation hashes describe rows and are a multiset, not identities."""

import pytest

from backend.domain.project_import_plans import _projection, read_verified_project_package
from backend.domain.project_imports import ProjectImportInvalid
from backend.domain.project_packages import build_structured_entries, canonical_line
from backend.services.project_packages import write_deterministic_zip
from backend.tests.unit.test_project_import_package_reader import _Snapshot


def validation(count=2, hashes=None):
    result = {key: {"count": 0, "hashes": []} for key in _Snapshot.projection_validation}
    result["currentStateProjections"] = {"count": count, "hashes": hashes if hashes is not None else ["a" * 64] * 2}
    return result


def test_real_zip_preflight_preserves_duplicate_projection_row_hashes(tmp_path):
    snapshot = _Snapshot()
    snapshot.projection_validation = validation()
    archive = tmp_path / "duplicate-projections.zip"
    write_deterministic_zip(archive, build_structured_entries(snapshot),
        project_logical_id=snapshot.source_project_logical_id, counts=snapshot.counts)
    package = read_verified_project_package(archive)
    assert package.summary.source_title == "测试项目"


@pytest.mark.parametrize("value", [
    validation(count=1),
    validation(hashes=["b" * 64, "a" * 64]),
    validation(hashes=["a" * 64, "invalid"]),
    validation(count=True, hashes=["a" * 64]),
])
def test_projection_validation_still_rejects_bad_count_order_hash_and_types(value):
    with pytest.raises(ProjectImportInvalid):
        _projection(canonical_line(value))
