CREATE TABLE style_templates (
  id CHAR(36) PRIMARY KEY,
  stable_key VARCHAR(160) NOT NULL,
  revision INT NOT NULL,
  name VARCHAR(200) NOT NULL,
  payload_json JSON NOT NULL,
  provenance_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_style_template_revision (stable_key, revision),
  UNIQUE KEY uq_style_template_head_ref (stable_key, id, revision, content_hash),
  UNIQUE KEY uq_style_template_contract_ref (id, revision, content_hash),
  CHECK (revision > 0),
  CHECK (status IN ('active','archived'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE style_template_heads (
  stable_key VARCHAR(160) PRIMARY KEY,
  style_template_id CHAR(36) NOT NULL,
  revision INT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  updated_at BIGINT NOT NULL,
  FOREIGN KEY (stable_key, style_template_id, revision, content_hash) REFERENCES style_templates(stable_key, id, revision, content_hash) ON DELETE RESTRICT,
  CHECK (revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE experience_cards (
  id CHAR(36) PRIMARY KEY,
  stable_key VARCHAR(160) NOT NULL,
  revision INT NOT NULL,
  title VARCHAR(200) NOT NULL,
  category VARCHAR(32) NOT NULL,
  payload_json JSON NOT NULL,
  provenance_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_experience_card_revision (stable_key, revision),
  UNIQUE KEY uq_experience_card_head_ref (stable_key, id, revision, content_hash),
  UNIQUE KEY uq_experience_card_contract_ref (id, revision, content_hash),
  CHECK (revision > 0),
  CHECK (category IN ('plot_organization','ensemble','dialogue','emotion','interiority','information_release','pacing','suspense','long_arc_continuity','progression_economy','character_arcs','action_conflict')),
  CHECK (status IN ('active','archived'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE experience_card_heads (
  stable_key VARCHAR(160) PRIMARY KEY,
  experience_card_id CHAR(36) NOT NULL,
  revision INT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  updated_at BIGINT NOT NULL,
  FOREIGN KEY (stable_key, experience_card_id, revision, content_hash) REFERENCES experience_cards(stable_key, id, revision, content_hash) ON DELETE RESTRICT,
  CHECK (revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE corpus_blobs (
  content_hash CHAR(64) PRIMARY KEY,
  byte_length BIGINT NOT NULL,
  storage_key VARCHAR(2048) NOT NULL,
  created_at BIGINT NOT NULL,
  CHECK (byte_length >= 0),
  CHECK (CHAR_LENGTH(TRIM(storage_key)) > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE corpus_sources (
  id CHAR(36) PRIMARY KEY,
  source_key VARCHAR(200) NOT NULL,
  archived_at BIGINT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_corpus_source_key (source_key),
  UNIQUE KEY uq_corpus_source_identity (source_key, id),
  CHECK (CHAR_LENGTH(TRIM(source_key)) > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE corpus_source_revisions (
  id CHAR(36) PRIMARY KEY,
  source_id CHAR(36) NOT NULL,
  revision INT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  relative_path VARCHAR(2048) NOT NULL,
  display_name VARCHAR(300) NOT NULL,
  author VARCHAR(200) NOT NULL,
  reference_tags_json JSON NOT NULL,
  notes TEXT NOT NULL,
  provenance_json JSON NOT NULL,
  byte_length BIGINT NOT NULL,
  encoding VARCHAR(64) NOT NULL,
  parser_version VARCHAR(64) NOT NULL,
  normalizer_version VARCHAR(64) NOT NULL,
  fragmenter_version VARCHAR(64) NOT NULL,
  index_version VARCHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  public_error_code VARCHAR(64) NULL,
  imported_at BIGINT NOT NULL,
  analyzed_at BIGINT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_corpus_source_revision (source_id, revision),
  UNIQUE KEY uq_corpus_source_revision_hash (source_id, revision, content_hash),
  UNIQUE KEY uq_corpus_source_revision_id (source_id, id),
  UNIQUE KEY uq_corpus_source_revision_identity (source_id, id, revision, content_hash),
  UNIQUE KEY uq_corpus_source_import (content_hash, parser_version, normalizer_version, fragmenter_version, index_version),
  FOREIGN KEY (source_id) REFERENCES corpus_sources(id) ON DELETE RESTRICT,
  FOREIGN KEY (content_hash) REFERENCES corpus_blobs(content_hash) ON DELETE RESTRICT,
  CHECK (revision > 0),
  CHECK (byte_length >= 0),
  CHECK (status IN ('imported','analyzed','failed')),
  CHECK (
    (status = 'imported' AND public_error_code IS NULL AND analyzed_at IS NULL)
    OR (status = 'analyzed' AND public_error_code IS NULL
      AND analyzed_at IS NOT NULL AND analyzed_at >= imported_at)
    OR (status = 'failed' AND public_error_code IS NOT NULL AND analyzed_at IS NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE corpus_source_heads (
  source_id CHAR(36) PRIMARY KEY,
  revision_id CHAR(36) NOT NULL,
  revision INT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  updated_at BIGINT NOT NULL,
  FOREIGN KEY (source_id, revision_id, revision, content_hash) REFERENCES corpus_source_revisions(source_id, id, revision, content_hash) ON DELETE RESTRICT,
  CHECK (revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE corpus_chapters (
  id CHAR(36) PRIMARY KEY,
  corpus_source_id CHAR(36) NOT NULL,
  source_revision_id CHAR(36) NOT NULL,
  source_revision INT NOT NULL,
  source_hash CHAR(64) NOT NULL,
  chapter_order INT NOT NULL,
  title VARCHAR(300) NOT NULL,
  raw_byte_start BIGINT NOT NULL,
  raw_byte_end BIGINT NOT NULL,
  normalized_char_start BIGINT NOT NULL,
  normalized_char_end BIGINT NOT NULL,
  normalized_text LONGTEXT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_corpus_chapter_order (source_revision_id, chapter_order),
  UNIQUE KEY uq_corpus_chapter_source_id (corpus_source_id, id),
  UNIQUE KEY uq_corpus_chapter_identity (corpus_source_id, id, content_hash),
  FOREIGN KEY (corpus_source_id, source_revision_id, source_revision, source_hash) REFERENCES corpus_source_revisions(source_id, id, revision, content_hash) ON DELETE RESTRICT,
  CHECK (source_revision > 0),
  CHECK (chapter_order > 0),
  CHECK (raw_byte_start >= 0 AND raw_byte_end >= raw_byte_start),
  CHECK (normalized_char_start >= 0 AND normalized_char_end >= normalized_char_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE corpus_fragments (
  id CHAR(36) PRIMARY KEY,
  corpus_source_id CHAR(36) NOT NULL,
  corpus_chapter_id CHAR(36) NOT NULL,
  fragment_order INT NOT NULL,
  chapter_char_start BIGINT NOT NULL,
  chapter_char_end BIGINT NOT NULL,
  normalized_text LONGTEXT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  index_payload JSON NOT NULL,
  analysis_version VARCHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_corpus_fragment_order (corpus_chapter_id, fragment_order),
  UNIQUE KEY uq_corpus_fragment_source_id (corpus_source_id, id),
  UNIQUE KEY uq_corpus_fragment_identity (corpus_source_id, corpus_chapter_id, id, content_hash),
  FOREIGN KEY (corpus_source_id, corpus_chapter_id) REFERENCES corpus_chapters(corpus_source_id, id) ON DELETE RESTRICT,
  CHECK (fragment_order > 0),
  CHECK (chapter_char_start >= 0 AND chapter_char_end > chapter_char_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE corpus_import_runs (
  id CHAR(36) PRIMARY KEY,
  idempotency_key CHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  relative_path VARCHAR(2048) NOT NULL,
  content_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  corpus_source_id CHAR(36) NULL,
  source_revision_id CHAR(36) NULL,
  source_revision INT NULL,
  public_error_code VARCHAR(64) NULL,
  parser_versions_json JSON NOT NULL,
  created_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_corpus_import_idempotency (idempotency_key),
  FOREIGN KEY (content_hash) REFERENCES corpus_blobs(content_hash) ON DELETE RESTRICT,
  FOREIGN KEY (corpus_source_id, source_revision_id, source_revision, content_hash) REFERENCES corpus_source_revisions(source_id, id, revision, content_hash) ON DELETE RESTRICT,
  CHECK (status IN ('reserved','running','succeeded','failed')),
  CHECK (
    (status IN ('reserved','running') AND corpus_source_id IS NULL
      AND source_revision_id IS NULL AND source_revision IS NULL
      AND public_error_code IS NULL AND completed_at IS NULL)
    OR (status = 'succeeded' AND corpus_source_id IS NOT NULL
      AND source_revision_id IS NOT NULL AND source_revision > 0
      AND public_error_code IS NULL AND completed_at IS NOT NULL)
    OR (status = 'failed' AND corpus_source_id IS NULL
      AND source_revision_id IS NULL AND source_revision IS NULL
      AND public_error_code IS NOT NULL AND completed_at IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
