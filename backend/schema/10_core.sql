CREATE TABLE projects (
  id CHAR(36) PRIMARY KEY,
  title VARCHAR(200) NOT NULL,
  status VARCHAR(24) NOT NULL,
  current_chapter INT NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  CHECK (status IN ('drafting','active','completed','archived')),
  CHECK (current_chapter >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE creative_seeds (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  title VARCHAR(200) NOT NULL,
  premise_json JSON NOT NULL,
  content_hash CHAR(64) NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_seed_title (project_id, title),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CHECK (status IN ('candidate','selected','archived'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE project_selected_seeds (
  project_id CHAR(36) PRIMARY KEY,
  seed_id CHAR(36) NOT NULL,
  selected_at BIGINT NOT NULL,
  UNIQUE KEY uq_selected_seed (seed_id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (seed_id) REFERENCES creative_seeds(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE provider_profiles (
  id CHAR(36) PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  provider_type VARCHAR(64) NOT NULL,
  model_name VARCHAR(160) NOT NULL,
  base_url VARCHAR(2048) NOT NULL,
  api_key TEXT NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  sort_order INT NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_provider_name (name),
  CHECK (enabled IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE task_model_bindings (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_binding_project (project_id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE task_model_binding_items (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  binding_id CHAR(36) NOT NULL,
  task_key VARCHAR(100) NOT NULL,
  provider_id CHAR(36) NOT NULL,
  model_name VARCHAR(160) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_binding_task (binding_id, task_key),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (binding_id) REFERENCES task_model_bindings(id) ON DELETE CASCADE,
  FOREIGN KEY (provider_id) REFERENCES provider_profiles(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement
