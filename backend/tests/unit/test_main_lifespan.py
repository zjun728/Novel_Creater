import asyncio
from collections.abc import Mapping
from contextlib import asynccontextmanager, contextmanager
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace, TracebackType

import httpx
import pytest

from backend import config as runtime_config
from backend import main
from backend.gateways.openai_json_transport import (
    OpenAIJSONTransportLifecycleError,
)
from backend.gateways.planning_provider import PlanningProviderGateway
from backend.gateways.chapter_outline_provider import (
    ChapterOutlineProviderGateway,
)
from backend.domain.routers import chapter_outlines, finalization, planning
from backend.runtime import draft_operation_tasks
from backend.runtime.draft_operation_tasks import DraftOperationTaskRegistry
from backend.schema_version import SchemaMismatch
from backend.services import product_database_lifecycle_lock as lifecycle_lock
from backend.tests.support.fakes import FakeAsyncContext


class FakePlanningProviderGateway:
    def __init__(self, events):
        self.events = events

    async def start(self):
        self.events.append("provider-start")

    async def aclose(self):
        self.events.append("provider-close")


class FakeDraftOperationTaskRegistry:
    def __init__(self, events=None):
        self.events = events

    async def start(self):
        if self.events is not None:
            self.events.append("draft-registry-start")

    async def aclose(self):
        if self.events is not None:
            self.events.append("draft-registry-close")


class FakeWindowsLifecycleLockAPI:
    def __init__(
        self,
        *,
        wait_result=0,
        release_result=True,
        close_result=True,
    ):
        self.handle = object()
        self.wait_result = wait_result
        self.release_result = release_result
        self.close_result = close_result

    def create(self, _name):
        return self.handle

    def wait(self, handle):
        assert handle is self.handle
        return self.wait_result

    def release(self, handle):
        assert handle is self.handle
        return self.release_result

    def close(self, handle):
        assert handle is self.handle
        return self.close_result


class ExclusiveRecordingLifecycleLockAPI:
    def __init__(self, events, *, release_failures=0):
        self.events = events
        self.release_failures = release_failures
        self.active = False
        self.handles = set()

    def create(self, _name):
        handle = object()
        self.handles.add(handle)
        return handle

    def wait(self, handle):
        assert handle in self.handles
        self.events.append("lock-attempt")
        if self.active:
            return 0x00000102
        self.active = True
        self.events.append("lock-enter")
        return 0x00000000

    def release(self, handle):
        assert handle in self.handles
        self.events.append("lock-exit")
        self.active = False
        if self.release_failures:
            self.release_failures -= 1
            return False
        return True

    def close(self, handle):
        assert handle in self.handles
        self.handles.remove(handle)
        self.events.append("lock-close")
        return True


class HostileTracebackRuntimeError(RuntimeError):
    def __init__(self, secret):
        super().__init__(secret)
        self.traceback_accesses = 0

    @property
    def __traceback__(self):
        self.traceback_accesses += 1
        raise ValueError(self.args[0])


def runtime_configuration(**changes):
    values = {
        "mysql_items": (
            ("host", "127.0.0.1"), ("port", 3307), ("user", "root"),
            ("password", "test-only"), ("db", "novel_creator"),
            ("charset", "utf8mb4"), ("autocommit", True),
            ("minsize", 1), ("maxsize", 10),
        ),
        "corpus_root": None,
        "managed_corpus_root": None,
        "market_scheduler_enabled": False,
    }
    values.update(changes)
    return runtime_config.RuntimeConfiguration(**values)


@pytest.fixture(autouse=True)
def isolated_runtime_configuration(monkeypatch):
    authority = SimpleNamespace(snapshot=runtime_configuration(), installed=None)

    def load(*, config_path):
        assert config_path is main.LOCAL_CONFIG_PATH
        return authority.snapshot

    def install(snapshot):
        assert snapshot is authority.snapshot
        assert authority.installed is None
        authority.installed = snapshot

    def clear(snapshot):
        assert snapshot is authority.installed
        authority.installed = None

    monkeypatch.setattr(main, "load_runtime_configuration", load)
    monkeypatch.setattr(main, "install_runtime_configuration", install)
    monkeypatch.setattr(main, "clear_runtime_configuration", clear)
    yield authority


class ControlledShutdownTransfer:
    def __init__(self, events, name):
        self.events = events
        self.name = name
        self.release = asyncio.Event()
        self.task = None

    def start_pool_close(self, close_pool_callback):
        if self.task is None:

            async def finish():
                self.events.append(f"{self.name}-transfer-wait")
                await self.release.wait()
                self.events.append(f"{self.name}-transfer-finish")
                await close_pool_callback()

            self.task = asyncio.create_task(
                finish(),
                name=f"{self.name}-test-shutdown-transfer",
            )
            self.task.add_done_callback(
                lambda task: task.exception()
                if not task.cancelled()
                else None
            )
        return self.task


class SuccessfulTransferDuck:
    @staticmethod
    def done():
        return True

    @staticmethod
    def cancelled():
        return False

    @staticmethod
    def result():
        return None


class FutureClassSpoof(SuccessfulTransferDuck):
    @property
    def __class__(self):
        return asyncio.Future


def _assert_no_sensitive_error_graph(
    error: BaseException,
    sentinels: tuple[str, ...],
) -> None:
    pending: list[tuple[object, int]] = [(error, 0)]
    seen: set[int] = set()
    evidence: list[str] = []
    while pending:
        value, depth = pending.pop()
        if value is None or depth > 24 or id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, str):
            evidence.append(value)
            continue
        if isinstance(value, bytes):
            evidence.append(value.decode("utf-8", errors="replace"))
            continue
        if isinstance(value, BaseException):
            evidence.extend((type(value).__name__, str(value)))
            pending.extend(
                (
                    (value.args, depth + 1),
                    (value.__cause__, depth + 1),
                    (value.__context__, depth + 1),
                    (value.__traceback__, depth + 1),
                    (vars(value), depth + 1),
                )
            )
            if isinstance(value, json.JSONDecodeError):
                pending.append((value.doc, depth + 1))
            if isinstance(value, httpx.HTTPError):
                try:
                    pending.append((value.request, depth + 1))
                except RuntimeError:
                    pass
                pending.append((getattr(value, "response", None), depth + 1))
            continue
        if isinstance(value, TracebackType):
            filename = value.tb_frame.f_code.co_filename.replace("\\", "/")
            if "/backend/tests/" not in filename:
                pending.append((value.tb_frame.f_locals, depth + 1))
            pending.append((value.tb_next, depth + 1))
            continue
        if isinstance(value, httpx.Request):
            pending.extend(
                (
                    (dict(value.headers), depth + 1),
                    (value.content, depth + 1),
                    (str(value.url), depth + 1),
                )
            )
            continue
        if isinstance(value, httpx.Response):
            pending.extend(
                (
                    (dict(value.headers), depth + 1),
                    (value.content, depth + 1),
                    (value.request, depth + 1),
                )
            )
            continue
        if isinstance(value, Mapping):
            pending.extend((item, depth + 1) for item in value.items())
            continue
        if isinstance(value, (list, tuple, set, frozenset)):
            pending.extend((item, depth + 1) for item in value)
            continue
        module_name = type(value).__module__
        if module_name.startswith(("backend.", "httpx.")):
            try:
                pending.append((vars(value), depth + 1))
            except TypeError:
                pass

    joined = "\n".join(evidence)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert all(sentinel not in joined for sentinel in sentinels)


async def _next_loop_turn():
    reached = asyncio.Event()
    asyncio.get_running_loop().call_soon(reached.set)
    await asyncio.wait_for(reached.wait(), timeout=1)


async def _record_event(events, event):
    events.append(event)


def install_lifespan_fakes(monkeypatch, verify_error=None):
    events = []
    main.app.state.draft_operation_shutdown_transfer = None
    main.app.state.market_scheduler_shutdown_transfer = None
    session = object()
    context = FakeAsyncContext(session, events)

    async def fake_verify(actual_session):
        assert actual_session is session
        events.append("verify")
        if verify_error is not None:
            raise verify_error

    async def fake_close_pool():
        events.append("close")

    class FakeRuntime:
        def start(self):
            events.append("scheduler-start")

        async def stop(self):
            events.append("scheduler-stop")

    def fake_build_runtime(*, enabled):
        assert type(enabled) is bool
        events.append("scheduler-build")
        return FakeRuntime()

    monkeypatch.setattr(main, "connection", lambda: context)
    monkeypatch.setattr(main, "verify_schema_version", fake_verify)
    monkeypatch.setattr(main, "close_pool", fake_close_pool)

    @contextmanager
    def fake_lifecycle_lock(config_path):
        assert config_path is main.LOCAL_CONFIG_PATH

        class FakeLifecycleLease:
            @staticmethod
            def defer_until(transfer):
                return transfer

        yield FakeLifecycleLease()

    monkeypatch.setattr(
        main,
        "product_database_lifecycle_lock",
        fake_lifecycle_lock,
        raising=False,
    )
    monkeypatch.setattr(
        main.project_packages,
        "cleanup_stale_project_package_roots",
        lambda _temp_parent: 0,
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "build_market_scheduler_runtime",
        fake_build_runtime,
    )
    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        FakePlanningProviderGateway(events),
        raising=False,
    )
    monkeypatch.setattr(
        main.finalization,
        "finalization_quality_gateway",
        FakePlanningProviderGateway([]),
    )
    monkeypatch.setattr(
        main.finalization,
        "finalization_extraction_gateway",
        FakePlanningProviderGateway([]),
    )
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        FakeDraftOperationTaskRegistry(),
    )
    return events


@pytest.mark.asyncio
async def test_lifespan_snapshot_is_loaded_inside_lock_and_cleared_before_release(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    lifecycle = ExclusiveRecordingLifecycleLockAPI(events)
    install_exclusive_lifecycle_lock(monkeypatch, lifecycle)
    snapshot = runtime_configuration(
        mysql_items=tuple(
            (key, "post_cutover" if key == "db" else value)
            for key, value in runtime_configuration().mysql_items
        ),
        market_scheduler_enabled=True,
    )

    monkeypatch.setattr(
        main,
        "load_runtime_configuration",
        lambda *, config_path: events.append("config-load") or snapshot,
    )
    monkeypatch.setattr(
        main,
        "install_runtime_configuration",
        lambda actual: events.append(("config-install", actual)),
    )
    monkeypatch.setattr(
        main,
        "clear_runtime_configuration",
        lambda actual: events.append(("config-clear", actual)),
    )
    monkeypatch.setattr(
        main,
        "build_market_scheduler_runtime",
        lambda *, enabled: events.append(("scheduler-enabled", enabled))
        or SimpleNamespace(
            start=lambda: events.append("scheduler-start"),
            stop=lambda: _record_event(events, "scheduler-stop"),
        ),
    )

    context = main.lifespan(main.app)
    await context.__aenter__()
    await context.__aexit__(None, None, None)

    assert events.index("lock-enter") < events.index("config-load")
    assert events.index("config-load") < events.index(("config-install", snapshot))
    assert events.index(("config-install", snapshot)) < events.index("verify")
    assert events.index("close") < events.index(("config-clear", snapshot))
    assert events.index(("config-clear", snapshot)) < events.index("lock-exit")
    assert events.count(("scheduler-enabled", True)) == 1


@pytest.mark.parametrize("failure_phase", ("load", "install"))
@pytest.mark.asyncio
async def test_runtime_configuration_setup_failure_runs_no_application_actions(
    monkeypatch,
    failure_phase,
):
    events = install_lifespan_fakes(monkeypatch)
    lifecycle = ExclusiveRecordingLifecycleLockAPI(events)
    install_exclusive_lifecycle_lock(monkeypatch, lifecycle)
    snapshot = runtime_configuration()

    def load(*, config_path):
        events.append("config-load")
        if failure_phase == "load":
            raise RuntimeError("PRIVATE_CONFIG_LOAD")
        return snapshot

    def install(actual):
        assert actual is snapshot
        events.append("config-install")
        raise RuntimeError("PRIVATE_CONFIG_INSTALL")

    monkeypatch.setattr(main, "load_runtime_configuration", load)
    monkeypatch.setattr(main, "install_runtime_configuration", install)

    with pytest.raises(lifecycle_lock.ProductDatabaseLifecycleError) as caught:
        await main.lifespan(main.app).__aenter__()

    expected = ["lock-attempt", "lock-enter", "config-load"]
    if failure_phase == "install":
        expected.append("config-install")
    expected.extend(("lock-exit", "lock-close"))
    assert events == expected
    assert lifecycle.active is False
    _assert_no_sensitive_error_graph(
        caught.value,
        ("PRIVATE_CONFIG_LOAD", "PRIVATE_CONFIG_INSTALL"),
    )


@pytest.mark.asyncio
async def test_lifespan_failure_graph_does_not_retain_runtime_snapshot_credentials(
    monkeypatch,
    isolated_runtime_configuration,
):
    secret = "PRIVATE_RUNTIME_SNAPSHOT_PASSWORD"
    isolated_runtime_configuration.snapshot = runtime_configuration(
        mysql_items=tuple(
            (key, secret if key == "password" else value)
            for key, value in runtime_configuration().mysql_items
        ),
    )
    events = install_lifespan_fakes(
        monkeypatch,
        verify_error=RuntimeError("PRIVATE_STARTUP_FAILURE"),
    )
    lifecycle = ExclusiveRecordingLifecycleLockAPI(events)
    install_exclusive_lifecycle_lock(monkeypatch, lifecycle)

    with pytest.raises(lifecycle_lock.ProductDatabaseLifecycleError) as caught:
        await main.lifespan(main.app).__aenter__()

    _assert_no_sensitive_error_graph(caught.value, (secret,))


@pytest.mark.parametrize(
    ("error_factory", "expected_type", "expected_args"),
    (
        (
            lambda: RuntimeError("PRIVATE_CONFIG_CLEAR"),
            lifecycle_lock.ProductDatabaseLifecycleError,
            ("product database lifecycle lock failed",),
        ),
        (lambda: asyncio.CancelledError("PRIVATE_CLEAR_CANCEL"), asyncio.CancelledError, ()),
        (lambda: KeyboardInterrupt("PRIVATE_CLEAR_INTERRUPT"), KeyboardInterrupt, ()),
        (lambda: SystemExit(37), SystemExit, (37,)),
    ),
)
@pytest.mark.asyncio
async def test_runtime_configuration_clear_failure_precedes_physical_release(
    monkeypatch,
    error_factory,
    expected_type,
    expected_args,
):
    events = install_lifespan_fakes(monkeypatch)
    lifecycle = ExclusiveRecordingLifecycleLockAPI(events)
    install_exclusive_lifecycle_lock(monkeypatch, lifecycle)

    def fail_clear(_snapshot):
        events.append("config-clear")
        raise error_factory()

    monkeypatch.setattr(main, "clear_runtime_configuration", fail_clear)
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(expected_type) as caught:
        await context.__aexit__(None, None, None)

    assert caught.value.args == expected_args
    assert events.index("close") < events.index("config-clear")
    assert events.index("config-clear") < events.index("lock-exit")
    assert events.count("config-clear") == 1
    assert events.count("lock-exit") == 1
    assert events.count("lock-close") == 1
    assert lifecycle.active is False


def test_importing_main_performs_no_local_configuration_read():
    script = """
from pathlib import Path
from backend.config import LOCAL_CONFIG_PATH

original_read_text = Path.read_text

def forbidden(self, *args, **kwargs):
    if self.resolve() == LOCAL_CONFIG_PATH.resolve():
        raise AssertionError(f\"configuration read during import: {self}\")
    return original_read_text(self, *args, **kwargs)

Path.read_text = forbidden
import backend.main
print(\"imported\")
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "imported"


def install_real_lifecycle_lock(monkeypatch, api):
    def acquire(config_path):
        assert config_path is main.LOCAL_CONFIG_PATH
        return lifecycle_lock.product_database_lifecycle_lock(
            config_path,
            platform_name="nt",
            windows_api=api,
        )

    monkeypatch.setattr(
        main,
        "product_database_lifecycle_lock",
        acquire,
        raising=False,
    )


def install_exclusive_lifecycle_lock(monkeypatch, api):
    def acquire(config_path):
        assert config_path is main.LOCAL_CONFIG_PATH
        return lifecycle_lock.product_database_lifecycle_lock(
            config_path,
            platform_name="nt",
            windows_api=api,
        )

    monkeypatch.setattr(main, "product_database_lifecycle_lock", acquire)


@pytest.mark.asyncio
async def test_lifespan_lock_wraps_all_startup_and_shutdown_resources(monkeypatch):
    events = install_lifespan_fakes(monkeypatch)

    @contextmanager
    def recording_lock(config_path):
        assert config_path is main.LOCAL_CONFIG_PATH
        events.append("lock-enter")
        try:
            yield
        finally:
            events.append("lock-exit")

    monkeypatch.setattr(
        main,
        "product_database_lifecycle_lock",
        recording_lock,
        raising=False,
    )
    monkeypatch.setattr(
        main.project_packages,
        "cleanup_stale_project_package_roots",
        lambda _temp_parent: events.append("project-package-stale-cleanup"),
    )
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        FakeDraftOperationTaskRegistry(events),
    )
    for module, attribute in (
        (main.planning, "planning_provider_gateway"),
        (main.chapter_outlines, "chapter_outline_provider_gateway"),
        (main.finalization, "finalization_quality_gateway"),
        (main.finalization, "finalization_extraction_gateway"),
    ):
        monkeypatch.setattr(
            module,
            attribute,
            FakePlanningProviderGateway(events),
            raising=False,
        )

    context = main.lifespan(main.app)
    await context.__aenter__()
    events.append("application-body")
    await context.__aexit__(None, None, None)

    assert events[0] == "lock-enter"
    assert events.index("lock-enter") < events.index(
        "project-package-stale-cleanup"
    )
    assert events.index("lock-enter") < events.index("connection-enter")
    for cleanup in (
        "draft-registry-close",
        "provider-close",
        "scheduler-stop",
        "close",
    ):
        assert events.index(cleanup) < events.index("lock-exit")
    assert events[-1] == "lock-exit"


@pytest.mark.asyncio
async def test_lifespan_lock_acquisition_failure_runs_no_application_actions(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    api = FakeWindowsLifecycleLockAPI(wait_result=0x00000102)
    install_real_lifecycle_lock(monkeypatch, api)
    context = main.lifespan(main.app)

    with pytest.raises(lifecycle_lock.ProductDatabaseLifecycleError) as caught:
        await context.__aenter__()

    assert caught.value.args == ("product database lifecycle lock failed",)
    assert events == []
    _assert_no_sensitive_error_graph(caught.value, ())


@pytest.mark.parametrize(
    "authority_factory",
    (SuccessfulTransferDuck, FutureClassSpoof),
)
@pytest.mark.asyncio
async def test_lifespan_rejects_spoofed_previous_transfer_before_app_actions(
    monkeypatch,
    authority_factory,
):
    events = install_lifespan_fakes(monkeypatch)
    lifecycle = ExclusiveRecordingLifecycleLockAPI(events)
    install_exclusive_lifecycle_lock(monkeypatch, lifecycle)
    main.app.state.market_scheduler_shutdown_transfer = authority_factory()
    context = main.lifespan(main.app)
    caught = None

    try:
        await context.__aenter__()
    except BaseException as error:
        caught = error
    else:
        await context.__aexit__(None, None, None)

    assert isinstance(caught, lifecycle_lock.ProductDatabaseLifecycleError)
    assert caught.args == ("product database lifecycle lock failed",)
    assert events == [
        "lock-attempt",
        "lock-enter",
        "lock-exit",
        "lock-close",
    ]
    assert not lifecycle.active
    _assert_no_sensitive_error_graph(caught, ())


@pytest.mark.asyncio
async def test_lifespan_surfaces_safe_lock_cleanup_failure_after_success(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    api = FakeWindowsLifecycleLockAPI(
        release_result=False,
        close_result=False,
    )
    install_real_lifecycle_lock(monkeypatch, api)
    context = main.lifespan(main.app)

    await context.__aenter__()
    with pytest.raises(BaseExceptionGroup) as caught:
        await context.__aexit__(None, None, None)

    assert events[-1] == "close"
    assert caught.value.message == "product database lifecycle lock cleanup failed"
    assert [error.args for error in caught.value.exceptions] == [
        ("product database lifecycle lock cleanup failed",),
        ("product database lifecycle lock cleanup failed",),
    ]
    _assert_no_sensitive_error_graph(caught.value, ())


@pytest.mark.parametrize("phase", ("startup", "body", "shutdown"))
@pytest.mark.parametrize(
    ("error_factory", "expected_type", "expected_args"),
    (
        (
            lambda: RuntimeError("PRIVATE_APPLICATION_FAILURE"),
            lifecycle_lock.ProductDatabaseLifecycleError,
            ("product database lifecycle lock failed",),
        ),
        (lambda: asyncio.CancelledError("PRIVATE_CANCEL"), asyncio.CancelledError, ()),
        (lambda: KeyboardInterrupt("PRIVATE_INTERRUPT"), KeyboardInterrupt, ()),
        (lambda: SystemExit(17), SystemExit, (17,)),
    ),
)
@pytest.mark.asyncio
async def test_lifespan_application_failure_stays_first_when_lock_cleanup_fails(
    monkeypatch,
    phase,
    error_factory,
    expected_type,
    expected_args,
):
    application_error = error_factory()
    events = install_lifespan_fakes(
        monkeypatch,
        verify_error=application_error if phase == "startup" else None,
    )
    if phase == "shutdown":

        async def fail_pool_close():
            events.append("close")
            raise application_error

        monkeypatch.setattr(main, "close_pool", fail_pool_close)
    api = FakeWindowsLifecycleLockAPI(
        release_result=False,
        close_result=False,
    )
    install_real_lifecycle_lock(monkeypatch, api)
    context = main.lifespan(main.app)

    with pytest.raises(BaseExceptionGroup) as caught:
        if phase == "startup":
            await context.__aenter__()
        else:
            await context.__aenter__()
            if phase == "body":
                await context.__aexit__(
                    type(application_error),
                    application_error,
                    application_error.__traceback__,
                )
            else:
                await context.__aexit__(None, None, None)

    primary, release_error, close_error = caught.value.exceptions
    assert type(primary) is expected_type
    assert primary.args == expected_args
    assert release_error.args == (
        "product database lifecycle lock cleanup failed",
    )
    assert close_error.args == (
        "product database lifecycle lock cleanup failed",
    )
    _assert_no_sensitive_error_graph(caught.value, ())
    assert all(
        sentinel not in repr(caught.value)
        for sentinel in (
            "PRIVATE_APPLICATION_FAILURE",
            "PRIVATE_CANCEL",
            "PRIVATE_INTERRUPT",
        )
    )


@pytest.mark.asyncio
async def test_lifespan_never_reads_application_error_traceback_before_lock_exit(
    monkeypatch,
):
    secret = "HOSTILE_APPLICATION_TRACEBACK_SECRET"
    application_error = HostileTracebackRuntimeError(secret)
    events = install_lifespan_fakes(monkeypatch, verify_error=application_error)
    lifecycle = ExclusiveRecordingLifecycleLockAPI(events)
    install_exclusive_lifecycle_lock(monkeypatch, lifecycle)

    with pytest.raises(lifecycle_lock.ProductDatabaseLifecycleError) as caught:
        await main.lifespan(main.app).__aenter__()

    assert application_error.traceback_accesses == 0
    assert caught.value.args == ("product database lifecycle lock failed",)
    assert events.count("lock-exit") == 1
    assert events.count("lock-close") == 1
    assert lifecycle.active is False
    _assert_no_sensitive_error_graph(caught.value, (secret,))


@pytest.mark.asyncio
async def test_lifespan_re_raises_body_primary_suppressed_by_lock_context(
    monkeypatch,
):
    install_lifespan_fakes(monkeypatch)

    @contextmanager
    def malicious_suppressing_lock(_config_path):
        try:
            yield
        except BaseException:
            return

    monkeypatch.setattr(
        main,
        "product_database_lifecycle_lock",
        malicious_suppressing_lock,
        raising=False,
    )
    application_error = RuntimeError("application body failure")
    context = main.lifespan(main.app)
    await context.__aenter__()

    suppressed = await context.__aexit__(
        RuntimeError,
        application_error,
        application_error.__traceback__,
    )

    assert suppressed is False


@pytest.mark.asyncio
async def test_lifespan_retains_lock_through_draft_shutdown_transfer(
    monkeypatch,
    isolated_runtime_configuration,
):
    events = install_lifespan_fakes(monkeypatch)
    lifecycle = ExclusiveRecordingLifecycleLockAPI(events)
    install_exclusive_lifecycle_lock(monkeypatch, lifecycle)
    transfer = ControlledShutdownTransfer(events, "draft")

    class PendingDraftRegistry(FakeDraftOperationTaskRegistry):
        async def aclose(self):
            events.append("draft-registry-close")
            raise draft_operation_tasks.DraftOperationTasksDrainPending(
                transfer
            )

    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        PendingDraftRegistry(events),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(lifecycle_lock.ProductDatabaseLifecycleError):
        await context.__aexit__(None, None, None)

    published = main.app.state.draft_operation_shutdown_transfer
    assert published is not transfer.task
    assert main.app.state.market_scheduler_shutdown_transfer is None
    assert not published.done()
    assert isolated_runtime_configuration.installed is not None
    assert lifecycle.active
    assert events.count("lock-exit") == 0
    with pytest.raises(lifecycle_lock.ProductDatabaseLifecycleError):
        with main.product_database_lifecycle_lock(main.LOCAL_CONFIG_PATH):
            pytest.fail("second lifecycle lock acquisition succeeded")

    transfer.release.set()
    await asyncio.wait_for(published, timeout=1)

    assert events.index("draft-transfer-finish") < events.index("close")
    assert events.index("close") < events.index("lock-exit")
    assert events.count("lock-exit") == 1
    assert isolated_runtime_configuration.installed is None
    assert not lifecycle.active


@pytest.mark.asyncio
async def test_external_completion_cancellation_cannot_clear_snapshot_early(
    monkeypatch,
    isolated_runtime_configuration,
):
    events = install_lifespan_fakes(monkeypatch)
    lifecycle = ExclusiveRecordingLifecycleLockAPI(events)
    install_exclusive_lifecycle_lock(monkeypatch, lifecycle)
    transfer = ControlledShutdownTransfer(events, "draft")

    class PendingDraftRegistry(FakeDraftOperationTaskRegistry):
        async def aclose(self):
            raise draft_operation_tasks.DraftOperationTasksDrainPending(transfer)

    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        PendingDraftRegistry(events),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()
    snapshot = isolated_runtime_configuration.installed

    with pytest.raises(lifecycle_lock.ProductDatabaseLifecycleError):
        await context.__aexit__(None, None, None)

    completion = main.app.state.draft_operation_shutdown_transfer
    completion.cancel()
    await _next_loop_turn()

    assert isolated_runtime_configuration.installed is snapshot
    assert lifecycle.active
    assert events.count("lock-exit") == 0

    transfer.release.set()
    await asyncio.wait_for(transfer.task, timeout=1)
    await _next_loop_turn()

    assert completion.cancelled()
    assert isolated_runtime_configuration.installed is None
    assert events.count("lock-exit") == 1
    assert events.count("lock-close") == 1
    assert lifecycle.active is False


@pytest.mark.parametrize(
    ("error_factory", "expected_type", "expected_args"),
    (
        (
            lambda: RuntimeError("PRIVATE_DEFERRED_CLEAR"),
            lifecycle_lock.ProductDatabaseLifecycleError,
            ("product database lifecycle lock failed",),
        ),
        (lambda: asyncio.CancelledError("PRIVATE_DEFERRED_CANCEL"), asyncio.CancelledError, ()),
        (lambda: KeyboardInterrupt("PRIVATE_DEFERRED_INTERRUPT"), BaseExceptionGroup, ()),
        (lambda: SystemExit(41), BaseExceptionGroup, (41,)),
    ),
)
@pytest.mark.asyncio
async def test_deferred_runtime_clear_failure_is_published_before_release(
    monkeypatch,
    error_factory,
    expected_type,
    expected_args,
):
    events = install_lifespan_fakes(monkeypatch)
    lifecycle = ExclusiveRecordingLifecycleLockAPI(events)
    install_exclusive_lifecycle_lock(monkeypatch, lifecycle)
    transfer = ControlledShutdownTransfer(events, "draft")

    class PendingDraftRegistry(FakeDraftOperationTaskRegistry):
        async def aclose(self):
            raise draft_operation_tasks.DraftOperationTasksDrainPending(transfer)

    def fail_clear(_snapshot):
        events.append("config-clear")
        raise error_factory()

    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        PendingDraftRegistry(events),
    )
    monkeypatch.setattr(main, "clear_runtime_configuration", fail_clear)
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(lifecycle_lock.ProductDatabaseLifecycleError):
        await context.__aexit__(None, None, None)

    completion = main.app.state.draft_operation_shutdown_transfer
    transfer.release.set()
    with pytest.raises(expected_type) as caught:
        await asyncio.wait_for(completion, timeout=1)

    if expected_type is BaseExceptionGroup:
        assert len(caught.value.exceptions) == 1
        flow = caught.value.exceptions[0]
        assert type(flow) in (KeyboardInterrupt, SystemExit)
        assert flow.args == expected_args
    else:
        assert caught.value.args == expected_args
    assert events.index("close") < events.index("config-clear")
    assert events.index("config-clear") < events.index("lock-exit")
    assert events.count("config-clear") == 1
    assert events.count("lock-exit") == 1
    assert events.count("lock-close") == 1
    assert lifecycle.active is False


@pytest.mark.parametrize(
    ("error_factory", "expected_type", "expected_args"),
    (
        (
            lambda: RuntimeError("PRIVATE_TRANSFER_FAILURE"),
            lifecycle_lock.ProductDatabaseLifecycleError,
            ("product database lifecycle lock failed",),
        ),
        (lambda: asyncio.CancelledError("PRIVATE_TRANSFER_CANCEL"), asyncio.CancelledError, ()),
        (lambda: KeyboardInterrupt("PRIVATE_TRANSFER_INTERRUPT"), BaseExceptionGroup, ()),
        (lambda: SystemExit(43), BaseExceptionGroup, (43,)),
    ),
)
@pytest.mark.asyncio
async def test_deferred_transfer_failure_clears_snapshot_before_release(
    monkeypatch,
    error_factory,
    expected_type,
    expected_args,
):
    events = []
    lifecycle = ExclusiveRecordingLifecycleLockAPI(events)
    install_exclusive_lifecycle_lock(monkeypatch, lifecycle)
    transfer = asyncio.get_running_loop().create_future()
    app = SimpleNamespace(
        state=SimpleNamespace(
            draft_operation_shutdown_transfer=None,
            market_scheduler_shutdown_transfer=None,
        )
    )

    @asynccontextmanager
    async def application_context(_app, _runtime_configuration):
        yield
        app.state.draft_operation_shutdown_transfer = transfer

    monkeypatch.setattr(main, "_application_lifespan", application_context)
    monkeypatch.setattr(
        main,
        "clear_runtime_configuration",
        lambda _snapshot: events.append("config-clear"),
    )
    context = main.lifespan(app)
    await context.__aenter__()
    await context.__aexit__(None, None, None)
    completion = app.state.draft_operation_shutdown_transfer

    transfer.set_exception(error_factory())
    with pytest.raises(expected_type) as caught:
        await asyncio.wait_for(completion, timeout=1)

    if expected_type is BaseExceptionGroup:
        assert len(caught.value.exceptions) == 1
        flow = caught.value.exceptions[0]
        assert type(flow) in (KeyboardInterrupt, SystemExit)
        assert flow.args == expected_args
    else:
        assert caught.value.args == expected_args
    assert events == [
        "lock-attempt",
        "lock-enter",
        "config-clear",
        "lock-exit",
        "lock-close",
    ]
    assert lifecycle.active is False


@pytest.mark.asyncio
async def test_lifespan_invalid_final_transfer_exits_lock_once_with_safe_error(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    lifecycle = ExclusiveRecordingLifecycleLockAPI(events)
    install_exclusive_lifecycle_lock(monkeypatch, lifecycle)

    class InvalidFinalTransfer:
        @staticmethod
        def start_pool_close(_close_pool_callback):
            return FutureClassSpoof()

    class PendingDraftRegistry(FakeDraftOperationTaskRegistry):
        async def aclose(self):
            raise draft_operation_tasks.DraftOperationTasksDrainPending(
                InvalidFinalTransfer()
            )

    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        PendingDraftRegistry(events),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(BaseException) as caught:
        await context.__aexit__(None, None, None)

    assert isinstance(
        caught.value,
        (
            lifecycle_lock.ProductDatabaseLifecycleError,
            BaseExceptionGroup,
        ),
    )
    _assert_no_sensitive_error_graph(caught.value, ())
    assert events.count("lock-exit") == 1
    assert events.count("lock-close") == 1
    assert not lifecycle.active


@pytest.mark.asyncio
async def test_lifespan_rejects_distinct_final_transfers_before_deferral(
    monkeypatch,
):
    events = []
    lifecycle = ExclusiveRecordingLifecycleLockAPI(events)
    install_exclusive_lifecycle_lock(monkeypatch, lifecycle)
    app = SimpleNamespace(
        state=SimpleNamespace(
            draft_operation_shutdown_transfer=None,
            market_scheduler_shutdown_transfer=None,
        )
    )
    loop = asyncio.get_running_loop()
    draft_transfer = loop.create_future()
    market_transfer = loop.create_future()
    draft_transfer.set_result(None)
    market_transfer.set_result(None)

    @asynccontextmanager
    async def application_context(_app, _runtime_configuration):
        yield
        app.state.draft_operation_shutdown_transfer = draft_transfer
        app.state.market_scheduler_shutdown_transfer = market_transfer

    monkeypatch.setattr(main, "_application_lifespan", application_context)
    context = main.lifespan(app)
    await context.__aenter__()

    with pytest.raises(lifecycle_lock.ProductDatabaseLifecycleError) as caught:
        await context.__aexit__(None, None, None)

    assert caught.value.args == ("product database lifecycle lock failed",)
    assert events == [
        "lock-attempt",
        "lock-enter",
        "lock-exit",
        "lock-close",
    ]
    assert not lifecycle.active
    _assert_no_sensitive_error_graph(caught.value, ())


@pytest.mark.asyncio
async def test_lifespan_publication_failure_cancels_deferral_and_exits_lock_once(
    monkeypatch,
):
    events = []
    lifecycle = ExclusiveRecordingLifecycleLockAPI(events)
    install_exclusive_lifecycle_lock(monkeypatch, lifecycle)

    class RejectingState:
        draft_operation_shutdown_transfer = None
        market_scheduler_shutdown_transfer = None
        reject_publication = False

        def __setattr__(self, name, value):
            if (
                self.reject_publication
                and name == "draft_operation_shutdown_transfer"
                and type(value) is asyncio.Future
            ):
                raise RuntimeError("PRIVATE_PUBLICATION_FAILURE")
            object.__setattr__(self, name, value)

    state = RejectingState()
    app = SimpleNamespace(state=state)
    transfer = asyncio.get_running_loop().create_future()

    @asynccontextmanager
    async def application_context(_app, _runtime_configuration):
        yield
        state.draft_operation_shutdown_transfer = transfer
        state.reject_publication = True

    monkeypatch.setattr(main, "_application_lifespan", application_context)
    monkeypatch.setattr(
        main,
        "clear_runtime_configuration",
        lambda _snapshot: events.append("config-clear"),
    )
    context = main.lifespan(app)
    await context.__aenter__()

    with pytest.raises(lifecycle_lock.ProductDatabaseLifecycleError) as caught:
        await context.__aexit__(None, None, None)
    await _next_loop_turn()

    assert caught.value.args == ("product database lifecycle lock failed",)
    assert "PRIVATE_PUBLICATION_FAILURE" not in repr(caught.value)
    assert events == [
        "lock-attempt",
        "lock-enter",
        "config-clear",
        "lock-exit",
        "lock-close",
    ]
    assert not lifecycle.active
    assert state.draft_operation_shutdown_transfer is transfer
    assert not transfer.done()
    transfer.cancel()
    _assert_no_sensitive_error_graph(caught.value, ())


@pytest.mark.parametrize(
    ("error_factory", "expected_type", "expected_args"),
    (
        (
            lambda: RuntimeError("PRIVATE_DEFERRED_APPLICATION_FAILURE"),
            lifecycle_lock.ProductDatabaseLifecycleError,
            ("product database lifecycle lock failed",),
        ),
        (
            lambda: asyncio.CancelledError("PRIVATE_DEFERRED_CANCEL"),
            asyncio.CancelledError,
            (),
        ),
        (
            lambda: KeyboardInterrupt("PRIVATE_DEFERRED_INTERRUPT"),
            KeyboardInterrupt,
            (),
        ),
        (lambda: SystemExit(29), SystemExit, (29,)),
    ),
)
@pytest.mark.asyncio
async def test_deferred_application_primary_is_immediately_safe_and_first(
    monkeypatch,
    error_factory,
    expected_type,
    expected_args,
):
    events = install_lifespan_fakes(monkeypatch)
    lifecycle = ExclusiveRecordingLifecycleLockAPI(events)
    install_exclusive_lifecycle_lock(monkeypatch, lifecycle)
    transfer = ControlledShutdownTransfer(events, "draft")

    class PendingDraftRegistry(FakeDraftOperationTaskRegistry):
        async def aclose(self):
            raise draft_operation_tasks.DraftOperationTasksDrainPending(
                transfer
            )

    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        PendingDraftRegistry(events),
    )
    application_error = error_factory()
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(BaseExceptionGroup) as caught:
        await context.__aexit__(
            type(application_error),
            application_error,
            application_error.__traceback__,
        )

    primary = caught.value.exceptions[0]
    assert type(primary) is expected_type
    assert primary.args == expected_args
    assert lifecycle.active
    assert events.count("lock-exit") == 0
    assert all(
        sentinel not in repr(caught.value)
        for sentinel in (
            "PRIVATE_DEFERRED_APPLICATION_FAILURE",
            "PRIVATE_DEFERRED_CANCEL",
            "PRIVATE_DEFERRED_INTERRUPT",
        )
    )

    completion = main.app.state.draft_operation_shutdown_transfer
    transfer.release.set()
    await asyncio.wait_for(completion, timeout=1)

    assert events.count("lock-exit") == 1
    assert not lifecycle.active


@pytest.mark.asyncio
async def test_lifespan_retains_lock_through_market_shutdown_transfer(
    monkeypatch,
    isolated_runtime_configuration,
):
    events = install_lifespan_fakes(monkeypatch)
    lifecycle = ExclusiveRecordingLifecycleLockAPI(events)
    install_exclusive_lifecycle_lock(monkeypatch, lifecycle)
    transfer = ControlledShutdownTransfer(events, "market")

    class PendingMarketRuntime:
        def start(self):
            events.append("scheduler-start")

        async def stop(self):
            events.append("scheduler-stop")
            error = TimeoutError("market scheduler shutdown timed out")
            error.cleanup_transfer = transfer
            raise error

    monkeypatch.setattr(
        main,
        "build_market_scheduler_runtime",
        lambda *, enabled: PendingMarketRuntime(),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(lifecycle_lock.ProductDatabaseLifecycleError):
        await context.__aexit__(None, None, None)

    published = main.app.state.market_scheduler_shutdown_transfer
    assert published is not transfer.task
    assert main.app.state.draft_operation_shutdown_transfer is None
    assert not published.done()
    assert isolated_runtime_configuration.installed is not None
    assert lifecycle.active
    assert events.count("lock-exit") == 0
    with pytest.raises(lifecycle_lock.ProductDatabaseLifecycleError):
        with main.product_database_lifecycle_lock(main.LOCAL_CONFIG_PATH):
            pytest.fail("second lifecycle lock acquisition succeeded")

    transfer.release.set()
    await asyncio.wait_for(published, timeout=1)

    assert events.index("market-transfer-finish") < events.index("close")
    assert events.index("close") < events.index("lock-exit")
    assert events.count("lock-exit") == 1
    assert isolated_runtime_configuration.installed is None
    assert not lifecycle.active


@pytest.mark.asyncio
async def test_lifespan_retains_one_lock_through_combined_shutdown_transfer(
    monkeypatch,
    isolated_runtime_configuration,
):
    events = install_lifespan_fakes(monkeypatch)
    lifecycle = ExclusiveRecordingLifecycleLockAPI(events)
    install_exclusive_lifecycle_lock(monkeypatch, lifecycle)
    draft_transfer = ControlledShutdownTransfer(events, "draft")
    market_transfer = ControlledShutdownTransfer(events, "market")

    class PendingDraftRegistry(FakeDraftOperationTaskRegistry):
        async def aclose(self):
            events.append("draft-registry-close")
            raise draft_operation_tasks.DraftOperationTasksDrainPending(
                draft_transfer
            )

    class PendingMarketRuntime:
        def start(self):
            events.append("scheduler-start")

        async def stop(self):
            events.append("scheduler-stop")
            error = TimeoutError("market scheduler shutdown timed out")
            error.cleanup_transfer = market_transfer
            raise error

    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        PendingDraftRegistry(events),
    )
    monkeypatch.setattr(
        main,
        "build_market_scheduler_runtime",
        lambda *, enabled: PendingMarketRuntime(),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(BaseExceptionGroup) as caught:
        await context.__aexit__(None, None, None)

    assert [type(error) for error in caught.value.exceptions] == [
        lifecycle_lock.ProductDatabaseLifecycleError,
        lifecycle_lock.ProductDatabaseLifecycleError,
    ]

    draft_published = main.app.state.draft_operation_shutdown_transfer
    market_published = main.app.state.market_scheduler_shutdown_transfer
    assert draft_published is market_published
    assert draft_published is not market_transfer.task
    assert lifecycle.active
    assert isolated_runtime_configuration.installed is not None
    assert events.count("lock-exit") == 0

    market_transfer.release.set()
    await _next_loop_turn()
    assert "close" not in events
    assert events.count("lock-exit") == 0
    with pytest.raises(lifecycle_lock.ProductDatabaseLifecycleError):
        with main.product_database_lifecycle_lock(main.LOCAL_CONFIG_PATH):
            pytest.fail("second lifecycle lock acquisition succeeded")

    draft_transfer.release.set()
    await asyncio.wait_for(draft_published, timeout=1)

    assert events.index("market-transfer-finish") < events.index(
        "draft-transfer-finish"
    )
    assert events.index("draft-transfer-finish") < events.index("close")
    assert events.index("close") < events.index("lock-exit")
    assert events.count("lock-exit") == 1
    assert isolated_runtime_configuration.installed is None
    assert not lifecycle.active


@pytest.mark.asyncio
async def test_transferred_lock_release_failure_is_published_and_blocks_restart(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    lifecycle = ExclusiveRecordingLifecycleLockAPI(
        events,
        release_failures=1,
    )
    install_exclusive_lifecycle_lock(monkeypatch, lifecycle)
    transfer = ControlledShutdownTransfer(events, "draft")

    class PendingDraftRegistry(FakeDraftOperationTaskRegistry):
        async def aclose(self):
            raise draft_operation_tasks.DraftOperationTasksDrainPending(
                transfer
            )

    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        PendingDraftRegistry(events),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()
    with pytest.raises(lifecycle_lock.ProductDatabaseLifecycleError):
        await context.__aexit__(None, None, None)

    published = main.app.state.draft_operation_shutdown_transfer
    transfer.release.set()
    await asyncio.wait_for(transfer.task, timeout=1)
    await _next_loop_turn()

    assert published.done()
    published_error = published.exception()
    assert isinstance(
        published_error,
        lifecycle_lock.ProductDatabaseLifecycleError,
    )
    assert published_error.args == (
        "product database lifecycle lock cleanup failed",
    )
    assert events.count("lock-exit") == 1
    app_actions_before_restart = tuple(events)

    restart = main.lifespan(main.app)
    with pytest.raises(lifecycle_lock.ProductDatabaseLifecycleError):
        await restart.__aenter__()

    assert events[len(app_actions_before_restart) :] == [
        "lock-attempt",
        "lock-enter",
        "lock-exit",
        "lock-close",
    ]
    assert events.count("lock-exit") == 2
    assert not lifecycle.active


@pytest.mark.asyncio
async def test_lifespan_runs_one_bounded_project_package_cleanup_before_services(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)

    def cleanup(temp_parent):
        assert temp_parent is main.project_packages.PROJECT_PACKAGE_TEMP_PARENT
        events.append("project-package-stale-cleanup")

    monkeypatch.setattr(
        main.project_packages,
        "cleanup_stale_project_package_roots",
        cleanup,
    )
    context = main.lifespan(main.app)

    await context.__aenter__()
    await context.__aexit__(None, None, None)

    assert events.count("project-package-stale-cleanup") == 1
    assert events.index("project-package-stale-cleanup") < events.index("verify")
    assert events.index("project-package-stale-cleanup") < events.index(
        "scheduler-build"
    )


@pytest.mark.asyncio
async def test_lifespan_runs_bounded_project_import_reconciliation_after_schema(
    monkeypatch, tmp_path, isolated_runtime_configuration,
):
    events = install_lifespan_fakes(monkeypatch)
    managed = tmp_path / "managed"
    managed.mkdir()

    async def reconcile(*, managed_corpus_root, connection_factory, transaction_factory):
        assert managed_corpus_root == managed
        assert connection_factory is main.connection
        assert transaction_factory is main.transaction
        events.append("project-import-reconcile")
        return 0

    isolated_runtime_configuration.snapshot = runtime_configuration(
        managed_corpus_root=managed,
    )
    monkeypatch.setattr(
        main.project_import_service, "reconcile_project_import_staging", reconcile,
    )
    context = main.lifespan(main.app)
    await context.__aenter__()
    await context.__aexit__(None, None, None)

    assert events.count("project-import-reconcile") == 1
    assert events.index("verify") < events.index("project-import-reconcile")
    assert events.index("project-import-reconcile") < events.index("scheduler-build")


@pytest.mark.asyncio
async def test_lifespan_stale_cleanup_failure_logs_only_safe_code_and_still_closes_pool(
    monkeypatch,
    caplog,
):
    events = install_lifespan_fakes(monkeypatch)
    secret = "PRIVATE_STALE_PATH_DSN_SECRET_SENTINEL"

    def fail_cleanup(_temp_parent):
        raise RuntimeError(secret)

    monkeypatch.setattr(
        main.project_packages,
        "cleanup_stale_project_package_roots",
        fail_cleanup,
    )
    context = main.lifespan(main.app)

    with caplog.at_level("WARNING", logger="backend.project_packages"):
        await context.__aenter__()
        await context.__aexit__(None, None, None)

    assert events.count("close") == 1
    assert "project_package_stale_cleanup_failed" in caplog.text
    assert secret not in caplog.text


def test_planning_generation_service_uses_the_exposed_gateway_handle():
    assert (
        planning.get_planning_generation_service()._gateway
        is planning.planning_provider_gateway
    )


def test_outline_generation_service_uses_the_exposed_gateway_handle():
    assert (
        chapter_outlines.get_chapter_outline_generation_service()._gateway
        is chapter_outlines.chapter_outline_provider_gateway
    )


def test_finalization_service_uses_the_exposed_gateway_handles():
    service = finalization.get_finalization_service()
    assert service.quality_provider is finalization.finalization_quality_gateway
    assert service.extraction_provider is finalization.finalization_extraction_gateway


@pytest.mark.asyncio
async def test_lifespan_starts_planning_then_outline_and_closes_in_reverse(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)

    class NamedGateway(FakePlanningProviderGateway):
        def __init__(self, actual_events, name):
            super().__init__(actual_events)
            self.name = name

        async def start(self):
            self.events.append(f"{self.name}-start")

        async def aclose(self):
            self.events.append(f"{self.name}-close")

    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        NamedGateway(events, "planning"),
    )
    monkeypatch.setattr(
        main.chapter_outlines,
        "chapter_outline_provider_gateway",
        NamedGateway(events, "outline"),
        raising=False,
    )
    monkeypatch.setattr(
        main.finalization,
        "finalization_quality_gateway",
        NamedGateway(events, "finalization-quality"),
    )
    monkeypatch.setattr(
        main.finalization,
        "finalization_extraction_gateway",
        NamedGateway(events, "finalization-extraction"),
    )
    context = main.lifespan(main.app)

    await context.__aenter__()
    await context.__aexit__(None, None, None)

    assert [
        event
        for event in events
        if event.endswith(("-start", "-close"))
    ] == [
        "scheduler-start",
        "planning-start",
        "outline-start",
        "finalization-quality-start",
        "finalization-extraction-start",
        "finalization-extraction-close",
        "finalization-quality-close",
        "outline-close",
        "planning-close",
    ]


@pytest.mark.asyncio
async def test_outline_start_failure_rolls_back_both_gateways_before_pool(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    startup_error = RuntimeError("outline startup failed")

    class PlanningGateway(FakePlanningProviderGateway):
        async def start(self):
            events.append("planning-start")

        async def aclose(self):
            events.append("planning-close")

    class OutlineGateway(FakePlanningProviderGateway):
        async def start(self):
            events.append("outline-start")
            raise startup_error

        async def aclose(self):
            events.append("outline-close")

    monkeypatch.setattr(
        main.planning, "planning_provider_gateway", PlanningGateway(events)
    )
    monkeypatch.setattr(
        main.chapter_outlines,
        "chapter_outline_provider_gateway",
        OutlineGateway(events),
        raising=False,
    )

    with pytest.raises(RuntimeError) as caught:
        await main.lifespan(main.app).__aenter__()

    assert caught.value is startup_error
    assert events[-5:] == [
        "outline-start",
        "outline-close",
        "planning-close",
        "scheduler-stop",
        "close",
    ]


@pytest.mark.asyncio
async def test_lifespan_restarts_the_outline_gateway_with_a_new_client(
    monkeypatch,
):
    install_lifespan_fakes(monkeypatch)
    gateway = ChapterOutlineProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(500, request=request)
        )
    )
    monkeypatch.setattr(
        main.chapter_outlines,
        "chapter_outline_provider_gateway",
        gateway,
        raising=False,
    )

    first_context = main.lifespan(main.app)
    await first_context.__aenter__()
    first_client = gateway._resource._client
    assert first_client is not None
    await first_context.__aexit__(None, None, None)

    second_context = main.lifespan(main.app)
    await second_context.__aenter__()
    second_client = gateway._resource._client
    assert second_client is not None
    assert second_client is not first_client
    assert first_client.is_closed is True
    await second_context.__aexit__(None, None, None)
    assert second_client.is_closed is True


@pytest.mark.asyncio
async def test_lifespan_drains_outline_before_closing_planning_and_pool(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)

    class DrainingOutline(FakePlanningProviderGateway):
        def __init__(self, actual_events):
            super().__init__(actual_events)
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def aclose(self):
            events.append("outline-close-start")
            self.started.set()
            await self.release.wait()
            events.append("outline-close-complete")

    outline = DrainingOutline(events)
    monkeypatch.setattr(
        main.chapter_outlines,
        "chapter_outline_provider_gateway",
        outline,
        raising=False,
    )
    context = main.lifespan(main.app)
    await context.__aenter__()
    shutdown = asyncio.create_task(context.__aexit__(None, None, None))
    try:
        await asyncio.wait_for(outline.started.wait(), timeout=1)
        assert "provider-close" not in events
        assert "close" not in events
    finally:
        outline.release.set()
        await asyncio.wait_for(shutdown, timeout=1)

    assert events[-5:] == [
        "outline-close-start",
        "outline-close-complete",
        "provider-close",
        "scheduler-stop",
        "close",
    ]


@pytest.mark.asyncio
async def test_outline_close_failure_is_sanitized_and_planning_still_closes(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    secret = "OUTLINE_CLOSE_SECRET"

    class FailingOutline(FakePlanningProviderGateway):
        async def aclose(self):
            events.append("outline-close")
            raise RuntimeError(secret)

    monkeypatch.setattr(
        main.chapter_outlines,
        "chapter_outline_provider_gateway",
        FailingOutline(events),
        raising=False,
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(OpenAIJSONTransportLifecycleError) as caught:
        await context.__aexit__(None, None, None)

    assert caught.value.args == ("OpenAI JSON transport lifecycle failed",)
    assert events[-4:] == [
        "outline-close",
        "provider-close",
        "scheduler-stop",
        "close",
    ]
    _assert_no_sensitive_error_graph(caught.value, (secret,))


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", (1, 2, 4))
async def test_repeated_cancellation_cannot_interrupt_outline_then_planning_cleanup(
    monkeypatch,
    cancel_count,
):
    events = install_lifespan_fakes(monkeypatch)

    class BlockingOutline(FakePlanningProviderGateway):
        def __init__(self, actual_events):
            super().__init__(actual_events)
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def aclose(self):
            events.append("outline-close-start")
            self.started.set()
            await self.release.wait()
            events.append("outline-close-complete")

    outline = BlockingOutline(events)
    monkeypatch.setattr(
        main.chapter_outlines,
        "chapter_outline_provider_gateway",
        outline,
        raising=False,
    )
    context = main.lifespan(main.app)
    await context.__aenter__()
    shutdown = asyncio.create_task(context.__aexit__(None, None, None))
    try:
        await asyncio.wait_for(outline.started.wait(), timeout=1)
        for _ in range(cancel_count):
            shutdown.cancel()
            await _next_loop_turn()
        assert shutdown.done() is False
        assert "provider-close" not in events
    finally:
        outline.release.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(shutdown, timeout=1)
    assert events[-5:] == [
        "outline-close-start",
        "outline-close-complete",
        "provider-close",
        "scheduler-stop",
        "close",
    ]
    assert shutdown.cancelling() == cancel_count


@pytest.mark.asyncio
async def test_lifespan_verifies_once_before_yield_and_closes_after_success(monkeypatch):
    events = install_lifespan_fakes(monkeypatch)
    context = main.lifespan(main.app)

    await context.__aenter__()
    events.append("app-yielded")

    assert events == [
        "connection-enter",
        "verify",
        "connection-exit",
        "scheduler-build",
        "scheduler-start",
        "provider-start",
        "app-yielded",
    ]

    await context.__aexit__(None, None, None)
    assert events == [
        "connection-enter",
        "verify",
        "connection-exit",
        "scheduler-build",
        "scheduler-start",
        "provider-start",
        "app-yielded",
        "provider-close",
        "scheduler-stop",
        "close",
    ]


@pytest.mark.asyncio
async def test_lifespan_does_not_yield_or_swallow_schema_mismatch(monkeypatch):
    mismatch = SchemaMismatch("wrong schema")
    events = install_lifespan_fakes(monkeypatch, verify_error=mismatch)
    context = main.lifespan(main.app)

    with pytest.raises(SchemaMismatch) as raised:
        await context.__aenter__()

    assert raised.value is mismatch
    assert events == [
        "connection-enter",
        "verify",
        "connection-exit",
        "close",
    ]


@pytest.mark.asyncio
async def test_lifespan_closes_pool_when_yielded_application_fails(monkeypatch):
    events = install_lifespan_fakes(monkeypatch)
    context = main.lifespan(main.app)
    await context.__aenter__()
    app_error = RuntimeError("application failed")

    suppressed = await context.__aexit__(
        RuntimeError, app_error, app_error.__traceback__
    )

    assert suppressed is False
    assert events == [
        "connection-enter",
        "verify",
        "connection-exit",
        "scheduler-build",
        "scheduler-start",
        "provider-start",
        "provider-close",
        "scheduler-stop",
        "close",
    ]


@pytest.mark.asyncio
async def test_lifespan_aggregates_scheduler_and_pool_cleanup_failures(monkeypatch):
    events = install_lifespan_fakes(monkeypatch)
    scheduler_error = RuntimeError("synthetic scheduler cleanup")
    pool_error = RuntimeError("synthetic pool cleanup")

    class FailingRuntime:
        def start(self):
            events.append("scheduler-start")

        async def stop(self):
            events.append("scheduler-stop")
            raise scheduler_error

    monkeypatch.setattr(
        main,
        "build_market_scheduler_runtime",
        lambda *, enabled: FailingRuntime(),
    )

    async def failing_close_pool():
        events.append("close")
        raise pool_error

    monkeypatch.setattr(main, "close_pool", failing_close_pool)
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(BaseExceptionGroup) as aggregated:
        await context.__aexit__(None, None, None)

    assert aggregated.value.exceptions == (scheduler_error, pool_error)
    assert events[-2:] == ["scheduler-stop", "close"]


@pytest.mark.asyncio
async def test_lifespan_preserves_application_error_with_all_cleanup_failures(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    application_error = RuntimeError("synthetic application failure")
    provider_secret = "PROVIDER_CLOSE_AGGREGATION_SECRET"
    scheduler_error = RuntimeError("synthetic scheduler cleanup")
    pool_error = RuntimeError("synthetic pool cleanup")

    class FailingGateway(FakePlanningProviderGateway):
        async def aclose(self):
            events.append("provider-close")
            raise RuntimeError(provider_secret)

    class FailingRuntime:
        def start(self):
            events.append("scheduler-start")

        async def stop(self):
            events.append("scheduler-stop")
            raise scheduler_error

    monkeypatch.setattr(
        main,
        "build_market_scheduler_runtime",
        lambda *, enabled: FailingRuntime(),
    )

    async def failing_close_pool():
        events.append("close")
        raise pool_error

    monkeypatch.setattr(main, "close_pool", failing_close_pool)
    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        FailingGateway(events),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(BaseExceptionGroup) as aggregated:
        await context.__aexit__(
            RuntimeError,
            application_error,
            application_error.__traceback__,
        )

    provider_error = aggregated.value.exceptions[1]
    assert aggregated.value.exceptions == (
        application_error,
        provider_error,
        scheduler_error,
        pool_error,
    )
    assert isinstance(
        provider_error,
        OpenAIJSONTransportLifecycleError,
    )
    assert provider_error.args == (
        "OpenAI JSON transport lifecycle failed",
    )
    assert events[-3:] == ["provider-close", "scheduler-stop", "close"]
    _assert_no_sensitive_error_graph(
        aggregated.value,
        (provider_secret,),
    )


@pytest.mark.asyncio
async def test_lifespan_restarts_the_production_gateway_with_a_new_client(
    monkeypatch,
):
    install_lifespan_fakes(monkeypatch)
    gateway = PlanningProviderGateway(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(500, request=request)
        )
    )
    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        gateway,
    )

    first_context = main.lifespan(main.app)
    await first_context.__aenter__()
    first_client = gateway._resource._client
    assert first_client is not None
    await first_context.__aexit__(None, None, None)

    second_context = main.lifespan(main.app)
    await second_context.__aenter__()
    second_client = gateway._resource._client
    assert second_client is not None
    assert second_client is not first_client
    assert first_client.is_closed is True
    await second_context.__aexit__(None, None, None)
    assert second_client.is_closed is True


@pytest.mark.asyncio
async def test_lifespan_start_failure_prevents_serving_and_always_closes(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    startup_error = RuntimeError("synthetic provider startup")

    class StartFailingGateway(FakePlanningProviderGateway):
        async def start(self):
            self.events.append("provider-start")
            raise startup_error

    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        StartFailingGateway(events),
    )
    context = main.lifespan(main.app)

    with pytest.raises(RuntimeError) as raised:
        await context.__aenter__()

    assert raised.value is startup_error
    assert "app-yielded" not in events
    assert events[-3:] == ["provider-close", "scheduler-stop", "close"]


@pytest.mark.asyncio
async def test_lifespan_waits_for_provider_calls_to_drain_before_pool_close(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)

    class DrainingGateway(FakePlanningProviderGateway):
        def __init__(self, actual_events):
            super().__init__(actual_events)
            self.close_started = asyncio.Event()
            self.active_call_released = asyncio.Event()
            self.close_completed = asyncio.Event()

        async def aclose(self):
            self.events.append("provider-close-start")
            self.close_started.set()
            await self.active_call_released.wait()
            self.events.append("provider-close-complete")
            self.close_completed.set()

    gateway = DrainingGateway(events)
    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        gateway,
    )
    context = main.lifespan(main.app)
    await context.__aenter__()
    shutdown = asyncio.create_task(context.__aexit__(None, None, None))
    try:
        await asyncio.wait_for(gateway.close_started.wait(), timeout=1)
        assert shutdown.done() is False
        assert "close" not in events
    finally:
        gateway.active_call_released.set()
        await asyncio.wait_for(shutdown, timeout=1)

    assert gateway.close_completed.is_set()
    assert events[-4:] == [
        "provider-close-start",
        "provider-close-complete",
        "scheduler-stop",
        "close",
    ]


@pytest.mark.asyncio
async def test_lifespan_sanitizes_provider_close_failure(monkeypatch):
    events = install_lifespan_fakes(monkeypatch)
    api_key = "PRIVATE_API_KEY_SENTINEL"
    base_url = "https://provider.example/v1"
    prompt = "PROMPT_SENTINEL"
    raw_response = "RAW_RESPONSE_SENTINEL"
    request = httpx.Request(
        "POST",
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        content=prompt,
    )
    response = httpx.Response(
        500,
        request=request,
        content=raw_response,
    )

    class CloseFailingGateway(FakePlanningProviderGateway):
        async def aclose(self):
            self.events.append("provider-close")
            raise httpx.HTTPStatusError(
                f"{api_key} {base_url} {prompt} {raw_response}",
                request=request,
                response=response,
            )

    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        CloseFailingGateway(events),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(OpenAIJSONTransportLifecycleError) as caught:
        await context.__aexit__(None, None, None)

    assert caught.value.args == ("OpenAI JSON transport lifecycle failed",)
    assert events[-3:] == ["provider-close", "scheduler-stop", "close"]
    _assert_no_sensitive_error_graph(
        caught.value,
        (api_key, base_url, prompt, raw_response, "Authorization"),
    )


@pytest.mark.asyncio
async def test_lifespan_keeps_application_failure_primary_when_provider_close_fails(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    application_error = RuntimeError("synthetic application failure")
    close_secret = "PROVIDER_CLOSE_SECRET_SENTINEL"

    class CloseFailingGateway(FakePlanningProviderGateway):
        async def aclose(self):
            self.events.append("provider-close")
            raise RuntimeError(close_secret)

    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        CloseFailingGateway(events),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(BaseExceptionGroup) as caught:
        await context.__aexit__(
            RuntimeError,
            application_error,
            application_error.__traceback__,
        )

    assert caught.value.exceptions[0] is application_error
    lifecycle_error = caught.value.exceptions[1]
    assert isinstance(
        lifecycle_error,
        OpenAIJSONTransportLifecycleError,
    )
    assert lifecycle_error.args == (
        "OpenAI JSON transport lifecycle failed",
    )
    _assert_no_sensitive_error_graph(caught.value, (close_secret,))


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", (1, 2, 4))
async def test_lifespan_repeated_cancellation_cannot_interrupt_provider_cleanup(
    monkeypatch,
    cancel_count,
):
    events = install_lifespan_fakes(monkeypatch)
    cleanup_secret = "PROVIDER_CLEANUP_SECRET_SENTINEL"

    class BlockingGateway(FakePlanningProviderGateway):
        def __init__(self, actual_events):
            super().__init__(actual_events)
            self.close_started = asyncio.Event()
            self.close_release = asyncio.Event()
            self.close_completed = asyncio.Event()

        async def aclose(self):
            sensitive_cleanup_local = cleanup_secret
            self.events.append("provider-close-start")
            self.close_started.set()
            await self.close_release.wait()
            assert sensitive_cleanup_local == cleanup_secret
            self.events.append("provider-close-complete")
            self.close_completed.set()

    gateway = BlockingGateway(events)
    monkeypatch.setattr(
        main.planning,
        "planning_provider_gateway",
        gateway,
    )
    context = main.lifespan(main.app)
    await context.__aenter__()
    shutdown = asyncio.create_task(context.__aexit__(None, None, None))
    try:
        await asyncio.wait_for(gateway.close_started.wait(), timeout=1)
        shutdown.cancel()
        await _next_loop_turn()
        for _ in range(cancel_count - 1):
            shutdown.cancel()
        await _next_loop_turn()
        assert shutdown.done() is False
        assert gateway.close_completed.is_set() is False
        assert "close" not in events
    finally:
        gateway.close_release.set()

    with pytest.raises(asyncio.CancelledError) as caught:
        await asyncio.wait_for(shutdown, timeout=1)

    assert gateway.close_completed.is_set()
    assert events[-4:] == [
        "provider-close-start",
        "provider-close-complete",
        "scheduler-stop",
        "close",
    ]
    assert caught.value.args == ()
    assert shutdown.cancelling() == cancel_count
    _assert_no_sensitive_error_graph(caught.value, (cleanup_secret,))


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", (1, 2, 4))
async def test_lifespan_repeated_cancellation_cannot_interrupt_pool_close(
    monkeypatch,
    cancel_count,
):
    events = install_lifespan_fakes(monkeypatch)
    cleanup_secret = "POOL_CLEANUP_SECRET_SENTINEL"
    close_started = asyncio.Event()
    close_release = asyncio.Event()
    close_completed = asyncio.Event()

    async def blocking_close_pool():
        sensitive_cleanup_local = cleanup_secret
        events.append("pool-close-start")
        close_started.set()
        try:
            await close_release.wait()
        finally:
            events.append("pool-close-finally")
        assert sensitive_cleanup_local == cleanup_secret
        events.append("pool-close-complete")
        close_completed.set()

    monkeypatch.setattr(main, "close_pool", blocking_close_pool)
    context = main.lifespan(main.app)
    await context.__aenter__()
    shutdown = asyncio.create_task(context.__aexit__(None, None, None))
    try:
        await asyncio.wait_for(close_started.wait(), timeout=1)
        shutdown.cancel()
        await _next_loop_turn()
        for _ in range(cancel_count - 1):
            shutdown.cancel()
        await _next_loop_turn()
        assert shutdown.done() is False
        assert close_completed.is_set() is False
    finally:
        close_release.set()

    with pytest.raises(asyncio.CancelledError) as caught:
        await asyncio.wait_for(shutdown, timeout=1)

    assert close_completed.is_set()
    assert events[-3:] == [
        "pool-close-start",
        "pool-close-finally",
        "pool-close-complete",
    ]
    assert caught.value.args == ()
    assert shutdown.cancelling() == cancel_count
    _assert_no_sensitive_error_graph(caught.value, (cleanup_secret,))


@pytest.mark.asyncio
async def test_lifespan_transfers_stalled_cleanup_before_pool_close(
    monkeypatch,
):
    from backend.runtime.market_scheduler import MarketSchedulerRuntime

    events = install_lifespan_fakes(monkeypatch)

    class UnresponsiveScheduler:
        enabled = True
        next_run_at = None

        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.cleaned = asyncio.Event()

        async def run_once(self):
            self.started.set()
            try:
                while not self.release.is_set():
                    try:
                        await self.release.wait()
                    except asyncio.CancelledError:
                        asyncio.current_task().uncancel()
            finally:
                events.append("scheduler-cleaned")
                self.cleaned.set()

    scheduler = UnresponsiveScheduler()
    runtime = MarketSchedulerRuntime(
        scheduler,
        poll_interval_seconds=60,
        shutdown_timeout_seconds=0.02,
    )
    monkeypatch.setattr(
        main,
        "build_market_scheduler_runtime",
        lambda *, enabled: runtime,
    )

    async def ordered_close_pool():
        events.append("close-after-cleaned" if scheduler.cleaned.is_set() else "close-early")

    monkeypatch.setattr(main, "close_pool", ordered_close_pool)
    context = main.lifespan(main.app)
    await context.__aenter__()
    await asyncio.wait_for(scheduler.started.wait(), timeout=1)
    started = asyncio.get_running_loop().time()

    with pytest.raises(TimeoutError):
        await context.__aexit__(None, None, None)

    elapsed = asyncio.get_running_loop().time() - started
    before_release = tuple(events)
    transfer = getattr(
        main.app.state,
        "market_scheduler_shutdown_transfer",
        None,
    )
    scheduler.release.set()
    if transfer is None:
        await asyncio.wait_for(scheduler.cleaned.wait(), timeout=1)
    else:
        await asyncio.wait_for(transfer, timeout=1)

    assert elapsed < 0.5
    assert "close-early" not in before_release
    assert "close-after-cleaned" not in before_release
    assert transfer is not None
    assert events[-2:] == ["scheduler-cleaned", "close-after-cleaned"]


@pytest.mark.asyncio
async def test_lifespan_cancellation_during_stop_defers_pool_close(
    monkeypatch,
):
    from backend.runtime.market_scheduler import MarketSchedulerRuntime

    events = install_lifespan_fakes(monkeypatch)

    class UnresponsiveScheduler:
        enabled = True
        next_run_at = None

        def __init__(self):
            self.started = asyncio.Event()
            self.cancel_seen = asyncio.Event()
            self.release = asyncio.Event()
            self.cleaned = asyncio.Event()

        async def run_once(self):
            self.started.set()
            try:
                while not self.release.is_set():
                    try:
                        await self.release.wait()
                    except asyncio.CancelledError:
                        self.cancel_seen.set()
                        asyncio.current_task().uncancel()
            finally:
                events.append("scheduler-cleaned")
                self.cleaned.set()

    scheduler = UnresponsiveScheduler()
    runtime = MarketSchedulerRuntime(
        scheduler,
        poll_interval_seconds=60,
        shutdown_timeout_seconds=1,
    )
    monkeypatch.setattr(
        main,
        "build_market_scheduler_runtime",
        lambda *, enabled: runtime,
    )

    async def ordered_close_pool():
        events.append("close-after-cleaned" if scheduler.cleaned.is_set() else "close-early")

    monkeypatch.setattr(main, "close_pool", ordered_close_pool)
    context = main.lifespan(main.app)
    await context.__aenter__()
    await asyncio.wait_for(scheduler.started.wait(), timeout=1)
    shutdown = asyncio.create_task(
        context.__aexit__(None, None, None)
    )
    await asyncio.wait_for(scheduler.cancel_seen.wait(), timeout=1)

    shutdown.cancel()
    with pytest.raises(asyncio.CancelledError):
        await shutdown

    before_release = tuple(events)
    transfer = getattr(
        main.app.state,
        "market_scheduler_shutdown_transfer",
        None,
    )
    scheduler.release.set()
    if transfer is None:
        await asyncio.wait_for(scheduler.cleaned.wait(), timeout=1)
    else:
        await asyncio.wait_for(transfer, timeout=1)

    assert "close-early" not in before_release
    assert "close-after-cleaned" not in before_release
    assert transfer is not None
    assert events[-2:] == ["scheduler-cleaned", "close-after-cleaned"]


@pytest.mark.asyncio
async def test_lifespan_starts_draft_registry_after_schema_and_drains_it_first(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    registry = FakeDraftOperationTaskRegistry(events)
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )
    context = main.lifespan(main.app)

    await context.__aenter__()
    events.append("app-yielded")
    await context.__aexit__(None, None, None)

    assert events.index("verify") < events.index("draft-registry-start")
    assert events.index("draft-registry-start") < events.index("scheduler-build")
    assert events.index("draft-registry-start") < events.index("app-yielded")
    assert events.index("draft-registry-close") < events.index("provider-close")
    assert events.index("draft-registry-close") < events.index("scheduler-stop")
    assert events.index("draft-registry-close") < events.index("close")


@pytest.mark.asyncio
async def test_lifespan_waits_for_named_draft_registry_drain_before_other_cleanup(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)

    class BlockingRegistry(FakeDraftOperationTaskRegistry):
        def __init__(self, actual_events):
            super().__init__(actual_events)
            self.close_started = asyncio.Event()
            self.close_release = asyncio.Event()
            self.close_completed = asyncio.Event()
            self.close_task_name = None

        async def aclose(self):
            self.close_task_name = asyncio.current_task().get_name()
            events.append("draft-registry-close-start")
            self.close_started.set()
            await self.close_release.wait()
            events.append("draft-registry-close-complete")
            self.close_completed.set()

    registry = BlockingRegistry(events)
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )
    context = main.lifespan(main.app)
    await context.__aenter__()
    shutdown = asyncio.create_task(context.__aexit__(None, None, None))
    try:
        await asyncio.wait_for(registry.close_started.wait(), timeout=1)
        assert "provider-close" not in events
        assert "scheduler-stop" not in events
        assert "close" not in events
    finally:
        registry.close_release.set()
        await asyncio.wait_for(shutdown, timeout=1)

    assert registry.close_completed.is_set()
    assert registry.close_task_name == "draft-operation-task-registry-close"
    assert events.index("draft-registry-close-complete") < events.index(
        "provider-close"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", (1, 2, 4))
async def test_repeated_cancellation_cannot_interrupt_draft_registry_drain(
    monkeypatch,
    cancel_count,
):
    events = install_lifespan_fakes(monkeypatch)

    class BlockingRegistry(FakeDraftOperationTaskRegistry):
        def __init__(self):
            super().__init__(events)
            self.close_started = asyncio.Event()
            self.close_release = asyncio.Event()
            self.close_completed = asyncio.Event()

        async def aclose(self):
            events.append("draft-registry-close-start")
            self.close_started.set()
            await self.close_release.wait()
            events.append("draft-registry-close-complete")
            self.close_completed.set()

    registry = BlockingRegistry()
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )
    context = main.lifespan(main.app)
    await context.__aenter__()
    shutdown = asyncio.create_task(context.__aexit__(None, None, None))
    try:
        await asyncio.wait_for(registry.close_started.wait(), timeout=1)
        for _ in range(cancel_count):
            shutdown.cancel()
            await _next_loop_turn()
        assert shutdown.done() is False
        assert "provider-close" not in events
        assert "close" not in events
    finally:
        registry.close_release.set()

    with pytest.raises(asyncio.CancelledError) as caught:
        await asyncio.wait_for(shutdown, timeout=1)

    assert caught.value.args == ()
    assert shutdown.cancelling() == cancel_count
    assert registry.close_completed.is_set()
    assert events.index("draft-registry-close-complete") < events.index(
        "provider-close"
    )


@pytest.mark.asyncio
async def test_draft_registry_start_failure_is_primary_and_still_closes(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    startup_error = RuntimeError("synthetic draft registry startup")

    class StartFailingRegistry(FakeDraftOperationTaskRegistry):
        async def start(self):
            events.append("draft-registry-start")
            raise startup_error

        async def aclose(self):
            events.append("draft-registry-close")

    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        StartFailingRegistry(events),
    )

    with pytest.raises(RuntimeError) as caught:
        await main.lifespan(main.app).__aenter__()

    assert caught.value is startup_error
    assert "scheduler-build" not in events
    assert "provider-start" not in events
    assert events[-2:] == ["draft-registry-close", "close"]


@pytest.mark.asyncio
async def test_draft_registry_close_failure_is_fixed_and_other_cleanup_continues(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    cleanup_secret = "DRAFT_REGISTRY_CLEANUP_SECRET_SENTINEL"

    class CloseFailingRegistry(FakeDraftOperationTaskRegistry):
        async def aclose(self):
            events.append("draft-registry-close")
            raise RuntimeError(cleanup_secret)

    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        CloseFailingRegistry(events),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(RuntimeError) as caught:
        await context.__aexit__(None, None, None)

    assert caught.value.args == (
        "Draft operation task registry lifecycle failed",
    )
    assert events[-3:] == [
        "draft-registry-close",
        "provider-close",
        "scheduler-stop",
    ]
    assert "close" not in events
    _assert_no_sensitive_error_graph(caught.value, (cleanup_secret,))


@pytest.mark.asyncio
async def test_generic_draft_failure_blocks_market_transfer_pool_callback(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)

    class CloseFailingRegistry(FakeDraftOperationTaskRegistry):
        async def aclose(self):
            events.append("draft-registry-close")
            raise RuntimeError("PRIVATE_DRAFT_CLOSE_SENTINEL")

    class CleanupTransfer:
        def __init__(self):
            self.task = None

        def start_pool_close(self, close_pool_callback):
            if self.task is None:
                self.task = asyncio.create_task(close_pool_callback())
                self.task.add_done_callback(
                    lambda task: task.exception()
                    if not task.cancelled()
                    else None
                )
            return self.task

    cleanup_transfer = CleanupTransfer()

    class TransferredRuntime:
        def start(self):
            events.append("scheduler-start")

        async def stop(self):
            events.append("scheduler-stop")
            error = TimeoutError("market scheduler shutdown timed out")
            error.cleanup_transfer = cleanup_transfer
            raise error

    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        CloseFailingRegistry(events),
    )
    monkeypatch.setattr(
        main,
        "build_market_scheduler_runtime",
        lambda *, enabled: TransferredRuntime(),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(BaseExceptionGroup):
        await context.__aexit__(None, None, None)

    transfer_task = main.app.state.market_scheduler_shutdown_transfer
    await asyncio.gather(transfer_task, return_exceptions=True)

    assert "draft-registry-close" in events
    assert "provider-close" in events
    assert "scheduler-stop" in events
    assert "close" not in events


@pytest.mark.asyncio
async def test_draft_registry_pending_drain_transfers_pool_close_safely(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    monkeypatch.setattr(
        draft_operation_tasks,
        "_DRAFT_OPERATION_TASK_SHUTDOWN_TIMEOUT_SECONDS",
        0.01,
    )
    registry = DraftOperationTaskRegistry()
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )
    worker_started = asyncio.Event()
    worker_cancelled = asyncio.Event()
    worker_release = asyncio.Event()
    worker_settled = asyncio.Event()
    worker_secret = "DRAFT_WORKER_PRIVATE_SENTINEL"

    async def stubborn_worker(signal):
        sensitive_local = worker_secret
        worker_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            assert signal.is_set()
            worker_cancelled.set()
            await worker_release.wait()
        assert sensitive_local == worker_secret
        events.append("draft-worker-settled")
        worker_settled.set()

    context = main.lifespan(main.app)
    await context.__aenter__()
    registry.launch("private-operation-id", stubborn_worker)
    await worker_started.wait()
    transfer = None
    try:
        with pytest.raises(
            main.DraftOperationTaskRegistryLifecycleError
        ) as caught:
            await asyncio.wait_for(
                context.__aexit__(None, None, None),
                timeout=0.5,
            )

        transfer = main.app.state.draft_operation_shutdown_transfer
        before_release = tuple(events)
        assert caught.value.args == (
            "Draft operation task registry lifecycle failed",
        )
        assert worker_cancelled.is_set()
        assert registry.state == "closing"
        assert registry.size == 1
        assert transfer is not None
        assert not transfer.done()
        assert "close" not in before_release
        _assert_no_sensitive_error_graph(
            caught.value,
            (worker_secret, "private-operation-id"),
        )

        worker_release.set()
        await asyncio.wait_for(transfer, timeout=1)

        assert worker_settled.is_set()
        assert registry.state == "closed"
        assert registry.size == 0
        assert events.count("close") == 1
        assert events.index("draft-worker-settled") < events.index("close")
    finally:
        worker_release.set()
        transfer = getattr(
            main.app.state,
            "draft_operation_shutdown_transfer",
            transfer,
        )
        if transfer is not None:
            await asyncio.wait_for(
                asyncio.shield(transfer),
                timeout=1,
            )
        await asyncio.wait_for(worker_settled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_draft_and_market_pending_drains_share_one_ordered_pool_transfer(
    monkeypatch,
):
    from backend.runtime.market_scheduler import MarketSchedulerRuntime

    events = install_lifespan_fakes(monkeypatch)
    monkeypatch.setattr(
        draft_operation_tasks,
        "_DRAFT_OPERATION_TASK_SHUTDOWN_TIMEOUT_SECONDS",
        0.01,
    )
    registry = DraftOperationTaskRegistry()
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )

    class UnresponsiveScheduler:
        enabled = True
        next_run_at = None

        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.cleaned = asyncio.Event()

        async def run_once(self):
            self.started.set()
            try:
                while not self.release.is_set():
                    try:
                        await self.release.wait()
                    except asyncio.CancelledError:
                        asyncio.current_task().uncancel()
            finally:
                events.append("market-drained")
                self.cleaned.set()

    scheduler = UnresponsiveScheduler()
    runtime = MarketSchedulerRuntime(
        scheduler,
        poll_interval_seconds=60,
        shutdown_timeout_seconds=0.01,
    )
    monkeypatch.setattr(
        main,
        "build_market_scheduler_runtime",
        lambda *, enabled: runtime,
    )
    draft_started = asyncio.Event()
    draft_cancelled = asyncio.Event()
    draft_release = asyncio.Event()
    draft_settled = asyncio.Event()

    async def stubborn_draft(signal):
        draft_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            assert signal.is_set()
            draft_cancelled.set()
            await draft_release.wait()
        events.append("draft-drained")
        draft_settled.set()

    context = main.lifespan(main.app)
    await context.__aenter__()
    await asyncio.wait_for(scheduler.started.wait(), timeout=1)
    registry.launch("operation", stubborn_draft)
    await draft_started.wait()
    draft_transfer = None
    market_transfer = None
    try:
        with pytest.raises(BaseExceptionGroup):
            await asyncio.wait_for(
                context.__aexit__(None, None, None),
                timeout=0.5,
            )

        draft_transfer = main.app.state.draft_operation_shutdown_transfer
        market_transfer = main.app.state.market_scheduler_shutdown_transfer
        assert draft_cancelled.is_set()
        assert draft_transfer is not None
        assert draft_transfer is market_transfer
        assert "close" not in events

        scheduler.release.set()
        await asyncio.wait_for(scheduler.cleaned.wait(), timeout=1)
        await _next_loop_turn()
        assert "close" not in events

        draft_release.set()
        await asyncio.wait_for(draft_transfer, timeout=1)

        assert draft_settled.is_set()
        assert registry.state == "closed"
        assert events.count("close") == 1
        assert events.index("market-drained") < events.index("close")
        assert events.index("draft-drained") < events.index("close")
    finally:
        scheduler.release.set()
        draft_release.set()
        final_tasks = {
            task
            for task in (
                getattr(
                    main.app.state,
                    "draft_operation_shutdown_transfer",
                    draft_transfer,
                ),
                getattr(
                    main.app.state,
                    "market_scheduler_shutdown_transfer",
                    market_transfer,
                ),
            )
            if task is not None
        }
        if final_tasks:
            await asyncio.wait_for(
                asyncio.gather(*final_tasks, return_exceptions=True),
                timeout=1,
            )
        await asyncio.wait_for(scheduler.cleaned.wait(), timeout=1)
        await asyncio.wait_for(draft_settled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_lifespan_fails_closed_while_previous_draft_transfer_is_pending(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    never = asyncio.Event()
    previous_transfer = asyncio.create_task(never.wait())
    main.app.state.draft_operation_shutdown_transfer = previous_transfer
    context = main.lifespan(main.app)
    entered = False

    try:
        with pytest.raises(
            main.DraftOperationTaskRegistryLifecycleError
        ) as caught:
            await context.__aenter__()
            entered = True

        assert caught.value.args == (
            "Draft operation task registry lifecycle failed",
        )
        assert events == []
    finally:
        if entered:
            await context.__aexit__(None, None, None)
        previous_transfer.cancel()
        await asyncio.gather(previous_transfer, return_exceptions=True)
        main.app.state.draft_operation_shutdown_transfer = None


@pytest.mark.asyncio
async def test_lifespan_fails_closed_safely_after_previous_draft_transfer_failure(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    transfer_secret = "DRAFT_TRANSFER_FAILURE_SECRET_SENTINEL"

    async def fail_transfer():
        raise RuntimeError(transfer_secret)

    previous_transfer = asyncio.create_task(fail_transfer())
    await asyncio.gather(previous_transfer, return_exceptions=True)
    main.app.state.draft_operation_shutdown_transfer = previous_transfer
    context = main.lifespan(main.app)
    entered = False

    try:
        with pytest.raises(
            main.DraftOperationTaskRegistryLifecycleError
        ) as caught:
            await context.__aenter__()
            entered = True

        assert caught.value.args == (
            "Draft operation task registry lifecycle failed",
        )
        assert events == []
        _assert_no_sensitive_error_graph(caught.value, (transfer_secret,))
    finally:
        if entered:
            await context.__aexit__(None, None, None)
        main.app.state.draft_operation_shutdown_transfer = None


@pytest.mark.asyncio
async def test_lifespan_fails_closed_before_startup_for_pending_market_transfer(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    registry = FakeDraftOperationTaskRegistry(events)
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )
    previous_transfer = asyncio.create_task(asyncio.Event().wait())
    main.app.state.market_scheduler_shutdown_transfer = previous_transfer
    context = main.lifespan(main.app)
    entered = False

    try:
        with pytest.raises(
            main.DraftOperationTaskRegistryLifecycleError
        ) as caught:
            await context.__aenter__()
            entered = True

        assert caught.value.args == (
            "Draft operation task registry lifecycle failed",
        )
        assert events == []
    finally:
        if entered:
            await context.__aexit__(None, None, None)
        previous_transfer.cancel()
        await asyncio.gather(previous_transfer, return_exceptions=True)
        main.app.state.market_scheduler_shutdown_transfer = None


@pytest.mark.asyncio
async def test_lifespan_fails_closed_safely_for_failed_market_transfer(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    registry = FakeDraftOperationTaskRegistry(events)
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )
    transfer_secret = "MARKET_TRANSFER_FAILURE_SECRET_SENTINEL"

    async def fail_transfer():
        raise RuntimeError(transfer_secret)

    previous_transfer = asyncio.create_task(fail_transfer())
    await asyncio.gather(previous_transfer, return_exceptions=True)
    main.app.state.market_scheduler_shutdown_transfer = previous_transfer
    context = main.lifespan(main.app)
    entered = False

    try:
        with pytest.raises(
            main.DraftOperationTaskRegistryLifecycleError
        ) as caught:
            await context.__aenter__()
            entered = True

        assert caught.value.args == (
            "Draft operation task registry lifecycle failed",
        )
        assert events == []
        _assert_no_sensitive_error_graph(caught.value, (transfer_secret,))
    finally:
        if entered:
            await context.__aexit__(None, None, None)
        main.app.state.market_scheduler_shutdown_transfer = None


@pytest.mark.asyncio
async def test_lifespan_allows_restart_after_successful_market_transfer(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    registry = FakeDraftOperationTaskRegistry(events)
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )
    previous_transfer = asyncio.create_task(asyncio.sleep(0))
    await previous_transfer
    main.app.state.market_scheduler_shutdown_transfer = previous_transfer
    context = main.lifespan(main.app)

    await context.__aenter__()
    await context.__aexit__(None, None, None)

    assert events.index("verify") < events.index("draft-registry-start")
    assert events.index("draft-registry-start") < events.index("scheduler-build")


@pytest.mark.asyncio
async def test_lifespan_deduplicates_same_successful_draft_and_market_transfer(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)

    class ClosedRegistry(FakeDraftOperationTaskRegistry):
        state = "closed"

    registry = ClosedRegistry(events)
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )

    previous_transfer = asyncio.get_running_loop().create_future()
    previous_transfer.set_result(None)
    assert type(previous_transfer) is asyncio.Future
    main.app.state.draft_operation_shutdown_transfer = previous_transfer
    main.app.state.market_scheduler_shutdown_transfer = previous_transfer
    context = main.lifespan(main.app)

    await context.__aenter__()
    await context.__aexit__(None, None, None)

    assert previous_transfer.result() is None


@pytest.mark.asyncio
async def test_application_error_stays_primary_when_draft_registry_close_fails(
    monkeypatch,
):
    events = install_lifespan_fakes(monkeypatch)
    application_error = RuntimeError("synthetic application failure")
    cleanup_secret = "DRAFT_REGISTRY_AGGREGATION_SECRET_SENTINEL"

    class CloseFailingRegistry(FakeDraftOperationTaskRegistry):
        async def aclose(self):
            raise RuntimeError(cleanup_secret)

    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        CloseFailingRegistry(events),
    )
    context = main.lifespan(main.app)
    await context.__aenter__()

    with pytest.raises(BaseExceptionGroup) as caught:
        await context.__aexit__(
            RuntimeError,
            application_error,
            application_error.__traceback__,
        )

    assert caught.value.exceptions[0] is application_error
    lifecycle_error = caught.value.exceptions[1]
    assert isinstance(
        lifecycle_error,
        main.DraftOperationTaskRegistryLifecycleError,
    )
    assert lifecycle_error.args == (
        "Draft operation task registry lifecycle failed",
    )
    _assert_no_sensitive_error_graph(caught.value, (cleanup_secret,))


@pytest.mark.asyncio
async def test_lifespan_restarts_the_same_draft_registry_cleanly(monkeypatch):
    install_lifespan_fakes(monkeypatch)
    registry = DraftOperationTaskRegistry()
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )

    for generation in (1, 2):
        context = main.lifespan(main.app)
        await context.__aenter__()
        completed = asyncio.Event()

        async def worker(_signal):
            completed.set()

        registry.launch(f"operation-{generation}", worker)
        await asyncio.wait_for(completed.wait(), timeout=1)
        await context.__aexit__(None, None, None)
        assert registry.size == 0


@pytest.mark.asyncio
async def test_lifespan_shutdown_only_cancels_task_without_business_cancel(
    monkeypatch,
):
    install_lifespan_fakes(monkeypatch)
    registry = DraftOperationTaskRegistry()
    monkeypatch.setattr(
        main.chapter_sessions,
        "draft_operation_task_registry",
        registry,
    )
    business_cancels = []

    async def forbidden_business_cancel(*args):
        business_cancels.append(args)

    monkeypatch.setattr(
        main.chapter_sessions._draft_operation_service,
        "cancel",
        forbidden_business_cancel,
    )
    worker_started = asyncio.Event()
    worker_cancelled = asyncio.Event()

    async def worker(_signal):
        worker_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            worker_cancelled.set()
            raise

    context = main.lifespan(main.app)
    await context.__aenter__()
    registry.launch("operation-active-at-shutdown", worker)
    await asyncio.wait_for(worker_started.wait(), timeout=1)

    await context.__aexit__(None, None, None)

    assert worker_cancelled.is_set()
    assert business_cancels == []
    assert registry.size == 0


@pytest.mark.asyncio
async def test_health_echoes_browser_owner_nonce_only_when_explicitly_injected(
    monkeypatch,
):
    monkeypatch.delenv("M2_BROWSER_RUN_NONCE", raising=False)
    assert await main.health() == {"ok": True}

    monkeypatch.setenv("M2_BROWSER_RUN_NONCE", "owned-browser-child-123")
    assert await main.health() == {
        "ok": True,
        "browserRunNonce": "owned-browser-child-123",
    }
