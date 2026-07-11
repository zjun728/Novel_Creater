CREATE TABLE current_state_projections (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  revision_number INT NOT NULL,
  entity_id CHAR(36) NOT NULL,
  field_path VARCHAR(200) NOT NULL,
  payload_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_current_state_key (project_id, revision_number, entity_id, field_path),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (entity_id) REFERENCES canon_entities(id) ON DELETE RESTRICT,
  CHECK (revision_number >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE memory_views (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  revision_number INT NOT NULL,
  entity_id CHAR(36) NOT NULL,
  memory_key VARCHAR(200) NOT NULL,
  payload_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_memory_key (project_id, revision_number, entity_id, memory_key),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (entity_id) REFERENCES canon_entities(id) ON DELETE RESTRICT,
  CHECK (revision_number >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE arc_projections (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  revision_number INT NOT NULL,
  entity_id CHAR(36) NOT NULL,
  arc_key VARCHAR(200) NOT NULL,
  payload_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_arc_key (project_id, revision_number, entity_id, arc_key),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (entity_id) REFERENCES canon_entities(id) ON DELETE RESTRICT,
  CHECK (revision_number >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE plot_thread_projections (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  revision_number INT NOT NULL,
  plot_thread_key VARCHAR(200) NOT NULL,
  payload_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_plot_thread_key (project_id, revision_number, plot_thread_key),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CHECK (revision_number >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE projection_heads (
  project_id CHAR(36) PRIMARY KEY,
  canon_revision_number INT NOT NULL,
  projection_revision_number INT NOT NULL,
  updated_at BIGINT NOT NULL,
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CHECK (canon_revision_number >= 0),
  CHECK (projection_revision_number >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement
