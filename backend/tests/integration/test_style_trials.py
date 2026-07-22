from __future__ import annotations

import asyncio
from hashlib import sha256
import json

import httpx
import pytest

from backend.domain.json_contracts import canonical_json
from backend.domain.style_trials import (
    GenerateStyleTrial,
    StyleTrialFailure,
    StyleTrialProviderOutput,
)
from backend.gateways.style_trial_provider import (
    StyleTrialProviderError,
    StyleTrialProviderGateway,
)
from backend.repositories.style_trials import StyleTrialRepository
from backend.services.style_trials import StyleTrialService
from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = pytest.mark.mysql

PROJECT_ID = "style-project"
SEED_HASH = "1" * 64
ENGINE_HASH = "2" * 64
PRIMARY_HASH = "3" * 64
SECONDARY_HASH = "4" * 64
BINDING_HASH = "5" * 64


def _seed_payload():
    return {
        "title": "典镇山河",
        "genre": "历史穿越",
        "logline": "守住失散的典籍",
        "protagonist": "沈砚",
        "desire": "让同伴活着离开",
        "coreConflict": "知识会招来争夺",
        "worldPressure": "战乱逼近",
        "openingHook": "残页显字",
        "differentiation": "每次使用知识都有代价",
    }


def _engine_payload():
    return {
        "name": "残典求生",
        "storyPromise": "知识改变处境也制造新债",
        "protagonistDesire": "保住同伴与残典",
        "sustainedPressure": "官府、豪强与战乱持续收紧空间",
        "growthDirection": "从独自判断走向组织同伴",
        "conflictLoop": "线索、资源、代价、新压力",
        "ensembleRoles": [{"role": "抄书匠", "purpose": "质疑牺牲"}],
        "advantageAndCost": "懂旧制但暴露会招来危险",
        "satisfactionSources": ["知识解决现实难题"],
        "longFormVariation": ["地方生存", "制度博弈"],
        "endingAnchor": "让知识可以传承",
        "risks": ["知识不能成为万能答案"],
        "differentiation": "解决问题会改变人物关系",
    }


def _style_payload(anchor: str):
    return {
        "schemaVersion": "style-template-v1",
        "reading_experience": "人物先做选择",
        "applicability": ["历史穿越"],
        "non_applicability": ["纯说明"],
        "standard_scene_example": "短示例",
        "complete_application_example": "完整示例",
        "narrative_distance": "贴近人物",
        "rhythm": "压力、选择、后果",
        "diction_density": "具体动词",
        "dialogue": "各说现实账",
        "subtext": "条件藏诉求",
        "character_voices": "欲望区分声音",
        "emotion": "情绪改变行动",
        "interiority": "念头落到决定",
        "action": "动作改变局面",
        "explanation": "先后果后规则",
        "environment": "环境约束行动",
        "body_response": "疲惫影响判断",
        "preferred_techniques": ["代价可见"],
        "risks": ["避免清单感"],
        "original_anchor": anchor,
    }


def _oversized_style_payload(anchor: str):
    payload = _style_payload(anchor)
    payload["standard_scene_example"] = "例" * 20_000
    payload["complete_application_example"] = "文" * 20_000
    return payload


