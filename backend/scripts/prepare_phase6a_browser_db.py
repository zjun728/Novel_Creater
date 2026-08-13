"""Build one owned, outbound-free finalized-download fixture through services."""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import time
from pathlib import Path

from backend.database import close_pool, connection, transaction
from backend.domain.assets import PACKAGE_VERSION, load_asset_package
from backend.domain.bibles import BiblePayload
from backend.domain.chapter_outlines import EditableChapterOutlineContent
from backend.domain.finalization import FinalizationChangeSet
from backend.domain.seeds import SeedPayload
from backend.domain.story_engines import StoryEngineOption
from backend.repositories.assets import AssetRepository
from backend.repositories.bibles import BibleRepository
from backend.repositories.canon import CanonRepository
from backend.repositories.chapter_outlines import ChapterOutlineRepository
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.repositories.contracts import ContractRepository
from backend.repositories.finalization import FinalizationRepository
from backend.repositories.model_bindings import ModelBindingRepository
from backend.repositories.planning import PlanningRepository
from backend.repositories.projects import ProjectRepository
from backend.repositories.seeds import SeedRepository
from backend.repositories.story_engines import StoryEngineRepository
from backend.services.assets import AssetSeedService
from backend.services.bibles import BibleService, ConfirmBible, SaveBibleDraft
from backend.services.canon import CanonService
from backend.services.chapter_outlines import (
    ChapterOutlineService, ConfirmChapterOutlineDraft, CreateChapterOutlineDraft,
    SaveChapterOutlineDraft,
)
from backend.services.chapter_sessions import (
    ChapterSessionService, CreateChapterSession, SaveDraftCandidate, SaveWorkingDraft,
)
from backend.services.contracts import (
    AssetRevisionRef, ConfirmContracts, ContractDraftInput, ContractService,
    CorpusSourceRef, SaveContractDraft,
)
from backend.services.finalization import (
    ConfirmFinalization, FinalizationService, PrepareFinalization,
)
from backend.services.finalization_commit import AtomicFinalizationService, CommitFinalization
from backend.services.model_bindings import ModelBindingService
from backend.services.planning import (
    ConfirmPlanningDraft, CreatePlanningDraft, PlanningService, SavePlanningDraft,
)
from backend.services.project_lifecycle import CreateProject, ProjectLifecycleService
from backend.services.provider_profiles import (
    ProviderCreateCommand, ProviderProfileService, SqlProviderProfileRepository,
)
from backend.services.seeds import CreateSeed, SeedService, SelectSeed
from backend.services.story_engines import CreateManualStoryEngineBatch, StoryEngineService

PROJECT = "81000000-0000-0000-0000-000000000001"
FINAL_ONE = "PHASE6A_FINAL_CHAPTER_ONE"
FINAL_TWO = "PHASE6A_FINAL_CHAPTER_TWO"
WORKING_SENTINEL = "PHASE6A_WORKING_SENTINEL"
CANDIDATE_SENTINEL = "PHASE6A_CANDIDATE_SENTINEL"
_DISPOSABLE = re.compile(r"novel_creator_test_[a-f0-9]{32}\Z")
_MANIFEST = Path(__file__).resolve().parents[1] / "assets" / PACKAGE_VERSION / "manifest.json"


class _Quality:
    async def audit(self, **_kwargs): return ()


class _Extraction:
    async def extract(self, *, manifest, **_kwargs):
        number = manifest.chapter_number
        return FinalizationChangeSet.model_validate({
            "schemaVersion": "finalization-changeset-v1", "title": f"第{number}章 定稿",
            "summary": f"第{number}章已定稿。", "existingEntityIds": [], "entities": [],
            "aliases": [], "canonEvents": [], "storyProgressEvents": [],
            "planningPatches": [], "planningSuggestions": [],
        })


def assert_database_name(value: str) -> str:
    if not isinstance(value, str) or _DISPOSABLE.fullmatch(value) is None:
        raise RuntimeError("Phase6A fixture requires a disposable database")
    return value


def _option(number: int) -> StoryEngineOption:
    marker = str(number)
    return StoryEngineOption(
        name=f"方案 {marker}", storyPromise=f"承诺 {marker}", protagonistDesire=f"欲望 {marker}",
        sustainedPressure=f"压力 {marker}", growthDirection=f"成长 {marker}", conflictLoop=f"循环 {marker}",
        ensembleRoles=({"role": f"角色 {marker}", "purpose": f"作用 {marker}"},),
        advantageAndCost=f"优势代价 {marker}", satisfactionSources=(f"爽点 {marker}",),
        longFormVariation=(f"变化 {marker}",), endingAnchor=f"结局 {marker}", risks=(f"风险 {marker}",),
        differentiation=f"差异 {marker}",
    )


