CREATE TABLE story_engine_batches (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  source_type VARCHAR(16) NOT NULL,
  seed_id CHAR(36) NOT NULL,
  seed_revision_id CHAR(36) NOT NULL,
  seed_hash CHAR(64) NOT NULL,
  binding_revision_id CHAR(36) NULL,
  binding_hash CHAR(64) NULL,
  provider_id CHAR(36) NULL,
  model_name_snapshot VARCHAR(160) NULL,
  idempotency_key CHAR(64) NOT NULL,
  request_json JSON NOT NULL,
  request_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  attempt_id CHAR(36) NULL,
  attempt_started_at BIGINT NULL,
  lease_expires_at BIGINT NULL,
  raw_response_text LONGTEXT NULL,
  raw_response_hash CHAR(64) NULL,
  public_error_code VARCHAR(64) NULL,
  created_at BIGINT NOT NULL,
  finished_at BIGINT NULL,
  UNIQUE KEY uq_engine_batch_idempotency (project_id, idempotency_key),
  UNIQUE KEY uq_engine_batch_project_id (project_id, id),
  FOREIGN KEY (project_id, seed_id) REFERENCES creative_seeds(project_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (seed_id, seed_revision_id) REFERENCES creative_seed_revisions(seed_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, binding_revision_id) REFERENCES project_model_binding_revisions(project_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (provider_id) REFERENCES provider_profiles(id) ON DELETE RESTRICT,
  CHECK (source_type IN ('provider','manual')),
  CHECK (status IN ('reserved','running','succeeded','failed','outcome_unknown')),
  CHECK ((raw_response_text IS NULL AND raw_response_hash IS NULL)
    OR (raw_response_text IS NOT NULL AND raw_response_hash IS NOT NULL)),
  CHECK (
    (source_type = 'manual' AND binding_revision_id IS NULL AND binding_hash IS NULL
      AND provider_id IS NULL AND model_name_snapshot IS NULL AND attempt_id IS NULL
      AND attempt_started_at IS NULL AND lease_expires_at IS NULL
      AND raw_response_text IS NULL AND raw_response_hash IS NULL
      AND status = 'succeeded' AND public_error_code IS NULL AND finished_at IS NOT NULL)
    OR (source_type = 'provider' AND binding_revision_id IS NOT NULL
      AND binding_hash IS NOT NULL AND provider_id IS NOT NULL
      AND model_name_snapshot IS NOT NULL)
  ),
  CHECK (
    source_type = 'manual'
    OR (status = 'reserved' AND attempt_id IS NULL AND attempt_started_at IS NULL
      AND lease_expires_at IS NULL AND raw_response_text IS NULL
      AND raw_response_hash IS NULL AND public_error_code IS NULL AND finished_at IS NULL)
    OR (status = 'running' AND attempt_id IS NOT NULL AND attempt_started_at IS NOT NULL
      AND lease_expires_at IS NOT NULL AND raw_response_text IS NULL
      AND raw_response_hash IS NULL AND public_error_code IS NULL AND finished_at IS NULL)
    OR (status = 'succeeded' AND attempt_id IS NOT NULL AND attempt_started_at IS NOT NULL
      AND lease_expires_at IS NOT NULL AND raw_response_text IS NOT NULL
      AND raw_response_hash IS NOT NULL
      AND public_error_code IS NULL AND finished_at IS NOT NULL)
    OR (status IN ('failed','outcome_unknown') AND attempt_id IS NOT NULL
      AND attempt_started_at IS NOT NULL AND lease_expires_at IS NOT NULL
      AND public_error_code IS NOT NULL AND finished_at IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE story_engine_options (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  batch_id CHAR(36) NOT NULL,
  option_order INT NOT NULL,
  payload_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_engine_option_order (batch_id, option_order),
  UNIQUE KEY uq_engine_option_hash (batch_id, content_hash),
  UNIQUE KEY uq_engine_option_project_id (project_id, id),
  FOREIGN KEY (project_id, batch_id) REFERENCES story_engine_batches(project_id, id) ON DELETE RESTRICT,
  CHECK (option_order BETWEEN 1 AND 3)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE project_contract_drafts (
  project_id CHAR(36) PRIMARY KEY,
  id CHAR(36) NOT NULL,
  base_head_revision INT NOT NULL,
  seed_revision_id CHAR(36) NOT NULL,
  seed_hash CHAR(64) NOT NULL,
  engine_option_id CHAR(36) NULL,
  draft_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  draft_version INT NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_contract_draft_id (id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, seed_revision_id) REFERENCES creative_seed_revisions(project_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, engine_option_id) REFERENCES story_engine_options(project_id, id) ON DELETE RESTRICT,
  CHECK (base_head_revision >= 0),
  CHECK (draft_version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE creation_contracts (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  revision INT NOT NULL,
  seed_id CHAR(36) NOT NULL,
  seed_revision_id CHAR(36) NOT NULL,
  seed_hash CHAR(64) NOT NULL,
  binding_revision_id CHAR(36) NOT NULL,
  binding_hash CHAR(64) NOT NULL,
  channel_profile_key VARCHAR(120) NOT NULL,
  genre_profile_key VARCHAR(120) NOT NULL,
  quality_charter_version INT NOT NULL,
  total_word_min INT NOT NULL,
  total_word_max INT NOT NULL,
  chapter_char_min INT NOT NULL,
  chapter_char_target INT NOT NULL,
  chapter_char_max INT NOT NULL,
  content_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  confirmed_at BIGINT NOT NULL,
  UNIQUE KEY uq_creation_contract_revision (project_id, revision),
  UNIQUE KEY uq_creation_contract_id (project_id, id),
  UNIQUE KEY uq_creation_contract_identity (project_id, id, revision),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, seed_id) REFERENCES creative_seeds(project_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (seed_id, seed_revision_id) REFERENCES creative_seed_revisions(seed_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, binding_revision_id) REFERENCES project_model_binding_revisions(project_id, id) ON DELETE RESTRICT,
  CHECK (revision > 0),
  CHECK (quality_charter_version > 0),
  CHECK (total_word_min > 0 AND total_word_max >= total_word_min),
  CHECK (chapter_char_min > 0 AND chapter_char_target >= chapter_char_min AND chapter_char_max >= chapter_char_target)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE style_contracts (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  creation_contract_id CHAR(36) NOT NULL,
  revision INT NOT NULL,
  merged_style_json JSON NOT NULL,
  likes_json JSON NOT NULL,
  dislikes_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  confirmed_at BIGINT NOT NULL,
  UNIQUE KEY uq_style_contract_revision (project_id, revision),
  UNIQUE KEY uq_style_contract_creation (creation_contract_id),
  UNIQUE KEY uq_style_contract_id (project_id, id),
  UNIQUE KEY uq_style_contract_identity (project_id, id, revision),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, creation_contract_id, revision) REFERENCES creation_contracts(project_id, id, revision) ON DELETE RESTRICT,
  CHECK (revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE project_contract_heads (
  project_id CHAR(36) PRIMARY KEY,
  revision INT NOT NULL,
  creation_contract_id CHAR(36) NULL,
  style_contract_id CHAR(36) NULL,
  creation_hash CHAR(64) NULL,
  style_hash CHAR(64) NULL,
  updated_at BIGINT NOT NULL,
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, creation_contract_id) REFERENCES creation_contracts(project_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, creation_contract_id, revision) REFERENCES creation_contracts(project_id, id, revision) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, style_contract_id) REFERENCES style_contracts(project_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, style_contract_id, revision) REFERENCES style_contracts(project_id, id, revision) ON DELETE RESTRICT,
  CHECK (revision >= 0),
  CHECK ((revision = 0 AND creation_contract_id IS NULL AND style_contract_id IS NULL
      AND creation_hash IS NULL AND style_hash IS NULL)
    OR (revision > 0 AND creation_contract_id IS NOT NULL AND style_contract_id IS NOT NULL
      AND creation_hash IS NOT NULL AND style_hash IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE contract_confirmation_requests (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  status VARCHAR(16) NOT NULL,
  creation_contract_id CHAR(36) NULL,
  style_contract_id CHAR(36) NULL,
  result_revision INT NULL,
  public_error_code VARCHAR(64) NULL,
  created_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_contract_confirmation_idempotency (project_id, idempotency_key),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, creation_contract_id, result_revision) REFERENCES creation_contracts(project_id, id, revision) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, style_contract_id, result_revision) REFERENCES style_contracts(project_id, id, revision) ON DELETE RESTRICT,
  CHECK (status IN ('reserved','succeeded','failed')),
  CHECK (
    (status = 'reserved' AND creation_contract_id IS NULL AND style_contract_id IS NULL
      AND result_revision IS NULL AND public_error_code IS NULL AND completed_at IS NULL)
    OR (status = 'succeeded' AND creation_contract_id IS NOT NULL
      AND style_contract_id IS NOT NULL AND result_revision > 0
      AND public_error_code IS NULL AND completed_at IS NOT NULL)
    OR (status = 'failed' AND creation_contract_id IS NULL AND style_contract_id IS NULL
      AND result_revision IS NULL AND public_error_code IS NOT NULL
      AND completed_at IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE creation_contract_engine_refs (
  creation_contract_id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  engine_option_id CHAR(36) NOT NULL,
  engine_hash CHAR(64) NOT NULL,
  FOREIGN KEY (project_id, creation_contract_id) REFERENCES creation_contracts(project_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, engine_option_id) REFERENCES story_engine_options(project_id, id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE style_contract_template_refs (
  style_contract_id CHAR(36) NOT NULL,
  role VARCHAR(16) NOT NULL,
  style_template_id CHAR(36) NOT NULL,
  asset_revision INT NOT NULL,
  asset_hash CHAR(64) NOT NULL,
  sort_order INT NOT NULL,
  PRIMARY KEY (style_contract_id, role),
  UNIQUE KEY uq_style_template_asset (style_contract_id, style_template_id),
  UNIQUE KEY uq_style_template_sort (style_contract_id, sort_order),
  FOREIGN KEY (style_contract_id) REFERENCES style_contracts(id) ON DELETE RESTRICT,
  FOREIGN KEY (style_template_id, asset_revision) REFERENCES style_templates(id, revision) ON DELETE RESTRICT,
  CHECK (role IN ('primary','secondary')),
  CHECK (asset_revision > 0),
  CHECK (sort_order > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE creation_contract_experience_refs (
  creation_contract_id CHAR(36) NOT NULL,
  experience_card_id CHAR(36) NOT NULL,
  asset_revision INT NOT NULL,
  asset_hash CHAR(64) NOT NULL,
  sort_order INT NOT NULL,
  PRIMARY KEY (creation_contract_id, experience_card_id),
  UNIQUE KEY uq_experience_ref_sort (creation_contract_id, sort_order),
  FOREIGN KEY (creation_contract_id) REFERENCES creation_contracts(id) ON DELETE RESTRICT,
  FOREIGN KEY (experience_card_id, asset_revision) REFERENCES experience_cards(id, revision) ON DELETE RESTRICT,
  CHECK (asset_revision > 0),
  CHECK (sort_order > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE creation_contract_corpus_refs (
  creation_contract_id CHAR(36) NOT NULL,
  corpus_source_id CHAR(36) NOT NULL,
  source_revision INT NOT NULL,
  source_hash CHAR(64) NOT NULL,
  selection_mode VARCHAR(16) NOT NULL,
  sort_order INT NOT NULL,
  PRIMARY KEY (creation_contract_id, corpus_source_id),
  UNIQUE KEY uq_corpus_ref_sort (creation_contract_id, sort_order),
  FOREIGN KEY (creation_contract_id) REFERENCES creation_contracts(id) ON DELETE RESTRICT,
  FOREIGN KEY (corpus_source_id, source_revision) REFERENCES corpus_sources(id, revision) ON DELETE RESTRICT,
  CHECK (source_revision > 0),
  CHECK (selection_mode IN ('author','system')),
  CHECK (sort_order > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
