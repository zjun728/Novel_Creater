from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.domain.product_database_readiness import (
    LEGACY_DATABASE,
    BackupReceipt,
    DatabaseInventory,
    ProductDatabaseReadinessError,
    ReadinessState,
    inventory_hash,
)
from backend.services import product_database_backup as backup


HASH_A = "a" * 64
RESTORE_DATABASE = "novel_creator_phase7b_restore_0123456789abcdef0123456789abcdef"


def make_inventory() -> DatabaseInventory:
    return DatabaseInventory(
        database=LEGACY_DATABASE,
        server_version="8.4.6",
        schema_version="writer-core-v1.13.0",
        manifest_hash="b" * 64,
        structural_fingerprint="c" * 64,
        table_names=("schema_metadata",),
        row_counts=(("schema_metadata", 1),),
        nonempty_table_count=1,
        total_row_count=1,
    )


def make_clients(tmp_path: Path) -> tuple[backup.MySQLClientPair, Path]:
    clients = tmp_path / "clients"
    clients.mkdir()
    dump = clients / "mysqldump.exe"
    mysql = clients / "mysql.exe"
    dump.write_bytes(b"fake")
    mysql.write_bytes(b"fake")
    return backup.MySQLClientPair(dump, mysql, "8.4.6"), clients


def make_option(tmp_path: Path) -> Path:
    option = tmp_path / "client.cnf"
    option.write_text("[client]\n", encoding="utf-8")
    return option


def test_client_pair_is_frozen_and_preflight_requires_matching_84_clients(tmp_path: Path):
    repository = tmp_path / "repo"
    repository.mkdir()
    pair, _ = make_clients(tmp_path)
    seen: list[Path] = []

    def versions(path: Path) -> str:
        seen.append(path)
        return f"{path.stem}  Ver 8.4.6 for Win64 on x86_64"

    observed = backup.preflight_client_pair(
        pair.mysqldump, pair.mysql, repository, versions
    )
    assert observed == pair
    assert seen == [pair.mysqldump, pair.mysql]
    with pytest.raises(FrozenInstanceError):
        observed.version = "8.4.7"  # type: ignore[misc]


@pytest.mark.parametrize("failure", (KeyboardInterrupt(), SystemExit(7), asyncio.CancelledError()))
def test_client_preflight_preserves_flow_control(tmp_path: Path, failure: BaseException):
    repository = tmp_path / "repo"
    repository.mkdir()
    pair, _ = make_clients(tmp_path)

    def fail(_path: Path) -> str:
        raise failure

    with pytest.raises(type(failure)) as raised:
        backup.preflight_client_pair(pair.mysqldump, pair.mysql, repository, fail)
    assert raised.value is failure


def test_client_preflight_rejects_relative_repo_inside_link_and_mismatch(tmp_path: Path):
    repository = tmp_path / "repo"
    repository.mkdir()
    inside_dump = repository / "mysqldump.exe"
    inside_dump.write_bytes(b"fake")
    pair, _ = make_clients(tmp_path)
    version = lambda path: f"{path.stem} Ver 8.4.6"

    unsafe_pairs = [
        (Path("mysqldump.exe"), pair.mysql, version),
        (inside_dump, pair.mysql, version),
        (pair.mysqldump, pair.mysql, lambda path: f"{path.stem} Ver 8.0.40"),
        (
            pair.mysqldump,
            pair.mysql,
            lambda path: f"{path.stem} Ver {'8.4.6' if path == pair.mysqldump else '8.4.7'}",
        ),
    ]
    for dump, mysql, runner in unsafe_pairs:
        with pytest.raises(backup.ProductDatabaseBackupError) as raised:
            backup.preflight_client_pair(dump, mysql, repository, runner)
        assert str(raised.value) == "mysql client preflight failed"

    link = tmp_path / "dump-link.exe"
    try:
        link.symlink_to(pair.mysqldump)
    except OSError:
        return
    with pytest.raises(backup.ProductDatabaseBackupError):
        backup.preflight_client_pair(link, pair.mysql, repository, version)


def test_client_preflight_checks_parent_components_for_reparse_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repository = tmp_path / "repo"
    repository.mkdir()
    pair, clients = make_clients(tmp_path)
    real_check = backup._is_reparse
    monkeypatch.setattr(
        backup,
        "_is_reparse",
        lambda path: path == clients or real_check(path),
    )
    version = lambda path: f"{path.stem} Ver 8.4.6"
    with pytest.raises(backup.ProductDatabaseBackupError):
        backup.preflight_client_pair(
            pair.mysqldump, pair.mysql, repository, version
        )


def test_exact_dump_and_restore_vectors_keep_option_first_and_contain_no_secret(tmp_path: Path):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    password = "never-in-argv"
    dump = backup.dump_command(pair, option, LEGACY_DATABASE)
    restore = backup.restore_command(pair, option, RESTORE_DATABASE)
    assert dump == [
        str(pair.mysqldump),
        f"--defaults-extra-file={option}",
        "--protocol=TCP",
        "--single-transaction",
        "--quick",
        "--hex-blob",
        "--routines",
        "--events",
        "--triggers",
        "--set-gtid-purged=OFF",
        "--skip-add-locks",
        "--skip-lock-tables",
        LEGACY_DATABASE,
    ]
    assert restore == [
        str(pair.mysql),
        f"--defaults-extra-file={option}",
        "--protocol=TCP",
        "--binary-mode=1",
        RESTORE_DATABASE,
    ]
    assert password not in " ".join(dump + restore)
    assert "--databases" not in dump
    with pytest.raises(ProductDatabaseReadinessError):
        backup.dump_command(pair, option, "novel_creator_v113")
    for invalid in (LEGACY_DATABASE, "novel_creator_v113"):
        with pytest.raises(ProductDatabaseReadinessError):
            backup.restore_command(pair, option, invalid)


def test_command_path_failures_are_fixed_and_do_not_echo_paths(tmp_path: Path):
    pair, _ = make_clients(tmp_path)
    missing = tmp_path / "password=secret.cnf"
    for command, database in (
        (backup.dump_command, LEGACY_DATABASE),
        (backup.restore_command, RESTORE_DATABASE),
    ):
        with pytest.raises(backup.ProductDatabaseBackupError) as raised:
            command(pair, missing, database)
        assert str(raised.value) == "mysql client preflight failed"
        assert str(missing) not in repr(raised.value)


def test_connection_preflight_uses_read_only_exact_vector_and_sanitizes_output(tmp_path: Path):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    secret = "password=do-not-leak"
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(argv: list[str], **kwargs: object) -> object:
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="8.4.6\n", stderr=secret)

    assert backup.preflight_client_connection(pair, option, runner) == "8.4.6"
    assert calls[0][0] == [
        str(pair.mysql),
        f"--defaults-extra-file={option}",
        "--protocol=TCP",
        "--batch",
        "--skip-column-names",
        "--execute=SELECT VERSION()",
    ]
    assert calls[0][1] == {"capture_output": True, "text": True, "check": False}
    for result in (
        SimpleNamespace(returncode=1, stdout="8.4.6", stderr=secret),
        SimpleNamespace(returncode=0, stdout="8.0.40\n", stderr=secret),
        SimpleNamespace(returncode=0, stdout="8.4.6\n\n", stderr=secret),
        SimpleNamespace(returncode=0, stdout=f"8.4.6\n{secret}\n", stderr=secret),
    ):
        with pytest.raises(backup.ProductDatabaseBackupError) as raised:
            backup.preflight_client_connection(pair, option, lambda *_a, **_k: result)
        assert str(raised.value) == "mysql connection preflight failed"
        assert secret not in repr(raised.value)


def test_private_option_file_restricts_before_writing_and_erases_password(tmp_path: Path):
    repository = tmp_path / "repo"
    repository.mkdir()
    temporary_root = tmp_path / "private"
    temporary_root.mkdir()
    events: list[str] = []
    secret = 'p\\a"s#s;w=o=r=d'

    def acl(path: Path) -> None:
        events.append("acl")
        assert path.read_bytes() == b""

    config = {"host": "127.0.0.1", "port": 3307, "user": "writer", "password": secret}
    with backup.private_mysql_option_file(
        config, temporary_root, acl, repository_root=repository
    ) as option:
        events.append("body")
        assert option.parent == temporary_root
        assert option.is_absolute()
        content = option.read_text(encoding="utf-8")
        assert content == (
            '[client]\n'
            'host="127.0.0.1"\n'
            'port=3307\n'
            'user="writer"\n'
            'password="p\\\\a\\"s\\#s\\;w\\=o\\=r\\=d"\n'
            'default-character-set="utf8mb4"\n'
        )
        if os.name != "nt":
            assert oct(option.stat().st_mode & 0o777) == "0o600"
    assert events == ["acl", "body"]
    assert not option.exists()
    assert secret not in str(option)


@pytest.mark.parametrize(
    "config",
    (
        {"host": "", "port": 3307, "user": "writer", "password": "x"},
        {"host": "127.0.0.1\nleak", "port": 3307, "user": "writer", "password": "x"},
        {"host": "127.0.0.1", "port": True, "user": "writer", "password": "x"},
        {"host": "127.0.0.1", "port": 0, "user": "writer", "password": "x"},
        {"host": "127.0.0.1", "port": 3307, "user": "writer", "password": "x\x00y"},
    ),
)
def test_private_option_file_rejects_unsafe_config_without_residue(tmp_path: Path, config: dict[str, object]):
    private = tmp_path / "private"
    private.mkdir()
    with pytest.raises(backup.ProductDatabaseBackupError):
        with backup.private_mysql_option_file(config, private, lambda _path: None):
            raise AssertionError("unreachable")
    assert list(private.iterdir()) == []


def test_private_option_file_rechecks_parent_safety_after_acl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    private = tmp_path / "private"
    private.mkdir()
    acl_finished = False
    real_check = backup._is_reparse

    def reparse(path: Path) -> bool:
        return (acl_finished and path == private) or real_check(path)

    def acl(_path: Path) -> None:
        nonlocal acl_finished
        acl_finished = True

    monkeypatch.setattr(backup, "_is_reparse", reparse)
    with pytest.raises(backup.ProductDatabaseBackupError):
        with backup.private_mysql_option_file(
            {"host": "h", "port": 1, "user": "u", "password": "p"},
            private,
            acl,
        ):
            raise AssertionError("unreachable")
    assert list(private.iterdir()) == []


def test_private_option_file_cleans_after_body_and_preserves_flow_control(tmp_path: Path):
    private = tmp_path / "private"
    private.mkdir()
    flow = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt) as raised:
        with backup.private_mysql_option_file(
            {"host": "h", "port": 1, "user": "u", "password": "p"},
            private,
            lambda _path: None,
        ):
            raise flow
    assert raised.value is flow
    assert list(private.iterdir()) == []


def test_private_option_cleanup_does_not_retry_or_swallow_flow_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    private = tmp_path / "private"
    private.mkdir()
    flow = KeyboardInterrupt()
    calls = 0
    def interrupt_once(path: Path, _identity: object) -> bool:
        nonlocal calls
        if path.parent == private:
            calls += 1
            if calls == 1:
                raise flow
        return True

    with pytest.raises(KeyboardInterrupt) as raised:
        with backup.private_mysql_option_file(
            {"host": "h", "port": 1, "user": "u", "password": "p"},
            private,
            lambda _path: None,
            owned_delete=interrupt_once,
        ):
            pass
    assert raised.value is flow
    assert calls == 1


