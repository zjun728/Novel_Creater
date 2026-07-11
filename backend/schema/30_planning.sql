CREATE TABLE volume_plans (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  volume_num INT NOT NULL,
  title VARCHAR(200) NOT NULL,
  direction_json JSON NOT NULL,
  revision INT NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_volume_num (project_id, volume_num),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CHECK (volume_num > 0),
  CHECK (revision > 0),
  CHECK (status IN ('planned','active','completed','cancelled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE story_blocks (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  volume_plan_id CHAR(36) NOT NULL,
  block_num INT NOT NULL,
  title VARCHAR(200) NOT NULL,
  goal_json JSON NOT NULL,
  revision INT NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_block_num (project_id, block_num),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (volume_plan_id) REFERENCES volume_plans(id) ON DELETE CASCADE,
  CHECK (block_num > 0),
  CHECK (revision > 0),
  CHECK (status IN ('planned','active','completed','failed','redirected'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE story_stages (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  story_block_id CHAR(36) NOT NULL,
  stage_order INT NOT NULL,
  title VARCHAR(200) NOT NULL,
  plan_json JSON NOT NULL,
  revision INT NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_stage_order (story_block_id, stage_order),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (story_block_id) REFERENCES story_blocks(id) ON DELETE CASCADE,
  CHECK (stage_order > 0),
  CHECK (revision > 0),
  CHECK (status IN ('pending','in_progress','completed','cancelled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE scene_tasks (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  story_stage_id CHAR(36) NOT NULL,
  task_order INT NOT NULL,
  task_json JSON NOT NULL,
  revision INT NOT NULL,
  status VARCHAR(24) NOT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_scene_order (story_stage_id, task_order),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (story_stage_id) REFERENCES story_stages(id) ON DELETE CASCADE,
  CHECK (task_order > 0),
  CHECK (revision > 0),
  CHECK (status IN ('pending','in_progress','completed','cancelled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement
