"""Verified author-facing history of one committed chapter review."""

import json
from hashlib import sha256

from pydantic import BaseModel, ConfigDict

from backend.domain.finalization import (
    FinalizationChangeSet, QualityReportPayload, change_set_hash, change_set_payload,
)
from backend.domain.json_contracts import canonical_hash
from backend.repositories.manuscripts import decode_finalized_authority, require_equal_pin
from backend.services.workbench import WorkbenchProjectMissing


class WorkbenchReviewMissing(LookupError):
    pass


class WorkbenchReviewSummary(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    projectId: str
    chapterNumber: int
    finalizationId: str
    canonRevision: int
    summary: str
    qualityReport: dict
    canonEvents: list[dict]
    storyProgressEvents: list[dict]
    planningPatches: list[dict]


def _json(value, expected):
    if isinstance(value, (str, bytes, bytearray)):
        value = json.loads(value)
    if type(value) is not expected:
        raise ValueError('invalid persisted review document')
    return value


def _evidence(value, prose):
    if value is None:
        return None
    start, end = value['startScalar'], value['endScalar']
    if end > len(prose):
        raise ValueError('review evidence is outside finalized prose')
    excerpt = prose[start:end]
    if sha256(excerpt.encode('utf-8')).hexdigest() != value['excerptHash']:
        raise ValueError('review evidence hash differs')
    return {**value, 'excerpt': excerpt, 'verified': True}


def _planning_nodes(planning):
    for volume in planning.volumes:
        yield ('volume', volume.id), volume
    for plot in planning.plots:
        yield ('plot', plot.id), plot
    for block in planning.story_blocks:
        yield ('story_block', block.id), block
        for stage in block.stages:
            yield ('stage', stage.id), stage
            for task in stage.scene_tasks:
                yield ('scene_task', task.id), task


class WorkbenchReviewReader:
    def __init__(self, repository, connection_factory):
        self.repository = repository
        self.connection_factory = connection_factory

    async def review(self, project_id, number):
        if type(number) is not int or not 1 <= number <= 2147483647:
            raise ValueError('invalid chapter number')
        async with self.connection_factory() as session:
            if await self.repository.project(session, project_id) is None:
                raise WorkbenchProjectMissing()
            row = await self.repository.chapter(session, project_id, number)
            if row is None:
                raise WorkbenchReviewMissing()
            authority = decode_finalized_authority(row, expected_project_id=project_id)
            if authority.chapter_number != number:
                raise ValueError('review chapter differs')
            for names in (
                ('final_project_id', 'record_project_id', 'attempt_project_id', 'revision_project_id', 'quality_project_id', 'canon_project_id'),
                ('final_session_id', 'record_session_id', 'attempt_session_id', 'quality_session_id'),
                ('final_candidate_id', 'record_candidate_id', 'attempt_candidate_id', 'quality_candidate_id'),
                ('final_finalization_id', 'record_id'),
                ('record_change_set_id', 'attempt_id', 'revision_change_set_id', 'canon_source_id'),
                ('record_revision', 'revision_number', 'attempt_current_revision', 'attempt_confirmed_revision'),
                ('record_hash', 'revision_hash', 'attempt_current_hash', 'attempt_confirmed_hash'),
                ('final_content_hash', 'record_candidate_hash', 'attempt_candidate_hash', 'quality_candidate_hash'),
                ('final_canon_revision', 'record_committed_canon', 'canon_revision'),
                ('record_expected_canon', 'attempt_expected_canon', 'quality_expected_canon'),
                ('final_planning_hash', 'attempt_planning_hash', 'quality_planning_hash'),
                ('final_outline_hash', 'attempt_outline_hash', 'quality_outline_hash'),
                ('attempt_context_hash', 'quality_context_hash'),
                ('attempt_quality_id', 'quality_id'),
            ):
                require_equal_pin(row, *names)
            if (row['attempt_status'] != 'committed' or row['canon_source_type'] != 'finalization'
                    or type(row['record_committed_canon']) is not int
                    or type(row['record_expected_canon']) is not int
                    or row['record_committed_canon'] != row['record_expected_canon'] + 1):
                raise ValueError('review has no valid commit')
            prose = row['final_content']
            if not isinstance(prose, str) or sha256(prose.encode('utf-8')).hexdigest() != row['final_content_hash']:
                raise ValueError('finalized prose hash differs')
            if canonical_hash(_json(row['context_manifest_json'], dict)) != row['attempt_context_hash']:
                raise ValueError('review context hash differs')
            change_set = FinalizationChangeSet.model_validate(_json(row['payload_json'], dict))
            if change_set_hash(change_set) != row['record_hash']:
                raise ValueError('review changeset hash differs')
            quality = QualityReportPayload.model_validate({
                'status': row['quality_status'],
                'deterministicBlocks': _json(row['deterministic_blocks_json'], list),
                'findings': _json(row['findings_json'], list),
            }).model_dump(mode='json', by_alias=True)
            if canonical_hash(quality) != row['quality_hash']:
                raise ValueError('review quality hash differs')
            # The commit gate never permits deterministic blocks to be accepted.
            if quality['deterministicBlocks']:
                raise ValueError('committed review contains deterministic blocks')
            from backend.domain.finalization_identity import finalization_storage_id
            scoped = {item.id: finalization_storage_id(project_id, row['attempt_id'], "entity", item.id)
                      for item in change_set.entities}
            ids = tuple(sorted(set(change_set.existing_entity_ids) | set(scoped) | set(scoped.values())))
            entities = await self.repository.entities(session, project_id, row['canon_revision'], ids)
            found = {item['id'] for item in entities}
            resolved = {raw: target if target in found else raw for raw, target in scoped.items()}
            if (len(found) != len(entities) or not found <= set(ids)
                    or not (set(change_set.existing_entity_ids) | set(resolved.values())) <= found):
                raise ValueError('review entities are incomplete')
            if any(item['project_id'] != project_id or not isinstance(item['canonical_name'], str) or not item['canonical_name'].strip() for item in entities):
                raise ValueError('review entities differ')
            names = {item['id']: item['canonical_name'] for item in entities}
            names.update({raw: names[target] for raw, target in resolved.items()})
            if any(names[item.id] != item.canonical_name for item in change_set.entities):
                raise ValueError('committed entity name differs')
            nodes = dict(_planning_nodes(authority.planning))
            payload = change_set_payload(change_set)
            for finding in quality['findings']:
                finding['evidence'] = _evidence(finding['evidence'], prose)
            quality['contentHash'] = row['quality_hash']
            for event in payload['canonEvents']:
                event['entityName'] = names.get(event['entityId']) if event['entityId'] is not None else None
                event['evidence'] = _evidence(event['evidence'], prose)
            for event in (*payload['storyProgressEvents'], *payload['planningPatches']):
                node = nodes.get((event['targetType'], event['targetId']))
                if node is None:
                    raise ValueError('review planning target is missing')
                if 'expectedRevision' in event and (node.revision != event['expectedRevision'] or node.content_hash != event['expectedHash']):
                    raise ValueError('review planning patch pin differs')
                event['targetTitle'] = node.task if event['targetType'] == 'scene_task' else node.title
                event['evidence'] = _evidence(event['evidence'], prose)
            # Suggestions are not part of this summary, but their evidence must
            # still belong to the exact committed prose before accepting JSON.
            for suggestion in payload['planningSuggestions']:
                _evidence(suggestion['evidence'], prose)
            return WorkbenchReviewSummary(
                projectId=project_id, chapterNumber=number, finalizationId=row['record_id'],
                canonRevision=row['canon_revision'], summary=change_set.summary,
                qualityReport=quality, canonEvents=payload['canonEvents'],
                storyProgressEvents=payload['storyProgressEvents'], planningPatches=payload['planningPatches'],
            )
