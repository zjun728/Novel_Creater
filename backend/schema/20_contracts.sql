CREATE TABLE creation_contracts (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  revision INT NOT NULL,
  payload_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_creation_contract_project (project_id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CHECK (revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE style_contracts (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  revision INT NOT NULL,
  payload_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_style_contract_project (project_id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CHECK (revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE contract_asset_refs (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  creation_contract_id CHAR(36) NOT NULL,
  asset_type VARCHAR(32) NOT NULL,
  asset_id CHAR(36) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_contract_asset (creation_contract_id, asset_type, asset_id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (creation_contract_id) REFERENCES creation_contracts(id) ON DELETE CASCADE,
  CHECK (asset_type IN ('style_template','experience_card','corpus_source'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement
