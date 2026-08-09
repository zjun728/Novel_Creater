CREATE TABLE chapter_sessions (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  planning_revision_id CHAR(36) NOT NULL,
  planning_revision INT NOT NULL,
  planning_hash CHAR(64) NOT NULL,
  story_block_id CHAR(36) NOT NULL,
  story_block_revision INT NOT NULL,
  story_block_hash CHAR(64) NOT NULL,
  chapter_outline_revision_id CHAR(36) NOT NULL,
  chapter_outline_revision INT NOT NULL,
  chapter_outline_hash CHAR(64) NOT NULL,
  chapter_num INT NOT NULL,
  expected_canon_revision INT NOT NULL,
  status VARCHAR(24) NOT NULL,
  draft_operation_fencing_token BIGINT NOT NULL DEFAULT 0,
  active_draft_operation_id CHAR(36) NULL,
  created_at BIGINT NOT NULL,
  finalized_at BIGINT NULL,
  UNIQUE KEY uq_chapter_session_num (project_id, chapter_num),
  UNIQUE KEY uq_chapter_session_project_id (project_id, id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, planning_revision_id, planning_revision, planning_hash) REFERENCES planning_revisions(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, chapter_num, chapter_outline_revision_id, chapter_outline_revision, chapter_outline_hash, planning_revision_id, planning_revision, planning_hash) REFERENCES chapter_outline_revisions(project_id, chapter_num, id, revision, content_hash, planning_revision_id, planning_revision, planning_hash) ON DELETE RESTRICT,
  CHECK (chapter_num > 0),
  CHECK (planning_revision > 0),
  CHECK (story_block_revision > 0),
  CHECK (chapter_outline_revision > 0),
  CHECK (expected_canon_revision >= 0),
  CHECK (draft_operation_fencing_token >= 0),
  CHECK (status IN ('drafting','final'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE working_drafts (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_session_id CHAR(36) NOT NULL,
  revision INT NOT NULL,
  content LONGTEXT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  source_payload_json JSON NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_working_draft_session (chapter_session_id),
  UNIQUE KEY uq_working_draft_owner (project_id, chapter_session_id, id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, chapter_session_id) REFERENCES chapter_sessions(project_id, id) ON DELETE CASCADE,
  CHECK (revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE draft_operation_attempts (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_session_id CHAR(36) NOT NULL,
  operation_type VARCHAR(40) NOT NULL,
  idempotency_key VARCHAR(64) NOT NULL,
  request_fingerprint CHAR(64) NOT NULL,
  active_slot TINYINT NULL,
  fencing_token BIGINT NOT NULL,
  lease_expires_at BIGINT NOT NULL,
  base_working_draft_revision INT NOT NULL,
  base_working_draft_hash CHAR(64) NOT NULL,
  input_manifest_json JSON NOT NULL,
  input_manifest_hash CHAR(64) NOT NULL,
  provider_id CHAR(36) NOT NULL,
  model_name_snapshot VARCHAR(200) NOT NULL,
  result_working_draft_revision INT NULL,
  result_content_hash CHAR(64) NULL,
  last_event_sequence INT NOT NULL,
  failure_code VARCHAR(64) NULL,
  partial_output_text LONGTEXT NOT NULL,
  partial_output_hash CHAR(64) NOT NULL,
  partial_output_scalars INT NOT NULL,
  heartbeat_at BIGINT NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  cancelled_at BIGINT NULL,
  UNIQUE KEY uq_draft_operation_idempotency
    (chapter_session_id, idempotency_key),
  UNIQUE KEY uq_draft_operation_active_slot
    (chapter_session_id, active_slot),
  UNIQUE KEY uq_draft_operation_fencing
    (chapter_session_id, fencing_token),
  UNIQUE KEY uq_draft_operation_project_id (project_id, id),
  UNIQUE KEY uq_draft_operation_owner (project_id, chapter_session_id, id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, chapter_session_id)
    REFERENCES chapter_sessions(project_id, id) ON DELETE CASCADE,
  FOREIGN KEY (provider_id) REFERENCES provider_profiles(id) ON DELETE RESTRICT,
  CHECK (active_slot IS NULL OR active_slot = 1),
  CHECK (fencing_token > 0),
  CHECK (lease_expires_at >= created_at),
  CHECK (base_working_draft_revision > 0),
  CHECK (last_event_sequence >= 0),
  CHECK (partial_output_scalars BETWEEN 0 AND 100000),
  CHECK (heartbeat_at >= created_at),
  CHECK (
    (status = 'cancelled' AND cancelled_at IS NOT NULL)
    OR (status <> 'cancelled' AND cancelled_at IS NULL)
  ),
  CHECK (
    (result_working_draft_revision IS NULL AND result_content_hash IS NULL)
    OR (result_working_draft_revision IS NOT NULL
      AND result_working_draft_revision > base_working_draft_revision
      AND result_content_hash IS NOT NULL)
  ),
  CHECK (operation_type IN ('generate_new','rewrite_selection','polish_selection','expand_selection','compress_selection')),
  CHECK (status IN ('starting','running','completed','failed','cancelled','expired')),
  CHECK (
    (status IN ('starting','running') AND active_slot IS NOT NULL AND active_slot = 1
      AND result_working_draft_revision IS NULL AND result_content_hash IS NULL
      AND failure_code IS NULL AND completed_at IS NULL AND cancelled_at IS NULL)
    OR (status = 'completed' AND active_slot IS NULL
      AND result_working_draft_revision IS NOT NULL
      AND result_content_hash IS NOT NULL AND failure_code IS NULL
      AND completed_at IS NOT NULL)
    OR (status = 'failed' AND active_slot IS NULL
      AND result_working_draft_revision IS NULL AND result_content_hash IS NULL
      AND failure_code IS NOT NULL AND completed_at IS NOT NULL)
    OR (status = 'cancelled' AND active_slot IS NULL
      AND failure_code IS NULL AND completed_at IS NOT NULL AND cancelled_at IS NOT NULL)
    OR (status = 'expired' AND active_slot IS NULL
      AND result_working_draft_revision IS NULL AND result_content_hash IS NULL
      AND failure_code IS NULL AND completed_at IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE working_draft_revisions (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_session_id CHAR(36) NOT NULL,
  working_draft_id CHAR(36) NOT NULL,
  working_draft_revision INT NOT NULL,
  snapshot_role VARCHAR(24) NOT NULL,
  replacement_reason VARCHAR(40) NOT NULL,
  source_operation_id CHAR(36) NOT NULL,
  content LONGTEXT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_working_draft_recovery
    (chapter_session_id, working_draft_revision, snapshot_role),
  FOREIGN KEY (project_id, chapter_session_id, working_draft_id)
    REFERENCES working_drafts(project_id, chapter_session_id, id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, chapter_session_id, source_operation_id)
    REFERENCES draft_operation_attempts(project_id, chapter_session_id, id) ON DELETE CASCADE,
  CHECK (working_draft_revision > 0),
  CHECK (snapshot_role IN ('before','after')),
  CHECK (replacement_reason IN ('generate_new','rewrite_selection','polish_selection','expand_selection','compress_selection','undo_local'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE draft_operation_events (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  draft_operation_id CHAR(36) NOT NULL,
  sequence_num INT NOT NULL,
  event_type VARCHAR(16) NOT NULL,
  closed_payload_json JSON NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_draft_operation_event_sequence
    (draft_operation_id, sequence_num),
  FOREIGN KEY (project_id, draft_operation_id)
    REFERENCES draft_operation_attempts(project_id, id)
    ON DELETE CASCADE,
  CHECK (sequence_num BETWEEN 1 AND 2048),
  CHECK (event_type IN ('started','delta','heartbeat','completed','failed','cancelled')),
  CHECK (
    (event_type IN ('started','heartbeat') AND closed_payload_json IS NULL)
    OR (event_type IN ('delta','completed','failed','cancelled')
      AND closed_payload_json IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE draft_candidates (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_session_id CHAR(36) NOT NULL,
  working_draft_revision INT NOT NULL,
  content LONGTEXT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  basis_hash CHAR(64) NOT NULL,
  provenance_json JSON NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_candidate_identity (chapter_session_id, content_hash, basis_hash),
  UNIQUE KEY uq_candidate_project_id (project_id, id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, chapter_session_id) REFERENCES chapter_sessions(project_id, id) ON DELETE CASCADE,
  CHECK (working_draft_revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE candidate_freeze_requests (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_session_id CHAR(36) NOT NULL,
  idempotency_key VARCHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  draft_candidate_id CHAR(36) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_candidate_freeze_idempotency
    (chapter_session_id, idempotency_key),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, chapter_session_id)
    REFERENCES chapter_sessions(project_id, id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, draft_candidate_id)
    REFERENCES draft_candidates(project_id, id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE finalization_change_sets (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  draft_candidate_id CHAR(36) NOT NULL,
  extraction_id CHAR(36) NOT NULL,
  candidate_hash CHAR(64) NOT NULL,
  expected_canon_revision INT NOT NULL,
  expected_planning_hash CHAR(64) NOT NULL,
  expected_outline_hash CHAR(64) NOT NULL,
  payload_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  confirmed_at BIGINT NULL,
  UNIQUE KEY uq_changeset_candidate (draft_candidate_id, candidate_hash, expected_canon_revision),
  UNIQUE KEY uq_changeset_project_id (project_id, id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, draft_candidate_id) REFERENCES draft_candidates(project_id, id) ON DELETE CASCADE,
  CHECK (expected_canon_revision >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE finalization_records (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_session_id CHAR(36) NOT NULL,
  draft_candidate_id CHAR(36) NOT NULL,
  change_set_id CHAR(36) NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  candidate_hash CHAR(64) NOT NULL,
  change_set_hash CHAR(64) NOT NULL,
  expected_canon_revision INT NOT NULL,
  committed_canon_revision INT NOT NULL,
  result_payload_json JSON NOT NULL,
  finalized_at BIGINT NOT NULL,
  UNIQUE KEY uq_finalization_idempotency (idempotency_key),
  UNIQUE KEY uq_finalization_session (chapter_session_id),
  UNIQUE KEY uq_finalization_project_id (project_id, id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, chapter_session_id) REFERENCES chapter_sessions(project_id, id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, draft_candidate_id) REFERENCES draft_candidates(project_id, id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, change_set_id) REFERENCES finalization_change_sets(project_id, id) ON DELETE CASCADE,
  CHECK (expected_canon_revision >= 0),
  CHECK (committed_canon_revision > expected_canon_revision)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE final_chapters (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_session_id CHAR(36) NOT NULL,
  draft_candidate_id CHAR(36) NOT NULL,
  finalization_record_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL,
  title VARCHAR(300) NOT NULL,
  content LONGTEXT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  canon_revision INT NOT NULL,
  planning_revision_id CHAR(36) NOT NULL,
  planning_revision INT NOT NULL,
  planning_hash CHAR(64) NOT NULL,
  chapter_outline_revision_id CHAR(36) NOT NULL,
  chapter_outline_revision INT NOT NULL,
  chapter_outline_hash CHAR(64) NOT NULL,
  finalized_at BIGINT NOT NULL,
  UNIQUE KEY uq_final_chapter_num (project_id, chapter_session_id, chapter_num),
  UNIQUE KEY uq_final_chapter_candidate (draft_candidate_id),
  UNIQUE KEY uq_final_chapter_record (finalization_record_id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, chapter_session_id) REFERENCES chapter_sessions(project_id, id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, draft_candidate_id) REFERENCES draft_candidates(project_id, id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, finalization_record_id) REFERENCES finalization_records(project_id, id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, planning_revision_id, planning_revision, planning_hash) REFERENCES planning_revisions(project_id, id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, chapter_num, chapter_outline_revision_id, chapter_outline_revision, chapter_outline_hash, planning_revision_id, planning_revision, planning_hash) REFERENCES chapter_outline_revisions(project_id, chapter_num, id, revision, content_hash, planning_revision_id, planning_revision, planning_hash) ON DELETE RESTRICT,
  CHECK (chapter_num > 0),
  CHECK (canon_revision > 0),
  CHECK (planning_revision > 0),
  CHECK (chapter_outline_revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
