"""Session-bound persistence for the application settings singleton."""

from __future__ import annotations


class ApplicationSettingsRepository:
    @staticmethod
    def _settings_sql() -> str:
        return """SELECT a.singleton_id,a.fallback_provider_id,a.revision,
                         a.updated_at,
                         p.id AS provider_id,p.name AS provider_name,
                         p.provider_type AS provider_provider_type,
                         p.model_name AS provider_model_name,
                         p.base_url AS provider_base_url,
                         p.api_key AS provider_api_key,
                         p.enabled AS provider_enabled,
                         p.lifecycle_status AS provider_lifecycle_status
                  FROM application_settings a
                  LEFT JOIN provider_profiles p
                    ON p.id=a.fallback_provider_id
                  WHERE a.singleton_id=1"""

    async def read_settings(self, session):
        return await session.fetchone(self._settings_sql())

    async def lock_settings(self, session):
        return await session.fetchone(
            """SELECT singleton_id,fallback_provider_id,revision,updated_at
               FROM application_settings
               WHERE singleton_id=1 FOR UPDATE"""
        )

    async def lock_provider(self, session, provider_id: str):
        return await session.fetchone(
            """SELECT id,name,provider_type,model_name,base_url,api_key,
                      enabled,lifecycle_status
               FROM provider_profiles
               WHERE id=%s FOR UPDATE""",
            (provider_id,),
        )

    async def compare_and_swap(
        self,
        session,
        *,
        expected_revision: int,
        fallback_provider_id: str | None,
        updated_at: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE application_settings
               SET fallback_provider_id=%s,
                   revision=revision+1,
                   updated_at=%s
               WHERE singleton_id=1 AND revision=%s""",
            (fallback_provider_id, updated_at, expected_revision),
        )
        return changed == 1

    async def read_schema_metadata(self, session):
        return await session.fetchone(
            """SELECT schema_version,manifest_hash
               FROM schema_metadata WHERE singleton_id=1"""
        )

    async def read_scheduler_next_run(self, session):
        row = await session.fetchone(
            """SELECT MIN(rs.next_run_at) AS next_run_at
               FROM market_sources s
               JOIN market_source_policy_heads h ON h.source_id=s.id
               JOIN market_source_policy_revisions p
                 ON p.source_id=h.source_id AND p.id=h.revision_id
                AND p.revision=h.revision AND p.content_hash=h.content_hash
               JOIN market_source_refresh_states rs ON rs.source_id=s.id
               WHERE s.status='active' AND p.policy_status='verified_public'
                 AND p.enabled=1 AND rs.next_run_at IS NOT NULL"""
        )
        return None if row is None else row["next_run_at"]
