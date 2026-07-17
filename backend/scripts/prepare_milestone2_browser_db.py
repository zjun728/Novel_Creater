"""Prepare or remove one guarded disposable database for an M2 browser spec."""

from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import os
import re
import sys
import time
from typing import Awaitable, Callable, Mapping, Sequence
from uuid import UUID

from backend.domain.assets import load_asset_package
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import BindingItem, BindingRevision, TASK_KEYS
from backend.domain.seeds import SeedPayload
from backend.scripts.initialize_database import (
    _default_connection_factory,
    initialize_database,
)
from backend.scripts.seed_writer_assets import MANIFEST_PATH
from backend.services.project_lifecycle import ProjectLifecycleService
from backend.services.projections import build_projection_bundle


_DISPOSABLE_DATABASE = re.compile(r"novel_creator_test_[a-f0-9]{32}\Z")
_DATABASE_EXISTS_QUERY = (
    "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s"
)
_REQUIRED_TEST_VARIABLES = (
    "TEST_MYSQL_HOST",
    "TEST_MYSQL_PORT",
    "TEST_MYSQL_USER",
    "TEST_MYSQL_PASSWORD",
)
SCENARIOS = ("foundation", "manual", "recovery", "settings")
PROJECT_ID = "00000000-0000-0000-0000-000000000201"
SELECTED_SEED_ID = "00000000-0000-0000-0000-000000000303"
SELECTED_SEED_REVISION_ID = "00000000-0000-0000-0000-000000000313"
PROVIDER_ID = "00000000-0000-0000-0000-000000000401"
BINDING_REVISION_ID = "00000000-0000-0000-0000-000000000501"
RECOVERY_ATTEMPT_ID = "00000000-0000-0000-0000-000000000703"
RECOVERY_LEASE_EXPIRES_AT = 1_719_999_000_000
_PROVIDER_SECRET = "browser-secret-must-not-leak"
_PROVIDER_BASE_URL = "https://private-provider.example/v1"


class BrowserDatabaseSafetyError(RuntimeError):
    """The requested browser database is not provably disposable."""


def assert_browser_database_name(database_name: str) -> None:
    if (
        not isinstance(database_name, str)
        or _DISPOSABLE_DATABASE.fullmatch(database_name) is None
    ):
        raise BrowserDatabaseSafetyError(
            f"Refusing non-disposable browser database: {database_name!r}"
        )


def browser_mysql_config(
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Use only explicit TEST_MYSQL_* values as administrative authority."""
    source = os.environ if environment is None else environment
    missing = [name for name in _REQUIRED_TEST_VARIABLES if not source.get(name)]
    if missing:
        raise BrowserDatabaseSafetyError(
            "Browser MySQL requires explicit variables: " + ", ".join(missing)
        )
    try:
        port = int(source["TEST_MYSQL_PORT"])
    except (TypeError, ValueError) as exc:
        raise BrowserDatabaseSafetyError(
            "TEST_MYSQL_PORT must be an integer"
        ) from exc
    if not 1 <= port <= 65535:
        raise BrowserDatabaseSafetyError(
            "TEST_MYSQL_PORT must be between 1 and 65535"
        )
    return {
        "host": source["TEST_MYSQL_HOST"],
        "port": port,
        "user": source["TEST_MYSQL_USER"],
        "password": source["TEST_MYSQL_PASSWORD"],
        "charset": "utf8mb4",
        "autocommit": True,
    }


def _stable_id(subject: str) -> str:
    return str(UUID(hex=sha256(subject.encode("utf-8")).hexdigest()[:32]))


def _seed_payload(index: int) -> SeedPayload:
    values = (
        (
            "雾港天文钟",
            "守钟学徒发现潮汐钟会提前刻下尚未发生的海难。",
            "沈砚，一名谨慎的守钟学徒",
            "找出钟面预言与失踪导师之间的联系",
            "港务议会要在风暴季前封存天文钟",
            "百年潮墙逐夜出现未知刻度",
            "第一声错误钟鸣让整座港口退潮",
            "以钟表误差推动海港悬疑，而非复用真实作品情节",
        ),
        (
            "纸城夜航",
            "地图修复师乘纸翼艇穿行会折叠街区的夜空。",
            "顾遥，一名善于辨认旧墨迹的地图修复师",
            "在城市彻底折叠前找到失散的妹妹",
            "新地图法令要求销毁全部手绘航线",
            "每次夜航都会让一条街道从白昼消失",
            "一封没有寄件人的折纸航图落在窗台",
            "用纸张物理规则组织城市冒险，而非影射既有 IP",
        ),
        (
            "盐原回声",
            "失语测绘员在盐原下听见一座沉没绿洲的回声。",
            "林澈，一名以振动记录地形的失语测绘员",
            "证明绿洲仍在移动并带回被困的勘探队",
            "商团准备引爆盐层开采最后的淡水脉",
            "盐暴会抹去地标，也会放大地下的求救声",
            "测杆第一次记录到来自未来营地的节拍",
            "以声学测绘塑造荒原求生，不借用任何现成世界观",
        ),
    )[index - 1]
    title, logline, protagonist, desire, conflict, pressure, hook, difference = values
    return SeedPayload(
        title=title,
        genre="合成奇幻悬疑",
        logline=logline,
        protagonist=protagonist,
        desire=desire,
        coreConflict=conflict,
        worldPressure=pressure,
        openingHook=hook,
        differentiation=difference,
    )


async def _insert_assets(session, now_ms: int) -> None:
    package = load_asset_package(MANIFEST_PATH, mode="release")
    for asset in sorted(package.styles, key=lambda value: value.stable_key):
        asset_id = _stable_id(f"m2-browser-style:{asset.stable_key}:{asset.revision}")
        await session.execute(
            """INSERT INTO style_templates
               (id,stable_key,revision,name,payload_json,provenance_json,
                content_hash,status,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'active',%s)""",
            (
                asset_id,
                asset.stable_key,
                asset.revision,
                asset.name,
                canonical_json(asset.payload),
                canonical_json(asset.provenance),
                asset.content_hash,
                now_ms,
            ),
        )
        await session.execute(
            """INSERT INTO style_template_heads
               (stable_key,style_template_id,revision,content_hash,updated_at)
               VALUES (%s,%s,%s,%s,%s)""",
            (asset.stable_key, asset_id, asset.revision, asset.content_hash, now_ms),
        )
    for asset in sorted(package.experience_cards, key=lambda value: value.stable_key):
        asset_id = _stable_id(f"m2-browser-card:{asset.stable_key}:{asset.revision}")
        await session.execute(
            """INSERT INTO experience_cards
               (id,stable_key,revision,title,category,payload_json,
                provenance_json,content_hash,status,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'active',%s)""",
            (
                asset_id,
                asset.stable_key,
                asset.revision,
                asset.title,
                asset.category,
                canonical_json(asset.payload),
                canonical_json(asset.provenance),
                asset.content_hash,
                now_ms,
            ),
        )
        await session.execute(
            """INSERT INTO experience_card_heads
               (stable_key,experience_card_id,revision,content_hash,updated_at)
               VALUES (%s,%s,%s,%s,%s)""",
            (asset.stable_key, asset_id, asset.revision, asset.content_hash, now_ms),
        )


async def _insert_foundation(
    session,
    now_ms: int,
    *,
    unbound_writing: bool = False,
) -> tuple[str, str]:
    await session.execute(
        """INSERT INTO projects
           (id,title,genre,description,target_words,target_chapters,status,
            current_chapter,created_at,updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,'drafting',0,%s,%s)""",
        (
            PROJECT_ID,
            "合成浏览器验收项目",
            "合成奇幻悬疑",
            "仅由原创合成数据组成的 Writer Core M2 浏览器验收项目。",
            600_000,
            180,
            now_ms,
            now_ms,
        ),
    )
    selected_hash = ""
    for index in range(1, 4):
        seed_id = f"00000000-0000-0000-0000-00000000030{index}"
        revision_id = f"00000000-0000-0000-0000-00000000031{index}"
        payload = _seed_payload(index)
        payload_hash = canonical_hash(payload)
        await session.execute(
            """INSERT INTO creative_seeds
               (id,project_id,status,created_at,updated_at)
               VALUES (%s,%s,'candidate',%s,%s)""",
            (seed_id, PROJECT_ID, now_ms, now_ms),
        )
        await session.execute(
            """INSERT INTO creative_seed_revisions
               (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
               VALUES (%s,%s,%s,1,%s,%s,%s)""",
            (
                revision_id,
                PROJECT_ID,
                seed_id,
                canonical_json(payload),
                payload_hash,
                now_ms,
            ),
        )
        await session.execute(
            """INSERT INTO creative_seed_heads
               (seed_id,revision_id,revision,content_hash,updated_at)
               VALUES (%s,%s,1,%s,%s)""",
            (seed_id, revision_id, payload_hash, now_ms),
        )
        if seed_id == SELECTED_SEED_ID:
            selected_hash = payload_hash

    await session.execute(
        """INSERT INTO project_selected_seeds
           (project_id,seed_id,seed_revision_id,seed_hash,selection_revision,
            selected_at,updated_at)
           VALUES (%s,%s,%s,%s,1,%s,%s)""",
        (
            PROJECT_ID,
            SELECTED_SEED_ID,
            SELECTED_SEED_REVISION_ID,
            selected_hash,
            now_ms,
            now_ms,
        ),
    )
    await session.execute(
        """INSERT INTO provider_profiles
           (id,name,provider_type,model_name,base_url,api_key,enabled,sort_order,
            stream,max_context_tokens,max_output_tokens,temperature,top_p,
            supports_json,supports_streaming,notes,thinking,lifecycle_status,
            deleted_at,created_at,updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,1,0,1,%s,%s,%s,%s,1,1,%s,NULL,
                   'active',NULL,%s,%s)""",
        (
            PROVIDER_ID,
            "合成浏览器 Provider",
            "openai-compatible",
            "browser-test-model",
            _PROVIDER_BASE_URL,
            _PROVIDER_SECRET,
            200_000,
            4096,
            "0.800",
            "0.900",
            "M2 browser fixture; automated tests never call this Provider.",
            now_ms,
            now_ms,
        ),
    )
    binding_items = tuple(
        BindingItem(
            task_key=task_key,
            resolution_status=(
                "unbound" if unbound_writing and task_key == "writing" else "bound"
            ),
            provider_id=(
                None if unbound_writing and task_key == "writing" else PROVIDER_ID
            ),
            provider_name_snapshot=(
                None
                if unbound_writing and task_key == "writing"
                else "合成浏览器 Provider"
            ),
            model_name_snapshot=(
                None
                if unbound_writing and task_key == "writing"
                else "browser-test-model"
            ),
        )
        for task_key in TASK_KEYS
    )
    binding = BindingRevision(
        project_id=PROJECT_ID,
        revision=1,
        items=binding_items,
    )
    binding_hash = canonical_hash(binding)
    await session.execute(
        """INSERT INTO project_model_binding_revisions
           (id,project_id,revision,content_hash,source_project_id,created_at)
           VALUES (%s,%s,1,%s,NULL,%s)""",
        (BINDING_REVISION_ID, PROJECT_ID, binding_hash, now_ms),
    )
    for item in binding_items:
        await session.execute(
            """INSERT INTO project_model_binding_items
               (binding_revision_id,task_key,resolution_status,provider_id,
                provider_name_snapshot,model_name_snapshot,item_hash)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (
                BINDING_REVISION_ID,
                item.task_key,
                item.resolution_status,
                item.provider_id,
                item.provider_name_snapshot,
                item.model_name_snapshot,
                canonical_hash(item),
            ),
        )
    await session.execute(
        """INSERT INTO project_model_binding_heads
           (project_id,revision,binding_revision_id,content_hash,updated_at)
           VALUES (%s,1,%s,%s,%s)""",
        (PROJECT_ID, BINDING_REVISION_ID, binding_hash, now_ms),
    )

    empty_hash = build_projection_bundle(0, ()).content_hash
    await session.execute(
        """INSERT INTO canon_revisions
           (id,project_id,revision_number,parent_revision_number,idempotency_key,
            source_type,source_id,content_hash,created_at)
           VALUES (%s,%s,0,0,%s,'bootstrap',NULL,%s,%s)""",
        (
            "00000000-0000-0000-0000-000000000601",
            PROJECT_ID,
            ProjectLifecycleService.bootstrap_idempotency_key(PROJECT_ID),
            empty_hash,
            now_ms,
        ),
    )
    await session.execute(
        """INSERT INTO projection_heads
           (project_id,canon_revision_number,projection_revision_number,
            content_hash,updated_at) VALUES (%s,0,0,%s,%s)""",
        (PROJECT_ID, empty_hash, now_ms),
    )
    await session.execute(
        """INSERT INTO project_contract_heads
           (project_id,revision,creation_contract_id,style_contract_id,
            creation_hash,style_hash,updated_at)
           VALUES (%s,0,NULL,NULL,NULL,NULL,%s)""",
        (PROJECT_ID, now_ms),
    )
    await _insert_assets(session, now_ms)
    return selected_hash, binding_hash


async def _insert_recovery_batches(
    session,
    now_ms: int,
    selected_hash: str,
    binding_hash: str,
) -> None:
    request = {
        "sourceType": "provider",
        "seed": {
            "id": SELECTED_SEED_ID,
            "revisionId": SELECTED_SEED_REVISION_ID,
            "hash": selected_hash,
        },
        "binding": {
            "revisionId": BINDING_REVISION_ID,
            "hash": binding_hash,
        },
        "provider": {"id": PROVIDER_ID, "modelName": "browser-test-model"},
        "fixture": "synthetic-recovery-precondition",
    }
    request_json = canonical_json(request)
    request_hash = canonical_hash(request)
    common = (
        PROJECT_ID,
        "provider",
        SELECTED_SEED_ID,
        SELECTED_SEED_REVISION_ID,
        selected_hash,
        BINDING_REVISION_ID,
        binding_hash,
        PROVIDER_ID,
        "browser-test-model",
    )
    await session.execute(
        """INSERT INTO story_engine_batches
           (id,project_id,source_type,seed_id,seed_revision_id,seed_hash,
            binding_revision_id,binding_hash,provider_id,model_name_snapshot,
            idempotency_key,request_json,request_hash,status,attempt_id,
            attempt_started_at,lease_expires_at,raw_response_text,
            raw_response_hash,public_error_code,created_at,finished_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                   NULL,NULL,NULL,%s,NULL)""",
        (
            "00000000-0000-0000-0000-000000000701",
            *common,
            sha256(b"m2-recovery-running").hexdigest(),
            request_json,
            request_hash,
            "running",
            RECOVERY_ATTEMPT_ID,
            RECOVERY_LEASE_EXPIRES_AT - 240_000,
            RECOVERY_LEASE_EXPIRES_AT,
            now_ms - 600_000,
        ),
    )
    await session.execute(
        """INSERT INTO story_engine_batches
           (id,project_id,source_type,seed_id,seed_revision_id,seed_hash,
            binding_revision_id,binding_hash,provider_id,model_name_snapshot,
            idempotency_key,request_json,request_hash,status,attempt_id,
            attempt_started_at,lease_expires_at,raw_response_text,
            raw_response_hash,public_error_code,created_at,finished_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,
                   NULL,NULL,NULL,NULL,%s,NULL)""",
        (
            "00000000-0000-0000-0000-000000000702",
            *common,
            sha256(b"m2-recovery-reserved").hexdigest(),
            request_json,
            request_hash,
            "reserved",
            now_ms - 600_000,
        ),
    )


async def seed_scenario(session, scenario: str, now_ms: int) -> None:
    if scenario not in SCENARIOS:
        raise BrowserDatabaseSafetyError(f"Unsupported M2 browser scenario: {scenario!r}")
    await session.execute("START TRANSACTION")
    try:
        selected_hash, binding_hash = await _insert_foundation(
            session,
            now_ms,
            unbound_writing=scenario == "foundation",
        )
        if scenario == "recovery":
            await _insert_recovery_batches(
                session,
                now_ms,
                selected_hash,
                binding_hash,
            )
        await session.execute("COMMIT")
    except BaseException as body_error:
        try:
            await session.execute("ROLLBACK")
        except BaseException as rollback_error:
            raise BaseExceptionGroup(
                "M2 browser fixture insert and rollback both failed",
                [body_error, rollback_error],
            ) from body_error
        raise


async def _drop_database(session, database_name: str) -> None:
    assert_browser_database_name(database_name)
    await session.execute(f"DROP DATABASE IF EXISTS `{database_name}`")
    remaining = await session.fetchone(_DATABASE_EXISTS_QUERY, (database_name,))
    if remaining is not None:
        raise BrowserDatabaseSafetyError(
            f"Disposable browser database still exists after cleanup: {database_name}"
        )


async def _prepare_database(
    session,
    database_name: str,
    scenario: str,
    now_ms: int,
) -> None:
    assert_browser_database_name(database_name)
    await initialize_database(session, database_name, database_name, now_ms)
    try:
        await seed_scenario(session, scenario, now_ms)
    except BaseException as prepare_error:
        try:
            await _drop_database(session, database_name)
        except BaseException as cleanup_error:
            raise BaseExceptionGroup(
                "M2 browser database preparation and cleanup both failed",
                [prepare_error, cleanup_error],
            ) from prepare_error
        raise


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare or drop one disposable M2 browser database"
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--scenario", required=True, choices=SCENARIOS)
    parser.add_argument("--drop", action="store_true")
    return parser


async def run_cli(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    connection_factory: Callable[[Mapping[str, object]], Awaitable[object]] | None = None,
    now_ms: Callable[[], int] | None = None,
    output: Callable[[str], None] = print,
) -> int:
    args = _argument_parser().parse_args(argv)
    assert_browser_database_name(args.database)
    config = browser_mysql_config(environment)
    factory = connection_factory or _default_connection_factory
    session = await factory(config)
    errors: list[BaseException] = []
    try:
        if args.drop:
            await _drop_database(session, args.database)
        else:
            timestamp = (now_ms or (lambda: int(time.time() * 1000)))()
            await _prepare_database(session, args.database, args.scenario, timestamp)
    except BaseException as exc:
        errors.append(exc)
    try:
        await session.close()
    except BaseException as exc:
        errors.append(exc)
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise BaseExceptionGroup(
            "M2 browser database operation and connection close both failed",
            errors,
        )
    action = "dropped" if args.drop else "prepared"
    output(f"scenario={args.scenario} action={action}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(run_cli(argv))
    except SystemExit:
        raise
    except BaseException:
        print("M2 browser database operation failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