def test_private_option_close_failure_does_not_double_close_owned_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    private = tmp_path / "private"
    private.mkdir()
    real_fdopen = os.fdopen
    close_calls = 0

    class CloseFailure:
        def __init__(self, wrapped: object):
            self.wrapped = wrapped

        def __getattr__(self, name: str) -> object:
            return getattr(self.wrapped, name)

        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1
            self.wrapped.close()
            raise OSError("password=do-not-leak")

    def failing_fdopen(*args: object, **kwargs: object) -> CloseFailure:
        return CloseFailure(real_fdopen(*args, **kwargs))

    monkeypatch.setattr(os, "fdopen", failing_fdopen)
    with pytest.raises(backup.ProductDatabaseBackupError) as raised:
        with backup.private_mysql_option_file(
            {"host": "h", "port": 1, "user": "u", "password": "p"},
            private,
            lambda _path: None,
        ):
            raise AssertionError("unreachable")
    assert str(raised.value) == "private mysql option file failed"
    assert close_calls == 1
    assert list(private.iterdir()) == []


def test_backup_directory_rejects_repo_link_and_rechecks_identity(tmp_path: Path):
    repository = tmp_path / "repo"
    repository.mkdir()
    outside = tmp_path / "backups"
    outside.mkdir()
    seen: list[Path] = []
    assert backup.preflight_backup_directory(outside, repository, seen.append) == outside.resolve()
    assert seen == [outside.resolve()]
    with pytest.raises(backup.ProductDatabaseBackupError):
        backup.preflight_backup_directory(repository, repository, seen.append)
    link = tmp_path / "backup-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        return
    with pytest.raises(backup.ProductDatabaseBackupError):
        backup.preflight_backup_directory(link, repository, seen.append)


def test_create_backup_preflights_before_file_creation_and_publishes_receipt(tmp_path: Path):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    repository = tmp_path / "declared-repository"
    repository.mkdir()
    inventory = make_inventory()
    events: list[str] = []

    def acl(path: Path) -> None:
        events.append("acl")
        if path.is_file():
            assert path.read_bytes() == b""

    def runner(argv: list[str], **kwargs: object) -> object:
        if Path(argv[0]) == pair.mysql:
            events.append("preflight")
            assert list(backup_dir.iterdir()) == []
            return SimpleNamespace(returncode=0, stdout="8.4.6\n", stderr="ignored")
        events.append("dump")
        assert kwargs["stderr"] == backup.subprocess.PIPE
        handle = kwargs["stdout"]
        assert getattr(handle, "mode") == "wb"
        handle.write(b"CREATE TABLE safe(id INT);\n")
        return SimpleNamespace(returncode=0, stderr=b"ignored")

    receipt = backup.create_logical_backup(
        pair=pair,
        option_file=option,
        source_inventory=inventory,
        backup_dir=backup_dir,
        backup_filename="phase7b.sql",
        previous_receipt_hash=HASH_A,
        runner=runner,
        acl_runner=acl,
        repository_root=repository,
    )
    payload = (backup_dir / "phase7b.sql").read_bytes()
    assert events == ["preflight", "acl", "acl", "dump"]
    assert receipt == BackupReceipt(
        state=ReadinessState.BACKUP_CREATED.value,
        previous_receipt_hash=HASH_A,
        source_database=LEGACY_DATABASE,
        backup_filename="phase7b.sql",
        backup_sha256=hashlib.sha256(payload).hexdigest(),
        backup_byte_length=len(payload),
        client_version="8.4.6",
        source_inventory_hash=inventory_hash(inventory),
    )
    assert [path.name for path in backup_dir.iterdir()] == ["phase7b.sql"]
    assert str(backup_dir) not in repr(receipt)


def test_backup_never_overwrites_existing_and_removes_unpublished_temp(tmp_path: Path):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    repository = tmp_path / "declared-repository"
    repository.mkdir()
    final = backup_dir / "phase7b.sql"
    final.write_bytes(b"existing")

    def runner(argv: list[str], **kwargs: object) -> object:
        if Path(argv[0]) == pair.mysql:
            return SimpleNamespace(returncode=0, stdout="8.4.6\n", stderr="secret")
        kwargs["stdout"].write(b"new data")
        return SimpleNamespace(returncode=0, stderr=b"secret")

    with pytest.raises(backup.ProductDatabaseBackupError) as raised:
        backup.create_logical_backup(
            pair,
            option,
            make_inventory(),
            backup_dir,
            "phase7b.sql",
            HASH_A,
            runner,
            lambda _p: None,
            repository_root=repository,
        )
    assert str(raised.value) == "logical backup failed"
    assert final.read_bytes() == b"existing"
    assert [path.name for path in backup_dir.iterdir()] == ["phase7b.sql"]


@pytest.mark.parametrize("mode", ("nonzero", "raise", "empty"))
def test_backup_failure_is_fixed_and_leaves_no_file(tmp_path: Path, mode: str):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    repository = tmp_path / "declared-repository"
    repository.mkdir()
    secret = "password=never-show"

    def runner(argv: list[str], **kwargs: object) -> object:
        if Path(argv[0]) == pair.mysql:
            return SimpleNamespace(returncode=0, stdout="8.4.6\n", stderr=secret)
        if mode == "raise":
            raise RuntimeError(secret)
        if mode != "empty":
            kwargs["stdout"].write(b"partial")
        return SimpleNamespace(returncode=1 if mode == "nonzero" else 0, stderr=secret)

    with pytest.raises(backup.ProductDatabaseBackupError) as raised:
        backup.create_logical_backup(
            pair,
            option,
            make_inventory(),
            backup_dir,
            "phase7b.sql",
            HASH_A,
            runner,
            lambda _p: None,
            repository_root=repository,
        )
    assert str(raised.value) == "logical backup failed"
    assert secret not in repr(raised.value)
    assert list(backup_dir.iterdir()) == []