async def _bootstrap(session):
    now = 1_700_000_000_000
    await session.execute(
        """INSERT INTO projects
           (id,title,genre,description,target_words,target_chapters,status,
            current_chapter,created_at,updated_at)
           VALUES (%s,'Style Trial','history','test only',100000,100,
                   'drafting',0,%s,%s)""",
        (PROJECT_ID, now, now),
    )
    await session.execute(
        """INSERT INTO creative_seeds
           (id,project_id,status,created_at,updated_at)
           VALUES ('seed-style',%s,'candidate',%s,%s)""",
        (PROJECT_ID, now, now),
    )
    await session.execute(
        """INSERT INTO creative_seed_revisions
           (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
           VALUES ('seed-style-rev',%s,'seed-style',1,%s,%s,%s)""",
        (PROJECT_ID, canonical_json(_seed_payload()), SEED_HASH, now),
    )
    await session.execute(
        """INSERT INTO creative_seed_heads
           (seed_id,revision_id,revision,content_hash,updated_at)
           VALUES ('seed-style','seed-style-rev',1,%s,%s)""",
        (SEED_HASH, now),
    )
    await session.execute(
        """INSERT INTO project_seed_selection_revisions
           (project_id,selection_revision,seed_id,seed_revision_id,seed_hash,selected_at)
           VALUES (%s,1,'seed-style','seed-style-rev',%s,%s)""",
        (PROJECT_ID, SEED_HASH, now),
    )
    await session.execute(
        """INSERT INTO project_selected_seeds
           (project_id,seed_id,seed_revision_id,seed_hash,selection_revision,
            selected_at,updated_at)
           VALUES (%s,'seed-style','seed-style-rev',%s,1,%s,%s)""",
        (PROJECT_ID, SEED_HASH, now, now),
    )
    await session.execute(
        """INSERT INTO provider_profiles
           (id,name,provider_type,model_name,base_url,api_key,enabled,sort_order,
            stream,max_context_tokens,max_output_tokens,temperature,top_p,
            supports_json,supports_streaming,notes,thinking,lifecycle_status,
            revision,deleted_at,created_at,updated_at)
           VALUES ('provider-style','Style Provider','openai-compatible',
                   'deepseek-v4-flash','https://style.test.invalid/v1',
                   'integration-secret-key',1,0,0,10000,4096,0.7,1.0,1,0,
                   'test only',NULL,'active',7,NULL,%s,%s)""",
        (now, now),
    )
    await session.execute(
        """INSERT INTO project_model_binding_revisions
           (id,project_id,revision,content_hash,source_project_id,created_at)
           VALUES ('binding-style',%s,1,%s,NULL,%s)""",
        (PROJECT_ID, BINDING_HASH, now),
    )
    await session.execute(
        """INSERT INTO project_model_binding_items
           (binding_revision_id,task_key,resolution_status,provider_id,
            provider_name_snapshot,model_name_snapshot,item_hash)
           VALUES ('binding-style','seed','bound','provider-style',
                   'Style Provider','deepseek-v4-flash',%s)""",
        ("6" * 64,),
    )
    await session.execute(
        """INSERT INTO project_model_binding_heads
           (project_id,revision,binding_revision_id,content_hash,updated_at)
           VALUES (%s,1,'binding-style',%s,%s)""",
        (PROJECT_ID, BINDING_HASH, now),
    )
    await session.execute(
        """INSERT INTO story_engine_batches
           (id,project_id,selection_revision,source_type,seed_id,seed_revision_id,
            seed_hash,binding_revision_id,binding_hash,provider_id,
            model_name_snapshot,idempotency_key,request_json,request_hash,status,
            attempt_id,attempt_started_at,lease_expires_at,raw_response_text,
            raw_response_hash,public_error_code,created_at,finished_at)
           VALUES ('engine-batch',%s,1,'manual','seed-style','seed-style-rev',%s,
                   NULL,NULL,NULL,NULL,%s,%s,%s,'succeeded',NULL,NULL,NULL,NULL,
                   NULL,NULL,%s,%s)""",
        (PROJECT_ID, SEED_HASH, "m" * 64, "{}", "7" * 64, now, now),
    )
    await session.execute(
        """INSERT INTO story_engine_options
           (id,project_id,selection_revision,batch_id,option_order,payload_json,
            content_hash,created_at)
           VALUES ('engine-option',%s,1,'engine-batch',1,%s,%s,%s)""",
        (PROJECT_ID, canonical_json(_engine_payload()), ENGINE_HASH, now),
    )
    for revision_id, stable_key, content_hash, anchor in (
        ("style-primary", "primary-style", PRIMARY_HASH, "主锚点"),
        ("style-secondary", "secondary-style", SECONDARY_HASH, "辅锚点"),
    ):
        await session.execute(
            """INSERT INTO style_templates
               (id,stable_key,revision,name,payload_json,provenance_json,
                content_hash,status,created_at)
               VALUES (%s,%s,1,%s,%s,%s,%s,'active',%s)""",
            (
                revision_id,
                stable_key,
                stable_key,
                canonical_json(_style_payload(anchor)),
                canonical_json({"decision": "approved"}),
                content_hash,
                now,
            ),
        )
        await session.execute(
            """INSERT INTO style_template_heads
               (stable_key,style_template_id,revision,content_hash,updated_at)
               VALUES (%s,%s,1,%s,%s)""",
            (stable_key, revision_id, content_hash, now),
        )


