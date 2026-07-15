import hashlib
import inspect
import json
import unittest

import httpx

from backend.control_plane.draft_write_errors import DraftWriteError
from backend.control_plane.restricted_jcs import canonical_sha256
from backend.routers.control_plane_draft_writes import create_router
import backend.routers.control_plane_draft_writes as router_module
from fakes import ExpectedExecution, FakeConnection, FakePool
from test_app import create_disposable_test_app


TOKEN = "route123"
SCHEMA = "novel_creator_control_plane_disposable_" + TOKEN
PATH = "/api/projects/project-1/draft-write-batches"


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def payload():
    return {
        "manifestVersion": 1,
        "purpose": "draft_only_pair",
        "projectId": "project-1",
        "writes": [
            {
                "chapterId": "chapter-1",
                "chapterNum": 1,
                "sourceVersionId": "source-1",
                "expectedSourceContentSha256": sha("source-one"),
                "title": "One",
                "content": "candidate-one",
                "contentSha256": sha("candidate-one"),
                "promptBrief": "Prompt one",
            },
            {
                "chapterId": "chapter-2",
                "chapterNum": 2,
                "sourceVersionId": "source-2",
                "expectedSourceContentSha256": sha("source-two"),
                "title": "Two",
                "content": "candidate-two",
                "contentSha256": sha("candidate-two"),
                "promptBrief": "Prompt two",
            },
        ],
    }


def uuids():
    values = iter(["batch-1", "candidate-1", "candidate-2"])
    return lambda: next(values)


def create_app(pool, *, environ=None, commit_operation=None):
    return create_disposable_test_app(
        pool=pool,
        expected_schema=SCHEMA,
        run_token=TOKEN,
        environ={"CONTROL_PLANE_DRAFT_WRITES_ENABLED": "true"} if environ is None else environ,
        uuid_factory=uuids(),
        clock_ms=lambda: 1700000000000,
        commit_operation=commit_operation,
    )


async def post(app, *, content: bytes, headers=()):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(PATH, content=content, headers=list(headers))


async def post_stream_chunks(app, *, chunks, headers=()):
    pending = list(chunks)
    receive_calls = 0
    sent = []

    async def receive():
        nonlocal receive_calls
        receive_calls += 1
        if not pending:
            return {"type": "http.disconnect"}
        body = pending.pop(0)
        return {
            "type": "http.request",
            "body": body,
            "more_body": bool(pending),
        }

    async def send(message):
        sent.append(message)

    raw_headers = [
        (name.lower().encode("ascii"), value.encode("ascii"))
        for name, value in headers
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": PATH,
        "raw_path": PATH.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": raw_headers,
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }
    await app(scope, receive, send)
    status = next(message["status"] for message in sent if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    )
    return status, json.loads(body), receive_calls, len(pending)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def valid_headers(value):
    return [
        ("Idempotency-Key", "Route-Key"),
        ("X-Manifest-SHA256", canonical_sha256(value)),
        ("Content-Type", "application/json"),
    ]


