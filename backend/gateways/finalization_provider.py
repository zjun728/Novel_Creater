"""Narrow safe Provider boundaries for quality advice and one extraction."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from hashlib import sha256
from typing import Protocol, runtime_checkable

import httpx
from pydantic import ValidationError

from backend.domain.finalization import (
    FinalizationChangeSet,
    PlanningPatch,
    QualityFinding,
    QualityReportPayload,
    change_set_payload,
)
from backend.domain.finalization_evidence import source_paragraphs
from backend.domain.json_contracts import canonical_json
from backend.gateways.openai_json_transport import OpenAIJSONTransport
from backend.prompts.finalization import (
    FinalizationProviderManifest,
    build_extraction_messages,
    build_quality_messages,
    build_progress_audit_messages,
    _progress_scope,
)


PROVIDER_TIMEOUT_SECONDS = 600
MAX_PROVIDER_RESPONSE_BYTES = 512 * 1024
_SAFE_ERROR = "Finalization provider failed"
_EVIDENCE_FIELDS = frozenset({
    "quote", "confidence", "rationale",
})
_PARAGRAPH_EVIDENCE_FIELDS = frozenset({"paragraphIds", "confidence", "rationale"})
_PARAGRAPH_RANGE_EVIDENCE_FIELDS = frozenset({"paragraphRange", "confidence", "rationale"})


class FinalizationProviderError(RuntimeError):
    """One fixed content-free failure category."""


def _raise_safe_error() -> None:
    raise FinalizationProviderError(_SAFE_ERROR) from None


def _raise_cancelled() -> None:
    raise asyncio.CancelledError()


@runtime_checkable
class FinalizationQualityProvider(Protocol):
    async def audit(
        self,
        *,
        provider: Mapping[str, object],
        model_name: str,
        manifest: FinalizationProviderManifest,
    ) -> tuple[QualityFinding, ...]: ...


@runtime_checkable
class FinalizationExtractionProvider(Protocol):
    async def extract(
        self,
        *,
        provider: Mapping[str, object],
        model_name: str,
        manifest: FinalizationProviderManifest,
    ) -> FinalizationChangeSet: ...


def _hydrate_evidence(value: object, prose: str) -> dict[str, object]:
    if type(value) is not dict or frozenset(value.keys()) not in (_EVIDENCE_FIELDS, _PARAGRAPH_EVIDENCE_FIELDS, _PARAGRAPH_RANGE_EVIDENCE_FIELDS):
        raise ValueError(_SAFE_ERROR)
    if 'paragraphRange' in value:
        selected = value['paragraphRange']
        if type(selected) is not dict or frozenset(selected) != {'start', 'end'}:
            raise ValueError(_SAFE_ERROR)
        paragraphs = source_paragraphs(prose)
        positions = {paragraph['id']: index for index, paragraph in enumerate(paragraphs)}
        if any(type(selected[key]) is not str or selected[key] not in positions for key in ('start', 'end')):
            raise ValueError(_SAFE_ERROR)
        first, last = positions[selected['start']], positions[selected['end']]
        if first > last:
            raise ValueError(_SAFE_ERROR)
        start, end = paragraphs[first]['startScalar'], paragraphs[last]['endScalar']
    elif 'paragraphIds' in value:
        ids = value['paragraphIds']
        paragraphs = source_paragraphs(prose)
        positions = {paragraph['id']: index for index, paragraph in enumerate(paragraphs)}
        if type(ids) is not list or not ids or any(type(item) is not str or item not in positions for item in ids):
            raise ValueError(_SAFE_ERROR)
        indexes = [positions[item] for item in ids]
        if indexes != list(range(indexes[0], indexes[0] + len(indexes))):
            raise ValueError(_SAFE_ERROR)
        start, end = paragraphs[indexes[0]]['startScalar'], paragraphs[indexes[-1]]['endScalar']
    else:
        quote = value["quote"]
        if not isinstance(quote, str) or not quote.strip():
            raise ValueError(_SAFE_ERROR)
        start = prose.find(quote)
        if start < 0 or prose.find(quote, start + 1) >= 0:
            raise ValueError(_SAFE_ERROR)
        end = start + len(quote)
    confidence = value["confidence"]
    if (
        type(start) is not int
        or type(end) is not int
        or start < 0
        or end <= start
        or end > len(prose)
        or type(confidence) not in (int, float)
        or type(confidence) is bool
    ):
        raise ValueError(_SAFE_ERROR)
    rationale = value["rationale"]
    if not isinstance(rationale, str):
        raise ValueError(_SAFE_ERROR)
    # A rationale cannot rely on paragraph references outside the stored quote.
    paragraphs_by_id = {p['id']: p for p in source_paragraphs(prose)}
    for reference in re.findall(r"(?<![A-Za-z0-9_])p\d+(?![A-Za-z0-9_])", rationale):
        paragraph = paragraphs_by_id.get(reference)
        if paragraph is None:
            raise ValueError(_SAFE_ERROR)
        start = min(start, paragraph['startScalar'])
        end = max(end, paragraph['endScalar'])
    excerpt_hash = sha256(prose[start:end].encode("utf-8")).hexdigest()
    return {
        "startScalar": start,
        "endScalar": end,
        "excerptHash": excerpt_hash,
        "confidence": float(confidence),
        "rationale": value["rationale"],
    }


def _hydrate_nested(value: object, prose: str) -> object:
    if type(value) is list:
        return [_hydrate_nested(item, prose) for item in value]
    if type(value) is dict:
        result = {}
        for key, item in value.items():
            # Fact values and Planning replacements are opaque strict JSON.
            # Their own keys (including "evidence") are content, not locations.
            if key in {"value", "replacement"}:
                result[key] = item
                continue
            result[key] = (
                _hydrate_evidence(item, prose)
                if key == "evidence"
                else _hydrate_nested(item, prose)
            )
        return result
    return value


def _drop_planning_patches_with_disallowed_fields(value: object) -> object:
    if type(value) is not dict or type(value.get("planningPatches")) is not list:
        return value
    result = dict(value)
    kept = []
    for item in value["planningPatches"]:
        try:
            PlanningPatch.model_validate(item)
        except ValidationError as error:
            issues = error.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )
            if (
                len(issues) == 1
                and issues[0].get("loc") == ()
                and issues[0].get("type") == "value_error"
                and issues[0].get("msg") == (
                    "Value error, planning fieldPath is not allowed "
                    "for targetType"
                )
            ):
                continue
        kept.append(item)
    result["planningPatches"] = kept
    return result


def _parse_quality(value: object, prose: str) -> tuple[QualityFinding, ...] | None:
    try:
        if type(value) is not dict or frozenset(value.keys()) != {"findings"}:
            raise ValueError(_SAFE_ERROR)
        if type(value["findings"]) is not list:
            raise ValueError(_SAFE_ERROR)
        if any(not isinstance(item, dict) or item.get('severity') not in ('required', 'suggested', 'optional') for item in value['findings']):
            raise ValueError(_SAFE_ERROR)
        hydrated = _hydrate_nested(value["findings"], prose)
        report = QualityReportPayload.model_validate({
            "status": "completed",
            "deterministicBlocks": [],
            "findings": hydrated,
        })
        return report.findings
    except (ValidationError, ValueError, TypeError, KeyError, UnicodeError):
        return None


def _parse_extraction(value: object, prose: str) -> FinalizationChangeSet | None:
    try:
        value = _validate_progress_basis(value, prose)
        hydrated = _hydrate_nested(value, prose)
        hydrated = _drop_planning_patches_with_disallowed_fields(hydrated)
        parsed = FinalizationChangeSet.model_validate(hydrated)
        # Only coalesce the same assertion at the same source location. Validate
        # identities first; never hide a malformed response or merge transitions.
        seen = set()
        events = []
        for event, key in zip(parsed.canon_events, change_set_payload(parsed)["canonEvents"]):
            key.pop("id")
            key["evidence"].pop("rationale")
            key["evidence"].pop("confidence")
            signature = canonical_json(key)
            if signature not in seen:
                seen.add(signature)
                events.append(event)
        return parsed.model_copy(update={"canon_events": tuple(events)})
    except (ValidationError, ValueError, TypeError, KeyError, UnicodeError):
        return None


def _validate_progress_basis(value: object, prose: str) -> object:
    """Validate transient model reasoning without extending persisted ChangeSets."""
    if type(value) is not dict or type(value.get('storyProgressEvents')) is not list:
        raise ValueError(_SAFE_ERROR)
    result = dict(value)
    events = []
    paragraphs = {p['id']: p for p in source_paragraphs(prose)}
    for event in value['storyProgressEvents']:
        if type(event) is not dict:
            raise ValueError(_SAFE_ERROR)
        clean = dict(event)
        basis = clean.pop('completionBasis', None)
        if type(basis) is not dict or set(basis) != {'execution', 'unmetRequirements', 'supportingParagraphIds'}:
            raise ValueError(_SAFE_ERROR)
        execution = basis['execution']
        unmet = basis['unmetRequirements']
        support = basis['supportingParagraphIds']
        if execution not in ('observed', 'planned', 'uncertain'):
            raise ValueError(_SAFE_ERROR)
        if type(unmet) is not list or any(type(item) is not str or not item.strip() for item in unmet):
            raise ValueError(_SAFE_ERROR)
        if clean.get('status') == 'completed' and (execution != 'observed' or unmet):
            raise ValueError(_SAFE_ERROR)
        if type(support) is not list or not support or any(type(item) is not str or item not in paragraphs for item in support):
            raise ValueError(_SAFE_ERROR)
        if len(set(support)) != len(support):
            raise ValueError(_SAFE_ERROR)
        evidence = _hydrate_evidence(clean.get('evidence'), prose)
        for identity in support:
            paragraph = paragraphs[identity]
            if not (evidence['startScalar'] <= paragraph['startScalar'] and paragraph['endScalar'] <= evidence['endScalar']):
                raise ValueError(_SAFE_ERROR)
        events.append(clean)
    result['storyProgressEvents'] = events
    return result


def _apply_progress_audit(value: dict, audit: object, manifest: FinalizationProviderManifest | None = None) -> dict | None:
    """Only replace existing progress proposals; never accept additions/upgrades."""
    if type(audit) is not dict or set(audit) != {'decisions'} or type(audit['decisions']) is not list:
        return None
    proposed = {event['id']: event for event in value['storyProgressEvents'] if event['targetType'] == 'scene_task'}
    decisions = {}
    for decision in audit['decisions']:
        if type(decision) is not dict or set(decision) != {'id', 'status', 'completionBasis', 'evidence'}:
            return None
        identity = decision['id']
        if type(identity) is not str or identity not in proposed or identity in decisions:
            return None
        if decision['status'] == 'completed' and proposed[identity]['status'] != 'completed':
            return None
        decisions[identity] = decision
    if set(decisions) != set(proposed):
        return None
    events = [{**event, **decisions.get(event['id'], {})} for event in value['storyProgressEvents']]
    if manifest is not None:
        scope = _progress_scope(manifest)
        states = {task['id']: task['confirmedStatus'] for stage in scope.get('stages', [])
                  for task in stage['requiredSceneTasks']}
        states.update({e['targetId']: e['status'] for e in events if e['targetType'] == 'scene_task'})
        descendants = {('stage', stage['id']): [task['id'] for task in stage['requiredSceneTasks']]
                       for stage in scope.get('stages', [])}
        if scope.get('available'):
            descendants[('story_block', scope['storyBlockId'])] = [task for ids in descendants.values() for task in ids]
        for event in events:
            if event['targetType'] == 'scene_task' or event['status'] != 'completed':
                continue
            children = descendants.get((event['targetType'], event['targetId']))
            if children is None:
                return None
            if any(states.get(child) != 'completed' for child in children):
                # Keep the already validated source interval when replacing a
                # parent's now-obsolete "all children completed" explanation.
                location = _hydrate_evidence(event['evidence'], manifest.candidate_prose)
                referenced = [p for p in source_paragraphs(manifest.candidate_prose)
                              if p['endScalar'] > location['startScalar'] and p['startScalar'] < location['endScalar']]
                if not referenced:
                    return None
                event['status'] = 'advanced'
                event['completionBasis'] = {**event['completionBasis'], 'unmetRequirements': ['关联场景任务尚未全部完成']}
                event['evidence'] = {
                    'paragraphRange': {'start': referenced[0]['id'], 'end': referenced[-1]['id']},
                    'confidence': event['evidence']['confidence'],
                    'rationale': '本次复核后，关联场景任务尚未全部完成，父阶段或故事块仅保留推进状态。',
                }
    return {**value, 'storyProgressEvents': events}


class _FinalizationGateway:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self._resource = OpenAIJSONTransport(
            transport=transport,
            timeout_seconds=PROVIDER_TIMEOUT_SECONDS,
            response_byte_limit=MAX_PROVIDER_RESPONSE_BYTES,
        )

    async def start(self) -> None:
        try:
            await self._resource.start()
        except asyncio.CancelledError:
            _raise_cancelled()
        except Exception:
            _raise_safe_error()

    async def aclose(self) -> None:
        try:
            await self._resource.aclose()
        except asyncio.CancelledError:
            _raise_cancelled()
        except Exception:
            _raise_safe_error()

    @staticmethod
    def _validated_manifest(
        provider: Mapping[str, object],
        model_name: str,
        manifest: FinalizationProviderManifest,
    ) -> FinalizationProviderManifest:
        value = FinalizationProviderManifest.model_validate(manifest, strict=True)
        provider_id = provider.get("id") if isinstance(provider, Mapping) else None
        if (
            not isinstance(provider_id, str)
            or not isinstance(model_name, str)
            or provider_id.strip() != value.binding.provider_id
            or model_name.strip() != value.binding.model_name
        ):
            raise ValueError(_SAFE_ERROR)
        return value

    async def _request(self, *, provider, model_name, messages):
        failed = False
        cancelled = False
        result = None
        runtime_provider = dict(provider)
        runtime_provider["temperature"] = 0.0
        try:
            base_url = provider.get("base_url")
            if isinstance(base_url, str):
                host = (httpx.URL(base_url).host or "").casefold()
                if host == "deepseek.com" or host.endswith(".deepseek.com"):
                    runtime_provider["thinking"] = {"type": "disabled"}
            result = await self._resource.request(
                provider=runtime_provider,
                model_name=model_name,
                messages=messages,
            )
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            failed = True
        if result is not None and result.cancelled:
            cancelled = True
        if result is None or not result.succeeded:
            failed = True
        if cancelled:
            provider = None
            runtime_provider = None
            model_name = None
            messages = None
            result = None
            _raise_cancelled()
        if failed:
            provider = None
            runtime_provider = None
            model_name = None
            messages = None
            result = None
            _raise_safe_error()
        runtime_provider = None
        return result.value


class FinalizationQualityGateway(_FinalizationGateway):
    async def audit(
        self,
        *,
        provider: Mapping[str, object],
        model_name: str,
        manifest: FinalizationProviderManifest,
    ) -> tuple[QualityFinding, ...]:
        failed = False
        frozen = None
        messages = None
        try:
            frozen = self._validated_manifest(provider, model_name, manifest)
            messages = build_quality_messages(manifest=frozen)
        except asyncio.CancelledError:
            _raise_cancelled()
        except Exception:
            failed = True
        if failed:
            provider = None
            model_name = None
            manifest = None
            frozen = None
            messages = None
            _raise_safe_error()
        value = await self._request(
            provider=provider, model_name=model_name, messages=messages,
        )
        parsed = _parse_quality(value, frozen.candidate_prose)
        value = None
        if parsed is None:
            provider = None
            model_name = None
            manifest = None
            frozen = None
            messages = None
            _raise_safe_error()
        return parsed


class FinalizationExtractionGateway(_FinalizationGateway):
    async def extract(
        self,
        *,
        provider: Mapping[str, object],
        model_name: str,
        manifest: FinalizationProviderManifest,
    ) -> FinalizationChangeSet:
        failed = False
        frozen = None
        messages = None
        try:
            frozen = self._validated_manifest(provider, model_name, manifest)
            messages = build_extraction_messages(manifest=frozen)
        except asyncio.CancelledError:
            _raise_cancelled()
        except Exception:
            failed = True
        if failed:
            provider = None
            model_name = None
            manifest = None
            frozen = None
            messages = None
            _raise_safe_error()
        value = await self._request(
            provider=provider, model_name=model_name, messages=messages,
        )
        parsed = _parse_extraction(value, frozen.candidate_prose)
        if parsed is not None and parsed.story_progress_events:
            scene_events = [event for event in value['storyProgressEvents'] if event['targetType'] == 'scene_task']
            audit = await self._request(
                provider=provider, model_name=model_name,
                messages=build_progress_audit_messages(manifest=frozen, events=scene_events),
            ) if scene_events else {'decisions': []}
            reviewed = _apply_progress_audit(value, audit, frozen)
            parsed = _parse_extraction(reviewed, frozen.candidate_prose) if reviewed is not None else None
            audit = None
            reviewed = None
        value = None
        if parsed is None:
            provider = None
            model_name = None
            manifest = None
            frozen = None
            messages = None
            _raise_safe_error()
        return parsed


__all__ = [
    "FinalizationExtractionGateway",
    "FinalizationExtractionProvider",
    "FinalizationProviderError",
    "FinalizationQualityGateway",
    "FinalizationQualityProvider",
]