class Gateway:
    def __init__(self, *, fail=False, before_return=None):
        self.calls = 0
        self.fail = fail
        self.before_return = before_return

    async def generate(self, **_kwargs):
        self.calls += 1
        if self.fail:
            raise StyleTrialProviderError("provider failed")
        if self.before_return is not None:
            await self.before_return()
        return StyleTrialProviderOutput(sample="城门铜铃响到第三遍时，沈砚终于松开了残页。")


def _command(**changes):
    values = {
        "project_id": PROJECT_ID,
        "selection_revision": 1,
        "engine_option_id": "engine-option",
        "engine_hash": ENGINE_HASH,
        "primary_style_revision_id": "style-primary",
        "primary_style_hash": PRIMARY_HASH,
        "secondary_style_revision_id": "style-secondary",
        "secondary_style_hash": SECONDARY_HASH,
        "author_scenario": "主角必须在救人和保住残页之间选择。",
        "idempotency_key": "i" * 64,
    }
    values.update(changes)
    return GenerateStyleTrial(**values)


def _service(database, gateway):
    factory = transaction_factory_for(database.connection_config)
    ids = iter(("style-request", "style-attempt"))
    return StyleTrialService(
        StyleTrialRepository(),
        transaction_factory=factory,
        provider_gateway=gateway,
        id_factory=lambda: next(ids),
        clock=lambda: 1_700_000_000_100,
    )


@pytest.mark.asyncio
async def test_success_persists_only_safe_manifest_and_validated_result_then_replays(
    disposable_mysql,
):
    await _bootstrap(disposable_mysql.session)
    gateway = Gateway()
    service = _service(disposable_mysql, gateway)

    first = await service.generate(_command())
    replay = await service.generate(_command())

    assert replay == first
    assert gateway.calls == 1
    request = await disposable_mysql.session.fetchone(
        "SELECT * FROM style_trial_requests WHERE project_id=%s", (PROJECT_ID,)
    )
    attempt = await disposable_mysql.session.fetchone(
        "SELECT * FROM style_trial_attempts WHERE project_id=%s", (PROJECT_ID,)
    )
    assert request["status"] == attempt["status"] == "succeeded"
    assert request["attempt_id"] == attempt["id"] == "style-attempt"
    assert json.loads(attempt["result_json"]) == {"sample": first.sample}
    manifest = json.loads(attempt["input_manifest_json"])
    assert "authorScenario" not in manifest
    assert manifest["scenarioHash"] == sha256(
        _command().author_scenario.encode("utf-8")
    ).hexdigest()
    assert manifest["scenarioLength"] == len(_command().author_scenario)
    assert manifest["provider"] == {
        "providerId": "provider-style",
        "providerType": "openai-compatible",
        "modelName": "deepseek-v4-flash",
        "profileRevision": 7,
    }
    stored = json.dumps({"request": request, "attempt": attempt}, default=str)
    assert _command().author_scenario not in stored
    assert "integration-secret-key" not in stored
    assert "style.test.invalid" not in stored
    assert "prompt" not in stored.lower()

    with pytest.raises(StyleTrialFailure) as conflict:
        await service.generate(_command(author_scenario="另一个场景"))
    assert conflict.value.code == "STYLE_TRIAL_IDEMPOTENCY_CONFLICT"
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_provider_observes_atomically_linked_running_request_and_attempt(
    disposable_mysql,
):
    await _bootstrap(disposable_mysql.session)

    async def inspect_running_pair():
        request = await disposable_mysql.session.fetchone(
            "SELECT status,attempt_id FROM style_trial_requests WHERE project_id=%s",
            (PROJECT_ID,),
        )
        attempt = await disposable_mysql.session.fetchone(
            "SELECT status FROM style_trial_attempts WHERE project_id=%s AND id=%s",
            (PROJECT_ID, request["attempt_id"]),
        )
        assert request == {"status": "running", "attempt_id": "style-attempt"}
        assert attempt == {"status": "running"}

    gateway = Gateway(before_return=inspect_running_pair)

    result = await _service(disposable_mysql, gateway).generate(_command())

    assert result.status == "succeeded"
    assert gateway.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "secret",
    ("integration-secret-key", "https://style.test.invalid/v1"),
)
async def test_secret_in_author_scenario_fails_before_any_ledger_write(
    disposable_mysql, secret,
):
    await _bootstrap(disposable_mysql.session)
    gateway = Gateway()

    with pytest.raises(StyleTrialFailure) as captured:
        await _service(disposable_mysql, gateway).generate(
            _command(author_scenario=f"场景错误嵌入 {secret}，必须拒绝。")
        )

    assert captured.value.code == "STYLE_TRIAL_NOT_READY"
    assert gateway.calls == 0
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM style_trial_attempts WHERE project_id=%s",
        (PROJECT_ID,),
    ) == {"count": 0}
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM style_trial_requests WHERE project_id=%s",
        (PROJECT_ID,),
    ) == {"count": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("secret_field", "secret"),
    (("api_key", "key7"), ("base_url", "url7")),
)
async def test_short_secret_in_scenario_fails_before_any_ledger_write(
    disposable_mysql, secret_field, secret,
):
    await _bootstrap(disposable_mysql.session)
    await disposable_mysql.session.execute(
        f"UPDATE provider_profiles SET {secret_field}=%s WHERE id='provider-style'",
        (secret,),
    )
    gateway = Gateway()

    with pytest.raises(StyleTrialFailure) as captured:
        await _service(disposable_mysql, gateway).generate(
            _command(author_scenario=f"场景里误写了 {secret} 这个短秘密。")
        )

    assert captured.value.code == "STYLE_TRIAL_NOT_READY"
    assert gateway.calls == 0
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM style_trial_attempts WHERE project_id=%s",
        (PROJECT_ID,),
    ) == {"count": 0}
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM style_trial_requests WHERE project_id=%s",
        (PROJECT_ID,),
    ) == {"count": 0}


