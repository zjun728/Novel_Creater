import json
import unittest
from pathlib import Path

from backend.serializers.provider import provider_public


ROOT = Path(__file__).resolve().parents[3]
SECRET = "STORED_SECRET_MUST_NOT_LEAVE"
PRIVATE_URL = "https://private-provider.example/v1"
NESTED_SECRET = "UNRELATED_NESTED_SECRET_MUST_NOT_LEAVE"


def provider_row():
    return {
        "id": "provider-1",
        "name": "Provider",
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
                "credentials": {"API_KEY": NESTED_SECRET, "region": "local"},
                "transport": {"base-url": NESTED_SECRET, "mode": "safe"},
            }
        ),
        "api_key": SECRET,
        "base_url": PRIVATE_URL,
        "created_at": 1,
        "updated_at": 2,
    }


class ProviderPublicBoundaryTest(unittest.TestCase):
    def test_public_projection_recursively_removes_secret_fields_and_values(self):
        result = provider_public(provider_row())
        encoded = json.dumps(result, ensure_ascii=False)

        self.assertNotIn(SECRET, encoded)
        self.assertNotIn(PRIVATE_URL, encoded)
        self.assertNotIn(NESTED_SECRET, encoded)
        self.assertNotIn("API_KEY", encoded)
        self.assertNotIn("base-url", encoded)
        self.assertTrue(result["hasKey"])
        self.assertTrue(result["hasBaseURL"])
        self.assertEqual(result["thinking"]["credentials"], {"region": "local"})
        self.assertEqual(result["thinking"]["transport"], {"mode": "safe"})

    def test_retired_full_export_and_import_routes_remain_absent(self):
        self.assertFalse((ROOT / "backend" / "routers" / "export.py").exists())
        client = (ROOT / "frontend" / "src" / "api" / "db" / "client.js").read_text(
            encoding="utf-8"
        )
        for forbidden in ("/export/full", "/import/full", "includeApiKeys"):
            self.assertNotIn(forbidden, client)


if __name__ == "__main__":
    unittest.main()
