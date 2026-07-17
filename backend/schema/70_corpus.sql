CREATE TABLE reference_uses (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_session_id CHAR(36) NOT NULL,
  draft_candidate_id CHAR(36) NOT NULL,
  corpus_source_id CHAR(36) NOT NULL,
  corpus_chapter_id CHAR(36) NOT NULL,
  location_start INT NOT NULL,
  location_end INT NOT NULL,
  reference_purpose VARCHAR(32) NOT NULL,
  referenced_text_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_reference_location (draft_candidate_id, corpus_chapter_id, location_start, location_end),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, chapter_session_id) REFERENCES chapter_sessions(project_id, id) ON DELETE CASCADE,
  FOREIGN KEY (project_id, draft_candidate_id) REFERENCES draft_candidates(project_id, id) ON DELETE CASCADE,
  FOREIGN KEY (corpus_source_id) REFERENCES corpus_sources(id) ON DELETE RESTRICT,
  FOREIGN KEY (corpus_chapter_id) REFERENCES corpus_chapters(id) ON DELETE RESTRICT,
  CHECK (location_start >= 0),
  CHECK (location_end > location_start),
  CHECK (reference_purpose IN ('generation','review','revision'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