@pytest.mark.asyncio
async def test_short_secret_in_seed_prompt_fails_before_any_ledger_write(
    disposable_mysql,
):
    await _bootstrap(disposable_mysql.session)
    await disposable_mysql.session.execute(
        "UPDATE provider_profiles SET api_key='key7' WHERE id='provider-style'"
    )
    seed = _seed_payload()
    seed["logline"] = "修复师发现 key7 被误写进种子。"
    await disposable_mysql.session.execute(
        "UPDATE creative_seed_revisions SET payload_json=%s WHERE id='seed-style-rev'",
        (canonical_json(seed),),
    )
    gateway = Gateway()

    with pytest.raises(StyleTrialFailure) as captured:
        await _service(disposable_mysql, gateway).generate(_command())

    assert captured.value.code == "STYLE_TRIAL_NOT_READY"
    assert gateway.calls == 0
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM style_trial_attempts WHERE project_id=%s",
        (PROJECT_ID,),
    ) == {"count": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("secret_field", "secret"),
    (("api_key", "key7"), ("base_url", "url7")),
)
async def test_short_secret_absent_from_prompt_and_manifest_still_executes(
    disposable_mysql, secret_field, secret,
):
    await _bootstrap(disposable_mysql.session)
    await disposable_mysql.session.execute(
        f"UPDATE provider_profiles SET {secret_field}=%s WHERE id='provider-style'",
        (secret,),
    )
    gateway = Gateway()

    result = await _service(disposable_mysql, gateway).generate(_command())

    assert result.status == "succeeded"
    assert gateway.calls == 1
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM style_trial_attempts WHERE project_id=%s",
        (PROJECT_ID,),
    ) == {"count": 1}
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM style_trial_requests WHERE project_id=%s",
        (PROJECT_ID,),
    ) == {"count": 1}


