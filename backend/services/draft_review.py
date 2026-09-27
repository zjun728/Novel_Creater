"""Bind a full-chapter rewrite to a persisted, current review and its draft."""
from collections.abc import Mapping
import hashlib
import re
from backend.domain.review_decisions import effective_findings
from uuid import UUID


def review_reference(value):
    fields = {"attemptId", "candidateId", "candidateHash", "changeSetRevision",
              "changeSetHash", "qualityReportHash"}
    if not isinstance(value, Mapping) or set(value) not in (fields, fields | {'decisionsRevision'}):
        raise ValueError("invalid review reference")
    if 'decisionsRevision' in value and (type(value['decisionsRevision']) is not int or value['decisionsRevision'] < 0):
        raise ValueError('invalid decisions revision')
    for key in ("attemptId", "candidateId"):
        if not isinstance(value[key], str) or str(UUID(value[key])) != value[key]:
            raise ValueError("invalid review identity")
    for key in ("candidateHash", "changeSetHash", "qualityReportHash"):
        if not isinstance(value[key], str) or not re.fullmatch(r"[0-9a-f]{64}", value[key]):
            raise ValueError("invalid review hash")
    if type(value["changeSetRevision"]) is not int or value["changeSetRevision"] < 1:
        raise ValueError("invalid review revision")
    return dict(value)


def current_review_report(reference, bundle, authority, draft):
    attempt, view, candidate = bundle["attempt"], bundle["view"], bundle["candidate"]
    chapter = authority["session"]
    report, changes = view["qualityReport"], view["changeSet"]
    decisions = view.get('findingDecisions') or {'revision': 0, 'ignoredFindingIds': []}
    if reference.get('decisionsRevision', 0) != decisions['revision']:
        raise ValueError('review decisions changed')
    if (
        attempt["id"] != reference["attemptId"]
        or attempt["status"] != "awaiting_author" or attempt["active_slot"] != 1
        or view["status"] != "awaiting_author"
        or view["attemptId"] != reference["attemptId"]
        or view["candidateId"] != reference["candidateId"]
        or view["candidateHash"] != reference["candidateHash"]
        or changes["revision"] != reference["changeSetRevision"]
        or changes["contentHash"] != reference["changeSetHash"]
        or report["contentHash"] != reference["qualityReportHash"]
        or report["status"] != "completed"
        or not (report["findings"] or report["deterministicBlocks"])
        or candidate["id"] != reference["candidateId"]
        or candidate["project_id"] != chapter["project_id"]
        or candidate["chapter_session_id"] != chapter["id"]
        or candidate["content_hash"] != reference["candidateHash"]
        or draft["content_hash"] != reference["candidateHash"]
        or candidate["content"] != draft["content"]
        or hashlib.sha256(candidate["content"].encode("utf-8")).hexdigest() != reference["candidateHash"]
        or attempt["expected_canon_revision"] != authority["projection"]["canonRevision"]
        or attempt["expected_canon_revision"] != chapter["expected_canon_revision"]
        or attempt["expected_planning_hash"] != chapter["planning_hash"]
        or attempt["expected_planning_hash"] != authority["outline"]["currentPlanning"]["contentHash"]
        or attempt["expected_outline_hash"] != chapter["chapter_outline_hash"]
        or attempt["expected_outline_hash"] != authority["outline"]["contentHash"]
    ):
        raise ValueError("review no longer applies to this draft")
    findings = effective_findings(report, decisions)
    if not findings and not report['deterministicBlocks']:
        raise ValueError('no effective review findings')
    return {**report, 'findings': findings}
