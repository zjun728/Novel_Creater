CREATE TABLE project_bible_drafts (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  active_slot TINYINT NULL,
  base_head_revision INT NOT NULL,
  selection_revision INT NOT NULL,
  seed_id CHAR(36) NOT NULL,
  seed_revision_id CHAR(36) NOT NULL,
  seed_hash CHAR(64) NOT NULL,
  contract_revision INT NOT NULL,
  creation_contract_id CHAR(36) NOT NULL,
  creation_hash CHAR(64) NOT NULL,
  style_contract_id CHAR(36) NOT NULL,
  style_hash CHAR(64) NOT NULL,
  binding_revision_id CHAR(36) NULL,
  binding_hash CHAR(64) NULL,
  policy_version VARCHAR(120) NOT NULL,
  draft_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  draft_version INT NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_bible_draft_project_id (project_id, id),
  UNIQUE KEY uq_bible_draft_active_slot (project_id, active_slot),
  UNIQUE KEY uq_bible_draft_generation (project_id, id, selection_revision, contract_revision, creation_hash, style_hash),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, selection_revision, seed_id, seed_revision_id, seed_hash) REFERENCES project_seed_selection_revisions(project_id, selection_revision, seed_id, seed_revision_id, seed_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, selection_revision, contract_revision, creation_hash) REFERENCES creation_contracts(project_id, selection_revision, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, creation_contract_id, contract_revision, creation_hash) REFERENCES creation_contracts(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, style_contract_id, contract_revision, style_hash) REFERENCES style_contracts(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, binding_revision_id, binding_hash) REFERENCES project_model_binding_revisions(project_id, id, content_hash) ON DELETE RESTRICT,
  CHECK (active_slot IS NULL OR active_slot = 1),
  CHECK (base_head_revision >= 0),
  CHECK (selection_revision > 0),
  CHECK (contract_revision > 0),
  CHECK (draft_version > 0),
  CHECK (
    (binding_revision_id IS NULL AND binding_hash IS NULL)
    OR (binding_revision_id IS NOT NULL AND binding_hash IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE bible_generation_attempts (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  selection_revision INT NOT NULL,
  seed_id CHAR(36) NOT NULL,
  seed_revision_id CHAR(36) NOT NULL,
  seed_hash CHAR(64) NOT NULL,
  contract_revision INT NOT NULL,
  creation_contract_id CHAR(36) NOT NULL,
  creation_hash CHAR(64) NOT NULL,
  style_contract_id CHAR(36) NOT NULL,
  style_hash CHAR(64) NOT NULL,
  binding_revision_id CHAR(36) NOT NULL,
  binding_hash CHAR(64) NOT NULL,
  provider_id CHAR(36) NOT NULL,
  model_name_snapshot VARCHAR(160) NOT NULL,
  policy_version VARCHAR(120) NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  input_manifest_json JSON NOT NULL,
  input_manifest_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  owner_token CHAR(36) NULL,
  lease_expires_at BIGINT NULL,
  attempt_version INT NOT NULL,
  result_json JSON NULL,
  result_hash CHAR(64) NULL,
  public_error_code VARCHAR(64) NULL,
  created_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_bible_generation_idempotency (project_id, idempotency_key),
  UNIQUE KEY uq_bible_generation_identity (project_id, id, result_hash),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, selection_revision, seed_id, seed_revision_id, seed_hash) REFERENCES project_seed_selection_revisions(project_id, selection_revision, seed_id, seed_revision_id, seed_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, selection_revision, contract_revision, creation_hash) REFERENCES creation_contracts(project_id, selection_revision, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, creation_contract_id, contract_revision, creation_hash) REFERENCES creation_contracts(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, style_contract_id, contract_revision, style_hash) REFERENCES style_contracts(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, binding_revision_id, binding_hash) REFERENCES project_model_binding_revisions(project_id, id, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (provider_id) REFERENCES provider_profiles(id) ON DELETE RESTRICT,
  CHECK (selection_revision > 0),
  CHECK (contract_revision > 0),
  CHECK (attempt_version > 0),
  CHECK (status IN ('reserved','running','succeeded','failed','outcome_unknown')),
  CHECK (
    (status IN ('reserved','running') AND owner_token IS NOT NULL
      AND lease_expires_at IS NOT NULL AND result_json IS NULL
      AND result_hash IS NULL AND public_error_code IS NULL
      AND completed_at IS NULL)
    OR (status = 'succeeded' AND owner_token IS NULL AND lease_expires_at IS NULL
      AND result_json IS NOT NULL AND result_hash IS NOT NULL
      AND public_error_code IS NULL AND completed_at IS NOT NULL)
    OR (status IN ('failed','outcome_unknown') AND owner_token IS NULL
      AND lease_expires_at IS NULL AND result_json IS NULL
      AND result_hash IS NULL AND public_error_code IS NOT NULL
      AND completed_at IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE creation_bible_revisions (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  revision INT NOT NULL,
  selection_revision INT NOT NULL,
  seed_id CHAR(36) NOT NULL,
  seed_revision_id CHAR(36) NOT NULL,
  seed_hash CHAR(64) NOT NULL,
  contract_revision INT NOT NULL,
  creation_contract_id CHAR(36) NOT NULL,
  creation_hash CHAR(64) NOT NULL,
  style_contract_id CHAR(36) NOT NULL,
  style_hash CHAR(64) NOT NULL,
  binding_revision_id CHAR(36) NULL,
  binding_hash CHAR(64) NULL,
  policy_version VARCHAR(120) NOT NULL,
  content_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  confirmed_at BIGINT NOT NULL,
  UNIQUE KEY uq_bible_revision (project_id, revision),
  UNIQUE KEY uq_bible_revision_hash (project_id, revision, content_hash),
  UNIQUE KEY uq_bible_revision_id (project_id, id),
  UNIQUE KEY uq_bible_revision_identity (project_id, id, revision, content_hash),
  UNIQUE KEY uq_bible_revision_generation (project_id, selection_revision, contract_revision, creation_hash, revision, content_hash),
  UNIQUE KEY uq_bible_revision_full_generation (project_id, id, selection_revision, contract_revision, creation_hash, style_hash, revision, content_hash),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, selection_revision, seed_id, seed_revision_id, seed_hash) REFERENCES project_seed_selection_revisions(project_id, selection_revision, seed_id, seed_revision_id, seed_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, selection_revision, contract_revision, creation_hash) REFERENCES creation_contracts(project_id, selection_revision, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, creation_contract_id, contract_revision, creation_hash) REFERENCES creation_contracts(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, style_contract_id, contract_revision, style_hash) REFERENCES style_contracts(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, binding_revision_id, binding_hash) REFERENCES project_model_binding_revisions(project_id, id, content_hash) ON DELETE RESTRICT,
  CHECK (revision > 0),
  CHECK (selection_revision > 0),
  CHECK (contract_revision > 0),
  CHECK (
    (binding_revision_id IS NULL AND binding_hash IS NULL)
    OR (binding_revision_id IS NOT NULL AND binding_hash IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE project_bible_heads (
  project_id CHAR(36) PRIMARY KEY,
  revision INT NOT NULL,
  bible_revision_id CHAR(36) NULL,
  content_hash CHAR(64) NULL,
  updated_at BIGINT NOT NULL,
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, bible_revision_id, revision, content_hash) REFERENCES creation_bible_revisions(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  CHECK (revision >= 0),
  CHECK ((revision = 0 AND bible_revision_id IS NULL AND content_hash IS NULL)
    OR (revision > 0 AND bible_revision_id IS NOT NULL AND content_hash IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE bible_confirmation_requests (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  selection_revision INT NOT NULL,
  contract_revision INT NOT NULL,
  creation_contract_id CHAR(36) NOT NULL,
  creation_hash CHAR(64) NOT NULL,
  style_contract_id CHAR(36) NOT NULL,
  style_hash CHAR(64) NOT NULL,
  draft_id CHAR(36) NOT NULL,
  draft_version INT NOT NULL,
  draft_hash CHAR(64) NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  status VARCHAR(16) NOT NULL,
  bible_revision_id CHAR(36) NULL,
  result_revision INT NULL,
  result_hash CHAR(64) NULL,
  public_error_code VARCHAR(64) NULL,
  created_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_bible_confirmation_idempotency (project_id, idempotency_key),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, selection_revision, contract_revision, creation_hash) REFERENCES creation_contracts(project_id, selection_revision, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, creation_contract_id, contract_revision, creation_hash) REFERENCES creation_contracts(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, style_contract_id, contract_revision, style_hash) REFERENCES style_contracts(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, draft_id) REFERENCES project_bible_drafts(project_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, bible_revision_id, selection_revision, contract_revision, creation_hash, style_hash, result_revision, result_hash) REFERENCES creation_bible_revisions(project_id, id, selection_revision, contract_revision, creation_hash, style_hash, revision, content_hash) ON DELETE RESTRICT,
  CHECK (selection_revision > 0),
  CHECK (contract_revision > 0),
  CHECK (draft_version > 0),
  CHECK (status IN ('reserved','succeeded','failed')),
  CHECK (
    (status = 'reserved' AND bible_revision_id IS NULL
      AND result_revision IS NULL AND result_hash IS NULL
      AND public_error_code IS NULL AND completed_at IS NULL)
    OR (status = 'succeeded' AND bible_revision_id IS NOT NULL
      AND result_revision > 0 AND result_hash IS NOT NULL
      AND public_error_code IS NULL AND completed_at IS NOT NULL)
    OR (status = 'failed' AND bible_revision_id IS NULL
      AND result_revision IS NULL AND result_hash IS NULL
      AND public_error_code IS NOT NULL AND completed_at IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
