"""Real project package round trips for continuity issues on owned MySQL only."""

from contextlib import asynccontextmanager
from uuid import UUID, uuid5

import aiomysql
import pytest

from backend.domain.continuity_issues import CreateContinuityIssue, UpdateContinuityIssue
from backend.domain.project_import_plans import build_publication_plan, read_verified_project_package
from backend.domain.project_imports import ProjectImportInvalid
from backend.http_errors import ProjectNotFound
from backend.repositories.continuity_issues import ContinuityIssueRepository
from backend.repositories.model_bindings import ModelBindingRepository
from backend.repositories.project_imports import ProjectImportRepository
from backend.repositories.project_packages import ProjectPackageRepository
from backend.repositories.project_overview import ProjectOverviewRepository
from backend.services.project_overview import ProjectOverviewService
from backend.repositories.projects import ProjectRepository
from backend.scripts import prepare_phase6a_browser_db as finalized_fixture
from backend.services.continuity_issues import ContinuityIssueService
from backend.services.model_bindings import ModelBindingService
from backend.services.project_lifecycle import CreateProject, ProjectLifecycleService
from backend.services.project_packages import ProjectPackageService, cleanup_project_package_file
from backend.tests.integration.test_project_import_publication_mysql import (
    COMMAND_ID, OWNER_ID, _running_command,
)
from backend.tests.support.disposable_mysql import assert_disposable_name, transaction_factory_for


pytestmark = [pytest.mark.mysql, pytest.mark.asyncio]
PROJECT_ID = finalized_fixture.PROJECT
ISSUE_NAMESPACE = UUID('97000000-0000-4000-8000-000000000001')


def _lifecycle(transaction):
    bindings = ModelBindingService(ModelBindingRepository(), transaction_factory=transaction,
                                   connection_factory=transaction)
    return ProjectLifecycleService(ProjectRepository(), transaction, transaction,
                                   model_binding_service=bindings)


async def _seed_finalized_project(database, monkeypatch):
    """Reuse the outbound-free author service fixture with explicit owned sessions.

    The older atomic-finalization SQL fixture stores {} contract payloads and
    cannot represent a valid project backup. This one builds all authorities
    through the actual author services and uses local quality/extraction fakes.
    """
    assert_disposable_name(database.database_name)
    transaction = transaction_factory_for(database.connection_config)
    monkeypatch.setenv('MYSQL_DB', database.database_name)
    monkeypatch.setattr(finalized_fixture, 'connection', transaction)
    monkeypatch.setattr(finalized_fixture, 'transaction', transaction)
    await finalized_fixture.prepare(database.database_name)
    return transaction


@asynccontextmanager
async def _packages(database, tmp_path):
    corpus = tmp_path / 'corpus'
    temporary = tmp_path / 'packages'
    corpus.mkdir()
    temporary.mkdir()
    pool = await aiomysql.create_pool(**{**database.connection_config, 'autocommit': True},
                                      minsize=1, maxsize=2)
    packages = []
    service = ProjectPackageService(repository=ProjectPackageRepository(pool=pool),
                                    managed_corpus_root=corpus, temp_parent=temporary)

    async def export(project_id, revision):
        artifact = await service.create_backup(project_id, revision)
        packages.append(artifact)
        try:
            verified = read_verified_project_package(artifact.path)
        except ProjectImportInvalid as error:
            # Keep fixture diagnostics structural: record kinds and field names,
            # never author text or provider configuration.
            details = []
            trace = error.__traceback__
            while trace is not None:
                local = trace.tb_frame.f_locals
                if trace.tb_frame.f_code.co_name == '_validate_graph':
                    record = local.get('record')
                    declaration = local.get('declaration')
                    if record is not None and declaration is not None:
                        details.append((record.entity_type, sorted(declaration.required_fields - set(record.data))))
                if trace.tb_frame.f_code.co_name == 'read_verified_project_package':
                    entry, parsed, expected = local.get('entry'), local.get('parsed'), local.get('expected_types')
                    if entry is not None and parsed is not None and expected is not None and entry.path in expected:
                        unexpected = sorted({record.entity_type for record in parsed} - expected[entry.path])
                        if unexpected:
                            details.append((entry.path, unexpected))
                trace = trace.tb_next
            raise AssertionError(f'Exported package cannot pass preflight: {details}') from error
        assert verified.package_hash == artifact.package_sha256
        return verified

    try:
        yield export
    finally:
        for package in packages:
            cleanup_project_package_file(package)
        pool.close()
        await pool.wait_closed()
        assert not list(temporary.iterdir())