def _planning_payload() -> dict[str, object]:
    return {
        "activeStoryBlockRef": "block", "volumes": [{"clientNodeKey": "volume", "order": 1,
        "title": "第一卷", "coreChange": "主角建立第一个可靠据点。", "mainPressure": "追兵逼近。",
        "ensembleFocus": ["主角", "同伴"], "forbiddenEvents": ["不可提前揭示幕后人"]}],
        "plots": [{"clientNodeKey": "plot", "order": 1, "title": "立足主线", "plotType": "main",
        "storyQuestion": "主角如何活下来？", "futureDirection": "从逃亡转为主动布局。",
        "expectedPayoff": "建立据点。", "relatedCharacters": ["主角"]}],
        "storyBlocks": [{"clientNodeKey": "block", "order": 1, "title": "夜渡封锁线",
        "volumeRef": "volume", "plotRefs": ["plot"], "entrySituation": "二人被困。",
        "blockGoal": "穿过封锁线。", "mainPressure": "追兵压缩路线。", "expectedChange": "二人建立信任。",
        "openQuestions": ["内应是谁"], "involvedCharacters": ["主角", "同伴"], "stages": [{
        "clientNodeKey": "stage", "order": 1, "title": "寻找缺口", "purpose": "确认封锁薄弱处。",
        "dramaticQuestion": "能否在暴露前找到缺口？", "sceneTasks": [{"clientNodeKey": "task",
        "order": 1, "task": "观察换岗。", "completionEvidence": "取得换岗间隔。"}]}]}],
    }


def _outline_payload(planning) -> EditableChapterOutlineContent:
    volume, block = planning.volumes[0], planning.story_blocks[0]
    stage, task = block.stages[0], block.stages[0].scene_tasks[0]
    ref = lambda item: {"id": item.id, "revision": item.revision, "contentHash": item.content_hash}
    return EditableChapterOutlineContent.model_validate({
        "schemaVersion": "chapter-outline-draft-v1", "volumeRef": ref(volume),
        "storyBlockRef": ref(block), "stageRefs": (ref(stage),), "sceneTaskRefs": (ref(task),),
        "chapterGoal": "找到封锁线缺口。", "expectedCharacters": ("主角", "同伴"),
        "continuation": ("承接被困局面",), "plannedTasks": ("观察换岗",),
        "scenes": ("废弃驿站侦察",), "forbiddenEarlyEvents": ("不可提前揭示内应",),
    })


def _bible_payload() -> BiblePayload:
    item = lambda key, text: {"id": key, "text": text}
    return BiblePayload.model_validate({"premiseAndPromise": "主角守住历史真相。",
        "worldRules": (item("rule", "改写历史必须付出代价。"),), "powerOrProgressionSystem": "校勘典籍获得线索。",
        "protagonist": "主角克制谨慎。", "coreCast": (item("cast", "同伴挑战主角判断。"),),
        "factions": (item("faction", "守典司封存异常典籍。"),), "longTermConflicts": (item("conflict", "真相与秩序冲突。"),),
        "relationshipDynamics": (item("relation", "二人从互疑走向信任。"),),
        "toneAndNarrativeBoundaries": "清楚好读，以选择推动情节。",
        "continuityGuardrails": (item("guard", "关键胜利必须伴随损失。"),),
        "openDesignQuestions": (item("question", "内应身份尚未确定。"),)}, strict=True)


async def _finalize(sessions, finalization_service, atomic_service, workspace, outline, prose, candidate_key, hash_key, expected_canon_revision):
    saved = await sessions.save_working_draft(SaveWorkingDraft(PROJECT, workspace.session.id,
        workspace.working_draft.revision, workspace.working_draft.content_hash, prose))
    candidate = await sessions.save_candidate(SaveDraftCandidate(PROJECT, workspace.session.id,
        saved.working_draft.revision, saved.working_draft.content_hash, candidate_key))
    prepared = await finalization_service.prepare(PrepareFinalization(PROJECT, workspace.session.id,
        candidate.saved_candidate_id, saved.working_draft.content_hash, expected_canon_revision,
        workspace.session.planning_hash, outline.content_hash, hash_key))
    if prepared.status != "awaiting_author": raise RuntimeError("Phase6A finalization was not reviewable")
    confirmed = await finalization_service.confirm(ConfirmFinalization(PROJECT, workspace.session.id,
        prepared.current_revision, prepared.current_revision_hash))
    await atomic_service.commit(CommitFinalization(PROJECT, workspace.session.id, hash_key[::-1],
        confirmed.current_revision, confirmed.current_revision_hash))


