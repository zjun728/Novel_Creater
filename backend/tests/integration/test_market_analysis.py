from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import importlib
import json

import pytest

from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = [pytest.mark.mysql, pytest.mark.asyncio]
NOW = 1_721_000_000_000
PROJECT_ID = "71000000-0000-0000-0000-000000000001"
PROVIDER_ID = "71000000-0000-0000-0000-000000000002"
BINDING_ID = "71000000-0000-0000-0000-000000000003"
SOURCE_ID = "71000000-0000-0000-0000-000000000004"
POLICY_ID = "71000000-0000-0000-0000-000000000005"
SNAPSHOT_A = "71000000-0000-0000-0000-000000000006"
SNAPSHOT_B = "71000000-0000-0000-0000-000000000007"
MANIFEST_A = "71000000-0000-0000-0000-000000000008"
MANIFEST_B = "71000000-0000-0000-0000-000000000009"


def _feature():
    try:
        domain = importlib.import_module("backend.domain.market_analysis")
        gateway = importlib.import_module(
            "backend.gateways.market_analysis_provider"
        )
        service = importlib.import_module("backend.services.market_analysis")
    except ModuleNotFoundError:
        pytest.fail("frozen market analysis integration feature is missing")
    return domain, gateway, service


def _payload() -> dict:
    fact = {
        "text": "公开榜单中穿越题材占有一定位置。",
        "snapshotIds": [SNAPSHOT_A],
        "inference": False,
    }
    inference = {
        "text": "穿越与群像经营的组合可能有增长空间。",
        "snapshotIds": [SNAPSHOT_A, SNAPSHOT_B],
        "inference": True,
    }
    return {
        "currentHeat": [fact],
        "growthDirections": [inference],
        "crowding": [fact],
        "opportunities": [inference],
        "uncertainties": [fact],
        "sourceCoverage": {
            "snapshotIds": [SNAPSHOT_A, SNAPSHOT_B],
            "summary": "覆盖两份冻结公开榜单快照。",
        },
    }


