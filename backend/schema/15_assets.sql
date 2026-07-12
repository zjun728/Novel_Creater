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

CREATE TABLE corpus_sources (
  id CHAR(36) PRIMARY KEY,
  source_key VARCHAR(200) NOT NULL,
  revision INT NOT NULL,
  relative_path VARCHAR(2048) NOT NULL,
  title VARCHAR(300) NOT NULL,
  author VARCHAR(200) NOT NULL,
  source_hash CHAR(64) NOT NULL,
  file_size BIGINT NOT NULL,
  encoding VARCHAR(64) NOT NULL,
  parser_version VARCHAR(64) NOT NULL,
  normalizer_version VARCHAR(64) NOT NULL,
  fragmenter_version VARCHAR(64) NOT NULL,
  index_version VARCHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  public_error_code VARCHAR(64) NULL,
  imported_at BIGINT NOT NULL,
  analyzed_at BIGINT NULL,
  UNIQUE KEY uq_corpus_source_revision (source_key, revision),
  UNIQUE KEY uq_corpus_source_id_revision (id, revision),
  UNIQUE KEY uq_corpus_source_import (source_hash, parser_version, normalizer_version, fragmenter_version, index_version),
  CHECK (revision > 0),
  CHECK (file_size >= 0),
  CHECK (status IN ('imported','analyzed','failed')),
  CHECK (
    (status = 'imported' AND public_error_code IS NULL AND analyzed_at IS NULL)
    OR (status = 'analyzed' AND public_error_code IS NULL
      AND analyzed_at IS NOT NULL AND analyzed_at >= imported_at)
    OR (status = 'failed' AND public_error_code IS NOT NULL AND analyzed_at IS NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE corpus_chapters (
  id CHAR(36) PRIMARY KEY,
  corpus_source_id CHAR(36) NOT NULL,
  chapter_order INT NOT NULL,
  title VARCHAR(300) NOT NULL,
  raw_byte_start BIGINT NOT NULL,
  raw_byte_end BIGINT NOT NULL,
  normalized_char_start BIGINT NOT NULL,
  normalized_char_end BIGINT NOT NULL,
  normalized_text LONGTEXT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_corpus_chapter_order (corpus_source_id, chapter_order),
  FOREIGN KEY (corpus_source_id) REFERENCES corpus_sources(id) ON DELETE RESTRICT,
  CHECK (chapter_order > 0),
  CHECK (raw_byte_start >= 0 AND raw_byte_end >= raw_byte_start),
  CHECK (normalized_char_start >= 0 AND normalized_char_end >= normalized_char_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE corpus_fragments (
  id CHAR(36) PRIMARY KEY,
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
  FOREIGN KEY (corpus_chapter_id) REFERENCES corpus_chapters(id) ON DELETE RESTRICT,
  CHECK (fragment_order > 0),
  CHECK (chapter_char_start >= 0 AND chapter_char_end > chapter_char_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE corpus_import_runs (
  id CHAR(36) PRIMARY KEY,
  idempotency_key CHAR(64) NOT NULL,
  request_hash CHAR(64) NOT NULL,
  relative_path VARCHAR(2048) NOT NULL,
  source_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  corpus_source_id CHAR(36) NULL,
  public_error_code VARCHAR(64) NULL,
  parser_versions_json JSON NOT NULL,
  created_at BIGINT NOT NULL,
  completed_at BIGINT NULL,
  UNIQUE KEY uq_corpus_import_idempotency (idempotency_key),
  FOREIGN KEY (corpus_source_id) REFERENCES corpus_sources(id) ON DELETE RESTRICT,
  CHECK (status IN ('reserved','running','succeeded','failed')),
  CHECK (
    (status IN ('reserved','running') AND corpus_source_id IS NULL
      AND public_error_code IS NULL AND completed_at IS NULL)
    OR (status = 'succeeded' AND corpus_source_id IS NOT NULL
      AND public_error_code IS NULL AND completed_at IS NOT NULL)
    OR (status = 'failed' AND corpus_source_id IS NULL
      AND public_error_code IS NOT NULL AND completed_at IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
