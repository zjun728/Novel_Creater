import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend.routers import providers
from backend.routers.provider_public import to_public_provider


SENTINEL = "SECRET_MUST_NEVER_LEAVE_BACKEND"


def provider_row(*, has_key=True):
    return {
        "id": "provider-1",
        "name": "Provider",
        "provider_type": "openai-compatible",
        "base_url": "https://example.invalid/v1",
        "api_key": SENTINEL if has_key else "",
        "model": "model-1",
        "stream": 1,
        "max_context_tokens": 200000,
        "max_output_tokens": 4096,
        "temperature": 0.8,
        "top_p": 0.9,
        "supports_json": 1,
        "supports_streaming": 1,
        "notes": "",
        "thinking": None,
        "created_at": 1,
        "updated_at": 2,
        "has_api_key": 1 if has_key else 0,
    }


def assert_secret_free(testcase, value, *, has_key):
    encoded = json.dumps(value, ensure_ascii=False)
    testcase.assertNotIn("apiKey", value)
    testcase.assertNotIn("api_key", value)
    testcase.assertNotIn('"apiKey"', encoded)
    testcase.assertNotIn('"api_key"', encoded)
    testcase.assertNotIn(SENTINEL, encoded)
    testcase.assertIs(value["hasApiKey"], has_key)


class ProviderSecretCrudTest(unittest.IsolatedAsyncioTestCase):
    def test_normalizes_has_api_key_metadata_to_single_public_spelling(self):
        row = provider_row(has_key=True)
        row.pop("has_api_key")
        row["hasAPIKey"] = 1

        result = to_public_provider(row)

        self.assertNotIn("hasAPIKey", result)
        assert_secret_free(self, result, has_key=True)

    async def test_list_returns_has_api_key_without_secret(self):
        fetchall = AsyncMock(return_value=[provider_row(has_key=True)])
        with patch.object(providers, "fetchall", fetchall):
            result = await providers.list_providers()

        assert_secret_free(self, result[0], has_key=True)
        self.assertNotIn("SELECT *", fetchall.await_args.args[0].upper())

    async def test_create_returns_has_api_key_without_secret(self):
        execute = AsyncMock()
        fetchone = AsyncMock(return_value=provider_row(has_key=True))
        request = providers.ProviderCreate(
            name="Provider", apiKey=SENTINEL, model="model-1"
        )
        with patch.object(providers, "execute", execute), patch.object(
            providers, "fetchone", fetchone
        ):
            result = await providers.create_provider(request)

        assert_secret_free(self, result, has_key=True)
        insert_args = execute.await_args.args[1]
        self.assertEqual(insert_args[4], SENTINEL)
        self.assertNotIn("SELECT *", fetchone.await_args.args[0].upper())

    async def test_empty_update_returns_has_api_key_without_secret(self):
        fetchone = AsyncMock(return_value=provider_row(has_key=True))
        execute = AsyncMock()
        with patch.object(providers, "fetchone", fetchone), patch.object(
            providers, "execute", execute
        ):
            result = await providers.update_provider(
                "provider-1", providers.ProviderUpdate()
            )

        assert_secret_free(self, result, has_key=True)
        execute.assert_not_awaited()

    async def test_named_update_returns_has_api_key_without_secret(self):
        fetchone = AsyncMock(return_value=provider_row(has_key=True))
        execute = AsyncMock()
        with patch.object(providers, "fetchone", fetchone), patch.object(
            providers, "execute", execute
        ):
            result = await providers.update_provider(
                "provider-1", providers.ProviderUpdate(name="Renamed")
            )

        assert_secret_free(self, result, has_key=True)

    async def test_update_omits_api_key_when_request_omits_it(self):
        execute = AsyncMock()
        with patch.object(providers, "execute", execute), patch.object(
            providers,
            "fetchone",
            AsyncMock(return_value=provider_row(has_key=True)),
        ):
            await providers.update_provider(
                "provider-1", providers.ProviderUpdate(name="Renamed")
            )

        sql, args = execute.await_args.args
        self.assertNotIn("api_key=%s", sql)
        self.assertNotIn(SENTINEL, args)

    async def test_update_replaces_non_empty_api_key(self):
        execute = AsyncMock()
        replacement = "  REPLACEMENT_KEY  "
        with patch.object(providers, "execute", execute), patch.object(
            providers,
            "fetchone",
            AsyncMock(return_value=provider_row(has_key=True)),
        ):
            await providers.update_provider(
                "provider-1", providers.ProviderUpdate(apiKey=replacement)
            )

        sql, args = execute.await_args.args
        self.assertIn("api_key=%s", sql)
        self.assertEqual(args[0], replacement)
        self.assertEqual(args.count(replacement), 1)

    async def test_update_clears_explicit_empty_api_key(self):
        execute = AsyncMock()
        with patch.object(providers, "execute", execute), patch.object(
            providers,
            "fetchone",
            AsyncMock(return_value=provider_row(has_key=False)),
        ):
            result = await providers.update_provider(
                "provider-1", providers.ProviderUpdate(apiKey="")
            )

        sql, args = execute.await_args.args
        self.assertIn("api_key=%s", sql)
        self.assertEqual(args[0], "")
        assert_secret_free(self, result, has_key=False)


if __name__ == "__main__":
    unittest.main()