async def _insert_running_trial(disposable_mysql, service, *, created_at):
    command = _command()
    manifest = {
        "provider": {
            "providerId": "provider-style",
            "providerType": "openai-compatible",
            "modelName": "deepseek-v4-flash",
            "profileRevision": 7,
        },
        "scenarioHash": sha256(command.author_scenario.encode("utf-8")).hexdigest(),
        "scenarioLength": len(command.author_scenario),
        "policyVersion": "style-trial-policy-v1",
    }
    await disposable_mysql.session.execute(
        """INSERT INTO style_trial_attempts
           (id,project_id,selection_revision,binding_revision_id,binding_hash,
            input_manifest_json,input_manifest_hash,status,result_json,result_hash,
            public_error_code,created_at,completed_at)
           VALUES ('style-attempt',%s,1,'binding-style',%s,%s,%s,'running',
                   NULL,NULL,NULL,%s,NULL)""",
        (
            PROJECT_ID, BINDING_HASH, canonical_json(manifest),
            "8" * 64, created_at,
        ),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO style_trial_requests
           (id,project_id,idempotency_key,request_hash,status,attempt_id,
            result_hash,public_error_code,created_at,completed_at)
           VALUES ('style-request',%s,%s,%s,'running','style-attempt',
                   NULL,NULL,%s,NULL)""",
        (
            PROJECT_ID, command.idempotency_key,
            service.request_hash(command), created_at,
        ),
    )
    return command


@pytest.mark.asyncio
async def test_stale_linked_pair_becomes_unknown_and_replays_without_provider(
    disposable_mysql,
):
    await _bootstrap(disposable_mysql.session)
    gateway = Gateway()
    service = _service(disposable_mysql, gateway)
    command = await _insert_running_trial(
        disposable_mysql,
        service,
        created_at=1_700_000_000_100 - 240_000,
    )

    result = await service.generate(command)
    replay = await service.generate(command)

    assert result == replay
    assert result.status == "outcome_unknown"
    assert result.public_error_code == "STYLE_TRIAL_OUTCOME_UNKNOWN"
    assert gateway.calls == 0
    request = await disposable_mysql.session.fetchone(
        "SELECT status,attempt_id,public_error_code FROM style_trial_requests WHERE project_id=%s",
        (PROJECT_ID,),
    )
    attempt = await disposable_mysql.session.fetchone(
        "SELECT status,public_error_code FROM style_trial_attempts WHERE project_id=%s",
        (PROJECT_ID,),
    )
    assert request == {
        "status": "outcome_unknown",
        "attempt_id": "style-attempt",
        "public_error_code": "STYLE_TRIAL_OUTCOME_UNKNOWN",
    }
    assert attempt == {
        "status": "outcome_unknown",
        "public_error_code": "STYLE_TRIAL_OUTCOME_UNKNOWN",
    }


@pytest.mark.asyncio
async def test_external_provider_cancellation_terminalizes_linked_pair_unknown(
    disposable_mysql,
):
    await _bootstrap(disposable_mysql.session)
    started = asyncio.Event()
    release = asyncio.Event()

    async def block_provider():
        started.set()
        await release.wait()

    gateway = Gateway(before_return=block_provider)
    service = _service(disposable_mysql, gateway)
    task = asyncio.create_task(service.generate(_command()))
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    request = await disposable_mysql.session.fetchone(
        "SELECT status,attempt_id FROM style_trial_requests WHERE project_id=%s",
        (PROJECT_ID,),
    )
    attempt = await disposable_mysql.session.fetchone(
        "SELECT status FROM style_trial_attempts WHERE project_id=%s",
        (PROJECT_ID,),
    )
    assert request == {"status": "outcome_unknown", "attempt_id": "style-attempt"}
    assert attempt == {"status": "outcome_unknown"}
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_provider_failure_is_one_failed_attempt_without_result_or_raw_response(
    disposable_mysql,
):
    await _bootstrap(disposable_mysql.session)
    gateway = Gateway(fail=True)

    service = _service(disposable_mysql, gateway)
    result = await service.generate(_command())
    replay = await service.generate(_command())

    assert replay == result
    assert gateway.calls == 1
    assert (result.status, result.public_error_code) == (
        "failed",
        "STYLE_TRIAL_PROVIDER_FAILED",
    )
    attempt = await disposable_mysql.session.fetchone(
        "SELECT * FROM style_trial_attempts WHERE project_id=%s", (PROJECT_ID,)
    )
    request = await disposable_mysql.session.fetchone(
        "SELECT * FROM style_trial_requests WHERE project_id=%s", (PROJECT_ID,)
    )
    assert attempt["status"] == request["status"] == "failed"
    assert request["attempt_id"] == attempt["id"]
    assert attempt["result_json"] is None
    assert attempt["result_hash"] is None
    assert request["result_hash"] is None


@pytest.mark.asyncio
async def test_short_secret_in_provider_envelope_is_one_safe_failed_attempt(
    disposable_mysql, caplog,
):
    await _bootstrap(disposable_mysql.session)
    await disposable_mysql.session.execute(
        "UPDATE provider_profiles SET api_key='abc' WHERE id='provider-style'"
    )
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "providerLeak": "xabcx",
                "choices": [
                    {"message": {"content": '{"sample":"安全正文"}'}}
                ],
            },
        )

    gateway = StyleTrialProviderGateway(transport=httpx.MockTransport(handler))
    result = await _service(disposable_mysql, gateway).generate(_command())

    assert calls == 1
    assert (result.status, result.sample, result.public_error_code) == (
        "failed",
        None,
        "STYLE_TRIAL_PROVIDER_FAILED",
    )
    request = await disposable_mysql.session.fetchone(
        "SELECT * FROM style_trial_requests WHERE project_id=%s", (PROJECT_ID,)
    )
    attempt = await disposable_mysql.session.fetchone(
        "SELECT * FROM style_trial_attempts WHERE project_id=%s", (PROJECT_ID,)
    )
    assert request["status"] == attempt["status"] == "failed"
    assert request["result_hash"] is None
    assert attempt["result_json"] is None
    assert attempt["result_hash"] is None
    public_and_stored = json.dumps(
        {
            "result": result.model_dump(mode="json"),
            "request": request,
            "attempt": attempt,
        },
        default=str,
        ensure_ascii=False,
    )
    assert "abc" not in public_and_stored
    assert "providerLeak" not in public_and_stored
    assert "xabcx" not in public_and_stored
    assert "abc" not in caplog.text
    assert "providerLeak" not in caplog.text


@pytest.mark.asyncio
async def test_oversized_valid_style_prompt_is_not_ready_without_ledger_or_provider(
    disposable_mysql,
):
    await _bootstrap(disposable_mysql.session)
    await disposable_mysql.session.execute(
        "UPDATE style_templates SET payload_json=%s WHERE id='style-primary'",
        (canonical_json(_oversized_style_payload("主锚点")),),
    )
    gateway = Gateway()

    with pytest.raises(StyleTrialFailure) as captured:
        await _service(disposable_mysql, gateway).generate(_command())

    assert captured.value.code == "STYLE_TRIAL_NOT_READY"
    assert gateway.calls == 0
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM style_trial_requests WHERE project_id=%s",
        (PROJECT_ID,),
    ) == {"count": 0}
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM style_trial_attempts WHERE project_id=%s",
        (PROJECT_ID,),
    ) == {"count": 0}


@pytest.mark.asyncio
async def test_cleanup_with_wrong_reservation_identity_leaves_running_pair_unchanged(
    disposable_mysql,
):
    await _bootstrap(disposable_mysql.session)
    gateway = Gateway()
    service = _service(disposable_mysql, gateway)
    command = await _insert_running_trial(
        disposable_mysql,
        service,
        created_at=1_700_000_000_100 - 1_000,
    )
    factory = transaction_factory_for(disposable_mysql.connection_config)

    async with factory() as session:
        changed = await service.repository.cleanup_interrupted(
            session,
            project_id=PROJECT_ID,
            idempotency_key=command.idempotency_key,
            request_hash=service.request_hash(command),
            request_id="wrong-request",
            attempt_id="wrong-attempt",
            public_error_code="STYLE_TRIAL_OUTCOME_UNKNOWN",
            completed_at=1_700_000_000_100,
        )

    assert changed is False
    assert await disposable_mysql.session.fetchone(
        "SELECT status FROM style_trial_requests WHERE project_id=%s",
        (PROJECT_ID,),
    ) == {"status": "running"}
    assert await disposable_mysql.session.fetchone(
        "SELECT status FROM style_trial_attempts WHERE project_id=%s",
        (PROJECT_ID,),
    ) == {"status": "running"}


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ("selection", "engine", "style", "binding"))
async def test_existing_input_drift_fails_closed_without_provider(
    disposable_mysql, drift,
):
    await _bootstrap(disposable_mysql.session)
    if drift == "selection":
        await disposable_mysql.session.execute(
            """INSERT INTO project_seed_selection_revisions
               (project_id,selection_revision,seed_id,seed_revision_id,seed_hash,selected_at)
               VALUES (%s,2,'seed-style','seed-style-rev',%s,2)""",
            (PROJECT_ID, SEED_HASH),
        )
        await disposable_mysql.session.execute(
            "UPDATE project_selected_seeds SET selection_revision=2 WHERE project_id=%s",
            (PROJECT_ID,),
        )
    elif drift == "engine":
        await disposable_mysql.session.execute(
            "UPDATE story_engine_options SET content_hash=%s WHERE id='engine-option'",
            ("9" * 64,),
        )
    elif drift == "style":
        await disposable_mysql.session.execute(
            """INSERT INTO style_templates
               (id,stable_key,revision,name,payload_json,provenance_json,
                content_hash,status,created_at)
               VALUES ('style-primary-v2','primary-style',2,'v2',%s,%s,%s,'active',2)""",
            (
                canonical_json(_style_payload("新锚点")),
                canonical_json({"decision": "approved"}),
                "9" * 64,
            ),
        )
        await disposable_mysql.session.execute(
            """UPDATE style_template_heads
                  SET style_template_id='style-primary-v2',revision=2,content_hash=%s
                WHERE stable_key='primary-style'""",
            ("9" * 64,),
        )
    else:
        await disposable_mysql.session.execute(
            "DELETE FROM project_model_binding_heads WHERE project_id=%s",
            (PROJECT_ID,),
        )
    gateway = Gateway()

    with pytest.raises(StyleTrialFailure):
        await _service(disposable_mysql, gateway).generate(_command())

    assert gateway.calls == 0
    assert await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM style_trial_attempts WHERE project_id=%s",
        (PROJECT_ID,),
    ) == {"count": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ("selection", "engine", "style", "binding"))
async def test_publication_rechecks_every_frozen_identity_after_provider(
    disposable_mysql, drift,
):
    await _bootstrap(disposable_mysql.session)

    async def mutate():
        if drift == "selection":
            await disposable_mysql.session.execute(
                """INSERT INTO project_seed_selection_revisions
                   (project_id,selection_revision,seed_id,seed_revision_id,
                    seed_hash,selected_at)
                   VALUES (%s,2,'seed-style','seed-style-rev',%s,2)""",
                (PROJECT_ID, SEED_HASH),
            )
            await disposable_mysql.session.execute(
                """UPDATE project_selected_seeds SET selection_revision=2
                    WHERE project_id=%s""",
                (PROJECT_ID,),
            )
        elif drift == "engine":
            await disposable_mysql.session.execute(
                "UPDATE story_engine_options SET content_hash=%s WHERE id='engine-option'",
                ("9" * 64,),
            )
        elif drift == "style":
            await disposable_mysql.session.execute(
                """INSERT INTO style_templates
                   (id,stable_key,revision,name,payload_json,provenance_json,
                    content_hash,status,created_at)
                   VALUES ('style-primary-v2','primary-style',2,'v2',%s,%s,%s,
                           'active',2)""",
                (
                    canonical_json(_style_payload("新锚点")),
                    canonical_json({"decision": "approved"}),
                    "9" * 64,
                ),
            )
            await disposable_mysql.session.execute(
                """UPDATE style_template_heads
                      SET style_template_id='style-primary-v2',revision=2,
                          content_hash=%s
                    WHERE stable_key='primary-style'""",
                ("9" * 64,),
            )
        else:
            await disposable_mysql.session.execute(
                """INSERT INTO project_model_binding_revisions
                   (id,project_id,revision,content_hash,source_project_id,created_at)
                   VALUES ('binding-style-v2',%s,2,%s,NULL,2)""",
                (PROJECT_ID, "9" * 64),
            )
            await disposable_mysql.session.execute(
                """INSERT INTO project_model_binding_items
                   (binding_revision_id,task_key,resolution_status,provider_id,
                    provider_name_snapshot,model_name_snapshot,item_hash)
                   VALUES ('binding-style-v2','seed','bound','provider-style',
                           'Style Provider','deepseek-v4-flash',%s)""",
                ("8" * 64,),
            )
            await disposable_mysql.session.execute(
                """UPDATE project_model_binding_heads
                      SET revision=2,binding_revision_id='binding-style-v2',
                          content_hash=%s WHERE project_id=%s""",
                ("9" * 64, PROJECT_ID),
            )

    gateway = Gateway(before_return=mutate)
    result = await _service(disposable_mysql, gateway).generate(_command())

    assert gateway.calls == 1
    assert (result.status, result.sample, result.public_error_code) == (
        "failed",
        None,
        "STYLE_TRIAL_INPUT_CHANGED",
    )
    attempt = await disposable_mysql.session.fetchone(
        "SELECT status,result_json,result_hash FROM style_trial_attempts WHERE project_id=%s",
        (PROJECT_ID,),
    )
    assert attempt == {"status": "failed", "result_json": None, "result_hash": None}