def test_verify_streams_exactly_64k_and_restore_verifies_before_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    payload = b"x" * (65536 * 2 + 3)
    dump = tmp_path / "backup.sql"
    dump.write_bytes(payload)
    reads: list[int] = []
    real_open = Path.open

    class Reader:
        def __init__(self, handle: object):
            self.handle = handle

        def __enter__(self):
            return self

        def __getattr__(self, name: str) -> object:
            return getattr(self.handle, name)

        def __exit__(self, *args: object):
            return self.handle.__exit__(*args)

        def read(self, size: int) -> bytes:
            reads.append(size)
            return self.handle.read(size)

    def tracking_open(path: Path, *args: object, **kwargs: object):
        handle = real_open(path, *args, **kwargs)
        if path == dump and args and args[0] == "rb":
            handle.__enter__()
            return Reader(handle)
        return handle

    monkeypatch.setattr(Path, "open", tracking_open)
    digest = hashlib.sha256(payload).hexdigest()
    backup.verify_backup_file(dump, digest, len(payload))
    assert reads and set(reads) == {65536}


def test_restore_checks_digest_and_name_before_spawn_and_uses_binary_stdin(tmp_path: Path):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    dump = tmp_path / "backup.sql"
    payload = b"CREATE TABLE t(id INT);\n"
    dump.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(argv: list[str], **kwargs: object) -> object:
        calls.append((argv, kwargs))
        assert getattr(kwargs["stdin"], "mode") == "rb"
        return SimpleNamespace(returncode=0, stderr=b"ignored")

    backup.restore_logical_backup(
        pair, option, dump, digest, len(payload), RESTORE_DATABASE, runner
    )
    assert calls[0][0] == backup.restore_command(pair, option, RESTORE_DATABASE)
    assert calls[0][1]["stdout"] == backup.subprocess.DEVNULL
    assert calls[0][1]["stderr"] == backup.subprocess.PIPE
    for bad_hash, bad_length in (("0" * 64, len(payload)), (digest, len(payload) + 1)):
        calls.clear()
        with pytest.raises(backup.ProductDatabaseBackupError) as raised:
            backup.restore_logical_backup(
                pair, option, dump, bad_hash, bad_length, RESTORE_DATABASE, runner
            )
        assert str(raised.value) == "logical restore failed"
        assert calls == []
    calls.clear()
    with pytest.raises(ProductDatabaseReadinessError):
        backup.restore_logical_backup(pair, option, dump, digest, len(payload), LEGACY_DATABASE, runner)
    assert calls == []


@pytest.mark.parametrize("failure", (SimpleNamespace(returncode=1, stderr=b"secret"), RuntimeError("secret")))
def test_restore_runner_failures_are_fixed(tmp_path: Path, failure: object):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    dump = tmp_path / "backup.sql"
    dump.write_bytes(b"safe")

    def runner(*_args: object, **_kwargs: object) -> object:
        if isinstance(failure, BaseException):
            raise failure
        return failure

    with pytest.raises(backup.ProductDatabaseBackupError) as raised:
        backup.restore_logical_backup(
            pair,
            option,
            dump,
            hashlib.sha256(b"safe").hexdigest(),
            4,
            RESTORE_DATABASE,
            runner,
        )
    assert str(raised.value) == "logical restore failed"
    assert "secret" not in repr(raised.value)


def test_public_errors_suppress_ambient_secret_context(tmp_path: Path):
    sentinel = "password=hidden dsn=mysql://private Provider=secret"
    try:
        raise RuntimeError(sentinel)
    except RuntimeError:
        with pytest.raises(backup.ProductDatabaseBackupError) as raised:
            backup.verify_backup_file(tmp_path / "missing.sql", "0" * 64, 0)
    assert str(raised.value) == "backup verification failed"
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__
    assert sentinel not in repr(raised.value)


def test_client_preflight_rechecks_all_ancestor_identities_after_each_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repository = tmp_path / "repo"
    repository.mkdir()
    pair, clients = make_clients(tmp_path)
    callback_finished = False
    real_reparse = backup._is_reparse

    def changing_reparse(path: Path) -> bool:
        return (callback_finished and path == clients) or real_reparse(path)

    def version(path: Path) -> str:
        nonlocal callback_finished
        callback_finished = True
        return f"{path.stem} Ver 8.4.6"

    monkeypatch.setattr(backup, "_is_reparse", changing_reparse)
    with pytest.raises(backup.ProductDatabaseBackupError) as raised:
        backup.preflight_client_pair(pair.mysqldump, pair.mysql, repository, version)
    assert str(raised.value) == "mysql client preflight failed"


def test_client_preflight_rechecks_after_callback_even_when_output_is_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repository = tmp_path / "repo"
    repository.mkdir()
    pair, _ = make_clients(tmp_path)
    callback_returned = False
    post_callback_checks = 0
    real_reparse = backup._is_reparse

    def observing_reparse(path: Path) -> bool:
        nonlocal post_callback_checks
        if callback_returned:
            post_callback_checks += 1
        return real_reparse(path)

    def invalid_version(_path: Path) -> str:
        nonlocal callback_returned
        callback_returned = True
        return "invalid-output"

    monkeypatch.setattr(backup, "_is_reparse", observing_reparse)
    with pytest.raises(backup.ProductDatabaseBackupError):
        backup.preflight_client_pair(
            pair.mysqldump, pair.mysql, repository, invalid_version
        )
    assert post_callback_checks > 0


def test_private_option_owner_bound_cleanup_leaves_a_replacement_untouched(
    tmp_path: Path,
):
    private = tmp_path / "private"
    private.mkdir()
    delete_calls: list[tuple[Path, object]] = []
    replacement = b"replacement-must-survive"

    def owner_delete(path: Path, identity: object) -> bool:
        delete_calls.append((path, identity))
        # The production primitive compares the open handle identity.  This
        # seam simulates a mismatch and therefore leaves the replacement.
        return True

    with backup.private_mysql_option_file(
        {"host": "h", "port": 1, "user": "u", "password": "p"},
        private,
        lambda _path: None,
        owned_delete=owner_delete,
    ) as option:
        original = private / "original-owned-object"
        option.rename(original)
        option.write_bytes(replacement)
    assert option.read_bytes() == replacement
    assert original.exists()
    assert len(delete_calls) == 1
    assert delete_calls[0][0] == option
    assert delete_calls[0][1] is not None


