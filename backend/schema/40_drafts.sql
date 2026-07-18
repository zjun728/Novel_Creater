CREATE TABLE chapter_sessions (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  selection_revision INT NOT NULL,
  contract_revision INT NOT NULL,
  contract_hash CHAR(64) NOT NULL,
  bible_revision INT NOT NULL,
  bible_hash CHAR(64) NOT NULL,
  volume_plan_id CHAR(36) NOT NULL,
  planning_manifest_hash CHAR(64) NOT NULL,
  story_block_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL,
  expected_canon_revision INT NOT NULL,
  expected_story_block_revision INT NOT NULL,
  planning_snapshot_json JSON NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  finalized_at BIGINT NULL,
  UNIQUE KEY uq_chapter_session_num (project_id, chapter_num),
  UNIQUE KEY uq_chapter_session_project_id (project_id, id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, selection_revision) REFERENCES project_seed_selection_revisions(project_id, selection_revision) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, contract_revision, contract_hash) REFERENCES creation_contracts(project_id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, bible_revision, bible_hash) REFERENCES creation_bible_revisions(project_id, revision, content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, volume_plan_id, planning_manifest_hash) REFERENCES volume_plans(project_id, id, manifest_hash) ON DELETE RESTRICT,
  FOREIGN KEY (project_id, volume_plan_id, story_block_id) REFERENCES story_blocks(project_id, volume_plan_id, id) ON DELETE RESTRICT,
  CHECK (chapter_num > 0),
  CHECK (selection_revision > 0),
  CHECK (contract_revision > 0),
  CHECK (bible_revision > 0),
  CHECK (expected_canon_revision >= 0),
  CHECK (expected_story_block_revision > 0),
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
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, chapter_session_id) REFERENCES chapter_sessions(project_id, id) ON DELETE CASCADE,
  CHECK (revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE draft_candidates (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_session_id CHAR(36) NOT NULL,
  working_draft_revision INT NOT NULL,
  content LONGTEXT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  provenance_json JSON NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_candidate_hash (chapter_session_id, content_hash),
  UNIQUE KEY uq_candidate_project_id (project_id, id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, chapter_session_id) REFERENCES chapter_sessions(project_id, id) ON DELETE CASCADE,
  CHECK (working_draft_revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE finalization_change_sets (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  draft_candidate_id CHAR(36) NOT NULL,
  extraction_id CHAR(36) NOT NULL,
  candidate_hash CHAR(64) NOT NULL,
  expected_canon_revision INT NOT NULL,
  expected_story_block_revision INT NOT NULL,
  payload_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  confirmed_at BIGINT NULL,
  UNIQUE KEY uq_changeset_candidate (draft_candidate_id, candidate_hash, expected_canon_revision),
  UNIQUE KEY uq_changeset_project_id (project_id, id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, draft_candidate_id) REFERENCES draft_candidates(project_id, id) ON DELETE CASCADE,
  CHECK (expected_canon_revision >= 0),
  CHECK (expected_story_block_revision > 0)
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
  story_block_revision INT NOT NULL,
  planning_snapshot_json JSON NOT NULL,
  finalized_at BIGINT NOT NULL,
  UNIQUE KEY uq_final_chapter_num (project_id, chapter_num),
  UNIQUE KEY uq_final_chapter_candidate (draft_candidate_id),
  UNIQUE KEY uq_final_chapter_record (finalization_record_id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, chapter_session_id) REFERENCES chapter_sessions(project_id, id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, draft_candidate_id) REFERENCES draft_candidates(project_id, id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, finalization_record_id) REFERENCES finalization_records(project_id, id) ON DELETE CASCADE,
  CHECK (chapter_num > 0),
  CHECK (canon_revision > 0),
  CHECK (story_block_revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