async def _publish(package, transaction):
    plan = build_publication_plan(package, COMMAND_ID, '连续性问题导入验证')
    assert plan.blobs == ()
    repository = ProjectImportRepository()
    await _running_command(repository, transaction, plan=plan)
    async with transaction() as session:
        target = await repository.publish_project(session, plan, now=20,
                                                   request_fingerprint='2' * 64, owner_token=OWNER_ID)
    assert target == plan.target_project_id
    return plan


def _issue_records(package):
    return {record.data['description']: record for record in package.graph_index.values()
            if record.entity_type == 'continuity-issue'}


def _meaning(record, package):
    """Compare author data while resolving package-local source identities."""
    data = dict(record.data)
    reference = data.pop('sourceFinalizationLogicalId', None)
    if reference is not None:
        finalization = package.graph_index[('finalization-record', reference)]
        finals = [item for item in package.graph_index.values() if item.entity_type == 'final-chapter'
                  and item.data['finalizationRecordLogicalId'] == reference]
        assert len(finals) == 1
        assert finals[0].data['chapterNumber'] == data['sourceChapterNumber']
        assert finals[0].data['candidateLogicalId'] == finalization.data['candidateLogicalId']
        assert finals[0].data['canonRevision'] == data['sourceCanonRevision']
        assert finalization.data['committedCanonRevision'] == data['sourceCanonRevision']
        assert type(data['sourceCanonRevision']) is int
    else:
        assert data.get('sourceChapterNumber') is None and data.get('sourceCanonRevision') is None
    return data


async def test_all_issue_states_and_formal_sources_survive_export_import_export_then_delete(
    disposable_mysql, monkeypatch, tmp_path,
):
    transaction = await _seed_finalized_project(disposable_mysql, monkeypatch)
    issues = ContinuityIssueService(ContinuityIssueRepository(), transaction_factory=transaction,
                                    connection_factory=transaction, clock=lambda: 100)
    expected = {}
    for source in (None, 1):
        for status in ('pending', 'resolved', 'ignored'):
            description = f'{status}状态，来源章节{source}'
            created = await issues.create(PROJECT_ID, CreateContinuityIssue(
                id=str(uuid5(ISSUE_NAMESPACE, description)), category='fact', severity='high',
                description=description, suggestion='核对跨章事实', futureTarget='第四章解释原因',
                sourceChapterNumber=source))
            if status != 'pending':
                created = await issues.update(PROJECT_ID, created['id'], UpdateContinuityIssue(
                    status=status, resolutionNote=f'作者已记录{status}处理结论', expectedUpdatedAt=created['updatedAt']))
            expected[description] = created
    lifecycle = _lifecycle(transaction)
    source_project = await lifecycle.get(PROJECT_ID)
    async with _packages(disposable_mysql, tmp_path) as export:
        source_package = await export(PROJECT_ID, source_project.lifecycle_revision)
        source_records = _issue_records(source_package)
        assert set(source_records) == set(expected)
        assert source_package.manifest.counts['continuity-issue'] == 6
        plan = await _publish(source_package, transaction)
        target_id = plan.target_project_id
        imported_project = await lifecycle.get(target_id)
        target_package = await export(target_id, imported_project.lifecycle_revision)
        imported_records = _issue_records(target_package)
        assert set(imported_records) == set(source_records)
        for description, source_record in source_records.items():
            assert _meaning(source_record, source_package) == _meaning(imported_records[description], target_package)

        async with transaction() as session:
            rows = await session.fetchall('SELECT * FROM continuity_issues WHERE project_id=%s', (target_id,))
            assert len(rows) == 6
            for row in rows:
                original = expected[row['description']]
                assert row['id'] != original['id']
                assert row['status'] == original['status'] and row['resolution_note'] == original['resolutionNote']
                assert row['source_canon_revision'] == original['sourceCanonRevision']
                if row['source_chapter'] is not None:
                    logical_id = source_records[row['description']].data['sourceFinalizationLogicalId']
                    mapped = str(uuid5(UUID(COMMAND_ID), f'finalization-record/{logical_id}'))
                    assert row['source_finalization_id'] == mapped
                    assert mapped != original['sourceFinalizationId']
                    assert await ContinuityIssueRepository().source_for_chapter(session, target_id, row['source_chapter']) == {
                        'project_id': target_id, 'source_chapter': row['source_chapter'],
                        'source_finalization_id': mapped, 'source_canon_revision': row['source_canon_revision'],
                    }

        archived = await lifecycle.archive(target_id, imported_project.lifecycle_revision)
        await lifecycle.permanently_delete(target_id, archived.lifecycle_revision)
        with pytest.raises(ProjectNotFound):
            await lifecycle.get(target_id, include_archived=True)
        async with transaction() as session:
            assert not await session.fetchall('SELECT id FROM continuity_issues WHERE project_id=%s', (target_id,))
            assert not await session.fetchall('SELECT id FROM finalization_records WHERE project_id=%s', (target_id,))
            source_count = await session.fetchone('SELECT COUNT(*) AS total FROM continuity_issues WHERE project_id=%s', (PROJECT_ID,))
            assert source_count['total'] == 6


