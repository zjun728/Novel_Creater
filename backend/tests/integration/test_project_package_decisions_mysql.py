"""Real isolated MySQL export/import/re-export preserves author review decisions."""
import json
from dataclasses import replace
from hashlib import sha256
import pytest
from backend.domain.project_import_plans import _validate_graph
from backend.domain.project_imports import ProjectImportInvalid
from backend.domain.json_contracts import canonical_hash
from backend.tests.integration.test_continuity_issue_packages_mysql import (
    PROJECT_ID, _seed_finalized_project, _packages, _lifecycle, _publish,
)
from backend.tests.integration.test_project_package_review_history_mysql import _assert_restored_reviews_readable


@pytest.mark.mysql
@pytest.mark.asyncio
@pytest.mark.parametrize("ignore", [True, False])
async def test_author_decisions_round_trip(disposable_mysql, monkeypatch, tmp_path, ignore):
    transaction = await _seed_finalized_project(disposable_mysql, monkeypatch)
    async with transaction() as session:
        reviews = await session.fetchall("SELECT s.id,s.quality_report_id,q.status,q.deterministic_blocks_json,c.content FROM finalization_change_sets s JOIN candidate_quality_reports q ON q.id=s.quality_report_id JOIN draft_candidates c ON c.id=s.draft_candidate_id WHERE s.project_id=%s ORDER BY s.id", (PROJECT_ID,))
        assert len(reviews) >= 2
        for review in reviews:
            finding = {"id": "same-id-in-distinct-reports", "severity": "optional", "dimension": "continuity",
                "reason": "An optional clarification", "suggestedAction": "Clarify if desired",
                "evidence": {"startScalar": 0, "endScalar": 1, "excerptHash": sha256(review["content"][0].encode()).hexdigest(), "confidence": 1.0, "rationale": "Opening character"}}
            report_hash = canonical_hash({"status": review["status"], "deterministicBlocks": json.loads(review["deterministic_blocks_json"]), "findings": [finding]})
            await session.execute("UPDATE candidate_quality_reports SET findings_json=%s,content_hash=%s WHERE project_id=%s AND id=%s", (json.dumps([finding]), report_hash, PROJECT_ID, review["quality_report_id"]))
            await session.execute("INSERT INTO review_finding_decisions (project_id,attempt_id,report_hash,revision,ignored_finding_ids_json,updated_at) VALUES (%s,%s,%s,3,%s,19)", (PROJECT_ID, review["id"], report_hash, json.dumps([finding["id"]] if ignore else [])))
    lifecycle = await _lifecycle(transaction).get(PROJECT_ID)
    async with _packages(disposable_mysql, tmp_path) as export:
        package = await export(PROJECT_ID, lifecycle.lifecycle_revision)
        records = [r for r in package.graph_index.values() if r.entity_type == "review-finding-decisions"]
        assert len(records) == len(reviews)
        # A valid archive graph cannot use a decision from another report,
        # an obsolete digest, duplicate rows, or a required finding.
        original = records[0]
        graph = tuple(package.graph_index.values())
        attempt = package.graph_index[("finalization-change-set", original.data["changeSetLogicalId"])]
        quality = package.graph_index[("candidate-quality", attempt.data["qualityReportLogicalId"])]
        other = records[1]
        other_attempt = package.graph_index[("finalization-change-set", other.data["changeSetLogicalId"])]
        other_quality = package.graph_index[("candidate-quality", other_attempt.data["qualityReportLogicalId"])]
        for patch in ({"reportHash": "0" * 64},
                      {"ignoredFindingIds": [other_quality.data["findings"][0]["id"]]},
                      {"ignoredFindingIds": [quality.data["findings"][0]["id"]] * 2}):
            bad = replace(original, data={**original.data, **patch})
            with pytest.raises(ProjectImportInvalid):
                _validate_graph(tuple(bad if item is original else item for item in graph))
        duplicate = replace(original, logical_id="review-finding-decisions:999")
        with pytest.raises(ProjectImportInvalid):
            _validate_graph((*graph, duplicate))
        required = replace(quality, data={**quality.data, "findings": [
            {**quality.data["findings"][0], "severity": "required"}]})
        bad = replace(original, data={**original.data, "ignoredFindingIds": [quality.data["findings"][0]["id"]]})
        with pytest.raises(ProjectImportInvalid):
            _validate_graph(tuple(required if item is quality else bad if item is original else item for item in graph))
        plan = await _publish(package, transaction)
        async with transaction() as session:
            restored = await session.fetchall("SELECT d.*,q.content_hash,q.findings_json FROM review_finding_decisions d JOIN finalization_change_sets s ON s.id=d.attempt_id AND s.project_id=d.project_id JOIN candidate_quality_reports q ON q.id=s.quality_report_id WHERE d.project_id=%s", (plan.target_project_id,))
        assert len(restored) == len(reviews)
        for row in restored:
            assert row["revision"] == 3 and row["updated_at"] == 19
            assert row["report_hash"] == row["content_hash"]
            findings = json.loads(row["findings_json"])
            assert findings[0]["id"] != "same-id-in-distinct-reports"
            assert json.loads(row["ignored_finding_ids_json"]) == ([findings[0]["id"]] if ignore else [])
            assert row["attempt_id"] not in {r["id"] for r in reviews}
        await _assert_restored_reviews_readable(transaction, plan.target_project_id)
        target_lifecycle = await _lifecycle(transaction).get(plan.target_project_id)
        again = await export(plan.target_project_id, target_lifecycle.lifecycle_revision)
        again_records = [r for r in again.graph_index.values() if r.entity_type == "review-finding-decisions"]
        assert len(again_records) == len(records)
        assert all(r.data["revision"] == 3 and len(r.data["ignoredFindingIds"]) == int(ignore) for r in again_records)
