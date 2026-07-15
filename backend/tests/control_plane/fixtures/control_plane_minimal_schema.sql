CREATE TABLE projects (
  id CHAR(36) PRIMARY KEY,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE chapters (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL DEFAULT 0,
  final_version_id CHAR(36) DEFAULT NULL,
  status VARCHAR(20) DEFAULT 'drafting',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_chapters_project (project_id),
  INDEX idx_chapters_num (project_id, chapter_num),
  INDEX idx_chapters_status (project_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE chapter_versions (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  chapter_id CHAR(36) NOT NULL,
  chapter_num INT NOT NULL DEFAULT 0,
  title VARCHAR(200) DEFAULT '',
  content LONGTEXT NULL,
  version_type VARCHAR(30) DEFAULT 'ai_candidate',
  source_model_id CHAR(36) DEFAULT NULL,
  prompt_brief TEXT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_versions_project (project_id),
  INDEX idx_versions_chapter (chapter_id),
  INDEX idx_versions_type (version_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
