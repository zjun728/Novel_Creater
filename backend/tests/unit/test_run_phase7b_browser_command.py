from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from backend.domain.json_contracts import canonical_json
from backend.scripts import prepare_product_database as preparation
from backend.scripts import run_phase7b_browser as command


def _internal_evidence(**changes: object) -> str:
    value: dict[str, object] = {
        "firstStage": None,
        "firstCause": None,
        "scenarioCount": 1,
        "providerCalls": 0,
        "outboundRequests": 0,
        "processCount": 0,
        "portCount": 0,
        "artifactCount": 0,
    }
    value.update(changes)
    return "PHASE7B_BROWSER_INTERNAL_EVIDENCE=" + canonical_json(value)


def _successful_runner(stdout: str):
    def runner(**_kwargs: object) -> object:
        return subprocess.CompletedProcess((), 0, stdout, "")

    return runner


def test_owned_browser_returns_only_post_cleanup_public_summary(tmp_path: Path) -> None:
    calls: list[object] = []

    def runner(**kwargs: object) -> object:
        calls.append(kwargs)
        return subprocess.CompletedProcess((), 0, _internal_evidence(), "")

    root_factory = lambda *_args: SimpleNamespace()  # noqa: E731
    result = preparation.run_owned_phase7b_browser(
        node_command=("node", "frontend/e2e/run-phase7b.mjs"),
        cwd=preparation.REPOSITORY_ROOT,
        environment={"MYSQL_DB": "novel_creator_product"},
        timeout_seconds=300,
        runner=runner,
        root_factory=root_factory,
    )

    assert result == {
        "firstStage": None,
        "firstCause": None,
        "scenarioCount": 1,
        "providerCalls": 0,
        "outboundRequests": 0,
        "processCount": 0,
        "portCount": 0,
        "rootCount": 0,
        "artifactCount": 0,
    }
    assert calls == [
        {
            "command": ("node", "frontend/e2e/run-phase7b.mjs"),
            "cwd": preparation.REPOSITORY_ROOT,
            "environment": {"MYSQL_DB": "novel_creator_product"},
            "timeout_seconds": 300,
            "root_lease_factory": root_factory,
        }
    ]


@pytest.mark.parametrize(
    "stdout",
    (
        "",
        "not-json",
        _internal_evidence() + "\n" + _internal_evidence(),
        _internal_evidence(extra=0),
        _internal_evidence(processCount=True),
        _internal_evidence(portCount=1),
        _internal_evidence(artifactCount=1),
        _internal_evidence(firstStage="secret-stage"),
        (
            "PHASE7B_BROWSER_INTERNAL_EVIDENCE="
            '{"artifactCount":0,"artifactCount":0,"firstCause":null,'
            '"firstStage":null,"outboundRequests":0,"portCount":0,'
            '"processCount":0,"providerCalls":0,"scenarioCount":1}'
        ),
        "PHASE7B_BROWSER_INTERNAL_EVIDENCE="
        + json.dumps(
            json.loads(_internal_evidence().split("=", 1)[1]), sort_keys=True
        ),
    ),
)
def test_owned_browser_rejects_missing_duplicate_or_noncanonical_private_evidence(
    tmp_path: Path, stdout: str
) -> None:
    with pytest.raises(preparation.ProductDatabasePreparationCommandError) as raised:
        preparation.run_owned_phase7b_browser(
            node_command=("node", "frontend/e2e/run-phase7b.mjs"),
            cwd=preparation.REPOSITORY_ROOT,
            environment={},
            timeout_seconds=300,
            runner=_successful_runner(stdout),
            root_factory=lambda *_args: SimpleNamespace(),
        )

    assert str(raised.value) == "readiness smoke failed"
    assert "secret" not in repr(raised.value)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    tuple(
        (field, bad_value)
        for field, expected in (
            ("scenarioCount", 1),
            ("providerCalls", 0),
            ("outboundRequests", 0),
            ("processCount", 0),
            ("portCount", 0),
            ("artifactCount", 0),
        )
        for bad_value in (bool(expected), float(expected))
    ),
)
def test_owned_browser_rejects_non_exact_private_counter_types(
    field: str, bad_value: object
) -> None:
    with pytest.raises(preparation.ProductDatabasePreparationCommandError) as raised:
        preparation.run_owned_phase7b_browser(
            node_command=("node", "frontend/e2e/run-phase7b.mjs"),
            cwd=preparation.REPOSITORY_ROOT,
            environment={},
            timeout_seconds=300,
            runner=_successful_runner(_internal_evidence(**{field: bad_value})),
            root_factory=lambda *_args: SimpleNamespace(),
        )

    assert str(raised.value) == "readiness smoke failed"
    assert "secret" not in repr(raised.value)


@pytest.mark.parametrize(
    ("failure", "expected_type"),
    (
        (RuntimeError("secret cleanup"), preparation.ProductDatabasePreparationCommandError),
        (asyncio.CancelledError("secret cancel"), asyncio.CancelledError),
        (KeyboardInterrupt("secret keyboard"), KeyboardInterrupt),
        (SystemExit("secret exit"), SystemExit),
    ),
)
def test_owned_browser_sanitizes_runner_and_cleanup_failures(
    failure: BaseException, expected_type: type[BaseException]
) -> None:
    def runner(**_kwargs: object) -> object:
        raise failure

    with pytest.raises(expected_type) as raised:
        preparation.run_owned_phase7b_browser(
            node_command=("node", "frontend/e2e/run-phase7b.mjs"),
            cwd=preparation.REPOSITORY_ROOT,
            environment={},
            timeout_seconds=300,
            runner=runner,
            root_factory=lambda *_args: SimpleNamespace(),
        )

    if expected_type is preparation.ProductDatabasePreparationCommandError:
        assert str(raised.value) == "readiness smoke failed"
    if expected_type is SystemExit:
        assert raised.value.code is None
    assert "secret" not in repr(raised.value)


