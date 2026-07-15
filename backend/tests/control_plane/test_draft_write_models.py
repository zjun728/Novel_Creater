from dataclasses import FrozenInstanceError
import hashlib
import unittest

from backend.control_plane.draft_write_errors import DraftWriteError
from backend.control_plane.draft_write_models import (
    DraftWriteResult,
    parse_manifest_bytes,
    parse_manifest_value,
    to_command,
)
from backend.control_plane.restricted_jcs import canonical_sha256


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def valid_payload() -> dict[str, object]:
    first_source_hash = content_hash("source-one")
    second_source_hash = content_hash("source-two")
    return {
        "manifestVersion": 1,
        "purpose": "draft_only_pair",
        "projectId": "project-1",
        "writes": [
            {
                "chapterId": "chapter-1",
                "chapterNum": 1,
                "sourceVersionId": "source-1",
                "expectedSourceContentSha256": first_source_hash,
                "title": "First",
                "content": "candidate-one",
                "contentSha256": content_hash("candidate-one"),
                "promptBrief": "Prompt one",
            },
            {
                "chapterId": "chapter-2",
                "chapterNum": 2,
                "sourceVersionId": "source-2",
                "expectedSourceContentSha256": second_source_hash,
                "title": "Second",
                "content": "candidate-two",
                "contentSha256": content_hash("candidate-two"),
                "promptBrief": "Prompt two",
            },
        ],
    }


def command_from(payload: dict[str, object], **overrides):
    options = {
        "route_project_id": payload["projectId"],
        "request": parse_manifest_value(payload),
        "idempotency_key": "Key-1",
        "manifest_sha256": canonical_sha256(payload),
    }
    options.update(overrides)
    return to_command(**options)


class DraftWriteModelsTest(unittest.TestCase):
    def assert_error(self, code, mutate, *, status=400):
        payload = valid_payload()
        mutate(payload)
        with self.assertRaises(DraftWriteError) as caught:
            parse_manifest_value(payload)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.http_status, status)

    def test_rejects_duplicate_raw_json_keys(self):
        with self.assertRaises(DraftWriteError) as caught:
            parse_manifest_bytes(b'{"manifestVersion":1,"manifestVersion":1}')
        self.assertEqual(caught.exception.code, "duplicate_json_key")

    def test_rejects_unknown_root_and_write_fields(self):
        self.assert_error("unknown_field", lambda p: p.update({"model": "forbidden"}))
        self.assert_error(
            "unknown_field",
            lambda p: p["writes"][0].update({"model": "forbidden"}),
        )

    def test_requires_fixed_manifest_version_and_purpose(self):
        for field, value in [
            ("manifestVersion", 2),
            ("manifestVersion", True),
            ("manifestVersion", "1"),
            ("purpose", "finalize"),
        ]:
            with self.subTest(field=field, value=value):
                self.assert_error("invalid_manifest", lambda p, f=field, v=value: p.update({f: v}))

    def test_requires_exactly_two_distinct_writes(self):
        self.assert_error("invalid_write_count", lambda p: p.update({"writes": p["writes"][:1]}))
        self.assert_error("invalid_write_count", lambda p: p.update({"writes": p["writes"] + [p["writes"][0]]}))
        self.assert_error(
            "duplicate_chapter_id",
            lambda p: p["writes"][1].update({"chapterId": p["writes"][0]["chapterId"]}),
        )

    def test_requires_nonempty_ids_and_strict_positive_signed_chapter_numbers(self):
        for field in ["chapterId", "sourceVersionId"]:
            self.assert_error("invalid_manifest", lambda p, f=field: p["writes"][0].update({f: ""}))
        self.assert_error("invalid_manifest", lambda p: p.update({"projectId": ""}))
        for value in [0, -1, True, "1", 2147483648]:
            with self.subTest(chapterNum=value):
                self.assert_error("invalid_manifest", lambda p, v=value: p["writes"][0].update({"chapterNum": v}))

    def test_requires_lowercase_sha256_fields(self):
        for field in ["expectedSourceContentSha256", "contentSha256"]:
            for value in ["0" * 63, "G" * 64, "A" * 64, 1]:
                with self.subTest(field=field, value=value):
                    self.assert_error("invalid_hash", lambda p, f=field, v=value: p["writes"][0].update({f: v}))

    def test_enforces_title_prompt_and_content_lengths(self):
        cases = [
            ("title", ""),
            ("title", "x" * 201),
            ("promptBrief", ""),
            ("promptBrief", "x" * 501),
            ("content", ""),
        ]
        for field, value in cases:
            with self.subTest(field=field, length=len(value)):
                self.assert_error("invalid_manifest", lambda p, f=field, v=value: p["writes"][0].update({f: v}))

    def test_rejects_route_identity_conflict(self):
        payload = valid_payload()
        with self.assertRaises(DraftWriteError) as caught:
            command_from(payload, route_project_id="project-other")
        self.assertEqual(caught.exception.code, "project_identity_conflict")
        self.assertEqual(caught.exception.http_status, 409)

    def test_rejects_invalid_idempotency_key_and_manifest_hash(self):
        payload = valid_payload()
        for key in ["", "has space", "\t", "x" * 121, "é"]:
            with self.subTest(key=repr(key)):
                with self.assertRaises(DraftWriteError) as caught:
                    command_from(payload, idempotency_key=key)
                self.assertEqual(caught.exception.code, "invalid_idempotency_key")
        with self.assertRaises(DraftWriteError) as caught:
            command_from(payload, manifest_sha256="A" * 64)
        self.assertEqual(caught.exception.code, "invalid_manifest_hash")

    def test_candidate_hash_mismatch_is_422(self):
        payload = valid_payload()
        payload["writes"][0]["contentSha256"] = "0" * 64
        with self.assertRaises(DraftWriteError) as caught:
            command_from(payload)
        self.assertEqual(caught.exception.code, "candidate_content_hash_mismatch")
        self.assertEqual(caught.exception.http_status, 422)

    def test_command_and_result_are_frozen_and_wire_fields_are_exact(self):
        command = command_from(valid_payload())
        self.assertEqual([write.chapter_id for write in command.writes], ["chapter-1", "chapter-2"])
        with self.assertRaises(FrozenInstanceError):
            command.project_id = "changed"

        result = DraftWriteResult(
            batch_id="batch-1",
            project_id="project-1",
            manifest_sha256="a" * 64,
            candidate_version_ids=("candidate-1", "candidate-2"),
            committed_at=1234,
        )
        self.assertEqual(
            result.to_wire(),
            {
                "batchId": "batch-1",
                "projectId": "project-1",
                "manifestSha256": "a" * 64,
                "candidateVersionIds": ["candidate-1", "candidate-2"],
                "committedAt": 1234,
            },
        )
        with self.assertRaises(FrozenInstanceError):
            result.batch_id = "changed"


if __name__ == "__main__":
    unittest.main()