def test_owner_bound_cleanup_makes_exactly_two_attempts_without_path_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    private = tmp_path / "private"
    private.mkdir()
    calls = 0

    def fail_delete(_path: Path, _identity: object) -> bool:
        nonlocal calls
        calls += 1
        raise OSError("password=not-public")

    monkeypatch.setattr(
        Path,
        "unlink",
        lambda *_args, **_kwargs: pytest.fail("path unlink is not owner-bound"),
    )
    with pytest.raises(backup.ProductDatabaseBackupError) as raised:
        with backup.private_mysql_option_file(
            {"host": "h", "port": 1, "user": "u", "password": "p"},
            private,
            lambda _path: None,
            owned_delete=fail_delete,
        ):
            pass
    assert str(raised.value) == "private mysql option file cleanup failed"
    assert calls == 2
    assert "password" not in repr(raised.value)


def test_public_verify_opens_backup_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    payload = b"verified-once"
    dump = tmp_path / "backup.sql"
    dump.write_bytes(payload)
    real_open = Path.open
    opens = 0

    def counting_open(path: Path, *args: object, **kwargs: object):
        nonlocal opens
        if path == dump:
            opens += 1
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counting_open)
    backup.verify_backup_file(
        dump, hashlib.sha256(payload).hexdigest(), len(payload)
    )
    assert opens == 1


def test_restore_hashes_seeks_and_spawns_with_the_same_single_open_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    dump = tmp_path / "backup.sql"
    original = b"original-verified-backup"
    dump.write_bytes(original)
    real_open = Path.open
    opens = 0
    verified_handle: object | None = None

    def counting_open(path: Path, *args: object, **kwargs: object):
        nonlocal opens
        if path == dump:
            opens += 1
        return real_open(path, *args, **kwargs)

    def observe_after_verification(_path: Path, handle: object) -> None:
        nonlocal verified_handle
        verified_handle = handle

    def runner(_argv: list[str], **kwargs: object) -> object:
        assert kwargs["stdin"] is verified_handle
        assert kwargs["stdin"].read() == original
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(Path, "open", counting_open)
    backup.restore_logical_backup(
        pair,
        option,
        dump,
        hashlib.sha256(original).hexdigest(),
        len(original),
        RESTORE_DATABASE,
        runner,
        after_verification=observe_after_verification,
    )
    assert opens == 1
    assert dump.read_bytes() == original


def test_restore_replacement_immediately_after_verification_fails_fixed(
    tmp_path: Path,
):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    dump = tmp_path / "backup.sql"
    original = b"original-verified-backup"
    dump.write_bytes(original)
    runner_called = False

    def replace_after_verification(path: Path, _handle: object) -> None:
        path.rename(path.with_suffix(".verified"))

    def runner(*_args: object, **_kwargs: object) -> object:
        nonlocal runner_called
        runner_called = True
        raise AssertionError("replacement must not reach runner")

    with pytest.raises(backup.ProductDatabaseBackupError) as raised:
        backup.restore_logical_backup(
            pair,
            option,
            dump,
            hashlib.sha256(original).hexdigest(),
            len(original),
            RESTORE_DATABASE,
            runner,
            after_verification=replace_after_verification,
        )
    assert str(raised.value) == "logical restore failed"
    assert not runner_called


def test_restore_verification_failures_are_logical_restore_failures_before_runner(
    tmp_path: Path,
):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    missing = tmp_path / "password=missing.sql"
    called = False

    def runner(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("unreachable")

    with pytest.raises(backup.ProductDatabaseBackupError) as raised:
        backup.restore_logical_backup(
            pair,
            option,
            missing,
            "0" * 64,
            0,
            RESTORE_DATABASE,
            runner,
        )
    assert str(raised.value) == "logical restore failed"
    assert str(missing) not in repr(raised.value)
    assert not called


def test_restore_read_flow_control_remains_primary_when_close_also_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    dump = tmp_path / "backup.sql"
    dump.write_bytes(b"safe")
    flow = KeyboardInterrupt()
    real_open = Path.open

    class ReadAndCloseFailure:
        def __init__(self, wrapped: object):
            self.wrapped = wrapped

        def __getattr__(self, name: str) -> object:
            return getattr(self.wrapped, name)

        def read(self, _size: int) -> bytes:
            raise flow

        def close(self) -> None:
            self.wrapped.close()
            raise OSError("password=cleanup-secret")

    def failing_open(path: Path, *args: object, **kwargs: object):
        opened = real_open(path, *args, **kwargs)
        if path == dump:
            return ReadAndCloseFailure(opened)
        return opened

    monkeypatch.setattr(Path, "open", failing_open)
    with pytest.raises(BaseExceptionGroup) as raised:
        backup.restore_logical_backup(
            pair,
            option,
            dump,
            hashlib.sha256(b"safe").hexdigest(),
            4,
            RESTORE_DATABASE,
            lambda *_a, **_k: pytest.fail("runner must not start"),
        )
    assert raised.value.exceptions[0] is flow
    assert isinstance(raised.value.exceptions[1], backup.ProductDatabaseBackupError)
    assert "cleanup-secret" not in repr(raised.value)


def test_owned_temp_identity_capture_failure_uses_the_creation_handle_for_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    private = tmp_path / "private"
    private.mkdir()
    deleted_by_handle = 0

    def identity_failure(_descriptor: int) -> object:
        raise OSError("password=identity-secret")

    def delete_descriptor(descriptor: int) -> None:
        nonlocal deleted_by_handle
        deleted_by_handle += 1
        path = next(private.iterdir())
        os.close(descriptor)
        path.unlink()

    monkeypatch.setattr(backup, "_identity_from_fd", identity_failure)
    monkeypatch.setattr(backup, "_delete_owned_descriptor", delete_descriptor)
    with pytest.raises(backup.ProductDatabaseBackupError) as raised:
        with backup.private_mysql_option_file(
            {"host": "h", "port": 1, "user": "u", "password": "p"},
            private,
            lambda _path: None,
        ):
            raise AssertionError("unreachable")
    assert str(raised.value) == "private mysql option file failed"
    assert deleted_by_handle == 1
    assert list(private.iterdir()) == []


def test_non_windows_owner_cleanup_fails_before_creating_any_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    private = tmp_path / "private"
    private.mkdir()
    monkeypatch.setattr(backup.os, "name", "posix")
    with pytest.raises(backup.ProductDatabaseBackupError) as raised:
        with backup.private_mysql_option_file(
            {"host": "h", "port": 1, "user": "u", "password": "p"},
            private,
            lambda _path: None,
        ):
            raise AssertionError("unreachable")
    assert str(raised.value) == "private mysql option file failed"
    assert list(private.iterdir()) == []


@pytest.mark.parametrize("stage", ("open", "acl", "fdopen", "write", "flush", "fsync"))
def test_private_option_setup_failure_matrix_has_no_residue_or_sensitive_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
):
    private = tmp_path / "private"
    private.mkdir()
    secret = "password=stage-secret"
    real_fdopen = os.fdopen

    class StageFailure:
        def __init__(self, wrapped: object):
            self.wrapped = wrapped

        def __getattr__(self, name: str) -> object:
            return getattr(self.wrapped, name)

        def write(self, value: str) -> int:
            if stage == "write":
                raise OSError(secret)
            return self.wrapped.write(value)

        def flush(self) -> None:
            if stage == "flush":
                raise OSError(secret)
            self.wrapped.flush()

        def close(self) -> None:
            self.wrapped.close()

    if stage == "open":
        monkeypatch.setattr(os, "open", lambda *_a, **_k: (_ for _ in ()).throw(OSError(secret)))
    elif stage == "fdopen":
        monkeypatch.setattr(os, "fdopen", lambda *_a, **_k: (_ for _ in ()).throw(OSError(secret)))
    elif stage in ("write", "flush"):
        monkeypatch.setattr(
            os,
            "fdopen",
            lambda *args, **kwargs: StageFailure(real_fdopen(*args, **kwargs)),
        )
    elif stage == "fsync":
        monkeypatch.setattr(os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError(secret)))

    def acl(_path: Path) -> None:
        if stage == "acl":
            raise OSError(secret)

    with pytest.raises(backup.ProductDatabaseBackupError) as raised:
        with backup.private_mysql_option_file(
            {"host": "h", "port": 1, "user": "u", "password": "p"},
            private,
            acl,
        ):
            raise AssertionError("unreachable")
    assert str(raised.value) == "private mysql option file failed"
    assert secret not in repr(raised.value)
    assert list(private.iterdir()) == []


def test_private_option_body_primary_precedes_two_cleanup_failures(tmp_path: Path):
    private = tmp_path / "private"
    private.mkdir()
    body = RuntimeError("body-primary")
    attempts = 0

    def cleanup_failure(_path: Path, _identity: object) -> bool:
        nonlocal attempts
        attempts += 1
        raise OSError("password=cleanup-secret")

    with pytest.raises(BaseExceptionGroup) as raised:
        with backup.private_mysql_option_file(
            {"host": "h", "port": 1, "user": "u", "password": "p"},
            private,
            lambda _path: None,
            owned_delete=cleanup_failure,
        ):
            raise body
    assert raised.value.exceptions[0] is body
    assert isinstance(raised.value.exceptions[1], backup.ProductDatabaseBackupError)
    assert attempts == 2
    assert "cleanup-secret" not in repr(raised.value)


@pytest.mark.parametrize("stage", ("acl", "write", "flush", "fsync", "close"))
def test_private_option_setup_flow_control_matrix_is_preserved_and_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
):
    private = tmp_path / "private"
    private.mkdir()
    flow = KeyboardInterrupt()
    real_fdopen = os.fdopen

    class FlowHandle:
        def __init__(self, wrapped: object):
            self.wrapped = wrapped

        def __getattr__(self, name: str) -> object:
            return getattr(self.wrapped, name)

        def write(self, value: str) -> int:
            if stage == "write":
                raise flow
            return self.wrapped.write(value)

        def flush(self) -> None:
            if stage == "flush":
                raise flow
            self.wrapped.flush()

        def close(self) -> None:
            self.wrapped.close()
            if stage == "close":
                raise flow

    if stage in ("write", "flush", "close"):
        monkeypatch.setattr(
            os,
            "fdopen",
            lambda *args, **kwargs: FlowHandle(real_fdopen(*args, **kwargs)),
        )
    elif stage == "fsync":
        monkeypatch.setattr(os, "fsync", lambda _fd: (_ for _ in ()).throw(flow))

    def acl(_path: Path) -> None:
        if stage == "acl":
            raise flow

    with pytest.raises(KeyboardInterrupt) as raised:
        with backup.private_mysql_option_file(
            {"host": "h", "port": 1, "user": "u", "password": "p"},
            private,
            acl,
        ):
            raise AssertionError("unreachable")
    assert raised.value is flow
    assert list(private.iterdir()) == []


def test_owner_delete_window_replacement_is_left_untouched(tmp_path: Path):
    private = tmp_path / "private"
    private.mkdir()
    replacement = b"replacement-at-delete-window"

    def replace_inside_delete(path: Path, _identity: object) -> bool:
        path.rename(path.with_suffix(".owned"))
        path.write_bytes(replacement)
        return True

    with backup.private_mysql_option_file(
        {"host": "h", "port": 1, "user": "u", "password": "p"},
        private,
        lambda _path: None,
        owned_delete=replace_inside_delete,
    ) as option:
        pass
    assert option.read_bytes() == replacement


def test_owner_bound_cleanup_treats_an_already_missing_original_as_complete(
    tmp_path: Path,
):
    private = tmp_path / "private"
    private.mkdir()
    with backup.private_mysql_option_file(
        {"host": "h", "port": 1, "user": "u", "password": "p"},
        private,
        lambda _path: None,
    ) as option:
        option.unlink()
    assert list(private.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows handle-bound deletion")
def test_windows_owner_bound_cleanup_does_not_delete_a_real_path_replacement(
    tmp_path: Path,
):
    private = tmp_path / "private"
    private.mkdir()
    replacement = b"real-replacement"
    with backup.private_mysql_option_file(
        {"host": "h", "port": 1, "user": "u", "password": "p"},
        private,
        lambda _path: None,
    ) as option:
        option.rename(option.with_suffix(".owned"))
        option.write_bytes(replacement)
    assert option.read_bytes() == replacement


@pytest.mark.parametrize(
    "stage", ("create", "acl", "fdopen", "runner", "flush", "fsync", "close", "hash")
)
def test_dump_stage_failure_matrix_is_fixed_and_removes_unpublished_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    directory = tmp_path / "backups"
    directory.mkdir()
    repository = tmp_path / "repo"
    repository.mkdir()
    secret = "password=dump-stage-secret"
    real_fdopen = os.fdopen
    acl_calls = 0

    class BinaryStageFailure:
        def __init__(self, wrapped: object):
            self.wrapped = wrapped
            self.mode = "wb"

        def __getattr__(self, name: str) -> object:
            return getattr(self.wrapped, name)

        def write(self, value: bytes) -> int:
            return self.wrapped.write(value)

        def flush(self) -> None:
            if stage == "flush":
                raise OSError(secret)
            self.wrapped.flush()

        def close(self) -> None:
            self.wrapped.close()
            if stage == "close":
                raise OSError(secret)

    if stage == "create":
        monkeypatch.setattr(os, "open", lambda *_a, **_k: (_ for _ in ()).throw(OSError(secret)))
    elif stage == "fdopen":
        monkeypatch.setattr(os, "fdopen", lambda *_a, **_k: (_ for _ in ()).throw(OSError(secret)))
    elif stage in ("flush", "close"):
        monkeypatch.setattr(
            os,
            "fdopen",
            lambda *args, **kwargs: BinaryStageFailure(real_fdopen(*args, **kwargs)),
        )
    elif stage == "fsync":
        monkeypatch.setattr(os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError(secret)))
    elif stage == "hash":
        monkeypatch.setattr(
            backup,
            "_hash_stream",
            lambda _path: (_ for _ in ()).throw(OSError(secret)),
        )

    def acl(_path: Path) -> None:
        nonlocal acl_calls
        acl_calls += 1
        if stage == "acl" and acl_calls == 2:
            raise OSError(secret)

    def runner(argv: list[str], **kwargs: object) -> object:
        if Path(argv[0]) == pair.mysql:
            return SimpleNamespace(returncode=0, stdout="8.4.6\n", stderr=secret)
        if stage == "runner":
            raise OSError(secret)
        kwargs["stdout"].write(b"safe dump")
        return SimpleNamespace(returncode=0, stderr=secret)

    with pytest.raises(backup.ProductDatabaseBackupError) as raised:
        backup.create_logical_backup(
            pair,
            option,
            make_inventory(),
            directory,
            "phase7b.sql",
            HASH_A,
            runner,
            acl,
            repository_root=repository,
        )
    assert str(raised.value) == "logical backup failed"
    assert secret not in repr(raised.value)
    assert list(directory.iterdir()) == []


def test_published_backup_survives_two_owned_temp_cleanup_failures(tmp_path: Path):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    directory = tmp_path / "backups"
    directory.mkdir()
    repository = tmp_path / "repo"
    repository.mkdir()
    attempts = 0

    def runner(argv: list[str], **kwargs: object) -> object:
        if Path(argv[0]) == pair.mysql:
            return SimpleNamespace(returncode=0, stdout="8.4.6\n", stderr="")
        kwargs["stdout"].write(b"published payload")
        return SimpleNamespace(returncode=0, stderr=b"")

    def fail_cleanup(_path: Path, _identity: object) -> bool:
        nonlocal attempts
        attempts += 1
        raise OSError("password=cleanup-secret")

    with pytest.raises(backup.ProductDatabaseBackupError) as raised:
        backup.create_logical_backup(
            pair,
            option,
            make_inventory(),
            directory,
            "phase7b.sql",
            HASH_A,
            runner,
            lambda _path: None,
            repository_root=repository,
            owned_delete=fail_cleanup,
        )
    assert str(raised.value) == "logical backup cleanup failed"
    assert (directory / "phase7b.sql").read_bytes() == b"published payload"
    assert attempts == 2


def test_dump_owner_cleanup_window_never_removes_replacement_or_publication(
    tmp_path: Path,
):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    directory = tmp_path / "backups"
    directory.mkdir()
    repository = tmp_path / "repo"
    repository.mkdir()
    replacement = b"replacement-temp"

    def runner(argv: list[str], **kwargs: object) -> object:
        if Path(argv[0]) == pair.mysql:
            return SimpleNamespace(returncode=0, stdout="8.4.6\n", stderr="")
        kwargs["stdout"].write(b"published-original")
        return SimpleNamespace(returncode=0, stderr=b"")

    def replace_inside_delete(path: Path, _identity: object) -> bool:
        path.rename(path.with_suffix(".owned"))
        path.write_bytes(replacement)
        return True

    receipt = backup.create_logical_backup(
        pair,
        option,
        make_inventory(),
        directory,
        "phase7b.sql",
        HASH_A,
        runner,
        lambda _path: None,
        repository_root=repository,
        owned_delete=replace_inside_delete,
    )
    assert receipt.backup_byte_length == len(b"published-original")
    assert (directory / "phase7b.sql").read_bytes() == b"published-original"
    replacements = [path for path in directory.iterdir() if path.name.startswith(".phase7b-backup-")]
    assert any(path.read_bytes() == replacement for path in replacements)


def test_dump_runner_flow_control_is_preserved_and_temp_is_removed(tmp_path: Path):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    directory = tmp_path / "backups"
    directory.mkdir()
    repository = tmp_path / "repo"
    repository.mkdir()
    flow = KeyboardInterrupt()

    def runner(argv: list[str], **_kwargs: object) -> object:
        if Path(argv[0]) == pair.mysql:
            return SimpleNamespace(returncode=0, stdout="8.4.6\n", stderr="")
        raise flow

    with pytest.raises(KeyboardInterrupt) as raised:
        backup.create_logical_backup(
            pair,
            option,
            make_inventory(),
            directory,
            "phase7b.sql",
            HASH_A,
            runner,
            lambda _path: None,
            repository_root=repository,
        )
    assert raised.value is flow
    assert list(directory.iterdir()) == []


def test_published_backup_is_retained_when_receipt_construction_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    directory = tmp_path / "backups"
    directory.mkdir()
    repository = tmp_path / "repo"
    repository.mkdir()
    real_receipt = BackupReceipt
    receipt_calls = 0

    def receipt_failure(**kwargs: object) -> BackupReceipt:
        nonlocal receipt_calls
        receipt_calls += 1
        if receipt_calls == 2:
            raise OSError("password=receipt-secret")
        return real_receipt(**kwargs)  # type: ignore[arg-type]

    def runner(argv: list[str], **kwargs: object) -> object:
        if Path(argv[0]) == pair.mysql:
            return SimpleNamespace(returncode=0, stdout="8.4.6\n", stderr="")
        kwargs["stdout"].write(b"published-before-receipt")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(backup, "BackupReceipt", receipt_failure)
    with pytest.raises(backup.ProductDatabaseBackupError) as raised:
        backup.create_logical_backup(
            pair,
            option,
            make_inventory(),
            directory,
            "phase7b.sql",
            HASH_A,
            runner,
            lambda _path: None,
            repository_root=repository,
        )
    assert str(raised.value) == "logical backup failed"
    assert (directory / "phase7b.sql").read_bytes() == b"published-before-receipt"


@pytest.mark.parametrize("stage", ("open", "read", "seek", "runner", "close"))
def test_restore_stage_failure_matrix_is_fixed_and_never_leaks_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    dump = tmp_path / "backup.sql"
    payload = b"verified restore"
    dump.write_bytes(payload)
    secret = "password=restore-stage-secret"
    real_open = Path.open
    runner_calls = 0

    class RestoreStageFailure:
        def __init__(self, wrapped: object):
            self.wrapped = wrapped

        def __getattr__(self, name: str) -> object:
            return getattr(self.wrapped, name)

        def read(self, size: int) -> bytes:
            if stage == "read":
                raise OSError(secret)
            return self.wrapped.read(size)

        def seek(self, offset: int) -> int:
            if stage == "seek":
                raise OSError(secret)
            return self.wrapped.seek(offset)

        def close(self) -> None:
            self.wrapped.close()
            if stage == "close":
                raise OSError(secret)

    def staged_open(path: Path, *args: object, **kwargs: object):
        if path == dump and stage == "open":
            raise OSError(secret)
        opened = real_open(path, *args, **kwargs)
        if path == dump:
            return RestoreStageFailure(opened)
        return opened

    def runner(*_args: object, **_kwargs: object) -> object:
        nonlocal runner_calls
        runner_calls += 1
        if stage == "runner":
            raise OSError(secret)
        return SimpleNamespace(returncode=0, stderr=secret)

    monkeypatch.setattr(Path, "open", staged_open)
    with pytest.raises(backup.ProductDatabaseBackupError) as raised:
        backup.restore_logical_backup(
            pair,
            option,
            dump,
            hashlib.sha256(payload).hexdigest(),
            len(payload),
            RESTORE_DATABASE,
            runner,
        )
    assert str(raised.value) == "logical restore failed"
    assert secret not in repr(raised.value)
    assert runner_calls == (1 if stage in ("runner", "close") else 0)


@pytest.mark.parametrize("stage", ("read", "seek", "runner", "close"))
def test_restore_flow_control_matrix_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
):
    pair, _ = make_clients(tmp_path)
    option = make_option(tmp_path)
    dump = tmp_path / "backup.sql"
    payload = b"verified restore"
    dump.write_bytes(payload)
    flow = KeyboardInterrupt()
    real_open = Path.open

    class RestoreFlow:
        def __init__(self, wrapped: object):
            self.wrapped = wrapped

        def __getattr__(self, name: str) -> object:
            return getattr(self.wrapped, name)

        def read(self, size: int) -> bytes:
            if stage == "read":
                raise flow
            return self.wrapped.read(size)

        def seek(self, offset: int) -> int:
            if stage == "seek":
                raise flow
            return self.wrapped.seek(offset)

        def close(self) -> None:
            self.wrapped.close()
            if stage == "close":
                raise flow

    def flow_open(path: Path, *args: object, **kwargs: object):
        opened = real_open(path, *args, **kwargs)
        return RestoreFlow(opened) if path == dump else opened

    def runner(*_args: object, **_kwargs: object) -> object:
        if stage == "runner":
            raise flow
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(Path, "open", flow_open)
    with pytest.raises(KeyboardInterrupt) as raised:
        backup.restore_logical_backup(
            pair,
            option,
            dump,
            hashlib.sha256(payload).hexdigest(),
            len(payload),
            RESTORE_DATABASE,
            runner,
        )
    assert raised.value is flow
