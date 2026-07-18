CREATE TABLE market_sources (
  id CHAR(36) PRIMARY KEY,
  stable_key VARCHAR(160) NOT NULL,
  adapter_key VARCHAR(120) NOT NULL,
  display_name VARCHAR(200) NOT NULL,
  public_config_json JSON NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_market_source_key (stable_key),
  UNIQUE KEY uq_market_source_identity (stable_key, id),
  CHECK (status IN ('active','archived'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE market_source_policy_revisions (
  id CHAR(36) PRIMARY KEY,
  source_id CHAR(36) NOT NULL,
  revision INT NOT NULL,
  policy_status VARCHAR(24) NOT NULL,
  policy_version VARCHAR(120) NOT NULL,
  checked_at BIGINT NOT NULL,
  evidence_url VARCHAR(2048) NOT NULL,
  evidence_hash CHAR(64) NOT NULL,
  allowed_origins_json JSON NOT NULL,
  path_prefixes_json JSON NOT NULL,
  enabled TINYINT NOT NULL,
  interval_minutes INT NOT NULL,
  next_run_at BIGINT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_market_policy_revision (source_id, revision),
  UNIQUE KEY uq_market_policy_revision_id (source_id, id),
  UNIQUE KEY uq_market_policy_identity (source_id, id, revision, content_hash),
  FOREIGN KEY (source_id) REFERENCES market_sources(id) ON DELETE RESTRICT,
  CHECK (revision > 0),
  CHECK (policy_status IN ('verified_public','manual_only','disabled')),
  CHECK (enabled IN (0,1)),
  CHECK (interval_minutes > 0),
  CHECK (enabled = 0 OR policy_status = 'verified_public')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE market_source_policy_heads (
  source_id CHAR(36) PRIMARY KEY,
  revision_id CHAR(36) NOT NULL,
  revision INT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  updated_at BIGINT NOT NULL,
  FOREIGN KEY (source_id, revision_id, revision, content_hash) REFERENCES market_source_policy_revisions(source_id, id, revision, content_hash) ON DELETE RESTRICT,
  CHECK (revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE market_snapshots (
  id CHAR(36) PRIMARY KEY,
  source_id CHAR(36) NOT NULL,
  captured_at BIGINT NOT NULL,
  platform VARCHAR(120) NOT NULL,
  ranking_name VARCHAR(160) NOT NULL,
  category VARCHAR(160) NOT NULL,
  source_url VARCHAR(2048) NOT NULL,
  content_hash CHAR(64) NOT NULL,
  entry_count INT NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_market_snapshot_content (source_id, content_hash),
  UNIQUE KEY uq_market_snapshot_identity (source_id, id, captured_at, content_hash),
  UNIQUE KEY uq_market_snapshot_source_id (source_id, id),
  UNIQUE KEY uq_market_snapshot_hash_identity (source_id, id, content_hash),
  FOREIGN KEY (source_id) REFERENCES market_sources(id) ON DELETE RESTRICT,
  CHECK (entry_count > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE market_snapshot_entries (
  id CHAR(36) PRIMARY KEY,
  source_id CHAR(36) NOT NULL,
  snapshot_id CHAR(36) NOT NULL,
  rank_number INT NOT NULL,
  title VARCHAR(300) NOT NULL,
  author VARCHAR(200) NOT NULL,
  category VARCHAR(160) NOT NULL,
  work_url VARCHAR(2048) NOT NULL,
  public_metrics_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_market_entry_rank (snapshot_id, rank_number),
  UNIQUE KEY uq_market_entry_identity (snapshot_id, id, content_hash),
  FOREIGN KEY (source_id, snapshot_id) REFERENCES market_snapshots(source_id, id) ON DELETE RESTRICT,
  CHECK (rank_number > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE market_snapshot_manifests (
  id CHAR(36) PRIMARY KEY,
  source_id CHAR(36) NOT NULL,
  snapshot_id CHAR(36) NOT NULL,
  snapshot_hash CHAR(64) NOT NULL,
  policy_revision_id CHAR(36) NOT NULL,
  policy_revision INT NOT NULL,
  policy_hash CHAR(64) NOT NULL,
  adapter_version VARCHAR(120) NOT NULL,
  manifest_json JSON NOT NULL,
  manifest_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_market_snapshot_manifest (snapshot_id),
  UNIQUE KEY uq_market_manifest_identity (id, manifest_hash),
  FOREIGN KEY (source_id, snapshot_id, snapshot_hash) REFERENCES market_snapshots(source_id, id, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (source_id, policy_revision_id, policy_revision, policy_hash) REFERENCES market_source_policy_revisions(source_id, id, revision, content_hash) ON DELETE RESTRICT,
  CHECK (policy_revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE market_source_refresh_states (
  source_id CHAR(36) PRIMARY KEY,
  last_snapshot_id CHAR(36) NULL,
  refresh_status VARCHAR(24) NOT NULL,
  lease_owner CHAR(36) NULL,
  lease_expires_at BIGINT NULL,
  last_attempted_at BIGINT NULL,
  last_succeeded_at BIGINT NULL,
  next_run_at BIGINT NULL,
  public_error_code VARCHAR(64) NULL,
  updated_at BIGINT NOT NULL,
  FOREIGN KEY (source_id) REFERENCES market_sources(id) ON DELETE RESTRICT,
  FOREIGN KEY (source_id, last_snapshot_id) REFERENCES market_snapshots(source_id, id) ON DELETE RESTRICT,
  CHECK (refresh_status IN ('idle','leased')),
  CHECK (
    (refresh_status = 'idle' AND lease_owner IS NULL AND lease_expires_at IS NULL)
    OR (refresh_status = 'leased' AND lease_owner IS NOT NULL
      AND lease_expires_at IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE market_refresh_requests (
  id CHAR(36) PRIMARY KEY,
  source_id CHAR(36) NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  policy_revision INT NOT NULL,
  input_manifest_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  snapshot_id CHAR(36) NULL,
  result_hash CHAR(64) NULL,
  public_error_code VARCHAR(64) NULL,
  created_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_market_refresh_idempotency (source_id, idempotency_key),
  FOREIGN KEY (source_id) REFERENCES market_sources(id) ON DELETE RESTRICT,
  FOREIGN KEY (source_id, snapshot_id) REFERENCES market_snapshots(source_id, id) ON DELETE RESTRICT,
  CHECK (policy_revision > 0),
  CHECK (status IN ('reserved','running','succeeded','failed','outcome_unknown')),
  CHECK (
    (status IN ('reserved','running') AND snapshot_id IS NULL
      AND result_hash IS NULL AND public_error_code IS NULL
      AND completed_at IS NULL)
    OR (status = 'succeeded' AND snapshot_id IS NOT NULL
      AND result_hash IS NOT NULL AND public_error_code IS NULL
      AND completed_at IS NOT NULL)
    OR (status IN ('failed','outcome_unknown') AND snapshot_id IS NULL
      AND result_hash IS NULL AND public_error_code IS NOT NULL
      AND completed_at IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE market_analyses (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  binding_revision_id CHAR(36) NOT NULL,
  binding_hash CHAR(64) NOT NULL,
  input_manifest_json JSON NOT NULL,
  input_manifest_hash CHAR(64) NOT NULL,
  policy_version VARCHAR(120) NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  analysis_json JSON NULL,
  result_hash CHAR(64) NULL,
  public_error_code VARCHAR(64) NULL,
  created_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_market_analysis_idempotency (project_id, idempotency_key),
  UNIQUE KEY uq_market_analysis_identity (project_id, id, result_hash),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, binding_revision_id) REFERENCES project_model_binding_revisions(project_id, id) ON DELETE RESTRICT,
  CHECK (status IN ('reserved','running','succeeded','failed','outcome_unknown')),
  CHECK (
    (status IN ('reserved','running') AND analysis_json IS NULL
      AND result_hash IS NULL AND public_error_code IS NULL
      AND completed_at IS NULL)
    OR (status = 'succeeded' AND analysis_json IS NOT NULL
      AND result_hash IS NOT NULL AND public_error_code IS NULL
      AND completed_at IS NOT NULL)
    OR (status IN ('failed','outcome_unknown') AND analysis_json IS NULL
      AND result_hash IS NULL AND public_error_code IS NOT NULL
      AND completed_at IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE seed_inspiration_attempts (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  selection_revision INT NOT NULL,
  binding_revision_id CHAR(36) NOT NULL,
  binding_hash CHAR(64) NOT NULL,
  input_manifest_json JSON NOT NULL,
  input_manifest_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  result_json JSON NULL,
  result_hash CHAR(64) NULL,
  public_error_code VARCHAR(64) NULL,
  created_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_seed_inspiration_attempt_identity (project_id, id, result_hash),
  FOREIGN KEY (project_id, selection_revision) REFERENCES project_seed_selection_revisions(project_id, selection_revision) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, binding_revision_id) REFERENCES project_model_binding_revisions(project_id, id) ON DELETE RESTRICT,
  CHECK (status IN ('reserved','running','succeeded','failed','outcome_unknown'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE seed_inspiration_requests (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  attempt_id CHAR(36) NULL,
  result_hash CHAR(64) NULL,
  public_error_code VARCHAR(64) NULL,
  created_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_seed_inspiration_idempotency (project_id, idempotency_key),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (attempt_id) REFERENCES seed_inspiration_attempts(id) ON DELETE RESTRICT,
  CHECK (status IN ('reserved','succeeded','failed','outcome_unknown'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE asset_recommendation_attempts (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  selection_revision INT NOT NULL,
  binding_revision_id CHAR(36) NOT NULL,
  binding_hash CHAR(64) NOT NULL,
  input_manifest_json JSON NOT NULL,
  input_manifest_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  result_json JSON NULL,
  result_hash CHAR(64) NULL,
  public_error_code VARCHAR(64) NULL,
  created_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_asset_recommendation_attempt_identity (project_id, id, result_hash),
  FOREIGN KEY (project_id, selection_revision) REFERENCES project_seed_selection_revisions(project_id, selection_revision) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, binding_revision_id) REFERENCES project_model_binding_revisions(project_id, id) ON DELETE RESTRICT,
  CHECK (status IN ('reserved','running','succeeded','failed','outcome_unknown'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE asset_recommendation_requests (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  attempt_id CHAR(36) NULL,
  result_hash CHAR(64) NULL,
  public_error_code VARCHAR(64) NULL,
  created_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_asset_recommendation_idempotency (project_id, idempotency_key),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (attempt_id) REFERENCES asset_recommendation_attempts(id) ON DELETE RESTRICT,
  CHECK (status IN ('reserved','succeeded','failed','outcome_unknown'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE style_trial_attempts (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  selection_revision INT NOT NULL,
  binding_revision_id CHAR(36) NOT NULL,
  binding_hash CHAR(64) NOT NULL,
  input_manifest_json JSON NOT NULL,
  input_manifest_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  result_json JSON NULL,
  result_hash CHAR(64) NULL,
  public_error_code VARCHAR(64) NULL,
  created_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_style_trial_attempt_identity (project_id, id, result_hash),
  FOREIGN KEY (project_id, selection_revision) REFERENCES project_seed_selection_revisions(project_id, selection_revision) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, binding_revision_id) REFERENCES project_model_binding_revisions(project_id, id) ON DELETE RESTRICT,
  CHECK (status IN ('reserved','running','succeeded','failed','outcome_unknown'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE style_trial_requests (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  attempt_id CHAR(36) NULL,
  result_hash CHAR(64) NULL,
  public_error_code VARCHAR(64) NULL,
  created_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_style_trial_idempotency (project_id, idempotency_key),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (attempt_id) REFERENCES style_trial_attempts(id) ON DELETE RESTRICT,
  CHECK (status IN ('reserved','succeeded','failed','outcome_unknown'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
