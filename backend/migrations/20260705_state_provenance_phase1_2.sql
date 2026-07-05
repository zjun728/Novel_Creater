-- ContextPack v2 Phase 1.2 dry-run migration draft.
-- Do not execute automatically in this development thread.
-- Existing routers write these columns only when they already exist.

ALTER TABLE chapter_versions
  ADD COLUMN provenance JSON DEFAULT NULL,
  ADD COLUMN source_chapter_num INT DEFAULT NULL,
  ADD COLUMN source_version_id VARCHAR(80) DEFAULT '',
  ADD COLUMN run_id VARCHAR(120) DEFAULT '',
  ADD COLUMN finalization_id VARCHAR(120) DEFAULT '',
  ADD COLUMN commit_status VARCHAR(40) DEFAULT 'unknown';

ALTER TABLE chapter_beat_plans
  ADD COLUMN provenance JSON DEFAULT NULL,
  ADD COLUMN source_chapter_num INT DEFAULT NULL,
  ADD COLUMN source_version_id VARCHAR(80) DEFAULT '',
  ADD COLUMN run_id VARCHAR(120) DEFAULT '',
  ADD COLUMN finalization_id VARCHAR(120) DEFAULT '',
  ADD COLUMN commit_status VARCHAR(40) DEFAULT 'plan_only';

ALTER TABLE canon_facts
  ADD COLUMN provenance JSON DEFAULT NULL,
  ADD COLUMN source_chapter_num INT DEFAULT NULL,
  ADD COLUMN source_version_id VARCHAR(80) DEFAULT '',
  ADD COLUMN run_id VARCHAR(120) DEFAULT '',
  ADD COLUMN finalization_id VARCHAR(120) DEFAULT '',
  ADD COLUMN commit_status VARCHAR(40) DEFAULT 'unknown';

ALTER TABLE characters
  ADD COLUMN provenance JSON DEFAULT NULL,
  ADD COLUMN source_chapter_num INT DEFAULT NULL,
  ADD COLUMN source_version_id VARCHAR(80) DEFAULT '',
  ADD COLUMN run_id VARCHAR(120) DEFAULT '',
  ADD COLUMN finalization_id VARCHAR(120) DEFAULT '',
  ADD COLUMN commit_status VARCHAR(40) DEFAULT 'unknown';

ALTER TABLE setting_entities
  ADD COLUMN provenance JSON DEFAULT NULL,
  ADD COLUMN source_chapter_num INT DEFAULT NULL,
  ADD COLUMN source_version_id VARCHAR(80) DEFAULT '',
  ADD COLUMN run_id VARCHAR(120) DEFAULT '',
  ADD COLUMN finalization_id VARCHAR(120) DEFAULT '',
  ADD COLUMN commit_status VARCHAR(40) DEFAULT 'unknown';

ALTER TABLE setting_relations
  ADD COLUMN provenance JSON DEFAULT NULL,
  ADD COLUMN source_chapter_num INT DEFAULT NULL,
  ADD COLUMN source_version_id VARCHAR(80) DEFAULT '',
  ADD COLUMN run_id VARCHAR(120) DEFAULT '',
  ADD COLUMN finalization_id VARCHAR(120) DEFAULT '',
  ADD COLUMN commit_status VARCHAR(40) DEFAULT 'unknown';

ALTER TABLE setting_change_events
  ADD COLUMN provenance JSON DEFAULT NULL,
  ADD COLUMN source_chapter_num INT DEFAULT NULL,
  ADD COLUMN source_version_id VARCHAR(80) DEFAULT '',
  ADD COLUMN run_id VARCHAR(120) DEFAULT '',
  ADD COLUMN finalization_id VARCHAR(120) DEFAULT '',
  ADD COLUMN commit_status VARCHAR(40) DEFAULT 'unknown';