async def prepare(
    database_name: str,
    *,
    corpus_source_refs: tuple[CorpusSourceRef, ...] = (),
) -> None:
    database_name = assert_database_name(database_name)
    if os.environ.get("MYSQL_DB") != database_name: raise RuntimeError("Phase6A fixture database authority mismatch")
    async with connection() as session:
        if await session.fetchone("SELECT DATABASE() AS database_name") != {"database_name": database_name}:
            raise RuntimeError("Phase6A fixture selected a non-owned database")
    providers = ProviderProfileService(SqlProviderProfileRepository(), transaction_factory=transaction,
        connection_factory=connection, connection_gateway=None)
    await providers.create(ProviderCreateCommand(name="Phase6A local deny", provider_type="openai-compatible",
        model="phase6a-local-deny", base_url="http://127.0.0.1:1/v1", api_key="phase6a-test-only-key",
        enabled=True, sort_order=1, stream=True, max_context_tokens=8192, max_output_tokens=2048,
        temperature=0.0, top_p=1.0, supports_json=True, supports_streaming=True,
        notes="Disposable browser fixture; connection is prohibited.", thinking=None,
        idempotency_key="phase6a-provider-create"))
    binding = ModelBindingService(ModelBindingRepository(), transaction_factory=transaction, connection_factory=connection)
    projects = ProjectLifecycleService(ProjectRepository(), transaction, connection, model_binding_service=binding)
    await projects.create(CreateProject(id=PROJECT, title="Phase6A finalized download", genre="fantasy"))
    seeds = SeedService(SeedRepository(), transaction_factory=transaction, connection_factory=connection)
    seed = await seeds.create(CreateSeed(project_id=PROJECT, payload=SeedPayload(title="典镇山河", genre="东方奇幻",
        logline="少年以县志镇压黑潮。", protagonist="沈码", desire="让乡民重获姓名。", coreConflict="修史会唤醒镇物。",
        worldPressure="黑潮上涨。", openingHook="县志预写死期。", differentiation="地方志力量体系。")))
    await seeds.select(SelectSeed(project_id=PROJECT, seed_id=seed.id, expected_seed_revision=seed.revision, expected_selection_revision=0))
    engines = StoryEngineService(StoryEngineRepository(), transaction_factory=transaction, connection_factory=connection)
    batch = await engines.create_manual(CreateManualStoryEngineBatch(PROJECT, "phase6a-manual-engine", tuple(_option(i) for i in range(1, 4))))
    assets_repository = AssetRepository()
    await AssetSeedService(assets_repository, transaction_factory=transaction).seed(load_asset_package(_MANIFEST, mode="release"))
    async with connection() as session:
        styles = await assets_repository.list_heads(session, "style", for_update=False)
        cards = await assets_repository.list_heads(session, "card", for_update=False)
    contracts = ContractService(ContractRepository(), transaction_factory=transaction, connection_factory=connection)
    contract = ContractDraftInput(schemaVersion="contract-draft-v2", draftStage="assets",
        engineOptionId=batch.options[0].id, engineHash=batch.options[0].content_hash,
        channelProfileKey="web-fiction", genreProfileKey="fantasy", qualityCharterVersion="quality-v1",
        targetTotalWords=150000, expectedVolumeCount=3, expectedChapterCount=60,
        chapterWordRangePreference=(2000, 3000), prohibitedDirections=("不写无代价升级",), authorNotes="人物选择优先。",
        primaryStyleRef=AssetRevisionRef(id=styles[0]["id"], revision=int(styles[0]["revision"]), contentHash=styles[0]["content_hash"]),
        experienceCardRefs=(AssetRevisionRef(id=cards[0]["id"], revision=int(cards[0]["revision"]), contentHash=cards[0]["content_hash"]),),
        corpusSourceRefs=tuple(corpus_source_refs), likes=("选择有代价",), dislikes=("空泛升级",))
    saved_contract = await contracts.save_draft(SaveContractDraft(PROJECT, 0, contract))
    await contracts.confirm(ConfirmContracts(PROJECT, "phase6a-confirm-contract", saved_contract.draft_version, saved_contract.content_hash))
    bibles = BibleService(BibleRepository(), contract_service=contracts, transaction_factory=transaction)
    bible_draft = await bibles.save_draft(SaveBibleDraft(PROJECT, 0, _bible_payload()))
    await bibles.confirm(ConfirmBible(PROJECT, "phase6a-confirm-bible", bible_draft.draft_version, 0))
    planning_service = PlanningService(PlanningRepository(), transaction_factory=transaction)
    planning_draft = await planning_service.create_draft(CreatePlanningDraft(PROJECT, "phase6a-create-planning"))
    planning_saved = await planning_service.save_draft(SavePlanningDraft(PROJECT, planning_draft.draft_id,
        planning_draft.draft_revision, planning_draft.content_hash, _planning_payload(), "phase6a-save-planning"))
    planning = await planning_service.confirm_draft(ConfirmPlanningDraft(PROJECT, planning_saved.draft_id,
        planning_saved.draft_revision, planning_saved.content_hash, "phase6a-confirm-planning"))
    outlines = ChapterOutlineService(ChapterOutlineRepository(), ChapterSessionRepository(),
        transaction_factory=transaction, planning_repository=PlanningRepository())
    sessions = ChapterSessionService(ChapterSessionRepository(), transaction_factory=transaction, connection_factory=connection)
    finalization_service = FinalizationService(transaction_factory=transaction, repository=FinalizationRepository(),
        quality_provider=_Quality(), extraction_provider=_Extraction(), clock=lambda: int(time.time() * 1000))
    atomic_service = AtomicFinalizationService(transaction_factory=transaction, repository=FinalizationRepository(),
        planning_repository=PlanningRepository(), canon_committer=CanonService(CanonRepository(), transaction_factory=transaction),
        clock=lambda: int(time.time() * 1000))
    for chapter, prose in ((1, FINAL_ONE), (2, FINAL_TWO)):
        draft = await outlines.create_draft(CreateChapterOutlineDraft(PROJECT, chapter))
        saved = await outlines.save_draft(SaveChapterOutlineDraft(PROJECT, chapter, draft.draft_id,
            draft.draft_revision, draft.content_hash, _outline_payload(planning.content)))
        outline = await outlines.confirm_draft(ConfirmChapterOutlineDraft(PROJECT, chapter, saved.draft_id,
            saved.draft_revision, saved.content_hash, 0, f"phase6a-outline-{chapter}"))
        workspace = await sessions.create_session(CreateChapterSession(PROJECT, chapter, planning.revision,
            planning.content_hash, outline.revision, outline.content_hash, chapter - 1))
        await _finalize(sessions, finalization_service, atomic_service, workspace, outline, prose,
            f"{chapter}" * 8 + "-" + f"{chapter}" * 4 + "-4" + f"{chapter}" * 3 + "-8" + f"{chapter}" * 3 + "-" + f"{chapter}" * 12,
            str(chapter) * 64, chapter - 1)
    draft = await outlines.create_draft(CreateChapterOutlineDraft(PROJECT, 3))
    saved = await outlines.save_draft(SaveChapterOutlineDraft(PROJECT, 3, draft.draft_id, draft.draft_revision,
        draft.content_hash, _outline_payload(planning.content)))
    outline = await outlines.confirm_draft(ConfirmChapterOutlineDraft(PROJECT, 3, saved.draft_id,
        saved.draft_revision, saved.content_hash, 0, "phase6a-outline-3"))
    third = await sessions.create_session(CreateChapterSession(PROJECT, 3, planning.revision, planning.content_hash,
        outline.revision, outline.content_hash, 2))
    candidate = await sessions.save_working_draft(SaveWorkingDraft(PROJECT, third.session.id,
        third.working_draft.revision, third.working_draft.content_hash, CANDIDATE_SENTINEL))
    await sessions.save_candidate(SaveDraftCandidate(PROJECT, third.session.id, candidate.working_draft.revision,
        candidate.working_draft.content_hash, "33333333-3333-4333-8333-333333333333"))
    await sessions.save_working_draft(SaveWorkingDraft(PROJECT, third.session.id, candidate.working_draft.revision,
        candidate.working_draft.content_hash, WORKING_SENTINEL))


