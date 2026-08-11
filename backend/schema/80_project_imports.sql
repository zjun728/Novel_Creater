CREATE TABLE project_package_import_commands (
  id CHAR(36) PRIMARY KEY,
  idempotency_key CHAR(64) NOT NULL,
  request_fingerprint CHAR(64) NOT NULL,
  package_hash CHAR(64) NOT NULL,
  manifest_hash CHAR(64) NOT NULL,
  package_version INT NOT NULL,
  target_project_id CHAR(36) NOT NULL,
  normalized_title VARCHAR(300) NOT NULL,
  status VARCHAR(16) NOT NULL,
  phase VARCHAR(16) NOT NULL,
  owner_token CHAR(36) NULL,
  lease_expires_at BIGINT NULL,
  staging_manifest_json JSON NULL,
  public_error_code VARCHAR(64) NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_project_import_idempotency (idempotency_key),
  UNIQUE KEY uq_project_import_target (target_project_id),
  UNIQUE KEY uq_project_import_command_target (id, target_project_id),
  CHECK (package_version > 0),
  CHECK (status IN ('reserved','running','succeeded','failed')),
  CHECK (phase IN ('uploaded','preflighted','staged','publishing','succeeded','failed')),
  CHECK (staging_manifest_json IS NULL OR JSON_VALID(staging_manifest_json)),
  CHECK (
    (status = 'reserved' AND phase IN ('uploaded','preflighted')
      AND owner_token IS NULL AND lease_expires_at IS NULL
      AND public_error_code IS NULL AND completed_at IS NULL)
    OR
    (status = 'running' AND phase IN ('preflighted','staged','publishing')
      AND owner_token IS NOT NULL AND lease_expires_at IS NOT NULL
      AND public_error_code IS NULL AND completed_at IS NULL)
    OR
    (status = 'succeeded' AND phase = 'succeeded'
      AND owner_token IS NULL AND lease_expires_at IS NULL
      AND public_error_code IS NULL AND completed_at IS NOT NULL)
    OR
    (status = 'failed' AND phase = 'failed'
      AND owner_token IS NULL AND lease_expires_at IS NULL
      AND public_error_code IS NOT NULL AND completed_at IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE project_import_provenance (
  project_id CHAR(36) NOT NULL,
  command_id CHAR(36) NOT NULL,
  record_order INT NOT NULL,
  category VARCHAR(32) NOT NULL,
  source_entity_type VARCHAR(120) NOT NULL,
  source_logical_id VARCHAR(200) NOT NULL,
  payload_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  PRIMARY KEY (project_id, record_order),
  UNIQUE KEY uq_project_import_provenance_command_order (command_id, record_order),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (command_id, project_id)
    REFERENCES project_package_import_commands(id, target_project_id) ON DELETE RESTRICT,
  CHECK (record_order > 0),
  CHECK (category IN ('provider-history','market-history','operation-history','unsupported-history')),
  CHECK (JSON_VALID(payload_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