class DraftWriteRouterTest(unittest.IsolatedAsyncioTestCase):
    async def test_route_is_unmounted_unless_passed_mapping_value_is_exact_true(self):
        for environ in [
            {},
            {"CONTROL_PLANE_DRAFT_WRITES_ENABLED": "false"},
            {"CONTROL_PLANE_DRAFT_WRITES_ENABLED": "1"},
            {"CONTROL_PLANE_DRAFT_WRITES_ENABLED": "True"},
            {"CONTROL_PLANE_DRAFT_WRITES_ENABLED": "TRUE"},
        ]:
            with self.subTest(environ=environ):
                pool = FakePool([])
                response = await post(
                    create_app(pool, environ=environ),
                    content=b"{}",
                )
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json(), {"detail": "Not Found"})
                self.assertEqual(pool.acquire_calls, 0)

    async def test_invalid_raw_manifest_headers_hashes_and_identity_never_acquire_pool(self):
        base = payload()
        unknown = payload()
        unknown["writes"][0]["model"] = "forbidden"
        route_conflict = payload()
        route_conflict["projectId"] = "other-project"
        candidate_mismatch = payload()
        candidate_mismatch["writes"][0]["contentSha256"] = "0" * 64

        cases = [
            (
                "invalid json",
                b"{",
                [("Idempotency-Key", "Key"), ("X-Manifest-SHA256", "0" * 64)],
                400,
                "invalid_manifest",
            ),
            (
                "duplicate json key",
                b'{"manifestVersion":1,"manifestVersion":1}',
                [("Idempotency-Key", "Key"), ("X-Manifest-SHA256", "0" * 64)],
                400,
                "duplicate_json_key",
            ),
            ("unknown field", encoded(unknown), valid_headers(unknown), 400, "unknown_field"),
            (
                "missing idempotency",
                encoded(base),
                [("X-Manifest-SHA256", canonical_sha256(base))],
                400,
                "invalid_idempotency_key",
            ),
            (
                "duplicate idempotency",
                encoded(base),
                [
                    ("Idempotency-Key", "Key-1"),
                    ("Idempotency-Key", "Key-2"),
                    ("X-Manifest-SHA256", canonical_sha256(base)),
                ],
                400,
                "invalid_idempotency_key",
            ),
            (
                "invalid idempotency bytes",
                encoded(base),
                [("Idempotency-Key", "has space"), ("X-Manifest-SHA256", canonical_sha256(base))],
                400,
                "invalid_idempotency_key",
            ),
            (
                "missing manifest hash",
                encoded(base),
                [("Idempotency-Key", "Key")],
                400,
                "invalid_manifest_hash",
            ),
            (
                "duplicate manifest hash",
                encoded(base),
                [
                    ("Idempotency-Key", "Key"),
                    ("X-Manifest-SHA256", canonical_sha256(base)),
                    ("X-Manifest-SHA256", canonical_sha256(base)),
                ],
                400,
                "invalid_manifest_hash",
            ),
            (
                "syntactically invalid manifest hash",
                encoded(base),
                [("Idempotency-Key", "Key"), ("X-Manifest-SHA256", "A" * 64)],
                400,
                "invalid_manifest_hash",
            ),
            (
                "manifest hash mismatch",
                encoded(base),
                [("Idempotency-Key", "Key"), ("X-Manifest-SHA256", "0" * 64)],
                400,
                "invalid_manifest_hash",
            ),
            (
                "route body mismatch",
                encoded(route_conflict),
                valid_headers(route_conflict),
                409,
                "project_identity_conflict",
            ),
            (
                "candidate hash mismatch",
                encoded(candidate_mismatch),
                valid_headers(candidate_mismatch),
                422,
                "candidate_content_hash_mismatch",
            ),
        ]

        for name, body, headers, status, code in cases:
            with self.subTest(name):
                pool = FakePool([])
                response = await post(create_app(pool), content=body, headers=headers)
                self.assertEqual(response.status_code, status, response.text)
                detail = response.json()["detail"]
                self.assertEqual(detail["code"], code)
                self.assertEqual(set(detail), {"code", "message", "retryable"})
                self.assertIsInstance(detail["message"], str)
                self.assertNotIn("candidate-one", detail["message"])
                self.assertEqual(pool.acquire_calls, 0)

    async def test_exact_true_mounts_and_returns_exact_result_wire_fields(self):
        executions = [
            ExpectedExecution("FROM projects", rows=[{"id": "project-1"}]),
            ExpectedExecution("INSERT INTO draft_write_batches", rowcount=1),
            ExpectedExecution(
                "FROM chapters",
                rows=[
                    {"id": "chapter-1", "project_id": "project-1", "chapter_num": 1, "status": "drafting", "final_version_id": None},
                    {"id": "chapter-2", "project_id": "project-1", "chapter_num": 2, "status": "drafting", "final_version_id": None},
                ],
            ),
            ExpectedExecution(
                "FROM chapter_versions",
                rows=[
                    {"id": "source-1", "project_id": "project-1", "chapter_id": "chapter-1", "content": "source-one"},
                    {"id": "source-2", "project_id": "project-1", "chapter_id": "chapter-2", "content": "source-two"},
                ],
            ),
            ExpectedExecution("INSERT INTO chapter_versions", rowcount=1),
            ExpectedExecution("INSERT INTO chapter_versions", rowcount=1),
            ExpectedExecution("UPDATE draft_write_batches", rowcount=1),
        ]
        conn = FakeConnection(database_name=SCHEMA, executions=executions)
        value = payload()
        response = await post(
            create_app(FakePool([conn])),
            content=encoded(value),
            headers=valid_headers(value),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {
                "batchId": "batch-1",
                "projectId": "project-1",
                "manifestSha256": canonical_sha256(value),
                "candidateVersionIds": ["candidate-1", "candidate-2"],
                "committedAt": 1700000000000,
            },
        )

    async def test_missing_or_invalid_headers_do_not_consume_body_stream(self):
        syntactic_hash = "0" * 64
        cases = [
            ("missing both", []),
            ("invalid hash", [("Idempotency-Key", "Key"), ("X-Manifest-SHA256", "A" * 64)]),
            ("invalid idempotency", [("Idempotency-Key", "has space"), ("X-Manifest-SHA256", syntactic_hash)]),
            (
                "duplicate hash",
                [
                    ("Idempotency-Key", "Key"),
                    ("X-Manifest-SHA256", syntactic_hash),
                    ("X-Manifest-SHA256", syntactic_hash),
                ],
            ),
        ]
        for name, headers in cases:
            with self.subTest(name):
                pool = FakePool([])
                status, body, receive_calls, pending = await post_stream_chunks(
                    create_app(pool),
                    chunks=[b"body-must-not-be-consumed"],
                    headers=headers,
                )
                self.assertEqual(status, 400)
                self.assertEqual(set(body["detail"]), {"code", "message", "retryable"})
                self.assertEqual(receive_calls, 0)
                self.assertEqual(pending, 1)
                self.assertEqual(pool.acquire_calls, 0)

    async def test_oversize_stream_stops_at_cumulative_byte_cap(self):
        limit = router_module.MAX_MANIFEST_BYTES
        chunks = [
            b"x" * (limit // 2),
            b"y" * (limit // 2),
            b"z",
            b"must-not-be-consumed",
        ]
        pool = FakePool([])
        status, body, receive_calls, pending = await post_stream_chunks(
            create_app(pool),
            chunks=chunks,
            headers=[
                ("Idempotency-Key", "Key"),
                ("X-Manifest-SHA256", "0" * 64),
            ],
        )
        self.assertEqual(status, 400)
        self.assertEqual(
            body,
            {
                "detail": {
                    "code": "invalid_manifest",
                    "message": "Manifest exceeds the maximum allowed size.",
                    "retryable": False,
                }
            },
        )
        self.assertEqual(receive_calls, 3)
        self.assertEqual(pending, 1)
        self.assertEqual(pool.acquire_calls, 0)

    async def test_deeply_nested_json_returns_safe_400_before_pool_acquire(self):
        deep_body = b"[" * 2000 + b"0" + b"]" * 2000
        pool = FakePool([])
        response = await post(
            create_app(pool),
            content=deep_body,
            headers=[
                ("Idempotency-Key", "Key"),
                ("X-Manifest-SHA256", "0" * 64),
            ],
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "detail": {
                    "code": "invalid_manifest",
                    "message": "Manifest is invalid.",
                    "retryable": False,
                }
            },
        )
        self.assertEqual(pool.acquire_calls, 0)

    async def test_domain_errors_are_mapped_to_safe_detail_only(self):
        from fastapi import FastAPI

        class RejectingService:
            async def submit(self, _command):
                raise DraftWriteError(
                    code="chapter_finalized",
                    http_status=409,
                    message="Chapter is already finalized.",
                )

        app = FastAPI()
        app.include_router(create_router(service=RejectingService()), prefix="/api")
        value = payload()
        response = await post(app, content=encoded(value), headers=valid_headers(value))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {
                "detail": {
                    "code": "chapter_finalized",
                    "message": "Chapter is already finalized.",
                    "retryable": False,
                }
            },
        )

    def test_router_and_test_app_do_not_import_product_globals_or_process_environment(self):
        source = inspect.getsource(router_module)
        app_source = inspect.getsource(create_disposable_test_app)
        combined = source + app_source
        for forbidden in ["backend.main", "from database", "import database", "MYSQL_CONFIG", "os.environ", "get_pool"]:
            self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