def test_owned_browser_rejects_child_nonzero_without_exposing_output() -> None:
    def runner(**_kwargs: object) -> object:
        return subprocess.CompletedProcess((), 7, _internal_evidence(), "password=secret")

    with pytest.raises(preparation.ProductDatabasePreparationCommandError) as raised:
        preparation.run_owned_phase7b_browser(
            node_command=("node", "frontend/e2e/run-phase7b.mjs"),
            cwd=preparation.REPOSITORY_ROOT,
            environment={},
            timeout_seconds=300,
            runner=runner,
            root_factory=lambda *_args: SimpleNamespace(),
        )

    assert str(raised.value) == "readiness smoke failed"
    assert "secret" not in repr(raised.value)


def test_wrapper_emits_one_canonical_public_marker_only_after_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(command.sys, "argv", ["run_phase7b_browser.py"])
    monkeypatch.setattr(command, "_run", lambda: dict(preparation._BROWSER_SMOKE_EXPECTED))

    assert command.main() == 0
    captured = capsys.readouterr()
    assert captured.out == (
        "PHASE7B_BROWSER_SMOKE_SUMMARY="
        + canonical_json(preparation._BROWSER_SMOKE_EXPECTED)
        + "\n"
    )
    assert captured.err == ""


def test_wrapper_owner_launches_node_runner_directly_without_routing_recursion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("MYSQL_DB", "unexpected_database")
    monkeypatch.setenv("MARKET_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("PHASE7B_UNRELATED", "preserved")

    def run_owned(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return dict(preparation._BROWSER_SMOKE_EXPECTED)

    monkeypatch.setattr(
        command,
        "read_local_document",
        lambda _path: {"MYSQL_DB": "novel_creator"},
    )
    monkeypatch.setattr(command, "run_owned_phase7b_browser", run_owned)

    assert command._run() == preparation._BROWSER_SMOKE_EXPECTED
    assert captured["node_command"] == (
        "node",
        "frontend/e2e/run-phase7b.mjs",
    )
    assert "scripts/run-tests.mjs" not in captured["node_command"]
    environment = captured["environment"]
    assert type(environment) is dict
    assert environment["MYSQL_DB"] == "novel_creator_v113"
    assert environment["MARKET_SCHEDULER_ENABLED"] == "false"
    assert environment["PHASE7B_UNRELATED"] == "preserved"


def test_wrapper_post_cutover_uses_normal_config_without_mysql_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    for name, value in {
        "MYSQL_HOST": "unexpected-host",
        "MYSQL_PORT": "3306",
        "MYSQL_USER": "unexpected-user",
        "MYSQL_PASSWORD": "unexpected-password",
        "MYSQL_DB": "unexpected-database",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("MARKET_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("PHASE7B_UNRELATED", "preserved")

    monkeypatch.setattr(
        command,
        "read_local_document",
        lambda _path: {"MYSQL_DB": "novel_creator_v113"},
    )

    def run_owned(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return dict(preparation._BROWSER_SMOKE_EXPECTED)

    monkeypatch.setattr(command, "run_owned_phase7b_browser", run_owned)

    assert command._run() == preparation._BROWSER_SMOKE_EXPECTED
    environment = captured["environment"]
    assert type(environment) is dict
    assert not any(name in environment for name in (
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "MYSQL_DB",
    ))
    assert environment["MARKET_SCHEDULER_ENABLED"] == "false"
    assert environment["PHASE7B_UNRELATED"] == "preserved"


def test_wrapper_rejects_every_argument_without_starting_owner(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    started = False

    def start() -> dict[str, object]:
        nonlocal started
        started = True
        return dict(preparation._BROWSER_SMOKE_EXPECTED)

    monkeypatch.setattr(command.sys, "argv", ["run_phase7b_browser.py", "--database=x"])
    monkeypatch.setattr(command, "_run", start)

    assert command.main() == 1
    captured = capsys.readouterr()
    assert started is False
    assert captured.out == ""
    assert captured.err == "phase7b browser smoke failed\n"


@pytest.mark.parametrize(
    ("field", "bad_value"),
    (("scenarioCount", True), ("providerCalls", 0.0), ("rootCount", False)),
)
def test_wrapper_rejects_non_exact_public_counter_types_without_success_marker(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    field: str,
    bad_value: object,
) -> None:
    summary = dict(preparation._BROWSER_SMOKE_EXPECTED)
    summary[field] = bad_value
    monkeypatch.setattr(command.sys, "argv", ["run_phase7b_browser.py"])
    monkeypatch.setattr(command, "_run", lambda: summary)

    assert command.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "phase7b browser smoke failed\n"


@pytest.mark.parametrize(
    "failure",
    (
        RuntimeError("password=secret"),
        asyncio.CancelledError("secret"),
        KeyboardInterrupt("secret"),
        SystemExit("secret"),
    ),
)
def test_wrapper_failure_is_fixed_and_never_emits_success_marker(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: BaseException,
) -> None:
    monkeypatch.setattr(command.sys, "argv", ["run_phase7b_browser.py"])

    def fail() -> dict[str, object]:
        raise failure

    monkeypatch.setattr(command, "_run", fail)

    assert command.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "phase7b browser smoke failed\n"
    assert "secret" not in captured.err
