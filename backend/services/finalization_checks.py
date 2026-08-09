"""Deterministic hard prechecks for one frozen finalization Candidate."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any

from backend.domain.finalization import (
    DeterministicBlock,
    EvidenceLocation,
    FinalizationAuthority,
    HardBlockCode,
)
from backend.domain.json_contracts import canonical_hash


_BASIS_KEYS = (
    "schemaVersion",
    "outlineRevisionId",
    "outlineRevision",
    "outlineHash",
    "planningRevisionId",
    "planningRevision",
    "planningHash",
    "canonRevision",
    "projectionRevision",
    "projectionHash",
)
_COPY_WINDOW = 120
_MAX_REFERENCE_SCALARS = 2_000_000
_ROLLING_BASE = 257
_ROLLING_MASK = (1 << 64) - 1


_MESSAGES = {
    HardBlockCode.CANON_CONFLICT: "Canon 或 Projection revision 已变化",
    HardBlockCode.EMPTY_CANDIDATE: "候选正文为空",
    HardBlockCode.TECHNICAL_TRUNCATION: "候选带有明确的技术截断标记",
    HardBlockCode.CANDIDATE_HASH_DRIFT: "候选内容或冻结基线校验失败",
    HardBlockCode.SESSION_DRIFT: "章节会话所有权或状态已变化",
    HardBlockCode.PLANNING_DRIFT: "Planning authority 已变化",
    HardBlockCode.OUTLINE_DRIFT: "Chapter Outline authority 已变化",
    HardBlockCode.DETERMINISTIC_COPY: "候选命中本地参考语料的长段确定性复制检查",
    HardBlockCode.PRECHECK_INCOMPLETE: "必要的确定性前置检查未完成",
}


def _text_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _block(
    code: HardBlockCode,
    *,
    evidence: EvidenceLocation | None = None,
) -> DeterministicBlock:
    return DeterministicBlock(
        code=code,
        message=_MESSAGES[code],
        evidence=evidence,
    )


def _append_once(
    blocks: list[DeterministicBlock],
    code: HardBlockCode,
    *,
    evidence: EvidenceLocation | None = None,
) -> None:
    if any(item.code is code for item in blocks):
        return
    blocks.append(_block(code, evidence=evidence))


def _basis_is_valid(candidate: Mapping[str, Any], authority, current) -> bool:
    provenance = candidate.get("provenance")
    if not isinstance(provenance, Mapping):
        return False
    try:
        basis = {key: provenance[key] for key in _BASIS_KEYS}
    except KeyError:
        return False
    if basis.get("schemaVersion") != "candidate-basis-v1":
        return False
    try:
        if candidate.get("basis_hash") != canonical_hash(basis):
            return False
    except (TypeError, ValueError):
        return False
    return (
        basis.get("canonRevision") == authority.expected_canon_revision
        and basis.get("canonRevision") == current.get("canon_revision")
        and basis.get("projectionRevision") == current.get("projection_revision")
        and basis.get("projectionHash") == current.get("projection_hash")
        and basis.get("planningHash") == authority.expected_planning_hash
        and basis.get("planningHash") == current.get("planning_hash")
        and basis.get("outlineHash") == authority.expected_outline_hash
        and basis.get("outlineHash") == current.get("outline_hash")
    )


def _normalized(value: str) -> tuple[str, tuple[int, ...]]:
    characters: list[str] = []
    positions: list[int] = []
    for index, character in enumerate(value):
        if character.isalnum():
            characters.append(character.casefold())
            positions.append(index)
    return "".join(characters), tuple(positions)


def _window_hashes(value: str, size: int):
    if len(value) < size:
        return
    power = pow(_ROLLING_BASE, size - 1, 1 << 64)
    current = 0
    for character in value[:size]:
        current = ((current * _ROLLING_BASE) + ord(character)) & _ROLLING_MASK
    yield 0, current
    for index in range(size, len(value)):
        outgoing = ord(value[index - size])
        current = (current - (outgoing * power)) & _ROLLING_MASK
        current = ((current * _ROLLING_BASE) + ord(value[index])) & _ROLLING_MASK
        yield index - size + 1, current


def _copy_evidence(
    candidate_content: str,
    sources: Sequence[Mapping[str, Any]],
) -> tuple[EvidenceLocation | None, bool]:
    normalized_candidate, candidate_positions = _normalized(candidate_content)
    source_values: list[tuple[str, str]] = []
    total_scalars = 0
    for row in sources:
        if not isinstance(row, Mapping):
            return None, False
        source_id = row.get("id")
        content = row.get("content")
        content_hash = row.get("content_hash")
        if (
            not isinstance(source_id, str)
            or not source_id.strip()
            or not isinstance(content, str)
            or not isinstance(content_hash, str)
            or _text_hash(content) != content_hash
        ):
            return None, False
        total_scalars += len(content)
        if total_scalars > _MAX_REFERENCE_SCALARS:
            return None, False
        normalized_source, _ = _normalized(content)
        source_values.append((source_id, normalized_source))

    index: dict[int, list[tuple[int, int]]] = {}
    for source_index, (_, normalized_source) in enumerate(source_values):
        for offset, digest in _window_hashes(normalized_source, _COPY_WINDOW) or ():
            bucket = index.setdefault(digest, [])
            if not bucket:
                bucket.append((source_index, offset))
                continue
            existing_source_index, existing_offset = bucket[0]
            existing_value = source_values[existing_source_index][1][
                existing_offset:existing_offset + _COPY_WINDOW
            ]
            candidate_value = normalized_source[offset:offset + _COPY_WINDOW]
            if candidate_value != existing_value:
                bucket.append((source_index, offset))

    for offset, digest in _window_hashes(normalized_candidate, _COPY_WINDOW) or ():
        window = normalized_candidate[offset:offset + _COPY_WINDOW]
        for source_index, source_offset in index.get(digest, ()):
            normalized_source = source_values[source_index][1]
            if window != normalized_source[
                source_offset:source_offset + _COPY_WINDOW
            ]:
                continue
            start = candidate_positions[offset]
            end = candidate_positions[offset + _COPY_WINDOW - 1] + 1
            excerpt_hash = _text_hash(candidate_content[start:end])
            return EvidenceLocation.model_validate({
                "startScalar": start,
                "endScalar": end,
                "excerptHash": excerpt_hash,
                "confidence": 1.0,
                "rationale": "本地参考语料归一化后连续 120 字符一致",
            }), True
    return None, True


def run_finalization_prechecks(
    authority: FinalizationAuthority,
    *,
    session: Mapping[str, Any],
    candidate: Mapping[str, Any],
    current_authority: Mapping[str, Any],
    reference_sources: Sequence[Mapping[str, Any]],
    copy_check_completed: bool,
) -> tuple[DeterministicBlock, ...]:
    """Return only provable hard blocks, in stable public order."""

    if type(authority) is not FinalizationAuthority:
        raise TypeError("authority must be a FinalizationAuthority")
    if not all(
        isinstance(value, Mapping)
        for value in (session, candidate, current_authority)
    ):
        raise TypeError("finalization precheck rows must be mappings")
    if type(copy_check_completed) is not bool:
        raise TypeError("copy_check_completed must be a boolean")

    blocks: list[DeterministicBlock] = []
    if (
        session.get("id") != authority.chapter_session_id
        or session.get("project_id") != authority.project_id
        or session.get("status") != "drafting"
        or session.get("active_draft_operation_id") is not None
        or session.get("expected_canon_revision")
        != authority.expected_canon_revision
        or session.get("planning_hash") != authority.expected_planning_hash
        or session.get("chapter_outline_hash") != authority.expected_outline_hash
        or candidate.get("id") != authority.candidate_id
        or candidate.get("project_id") != authority.project_id
        or candidate.get("chapter_session_id") != authority.chapter_session_id
    ):
        _append_once(blocks, HardBlockCode.SESSION_DRIFT)

    content = candidate.get("content")
    content_hash = candidate.get("content_hash")
    if (
        not isinstance(content, str)
        or not isinstance(content_hash, str)
        or content_hash != authority.candidate_hash
        or (isinstance(content, str) and _text_hash(content) != content_hash)
        or not _basis_is_valid(candidate, authority, current_authority)
    ):
        _append_once(blocks, HardBlockCode.CANDIDATE_HASH_DRIFT)
    if not isinstance(content, str) or not content.strip():
        _append_once(blocks, HardBlockCode.EMPTY_CANDIDATE)

    canon_revision = current_authority.get("canon_revision")
    if (
        canon_revision != authority.expected_canon_revision
        or current_authority.get("projection_revision") != canon_revision
        or not isinstance(current_authority.get("projection_hash"), str)
    ):
        _append_once(blocks, HardBlockCode.CANON_CONFLICT)
    if current_authority.get("planning_hash") != authority.expected_planning_hash:
        _append_once(blocks, HardBlockCode.PLANNING_DRIFT)
    if current_authority.get("outline_hash") != authority.expected_outline_hash:
        _append_once(blocks, HardBlockCode.OUTLINE_DRIFT)

    provenance = candidate.get("provenance")
    if (
        isinstance(provenance, Mapping)
        and (
            provenance.get("technicalTruncation") is True
            or provenance.get("completionStatus") == "truncated"
        )
    ):
        _append_once(blocks, HardBlockCode.TECHNICAL_TRUNCATION)

    if not copy_check_completed:
        _append_once(blocks, HardBlockCode.PRECHECK_INCOMPLETE)
    elif isinstance(content, str):
        evidence, completed = _copy_evidence(content, reference_sources)
        if not completed:
            _append_once(blocks, HardBlockCode.PRECHECK_INCOMPLETE)
        elif evidence is not None:
            _append_once(
                blocks,
                HardBlockCode.DETERMINISTIC_COPY,
                evidence=evidence,
            )
    return tuple(blocks)


__all__ = ["run_finalization_prechecks"]
