CREATE TABLE corpus_sources (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  source_path VARCHAR(2048) NOT NULL,
  source_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  imported_at BIGINT NOT NULL,
  analyzed_at BIGINT NULL,
  UNIQUE KEY uq_corpus_source_hash (project_id, source_hash),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CHECK (status IN ('imported','analyzed','failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE corpus_chapters (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  corpus_source_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL,
  title VARCHAR(300) NOT NULL,
  normalized_text LONGTEXT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_corpus_chapter_num (corpus_source_id, chapter_num),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (corpus_source_id) REFERENCES corpus_sources(id) ON DELETE CASCADE,
  CHECK (chapter_num > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE style_templates (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  name VARCHAR(200) NOT NULL,
  revision INT NOT NULL,
  payload_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_style_template_name (project_id, name, revision),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CHECK (revision > 0),
  CHECK (status IN ('active','archived'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE experience_cards (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  title VARCHAR(200) NOT NULL,
  category VARCHAR(64) NOT NULL,
  revision INT NOT NULL,
  payload_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_experience_card_title (project_id, title, revision),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CHECK (revision > 0),
  CHECK (status IN ('active','archived'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

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
  FOREIGN KEY (chapter_session_id) REFERENCES chapter_sessions(id) ON DELETE RESTRICT,
  FOREIGN KEY (draft_candidate_id) REFERENCES draft_candidates(id) ON DELETE RESTRICT,
  FOREIGN KEY (corpus_source_id) REFERENCES corpus_sources(id) ON DELETE RESTRICT,
  FOREIGN KEY (corpus_chapter_id) REFERENCES corpus_chapters(id) ON DELETE RESTRICT,
  CHECK (location_start >= 0),
  CHECK (location_end > location_start),
  CHECK (reference_purpose IN ('generation','review','revision'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement
