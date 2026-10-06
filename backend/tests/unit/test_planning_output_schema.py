from __future__ import annotations

import json
from copy import deepcopy

import httpx
import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.domain.planning import DraftPlanningAggregate
from backend.gateways.planning_provider import PlanningProviderGateway
from backend.prompts.planning import build_planning_messages
from backend.tests.unit.test_planning_domain import _normalize, _valid_payload
from backend.tests.unit.test_planning_gateway import _manifest, _provider


NODE_PATHS = (
    ("volumes", 0),
    ("plots", 0),
    ("storyBlocks", 0),
    ("storyBlocks", 0, "stages", 0),
    ("storyBlocks", 0, "stages", 0, "sceneTasks", 0),
)
IDENTITY_FIELDS = ("clientNodeKey", "id", "revision", "contentHash")


def _node(value, path):
    for key in path:
        value = value[key]
    return value


def _persisted(node):
    node["id"] = node.pop("clientNodeKey")
    node["revision"] = 1
    node["contentHash"] = "a" * 64
    return node


def _nodes(payload):
    for section in ("volumes", "plots", "storyBlocks"):
        for node in payload[section]:
            yield node
            for stage in node.get("stages", []):
                yield stage
                yield from stage["sceneTasks"]


def _request_manifest(mode=None, before=None):
    manifest = _manifest()
    manifest["draft"] = deepcopy(before) if before is not None else {
        "activeStoryBlockRef": None,
        "volumes": [],
        "plots": [],
        "storyBlocks": [],
    }
    if mode:
        manifest["expansion"] = {
            "mode": mode,
            "authorityHash": "a" * 64,
            "targetVolumeRef": None,
            "targetBlockRef": None,
            "continuity": {},
        }
        if mode in ("revise_block", "fill_next_block", "fill_next_volume"):
            manifest["expansion"].update(
                targetVolumeRef="volume-1", targetBlockRef="block-1"
            )
    return manifest


def _contract(mode=None, before=None):
    messages = build_planning_messages(
        manifest=_request_manifest(mode, before), author_instructions=""
    )
    return json.loads(messages[1]["content"])["outputContract"]


def _validator(mode=None, before=None):
    schema = _contract(mode, before)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.mark.parametrize("path", NODE_PATHS)
@pytest.mark.parametrize("bad_key", (None, "", 7))
def test_initial_request_rejects_invalid_new_identity_at_every_depth(path, bad_key):
    payload = _valid_payload()
    _node(payload, path)["clientNodeKey"] = bad_key
    assert not _validator("initial").is_valid(payload)


@pytest.mark.parametrize("path", NODE_PATHS)
def test_initial_request_requires_every_new_identity_and_rejects_persisted_nodes(path):
    payload = _valid_payload()
    _node(payload, path).pop("clientNodeKey")
    assert not _validator("initial").is_valid(payload)
    payload = _valid_payload()
    _persisted(_node(payload, path))
    assert not _validator("initial").is_valid(payload)


@pytest.mark.parametrize("path", NODE_PATHS)
def test_mixed_request_accepts_complete_existing_identity_without_new_key(path):
    payload = _valid_payload()
    node = _persisted(_node(payload, path))
    validator = _validator()
    assert validator.is_valid(payload)
    node["clientNodeKey"] = None
    assert validator.is_valid(payload)
    node["clientNodeKey"] = "mixed-new-key"
    assert not validator.is_valid(payload)


@pytest.mark.parametrize("path", NODE_PATHS)
@pytest.mark.parametrize("omitted", ("id", "revision", "contentHash"))
def test_mixed_request_rejects_partial_persisted_identity(path, omitted):
    payload = _valid_payload()
    _persisted(_node(payload, path)).pop(omitted)
    assert not _validator().is_valid(payload)


@pytest.mark.parametrize("path", NODE_PATHS)
@pytest.mark.parametrize("field,value", (
    ("id", None), ("revision", None), ("revision", 0),
    ("contentHash", None), ("contentHash", "bad-hash"),
))
def test_mixed_request_preserves_persisted_identity_value_constraints(path, field, value):
    payload = _valid_payload()
    _persisted(_node(payload, path))[field] = value
    assert not _validator().is_valid(payload)


@pytest.mark.parametrize("path", NODE_PATHS)
def test_existing_identity_keeps_original_empty_string_id_shape(path):
    payload = _valid_payload()
    _persisted(_node(payload, path))["id"] = ""
    original = Draft202012Validator(DraftPlanningAggregate.model_json_schema(by_alias=True))
    assert original.is_valid(payload)
    assert _validator().is_valid(payload)
    DraftPlanningAggregate.model_validate(payload, strict=True)
    # This checks the original identity shape, not server-issued ID authority.


def _payload_with_new_key(path, key):
    payload = _valid_payload()
    node = _node(payload, path)
    previous_key = node["clientNodeKey"]
    node["clientNodeKey"] = key
    if path[0] == "volumes":
        if key == "":
            # Isolate identity from volumeRef's independent min_length=1.
            payload.update(storyBlocks=[], activeStoryBlockRef=None)
        else:
            payload["storyBlocks"][0]["volumeRef"] = key
    elif path[0] == "plots":
        block = payload["storyBlocks"][0]
        block["plotRefs"] = [key if ref == previous_key else ref for ref in block["plotRefs"]]
    elif len(path) == 2:
        payload["activeStoryBlockRef"] = key
    return payload


@pytest.mark.parametrize("path", NODE_PATHS)
def test_empty_generated_key_is_an_explicit_narrowing_of_domain_identity(path):
    payload = _payload_with_new_key(path, "")
    assert not _validator("initial").is_valid(payload)
    DraftPlanningAggregate.model_validate(payload, strict=True)
    _normalize(payload)


@pytest.mark.parametrize("path", NODE_PATHS)
@pytest.mark.parametrize("key", (" ", "\t", "\u3000"))
def test_whitespace_new_keys_remain_allowed_by_generation_and_domain(path, key):
    payload = _payload_with_new_key(path, key)
    assert _validator("initial").is_valid(payload)
    DraftPlanningAggregate.model_validate(payload, strict=True)
    _normalize(payload)


def test_new_identity_accepts_absent_or_null_server_fields():
    payload = _valid_payload()
    for node in _nodes(payload):
        node.update(id=None, revision=None, contentHash=None)
    assert _validator("initial").is_valid(payload)
    DraftPlanningAggregate.model_validate(payload, strict=True)


@pytest.mark.parametrize("path", NODE_PATHS)
@pytest.mark.parametrize("identity", ({}, {"clientNodeKey": None}, {"clientNodeKey": ""}))
def test_mixed_request_rejects_missing_null_or_empty_new_identity(path, identity):
    payload = _valid_payload()
    node = _node(payload, path)
    for field in IDENTITY_FIELDS:
        node.pop(field, None)
    node.update(identity)
    assert not _validator().is_valid(payload)


def test_initial_retains_existing_volume_and_plot_identities_but_requires_new_block():
    before = _valid_payload()
    before["storyBlocks"] = []
    before["activeStoryBlockRef"] = None
    for node in _nodes(before):
        _persisted(node)
    payload = _valid_payload()
    payload["volumes"] = deepcopy(before["volumes"])
    payload["plots"] = deepcopy(before["plots"])
    validator = _validator("initial", before)
    assert validator.is_valid(payload)
    _persisted(payload["storyBlocks"][0])
    assert not validator.is_valid(payload)


@pytest.mark.parametrize("mode", ("next_block", "next_volume"))
def test_continuation_delta_requires_new_nested_identities(mode):
    payload = _valid_payload()
    delta = {"nextVolume": payload["volumes"][0], "nextStoryBlock": payload["storyBlocks"][0]}
    validator = _validator(mode)
    assert validator.is_valid(delta)
    task = delta["nextStoryBlock"]["stages"][0]["sceneTasks"][0]
    task.pop("clientNodeKey")
    assert not validator.is_valid(delta)


def test_block_revision_accepts_existing_nodes_and_new_tasks_together():
    before = _valid_payload()
    for node in _nodes(before):
        _persisted(node)
    block = deepcopy(before["storyBlocks"][0])
    task = deepcopy(_valid_payload()["storyBlocks"][0]["stages"][0]["sceneTasks"][0])
    task.update(clientNodeKey="added-task", order=3)
    block["stages"][0]["sceneTasks"].append(task)
    validator = _validator("revise_block", before)
    assert validator.is_valid({"storyBlock": block})
    task["clientNodeKey"] = None
    assert not validator.is_valid({"storyBlock": block})


@pytest.mark.parametrize("mode", ("fill_next_block", "fill_next_volume"))
def test_completion_patch_omits_existing_identity_and_requires_new_children(mode):
    before = _valid_payload()
    for node in _nodes(before):
        _persisted(node)
    before["volumes"][0]["mainPressure"] = ""
    before["storyBlocks"][0]["stages"] = []
    delta = {
        "nextVolume": {"mainPressure": "新的压力"} if mode == "fill_next_volume" else None,
        "nextStoryBlock": {"stages": deepcopy(_valid_payload()["storyBlocks"][0]["stages"])},
    }
    validator = _validator(mode, before)
    assert validator.is_valid(delta)
    delta["nextStoryBlock"]["id"] = "block-1"
    assert not validator.is_valid(delta)
    delta["nextStoryBlock"].pop("id")
    delta["nextStoryBlock"]["stages"][0]["sceneTasks"][0].pop("clientNodeKey")
    assert not validator.is_valid(delta)


def test_completion_of_existing_nested_task_stays_identity_free():
    before = _valid_payload()
    for node in _nodes(before):
        _persisted(node)
    before["storyBlocks"][0]["stages"][0]["sceneTasks"][0]["completionEvidence"] = " "
    delta = {
        "nextVolume": None,
        "nextStoryBlock": {"stages": [{"sceneTasks": [
            {"completionEvidence": "现场取得可复核证据。"}, {}
        ]}]},
    }
    validator = _validator("fill_next_block", before)
    assert validator.is_valid(delta)
    delta["nextStoryBlock"]["stages"][0]["sceneTasks"][0]["clientNodeKey"] = "invented-key"
    assert not validator.is_valid(delta)


def _failed_shape(stages, plots, all_missing):
    payload = _valid_payload()
    volume, plot = payload["volumes"][0], payload["plots"][0]
    payload["volumes"] = [dict(deepcopy(volume), clientNodeKey=f"vol-{i}", order=i) for i in range(1, 16)]
    payload["plots"] = [dict(deepcopy(plot), clientNodeKey=f"plot-{i}", order=i) for i in range(1, plots + 1)]
    block = payload["storyBlocks"][0]
    block.update(volumeRef="vol-1", plotRefs=["plot-1"])
    stage = block["stages"][0]
    task = stage["sceneTasks"][0]
    block["stages"] = []
    for i in range(stages):
        child = dict(deepcopy(stage), clientNodeKey=f"stage-{i}", order=i + 1)
        child["sceneTasks"] = [dict(deepcopy(task), order=j + 1) for j in range(3)]
        for scene in child["sceneTasks"]:
            scene.pop("clientNodeKey")
        block["stages"].append(child)
    if all_missing:
        for node in _nodes(payload):
            node.pop("clientNodeKey", None)
    return payload


@pytest.mark.parametrize("stages,plots,all_missing,expected_errors", ((3, 10, True, 9), (4, 15, False, 12)))
def test_original_failure_shapes_expose_old_contract_gap_but_new_contract_rejects(
    stages, plots, all_missing, expected_errors
):
    payload = _failed_shape(stages, plots, all_missing)
    assert Draft202012Validator(DraftPlanningAggregate.model_json_schema(by_alias=True)).is_valid(payload)
    assert not _validator("initial").is_valid(payload)
    with pytest.raises(ValidationError) as failure:
        DraftPlanningAggregate.model_validate(payload, strict=True)
    # Parent after validators do not run after their nested tasks fail.
    assert len(failure.value.errors()) == expected_errors + (25 if all_missing else 0)


@pytest.mark.asyncio
async def test_actual_provider_request_carries_enforced_nested_identity_contract():
    payload = _valid_payload()
    observed = []

    def respond(request):
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        schema = json.loads(body["messages"][1]["content"])["outputContract"]
        validator = Draft202012Validator(schema)
        assert validator.is_valid(payload)
        missing = deepcopy(payload)
        missing["storyBlocks"][0]["stages"][0]["sceneTasks"][0].pop("clientNodeKey")
        assert not validator.is_valid(missing)
        observed.append(body)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    gateway = PlanningProviderGateway(transport=httpx.MockTransport(respond))
    await gateway.start()
    try:
        await gateway.generate(provider=_provider(), model_name="planning-model",
                               manifest=_request_manifest("initial"), author_instructions="")
    finally:
        await gateway.aclose()
    assert len(observed) == 1