async def _seed(session):
    await session.execute(
        """INSERT INTO projects
           (id,title,genre,description,target_words,target_chapters,status,
            current_chapter,archived_at,lifecycle_revision,created_at,updated_at)
           VALUES (%s,'分析项目','玄幻','test',100000,100,'drafting',0,NULL,0,%s,%s)""",
        (PROJECT_ID, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO provider_profiles
           (id,name,provider_type,model_name,base_url,api_key,enabled,sort_order,
            stream,max_context_tokens,max_output_tokens,temperature,top_p,
            supports_json,supports_streaming,notes,thinking,lifecycle_status,
            revision,deleted_at,created_at,updated_at)
           VALUES (%s,'Analysis Provider','openai-compatible',
                   'deepseek-v4-flash','https://provider.invalid/v1',
                   'PRIVATE_INTEGRATION_KEY',1,1,0,128000,2400,0.2,0.9,1,0,
                   '',NULL,'active',1,NULL,%s,%s)""",
        (PROVIDER_ID, NOW, NOW),
    )
    await session.execute(
        """INSERT INTO project_model_binding_revisions
           (id,project_id,revision,content_hash,source_project_id,created_at)
           VALUES (%s,%s,1,%s,NULL,%s)""",
        (BINDING_ID, PROJECT_ID, "d" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO project_model_binding_items
           (binding_revision_id,task_key,resolution_status,provider_id,
            provider_name_snapshot,model_name_snapshot,item_hash)
           VALUES (%s,'market','bound',%s,'Analysis Provider',
                   'deepseek-v4-flash',%s)""",
        (BINDING_ID, PROVIDER_ID, "f" * 64),
    )
    await session.execute(
        """INSERT INTO project_model_binding_heads
           (project_id,revision,binding_revision_id,content_hash,updated_at)
           VALUES (%s,1,%s,%s,%s)""",
        (PROJECT_ID, BINDING_ID, "d" * 64, NOW),
    )
    await session.execute(
        """INSERT INTO market_sources
           (id,stable_key,adapter_key,display_name,public_config_json,status,
            created_at,updated_at)
           VALUES (%s,'fixture.rank','qidian_public_rank','Fixture Rank',
                   %s,'active',%s,%s)""",
        (
            SOURCE_ID,
            json.dumps(
                {
                    "platform": "qidian",
                    "rankingName": "newsign",
                    "category": "male",
                }
            ),
            NOW,
            NOW,
        ),
    )
    await session.execute(
        """INSERT INTO market_source_policy_revisions
           (id,source_id,revision,policy_status,policy_version,checked_at,
            evidence_url,evidence_hash,allowed_origins_json,path_prefixes_json,
            enabled,interval_minutes,next_run_at,content_hash,created_at)
           VALUES (%s,%s,1,'manual_only','fixture-v1',%s,
                   'https://evidence.invalid/rank',%s,%s,%s,0,360,NULL,%s,%s)""",
        (
            POLICY_ID,
            SOURCE_ID,
            NOW,
            "1" * 64,
            '["https://www.qidian.com"]',
            '["/rank/"]',
            "2" * 64,
            NOW,
        ),
    )
    await session.execute(
        """INSERT INTO market_source_policy_heads
           (source_id,revision_id,revision,content_hash,updated_at)
           VALUES (%s,%s,1,%s,%s)""",
        (SOURCE_ID, POLICY_ID, "2" * 64, NOW),
    )
    for index, (snapshot_id, snapshot_hash, manifest_id, manifest_hash) in enumerate(
        (
            (SNAPSHOT_A, "a" * 64, MANIFEST_A, "b" * 64),
            (SNAPSHOT_B, "c" * 64, MANIFEST_B, "e" * 64),
        ),
        start=1,
    ):
        await session.execute(
            """INSERT INTO market_snapshots
               (id,source_id,captured_at,platform,ranking_name,category,
                source_url,content_hash,entry_count,created_at)
               VALUES (%s,%s,%s,'qidian','newsign','male',
                       'https://www.qidian.com/rank/newsign/',%s,1,%s)""",
            (snapshot_id, SOURCE_ID, NOW + index, snapshot_hash, NOW),
        )
        await session.execute(
            """INSERT INTO market_snapshot_entries
               (id,source_id,snapshot_id,rank_number,title,author,category,
                work_url,public_metrics_json,content_hash,created_at)
               VALUES (%s,%s,%s,1,%s,'合成作者','玄幻',%s,%s,%s,%s)""",
            (
                f"72000000-0000-0000-0000-{index:012d}",
                SOURCE_ID,
                snapshot_id,
                f"作品{index}",
                f"https://www.qidian.com/book/{900000000 + index}/",
                json.dumps({"weeklyRecommendations": index * 100}),
                str(index) * 64,
                NOW,
            ),
        )
        await session.execute(
            """INSERT INTO market_snapshot_manifests
               (id,source_id,snapshot_id,snapshot_hash,policy_revision_id,
                policy_revision,policy_hash,adapter_version,manifest_json,
                manifest_hash,created_at)
               VALUES (%s,%s,%s,%s,%s,1,%s,'fixture-v1',%s,%s,%s)""",
            (
                manifest_id,
                SOURCE_ID,
                snapshot_id,
                snapshot_hash,
                POLICY_ID,
                "2" * 64,
                json.dumps({"snapshotId": snapshot_id}),
                manifest_hash,
                NOW,
            ),
        )


class BlockingGateway:
    def __init__(self, response, *, error=None, before_return=None):
        self.response = response
        self.error = error
        self.before_return = before_return
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False

    async def generate(self, **_values):
        self.calls += 1
        self.started.set()
        if self.block:
            await self.release.wait()
        if self.before_return is not None:
            await self.before_return()
        if self.error is not None:
            raise self.error
        return json.dumps(self.response, ensure_ascii=False)


async def test_analysis_idempotency_concurrency_failure_and_manifest_race(
    disposable_mysql,
):
    domain, gateway_module, service_module = _feature()
    await _seed(disposable_mysql.session)
    transaction = transaction_factory_for(disposable_mysql.connection_config)

    @asynccontextmanager
    async def connection():
        yield disposable_mysql.session

    ids = iter(
        f"73000000-0000-0000-0000-{index:012d}"
        for index in range(1, 100)
    )
    from backend.repositories.market import MarketRepository

    gateway = BlockingGateway(_payload())
    gateway.block = True
    service = service_module.MarketAnalysisService(
        MarketRepository(),
        transaction_factory=transaction,
        connection_factory=connection,
        provider_gateway=gateway,
        id_factory=lambda: next(ids),
        clock=iter(range(NOW + 100, NOW + 1000)).__next__,
    )
    command = service_module.AnalyzeMarket(
        project_id=PROJECT_ID,
        snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
        idempotency_key="i" * 64,
    )
    first_task = asyncio.create_task(service.analyze(command))
    await gateway.started.wait()
    concurrent = await service.analyze(command)
    assert concurrent.status == "running"
    gateway.release.set()
    first = await first_task
    replay = await service.analyze(command)
    assert first.status == replay.status == "succeeded"
    assert replay.result_hash == first.result_hash
    assert gateway.calls == 1

    with pytest.raises(domain.MarketAnalysisFailure) as conflict:
        await service.analyze(
            service_module.AnalyzeMarket(
                project_id=PROJECT_ID,
                snapshot_ids=(SNAPSHOT_B, SNAPSHOT_A),
                idempotency_key="i" * 64,
            )
        )
    assert conflict.value.code == "MARKET_ANALYSIS_IDEMPOTENCY_CONFLICT"
    assert gateway.calls == 1

    simultaneous_count = 0
    simultaneous_lock = asyncio.Lock()
    simultaneous_ready = asyncio.Event()

    @asynccontextmanager
    async def simultaneous_transaction():
        nonlocal simultaneous_count
        async with transaction() as session:
            async with simultaneous_lock:
                simultaneous_count += 1
                sequence = simultaneous_count
                if simultaneous_count >= 2:
                    simultaneous_ready.set()
            if sequence <= 2:
                await simultaneous_ready.wait()
            yield session

    simultaneous_gateway = BlockingGateway(_payload())
    simultaneous_service = service_module.MarketAnalysisService(
        MarketRepository(),
        transaction_factory=simultaneous_transaction,
        connection_factory=connection,
        provider_gateway=simultaneous_gateway,
        id_factory=lambda: next(ids),
        clock=iter(range(NOW + 500, NOW + 1000)).__next__,
    )
    simultaneous_command = service_module.AnalyzeMarket(
        project_id=PROJECT_ID,
        snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
        idempotency_key="q" * 64,
    )
    contenders = await asyncio.gather(
        simultaneous_service.analyze(simultaneous_command),
        simultaneous_service.analyze(simultaneous_command),
        return_exceptions=True,
    )
    assert not any(isinstance(item, BaseException) for item in contenders)
    assert {item.status for item in contenders}.issubset(
        {"running", "succeeded"}
    )
    simultaneous_replay = await simultaneous_service.analyze(
        simultaneous_command
    )
    assert simultaneous_replay.status == "succeeded"
    assert simultaneous_gateway.calls == 1

    failed_gateway = BlockingGateway(
        _payload(),
        error=gateway_module.MarketAnalysisProviderHTTPError(
            "provider request failed"
        ),
    )
    failed_service = service_module.MarketAnalysisService(
        MarketRepository(),
        transaction_factory=transaction,
        connection_factory=connection,
        provider_gateway=failed_gateway,
        id_factory=lambda: next(ids),
        clock=iter(range(NOW + 1000, NOW + 2000)).__next__,
    )
    failed = await failed_service.analyze(
        service_module.AnalyzeMarket(
            project_id=PROJECT_ID,
            snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
            idempotency_key="f" * 64,
        )
    )
    assert failed.status == "failed"
    assert failed.analysis is None
    assert failed.public_error_code == "MARKET_ANALYSIS_PROVIDER_FAILED"

    async def mutate_manifest():
        await disposable_mysql.session.execute(
            """UPDATE market_snapshot_manifests
               SET manifest_hash=%s WHERE snapshot_id=%s""",
            ("9" * 64, SNAPSHOT_A),
        )

    race_gateway = BlockingGateway(_payload(), before_return=mutate_manifest)
    race_service = service_module.MarketAnalysisService(
        MarketRepository(),
        transaction_factory=transaction,
        connection_factory=connection,
        provider_gateway=race_gateway,
        id_factory=lambda: next(ids),
        clock=iter(range(NOW + 2000, NOW + 3000)).__next__,
    )
    raced = await race_service.analyze(
        service_module.AnalyzeMarket(
            project_id=PROJECT_ID,
            snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
            idempotency_key="r" * 64,
        )
    )
    assert raced.status == "failed"
    assert raced.analysis is None
    assert raced.public_error_code == "MARKET_ANALYSIS_INPUT_CHANGED"

    rows = await disposable_mysql.session.fetchall(
        """SELECT status,analysis_json,result_hash,public_error_code
           FROM market_analyses WHERE project_id=%s ORDER BY created_at,id""",
        (PROJECT_ID,),
    )
    assert [row["status"] for row in rows] == [
        "succeeded",
        "succeeded",
        "failed",
        "failed",
    ]
    assert rows[2]["analysis_json"] is None
    assert rows[2]["result_hash"] is None
    rendered = json.dumps(rows, default=str)
    assert "PRIVATE_INTEGRATION_KEY" not in rendered
    assert "provider.invalid" not in rendered

    await disposable_mysql.session.execute(
        """UPDATE project_model_binding_items
           SET resolution_status='unbound',provider_id=NULL,
               provider_name_snapshot=NULL,model_name_snapshot=NULL,
               item_hash=%s
           WHERE binding_revision_id=%s AND task_key='market'""",
        ("0" * 64, BINDING_ID),
    )
    not_ready_gateway = BlockingGateway(_payload())
    not_ready_service = service_module.MarketAnalysisService(
        MarketRepository(),
        transaction_factory=transaction,
        connection_factory=connection,
        provider_gateway=not_ready_gateway,
        id_factory=lambda: next(ids),
        clock=lambda: NOW + 4000,
    )
    with pytest.raises(domain.MarketAnalysisFailure) as not_ready:
        await not_ready_service.analyze(
            service_module.AnalyzeMarket(
                project_id=PROJECT_ID,
                snapshot_ids=(SNAPSHOT_A, SNAPSHOT_B),
                idempotency_key="n" * 64,
            )
        )
    assert not_ready.value.code == "MARKET_ANALYSIS_NOT_READY"
    assert not_ready_gateway.calls == 0

    from backend.domain.seeds import SeedPayload
    from backend.repositories.seeds import SeedRepository
    from backend.services.seeds import CreateSeed, SeedService

    seed_ids = iter(
        (
            "74000000-0000-0000-0000-000000000001",
            "74000000-0000-0000-0000-000000000002",
        )
    )
    manual_seed = await SeedService(
        SeedRepository(),
        transaction_factory=transaction,
        id_factory=lambda: next(seed_ids),
        clock=lambda: NOW + 5000,
    ).create(
        CreateSeed(
            project_id=PROJECT_ID,
            payload=SeedPayload(
                title="手工种子",
                genre="玄幻",
                logline="穿越者从公开档案中寻找失落传承。",
                protagonist="谨慎的基层档案员",
                desire="保护身边的人",
                coreConflict="个人选择与庞大秩序冲突",
                worldPressure="灵气复苏后的阶层压力",
                openingHook="一页不存在于目录里的古籍突然显字",
                differentiation="群像经营与知识考据并行",
            ),
        )
    )
    assert manual_seed.payload.title == "手工种子"