async def verify_postconditions(database_name: str) -> None:
    database_name = assert_database_name(database_name)
    if os.environ.get("MYSQL_DB") != database_name: raise RuntimeError("Phase6A verifier database authority mismatch")
    async with connection() as session:
        selected = await session.fetchone("SELECT DATABASE() AS database_name")
        finals = await session.fetchall("SELECT chapter_num,content FROM final_chapters WHERE project_id=%s ORDER BY chapter_num", (PROJECT,))
        sentinels = await session.fetchone("SELECT SUM(content IN (%s,%s)) AS working_count FROM working_drafts WHERE project_id=%s", (WORKING_SENTINEL, "PHASE6A_UNSAVED_SENTINEL", PROJECT))
        candidates = await session.fetchone("SELECT SUM(content=%s) AS candidate_count FROM draft_candidates WHERE project_id=%s", (CANDIDATE_SENTINEL, PROJECT))
    if selected != {"database_name": database_name} or finals != [{"chapter_num": 1, "content": FINAL_ONE}, {"chapter_num": 2, "content": FINAL_TWO}]:
        raise RuntimeError("Phase6A final chapter authority is invalid")
    if int(sentinels.get("working_count") or 0) != 1 or int(candidates.get("candidate_count") or 0) != 1:
        raise RuntimeError("Phase6A non-final sentinel authority is invalid")


async def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--database", required=True); parser.add_argument("--verify-postconditions", action="store_true")
    args = parser.parse_args()
    try: await (verify_postconditions(args.database) if args.verify_postconditions else prepare(args.database))
    finally: await close_pool()


if __name__ == "__main__": asyncio.run(main())
