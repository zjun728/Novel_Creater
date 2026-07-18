CREATE TABLE projects (
  id CHAR(36) PRIMARY KEY,
  title VARCHAR(200) NOT NULL,
  genre VARCHAR(120) NOT NULL,
  description TEXT NOT NULL,
  target_words INT NOT NULL,
  target_chapters INT NOT NULL,
  status VARCHAR(24) NOT NULL,
  current_chapter INT NOT NULL DEFAULT 0,
  archived_at BIGINT NULL,
  lifecycle_revision INT NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  CHECK (status IN ('drafting','active','completed')),
  CHECK (current_chapter >= 0),
  CHECK (lifecycle_revision >= 0),
  CHECK (target_words > 0),
  CHECK (target_chapters > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE creative_seeds (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_seed_project_id (project_id, id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CHECK (status IN ('candidate','archived'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE creative_seed_revisions (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  seed_id CHAR(36) NOT NULL,
  revision INT NOT NULL,
  payload_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_seed_revision (seed_id, revision),
  UNIQUE KEY uq_seed_revision_id (seed_id, id),
  UNIQUE KEY uq_seed_revision_project_id (project_id, id),
  UNIQUE KEY uq_seed_revision_project_seed_id (project_id, seed_id, id),
  UNIQUE KEY uq_seed_revision_project_fact (project_id, seed_id, id, content_hash),
  UNIQUE KEY uq_seed_revision_fact (seed_id, id, revision, content_hash),
  FOREIGN KEY (project_id, seed_id) REFERENCES creative_seeds(project_id, id) ON DELETE RESTRICT,
  CHECK (revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE creative_seed_heads (
  seed_id CHAR(36) PRIMARY KEY,
  revision_id CHAR(36) NOT NULL,
  revision INT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_seed_head_revision (seed_id, revision_id),
  FOREIGN KEY (seed_id, revision_id, revision, content_hash) REFERENCES creative_seed_revisions(seed_id, id, revision, content_hash) ON DELETE RESTRICT,
  CHECK (revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE project_seed_selection_revisions (
  project_id CHAR(36) NOT NULL,
  selection_revision INT NOT NULL,
  seed_id CHAR(36) NOT NULL,
  seed_revision_id CHAR(36) NOT NULL,
  seed_hash CHAR(64) NOT NULL,
  selected_at BIGINT NOT NULL,
  PRIMARY KEY (project_id, selection_revision),
  UNIQUE KEY uq_seed_selection_fact (project_id, selection_revision, seed_id, seed_revision_id, seed_hash),
  UNIQUE KEY uq_seed_selection_revision_fact (project_id, selection_revision, seed_revision_id, seed_hash),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, seed_id, seed_revision_id, seed_hash) REFERENCES creative_seed_revisions(project_id, seed_id, id, content_hash) ON DELETE RESTRICT,
  CHECK (selection_revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE project_selected_seeds (
  project_id CHAR(36) PRIMARY KEY,
  seed_id CHAR(36) NOT NULL,
  seed_revision_id CHAR(36) NOT NULL,
  seed_hash CHAR(64) NOT NULL,
  selection_revision INT NOT NULL,
  selected_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  FOREIGN KEY (project_id, selection_revision, seed_id, seed_revision_id, seed_hash) REFERENCES project_seed_selection_revisions(project_id, selection_revision, seed_id, seed_revision_id, seed_hash) ON DELETE RESTRICT,
  CHECK (selection_revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE provider_profiles (
  id CHAR(36) PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  provider_type VARCHAR(64) NULL,
  model_name VARCHAR(160) NULL,
  base_url VARCHAR(2048) NULL,
  api_key TEXT NULL,
  enabled TINYINT NOT NULL DEFAULT 1,
  sort_order INT NOT NULL DEFAULT 0,
  stream TINYINT NOT NULL DEFAULT 1,
  max_context_tokens INT NOT NULL,
  max_output_tokens INT NOT NULL,
  temperature DECIMAL(5,3) NOT NULL,
  top_p DECIMAL(5,3) NOT NULL,
  supports_json TINYINT NOT NULL DEFAULT 1,
  supports_streaming TINYINT NOT NULL DEFAULT 1,
  notes TEXT NOT NULL,
  thinking JSON NULL,
  lifecycle_status VARCHAR(16) NOT NULL,
  revision INT NOT NULL DEFAULT 0,
  deleted_at BIGINT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_provider_name (name),
  CHECK (enabled IN (0,1)),
  CHECK (stream IN (0,1)),
  CHECK (supports_json IN (0,1)),
  CHECK (supports_streaming IN (0,1)),
  CHECK (max_context_tokens > 0),
  CHECK (max_output_tokens > 0),
  CHECK (revision >= 0),
  CHECK (lifecycle_status IN ('active','unconfigured','deleted')),
  CHECK (
    (lifecycle_status = 'active' AND deleted_at IS NULL AND provider_type IS NOT NULL
      AND model_name IS NOT NULL AND base_url IS NOT NULL AND base_url <> ''
      AND api_key IS NOT NULL AND api_key <> '')
    OR (lifecycle_status = 'unconfigured' AND deleted_at IS NULL AND enabled = 0
      AND (api_key IS NULL OR api_key = ''))
    OR (lifecycle_status = 'deleted' AND deleted_at IS NOT NULL AND enabled = 0
      AND (api_key IS NULL OR api_key = '')
      AND (base_url IS NULL OR base_url = ''))
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE provider_profile_mutation_requests (
  id CHAR(36) PRIMARY KEY,
  provider_id CHAR(36) NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  mutation_kind VARCHAR(24) NOT NULL,
  expected_revision INT NOT NULL,
  status VARCHAR(16) NOT NULL,
  result_revision INT NULL,
  public_error_code VARCHAR(64) NULL,
  created_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_provider_mutation_idempotency (provider_id, idempotency_key),
  FOREIGN KEY (provider_id) REFERENCES provider_profiles(id) ON DELETE RESTRICT,
  CHECK (expected_revision >= 0),
  CHECK (mutation_kind IN ('create','update','clear_key','delete')),
  CHECK (status IN ('reserved','succeeded','failed')),
  CHECK (
    (status = 'reserved' AND result_revision IS NULL
      AND public_error_code IS NULL AND completed_at IS NULL)
    OR (status = 'succeeded' AND result_revision > expected_revision
      AND public_error_code IS NULL AND completed_at IS NOT NULL)
    OR (status = 'failed' AND result_revision IS NULL
      AND public_error_code IS NOT NULL AND completed_at IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE project_model_binding_revisions (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  revision INT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  source_project_id CHAR(36) NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_binding_revision (project_id, revision),
  UNIQUE KEY uq_binding_revision_id (project_id, id),
  UNIQUE KEY uq_binding_revision_identity (project_id, id, revision),
  UNIQUE KEY uq_binding_revision_hash_identity (project_id, id, content_hash),
  UNIQUE KEY uq_binding_revision_full_identity (project_id, id, revision, content_hash),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (source_project_id) REFERENCES projects(id) ON DELETE SET NULL,
  CHECK (revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE project_model_binding_items (
  binding_revision_id CHAR(36) NOT NULL,
  task_key VARCHAR(32) NOT NULL,
  resolution_status VARCHAR(16) NOT NULL,
  provider_id CHAR(36) NULL,
  provider_name_snapshot VARCHAR(120) NULL,
  model_name_snapshot VARCHAR(160) NULL,
  item_hash CHAR(64) NOT NULL,
  PRIMARY KEY (binding_revision_id, task_key),
  FOREIGN KEY (binding_revision_id) REFERENCES project_model_binding_revisions(id) ON DELETE CASCADE,
  FOREIGN KEY (provider_id) REFERENCES provider_profiles(id) ON DELETE RESTRICT,
  CHECK (task_key IN ('seed','planning','writing','audit','summary','extraction','polish','market')),
  CHECK (resolution_status IN ('bound','unbound')),
  CHECK (
    (resolution_status = 'bound' AND provider_id IS NOT NULL
      AND provider_name_snapshot IS NOT NULL AND model_name_snapshot IS NOT NULL)
    OR (resolution_status = 'unbound' AND provider_id IS NULL
      AND provider_name_snapshot IS NULL AND model_name_snapshot IS NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE project_model_binding_heads (
  project_id CHAR(36) PRIMARY KEY,
  revision INT NOT NULL,
  binding_revision_id CHAR(36) NOT NULL,
  content_hash CHAR(64) NOT NULL,
  updated_at BIGINT NOT NULL,
  FOREIGN KEY (project_id, binding_revision_id, revision, content_hash) REFERENCES project_model_binding_revisions(project_id, id, revision, content_hash) ON DELETE CASCADE,
  CHECK (revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