async def test_old_package_without_issue_records_remains_importable(disposable_mysql, tmp_path):
    transaction = transaction_factory_for(disposable_mysql.connection_config)
    lifecycle = _lifecycle(transaction)
    source = await lifecycle.create(CreateProject(id=PROJECT_ID, title='旧格式无问题记录项目'))
    async with _packages(disposable_mysql, tmp_path) as export:
        package = await export(PROJECT_ID, source.lifecycle_revision)
        assert _issue_records(package) == {}
        assert 'continuity-issue' not in package.manifest.counts
        plan = await _publish(package, transaction)
        imported = await lifecycle.get(plan.target_project_id)
        second = await export(plan.target_project_id, imported.lifecycle_revision)
        assert _issue_records(second) == {}
        async with transaction() as session:
            assert not await session.fetchall('SELECT id FROM continuity_issues WHERE project_id=%s', (plan.target_project_id,))


async def test_permanent_delete_cleans_manual_and_formal_source_issues(disposable_mysql, monkeypatch):
    transaction = await _seed_finalized_project(disposable_mysql, monkeypatch)
    issues = ContinuityIssueService(ContinuityIssueRepository(), transaction_factory=transaction,
                                    connection_factory=transaction)
    overview = ProjectOverviewService(ProjectOverviewRepository(), connection_factory=transaction)
    assert (await overview.get(PROJECT_ID)).continuity.pending_count == 0
    created_issues = []
    for number in (None, 1):
        created = await issues.create(PROJECT_ID, CreateContinuityIssue(
            id=str(uuid5(ISSUE_NAMESPACE, f'delete-source-{number}')), category='rule',
            severity='low', description='永久删除应一并清理的问题', sourceChapterNumber=number))
        created_issues.append(created)
        assert (await overview.get(PROJECT_ID)).continuity.pending_count == len(created_issues)
    for index, status in enumerate(('resolved', 'ignored')):
        created = created_issues[index]
        await issues.update(PROJECT_ID, created['id'], UpdateContinuityIssue(
            status=status, resolutionNote='作者核对后记录处理结论', expectedUpdatedAt=created['updatedAt']))
        assert (await overview.get(PROJECT_ID)).continuity.pending_count == 1 - index
    lifecycle = _lifecycle(transaction)
    project = await lifecycle.get(PROJECT_ID)
    archived = await lifecycle.archive(PROJECT_ID, project.lifecycle_revision)
    archived_overview = await overview.get(PROJECT_ID)
    assert archived_overview.project.lifecycle == "archived"
    assert archived_overview.continuity.pending_count == 0
    await lifecycle.permanently_delete(PROJECT_ID, archived.lifecycle_revision)
    with pytest.raises(ProjectNotFound):
        await lifecycle.get(PROJECT_ID, include_archived=True)
    async with transaction() as session:
        for table in ('continuity_issues', 'finalization_records', 'final_chapters'):
            assert not await session.fetchall(f'SELECT id FROM {table} WHERE project_id=%s', (PROJECT_ID,))
