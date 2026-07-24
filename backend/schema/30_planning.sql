CREATE TABLE planning_drafts (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  active_slot TINYINT NULL,
  base_head_revision INT NOT NULL,
  draft_revision INT NOT NULL,
  selection_revision INT NOT NULL,
  seed_id CHAR(36) NOT NULL,
  seed_revision_id CHAR(36) NOT NULL,
  seed_hash CHAR(64) NOT NULL,
  contract_revision INT NOT NULL,
  creation_contract_id CHAR(36) NOT NULL,
  creation_hash CHAR(64) NOT NULL,
  style_contract_id CHAR(36) NOT NULL,
  style_hash CHAR(64) NOT NULL,
  bible_revision INT NOT NULL,
  bible_revision_id CHAR(36) NOT NULL,
  bible_hash CHAR(64) NOT NULL,
  content_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  source_attempt_id CHAR(36) NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_planning_draft_project_id (project_id, id),
  UNIQUE KEY uq_planning_draft_active_slot (project_id, active_slot),
  UNIQUE KEY uq_planning_draft_identity (project_id, id, draft_revision, content_hash),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, selection_revision, seed_id, seed_revision_id, seed_hash) REFERENCES project_seed_selection_revisions(project_id, selection_revision, seed_id, seed_revision_id, seed_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, creation_contract_id, contract_revision, creation_hash) REFERENCES creation_contracts(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, style_contract_id, contract_revision, style_hash) REFERENCES style_contracts(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, bible_revision_id, selection_revision, contract_revision, creation_hash, style_hash, bible_revision, bible_hash) REFERENCES creation_bible_revisions(project_id, id, selection_revision, contract_revision, creation_hash, style_hash, revision, content_hash) ON DELETE RESTRICT,
  CHECK (active_slot IS NULL OR active_slot = 1),
  CHECK (base_head_revision >= 0),
  CHECK (draft_revision > 0),
  CHECK (selection_revision > 0),
  CHECK (contract_revision > 0),
  CHECK (bible_revision > 0),
  CHECK (status IN ('active','confirmed','superseded')),
  CHECK (
    (status = 'active' AND active_slot IS NOT NULL AND active_slot = 1)
    OR (status IN ('confirmed','superseded') AND active_slot IS NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE planning_generation_attempts (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  draft_id CHAR(36) NOT NULL,
  operation_id CHAR(36) NOT NULL,
  active_slot TINYINT NULL,
  idempotency_key VARCHAR(64) NOT NULL,
  request_fingerprint CHAR(64) NOT NULL,
  binding_revision_id CHAR(36) NOT NULL,
  binding_revision INT NOT NULL,
  binding_hash CHAR(64) NOT NULL,
  provider_id CHAR(36) NOT NULL,
  model_name_snapshot VARCHAR(200) NOT NULL,
  fencing_token BIGINT NOT NULL,
  lease_expires_at BIGINT NOT NULL,
  input_manifest_json JSON NOT NULL,
  input_manifest_hash CHAR(64) NOT NULL,
  result_content_json JSON NULL,
  result_content_hash CHAR(64) NULL,
  loaded_draft_revision INT NULL,
  loaded_at BIGINT NULL,
  failure_code VARCHAR(64) NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_planning_generation_project_id (project_id, id),
  UNIQUE KEY uq_planning_operation (project_id, operation_id),
  UNIQUE KEY uq_planning_generation_idempotency (project_id, idempotency_key),
  UNIQUE KEY uq_active_planning_generation (draft_id, active_slot),
  UNIQUE KEY uq_planning_fencing (draft_id, fencing_token),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, draft_id) REFERENCES planning_drafts(project_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, binding_revision_id, binding_revision, binding_hash) REFERENCES project_model_binding_revisions(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (provider_id) REFERENCES provider_profiles(id) ON DELETE RESTRICT,
  CHECK (active_slot IS NULL OR active_slot = 1),
  CHECK (binding_revision > 0),
  CHECK (fencing_token > 0),
  CHECK (lease_expires_at >= created_at),
  CHECK ((result_content_json IS NULL AND result_content_hash IS NULL)
    OR (result_content_json IS NOT NULL AND result_content_hash IS NOT NULL)),
  CHECK ((loaded_draft_revision IS NULL AND loaded_at IS NULL)
    OR (status = 'succeeded' AND loaded_draft_revision IS NOT NULL
      AND loaded_draft_revision > 0 AND loaded_at IS NOT NULL)),
  CHECK (status IN ('pending','succeeded','failed','superseded')),
  CHECK (
    (status = 'pending' AND active_slot IS NOT NULL AND active_slot = 1)
    OR (status IN ('succeeded','failed','superseded') AND active_slot IS NULL)
  ),
  CHECK (
    (status = 'pending' AND active_slot IS NOT NULL AND active_slot = 1
      AND result_content_json IS NULL AND result_content_hash IS NULL
      AND loaded_draft_revision IS NULL AND loaded_at IS NULL
      AND failure_code IS NULL)
    OR (status = 'succeeded' AND active_slot IS NULL
      AND result_content_json IS NOT NULL AND result_content_hash IS NOT NULL
      AND failure_code IS NULL)
    OR (status = 'failed' AND active_slot IS NULL
      AND result_content_json IS NULL AND result_content_hash IS NULL
      AND loaded_draft_revision IS NULL AND loaded_at IS NULL
      AND failure_code IS NOT NULL)
    OR (status = 'superseded' AND active_slot IS NULL
      AND loaded_draft_revision IS NULL AND loaded_at IS NULL
      AND failure_code IS NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE planning_revisions (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  revision INT NOT NULL,
  parent_revision INT NOT NULL,
  selection_revision INT NOT NULL,
  seed_id CHAR(36) NOT NULL,
  seed_revision_id CHAR(36) NOT NULL,
  seed_hash CHAR(64) NOT NULL,
  contract_revision INT NOT NULL,
  creation_contract_id CHAR(36) NOT NULL,
  creation_hash CHAR(64) NOT NULL,
  style_contract_id CHAR(36) NOT NULL,
  style_hash CHAR(64) NOT NULL,
  bible_revision INT NOT NULL,
  bible_revision_id CHAR(36) NOT NULL,
  bible_hash CHAR(64) NOT NULL,
  content_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_planning_revision (project_id, revision),
  UNIQUE KEY uq_planning_revision_project_id (project_id, id),
  UNIQUE KEY uq_planning_revision_identity (project_id, id, revision, content_hash),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, selection_revision, seed_id, seed_revision_id, seed_hash) REFERENCES project_seed_selection_revisions(project_id, selection_revision, seed_id, seed_revision_id, seed_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, creation_contract_id, contract_revision, creation_hash) REFERENCES creation_contracts(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, style_contract_id, contract_revision, style_hash) REFERENCES style_contracts(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, bible_revision_id, selection_revision, contract_revision, creation_hash, style_hash, bible_revision, bible_hash) REFERENCES creation_bible_revisions(project_id, id, selection_revision, contract_revision, creation_hash, style_hash, revision, content_hash) ON DELETE RESTRICT,
  CHECK (revision > 0),
  CHECK (parent_revision >= 0 AND parent_revision < revision),
  CHECK (selection_revision > 0),
  CHECK (contract_revision > 0),
  CHECK (bible_revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE project_planning_heads (
  project_id CHAR(36) NOT NULL PRIMARY KEY,
  revision INT NOT NULL,
  planning_revision_id CHAR(36) NULL,
  content_hash CHAR(64) NULL,
  updated_at BIGINT NOT NULL,
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, planning_revision_id, revision, content_hash) REFERENCES planning_revisions(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  CHECK (revision >= 0),
  CHECK (
    (revision = 0 AND planning_revision_id IS NULL AND content_hash IS NULL)
    OR (revision > 0 AND planning_revision_id IS NOT NULL
      AND content_hash IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE planning_confirmation_requests (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  planning_draft_id CHAR(36) NOT NULL,
  draft_revision INT NOT NULL,
  draft_hash CHAR(64) NOT NULL,
  expected_head_revision INT NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  request_fingerprint CHAR(64) NOT NULL,
  status VARCHAR(16) NOT NULL,
  planning_revision_id CHAR(36) NULL,
  result_revision INT NULL,
  result_hash CHAR(64) NULL,
  public_error_code VARCHAR(64) NULL,
  created_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_planning_confirmation_project_id (project_id, id),
  UNIQUE KEY uq_planning_confirmation_idempotency (project_id, idempotency_key),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, planning_draft_id, draft_revision, draft_hash) REFERENCES planning_drafts(project_id, id, draft_revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, planning_revision_id, result_revision, result_hash) REFERENCES planning_revisions(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  CHECK (draft_revision > 0),
  CHECK (expected_head_revision >= 0),
  CHECK (status IN ('pending','succeeded','failed')),
  CHECK (
    (status = 'pending' AND planning_revision_id IS NULL
      AND result_revision IS NULL AND result_hash IS NULL
      AND public_error_code IS NULL AND completed_at IS NULL)
    OR (status = 'succeeded' AND planning_revision_id IS NOT NULL
      AND result_revision IS NOT NULL AND result_revision > expected_head_revision
      AND result_hash IS NOT NULL
      AND public_error_code IS NULL AND completed_at IS NOT NULL)
    OR (status = 'failed' AND planning_revision_id IS NULL
      AND result_revision IS NULL AND result_hash IS NULL
      AND public_error_code IS NOT NULL AND completed_at IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE chapter_outline_drafts (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL,
  active_slot TINYINT NULL,
  base_head_revision INT NOT NULL,
  draft_revision INT NOT NULL,
  planning_revision_id CHAR(36) NOT NULL,
  planning_revision INT NOT NULL,
  planning_hash CHAR(64) NOT NULL,
  canon_revision INT NOT NULL,
  projection_revision INT NOT NULL,
  projection_hash CHAR(64) NOT NULL,
  content_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  source_attempt_id CHAR(36) NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_outline_draft_project_id (project_id, id),
  UNIQUE KEY uq_outline_draft_active_slot (project_id, chapter_num, active_slot),
  UNIQUE KEY uq_outline_draft_identity (project_id, id, draft_revision, content_hash),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, planning_revision_id, planning_revision, planning_hash) REFERENCES planning_revisions(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  CHECK (chapter_num > 0),
  CHECK (active_slot IS NULL OR active_slot = 1),
  CHECK (base_head_revision >= 0),
  CHECK (draft_revision > 0),
  CHECK (planning_revision > 0),
  CHECK (canon_revision >= 0),
  CHECK (projection_revision >= 0),
  CHECK (status IN ('active','confirmed','superseded')),
  CHECK (
    (status = 'active' AND active_slot IS NOT NULL AND active_slot = 1)
    OR (status IN ('confirmed','superseded') AND active_slot IS NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE chapter_outline_generation_attempts (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  outline_draft_id CHAR(36) NOT NULL,
  operation_id CHAR(36) NOT NULL,
  active_slot TINYINT NULL,
  idempotency_key VARCHAR(64) NOT NULL,
  request_fingerprint CHAR(64) NOT NULL,
  binding_revision_id CHAR(36) NOT NULL,
  binding_revision INT NOT NULL,
  binding_hash CHAR(64) NOT NULL,
  provider_id CHAR(36) NOT NULL,
  model_name_snapshot VARCHAR(200) NOT NULL,
  fencing_token BIGINT NOT NULL,
  lease_expires_at BIGINT NOT NULL,
  input_manifest_json JSON NOT NULL,
  input_manifest_hash CHAR(64) NOT NULL,
  result_content_json JSON NULL,
  result_content_hash CHAR(64) NULL,
  loaded_outline_draft_revision INT NULL,
  loaded_at BIGINT NULL,
  failure_code VARCHAR(64) NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_chapter_outline_generation_project_id (project_id, id),
  UNIQUE KEY uq_outline_operation (project_id, operation_id),
  UNIQUE KEY uq_outline_generation_idempotency (project_id, idempotency_key),
  UNIQUE KEY uq_active_outline_generation (outline_draft_id, active_slot),
  UNIQUE KEY uq_outline_fencing (outline_draft_id, fencing_token),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, outline_draft_id) REFERENCES chapter_outline_drafts(project_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, binding_revision_id, binding_revision, binding_hash) REFERENCES project_model_binding_revisions(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (provider_id) REFERENCES provider_profiles(id) ON DELETE RESTRICT,
  CHECK (active_slot IS NULL OR active_slot = 1),
  CHECK (binding_revision > 0),
  CHECK (fencing_token > 0),
  CHECK (lease_expires_at >= created_at),
  CHECK ((result_content_json IS NULL AND result_content_hash IS NULL)
    OR (result_content_json IS NOT NULL AND result_content_hash IS NOT NULL)),
  CHECK ((loaded_outline_draft_revision IS NULL AND loaded_at IS NULL)
    OR (status = 'succeeded' AND loaded_outline_draft_revision IS NOT NULL
      AND loaded_outline_draft_revision > 0 AND loaded_at IS NOT NULL)),
  CHECK (status IN ('pending','succeeded','failed','superseded')),
  CHECK (
    (status = 'pending' AND active_slot IS NOT NULL AND active_slot = 1)
    OR (status IN ('succeeded','failed','superseded') AND active_slot IS NULL)
  ),
  CHECK (
    (status = 'pending' AND active_slot IS NOT NULL AND active_slot = 1
      AND result_content_json IS NULL AND result_content_hash IS NULL
      AND loaded_outline_draft_revision IS NULL AND loaded_at IS NULL
      AND failure_code IS NULL)
    OR (status = 'succeeded' AND active_slot IS NULL
      AND result_content_json IS NOT NULL AND result_content_hash IS NOT NULL
      AND failure_code IS NULL)
    OR (status = 'failed' AND active_slot IS NULL
      AND result_content_json IS NULL AND result_content_hash IS NULL
      AND loaded_outline_draft_revision IS NULL AND loaded_at IS NULL
      AND failure_code IS NOT NULL)
    OR (status = 'superseded' AND active_slot IS NULL
      AND loaded_outline_draft_revision IS NULL AND loaded_at IS NULL
      AND failure_code IS NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE chapter_outline_revisions (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL,
  revision INT NOT NULL,
  parent_revision INT NOT NULL,
  planning_revision_id CHAR(36) NOT NULL,
  planning_revision INT NOT NULL,
  planning_hash CHAR(64) NOT NULL,
  canon_revision INT NOT NULL,
  projection_revision INT NOT NULL,
  projection_hash CHAR(64) NOT NULL,
  content_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_outline_revision (project_id, chapter_num, revision),
  UNIQUE KEY uq_outline_revision_project_id (project_id, id),
  UNIQUE KEY uq_outline_revision_identity (project_id, id, revision, content_hash),
  UNIQUE KEY uq_outline_revision_chapter_identity (project_id, chapter_num, id, revision, content_hash),
  UNIQUE KEY uq_outline_revision_planning_identity (project_id, chapter_num, id, revision, content_hash, planning_revision_id, planning_revision, planning_hash),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, planning_revision_id, planning_revision, planning_hash) REFERENCES planning_revisions(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  CHECK (chapter_num > 0),
  CHECK (revision > 0),
  CHECK (parent_revision >= 0 AND parent_revision < revision),
  CHECK (planning_revision > 0),
  CHECK (canon_revision >= 0),
  CHECK (projection_revision >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE project_chapter_outline_heads (
  project_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL,
  revision INT NOT NULL,
  outline_revision_id CHAR(36) NULL,
  content_hash CHAR(64) NULL,
  updated_at BIGINT NOT NULL,
  PRIMARY KEY (project_id, chapter_num),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, chapter_num, outline_revision_id, revision, content_hash) REFERENCES chapter_outline_revisions(project_id, chapter_num, id, revision, content_hash) ON DELETE RESTRICT,
  CHECK (chapter_num > 0),
  CHECK (revision >= 0),
  CHECK (
    (revision = 0 AND outline_revision_id IS NULL AND content_hash IS NULL)
    OR (revision > 0 AND outline_revision_id IS NOT NULL
      AND content_hash IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE chapter_outline_confirmation_requests (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL,
  chapter_outline_draft_id CHAR(36) NOT NULL,
  draft_revision INT NOT NULL,
  draft_hash CHAR(64) NOT NULL,
  expected_head_revision INT NOT NULL,
  planning_revision_id CHAR(36) NOT NULL,
  planning_revision INT NOT NULL,
  planning_hash CHAR(64) NOT NULL,
  canon_revision INT NOT NULL,
  projection_revision INT NOT NULL,
  projection_hash CHAR(64) NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  request_fingerprint CHAR(64) NOT NULL,
  status VARCHAR(16) NOT NULL,
  outline_revision_id CHAR(36) NULL,
  result_revision INT NULL,
  result_hash CHAR(64) NULL,
  public_error_code VARCHAR(64) NULL,
  created_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_outline_confirmation_project_id (project_id, id),
  UNIQUE KEY uq_outline_confirmation_idempotency (project_id, chapter_num, idempotency_key),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, chapter_outline_draft_id, draft_revision, draft_hash) REFERENCES chapter_outline_drafts(project_id, id, draft_revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, planning_revision_id, planning_revision, planning_hash) REFERENCES planning_revisions(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, chapter_num, outline_revision_id, result_revision, result_hash, planning_revision_id, planning_revision, planning_hash) REFERENCES chapter_outline_revisions(project_id, chapter_num, id, revision, content_hash, planning_revision_id, planning_revision, planning_hash) ON DELETE RESTRICT,
  CHECK (chapter_num > 0),
  CHECK (draft_revision > 0),
  CHECK (expected_head_revision >= 0),
  CHECK (planning_revision > 0),
  CHECK (canon_revision >= 0),
  CHECK (projection_revision >= 0),
  CHECK (status IN ('pending','succeeded','failed')),
  CHECK (
    (status = 'pending' AND outline_revision_id IS NULL
      AND result_revision IS NULL AND result_hash IS NULL
      AND public_error_code IS NULL AND completed_at IS NULL)
    OR (status = 'succeeded' AND outline_revision_id IS NOT NULL
      AND result_revision IS NOT NULL AND result_revision > expected_head_revision
      AND result_hash IS NOT NULL
      AND public_error_code IS NULL AND completed_at IS NOT NULL)
    OR (status = 'failed' AND outline_revision_id IS NULL
      AND result_revision IS NULL AND result_hash IS NULL
      AND public_error_code IS NOT NULL AND completed_at IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
