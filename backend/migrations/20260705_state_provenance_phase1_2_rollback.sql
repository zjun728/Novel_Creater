-- ContextPack v2 Phase 2.5 rollback dry-run draft.
-- Do not execute automatically in this development thread.
-- Before any real execution, take a full database backup and verify no
-- downstream code depends on these audit tables.

DROP TABLE IF EXISTS project_health_checks;
DROP TABLE IF EXISTS finalization_markers;

-- Provenance columns added to existing production tables are intentionally not
-- dropped by this lightweight rollback draft. If a future real rollback must
-- remove those columns, prepare a separate backup-verified migration after
-- exporting the provenance JSON/scalar evidence.
