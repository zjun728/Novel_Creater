"""Author decisions survive package identity rewrites without crossing reports."""
import pytest
from backend.repositories.project_packages import PROJECT_OWNED_TABLES, PROJECT_TABLE_RECORD_TYPES


def test_review_decisions_are_explicit_project_owned_author_data():
    assert "review_finding_decisions" in PROJECT_OWNED_TABLES
    assert PROJECT_TABLE_RECORD_TYPES["review_finding_decisions"] == "review-finding-decisions"

from backend.domain.review_decisions import validate_package_decisions
from backend.domain.project_packages import PackageRecord
from backend.domain.project_import_plans import _rewrite_record_data


@pytest.mark.parametrize("patch", [
    {"reportHash": None}, {"reportHash": "invalid"}, {"revision": 0}, {"revision": True}, {"updatedAt": -1},
    {"ignoredFindingIds": ["required"]}, {"ignoredFindingIds": ["another-report"]},
    {"ignoredFindingIds": ["optional", "optional"]}, {"ignoredFindingIds": "optional"},
    {"ignoredFindingIds": [1]},
])
def test_invalid_decisions_fail_closed(patch):
    data = {"reportHash": "a" * 64, "revision": 3, "updatedAt": 19, "ignoredFindingIds": ["optional"], **patch}
    with pytest.raises(ValueError):
        validate_package_decisions(data, {"status": "completed", "findings": [
            {"id": "optional", "severity": "optional"}, {"id": "required", "severity": "required"}]})


def test_decisions_rewrite_exact_finding_and_attempt_identities():
    record = PackageRecord("review-finding-decisions", "review-finding-decisions:1", data={
        "changeSetLogicalId": "finalization-change-set:1", "reportHash": "a" * 64,
        "revision": 3, "updatedAt": 19, "ignoredFindingIds": ["quality-finding:1"]})
    rewritten = _rewrite_record_data(record, {
        ("finalization-change-set", "finalization-change-set:1"): "new-attempt",
        ("quality-finding", "quality-finding:1"): "new-finding",
    }, {})
    assert rewritten["changeSetLogicalId"] == "new-attempt"
    assert rewritten["ignoredFindingIds"] == ["new-finding"]
    assert rewritten["revision"] == 3
