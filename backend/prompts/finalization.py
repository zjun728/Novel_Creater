"""Closed prompt manifests for quality audit and one finalization extraction."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.domain.json_contracts import canonical_json
from backend.domain.finalization_evidence import source_paragraphs
from backend.prompts.planning import validate_planning_story_context_candidate


FINALIZATION_MAX_MANIFEST_BYTES = 384 * 1024
FINALIZATION_MAX_PROMPT_BYTES = 512 * 1024
_HASH_PATTERN = r"^[0-9a-f]{64}$"
_SAFE_ERROR = "Finalization prompt input invalid"
_STRICT = ConfigDict(
    strict=True,
    frozen=True,
    extra="forbid",
    hide_input_in_errors=True,
)


class FinalizationBinding(BaseModel):
    model_config = _STRICT

    provider_id: str = Field(min_length=1, max_length=100)
    model_name: str = Field(min_length=1, max_length=200)
    provider_profile_revision: int = Field(ge=0)


class FinalizationProviderManifest(BaseModel):
    model_config = _STRICT

    schema_version: Literal["finalization-provider-v1"] = (
        "finalization-provider-v1"
    )
    chapter_number: int = Field(ge=1)
    candidate_hash: str = Field(pattern=_HASH_PATTERN)
    candidate_prose: str = Field(min_length=1, max_length=100_000)
    canon_context: dict[str, object]
    planning_context: dict[str, object]
    outline_context: dict[str, object]
    contract_context: dict[str, object]
    bible_context: dict[str, object]
    policy_version: str = Field(min_length=1, max_length=32)
    binding: FinalizationBinding

    @field_validator(
        "canon_context",
        "planning_context",
        "outline_context",
        "contract_context",
        "bible_context",
        mode="before",
    )
    @classmethod
    def validate_strict_json_object(cls, value):
        if type(value) is not dict:
            raise ValueError(_SAFE_ERROR)
        try:
            rendered = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            return json.loads(rendered)
        except (UnicodeError, TypeError, ValueError, RecursionError):
            raise ValueError(_SAFE_ERROR) from None

    @model_validator(mode="after")
    def validate_frozen_safe_manifest(self) -> Self:
        if sha256(self.candidate_prose.encode("utf-8")).hexdigest() != self.candidate_hash:
            raise ValueError(_SAFE_ERROR)
        snapshot = self.model_dump(mode="json")
        try:
            validate_planning_story_context_candidate(snapshot)
            rendered = canonical_json(snapshot).encode("utf-8")
        except (UnicodeError, TypeError, ValueError, RecursionError):
            raise ValueError(_SAFE_ERROR) from None
        if len(rendered) > FINALIZATION_MAX_MANIFEST_BYTES:
            raise ValueError(_SAFE_ERROR)
        return self


def _progress_scope(manifest: FinalizationProviderManifest) -> dict[str, object]:
    """Describe existing task scope; never infer completion from chapter coverage."""
    outline = manifest.outline_context.get("content")
    planning = manifest.planning_context.get("content")
    if not isinstance(outline, dict) or not isinstance(planning, dict):
        return {"available": False}
    block_ref = outline.get("storyBlockRef")
    block_id = block_ref.get("id") if isinstance(block_ref, dict) else None
    blocks = planning.get("storyBlocks", [])
    matches = [block for block in blocks if isinstance(block, dict) and block.get("id") == block_id]
    if block_id is None or len(matches) != 1:
        return {"available": False}
    bound = {
        ref["id"] for ref in outline.get("sceneTaskRefs", [])
        if isinstance(ref, dict) and isinstance(ref.get("id"), str)
    }
    statuses = {}
    for row in manifest.canon_context.get("actualProgress", []):
        if not isinstance(row, dict) or not isinstance(row.get("payload"), dict):
            continue
        value = row["payload"]
        key = (value.get("targetType"), value.get("targetId"))
        if row.get("field_path") == f"plot.progress.{key[0]}.{key[1]}":
            statuses[key] = value.get("status")

    def status(kind, identity):
        value = statuses.get((kind, identity))
        return value if value in {"started", "advanced", "completed"} else "not_confirmed_completed"

    block = matches[0]
    stages = []
    remaining = []
    for stage in block.get("stages", []):
        # Match the existing completion guard's descendant selection exactly.
        if stage.get("lifecycle") == "archived":
            continue
        tasks = [{
            "id": task["id"], "task": task.get("task"),
            "completionEvidence": task.get("completionEvidence"),
            "boundToCurrentOutline": task["id"] in bound,
            "confirmedStatus": status("scene_task", task["id"]),
        } for task in stage.get("sceneTasks", []) if task.get("lifecycle") != "archived"]
        stage_remaining = [task["id"] for task in tasks if task["confirmedStatus"] != "completed"]
        remaining.extend(stage_remaining)
        stages.append({
            "id": stage["id"], "title": stage.get("title"), "purpose": stage.get("purpose"),
            "confirmedStatus": status("stage", stage["id"]),
            "requiredSceneTasks": tasks, "notPreviouslyCompletedTaskIds": stage_remaining,
        })
    return {
        "available": True, "boundSceneTaskIds": sorted(bound),
        "storyBlockId": block_id, "storyBlockGoal": block.get("blockGoal"),
        "confirmedStatus": status("story_block", block_id), "stages": stages,
        "notPreviouslyCompletedTaskIds": remaining,
    }


def _user_payload(manifest: FinalizationProviderManifest) -> dict[str, object]:
    return {
        "schemaVersion": manifest.schema_version,
        "chapterNumber": manifest.chapter_number,
        "candidateHash": manifest.candidate_hash,
        "candidateParagraphs": [
            {"id": paragraph['id'], "text": paragraph['text']}
            for paragraph in source_paragraphs(manifest.candidate_prose)
        ],
        "canonContext": manifest.canon_context,
        "planningContext": manifest.planning_context,
        "outlineContext": manifest.outline_context,
        "progressScope": _progress_scope(manifest),
        "contractContext": manifest.contract_context,
        "bibleContext": manifest.bible_context,
        "policyVersion": manifest.policy_version,
    }


def _messages(
    manifest: FinalizationProviderManifest,
    instruction: dict[str, object],
) -> tuple[dict[str, str], ...]:
    try:
        user_payload = _user_payload(manifest)
        if instruction.get("task") == "finalization_extraction":
            # Future scene prose is not evidence. Preserve task identities and
            # the full planning inventory, but do not invite outline retelling.
            outline = dict(manifest.outline_context)
            content = outline.get("content")
            if isinstance(content, dict):
                outline["content"] = {
                    key: value for key, value in content.items()
                    if key in {"storyBlockRef", "stageRefs", "sceneTaskRefs", "volumeRef"}
                }
            else:
                outline = {}
            user_payload["outlineContext"] = outline
            user_payload["bibleContext"] = {}
            user_payload["contractContext"] = {}
        messages = (
            {"role": "system", "content": canonical_json(instruction)},
            {"role": "user", "content": canonical_json(user_payload)},
        )
        rendered = json.dumps(
            messages,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (UnicodeError, TypeError, ValueError, RecursionError):
        raise ValueError(_SAFE_ERROR) from None
    if len(rendered) > FINALIZATION_MAX_PROMPT_BYTES:
        raise ValueError(_SAFE_ERROR)
    return messages


_PARAGRAPH_RANGE_RULES = {
    "meaning": "paragraphRange is an object with exactly start and end paragraph IDs. It denotes one complete, non-empty contiguous interval in candidateParagraphs source order, including both endpoints and every paragraph between them.",
    "exampleSourceOrder": ["p1", "p2", "p3", "p4", "p5"],
    "validExamples": [{"start": "p2", "end": "p2"}, {"start": "p2", "end": "p4"}],
    "invalidExamples": {
        "reverseOrder": {"start": "p4", "end": "p2"},
        "unknownId": {"start": "p2", "end": "p9"},
        "extraKey": {"start": "p2", "end": "p4", "middle": "p3"},
    },
    "distantEvidence": "For support spanning p2 and p4, return paragraphRange={start: p2, end: p4}; the server includes all of p2, p3 and p4 and the original separators. Do not enumerate paragraphIds, return sparse evidence points, copy prose, or calculate offsets or hashes.",
    "beforeOutput": "Check every evidence.paragraphRange before returning JSON: exactly start/end, both strings naming real supplied paragraph IDs, and start no later than end in source order. Use the same ID for a single paragraph. Select the smallest complete interval that directly supports the item. If no such interval supports the item, omit the unsupported item instead of emitting invalid evidence.",
}


def build_quality_messages(
    *,
    manifest: FinalizationProviderManifest,
) -> tuple[dict[str, str], ...]:
    value = FinalizationProviderManifest.model_validate(manifest, strict=True)
    evidence_shape = {
        "paragraphRange": {"start": "exact first paragraph id from candidateParagraphs", "end": "exact last paragraph id from candidateParagraphs"},
        "confidence": "number from 0 to 1",
        "rationale": "brief reason",
    }
    return _messages(value, {
        "task": "quality_audit",
        "language": "zh-CN",
        "response": "json_object_only",
        "mayCreateCanonFacts": False,
        "mayRewriteCandidate": False,
        "scoreGate": False,
        "reviewProcedure": [
            "First reconstruct a private event ledger from candidateParagraphs in narrative time order: actor, action, object/count, custodian, source of knowledge, and whether the action actually happened. Do not output this ledger.",
            "Check conservation of named objects and copies: opening count plus explicit additions minus explicit removals equals closing count. An original and its copy are different objects. Follow stated handovers, storage and signatures; do not invent a transfer to reconcile simultaneous incompatible locations.",
            "Compare this ledger with source-chapter-qualified Canon facts and the current outline. A newly evidenced action can change an old dynamic state; an intention, request, reported rumour or character inference cannot establish its execution or truth.",
            "Before reporting a conflict, reread all candidate paragraphs for the missing handover, explanation or later resolution. Do not invent a counterfactual interpretation (for example swapping the stated meanings of tally marks) to create a problem. Cite the smallest interval that demonstrates the real defect.",
        ],
        "findingPolicy": {
            "actionableOnly": "Every finding must identify an actual defect and a concrete necessary or useful edit. Successful checks, praise, confirmations of consistency, no-change-needed statements and speculative checks of unspecified future designs are not findings at any severity. Omit them; an empty findings array is valid.",
            "noQuota": "Dimensions are possible categories, not a checklist of output rows. Do not fill every dimension or repeat one issue in multiple dimensions.",
            "severity": "Use required for an evidenced contradiction within this candidate, against confirmed history, or against an explicit outline constraint. Use suggested for substantive but noncontradictory improvements and optional for subjective style edits. Never downgrade a genuine contradiction just to let the chapter pass.",
        },
        "requiredFindingFields": [
            "id", "dimension", "reason", "suggestedAction", "evidence",
        ],
        "evidenceFields": [
            "paragraphRange", "confidence", "rationale",
        ],
        "evidenceParagraphRange": _PARAGRAPH_RANGE_RULES,
        "dimensions": [
            "plot_effectiveness", "content_richness", "character_vitality",
            "dialogue_credibility", "emotional_naturalness", "continuity",
            "pacing", "style_stability", "ai_flavor", "reading_motivation",
        ],
        "outputShape": {
            "findings": [{
                "id": "unique finding id",
                "dimension": (
                    "plot_effectiveness|content_richness|character_vitality|"
                    "dialogue_credibility|emotional_naturalness|continuity|"
                    "pacing|style_stability|ai_flavor|reading_motivation"
                ),
                "reason": "specific reason",
                "severity": "required | suggested | optional",
                "suggestedAction": "specific action",
                "evidence": evidence_shape,
            }],
        },
        "rules": [
            "Return outputShape directly as the top-level object; never wrap it.",
            "Return an empty findings array when there is no supported finding.",
            "Select the smallest supporting paragraphRange using exact start/end IDs from candidateParagraphs. Never invent IDs or estimate offsets.",
            "Classify every finding with severity: required only for an evidence-backed contradiction of confirmed facts or explicit chapter-outline constraints; suggested for substantive improvements; optional only for subjective wording or style preferences that do not affect facts, continuity or chapter delivery.",
            "Read canonContext as history through earlier finalized chapters, not the required end state of the current chapter. Resolve relative words such as today, tomorrow or this chapter against the source chapter of each fact. A current scene may explicitly change a prior dynamic state: a person not yet transferred in chapter 1 can depart in chapter 2. Do not call that evidenced transition a contradiction or require Canon to be updated before finalization; extraction proposes the new state after this audit.",
            "Still require correction for rewriting an earlier event, changing an established count or identity without an evidenced transition, or violating a stable constraint. For example, eleven retained samples plus eleven newly collected samples total twenty-two; silently claiming eighteen is a contradiction. An unresolved thread may continue into later chapters unless the current outline explicitly requires its resolution; lack of an immediate reply is not by itself a confirmed-fact conflict.",
            "Do not infer severity from dimension alone. Required findings block author confirmation until corrected and reviewed again; the server, not the model, performs finalization. Never label subjective preferences required.",
            "Return paragraphRange only; the server supplies the exact original excerpt. Never return rewritten prose.",
        ],
    })


def build_extraction_messages(
    *,
    manifest: FinalizationProviderManifest,
) -> tuple[dict[str, str], ...]:
    value = FinalizationProviderManifest.model_validate(manifest, strict=True)
    evidence_shape = {
        "paragraphRange": {"start": "exact first paragraph id from candidateParagraphs", "end": "exact last paragraph id from candidateParagraphs"},
        "confidence": "number from 0 to 1",
        "rationale": "brief reason",
    }
    return _messages(value, {
        "task": "finalization_extraction",
        "language": "zh-CN",
        "response": "json_object_only",
        "singleExtraction": True,
        "extractionProcedure": [
            "Treat candidateParagraphs as the sole evidence of current events. Canon is prior history, Bible and Planning are intentions, and the outline is assigned work rather than proof that work finished. Compose the summary from the evidenced events last; never copy the outline goal as an accomplished summary.",
            "For each proposed record, privately identify the exact supported assertion, its actor/owner, narrative time, source of knowledge and whether it is observed, said, inferred, planned or executed. Emit only the supported assertion. A request for tomorrow's test supports a present intention, not a completed test; a report of missing stock supports what the reporter says, not independently verified loss.",
            "Use claim for an unverified report's underlying assertion, retaining who said it and the uncertainty. A dynamic_event may record the observable act of speaking or recording, but its value must explicitly attribute the statement and must not present the reported content as established truth. Do not emit the same proposition again as a confirmed fact or a resolved plot thread.",
            "For each scene task, compare every element of completionEvidence with actual action in the quoted paragraphs. If only a proposal, partial step or one of several required results occurred, use started/advanced or omit the task. A signature with unknown contents does not prove approval; viewing names does not prove a substitution method. Never complete a task because its words appear in the outline or a speaker promises it.",
            "Consolidate repeated mentions of the same fact and same end state. A character repeatedly touching a sample bag does not create a new psychological arc each time. Extract meaningful changes and concrete continuity facts, not every gesture or sentence. There is no minimum record count. Preserve different assertions, sources, custodians and real successive transitions; do not merge contradictions or erase evidence to reduce length.",
            "Use one canonical existing field and owner for a continuing thread or dimension. Prefer a single evidence-supported end-state update per owner/field when all sentences describe the same state; do not duplicate it under action.*, arc.* and plot.* merely to populate views. Keep the actual sequence if intermediate states carry distinct consequences.",
        ],
        "completionAudit": {
            "requirements": "A task's full task text AND completionEvidence are conjunctive requirements. A shorter completionEvidence never waives a result explicitly required by task. First split both into distinct actions/results, then verify each against candidateParagraphs, never against the outline's proposed scenes.",
            "rationale": "For each progress event, evidence.rationale must name what actually occurred and what remains unsupported. For completed, briefly map every required action/result to the observed event; never repeat the task description as proof. If an action's execution, a document's contents, a cause or a method is unstated, mark advanced/started and name that gap. Do not invent certainty to qualify for completed.",
            "counterexamples": [
                "An order to transfer someone tomorrow, while that person is still here tonight, proves an issued order, not that the person has left. A task requiring the person to have been transferred remains incomplete.",
                "Copying signatories identifies names, not HOW substitution was carried out. A task requiring both the substitution method and the names is advanced until the method is actually established.",
                "An official writing unspecified words and stamping a document does not prove its contents are a refusal, approval or request for a retest. A preceding proposal is not proof that the proposal was written down.",
            ],
            "propagation": "Apply the same time and certainty limits to canonEvents, parent progress and summary. After classifying tasks, remove any summary or plot statement that presents their still-missing results as achieved. An unverified autobiographical statement remains attributed even in identity fields; do not promote the same claim elsewhere to stable_definition.",
        },
        "schemaVersion": "finalization-changeset-v1",
        "evidenceFields": [
            "paragraphRange", "confidence", "rationale",
        ],
        "evidenceParagraphRange": _PARAGRAPH_RANGE_RULES,
        "requiredCollections": [
            "existingEntityIds", "entities", "aliases", "canonEvents",
            "storyProgressEvents", "planningPatches", "planningSuggestions",
        ],
        "outputShape": {
            "schemaVersion": "finalization-changeset-v1",
            "title": "chapter title",
            "summary": "chapter summary",
            "existingEntityIds": ["exact existing Canon entity id"],
            "entities": [{
                "id": "unique change id",
                "entityType": "person|organization|place|item",
                "canonicalName": "name",
            }],
            "aliases": [{
                "id": "unique change id",
                "entityId": "declared existing or new entity id",
                "alias": "alias",
            }],
            "canonEvents": [{
                "id": "unique change id",
                "entityId": "declared entity id or null",
                "factKind": "stable_definition|dynamic_event|claim",
                "fieldPath": "fact field path",
                "value": "strict JSON value",
                "evidence": evidence_shape,
                "effectiveStartChapter": "integer >= 1 or null",
                "effectiveEndChapter": "integer >= start or null",
                "assertionOperator": "equals|not_equals",
                "valueCardinality": "single|multi",
            }],
            "storyProgressEvents": [{
                "id": "unique change id",
                "targetType": "story_block|stage|scene_task",
                "targetId": "exact target id from planningContext",
                "status": "started|advanced|completed",
                "completionBasis": {
                    "execution": "observed|planned|uncertain",
                    "unmetRequirements": ["required action/result not yet evidenced; empty only when none remain"],
                    "supportingParagraphIds": ["exact paragraph IDs used to reach this decision, all inside evidence.paragraphRange"],
                },
                "evidence": evidence_shape,
            }],
            "planningPatches": [{
                "id": "unique change id",
                "targetType": "volume|plot|story_block|stage|scene_task",
                "targetId": "exact target id from planningContext",
                "expectedRevision": "exact target revision from planningContext",
                "expectedHash": "exact target hash from planningContext",
                "fieldPath": "allowed field for the target type",
                "replacement": "strict JSON replacement",
                "evidence": evidence_shape,
            }],
            "planningSuggestions": [{
                "id": "unique change id",
                "targetId": "exact planning id or null",
                "message": "non-authoritative suggestion",
                "evidence": evidence_shape,
            }],
        },
        "forbiddenOutput": [
            "changeset wrapper", "top-level evidence", "excerptHash",
            "unknown fields", "markdown", "commentary",
        ],
        "rules": [
            "For EVERY storyProgressEvent, decide completionBasis BEFORE status. execution concerns the TASK'S required outcome, not whether a preparatory order or discussion occurred. A future transfer order is an observed order but a planned transfer; classify execution=planned while departure has not happened. An order-making task itself can be observed. Read later paragraphs before deciding: a later actual departure can satisfy a previously planned transfer.",
            "completionBasis is mandatory transient provider metadata, removed by the gateway before persistence. completed requires execution=observed AND unmetRequirements=[]; otherwise use started/advanced or omit the unsupported event. Include every requirement missing from the full task AND completionEvidence, rather than measuring only pressure, intention or preparation. Never mark observed merely to qualify for completed.",
            "Every supportingParagraphIds entry and every p-number cited in evidence.rationale must be inside evidence.paragraphRange. Choose the smallest contiguous interval containing ALL relied-on paragraphs, not just the first action. If p24 and p77 are both needed, the interval must include p24 through p77. Do not cite outside evidence, invent extra support or silently discard a needed paragraph.",
            "Return one complete closed ChangeSet.",
            "Return outputShape directly as the top-level object; never wrap it.",
            "Every collection is required but may be empty when no supported change exists.",
            "Every id field must be unique within the complete ChangeSet.",
            "Use only supplied existing entity and Planning identities.",
            "A stable_definition MUST reference an entityId declared in existingEntityIds or entities; entityId=null is forbidden for stable_definition. Global occurrences use dynamic_event, and unverified statements use claim. Choose the fact kind from the evidence; do not invent an entity or relabel a fact merely to satisfy this rule.",
            "Do not mutate confirmed or implemented Planning.",
            "Return source paragraphRange endpoints, not copied or rewritten Candidate prose or commentary.",
            "Never estimate character offsets. Select the smallest supporting paragraphRange by exact start/end IDs from candidateParagraphs. The selected paragraphs must directly support the event, rather than only mention its character.",
            "If no supporting source paragraph exists, omit that unsupported finding or event. Statements by characters are claims, not established facts.",
            "Classify supported Canon events using the existing projection field paths: arc.<dimension> for an actually demonstrated change in a person's goal, belief, relationship, ability or psychological state (entityId must name that person); plot.<threadKey> for an actually introduced, advanced or resolved main plot, subplot, character thread, unfinished storyline, clue, mystery or foreshadowing thread. Reuse both the existing exact entityId (including null for global threads) and fieldPath for the same dimension or thread so its latest state updates instead of creating duplicate threads. A new observer does not change a thread's owner; describe involved people in value instead. Other factual fields remain ordinary facts. Do not use clue.* or arbitrary observation fields as substitutes for a clue's plot.* state.",
            "These are categories for evidence already in candidateParagraphs, not a quota: keep collections empty when unsupported. Bible and Planning character designs are future intentions, not achieved arcs. A clue observed is not a mystery solved; record the actual discovery and remaining uncertainty. Never promote a character's speculation to a confirmed explanation. A demonstrated decision may change the person's present intention but does not establish its later execution.",
            "The plot.progress.* namespace is reserved for storyProgressEvents; never emit it in canonEvents. Do not duplicate one event across arbitrary fields merely to populate views. All facts, arcs and clues use this single extraction and the same author-confirmed Canon events.",
            "Use progressScope as a derived task inventory, not new authority. boundSceneTaskIds identifies only this chapter's assigned tasks; requiredSceneTasks includes the parent's other tasks. Finishing this chapter or every bound task does not complete a stage or story block when another required task remains unfinished.",
            "Before emitting any parent completed event, check every required scene task: it must have confirmedStatus=completed or its actual completion must be evidenced by a scene_task completed event in this same ChangeSet. A task outside this chapter's bound IDs is not implicitly completed. Re-check after any current event that changes a previously completed task to started/advanced. The parent goal must also have happened; otherwise use only the progress status actually supported by the prose. Never invent child completion to make a parent eligible.",
            "Parent progress is completed only when every active descendant scene task has confirmed completion in canonContext.actualProgress or this ChangeSet, and the parent goal actually happened. Otherwise use advanced. A plan, invitation or decision is not its later execution.",
        ],
    })


__all__ = [
    "FINALIZATION_MAX_PROMPT_BYTES",
    "FinalizationBinding",
    "FinalizationProviderManifest",
    "build_extraction_messages",
    "build_quality_messages",
]


def build_progress_audit_messages(*, manifest: FinalizationProviderManifest, events: list[dict]) -> tuple[dict[str, str], ...]:
    """One focused verification of proposed progress, never another fact extraction."""
    instruction = {
        "task": "verify_proposed_progress", "language": "zh-CN", "response": "json_object_only",
        "rules": [
            "先将任务动作与 completionEvidence 要求的结果分开核对。执行或观察到动作，并不自动证明已取得结果；必须从正文找出实际取得的知识、信息、交付物或状态。把结果直接写入理由不能代替正文证据。仅看到一次事件或听到一个时刻，不能推算重复事件的时间间隔；明确测量、比较或直接获得间隔信息才支持该结果。缺少所需结果时列入 unmetRequirements 并保留 started/advanced。",
            "这是执行结果核验，不是剧情效果评分。任务中的每个动作都必须发生；威胁生效、压力已经产生、旁人接受安排，不能替代人员离开、材料交付等尚未发生的动作。调动类任务除非明确只要求发令，完成必须有本人实际离开原处或到达新处的正文证据；只有宣布、转述、确认明日调令时只能 started/advanced。不要把行政安排已生效解释为人已离开。",
            "先确定正文当前时刻，再读相对时间：今夜仍与本人在原处交谈、执行说定在明天，说明此刻尚未执行。人物说‘你调走我一人’、旁白推算调走后的工期，均不能推翻同场景明确的未来执行时间。只有后文明确跨到次日且写出执行动作，才可 completed。",
            "Independently classify every requested event against candidateParagraphs and the full task AND completionEvidence. Only requested identities are supplied, not the first extractor's opinions. Output exactly one decision per event id; do not add facts, tasks or identities.",
            "Determine the required end result, then distinguish preparation/order/decision from execution. A future transfer order with the worker still present is only planned transfer even if staffing pressure is already felt. An order-only task can be completed by the order. If later paragraphs show actual departure, actual transfer can be completed.",
            "Names copied from a ledger do not prove the substitution method. Unspecified written annotations do not prove a written retest request. Quote the actual gap in unmetRequirements; do not use an outline goal as proof.",
            "completed requires execution=observed and no unmet requirements. Otherwise return started/advanced. Parent completion also requires every required child to be confirmed completed or genuinely completed in these decisions; any incomplete child prevents parent completed.",
            "Each evidence paragraphRange must contain all supportingParagraphIds and every p-number cited in rationale. Use the smallest contiguous interval containing all actual supporting paragraphs. Unknown paragraph IDs are forbidden.",
        ],
        "closedShape": "Each decision has exactly id, status, completionBasis, evidence. Do not repeat targetId or targetType. Empty unmetRequirements is allowed only when every required result occurred.",
        "outputShape": {"decisions": [{"id": "exact proposed event id", "status": "started|advanced|completed",
            "completionBasis": {"execution": "observed|planned|uncertain", "unmetRequirements": ["missing required result, or empty list"],
                                "supportingParagraphIds": ["exact paragraph id"]},
            "evidence": {"paragraphRange": {"start": "first paragraph id", "end": "last paragraph id"},
                         "confidence": "number 0..1", "rationale": "what actually happened and what remains missing"}}]},
    }
    scope = _progress_scope(manifest)
    if len(events) == 1 and events[0]['targetType'] == 'scene_task':
        scope = {'requiredTasks': [task for stage in scope.get('stages', [])
                                  for task in stage['requiredSceneTasks'] if task['id'] == events[0]['targetId']]}
    payload = {"progressScope": scope, "requestedEvents": [
                   {key: event[key] for key in ('id', 'targetType', 'targetId')} for event in events],
               "candidateParagraphs": [{"id": p['id'], "text": p['text']} for p in source_paragraphs(manifest.candidate_prose)]}
    messages = ({"role": "system", "content": canonical_json(instruction)},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)})
    if len(json.dumps(messages, ensure_ascii=False).encode('utf-8')) > FINALIZATION_MAX_PROMPT_BYTES:
        raise ValueError(_SAFE_ERROR)
    return messages
