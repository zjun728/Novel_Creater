CREATE TABLE topic_discussions (
  id CHAR(36) PRIMARY KEY,
  title VARCHAR(300) NOT NULL,
  status VARCHAR(16) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  CHECK (status IN ('active'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE topic_discussion_messages (
  id CHAR(36) PRIMARY KEY,
  discussion_id CHAR(36) NOT NULL,
  sequence_number INT NOT NULL,
  role VARCHAR(16) NOT NULL,
  content_text MEDIUMTEXT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_topic_message_sequence (discussion_id, sequence_number),
  UNIQUE KEY uq_topic_message_owner (discussion_id, id),
  FOREIGN KEY (discussion_id) REFERENCES topic_discussions(id) ON DELETE RESTRICT,
  CHECK (sequence_number > 0),
  CHECK (role IN ('user','assistant'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE topic_discussion_requests (
  id CHAR(36) PRIMARY KEY,
  discussion_id CHAR(36) NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  input_manifest_json JSON NOT NULL,
  input_manifest_hash CHAR(64) NOT NULL,
  provider_id CHAR(36) NULL,
  provider_name_snapshot VARCHAR(120) NULL,
  model_name_snapshot VARCHAR(160) NULL,
  provider_config_hash CHAR(64) NULL,
  status VARCHAR(24) NOT NULL,
  user_message_id CHAR(36) NOT NULL,
  assistant_message_id CHAR(36) NULL,
  result_json JSON NULL,
  result_hash CHAR(64) NULL,
  public_error_code VARCHAR(64) NULL,
  created_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_topic_request_idempotency (discussion_id, idempotency_key),
  UNIQUE KEY uq_topic_request_owner (discussion_id, id),
  FOREIGN KEY (discussion_id) REFERENCES topic_discussions(id) ON DELETE RESTRICT,
  FOREIGN KEY (discussion_id, user_message_id) REFERENCES topic_discussion_messages(discussion_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (discussion_id, assistant_message_id) REFERENCES topic_discussion_messages(discussion_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (provider_id) REFERENCES provider_profiles(id) ON DELETE RESTRICT,
  CHECK (status IN ('reserved','running','succeeded','failed','outcome_unknown')),
  CHECK (
    (status IN ('reserved','running')
      AND assistant_message_id IS NULL
      AND result_json IS NULL AND result_hash IS NULL
      AND public_error_code IS NULL AND completed_at IS NULL)
    OR (status = 'succeeded'
      AND provider_id IS NOT NULL
      AND assistant_message_id IS NOT NULL
      AND result_json IS NOT NULL AND result_hash IS NOT NULL
      AND public_error_code IS NULL AND completed_at IS NOT NULL)
    OR (status IN ('failed','outcome_unknown')
      AND assistant_message_id IS NULL
      AND result_json IS NULL AND result_hash IS NULL
      AND public_error_code IS NOT NULL AND completed_at IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE topic_directions (
  id CHAR(36) PRIMARY KEY,
  current_version INT NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  CHECK (current_version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE topic_direction_versions (
  id CHAR(36) PRIMARY KEY,
  direction_id CHAR(36) NOT NULL,
  version INT NOT NULL,
  payload_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  discussion_id CHAR(36) NOT NULL,
  basis_json JSON NOT NULL,
  basis_hash CHAR(64) NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_topic_direction_version (direction_id, version),
  UNIQUE KEY uq_topic_direction_version_id (direction_id, id),
  UNIQUE KEY uq_topic_direction_version_fact (direction_id, version, content_hash),
  UNIQUE KEY uq_topic_direction_idempotency (idempotency_key),
  FOREIGN KEY (direction_id) REFERENCES topic_directions(id) ON DELETE RESTRICT,
  FOREIGN KEY (discussion_id) REFERENCES topic_discussions(id) ON DELETE RESTRICT,
  CHECK (version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE topic_candidates (
  id CHAR(36) PRIMARY KEY,
  status VARCHAR(16) NOT NULL,
  current_version INT NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  CHECK (status IN ('active','archived')),
  CHECK (current_version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE topic_candidate_versions (
  id CHAR(36) PRIMARY KEY,
  candidate_id CHAR(36) NOT NULL,
  version INT NOT NULL,
  payload_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  discussion_id CHAR(36) NOT NULL,
  basis_json JSON NOT NULL,
  basis_hash CHAR(64) NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_topic_candidate_version (candidate_id, version),
  UNIQUE KEY uq_topic_candidate_version_id (candidate_id, id),
  UNIQUE KEY uq_topic_candidate_version_fact (candidate_id, version, content_hash),
  UNIQUE KEY uq_topic_candidate_idempotency (idempotency_key),
  FOREIGN KEY (candidate_id) REFERENCES topic_candidates(id) ON DELETE RESTRICT,
  FOREIGN KEY (discussion_id) REFERENCES topic_discussions(id) ON DELETE RESTRICT,
  CHECK (version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE topic_project_handoffs (
  id CHAR(36) PRIMARY KEY,
  candidate_id CHAR(36) NOT NULL,
  candidate_version INT NOT NULL,
  candidate_hash CHAR(64) NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  project_id CHAR(36) NOT NULL,
  seed_id CHAR(36) NOT NULL,
  seed_revision_id CHAR(36) NOT NULL,
  seed_revision INT NOT NULL,
  seed_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_topic_handoff_idempotency (idempotency_key),
  UNIQUE KEY uq_topic_handoff_project (project_id),
  FOREIGN KEY (candidate_id, candidate_version, candidate_hash) REFERENCES topic_candidate_versions(candidate_id, version, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, seed_id, seed_revision_id, seed_hash) REFERENCES creative_seed_revisions(project_id, seed_id, id, content_hash) ON DELETE RESTRICT,
  CHECK (candidate_version > 0),
  CHECK (seed_revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
