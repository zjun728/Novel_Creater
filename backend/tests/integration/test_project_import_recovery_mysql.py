from contextlib import asynccontextmanager
from hashlib import sha256

import pytest

from backend.security.paths import managed_corpus_blob_path, managed_corpus_storage_key
from backend.domain.json_contracts import canonical_json
from backend.services.project_imports import STAGING_DIRECTORY, STAGING_MANIFEST, reconcile_project_import_staging
from backend.tests.support.disposable_mysql import transaction_factory_for


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_recovery_deletes_only_terminal_command_created_unreferenced_blob(
    disposable_mysql, tmp_path,
):
    managed = tmp_path / "managed"
    managed.mkdir()
    staging_parent = managed / STAGING_DIRECTORY
    staging_parent.mkdir()
    blobs = ((b"remove", False), (b"preserve", True))

    for index, (data, referenced) in enumerate(blobs, start=1):
        command = f"10000000-0000-4000-8000-{index:012d}"
        digest = sha256(data).hexdigest()
        target = managed_corpus_blob_path(managed, digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        root = staging_parent / command
        root.mkdir()
        (root / STAGING_MANIFEST).write_text(canonical_json({
            "commandId": command,
            "idMapHash": "a" * 64,
            "blobs": [{
                "contentHash": digest,
                "byteLength": len(data),
                "storageKey": managed_corpus_storage_key(digest),
                "created": True,
            }],
        }), encoding="utf-8")
        await disposable_mysql.session.execute(
            """INSERT INTO project_package_import_commands
               (id,idempotency_key,request_fingerprint,package_hash,manifest_hash,
                package_version,target_project_id,normalized_title,status,phase,
                owner_token,lease_expires_at,staging_manifest_json,public_error_code,
                created_at,updated_at,completed_at)
               VALUES (%s,%s,%s,%s,%s,1,%s,'Imported','succeeded','succeeded',
                       NULL,NULL,%s,NULL,1,1,1)""",
            (command, f"recovery_key_{index:02d}".ljust(16, "x"), "b" * 64,
             "c" * 64, "d" * 64, f"20000000-0000-4000-8000-{index:012d}",
             (root / STAGING_MANIFEST).read_text("utf-8")),
        )
        if referenced:
            await disposable_mysql.session.execute(
                "INSERT INTO corpus_blobs (content_hash,byte_length,storage_key,created_at) VALUES (%s,%s,%s,1)",
                (digest, len(data), managed_corpus_storage_key(digest)),
            )

    @asynccontextmanager
    async def connect():
        yield disposable_mysql.session

    assert await reconcile_project_import_staging(
        managed_corpus_root=managed, connection_factory=connect,
        transaction_factory=transaction_factory_for(disposable_mysql.connection_config),
        now_ms=2,
    ) == 2
    assert not managed_corpus_blob_path(managed, sha256(b"remove").hexdigest()).exists()
    assert managed_corpus_blob_path(managed, sha256(b"preserve").hexdigest()).read_bytes() == b"preserve"
    assert list(staging_parent.iterdir()) == []