ALTER TABLE project_volumes
  ADD COLUMN provenance JSON DEFAULT NULL,
  ADD COLUMN source_chapter_num INT DEFAULT NULL,
  ADD COLUMN source_version_id VARCHAR(80) DEFAULT '',
  ADD COLUMN run_id VARCHAR(120) DEFAULT '',
  ADD COLUMN finalization_id VARCHAR(120) DEFAULT '',
  ADD COLUMN commit_status VARCHAR(40) DEFAULT 'unknown';

CREATE INDEX idx_chapter_versions_provenance
  ON chapter_versions (project_id, source_chapter_num, commit_status);

CREATE INDEX idx_chapter_beat_plans_provenance
  ON chapter_beat_plans (project_id, source_chapter_num, commit_status);

CREATE INDEX idx_canon_facts_provenance
  ON canon_facts (project_id, source_chapter_num, commit_status);

CREATE INDEX idx_setting_entities_provenance
  ON setting_entities (project_id, source_chapter_num, commit_status);

CREATE INDEX idx_setting_relations_provenance
  ON setting_relations (project_id, source_chapter_num, commit_status);

CREATE INDEX idx_setting_change_events_provenance
  ON setting_change_events (project_id, source_chapter_num, commit_status);

CREATE INDEX idx_project_volumes_provenance
  ON project_volumes (project_id, source_chapter_num, commit_status);

-- Phase 2.5 production schema adapter draft.
-- Durable finalization markers let the next chapter readiness gate block
-- pending or half-success finalization transactions after process restarts.
CREATE TABLE IF NOT EXISTS finalization_markers (
  id VARCHAR(160) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL,
  source_chapter_num INT DEFAULT NULL,
  source_version_id VARCHAR(80) DEFAULT '',
  run_id VARCHAR(120) DEFAULT '',
  finalization_id VARCHAR(120) DEFAULT '',
  commit_status VARCHAR(40) NOT NULL DEFAULT 'pending',
  reason TEXT DEFAULT NULL,
  provenance JSON DEFAULT NULL,
  started_at BIGINT DEFAULT NULL,
  updated_at BIGINT NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uniq_finalization_marker_run (project_id, chapter_num, run_id, finalization_id),
  INDEX idx_finalization_markers_project_chapter (project_id, chapter_num, commit_status),
  INDEX idx_finalization_markers_finalization (project_id, finalization_id),
  CONSTRAINT chk_finalization_markers_commit_status CHECK (
    commit_status IN (
      'staged',
      'validated',
      'committed',
      'pending',
      'in_progress',
      'failed_pre_commit',
      'failed_after_chapter_commit',
      'half_success'
    )
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Persistent project health-check dry-run results are audit artifacts. They
-- must never become creative facts; ContextPack consumes their blocking status
-- only through deterministic readiness gates.
CREATE TABLE IF NOT EXISTS project_health_checks (
  id VARCHAR(160) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL,
  source_chapter_num INT DEFAULT NULL,
  source_version_id VARCHAR(80) DEFAULT '',
  run_id VARCHAR(120) DEFAULT '',
  finalization_id VARCHAR(120) DEFAULT '',
  commit_status VARCHAR(40) NOT NULL DEFAULT 'dry_run',
  blocked TINYINT(1) NOT NULL DEFAULT 0,
  blocking_count INT NOT NULL DEFAULT 0,
  warning_count INT NOT NULL DEFAULT 0,
  result_json JSON DEFAULT NULL,
  issue_summary JSON DEFAULT NULL,
  provenance JSON DEFAULT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uniq_project_health_run (project_id, chapter_num, run_id),
  INDEX idx_project_health_checks_project_chapter (project_id, chapter_num, blocked),
  INDEX idx_project_health_checks_run (project_id, run_id),
  CONSTRAINT chk_project_health_checks_commit_status CHECK (
    commit_status IN ('dry_run', 'ready', 'blocked', 'warning', 'failed', 'unknown')
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
