import json
import unittest
from pathlib import Path

from backend.serializers.provider import provider_public


ROOT = Path(__file__).resolve().parents[3]
SECRET = "STORED_SECRET_MUST_NOT_LEAVE"
PRIVATE_URL = "https://private-provider.example/v1"
FORBIDDEN_KEYS = {
    "apiKey",
    "api_key",
    "baseURL",
    "base_url",
    "authorization",
    "token",
    "password",
}


def provider_row():
    return {
        "id": "provider-1",
        "name": f"Provider {SECRET}",
        "provider_type": "openai-compatible",
        "model_name": "model-1",
        "enabled": 1,
        "sort_order": 0,
        "stream": 1,
        "max_context_tokens": 200_000,
        "max_output_tokens": 4096,
        "temperature": 0.8,
        "top_p": 0.9,
        "supports_json": 1,
        "supports_streaming": 1,
        "notes": f"safe after redaction {SECRET} {PRIVATE_URL}",
        "thinking": json.dumps(
            {
                "mode": "enabled",
                "authorization": SECRET,
                "token": SECRET,
                "password": SECRET,
                "api_key": SECRET,
                "base_url": PRIVATE_URL,
            }
        ),
        "api_key": SECRET,
        "base_url": PRIVATE_URL,
        "lifecycle_status": "active",
        "revision": 7,
        "deleted_at": None,
        "created_at": 1,
        "updated_at": 2,
    }


def assert_no_forbidden_keys(value):
    if isinstance(value, dict):
        assert not (set(value) & FORBIDDEN_KEYS), value
        for item in value.values():
            assert_no_forbidden_keys(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_forbidden_keys(item)


class ProviderPublicBoundaryTest(unittest.TestCase):
    def test_public_projection_is_whitelisted_and_recursively_secret_free(self):
        result = provider_public(provider_row())
        encoded = json.dumps(result, ensure_ascii=False)

        assert_no_forbidden_keys(result)
        self.assertNotIn(SECRET, encoded)
        self.assertNotIn(PRIVATE_URL, encoded)
        self.assertTrue(result["hasKey"])
        self.assertTrue(result["hasBaseURL"])
        self.assertEqual(result["lifecycleStatus"], "active")
        self.assertEqual(result["revision"], 7)
        self.assertEqual(result["thinking"], {"mode": "enabled"})

    def test_retired_full_export_and_import_routes_remain_absent(self):
        self.assertFalse((ROOT / "backend" / "routers" / "export.py").exists())
        client = (ROOT / "frontend" / "src" / "api" / "db" / "client.js").read_text(
            encoding="utf-8"
        )
        for forbidden in ("/export/full", "/import/full", "includeApiKeys"):
            self.assertNotIn(forbidden, client)


if __name__ == "__main__":
    unittest.main()
