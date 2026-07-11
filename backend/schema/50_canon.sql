CREATE TABLE canon_entities (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  entity_type VARCHAR(24) NOT NULL,
  canonical_name VARCHAR(200) NOT NULL,
  normalized_name VARCHAR(200) NOT NULL,
  created_revision INT NOT NULL,
  created_at BIGINT NOT NULL,
  KEY ix_entity_name (project_id, entity_type, normalized_name),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CHECK (entity_type IN ('person','organization','place','item')),
  CHECK (created_revision >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE entity_aliases (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  entity_id CHAR(36) NOT NULL,
  alias VARCHAR(200) NOT NULL,
  normalized_alias VARCHAR(200) NOT NULL,
  created_revision INT NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_entity_alias (project_id, entity_id, normalized_alias),
  KEY ix_alias_lookup (project_id, normalized_alias),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (entity_id) REFERENCES canon_entities(id) ON DELETE CASCADE,
  CHECK (created_revision >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE canon_revisions (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  revision_number INT NOT NULL,
  parent_revision_number INT NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  source_type VARCHAR(32) NOT NULL,
  source_id CHAR(36) NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_revision_number (project_id, revision_number),
  UNIQUE KEY uq_revision_idempotency (project_id, idempotency_key),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CHECK (revision_number >= 0),
  CHECK (parent_revision_number >= 0),
  CHECK (source_type IN ('bootstrap','finalization','manual_test'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement

CREATE TABLE canon_events (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  revision_id CHAR(36) NOT NULL,
  revision_number INT NOT NULL,
  event_order INT NOT NULL,
  entity_id CHAR(36) NULL,
  fact_kind VARCHAR(24) NOT NULL,
  field_path VARCHAR(200) NOT NULL,
  value_json JSON NOT NULL,
  evidence_json JSON NOT NULL,
  effective_start_chapter INT NULL,
  effective_end_chapter INT NULL,
  assertion_operator VARCHAR(16) NOT NULL,
  value_cardinality VARCHAR(12) NOT NULL,
  confirmation_status VARCHAR(16) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_event_order (project_id, revision_number, event_order),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (revision_id) REFERENCES canon_revisions(id) ON DELETE RESTRICT,
  FOREIGN KEY (entity_id) REFERENCES canon_entities(id) ON DELETE RESTRICT,
  CHECK (revision_number >= 0),
  CHECK (event_order > 0),
  CHECK (fact_kind IN ('stable_definition','dynamic_event','claim')),
  CHECK (confirmation_status IN ('confirmed','rejected')),
  CHECK (assertion_operator IN ('equals','not_equals')),
  CHECK (value_cardinality IN ('single','multi')),
  CHECK (effective_start_chapter IS NULL OR effective_start_chapter > 0),
  CHECK (effective_end_chapter IS NULL OR effective_end_chapter > 0),
  CHECK (effective_end_chapter IS NULL OR effective_start_chapter IS NULL OR effective_end_chapter >= effective_start_chapter)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
